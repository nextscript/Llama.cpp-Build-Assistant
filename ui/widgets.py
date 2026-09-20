from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QPlainTextEdit, QComboBox, QCompleter, QTableWidget, QAbstractItemView, QHeaderView)
from qfluentwidgets import PushButton, PrimaryPushButton, LineEdit as FluentLineEdit
from ui.theme import BUTTON_STYLE, FIELD_STYLE


def label(text, role='', wrap=True):
    widget = QLabel(text)
    widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, primary=False, danger=False):
    widget = (PrimaryPushButton if primary else PushButton)(text)
    widget.setProperty('primary', primary)
    widget.setProperty('danger', danger)
    widget.setMinimumHeight(36)
    widget.setStyleSheet(BUTTON_STYLE)
    widget.clicked.connect(callback)
    return widget


def card(title=None):
    widget = QFrame()
    widget.setObjectName('card')
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(20, 15, 20, 15)
    layout.setSpacing(8)
    if title:
        layout.addWidget(label(title, 'subtitle'))
    return widget, layout


def row(*widgets):
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for child in widgets:
        layout.addWidget(child)
    return widget


class Page(QWidget):
    def __init__(self, title):
        super().__init__()
        self.setObjectName('page')
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(25, 20, 25, 20)
        self.body.setSpacing(16)
        if title:
            self.body.addWidget(label(title, 'heading'))


class Log(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setUndoRedoEnabled(False)

    def append(self, text):
        self.appendPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class SearchCombo(QComboBox):
    def __init__(self, values=()):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumHeight(36)
        self.setMaxVisibleItems(10)
        self.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.set_values(values)

    def set_values(self, values, selected=None):
        current = self.currentText() if selected is None else selected
        self.blockSignals(True)
        self.clear()
        self.addItems(list(values))
        if current:
            self.setCurrentText(current)
        self.blockSignals(False)


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(48)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return widget


class LineEdit(FluentLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setStyleSheet(FIELD_STYLE)
