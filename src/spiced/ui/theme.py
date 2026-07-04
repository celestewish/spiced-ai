"""Visual theme: saffron accents, cream background, deep brown text.

Calm spacing, rounded panels, and readable typography. The palette is kept in
one place so screens stay consistent.
"""

from __future__ import annotations

# Palette
CREAM = "#FBF3E4"
CREAM_PANEL = "#FFFDF8"
SAFFRON = "#E8873B"
SAFFRON_DEEP = "#D2721F"
BROWN = "#3A2C1F"
BROWN_SOFT = "#6E5A48"
BORDER = "#E7D7BE"
SIDEBAR = "#F3E5CC"
SELECTED = "#F6D9AF"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 14px;
    color: {BROWN};
}}

QMainWindow, QWidget#Root {{
    background: {CREAM};
}}

/* Panels */
QFrame#Panel, QFrame#Sidebar, QFrame#ContextPanel {{
    background: {CREAM_PANEL};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}

QFrame#Sidebar {{
    background: {SIDEBAR};
}}

QLabel#Brand {{
    font-size: 22px;
    font-weight: 700;
    color: {SAFFRON_DEEP};
    padding: 6px 4px;
}}

QLabel#Tagline {{
    color: {BROWN_SOFT};
    font-size: 12px;
    padding: 0 4px 8px 4px;
}}

QLabel#ScreenTitle {{
    font-size: 20px;
    font-weight: 700;
    color: {BROWN};
}}

QLabel#SectionTitle {{
    font-size: 13px;
    font-weight: 700;
    color: {BROWN_SOFT};
    text-transform: uppercase;
    letter-spacing: 1px;
}}

QLabel#Muted {{
    color: {BROWN_SOFT};
}}

/* Sidebar navigation buttons */
QPushButton#NavButton {{
    text-align: left;
    padding: 11px 14px;
    border: none;
    border-radius: 10px;
    background: transparent;
    font-size: 14px;
    color: {BROWN};
}}
QPushButton#NavButton:hover {{
    background: {SELECTED};
}}
QPushButton#NavButton:checked {{
    background: {SAFFRON};
    color: white;
    font-weight: 600;
}}

/* Primary buttons */
QPushButton {{
    background: {SAFFRON};
    color: white;
    border: none;
    border-radius: 10px;
    padding: 9px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {SAFFRON_DEEP}; }}
QPushButton:disabled {{ background: #E7D7BE; color: {BROWN_SOFT}; }}

QPushButton#Ghost {{
    background: transparent;
    color: {SAFFRON_DEEP};
    border: 1px solid {SAFFRON};
}}
QPushButton#Ghost:hover {{ background: {SELECTED}; }}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: white;
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: {SAFFRON};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 1px solid {SAFFRON};
}}

/* Usage / plan pill */
QLabel#UsagePill {{
    background: {SELECTED};
    color: {BROWN};
    border-radius: 12px;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
}}

QListWidget {{
    background: transparent;
    border: none;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: {SELECTED};
    color: {BROWN};
}}

QScrollArea {{ border: none; background: transparent; }}
"""
