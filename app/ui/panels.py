"""The three things the table can be instead of a table: scanning, empty, error."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui import styles
from app.ui.dialogs import hairline, micro


class StatePanel(QWidget):
    """A centred, quiet message. Never a spinner, never a fake row."""

    action_triggered = Signal()

    BODY_WIDTH = 420

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.state = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 60)
        layout.setSpacing(0)
        layout.addStretch(1)

        self._kicker = micro("")
        self._kicker.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._kicker)
        layout.addSpacing(12)

        self._headline = QLabel("")
        self._headline.setFont(styles.sans(15, styles.DEMI))
        self._headline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._headline.setStyleSheet(f"color: {styles.rgba(styles.TEXT)};")
        layout.addWidget(self._headline)

        layout.addSpacing(14)
        rule_row = QWidget()
        rule_layout = QVBoxLayout(rule_row)
        rule_layout.setContentsMargins(0, 0, 0, 0)
        self._rule = hairline(styles.ACCENT)
        self._rule.setFixedWidth(28)
        rule_layout.addWidget(self._rule, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(rule_row)
        layout.addSpacing(14)

        self._body = QLabel("")
        self._body.setFont(styles.sans(10))
        self._body.setWordWrap(True)
        self._body.setFixedWidth(self.BODY_WIDTH)
        self._body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._body.setStyleSheet(f"color: {styles.rgba(styles.TEXT_MUTED)};")
        layout.addWidget(self._body, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(24)
        self._button = QPushButton("")
        self._button.setObjectName("refreshButton")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setFixedWidth(140)
        self._button.clicked.connect(self.action_triggered.emit)
        layout.addWidget(self._button, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(2)

    def show_state(
        self,
        state: str,
        kicker: str,
        headline: str,
        body: str,
        action: Optional[str] = None,
    ) -> None:
        """``state`` names the panel so callers can act on it, not guess."""
        self.state = state
        self._kicker.setText(kicker)
        self._headline.setText(headline)
        self._body.setText(body)
        self._body.setVisible(bool(body))
        # A layout will not consult heightForWidth for an aligned widget, so
        # the wrapped height has to be applied by hand or the text is clipped.
        self._body.setMinimumHeight(
            self._body.heightForWidth(self.BODY_WIDTH) if body else 0
        )
        self._button.setText(action or "")
        self._button.setVisible(bool(action))

    # --------------------------------------------------------- named states

    SCANNING = "scanning"
    EMPTY = "empty"
    NO_MATCHES = "no_matches"
    ERROR = "error"

    def show_scanning(self) -> None:
        self.show_state(
            self.SCANNING,
            "Working",
            "Scanning local ports…",
            "Reading the local TCP table and resolving the processes behind it.",
        )

    def show_empty(self) -> None:
        self.show_state(
            self.EMPTY,
            "Nothing listening",
            "No listening ports",
            "No active listening services were detected on this machine.",
            "REFRESH",
        )

    def show_no_matches(self, query: str) -> None:
        self.show_state(
            self.NO_MATCHES,
            "No matches",
            "Nothing matches your search",
            f'No listening port matches "{query}".',
            "CLEAR SEARCH",
        )

    def show_error(self, message: str) -> None:
        self.show_state(
            self.ERROR,
            "Error",
            "Unable to inspect local ports",
            message or "Some processes may require elevated permissions.",
            "RETRY",
        )
