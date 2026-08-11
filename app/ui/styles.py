"""The ZeroPort visual system: palette, type, and the background texture.

Everything visual is defined once here so the rest of the UI never invents a
colour. The palette is deliberately tiny — near-black, off-white, one lime
accent, and a violet used for exactly one thing.
"""

from __future__ import annotations

import random
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap

# --------------------------------------------------------------------- colour

BASE = QColor("#0A0A0B")
SURFACE = QColor("#0E0E10")
SURFACE_RAISED = QColor("#131316")
SURFACE_HOVER = QColor("#141417")
SURFACE_SELECTED = QColor("#1A1A1E")

TEXT = QColor("#FAFAFA")
TEXT_MUTED = QColor(250, 250, 250, 165)
TEXT_FAINT = QColor(250, 250, 250, 105)
TEXT_GHOST = QColor(250, 250, 250, 66)

ACCENT = QColor("#C6F24E")
ACCENT_SOFT = QColor(198, 242, 78, 38)
ACCENT_LINE = QColor(198, 242, 78, 120)

VIOLET = QColor("#A855F7")
VIOLET_SOFT = QColor(168, 85, 247, 40)

DANGER = QColor("#E0685A")
DANGER_SOFT = QColor(224, 104, 90, 34)

LINE = QColor(250, 250, 250, 20)
LINE_STRONG = QColor(250, 250, 250, 34)


def rgba(color: QColor, alpha: Optional[float] = None) -> str:
    """CSS colour string for use inside stylesheets."""
    a = color.alphaF() if alpha is None else alpha
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {a:.3f})"


# ----------------------------------------------------------------- typography

_SANS_STACK = (
    "Inter",
    "Geist",
    "Space Grotesk",
    "Segoe UI Variable Text",
    "Segoe UI",
)
_MONO_STACK = (
    "Geist Mono",
    "JetBrains Mono",
    "Cascadia Mono",
    "Consolas",
    "Courier New",
)

NORMAL = QFont.Weight.Normal
MEDIUM = QFont.Weight.Medium
DEMI = QFont.Weight.DemiBold
BOLD = QFont.Weight.Bold

_sans_family: Optional[str] = None
_mono_family: Optional[str] = None


def _first_available(stack) -> str:
    families = set(QFontDatabase.families())
    for name in stack:
        if name in families:
            return name
    return stack[-1]


def sans_family() -> str:
    global _sans_family
    if _sans_family is None:
        _sans_family = _first_available(_SANS_STACK)
    return _sans_family


def mono_family() -> str:
    global _mono_family
    if _mono_family is None:
        _mono_family = _first_available(_MONO_STACK)
    return _mono_family


def sans(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(sans_family(), size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def mono(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(mono_family(), size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def micro_label(size: int = 8) -> QFont:
    """Uppercase technical label: small, monospace, widely tracked."""
    font = mono(size, QFont.Weight.Medium)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
    return font


# ------------------------------------------------------------------- texture

_TILE_SIZE = 192
_DOT_SPACING = 24
_texture_cache: Optional[QPixmap] = None


def background_tile() -> QPixmap:
    """A seamless near-black tile: base colour, faint grain, quiet dot grid.

    Built once and reused as a brush, so painting the background costs a blit.
    """
    global _texture_cache
    if _texture_cache is not None:
        return _texture_cache

    image = QImage(_TILE_SIZE, _TILE_SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(BASE)

    # Film grain — a fixed seed so the texture is identical on every launch.
    rng = random.Random(0x2E70)
    for _ in range(int(_TILE_SIZE * _TILE_SIZE * 0.055)):
        x = rng.randrange(_TILE_SIZE)
        y = rng.randrange(_TILE_SIZE)
        alpha = rng.randint(3, 7)
        image.setPixelColor(x, y, _blend(BASE, QColor(255, 255, 255, alpha)))
    for _ in range(int(_TILE_SIZE * _TILE_SIZE * 0.03)):
        x = rng.randrange(_TILE_SIZE)
        y = rng.randrange(_TILE_SIZE)
        image.setPixelColor(x, y, _blend(BASE, QColor(0, 0, 0, rng.randint(4, 9))))

    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 9))  # ~3.5% white
    for y in range(0, _TILE_SIZE, _DOT_SPACING):
        for x in range(0, _TILE_SIZE, _DOT_SPACING):
            painter.drawRect(x, y, 1, 1)
    painter.end()

    _texture_cache = QPixmap.fromImage(image)
    return _texture_cache


def _blend(base: QColor, overlay: QColor) -> QColor:
    a = overlay.alphaF()
    return QColor(
        int(base.red() * (1 - a) + overlay.red() * a),
        int(base.green() * (1 - a) + overlay.green() * a),
        int(base.blue() * (1 - a) + overlay.blue() * a),
    )


# ---------------------------------------------------------------- stylesheet


def app_stylesheet() -> str:
    """Chrome that is genuinely simpler to express as QSS than to paint."""
    return f"""
    QWidget {{
        color: {rgba(TEXT)};
        font-family: "{sans_family()}";
        font-size: 13px;
    }}

    QToolTip {{
        background-color: {rgba(SURFACE_RAISED)};
        color: {rgba(TEXT)};
        border: 1px solid {rgba(LINE_STRONG)};
        padding: 6px 9px;
        font-size: 12px;
    }}

    /* ------------------------------------------------------------- inputs */

    QLineEdit#searchField {{
        background: {rgba(SURFACE)};
        border: 1px solid {rgba(LINE)};
        border-radius: 2px;
        padding: 8px 12px 8px 12px;
        selection-background-color: {rgba(ACCENT_SOFT)};
        selection-color: {rgba(TEXT)};
        color: {rgba(TEXT)};
    }}
    QLineEdit#searchField:hover {{
        border-color: {rgba(LINE_STRONG)};
    }}
    QLineEdit#searchField:focus {{
        border-color: {rgba(ACCENT_LINE)};
        background: {rgba(SURFACE_RAISED)};
    }}

    /* ------------------------------------------------------------ buttons */

    QPushButton#refreshButton {{
        background: transparent;
        border: 1px solid {rgba(LINE_STRONG)};
        border-radius: 2px;
        padding: 8px 18px;
        color: {rgba(TEXT_MUTED)};
        font-family: "{mono_family()}";
        font-size: 11px;
        letter-spacing: 1.4px;
    }}
    QPushButton#refreshButton:hover {{
        border-color: {rgba(ACCENT_LINE)};
        color: {rgba(ACCENT)};
    }}
    QPushButton#refreshButton:pressed {{
        background: {rgba(ACCENT_SOFT)};
    }}
    QPushButton#refreshButton:disabled {{
        color: {rgba(TEXT_GHOST)};
        border-color: {rgba(LINE)};
    }}

    QPushButton#ghostButton {{
        background: transparent;
        border: 1px solid {rgba(LINE)};
        border-radius: 2px;
        padding: 8px 16px;
        color: {rgba(TEXT_MUTED)};
        font-family: "{mono_family()}";
        font-size: 11px;
        letter-spacing: 1.2px;
    }}
    QPushButton#ghostButton:hover {{
        border-color: {rgba(LINE_STRONG)};
        color: {rgba(TEXT)};
    }}

    QPushButton#dangerButton {{
        background: {rgba(DANGER_SOFT)};
        border: 1px solid {rgba(DANGER, 0.55)};
        border-radius: 2px;
        padding: 8px 16px;
        color: {rgba(DANGER)};
        font-family: "{mono_family()}";
        font-size: 11px;
        letter-spacing: 1.2px;
    }}
    QPushButton#dangerButton:hover {{
        background: {rgba(DANGER, 0.20)};
        color: #F2A197;
    }}

    QPushButton#iconButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 2px;
        padding: 6px 10px;
        color: {rgba(TEXT_FAINT)};
        font-family: "{mono_family()}";
        font-size: 11px;
        letter-spacing: 1.2px;
    }}
    QPushButton#iconButton:hover {{
        color: {rgba(TEXT)};
        border-color: {rgba(LINE)};
    }}

    /* ----------------------------------------------------------- combobox */

    QComboBox#intervalBox {{
        background: transparent;
        border: 1px solid {rgba(LINE)};
        border-radius: 2px;
        padding: 7px 10px;
        color: {rgba(TEXT_MUTED)};
        font-family: "{mono_family()}";
        font-size: 11px;
        letter-spacing: 1.1px;
        min-width: 96px;
    }}
    QComboBox#intervalBox:hover {{
        border-color: {rgba(LINE_STRONG)};
        color: {rgba(TEXT)};
    }}
    QComboBox#intervalBox::drop-down {{
        border: none;
        width: 18px;
    }}
    QComboBox#intervalBox::down-arrow {{
        image: none;
        border-left: 3px solid transparent;
        border-right: 3px solid transparent;
        border-top: 4px solid {rgba(TEXT_FAINT)};
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {rgba(SURFACE_RAISED)};
        border: 1px solid {rgba(LINE_STRONG)};
        selection-background-color: {rgba(ACCENT_SOFT)};
        selection-color: {rgba(TEXT)};
        outline: none;
        padding: 4px;
        font-family: "{mono_family()}";
        font-size: 11px;
    }}

    /* -------------------------------------------------------------- table */

    QTableView#portTable {{
        background: transparent;
        border: none;
        outline: none;
        gridline-color: transparent;
        selection-background-color: transparent;
    }}
    QHeaderView {{
        background: transparent;
        border: none;
    }}
    QHeaderView::section {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {rgba(LINE_STRONG)};
        padding: 0px 12px 10px 12px;
        color: {rgba(TEXT_FAINT)};
        font-family: "{mono_family()}";
        font-size: 10px;
        letter-spacing: 1.4px;
    }}
    QHeaderView::section:hover {{
        color: {rgba(TEXT_MUTED)};
    }}
    QHeaderView::up-arrow, QHeaderView::down-arrow {{
        image: none;
        width: 0px;
    }}

    /* ---------------------------------------------------------- scrollbar */

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {rgba(TEXT, 0.13)};
        border-radius: 2px;
        min-height: 32px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {rgba(TEXT, 0.24)};
    }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none;
        height: 0px;
        width: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
    }}
    QScrollBar::handle:horizontal {{
        background: {rgba(TEXT, 0.13)};
        border-radius: 2px;
        min-width: 32px;
        margin: 2px;
    }}

    /* ------------------------------------------------------------ dialogs */

    QDialog {{
        background: {rgba(SURFACE)};
    }}

    QTableWidget#mappingTable {{
        background: {rgba(BASE)};
        border: 1px solid {rgba(LINE)};
        gridline-color: {rgba(LINE)};
        outline: none;
        selection-background-color: {rgba(ACCENT_SOFT)};
        selection-color: {rgba(TEXT)};
    }}
    QTableWidget#mappingTable::item {{
        padding: 4px 6px;
    }}
    """
