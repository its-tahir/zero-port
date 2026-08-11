"""Windows-specific judgement calls, kept out of the generic services.

The point of this module is to decide what must not be killed. Being wrong in
the permissive direction means a developer reboots their machine, so the rules
here lean deliberately conservative.
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Optional, Tuple

from app.models.port_info import ProcessInfo

IS_WINDOWS = sys.platform == "win32"

# Core Windows processes. Terminating any of these either fails outright or
# takes the session (or the machine) down with it.
CRITICAL_PROCESS_NAMES = frozenset(
    {
        "system",
        "system idle process",
        "registry",
        "memory compression",
        "secure system",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "lsaiso.exe",
        "svchost.exe",
        "fontdrvhost.exe",
        "dwm.exe",
        "sihost.exe",
        "ctfmon.exe",
        "spoolsv.exe",
        "wudfhost.exe",
        "audiodg.exe",
        "searchindexer.exe",
        "msmpeng.exe",
        "securityhealthservice.exe",
        "wininet.exe",
        "taskhostw.exe",
    }
)

# Service accounts. A listener owned by one of these is infrastructure, not a
# dev server the user started.
SYSTEM_ACCOUNTS = frozenset(
    {
        "nt authority\\system",
        "nt authority\\local service",
        "nt authority\\network service",
        "nt authority\\lokaler dienst",
        "nt authority\\netzwerkdienst",
        "system",
        "local service",
        "network service",
    }
)

_SYSTEM_DIRS: Tuple[str, ...] = (
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32").lower(),
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64").lower(),
)


def is_protected_process(info: ProcessInfo) -> Tuple[bool, str]:
    """Return ``(protected, reason)`` for a resolved process.

    ``reason`` is user-facing, so keep it short and specific.
    """
    if info.pid <= 0:
        return True, "No owning process could be identified."

    # PID 0 is the Idle process and 4 is the Windows kernel ("System").
    if info.pid <= 4:
        return True, "Windows kernel process."

    name = (info.name or "").strip().lower()
    if name in CRITICAL_PROCESS_NAMES:
        return True, "Core Windows process."

    username = (info.username or "").strip().lower()
    exe = (info.exe or "").strip().lower()
    in_system_dir = any(exe.startswith(d + os.sep) for d in _SYSTEM_DIRS if d)

    if in_system_dir and username in SYSTEM_ACCOUNTS:
        return True, "Windows system service."

    if in_system_dir and not info.accessible:
        return True, "Protected Windows service."

    return False, ""


def is_admin() -> bool:
    """Whether the current process is running elevated."""
    if not IS_WINDOWS:
        try:
            return os.geteuid() == 0  # type: ignore[attr-defined]
        except AttributeError:
            return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def set_app_user_model_id(app_id: str) -> None:
    """Give Windows a stable identity so the taskbar shows our own icon.

    Without this a PySide6 app inherits the Python launcher's taskbar grouping.
    """
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        # Cosmetic only — never let this stop the app from starting.
        pass


def format_address(ip: Optional[str]) -> str:
    """Turn a raw bind address into something a developer reads at a glance."""
    if not ip:
        return "*"
    if ip in ("0.0.0.0", "::", "*"):
        return "ALL"
    if ip == "::1":
        return "::1"
    return ip


def address_is_local_only(ip: Optional[str]) -> bool:
    return ip in ("127.0.0.1", "::1")
