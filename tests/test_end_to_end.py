"""The whole product, once: find a real port, stop it from the UI, see it go.

Everything else tests a layer. This test starts a real listener, waits for the
real window to show it, clicks the real STOP cell, accepts the real
confirmation dialog, and checks the port is released — the exact sequence a
developer performs when something is squatting on 8000.
"""

import os
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from app.config.config_manager import ConfigManager  # noqa: E402
from app.models.port_info import TerminationOutcome  # noqa: E402
from app.services.port_scanner import PortScanner  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.port_table import COL_ACTION, ENTRY_ROLE, PortItemDelegate  # noqa: E402

LISTENER = (
    "import os, socket, time\n"
    "s = socket.socket()\n"
    "s.bind(('127.0.0.1', 0))\n"
    "s.listen(1)\n"
    "print(os.getpid(), s.getsockname()[1], flush=True)\n"
    "time.sleep(300)\n"
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def listener():
    proc = subprocess.Popen(
        [sys.executable, "-c", LISTENER], stdout=subprocess.PIPE, text=True
    )
    pid, port = (int(v) for v in proc.stdout.readline().split())
    yield pid, port
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=5)
    if proc.stdout:
        proc.stdout.close()


def _pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def _wait_for(app, predicate, timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        _pump(app, 0.2)
    return predicate()


def test_a_developer_finds_a_port_and_releases_it(qapp, listener, tmp_path):
    pid, port = listener

    config = ConfigManager(tmp_path / "config.json")
    config.set_refresh(True, 2)
    window = MainWindow(config)
    window.resize(1180, 720)
    window.show()

    outcomes = []
    window.worker.stop_finished.connect(lambda _entry, result: outcomes.append(result))

    def row_for_port():
        for row in range(window.table.proxy.rowCount()):
            index = window.table.proxy.index(row, COL_ACTION)
            entry = index.data(ENTRY_ROLE)
            if entry is not None and entry.port == port:
                return index
        return None

    try:
        # 1. It shows up on its own, correctly attributed.
        index = _wait_for(qapp, row_for_port, timeout=20)
        assert index is not None, f"port {port} never appeared in the window"

        entry = index.data(ENTRY_ROLE)
        assert entry.pid == pid
        assert entry.can_stop
        assert entry.status == "RUNNING"

        # 2. Clicking STOP asks for confirmation, and confirming stops it.
        QTimer.singleShot(400, lambda: _accept_open_dialog(qapp))
        point = PortItemDelegate.button_rect(window.table.visualRect(index)).center()
        QTest.mouseClick(
            window.table.viewport(), Qt.MouseButton.LeftButton, pos=point
        )

        assert _wait_for(qapp, lambda: bool(outcomes), timeout=25), "no result came back"
        assert outcomes[0].outcome is TerminationOutcome.STOPPED, outcomes[0].message

        # 3. The port is genuinely released, and the table catches up by itself.
        _pump(qapp, 2)
        assert not [e for e in PortScanner().scan() if e.port == port]
        assert _wait_for(
            qapp, lambda: row_for_port() is None, timeout=15
        ), "the row is still listed after the process was stopped"
    finally:
        window.close()


def _accept_open_dialog(app) -> bool:
    for widget in app.topLevelWidgets():
        if isinstance(widget, QDialog) and widget.isVisible():
            widget.accept()
            return True
    return False
