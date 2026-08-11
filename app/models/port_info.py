"""Immutable value objects shared between the service layer and the UI.

Nothing in here touches the operating system. These types are what the services
produce and what the UI consumes, which keeps the boundary between them honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


@dataclass(frozen=True)
class ProcessInfo:
    """What we managed to learn about the process behind a socket.

    A PID on its own is not an identity — Windows reuses them. ``create_time``
    is the second half of the fingerprint and is what makes it safe to act on a
    PID we read a few seconds ago.
    """

    pid: int
    name: str
    exe: Optional[str] = None
    cmdline: Optional[str] = None
    username: Optional[str] = None
    create_time: Optional[float] = None
    exists: bool = True
    accessible: bool = True

    @property
    def fingerprint(self) -> Tuple[int, Optional[float], str]:
        return (self.pid, self.create_time, self.name)

    @property
    def display_name(self) -> str:
        return self.name or f"PID {self.pid}"

    @staticmethod
    def unknown(pid: Optional[int]) -> "ProcessInfo":
        """Used when the socket has no owning PID we can see at all."""
        return ProcessInfo(
            pid=pid if pid is not None else -1,
            name="",
            exists=False,
            accessible=False,
        )


@dataclass(frozen=True)
class PortEntry:
    """One listening TCP endpoint, resolved and ready to render."""

    port: int
    protocol: str
    address: str
    process: ProcessInfo
    description: str
    protected: bool = False
    protection_reason: str = ""
    sibling_ports: Tuple[int, ...] = field(default_factory=tuple)

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def has_pid(self) -> bool:
        return self.process.pid > 0

    @property
    def status(self) -> str:
        if not self.has_pid:
            return "UNKNOWN"
        if not self.process.exists:
            return "EXITED"
        return "RUNNING"

    @property
    def can_stop(self) -> bool:
        """Whether the UI should offer termination for this row."""
        return self.has_pid and self.process.exists and not self.protected

    @property
    def shares_process(self) -> bool:
        return len(self.sibling_ports) > 0

    @property
    def owned_ports(self) -> Tuple[int, ...]:
        return tuple(sorted({self.port, *self.sibling_ports}))

    @property
    def search_blob(self) -> str:
        """Everything the search box is allowed to match against."""
        parts = [
            str(self.port),
            self.protocol,
            self.address,
            str(self.pid) if self.has_pid else "",
            self.process.name,
            self.description,
            self.status,
        ]
        return " ".join(p for p in parts if p).lower()


class TerminationOutcome(Enum):
    """Every way a stop request can end. The UI maps these to messages."""

    STOPPED = "stopped"
    ALREADY_EXITED = "already_exited"
    PROCESS_CHANGED = "process_changed"
    PROTECTED = "protected"
    ACCESS_DENIED = "access_denied"
    TIMED_OUT = "timed_out"
    INVALID = "invalid"
    FAILED = "failed"

    @property
    def is_success(self) -> bool:
        return self in (TerminationOutcome.STOPPED, TerminationOutcome.ALREADY_EXITED)


@dataclass(frozen=True)
class TerminationResult:
    outcome: TerminationOutcome
    message: str
    forced: bool = False

    @property
    def is_success(self) -> bool:
        return self.outcome.is_success
