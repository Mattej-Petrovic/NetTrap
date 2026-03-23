from __future__ import annotations

BACKGROUND_MAIN = "#0D1117"
BACKGROUND_SIDEBAR = "#080C11"
BACKGROUND_CARDS = "#161B22"
BORDER_DIVIDERS = "#21262D"
TEXT_PRIMARY = "#E6EDF3"
TEXT_SECONDARY = "#7D8590"
ACCENT_PRIMARY = "#00D4AA"
ACCENT_SSH = "#F0883E"
ACCENT_HTTP = "#58A6FF"
ACCENT_ALERTS = "#F85149"
SUCCESS_ACTIVE = "#3FB950"
INACTIVE_STOPPED = "#484F58"

FONT_MONO = "Consolas"
FONT_MONO_FALLBACK = "Courier New"
FONT_SANS = "Segoe UI"
FONT_SANS_FALLBACK = "Arial"


def get_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {BACKGROUND_MAIN};
        color: {TEXT_PRIMARY};
        font-family: "{FONT_SANS}", "{FONT_SANS_FALLBACK}";
    }}

    QLabel {{
        background: transparent;
        color: {TEXT_PRIMARY};
    }}

    QPushButton {{
        background-color: {BACKGROUND_CARDS};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_DIVIDERS};
        border-radius: 8px;
        padding: 10px 14px;
    }}

    QPushButton:hover {{
        background-color: #1C2128;
    }}

    QPushButton:pressed {{
        background-color: #131820;
    }}

    QPushButton#navButton {{
        background-color: transparent;
        border: none;
        border-left: 3px solid transparent;
        border-radius: 0;
        color: {TEXT_SECONDARY};
        font-size: 14px;
        font-weight: 600;
        padding: 12px 14px;
        text-align: left;
    }}

    QPushButton#navButton:hover {{
        background-color: #1C2128;
    }}

    QPushButton#navButton[navActive="true"] {{
        color: {ACCENT_PRIMARY};
        border-left: 3px solid {ACCENT_PRIMARY};
    }}

    QPushButton#stopAllButton {{
        background-color: {ACCENT_ALERTS};
        border: none;
        color: {TEXT_PRIMARY};
        font-weight: 700;
        padding: 10px 14px;
    }}

    QPushButton#stopAllButton:hover {{
        background-color: #da3633;
    }}

    QPushButton#stopAllButton:pressed {{
        background-color: #b62324;
    }}

    QLineEdit, QComboBox {{
        background-color: {BACKGROUND_CARDS};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_DIVIDERS};
        border-radius: 8px;
        padding: 8px 10px;
        selection-background-color: {ACCENT_PRIMARY};
    }}

    QLineEdit:focus, QComboBox:focus {{
        border: 1px solid {ACCENT_PRIMARY};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 28px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {BACKGROUND_CARDS};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_DIVIDERS};
        selection-background-color: #1C2128;
    }}

    QTableWidget {{
        background-color: {BACKGROUND_CARDS};
        alternate-background-color: #11161d;
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_DIVIDERS};
        gridline-color: {BORDER_DIVIDERS};
        selection-background-color: #1C2128;
        selection-color: {TEXT_PRIMARY};
    }}

    QHeaderView::section {{
        background-color: {BACKGROUND_SIDEBAR};
        color: {TEXT_SECONDARY};
        border: none;
        border-bottom: 1px solid {BORDER_DIVIDERS};
        padding: 8px;
        font-weight: 600;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background-color: #30363d;
        border-radius: 4px;
        min-height: 24px;
    }}

    QScrollBar::handle:vertical:hover {{
        background-color: #484f58;
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical,
    QScrollBar:horizontal,
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: transparent;
        border: none;
        width: 0;
        height: 0;
    }}
    """
