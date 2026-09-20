from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QPlainTextEdit, QMessageBox, QWidget
from qfluentwidgets import CheckBox
from ui.widgets import LineEdit
from source_manager import get_remote_branches, add_source, edit_source
from profile_manager import add_profile, edit_profile
from config import BUILD_TYPES
from ui.widgets import SearchCombo, button, row, label


class SourceDialog(QDialog):
    def __init__(self, owner, source=None):
        super().__init__(owner)
        self.owner, self.source = owner, source or {}
        self.generation = 0
        self.closed = False
        self.branches = []
        self.loaded_url = ''
        self.setWindowTitle('Edit Build Source' if source else 'Add Build Source')
        self.resize(600, 440)
        body = QVBoxLayout(self)
        body.setContentsMargins(20, 20, 20, 20)
        body.addWidget(label(self.windowTitle(), 'subtitle'))
        form = QFormLayout()
        body.addLayout(form)
        self.fields = {}
        for key, text in [('name', 'Name:'), ('repo_url', 'Repository URL:')]:
            entry = LineEdit(self)
            entry.setText(self.source.get(key, ''))
            self.fields[key] = entry
            form.addRow(text, entry)
        self.branch = SearchCombo([self.source.get('branch', '')])
        self.branch.lineEdit().setPlaceholderText('Select or enter a custom branch / ref')
        self.refresh = button('Refresh', self.load_branches)
        form.addRow('Branch:', row(self.branch, self.refresh))
        self.status = label('Enter a repository URL', 'muted')
        form.addRow(self.status)
        for key, text in [('commit', 'Pinned Commit (optional):'), ('fetch_ref', 'Fetch Ref (optional):')]:
            entry = LineEdit(self)
            entry.setText(self.source.get(key, ''))
            self.fields[key] = entry
            form.addRow(text, entry)
        self.save_button = button('Save' if source else 'Add', self.save, True)
        body.addStretch()
        body.addWidget(row(self.save_button, button('Cancel', self.reject)))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.load_branches)
        self.fields['repo_url'].textChanged.connect(self.schedule)
        self.finished.connect(self.on_close)
        if self.fields['repo_url'].text():
            self.timer.start()

    def on_close(self, *_):
        self.closed = True
        self.generation += 1
        self.timer.stop()

    def schedule(self, *_):
        self.generation += 1
        self.branches = []
        self.timer.start()

    def load_branches(self):
        self.generation += 1
        generation = self.generation
        url = self.fields['repo_url'].text().strip()
        if not url:
            self.status.setText('Enter a repository URL')
            self.refresh.setEnabled(True)
            return
        original = self.branch.currentText()
        self.status.setText('Loading remote branches...')
        self.refresh.setEnabled(False)
        def apply(result):
            if self.closed or generation != self.generation:
                return
            branches, default = result
            self.branches, self.loaded_url = branches, url
            # Preserve typed custom refs and pinned-source branches.
            selected = self.branch.currentText()
            if not selected or selected == original and url != self.source.get('repo_url'):
                selected = next((b for b in ('main', 'master', default) if b in branches), branches[0])
            self.branch.set_values(branches, selected)
            self.status.setText(f'Loaded {len(branches)} remote branches · Default: {default or "Unknown"}')
            self.refresh.setEnabled(True)
        def fail(message):
            if self.closed or generation != self.generation:
                return
            self.status.setText(f'Could not load branches: {message}. Enter a custom branch.')
            self.refresh.setEnabled(True)
        self.owner.tasks.start(lambda log: get_remote_branches(url), apply, fail)

    def save(self):
        values = {k: v.text().strip() for k, v in self.fields.items()}
        values['branch'] = self.branch.currentText().strip()
        if not all(values[k] for k in ('name', 'repo_url', 'branch')):
            QMessageBox.warning(self, 'Error', 'Name, Repository URL and Branch are required.')
            return
        if self.branches and self.loaded_url == values['repo_url'] and values['branch'] not in self.branches:
            QMessageBox.warning(self, 'Error', 'Branch not found in remote repository')
            return
        self.save_button.setEnabled(False)
        source_id = self.source.get('id')
        def save(log):
            if source_id:
                return edit_source(source_id, **values)
            return add_source(**values, source_type='custom', experimental=False)
        def done(result):
            if self.closed:
                return
            self.save_button.setEnabled(True)
            if result[0]:
                self.owner.reload_data()
                self.accept()
            else:
                QMessageBox.warning(self, 'Error', result[1])
        def failed(message):
            if not self.closed:
                self.save_button.setEnabled(True)
                QMessageBox.warning(self, 'Error', message)
        self.owner.tasks.start(save, done, failed)


class ProfileDialog(QDialog):
    def __init__(self, owner, profile=None):
        super().__init__(owner)
        self.owner, self.profile = owner, profile
        self.setWindowTitle('Edit Build Profile' if profile else 'Add Build Profile')
        self.resize(560, 460)
        body = QVBoxLayout(self)
        body.setContentsMargins(20, 15, 20, 18)
        body.addWidget(label(self.windowTitle(), 'subtitle'))
        form = QFormLayout()
        body.addLayout(form)
        self.name = LineEdit(self)
        self.name.setText((profile or {}).get('name', ''))
        self.kind = SearchCombo(BUILD_TYPES)
        self.kind.setCurrentText((profile or {}).get('build_type', 'CPU'))
        self.flags = QPlainTextEdit('\n'.join(profile.get('cmake_flags', []))) if profile else FlagRows()
        self.flags.setPlaceholderText('-DGGML_CUDA=ON')
        form.addRow('Name:', self.name)
        form.addRow('Build Type:', self.kind)
        form.addRow('CMake Flags (one per line):', self.flags)
        self.save_button = button('Save' if profile else 'Add', self.save, True)
        body.addWidget(row(self.save_button, button('Cancel', self.reject)))

    def save(self):
        name, kind = self.name.text().strip(), self.kind.currentText()
        flags = [line.strip() for line in self.flags.toPlainText().splitlines() if line.strip()]
        if not name or kind not in BUILD_TYPES:
            QMessageBox.warning(self, 'Error', 'Name and a valid build type are required.')
            return
        if any(p['name'] == name and p.get('name') != (self.profile or {}).get('name') for p in self.owner.profiles):
            QMessageBox.warning(self, 'Error', 'Profile with this name already exists')
            return
        self.save_button.setEnabled(False)
        original = self.profile['name'] if self.profile else None
        def save(log):
            return (edit_profile(original, name=name, build_type=kind, cmake_flags=flags)
                    if original else add_profile(name, build_type=kind, cmake_flags=flags))
        def done(result):
            self.save_button.setEnabled(True)
            if result[0]:
                self.owner.reload_data()
                self.accept()
            else:
                QMessageBox.warning(self, 'Error', result[1])
        def fail(message):
            self.save_button.setEnabled(True)
            QMessageBox.warning(self, 'Error', message)
        self.owner.tasks.start(save, done, fail)


class FlagRows(QWidget):
    """Keep the original add-profile dialog's plus/minus flag controls."""
    def __init__(self):
        super().__init__()
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.entries = []
        self.add_row()

    def add_row(self, value=''):
        entry = LineEdit()
        entry.setText(value if isinstance(value, str) else '')
        entry.setPlaceholderText('-DGGML_CUDA=ON')
        first = not self.entries
        action = button('+' if first else '-', self.add_row if first else lambda: self.remove_row(container, entry))
        action.setFixedWidth(34)
        container = row(entry, action)
        self.body.addWidget(container)
        self.entries.append(entry)

    def remove_row(self, container, entry):
        self.entries.remove(entry)
        self.body.removeWidget(container)
        container.deleteLater()

    def setPlaceholderText(self, text):
        self.entries[0].setPlaceholderText(text)

    def toPlainText(self):
        return '\n'.join(entry.text() for entry in self.entries)

    def setPlainText(self, text):
        lines = text.splitlines() or ['']
        self.entries[0].setText(lines[0])
        for line in lines[1:]:
            self.add_row(line)
