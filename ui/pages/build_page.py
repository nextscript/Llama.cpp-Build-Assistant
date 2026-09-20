import os
import shutil
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QScrollArea, QVBoxLayout, QWidget, QGridLayout, QFileDialog, QSpinBox
from qfluentwidgets import CheckBox
from ui.widgets import LineEdit
from config import BUILDS_DIR
from app_settings import normalize_build_choices, BUILD_OUTPUT_DIRECTORY_KEY
from ui.widgets import Page, card, label, row, button, Log, SearchCombo
from ui.workers.build_worker import cmake_option_is_off


class BuildPage(Page):
    selection_changed = Signal()

    def __init__(self, owner, settings):
        super().__init__('')
        self.owner = owner
        self.body.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body.addWidget(self.splitter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        left = Page('Build Configuration')
        scroll.setWidget(left)
        self.splitter.addWidget(scroll)
        self.source = SearchCombo()
        self.profile = SearchCombo()
        for title, field in [('Build Source:', self.source), ('Build Profile:', self.profile)]:
            panel, layout = card(title)
            layout.addWidget(field)
            left.body.addWidget(panel)
        panel, layout = card('Build Version Status')
        self.version = {}
        grid = QGridLayout()
        for i, (key, title) in enumerate([
            ('local_build', 'Local Build:'), ('remote_build', 'Latest Available:'),
            ('local_commit', 'Local Commit:'), ('remote_commit', 'Remote Commit:'),
            ('branch', 'Branch:'), ('source_type', 'Source Type:'),
            ('status', 'Status:'), ('last_update', 'Last Update:')]):
            r, c = i // 2, (i % 2) * 2
            grid.addWidget(label(title, 'muted'), r, c)
            self.version[key] = label('—')
            grid.addWidget(self.version[key], r, c + 1)
            grid.setColumnStretch(c + 1, 1)
        layout.addLayout(grid)
        self.version_message = label('', 'muted')
        layout.addWidget(self.version_message)
        self.check_version = button('Check for Updates', owner.check_source_version, True)
        self.changes = button('View Changes', owner.view_changes)
        self.changes.setEnabled(False)
        layout.addWidget(row(self.check_version, self.changes))
        left.body.addWidget(panel)
        panel, layout = card('Build Options:')
        self.clean = CheckBox('Clean build (remove previous build directory)')
        self.clean.setChecked(True)
        self.update = CheckBox('Update repository before build')
        self.update.setChecked(True)
        self.web_ui = CheckBox('Build web UI with npm (unchecked: CMake downloads the prebuilt UI, needs internet)')
        self.web_ui.setChecked(bool(shutil.which('npm') or shutil.which('npm.cmd')))
        self.web_ui.setToolTip(self.web_ui.text())
        self.core = CheckBox('Core tools only (llama-server, llama-cli, llama-bench, llama-quantize)')
        for checkbox in (self.clean, self.update, self.web_ui, self.core):
            layout.addWidget(checkbox)
        target, jobs = normalize_build_choices(settings)
        self.cpu = SearchCombo(['portable', 'native'])
        self.cpu.setCurrentText(target)
        self.jobs = QSpinBox()
        self.jobs.setRange(1, 4096)
        self.jobs.setValue(jobs)
        layout.addWidget(row(label('CPU target:'), self.cpu, label('Parallel jobs:'), self.jobs))
        layout.addWidget(label('portable = AVX2/FMA/F16C, runs on any CPU since Haswell/Zen 1. '
                               'native = tuned for this PC (AVX-512/AMX), not portable.', 'muted'))
        left.body.addWidget(panel)
        panel, layout = card('Build Output Directory:')
        self.output = LineEdit()
        value = settings.get(BUILD_OUTPUT_DIRECTORY_KEY)
        self.output.setText(value if isinstance(value, str) and value.strip() else BUILDS_DIR)
        self.output.editingFinished.connect(owner.save_output)
        layout.addWidget(row(self.output, button('Browse...', self.browse), button('Reset to Default', self.reset_output)))
        layout.addWidget(label(f'Default: {BUILDS_DIR}', 'muted'))
        left.body.addWidget(panel)
        panel, layout = card()
        self.start = button('Start Build', owner.start_build, True)
        self.start.setMinimumHeight(50)
        layout.addWidget(self.start)
        left.body.addWidget(panel)
        left.body.addStretch()
        panel, layout = card('Live Build Log:')
        self.log = Log()
        layout.addWidget(self.log)
        self.splitter.addWidget(panel)
        self.splitter.setSizes([840, 560])
        self.splitter.setChildrenCollapsible(False)
        self.source.currentTextChanged.connect(owner.source_changed)
        self.profile.currentTextChanged.connect(self.profile_changed)
        self.profile.activated.connect(owner.profile_selected)

    def browse(self):
        value = QFileDialog.getExistingDirectory(self, 'Select Build Output Directory', self.output.text())
        if value:
            self.output.setText(value)
            self.owner.save_output()

    def reset_output(self):
        self.output.setText(BUILDS_DIR)
        self.owner.save_output()

    def profile_changed(self, *_):
        profile = self.owner.selected_profile()
        for key, checkbox in [('clean_build', self.clean), ('update_repo', self.update)]:
            if key in profile:
                checkbox.setChecked(bool(profile[key]))
        disabled = cmake_option_is_off(profile.get('cmake_flags', []), 'LLAMA_BUILD_UI')
        self.web_ui.setEnabled(not disabled)
        if disabled:
            self.web_ui.setChecked(False)
        self.owner.check_source_version()

    def options(self):
        return dict(update_repo_flag=self.update.isChecked(), clean_build=self.clean.isChecked(),
                    build_ui=self.web_ui.isChecked() and self.web_ui.isEnabled(),
                    core_only=self.core.isChecked(), cpu_target=self.cpu.currentText(),
                    jobs=self.jobs.value(), build_output_dir=self.output.text().strip())
