import os

import pytest

from app.models.port_info import ProcessInfo
from app.utils.windows import format_address, is_protected_process

SYSTEM32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def test_the_kernel_is_protected():
    protected, reason = is_protected_process(ProcessInfo(pid=4, name="System"))
    assert protected
    assert reason


def test_sockets_without_an_owner_are_protected():
    protected, _reason = is_protected_process(ProcessInfo.unknown(None))
    assert protected


@pytest.mark.parametrize(
    "name", ["svchost.exe", "lsass.exe", "csrss.exe", "services.exe", "winlogon.exe"]
)
def test_core_windows_processes_are_protected(name):
    protected, reason = is_protected_process(ProcessInfo(pid=900, name=name))
    assert protected
    assert reason


def test_system_owned_services_in_system32_are_protected():
    info = ProcessInfo(
        pid=1200,
        name="somehost.exe",
        exe=os.path.join(SYSTEM32, "somehost.exe"),
        username="NT AUTHORITY\\SYSTEM",
    )
    protected, _reason = is_protected_process(info)
    assert protected


def test_a_developer_process_is_not_protected():
    info = ProcessInfo(
        pid=12452,
        name="python.exe",
        exe=r"C:\Python311\python.exe",
        username="DESKTOP\\tahir",
    )
    protected, reason = is_protected_process(info)
    assert not protected
    assert reason == ""


def test_a_user_process_named_like_a_service_elsewhere_is_still_protected():
    """Name matching is intentionally strict — svchost.exe is never a dev server."""
    info = ProcessInfo(pid=5000, name="svchost.exe", exe=r"C:\tmp\svchost.exe")
    protected, _reason = is_protected_process(info)
    assert protected


def test_the_current_process_is_never_protected():
    info = ProcessInfo(
        pid=os.getpid(), name="python.exe", exe=r"C:\Python311\python.exe"
    )
    protected, _reason = is_protected_process(info)
    assert not protected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("127.0.0.1", "127.0.0.1"),
        ("0.0.0.0", "ALL"),
        ("::", "ALL"),
        ("::1", "::1"),
        ("192.168.1.5", "192.168.1.5"),
        (None, "*"),
        ("", "*"),
    ],
)
def test_addresses_are_formatted_for_humans(raw, expected):
    assert format_address(raw) == expected
