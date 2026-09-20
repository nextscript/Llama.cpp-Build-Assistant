"""The original application palette, shared by every Qt page and dialog."""
from qfluentwidgets import setTheme, setThemeColor, Theme

BG = '#080d14'
SURFACE = '#101722'
SURFACE_ALT = '#121c29'
BORDER = '#273445'
TEXT = '#eef4ff'
MUTED = '#94a3b8'
BLUE = '#2563eb'
BLUE_HOVER = '#1d4ed8'
GREEN = '#7bd45a'
DANGER = '#dc2626'
DANGER_HOVER = '#b91c1c'

def apply_theme(app):
    setTheme(Theme.DARK)
    setThemeColor(BLUE)
    app.setStyleSheet(f'''
        QWidget {{ color: {TEXT}; font-family: "Segoe UI"; font-size: 13px; }}
        QMainWindow, QDialog, QWidget#shell {{ background: {BG}; }}
        QStackedWidget, QWidget#page {{ background: #0d131d; border-radius: 10px; }}
        QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
        QFrame#sidebar {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 10px; }}
        QLabel {{ background: transparent; border: none; }}
        QLabel#heading {{ font-size: 24px; font-weight: 600; }}
        QLabel#appTitle {{ font-size: 20px; font-weight: 600; }}
        QLabel#subtitle {{ font-size: 15px; font-weight: 600; }}
        QLabel#muted {{ color: {MUTED}; }}
        QLabel#status {{ color: {GREEN}; background: #16331f; border-radius: 8px; padding: 8px 16px; }}
        QPushButton {{ background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px; }}
        QPushButton:hover {{ background: #182438; }}
        QPushButton[primary="true"], QPushButton#nav:checked {{ background: {BLUE}; color: white; border: none; }}
        QPushButton[primary="true"]:hover {{ background: {BLUE_HOVER}; }}
        QPushButton[danger="true"] {{ background: {DANGER}; }}
        QPushButton[danger="true"]:hover {{ background: {DANGER_HOVER}; }}
        QPushButton:disabled {{ color: {MUTED}; background: {SURFACE}; }}
        QPushButton#nav {{ text-align: left; border: none; background: transparent; font-size: 14px; }}
        QPushButton#nav:hover {{ background: #182438; }}
        QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background: #0b111a; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px; selection-background-color: {BLUE}; }}
        QComboBox QAbstractItemView {{ background: {SURFACE_ALT}; color: {TEXT}; selection-background-color: {BLUE}; }}
        QPlainTextEdit {{ font-family: Consolas; font-size: 12px; }}
        QScrollArea {{ border: none; background: transparent; }}
        QTableWidget {{ background: {SURFACE}; alternate-background-color: {SURFACE_ALT}; border: 1px solid {BORDER}; gridline-color: {BORDER}; selection-background-color: {BLUE}; }}
        QHeaderView::section {{ background: {SURFACE_ALT}; color: {TEXT}; border: none; padding: 10px; font-weight: 600; }}
        QSplitter::handle {{ background: {BG}; width: 12px; }}
        QScrollBar:vertical {{ background: {SURFACE}; width: 10px; }}
        QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 24px; border-radius: 4px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    ''')
# Explicit component rules take precedence over QFluentWidgets' local theme sheets.
BUTTON_STYLE = f'''
QPushButton {{ color: {TEXT}; background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 12px; font-size: 13px; }}
QPushButton:hover {{ background: #182438; }}
QPushButton[primary="true"] {{ background: {BLUE}; border: none; color: white; }}
QPushButton[primary="true"]:hover {{ background: {BLUE_HOVER}; }}
QPushButton[danger="true"] {{ background: {DANGER}; border: none; }}
QPushButton[danger="true"]:hover {{ background: {DANGER_HOVER}; }}
QPushButton:disabled {{ color: {MUTED}; background: {SURFACE}; }}
QPushButton#nav {{ text-align: left; border: none; background: transparent; font-size: 14px; padding: 8px; }}
QPushButton#nav:hover {{ background: #182438; }}
QPushButton#nav:checked {{ background: {BLUE}; color: white; }}
QPushButton#nav:checked:hover {{ background: {BLUE_HOVER}; }}
'''
FIELD_STYLE = f'''
QLineEdit {{ background: #0b111a; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px; selection-background-color: {BLUE}; }}
QLineEdit:focus {{ border: 1px solid {BLUE}; }}
'''
