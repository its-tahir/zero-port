import os
import subprocess
import sys

import psutil
import pytest

from app.models.port_info import ProcessInfo
from app.services.process_inspector import ProcessInspector


@pytest.fixture
def inspector():
    return ProcessInspector()


def test_current_process_is_fully_described(inspector):
    info = inspector.inspect(os.getpid())
    assert info.pid == os.getpid()
    assert "python" in info.name.lower()
    assert info.exe
    assert info.cmdline
    assert info.create_time is not None
    assert info.exists and info.accessible


def test_missing_pid_is_reported_not_raised(inspector):
    dead_pid = _find_unused_pid()
    info = inspector.inspect(dead_pid)
    assert info.pid == dead_pid
    assert not info.exists
    assert info.display_name == f"PID {dead_pid}"


@pytest.mark.parametrize("pid", [None, 0, -1])
def test_absent_pids_produce_an_unknown_process(inspector, pid):
    info = inspector.inspect(pid)
    assert not info.exists
    assert not info.accessible


def test_results_are_cached_within_a_pass(inspector):
    first = inspector.inspect(os.getpid())
    second = inspector.inspect(os.getpid())
    assert first is second
    inspector.reset_cache()
    assert inspector.inspect(os.getpid()) is not first


def test_very_long_command_lines_are_truncated(inspector, monkeypatch):
    long_args = ["python"] + ["--flag=" + "x" * 200] * 40
    monkeypatch.setattr(psutil.Process, "cmdline", lambda self: long_args)
    info = inspector.inspect(os.getpid())
    assert len(info.cmdline) <= 2051
    assert info.cmdline.endswith("...")


def test_verify_accepts_the_same_process(inspector):
    info = inspector.inspect(os.getpid())
    same, current = inspector.verify(info)
    assert same
    assert current.pid == info.pid


def test_verify_rejects_a_recycled_pid(inspector):
    info = inspector.inspect(os.getpid())
    impostor = ProcessInfo(
        pid=info.pid,
        name=info.name,
        create_time=(info.create_time or 0) - 500,
    )
    same, current = inspector.verify(impostor)
    assert not same
    assert current is not None


def test_verify_rejects_a_different_name_on_the_same_pid(inspector):
    info = inspector.inspect(os.getpid())
    impostor = ProcessInfo(
        pid=info.pid, name="definitely-not-python.exe", create_time=info.create_time
    )
    same, _current = inspector.verify(impostor)
    assert not same


def test_verify_reports_a_vanished_process(inspector):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    info = ProcessInfo(pid=child.pid, name="python.exe", create_time=1.0)
    same, current = inspector.verify(info)
    assert not same
    assert current is None


def test_access_denied_processes_are_marked_inaccessible(inspector, monkeypatch):
    monkeypatch.setattr(
        psutil.Process, "exe", lambda self: (_ for _ in ()).throw(psutil.AccessDenied())
    )
    info = inspector.inspect(os.getpid())
    assert info.exists
    assert not info.accessible
    assert info.name  # the name still came through


def _find_unused_pid() -> int:
    for candidate in range(999_000, 1_000_000):
        if not psutil.pid_exists(candidate):
            return candidate
    raise RuntimeError("no free PID found")
