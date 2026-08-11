"""PID -> process metadata.

Two things matter here. First, a process can vanish between any two calls, so
every lookup degrades to a partial answer instead of raising. Second, a scan
touches the same PIDs repeatedly, so results are cached per scan pass keyed on
``(pid, create_time)`` — the cache can never hand back a recycled PID's data.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import psutil

from app.models.port_info import ProcessInfo

_CMDLINE_LIMIT = 2048


class ProcessInspector:
    """Resolves PIDs to :class:`ProcessInfo`, tolerating every failure mode."""

    def __init__(self) -> None:
        self._cache: Dict[Tuple[int, Optional[float]], ProcessInfo] = {}

    def reset_cache(self) -> None:
        """Called at the start of each scan pass so data never goes stale."""
        self._cache.clear()

    def inspect(self, pid: Optional[int]) -> ProcessInfo:
        if pid is None or pid <= 0:
            return ProcessInfo.unknown(pid)

        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return ProcessInfo(pid=pid, name="", exists=False, accessible=False)
        except (psutil.AccessDenied, OSError, ValueError):
            return ProcessInfo(pid=pid, name="", exists=True, accessible=False)

        return self.inspect_process(proc)

    def inspect_process(self, proc: psutil.Process) -> ProcessInfo:
        pid = proc.pid
        create_time = self._safe_create_time(proc)

        key = (pid, create_time)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        name = ""
        exe: Optional[str] = None
        cmdline: Optional[str] = None
        username: Optional[str] = None
        accessible = True
        exists = True

        try:
            name = proc.name() or ""
        except psutil.NoSuchProcess:
            exists = False
        except (psutil.AccessDenied, OSError):
            accessible = False

        if exists:
            exe, denied = self._safe(proc.exe)
            accessible = accessible and not denied

            raw_cmdline, denied = self._safe(proc.cmdline)
            accessible = accessible and not denied
            cmdline = self._join_cmdline(raw_cmdline)

            username, denied = self._safe(proc.username)
            accessible = accessible and not denied

            # A name is the one field we really want; fall back to the exe.
            if not name and exe:
                name = exe.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

        info = ProcessInfo(
            pid=pid,
            name=name,
            exe=exe or None,
            cmdline=cmdline,
            username=username or None,
            create_time=create_time,
            exists=exists,
            accessible=accessible,
        )
        self._cache[key] = info
        return info

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _safe(getter):
        """Call a psutil accessor. Returns ``(value, access_denied)``."""
        try:
            return getter(), False
        except psutil.AccessDenied:
            return None, True
        except (psutil.NoSuchProcess, psutil.ZombieProcess, OSError, ValueError):
            return None, False

    @staticmethod
    def _safe_create_time(proc: psutil.Process) -> Optional[float]:
        try:
            return proc.create_time()
        except (psutil.Error, OSError, ValueError):
            return None

    @staticmethod
    def _join_cmdline(parts) -> Optional[str]:
        if not parts:
            return None
        try:
            joined = " ".join(str(p) for p in parts if p is not None)
        except TypeError:
            return None
        joined = joined.strip()
        if not joined:
            return None
        if len(joined) > _CMDLINE_LIMIT:
            joined = joined[:_CMDLINE_LIMIT] + "..."
        return joined

    # ------------------------------------------------------------ validation

    def verify(self, expected: ProcessInfo) -> Tuple[bool, Optional[ProcessInfo]]:
        """Re-read a process and confirm it is still the same one.

        Returns ``(still_the_same, current_info_or_None)``. ``None`` means the
        process is gone. This is the gate every termination passes through.
        """
        if expected.pid <= 0:
            return False, None

        try:
            proc = psutil.Process(expected.pid)
        except psutil.NoSuchProcess:
            return False, None
        except (psutil.AccessDenied, OSError, ValueError):
            # Present but unreadable — we cannot confirm identity, so refuse.
            return False, ProcessInfo(
                pid=expected.pid, name=expected.name, exists=True, accessible=False
            )

        current = self.inspect_process(proc)

        if expected.create_time is not None and current.create_time is not None:
            if abs(expected.create_time - current.create_time) > 0.001:
                return False, current

        if expected.name and current.name and expected.name != current.name:
            return False, current

        return True, current
