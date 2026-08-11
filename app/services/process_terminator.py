"""Stop a process that owns a port — carefully.

Every path through this module revalidates identity before it acts. A PID read
during a scan may belong to something else by the time the user clicks STOP,
and killing the wrong process is the one failure this tool must never have.

No shell commands are used anywhere. Only direct process APIs.
"""

from __future__ import annotations

from typing import Optional

import psutil

from app.models.port_info import (
    PortEntry,
    ProcessInfo,
    TerminationOutcome,
    TerminationResult,
)
from app.services.process_inspector import ProcessInspector
from app.utils.windows import is_protected_process

GRACEFUL_TIMEOUT = 3.0
FORCE_TIMEOUT = 2.0


class ProcessTerminator:
    """Graceful-then-forced termination with full revalidation."""

    def __init__(
        self,
        inspector: Optional[ProcessInspector] = None,
        graceful_timeout: float = GRACEFUL_TIMEOUT,
        force_timeout: float = FORCE_TIMEOUT,
    ) -> None:
        self.inspector = inspector or ProcessInspector()
        self.graceful_timeout = graceful_timeout
        self.force_timeout = force_timeout

    def stop_entry(self, entry: PortEntry) -> TerminationResult:
        """Stop the process behind a port row the user selected."""
        if entry.protected:
            return TerminationResult(
                TerminationOutcome.PROTECTED,
                entry.protection_reason
                or "This is a protected Windows process and will not be stopped.",
            )
        return self.stop(entry.process)

    def stop(self, expected: ProcessInfo) -> TerminationResult:
        if expected.pid <= 0:
            return TerminationResult(
                TerminationOutcome.INVALID,
                "No process is associated with this port.",
            )

        # 1 + 2. Confirm the PID still refers to the same process.
        self.inspector.reset_cache()
        same, current = self.inspector.verify(expected)

        if current is None:
            return TerminationResult(
                TerminationOutcome.ALREADY_EXITED,
                "The process has already exited.",
            )

        if not same:
            if not current.accessible:
                return TerminationResult(
                    TerminationOutcome.ACCESS_DENIED,
                    "This process cannot be inspected, so ZeroPort will not stop it. "
                    "It may require administrator privileges.",
                )
            return TerminationResult(
                TerminationOutcome.PROCESS_CHANGED,
                f"PID {expected.pid} now belongs to a different process "
                f"({current.display_name}). Nothing was stopped — refresh and try again.",
            )

        # 3. Protection is re-evaluated against the freshly read process.
        protected, reason = is_protected_process(current)
        if protected:
            return TerminationResult(
                TerminationOutcome.PROTECTED,
                reason or "This is a protected Windows process and will not be stopped.",
            )

        return self._terminate(current)

    # ------------------------------------------------------------------ steps

    def _terminate(self, info: ProcessInfo) -> TerminationResult:
        try:
            proc = psutil.Process(info.pid)
        except psutil.NoSuchProcess:
            return TerminationResult(
                TerminationOutcome.ALREADY_EXITED,
                "The process exited before it could be stopped.",
            )
        except (psutil.Error, OSError, ValueError) as exc:
            return TerminationResult(
                TerminationOutcome.FAILED, f"Could not open the process: {exc}"
            )

        # Guard once more against a PID recycled between verify() and here.
        if info.create_time is not None:
            try:
                if abs(proc.create_time() - info.create_time) > 0.001:
                    return TerminationResult(
                        TerminationOutcome.PROCESS_CHANGED,
                        f"PID {info.pid} was reused by another process. Nothing was stopped.",
                    )
            except psutil.NoSuchProcess:
                return TerminationResult(
                    TerminationOutcome.ALREADY_EXITED,
                    "The process exited before it could be stopped.",
                )
            except (psutil.Error, OSError):
                pass

        # 3. Ask politely first.
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            return TerminationResult(
                TerminationOutcome.ALREADY_EXITED,
                "The process exited before it could be stopped.",
            )
        except psutil.AccessDenied:
            return self._access_denied(info)
        except (psutil.Error, OSError) as exc:
            return TerminationResult(
                TerminationOutcome.FAILED, f"Could not stop the process: {exc}"
            )

        # 4 + 5. Give it a moment, then check.
        if self._wait(proc, self.graceful_timeout):
            return TerminationResult(
                TerminationOutcome.STOPPED, f"{info.display_name} was stopped."
            )

        # 6. Still alive — escalate deliberately, not automatically-forever.
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            return TerminationResult(
                TerminationOutcome.STOPPED,
                f"{info.display_name} was stopped.",
            )
        except psutil.AccessDenied:
            return self._access_denied(info)
        except (psutil.Error, OSError) as exc:
            return TerminationResult(
                TerminationOutcome.FAILED, f"Could not force-stop the process: {exc}"
            )

        if self._wait(proc, self.force_timeout):
            return TerminationResult(
                TerminationOutcome.STOPPED,
                f"{info.display_name} was force-stopped.",
                forced=True,
            )

        return TerminationResult(
            TerminationOutcome.TIMED_OUT,
            f"{info.display_name} did not exit. It may be unresponsive or protected "
            "by the system.",
            forced=True,
        )

    @staticmethod
    def _wait(proc: psutil.Process, timeout: float) -> bool:
        """True if the process is gone within ``timeout`` seconds."""
        try:
            proc.wait(timeout=timeout)
            return True
        except psutil.TimeoutExpired:
            return not proc.is_running()
        except psutil.NoSuchProcess:
            return True
        except (psutil.Error, OSError):
            # If we cannot wait, fall back to a direct liveness check.
            try:
                return not psutil.pid_exists(proc.pid)
            except OSError:
                return False

    @staticmethod
    def _access_denied(info: ProcessInfo) -> TerminationResult:
        return TerminationResult(
            TerminationOutcome.ACCESS_DENIED,
            f"Unable to stop {info.display_name}.\n\n"
            "The process may require administrator privileges. "
            "Try running ZeroPort as Administrator.",
        )
