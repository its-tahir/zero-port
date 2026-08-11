"""Headless checks that the window actually assembles and reacts to results.

These run under Qt's offscreen platform, so they exercise real widgets without
needing a desktop session.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config.config_manager import ConfigManager  # noqa: E402
from app.models.port_info import PortEntry, ProcessInfo  # noqa: E402
from app.ui import styles  # noqa: E402
from app.ui.dialogs import ConfirmStopDialog, ProcessDetailsDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.panels import StatePanel  # noqa: E402
from app.ui.port_table import (  # noqa: E402
    COL_ACTION,
    COL_DESCRIPTION,
    COL_PID,
    COL_PORT,
    ENTRY_ROLE,
    PortItemDelegate,
    PortTableModel,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def entry(port=8000, pid=12452, name="python.exe", description="FastAPI / Uvicorn",
          protected=False, siblings=()):
    return PortEntry(
        port=port,
        protocol="TCP",
        address="127.0.0.1",
        process=ProcessInfo(
            pid=pid,
            name=name,
            exe=r"C:\Python311\python.exe",
            cmdline="python -m uvicorn main:app --port 8000",
            username="DESKTOP\\tahir",
            create_time=1000.0,
        ),
        description=description,
        protected=protected,
        protection_reason="Core Windows process." if protected else "",
        sibling_ports=tuple(siblings),
    )


@pytest.fixture
def window(qapp, tmp_path):
    config = ConfigManager(tmp_path / "config.json")
    config.set_refresh(False)
    win = MainWindow(config)

    # Keep the window off the real machine: tests feed results in directly, so
    # a background scan must never overwrite them mid-test.
    win.request_scan.disconnect()
    win.request_stop.disconnect()

    yield win
    win.close()


# ------------------------------------------------------------------- model


def test_model_exposes_display_and_sort_values(qapp):
    model = PortTableModel()
    model.set_entries([entry(port=8000), entry(port=443, pid=4, name="System")])

    assert model.rowCount() == 2
    assert model.index(0, COL_PORT).data() == "8000"
    assert model.index(0, COL_PID).data() == "12452"
    assert model.index(0, COL_DESCRIPTION).data() == "FastAPI / Uvicorn"
    assert model.index(1, COL_PORT).data() == "443"
    assert isinstance(model.index(0, COL_PORT).data(ENTRY_ROLE), PortEntry)


def test_shared_pid_tooltip_lists_every_port(qapp):
    model = PortTableModel()
    model.set_entries([entry(port=8000, siblings=(8001, 8080))])
    tooltip = model.index(0, COL_PID).data(3)  # Qt.ToolTipRole
    assert "8000" in tooltip and "8001" in tooltip and "8080" in tooltip


# -------------------------------------------------------------------- table


def test_search_filters_rows(window):
    window._on_scan_finished(
        [
            entry(port=8000, name="python.exe", description="FastAPI / Uvicorn"),
            entry(port=3000, pid=18320, name="node.exe", description="Next.js"),
            entry(port=5432, pid=4210, name="postgres.exe", description="PostgreSQL"),
        ]
    )
    assert window.table.visible_count() == 3

    window.search.setText("node")
    assert window.table.visible_count() == 1

    window.search.setText("54")
    assert window.table.visible_count() == 1

    window.search.setText("")
    assert window.table.visible_count() == 3


def test_search_matches_every_term(window):
    window._on_scan_finished(
        [
            entry(port=8000, name="python.exe"),
            entry(port=8001, pid=999, name="python.exe", description="Agent API"),
        ]
    )
    window.search.setText("python 8001")
    assert window.table.visible_count() == 1


def test_selection_survives_a_refresh(window):
    rows = [entry(port=8000), entry(port=3000, pid=18320, name="node.exe")]
    window._on_scan_finished(rows)
    window.table.select_key((3000, "TCP", "127.0.0.1", 18320))
    assert window.table.selected_entry().port == 3000

    window._on_scan_finished(list(reversed(rows)))
    assert window.table.selected_entry().port == 3000


# ------------------------------------------------------------------- states


def test_the_count_reflects_the_result(window):
    window._on_scan_finished([entry(port=p, pid=p) for p in (8000, 3000, 5432)])
    assert window.count_label.text() == "3"
    assert window.stack.currentWidget() is window.table


def test_the_count_shows_the_filtered_total(window):
    window._on_scan_finished([entry(port=p, pid=p) for p in (8000, 3000, 5432)])
    window.search.setText("8000")
    assert window.count_label.text() == "1"
    assert "3" in window.count_caption.text()


def test_empty_result_shows_the_empty_state(window):
    window._on_scan_finished([])
    assert window.stack.currentWidget() is window.state_panel
    assert window.count_label.text() == "0"


def test_no_search_matches_shows_its_own_state(window):
    window._on_scan_finished([entry(port=8000)])
    window.search.setText("zzzznope")
    assert window.stack.currentWidget() is window.state_panel


def test_scan_failure_shows_the_error_state(window):
    window._on_scan_failed("Windows denied access to the connection table.")
    assert window.stack.currentWidget() is window.state_panel
    assert window.count_label.text() == "—"


def test_a_failed_scan_never_leaves_stale_rows_behind(window):
    """Showing the last good scan as if it were current is worse than nothing."""
    window._on_scan_finished([entry(port=8000), entry(port=3000, pid=18320)])
    window.search.setText("python")

    window._on_scan_failed("Windows denied access to the connection table.")
    assert window.stack.currentWidget() is window.state_panel

    # Typing must not swap the stale table back in.
    window.search.setText("py")
    assert window.stack.currentWidget() is window.state_panel
    assert window.table.visible_count() == 0

    # ...and it comes back cleanly once a scan succeeds.
    window._on_scan_finished([entry(port=8000)])
    assert window.stack.currentWidget() is window.table


def test_the_state_button_retries_after_an_error_rather_than_clearing_search(window):
    window._on_scan_finished([entry(port=8000)])
    window.search.setText("python")
    window._on_scan_failed("boom")

    window._scan_in_flight = False
    window._on_state_action()

    assert window._scan_in_flight, "RETRY did not start a new scan"
    assert window.search.text() == "python", "RETRY should not clear the search"


def test_the_state_button_clears_the_search_when_nothing_matched(window):
    window._on_scan_finished([entry(port=8000)])
    window.search.setText("zzzznope")
    assert window.state_panel.state == StatePanel.NO_MATCHES

    window._on_state_action()
    assert window.search.text() == ""


def test_a_row_that_cannot_be_stopped_explains_which_reason_applies(window):
    protected = entry(pid=4, name="System", protected=True)
    assert window._refusal(protected)[0] == "Protected process"

    ownerless = PortEntry(
        port=445,
        protocol="TCP",
        address="ALL",
        process=ProcessInfo.unknown(None),
        description="Windows file sharing (SMB)",
        protected=True,
    )
    assert window._refusal(ownerless)[0] == "No process to stop"


def test_overlapping_scans_are_coalesced(window):
    window._scan_in_flight = False
    window.refresh()
    assert window._scan_in_flight
    window.refresh()
    assert window._rescan_queued


def test_a_fast_scan_never_flashes_the_progress_bar(window):
    """A scan takes ~70ms; a lime line every 5 seconds would be noise."""
    window._scan_in_flight = False
    window.refresh()
    assert not window.scan_bar.isVisible()
    assert window.scan_bar_timer.isActive()

    window._on_scan_finished([entry()])
    assert not window.scan_bar.isVisible()
    assert not window.scan_bar_timer.isActive()


def test_state_messages_wrap_instead_of_clipping(window):
    window._on_scan_failed(
        "Windows denied access to the connection table. "
        "Some processes may require elevated permissions."
    )
    QApplication.processEvents()

    body = window.state_panel._body
    assert body.width() == window.state_panel.BODY_WIDTH
    one_line = body.fontMetrics().height()
    # Two sentences at this width need more than one line, and the label must
    # actually be tall enough to show them.
    assert body.heightForWidth(body.width()) > one_line * 1.5
    assert body.minimumHeight() >= body.heightForWidth(body.width())


# ------------------------------------------------------------------ dialogs


def test_confirm_dialog_names_the_process_and_its_other_ports(qapp):
    dialog = ConfirmStopDialog(None, entry(siblings=(8001, 8080)))
    text = _all_text(dialog)
    assert "8000" in text
    assert "python.exe" in text
    assert "12452" in text
    assert "8001" in text
    dialog.deleteLater()


def test_details_dialog_shows_the_command_line(qapp):
    dialog = ProcessDetailsDialog(None, entry())
    text = _all_text(dialog)
    assert "uvicorn" in text
    assert r"C:\Python311\python.exe" in text
    dialog.deleteLater()


def test_protected_rows_have_no_stop_button(qapp):
    protected = entry(pid=4, name="System", protected=True)
    assert not protected.can_stop

    model = PortTableModel()
    model.set_entries([protected])
    assert model.index(0, COL_ACTION).data(3)  # tooltip explains why


# ------------------------------------------------------------------- visuals


def test_the_background_tile_is_near_black_and_reusable(qapp):
    tile = styles.background_tile()
    assert tile is styles.background_tile()
    assert tile.width() == tile.height() == 192

    image = tile.toImage()
    # Nothing in the texture may be bright enough to compete with content.
    brightest = max(
        image.pixelColor(x, y).lightness()
        for x in range(0, 192, 4)
        for y in range(0, 192, 4)
    )
    assert brightest < 40


def test_the_stop_button_stays_inside_its_cell(qapp):
    from PySide6.QtCore import QRect

    cell = QRect(900, 40, 104, 40)
    box = PortItemDelegate.button_rect(cell)
    assert cell.contains(box)


# --------------------------------------------------------------- stop button


def _click_stop_on_port(window, port: int):
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtTest import QTest

    # The window's own handler opens a modal dialog, which would block a
    # headless run. These tests only care that the click is delivered.
    window.table.stop_requested.disconnect(window.confirm_stop)

    window.show()
    QApplication.processEvents()

    for row in range(window.table.proxy.rowCount()):
        index = window.table.proxy.index(row, COL_ACTION)
        if index.data(ENTRY_ROLE).port == port:
            break
    else:
        raise AssertionError(f"port {port} is not in the table")

    point = PortItemDelegate.button_rect(window.table.visualRect(index)).center()
    QTest.mouseClick(window.table.viewport(), _Qt.MouseButton.LeftButton, pos=point)
    QApplication.processEvents()


def test_clicking_stop_raises_a_request_for_that_row(window):
    """Regression: Qt delivers editorEvent on release, not press."""
    window._on_scan_finished([entry(port=8000), entry(port=3000, pid=18320)])

    seen = []
    window.table.stop_requested.connect(seen.append)
    _click_stop_on_port(window, 3000)

    assert seen, "clicking STOP produced no request"
    assert seen[0].port == 3000
    assert seen[0].pid == 18320


def test_clicking_a_protected_row_produces_no_request(window):
    window._on_scan_finished([entry(port=445, pid=4, name="System", protected=True)])

    seen = []
    window.table.stop_requested.connect(seen.append)
    _click_stop_on_port(window, 445)

    assert not seen


def _all_text(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(child.text() for child in widget.findChildren(QLabel))
