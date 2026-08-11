# ZeroPort — Design

Date: 2026-08-11
Status: Approved (supplied as a complete product brief)

## Problem

A developer hits `Address already in use` and has to drop into a terminal, run
`netstat`, cross-reference a PID with `tasklist`, and guess what the process is.
ZeroPort answers "what is using this port?" instantly and lets the developer
release it safely.

## Scope

Discover → Understand → Release listening TCP ports on the local Windows machine.
Nothing else. No monitoring, no firewall, no Docker, no accounts, no network.

## Architecture

```
app/
  main.py                 entry point, QApplication bootstrap
  models/port_info.py     ProcessInfo, PortEntry, TerminationResult (frozen dataclasses)
  services/
    port_scanner.py       psutil.net_connections -> listening TCP endpoints
    process_inspector.py  PID -> name/exe/cmdline/user, with identity fingerprint
    description_resolver.py  signals -> human description
    process_terminator.py graceful -> forced termination with revalidation
    scan_worker.py        QObject worker living on a QThread
  config/config_manager.py  %APPDATA%/ZeroPort/config.json
  utils/windows.py        protected-process rules, address/formatting helpers
  ui/                     styles, main_window, port_table (model+delegate), dialogs
```

The UI layer never touches psutil. Every OS interaction goes through `services/`.

### Threading

Scanning runs on a dedicated `QThread` holding a `ScanWorker`. The window
requests a scan via a queued signal and receives `scan_finished(list[PortEntry])`
or `scan_failed(str)`. Overlapping requests are coalesced — a scan already in
flight sets a "dirty" flag rather than queueing a second scan. Termination also
runs on that worker so the UI never blocks on `wait()`.

### Data model

`PortEntry` is one listening endpoint: port, protocol (TCP/TCP6), address, PID,
`ProcessInfo`, description, status, `protected`, `can_stop`, and
`sibling_ports` (other ports the same PID owns). One process owning three ports
produces three rows sharing a PID; the PID cell carries a marker and tooltip.

### Identity fingerprint

A PID is not a stable identity. Every `ProcessInfo` carries `create_time`.
Termination revalidates `(pid, create_time, name)` immediately before acting;
if any differ, the operation aborts with `PROCESS_CHANGED`.

### Description resolution

Precedence, most confident first:

1. User mapping in `config.json` keyed by port string.
2. Command-line pattern match (`uvicorn` → FastAPI / Uvicorn, `next dev` →
   Next.js, `vite` → Vite dev server, `manage.py runserver` → Django, ...).
3. Executable/process-name match (`postgres.exe` → PostgreSQL, `redis-server.exe`
   → Redis, ...).
4. Well-known port hint — only applied when the process itself yields nothing
   (unknown or a system host process), because a port number alone is weak
   evidence.
5. Generic family fallback: `Python process`, `Node.js process`, `Unknown service`.

Never invent specifics. Conservative fallbacks are correct answers.

### Protection

`pid <= 4`, the Windows core process set (System, smss, csrss, wininit,
services, lsass, winlogon, svchost, ...), and processes under `C:\Windows\System32`
owned by SYSTEM/LOCAL SERVICE/NETWORK SERVICE are marked protected. Protected
rows show `PROTECTED` instead of a STOP affordance and cannot be terminated
from the UI.

### Termination sequence

1. Re-open the PID; abort if gone (`ALREADY_EXITED`).
2. Compare fingerprint; abort on mismatch (`PROCESS_CHANGED`).
3. Refuse if protected (`PROTECTED`).
4. `terminate()`, wait 3s.
5. If alive, `kill()`, wait 2s.
6. Report `STOPPED`, `ACCESS_DENIED`, or `FAILED`, then trigger a rescan.

No shell commands, ever. Only direct psutil/Win32 process APIs.

## UI

Single 1100×700 window (min 850×500), remembered between launches.

- Header: `TN.` monogram (lime period), title, `its-tahir.com` footer mark.
- Stat block: `LOCAL PORTS` micro-label + listening count.
- Toolbar: instant search field, auto-refresh interval selector (2/5/10/30/OFF,
  default 5s), REFRESH button.
- Table: PORT · PROCESS · PID · ADDRESS · DESCRIPTION · STATUS · ACTION.
  Sortable, compact rows, hover/selected states, hairline separators,
  monospace treatment for port/PID/address. STOP is painted by a delegate, not
  a widget per row.
- Row activation opens a details dialog (command line, executable, sibling ports).
- States: scanning, empty, error — each a centered quiet panel, no fake rows.

### Visual system

Base `#0A0A0B`, text `#FAFAFA`, accent `#C6F24E`, rare secondary `#A855F7`.
Background carries a ~3% white dot grid plus a faint procedural grain, painted
once into a cached tile. Uppercase monospace micro-labels with wide tracking.
No gradients, glow, glass, or animation beyond a 1px indeterminate scan line.

## Testing

Pytest over the service layer: scanner filtering and grouping (with a real
bound socket), inspector fallbacks for dead/denied processes, the full
description rule table, custom-description override, and the terminator's
happy path, already-exited race, fingerprint mismatch, protection refusal, and
access-denied handling. Termination tests spawn a real short-lived child
process.

## Packaging

PyInstaller one-file, windowed (no console), `assets/icon.ico` generated by a
dependency-free rasterizer in `tools/make_icon.py`. `build_windows.bat` creates
the venv, installs deps, runs tests, then builds `dist/ZeroPort.exe`.

## Out of scope

Stop-all, remote hosts, UDP inspection, bandwidth/CPU/RAM monitoring, firewall,
Docker, telemetry, updates, accounts.
