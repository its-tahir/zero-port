"""Termination tests use real child processes, including a real listener.

Child processes report their own PID on stdout rather than trusting
``Popen.pid``: on Windows a virtual-environment ``python.exe`` is a launcher
that runs the real interpreter as a separate process, and the socket belongs to
that one.
"""

import subprocess
import sys
import time

import psutil
import pytest

from app.models.port_info import PortEntry, ProcessInfo, TerminationOutcome
from app.services.port_scanner import PortScanner
from app.services.process_inspector import ProcessInspector
from app.services.process_terminator import ProcessTerminator

SLEEPER = "import os, time; print(os.getpid(), flush=True); time.sleep(60)"

LISTENER = (
    "import os, socket, time\n"
    "s = socket.socket()\n"
    "s.bind(('127.0.0.1', 0))\n"
    "s.listen(1)\n"
    "print(os.getpid(), s.getsockname()[1], flush=True)\n"
    "time.sleep(60)\n"
)


class Child:
    """A real child process that tells us its own PID (and optionally a port)."""

    def __init__(self, script: str) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
        )
        fields = self._proc.stdout.readline().split()
        self.pid = int(fields[0])
        self.port = int(fields[1]) if len(fields) > 1 else None

    @property
    def alive(self) -> bool:
        return psutil.pid_exists(self.pid)

    def wait_until_gone(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.alive:
                return True
            time.sleep(0.05)
        return not self.alive

    def kill(self) -> None:
        try:
            psutil.Process(self.pid).kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        self.wait_until_gone()

    def close(self) -> None:
        self.kill()
        if self._proc.poll() is None:
            self._proc.kill()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if self._proc.stdout:
            self._proc.stdout.close()


@pytest.fixture
def terminator():
    return ProcessTerminator(ProcessInspector(), graceful_timeout=5.0, force_timeout=3.0)


@pytest.fixture
def inspector():
    return ProcessInspector()


@pytest.fixture
def sleeper():
    child = Child(SLEEPER)
    yield child
    child.close()


@pytest.fixture
def listener():
    child = Child(LISTENER)
    yield child
    child.close()


def test_a_running_child_is_stopped(terminator, inspector, sleeper):
    result = terminator.stop(inspector.inspect(sleeper.pid))

    assert result.outcome is TerminationOutcome.STOPPED, result.message
    assert result.is_success
    assert sleeper.wait_until_gone()


def test_stopping_a_process_releases_its_port(terminator, listener):
    scanner = PortScanner()

    before = [e for e in scanner.scan() if e.port == listener.port]
    assert before, "the child's port was never observed"
    assert before[0].pid == listener.pid
    assert before[0].can_stop

    result = terminator.stop_entry(before[0])
    assert result.outcome is TerminationOutcome.STOPPED, result.message

    assert listener.wait_until_gone()
    after = [e for e in scanner.scan() if e.port == listener.port]
    assert not after, "the port is still listed after termination"


def test_a_process_that_already_exited_is_reported_not_retried(terminator, inspector):
    child = Child(SLEEPER)
    info = inspector.inspect(child.pid)
    child.kill()
    assert child.wait_until_gone()

    try:
        result = terminator.stop(info)
        assert result.outcome is TerminationOutcome.ALREADY_EXITED
        assert result.is_success
    finally:
        child.close()


def test_a_recycled_pid_is_never_terminated(terminator, inspector, sleeper):
    real = inspector.inspect(sleeper.pid)
    stale = ProcessInfo(
        pid=real.pid, name=real.name, create_time=(real.create_time or 0) - 900
    )

    result = terminator.stop(stale)

    assert result.outcome is TerminationOutcome.PROCESS_CHANGED
    assert sleeper.alive, "an unrelated process was terminated"


def test_a_renamed_pid_is_never_terminated(terminator, inspector, sleeper):
    real = inspector.inspect(sleeper.pid)
    stale = ProcessInfo(pid=real.pid, name="notepad.exe", create_time=real.create_time)

    result = terminator.stop(stale)

    assert result.outcome is TerminationOutcome.PROCESS_CHANGED
    assert sleeper.alive


def test_protected_entries_are_refused_before_anything_happens(terminator):
    entry = PortEntry(
        port=445,
        protocol="TCP",
        address="ALL",
        process=ProcessInfo(pid=4, name="System", create_time=1.0),
        description="Windows file sharing (SMB)",
        protected=True,
        protection_reason="Windows kernel process.",
    )
    result = terminator.stop_entry(entry)
    assert result.outcome is TerminationOutcome.PROTECTED
    assert "kernel" in result.message.lower()


def test_the_kernel_is_refused_even_without_the_protected_flag(terminator):
    result = terminator.stop(ProcessInfo(pid=4, name="System", create_time=1.0))
    assert result.outcome in (
        TerminationOutcome.PROTECTED,
        TerminationOutcome.ACCESS_DENIED,
        TerminationOutcome.PROCESS_CHANGED,
    )
    assert psutil.pid_exists(4)


def test_a_missing_pid_is_rejected(terminator):
    result = terminator.stop(ProcessInfo(pid=-1, name=""))
    assert result.outcome is TerminationOutcome.INVALID


def test_access_denied_produces_the_administrator_hint(
    terminator, inspector, sleeper, monkeypatch
):
    def denied(self):
        raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(psutil.Process, "terminate", denied)
    monkeypatch.setattr(psutil.Process, "kill", denied)

    result = terminator.stop(inspector.inspect(sleeper.pid))

    assert result.outcome is TerminationOutcome.ACCESS_DENIED
    assert "administrator" in result.message.lower()
    assert sleeper.alive


def test_a_stubborn_process_is_force_stopped(terminator, inspector, sleeper, monkeypatch):
    """A terminate() that does nothing must escalate to kill()."""
    monkeypatch.setattr(psutil.Process, "terminate", lambda self: None)
    terminator.graceful_timeout = 0.4

    result = terminator.stop(inspector.inspect(sleeper.pid))

    assert result.outcome is TerminationOutcome.STOPPED
    assert result.forced
    assert sleeper.wait_until_gone()


def test_an_unkillable_process_times_out_instead_of_hanging(
    terminator, inspector, sleeper, monkeypatch
):
    monkeypatch.setattr(psutil.Process, "terminate", lambda self: None)
    monkeypatch.setattr(psutil.Process, "kill", lambda self: None)
    terminator.graceful_timeout = 0.3
    terminator.force_timeout = 0.3

    result = terminator.stop(inspector.inspect(sleeper.pid))

    assert result.outcome is TerminationOutcome.TIMED_OUT
    assert not result.is_success
    assert sleeper.alive
