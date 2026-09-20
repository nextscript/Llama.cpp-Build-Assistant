"""Native Qt shell with persistent pages and asynchronous backend calls."""
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import QByteArray, QTimer, QUrl, Qt
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QFrame, QStackedWidget, QFileDialog, QMessageBox, QScrollArea)
from config import BUNDLE_DIR, BUILDS_DIR, BUILD_TYPE_DISPLAY, BUILD_TYPE_FLAGS
from app_settings import (load_settings, normalize_window_position,
    validate_build_output_directory, BUILD_OUTPUT_DIRECTORY_KEY)
from ui.settings import save_setting
from source_manager import load_sources, delete_source
from profile_manager import load_profiles, delete_profile
from builder import get_build_history
from hardware_check import run_full_check, select_profile_name, get_recommendation, get_recommendation_reason
from dependency_checker import check_all, get_missing_for_build_type, get_missing_programs_text
from dependency_installer import install_missing, check_after_install
from source_version import check_source_version
from ui.widgets import Page, card, label, button, row, Log
from ui.pages.build_page import BuildPage
from ui.pages.management import ManagementPage, HistoryPage
from ui.dialogs.editors import SourceDialog, ProfileDialog
from ui.dialogs.progress import ProgressDialog, UpdateDialog
from ui.workers.tasks import Tasks
from ui.workers.build_worker import build
from ui.workers.update_worker import check_update, local_version, RELEASES
from ui.reports import system_report, manual_guide, cpu_target_hint


class MainWindow(QMainWindow):
    def __init__(self, auto_start=True):
        super().__init__()
        self.setWindowTitle('Llama.cpp Build Assistant')
        self.resize(1600, 1024)
        self.setMinimumSize(1200, 800)
        self.setWindowIcon(QIcon(str(Path(BUNDLE_DIR) / 'icon.png')))
        self.settings = load_settings()
        self.tasks = Tasks(self)
        self.sources, self.profiles = [], []
        self.hardware_report = None
        self.dependencies = None
        self.is_building = False
        self.hardware_busy = self.dependency_busy = False
        self.profile_manual = False
        self.version_generation = 0
        self.version_result = None
        self.version_key = None
        self.dialogs = []
        self.closing = False
        self.geometry_saved = False
        self.restarting = False
        self.output_generation = 0
        self.version_busy = False
        self.version_pending = False
        self.build_shell()
        self.restore_window()
        self.tasks.idle.connect(self.finish_close)
        self.show_view('Dashboard')
        if auto_start:
            QTimer.singleShot(0, self.reload_data)
            QTimer.singleShot(500, self.run_hardware_check)

    def build_shell(self):
        shell = QWidget()
        shell.setObjectName('shell')
        self.setCentralWidget(shell)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(0)
        top = QWidget()
        top.setFixedHeight(64)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(8, 10, 18, 10)
        logo = label('', wrap=False)
        pixmap = QPixmap(str(Path(BUNDLE_DIR) / 'logo.png'))
        logo.setPixmap(pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        top_layout.addWidget(logo)
        title = label('Llama.cpp Build Assistant', 'appTitle', wrap=False)
        font = title.font()
        font.setPixelSize(20)
        title.setFont(font)
        top_layout.addWidget(title)
        self.status = label('Ready', 'status')
        top_layout.addSpacing(22)
        top_layout.addWidget(self.status)
        top_layout.addStretch()
        layout.addWidget(top)
        body = QHBoxLayout()
        body.setSpacing(10)
        layout.addLayout(body, 1)
        self.sidebar = QFrame()
        self.sidebar.setObjectName('sidebar')
        self.sidebar.setFixedWidth(150)
        nav = QVBoxLayout(self.sidebar)
        nav.setContentsMargins(8, 10, 8, 10)
        nav.setSpacing(5)
        body.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.dashboard = Page('Dashboard')
        panel, content = card('Hardware Overview')
        content.setSpacing(6)
        content.itemAt(0).widget().setMinimumHeight(28)
        self.hardware_labels = {}
        for name in ('CPU', 'RAM', 'GPU', 'CUDA', 'SYCL', 'OS', 'Free Disk'):
            field = label(name + ': Loading...')
            field.setMinimumHeight(28)
            content.addWidget(field)
            self.hardware_labels[name] = field
        self.dashboard.body.addWidget(panel)
        panel, content = card('Recommended Build')
        self.recommendation = label('Running hardware check...')
        self.recommendation.setMinimumHeight(38)
        content.addWidget(self.recommendation)
        self.dashboard.body.addWidget(panel)
        panel, content = card('Selected Source')
        self.current_source = label('main llama.cpp')
        self.current_source.setMinimumHeight(38)
        content.addWidget(self.current_source)
        self.dashboard.body.addWidget(panel)
        self.dashboard.body.addStretch()
        self.system_page = Page('System Check')
        panel, content = card()
        self.hardware_button = button('Run System Check', self.run_hardware_check, True)
        content.addWidget(row(self.hardware_button, button('Export Report', self.export_report)))
        self.system_page.body.addWidget(panel)
        self.system_log = Log()
        self.system_page.body.addWidget(self.system_log, 1)
        self.dependencies_page = Page('Dependencies')
        panel, content = card()
        self.dependency_button = button('Check Dependencies', self.check_dependencies, True)
        content.addWidget(row(self.dependency_button, button('Install Missing', self.install_dependencies, True),
                              button('Show Manual Guide', self.show_manual_guide)))
        self.dependencies_page.body.addWidget(panel)
        self.dependency_log = Log()
        self.dependencies_page.body.addWidget(self.dependency_log, 1)
        self.build_page = BuildPage(self, self.settings)
        self.history_page = HistoryPage(self)
        self.sources_page = ManagementPage(self, 'Sources')
        self.profiles_page = ManagementPage(self, 'Profiles')
        self.update_page = Page('Application Update')
        panel, content = card('Current Version:')
        content.addWidget(label('v' + local_version(), 'subtitle'))
        content.addWidget(label('Repository: nextscript/Llama.cpp-Build-Assistant', 'muted'))
        self.update_page.body.addWidget(panel)
        panel, content = card()
        self.update_button = button('Check for Updates', self.check_updates, True)
        self.update_status = label('')
        content.addWidget(row(self.update_button, self.update_status))
        self.update_page.body.addWidget(panel)
        self.update_page.body.addStretch()
        self.pages = dict(zip(('Dashboard', 'System Check', 'Dependencies', 'Build', 'History', 'Sources', 'Profiles', 'Update'),
            (self.dashboard, self.system_page, self.dependencies_page, self.build_page, self.history_page, self.sources_page, self.profiles_page, self.update_page)))
        self.nav_buttons = {}
        for name, page in self.pages.items():
            self.stack.addWidget(page)
            item = button(name, lambda checked=False, n=name: self.show_view(n))
            item.setObjectName('nav')
            item.style().unpolish(item)
            item.style().polish(item)
            item.setCheckable(True)
            item.setFixedHeight(48)
            nav.addWidget(item)
            self.nav_buttons[name] = item
        nav.addStretch()

    def show_view(self, name):
        self.stack.setCurrentWidget(self.pages[name])
        for key, item in self.nav_buttons.items():
            item.setChecked(key == name)
        if name == 'Build':
            self.check_source_version()
        elif name == 'History':
            self.load_history()

    def error(self, text):
        self.status.setText('Error')
        if not self.closing:
            QMessageBox.warning(self, 'Error', text)

    def selected_source(self):
        name = self.build_page.source.currentText()
        return next((s for s in self.sources if s.get('name') == name), {})

    def selected_profile(self):
        name = self.build_page.profile.currentText()
        return next((p for p in self.profiles if p.get('name') == name), {})

    def reload_data(self):
        if self.closing:
            return
        def loaded(result):
            self.sources, self.profiles = result
            self.sources_page.populate(self.sources)
            self.profiles_page.populate(self.profiles)
            for combo, values in ((self.build_page.source, self.sources), (self.build_page.profile, self.profiles)):
                names = [v['name'] for v in values]
                selected = combo.currentText()
                if selected not in names:
                    selected = names[0] if names else ''
                combo.set_values(names, selected)
            if self.hardware_report and not self.profile_manual:
                name = select_profile_name(self.hardware_report, self.profiles)
                if name:
                    self.build_page.profile.setCurrentText(name)
            self.build_page.profile_changed()
            self.source_changed()
        self.tasks.start(lambda log: (load_sources(), load_profiles()), loaded, self.error)

    def source_changed(self, *_):
        self.current_source.setText(self.selected_source().get('name', 'No source selected'))
        self.check_source_version()

    def profile_selected(self, *_):
        self.profile_manual = True

    def edit_item(self, kind, item=None):
        self.open_dialog((SourceDialog if kind == 'Sources' else ProfileDialog)(self, item))

    def delete_item(self, kind, item):
        singular = 'Source' if kind == 'Sources' else 'Profile'
        if QMessageBox.question(self, 'Delete ' + singular, f"Delete {singular.lower()} '{item['name']}'?") != QMessageBox.StandardButton.Yes:
            return
        delete = delete_source if kind == 'Sources' else delete_profile
        key = item['id'] if kind == 'Sources' else item['name']
        def done(result):
            if result[0]:
                self.reload_data()
            else:
                self.error(result[1])
        self.tasks.start(lambda log: delete(key), done, self.error)

    def open_dialog(self, dialog):
        self.dialogs.append(dialog)
        dialog.finished.connect(lambda _: self.dialogs.remove(dialog) if dialog in self.dialogs else None)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()
        dialog.move(self.frameGeometry().center() - dialog.rect().center())
        return dialog

    def show_text(self, title, text):
        dialog = ProgressDialog(self, title, (760, 520))
        dialog.log.setPlainText(text)
        return self.open_dialog(dialog)

    def run_hardware_check(self):
        if self.hardware_busy or self.closing:
            return
        self.hardware_busy = True
        self.hardware_button.setEnabled(False)
        self.status.setText('Checking hardware...')
        def done(result):
            self.hardware_busy = False
            self.hardware_button.setEnabled(True)
            report, deps = result
            self.hardware_report = report
            cpu, ram, gpu = report.get('cpu', {}), report.get('ram', {}), report.get('gpu', {})
            values = {
                'CPU': f"{cpu.get('name', 'Unknown')} ({cpu.get('cores', 0)} cores, {cpu.get('threads', 0)} threads)",
                'RAM': f"{ram.get('total_gb', 0)} GB total, {ram.get('free_gb', 0)} GB free",
                'GPU': ', '.join(g.get('name', 'Unknown') for g in gpu.get('gpus', [])) or 'None detected',
                'CUDA': f"Available {gpu.get('cuda_version', '')}" if gpu.get('cuda_available') else 'Not available',
                'SYCL': 'Available' if gpu.get('sycl_available') else 'Not available',
                'OS': report.get('os', 'Unknown'), 'Free Disk': f"{report.get('free_disk_gb', 0)} GB"}
            for key, value in values.items():
                self.hardware_labels[key].setText(f'{key}: {value}')
            if not self.profile_manual:
                name = select_profile_name(report, self.profiles)
                if name:
                    self.build_page.profile.setCurrentText(name)
            rec = get_recommendation(report)
            self.recommendation.setText(f"Recommended: {BUILD_TYPE_DISPLAY.get(rec, rec)} Build ({BUILD_TYPE_FLAGS.get(rec, '')})\n"
                f"Profile: {self.build_page.profile.currentText()}\n{get_recommendation_reason(report)}\n"
                + cpu_target_hint(report, self.build_page.cpu.currentText()))
            self.system_log.setPlainText(system_report(report, self.build_page.cpu.currentText()))
            self.display_dependencies(deps)
            self.status.setText('Hardware check complete')
        def failed(message):
            self.hardware_busy = False
            self.hardware_button.setEnabled(True)
            self.error('Hardware check failed: ' + message)
        self.tasks.start(lambda log: (run_full_check(), check_all()), done, failed)

    def check_dependencies(self):
        if self.dependency_busy or self.closing:
            return
        self.dependency_busy = True
        self.dependency_button.setEnabled(False)
        def done(result):
            self.dependency_busy = False
            self.dependency_button.setEnabled(True)
            self.display_dependencies(result)
        def failed(message):
            self.dependency_busy = False
            self.dependency_button.setEnabled(True)
            self.error(message)
        self.tasks.start(lambda log: check_all(), done, failed)

    def display_dependencies(self, results):
        self.dependencies = results
        kind = self.selected_profile().get('build_type', 'CPU')
        lines = ['=' * 60, 'DEPENDENCY CHECK', '=' * 60, '']
        for name, info in results.items():
            status = 'FOUND' if info.get('found') else 'MISSING'
            lines.append(f"  {name:20s} [{status:7s}] {info.get('version') or info.get('path', '')}")
        missing = get_missing_programs_text(get_missing_for_build_type(results, kind))
        lines += ['', f"Missing for {kind} build: {', '.join(missing)}" if missing else f'All dependencies for {kind} build are satisfied!']
        self.dependency_log.setPlainText('\n'.join(lines))

    def install_dependencies(self):
        if self.dependencies is None:
            self.check_dependencies()
            QMessageBox.information(self, 'Dependencies', 'Dependency check started. Please retry when it completes.')
            return
        missing = get_missing_for_build_type(self.dependencies, self.selected_profile().get('build_type', 'CPU'))
        if not missing:
            QMessageBox.information(self, 'Dependencies', 'All dependencies are already installed!')
            return
        if 'cuda_toolkit' in missing:
            if QMessageBox.question(self, 'CUDA Installation Warning', 'Automatic CUDA installation may require a system restart.\nThe CUDA version must match your NVIDIA driver.\n\nDo you want to install CUDA automatically?') != QMessageBox.StandardButton.Yes:
                return
        names = get_missing_programs_text(missing)
        if QMessageBox.question(self, 'Install Missing Dependencies', 'The following programs are missing:\n\n' + '\n'.join(names) + '\n\nShould these programs be installed automatically?') != QMessageBox.StandardButton.Yes:
            return
        dialog = self.open_dialog(ProgressDialog(self, 'Installing Dependencies'))
        dialog.set_busy(True)
        def install(log):
            results = install_missing(missing, callback=log)
            for name, (ok, message) in results.items():
                log(f"{name}: {'OK' if ok else 'FAILED'} {message}")
            return check_after_install()
        def done(results):
            self.display_dependencies(results)
            dialog.log.append('Dependency installation finished.')
            dialog.set_busy(False)
        def failed(message):
            dialog.log.append('Installation failed: ' + message)
            dialog.set_busy(False)
        self.tasks.start(install, done, failed, dialog.log.append)

    def show_manual_guide(self):
        self.tasks.start(lambda log: manual_guide(), lambda text: self.show_text('Manual Installation Guide', text), self.error)

    def export_report(self):
        if not self.hardware_report:
            QMessageBox.information(self, 'Export', 'No hardware report available. Run a system check first.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export Report', 'system_report.json', 'JSON files (*.json)')
        if path:
            report = deepcopy(self.hardware_report)
            self.tasks.start(lambda log: Path(path).write_text(json.dumps(report, indent=2), encoding='utf-8'),
                             lambda _: self.status.setText(f'Report saved to {path}'), self.error)

    def check_source_version(self):
        if not hasattr(self, 'build_page') or self.closing:
            return
        source, profile = deepcopy(self.selected_source()), deepcopy(self.selected_profile())
        output = self.build_page.output.text()
        key = (json.dumps(source, sort_keys=True), output, profile.get('build_type'))
        sender = self.sender()
        force = sender is self.build_page.check_version
        if key == self.version_key and not force:
            return
        self.version_key = key
        self.version_generation += 1
        generation = self.version_generation
        self.version_result = None
        self.build_page.changes.setEnabled(False)
        if not source:
            for field in self.build_page.version.values():
                field.setText('—')
            return
        self.build_page.version['status'].setText('Checking...')
        if self.version_busy:
            self.version_pending = True
            return
        self.version_busy = True
        def done(result):
            if generation != self.version_generation:
                return
            self.version_result = result
            values = dict(result, source_type={'official': 'Normal branch', 'fork': 'Fork', 'custom': 'Custom source', 'pinned': 'Pinned commit', 'pr': f"PR #{result.get('pr', '')}"}.get(result.get('kind'), 'Custom source'), status=result.get('status_text'))
            if result.get('pinned') and result.get('kind') == 'pr':
                values['source_type'] += ' (pinned)'
            if result.get('pr_state'):
                values['source_type'] += ' — ' + result['pr_state']
            for key, widget in self.build_page.version.items():
                value = values.get(key) or 'Not available'
                widget.setText(value[:9] if key.endswith('_commit') and values.get(key) else value)
            details = [result.get('message', '')]
            if result.get('pinned'):
                details.append('This source is pinned and will never be moved automatically.')
            if result.get('behind'):
                details.append(f"{result['behind']} newer commits available.")
            if result.get('ahead'):
                details.append(f"The local checkout is {result['ahead']} commits ahead of the remote target.")
            self.build_page.version_message.setText(' '.join(details))
            self.build_page.changes.setEnabled(bool(result.get('changes')))
        def failed(message):
            if generation == self.version_generation:
                self.build_page.version['status'].setText('Unable to check')
                self.build_page.version_message.setText(message)
                self.version_key = None
        def finish(result=None, error=None):
            self.version_busy = False
            if error is not None:
                failed(error)
            else:
                done(result)
            if self.version_pending:
                self.version_pending = False
                self.version_key = None
                self.check_source_version()
        self.tasks.start(lambda log: check_source_version(source, output, profile.get('build_type')),
                         lambda result: finish(result=result), lambda message: finish(error=message))

    def view_changes(self):
        self.show_text('Available Source Changes', '\n'.join((self.version_result or {}).get('changes', [])) or 'No new commits are available to display.')

    def save_output(self):
        if self.closing:
            return
        value = self.build_page.output.text()
        self.output_generation += 1
        generation = self.output_generation
        def validate(log):
            normalized, _ = validate_build_output_directory(value)
            save_setting(BUILD_OUTPUT_DIRECTORY_KEY, normalized)
            return normalized
        def done(normalized):
            if generation == self.output_generation:
                self.build_page.output.setText(normalized)
                self.check_source_version()
        self.tasks.start(validate, done, self.error)

    def start_build(self):
        if self.is_building or self.closing:
            return
        source, profile = deepcopy(self.selected_source()), deepcopy(self.selected_profile())
        if not source or not source.get('repo_url'):
            self.error('Please select a valid build source with a repository URL.')
            return
        if not profile:
            self.error('Please select a valid build profile.')
            return
        options = self.build_page.options()
        if options['cpu_target'] not in ('portable', 'native'):
            self.error('Please select a valid CPU target.')
            return
        self.is_building = True
        self.build_page.start.setEnabled(False)
        self.build_page.start.setText('Building...')
        self.build_page.log.clear()
        self.status.setText('Building...')
        def reset():
            self.is_building = False
            self.build_page.start.setEnabled(True)
            self.build_page.start.setText('Start Build')
            self.version_key = None
            self.check_source_version()
            self.load_history()
        def done(result):
            reset()
            self.status.setText('Build successful!' if result['success'] else 'Build failed')
        def failed(message):
            reset()
            self.build_page.log.append('Unexpected error: ' + message)
            self.status.setText('Build error')
        self.tasks.start(lambda log: build(source, profile, options, log), done, failed, self.build_page.log.append)

    def load_history(self):
        if not self.closing:
            self.tasks.start(lambda log: get_build_history(), self.history_page.populate, self.error)

    def check_updates(self):
        if getattr(sys, 'frozen', False):
            QDesktopServices.openUrl(QUrl(RELEASES))
            return
        self.update_button.setEnabled(False)
        self.update_status.setText('Checking for updates...')
        def done(result):
            self.update_button.setEnabled(True)
            self.update_status.setText('Update available!' if result['available'] else 'Up to date.')
            if result['available'] and not self.closing:
                self.open_dialog(UpdateDialog(self, result))
        def failed(message):
            self.update_button.setEnabled(True)
            self.update_status.setText('Update check failed: ' + message)
        self.tasks.start(check_update, done, failed)

    def restore_window(self):
        geometry = self.settings.get('qt_geometry')
        if isinstance(geometry, str):
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode('ascii', errors='ignore')))
        else:
            position = normalize_window_position(self.settings.get('window_position'))
            if position:
                self.move(*position)
        if not any(screen.availableGeometry().intersects(self.frameGeometry()) for screen in QApplication.screens()):
            self.move(QApplication.primaryScreen().availableGeometry().topLeft())
        sizes = self.settings.get('qt_build_splitter')
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(v, int) and v > 0 for v in sizes):
            self.build_page.splitter.setSizes(sizes)

    def closeEvent(self, event):
        if self.geometry_saved:
            event.accept()
            return
        if self.is_building or any(getattr(dialog, 'busy', False) for dialog in self.dialogs):
            self.status.setText('Please wait for the active operation to finish before closing.')
            event.ignore()
            return
        event.ignore()
        if self.closing:
            return
        self.closing = True
        self.centralWidget().setEnabled(False)
        self.status.setText('Closing...')
        self.finish_close()

    def finish_close(self):
        if not self.closing or self.tasks.active or self.geometry_saved:
            return
        geometry = bytes(self.saveGeometry().toBase64()).decode('ascii')
        rect = self.normalGeometry()
        sizes = self.build_page.splitter.sizes()
        def save(log):
            save_setting('qt_geometry', geometry)
            save_setting('qt_build_splitter', sizes)
            save_setting('window_position', {'x': rect.x(), 'y': rect.y()})
        def done(_):
            self.geometry_saved = True
            # The task has finished its work; defer closing until its QThread is reaped.
        def failed(message):
            self.closing = False
            self.centralWidget().setEnabled(True)
            self.error('Could not save window position: ' + message)
        self.tasks.idle.disconnect(self.finish_close)
        def saved_idle():
            self.tasks.idle.disconnect(saved_idle)
            self.tasks.idle.connect(self.finish_close)
            if self.geometry_saved:
                self.close()
                if self.restarting:
                    os.execl(sys.executable, sys.executable, str(Path(BUNDLE_DIR) / 'app.py'))
        self.tasks.idle.connect(saved_idle)
        self.tasks.start(save, done, failed)

    def restart(self):
        self.restarting = True
        self.close()
