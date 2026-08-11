"""The service layer's presence on a background thread.

Everything that touches the OS runs here so the window never blocks. The
worker owns its own scanner and terminator instances; the UI only ever talks
to it through queued signals.
"""

from __future__ import annotations

from typing import List, Mapping, Optional

from PySide6.QtCore import QObject, Signal, Slot

from app.models.port_info import PortEntry, TerminationOutcome, TerminationResult
from app.services.description_resolver import DescriptionResolver
from app.services.port_scanner import PortScanner, ScanError
from app.services.process_inspector import ProcessInspector
from app.services.process_terminator import ProcessTerminator


class ScanWorker(QObject):
    """Runs scans and terminations off the UI thread."""

    scan_finished = Signal(list)
    scan_failed = Signal(str)
    stop_finished = Signal(object, object)

    def __init__(self, custom_descriptions: Optional[Mapping[str, str]] = None) -> None:
        super().__init__()
        self._inspector = ProcessInspector()
        self._resolver = DescriptionResolver(custom_descriptions or {})
        self._scanner = PortScanner(self._inspector, self._resolver)
        self._terminator = ProcessTerminator(self._inspector)

    @Slot(dict)
    def set_custom_descriptions(self, mapping: dict) -> None:
        self._resolver.set_custom_descriptions(mapping)

    @Slot()
    def run_scan(self) -> None:
        try:
            entries: List[PortEntry] = self._scanner.scan()
        except ScanError as exc:
            self.scan_failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - last-resort safety net
            self.scan_failed.emit(f"Unexpected error while scanning: {exc}")
            return
        self.scan_finished.emit(entries)

    @Slot(object)
    def run_stop(self, entry: PortEntry) -> None:
        try:
            result = self._terminator.stop_entry(entry)
        except Exception as exc:  # pragma: no cover - last-resort safety net
            result = TerminationResult(
                TerminationOutcome.FAILED, f"Unexpected error while stopping: {exc}"
            )
        self.stop_finished.emit(entry, result)
