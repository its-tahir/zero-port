"""Discover listening TCP endpoints and assemble them into :class:`PortEntry`.

One pass does the whole job: read the connection table once, resolve each
distinct PID once, then decorate every row with a description, protection
verdict and its sibling ports.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

import psutil

from app.models.port_info import PortEntry, ProcessInfo
from app.services.description_resolver import DescriptionResolver
from app.services.process_inspector import ProcessInspector
from app.utils.windows import format_address, is_protected_process


class ScanError(RuntimeError):
    """Raised when the connection table itself cannot be read."""


class PortScanner:
    """Produces the list of listening TCP ports on the local machine."""

    def __init__(
        self,
        inspector: Optional[ProcessInspector] = None,
        resolver: Optional[DescriptionResolver] = None,
    ) -> None:
        self.inspector = inspector or ProcessInspector()
        self.resolver = resolver or DescriptionResolver()

    def scan(self) -> List[PortEntry]:
        connections = self._read_connections()
        listening = self._filter_listening(connections)
        return self._build_entries(listening)

    # ------------------------------------------------------------------ steps

    @staticmethod
    def _read_connections() -> Iterable:
        try:
            return psutil.net_connections(kind="tcp")
        except psutil.AccessDenied as exc:
            raise ScanError(
                "Windows denied access to the connection table. "
                "Some processes may require elevated permissions."
            ) from exc
        except (psutil.Error, OSError, RuntimeError) as exc:
            raise ScanError(f"Could not read local network state: {exc}") from exc

    @staticmethod
    def _filter_listening(connections: Iterable) -> List[Tuple]:
        """Keep listening sockets, de-duplicated per (port, address, pid).

        Windows reports IPv4 and IPv6 wildcard listeners for the same service
        as separate rows; those are genuinely separate endpoints, so both are
        kept. Exact duplicates are not.
        """
        seen: Set[Tuple[int, str, Optional[int], str]] = set()
        rows: List[Tuple] = []

        for conn in connections:
            if conn.status != psutil.CONN_LISTEN:
                continue
            if not conn.laddr:
                continue

            try:
                port = int(conn.laddr.port)
                ip = str(conn.laddr.ip)
            except (AttributeError, TypeError, ValueError):
                continue

            protocol = "TCP6" if ":" in ip else "TCP"
            key = (port, ip, conn.pid, protocol)
            if key in seen:
                continue
            seen.add(key)
            rows.append((port, ip, conn.pid, protocol))

        return rows

    def _build_entries(self, rows: List[Tuple]) -> List[PortEntry]:
        self.inspector.reset_cache()

        # Resolve each PID once, not once per socket.
        pids = {pid for _, _, pid, _ in rows if pid}
        processes: Dict[int, ProcessInfo] = {
            pid: self.inspector.inspect(pid) for pid in pids
        }

        ports_by_pid: Dict[int, Set[int]] = defaultdict(set)
        for port, _ip, pid, _protocol in rows:
            if pid:
                ports_by_pid[pid].add(port)

        # One row per (port, owner). The IPv4 and IPv6 sockets of the same
        # service are one answer, not two identical-looking rows.
        grouped: "OrderedDict[Tuple[int, Optional[int]], List[Tuple[str, str]]]" = (
            OrderedDict()
        )
        for port, ip, pid, protocol in rows:
            grouped.setdefault((port, pid), []).append((ip, protocol))

        entries: List[PortEntry] = []
        for (port, pid), bindings in grouped.items():
            info = processes.get(pid) if pid else None
            if info is None:
                info = ProcessInfo.unknown(pid)

            protected, reason = is_protected_process(info)
            siblings = tuple(sorted(ports_by_pid.get(pid, set()) - {port})) if pid else ()

            entries.append(
                PortEntry(
                    port=port,
                    protocol=self._merge_protocols(bindings),
                    address=self._merge_addresses(bindings),
                    process=info,
                    description=self.resolver.resolve(port, info),
                    protected=protected,
                    protection_reason=reason,
                    sibling_ports=siblings,
                    bindings=tuple(bindings),
                )
            )

        entries.sort(key=lambda e: (e.port, e.address, e.pid))
        return entries

    @staticmethod
    def _merge_protocols(bindings: List[Tuple[str, str]]) -> str:
        protocols = sorted({protocol for _ip, protocol in bindings})
        return " · ".join(protocols)

    @staticmethod
    def _merge_addresses(bindings: List[Tuple[str, str]]) -> str:
        """A wildcard binding subsumes the rest — it already means everything."""
        formatted: List[str] = []
        for ip, _protocol in bindings:
            label = format_address(ip)
            if label == "ALL":
                return "ALL"
            if label not in formatted:
                formatted.append(label)
        return ", ".join(formatted)
