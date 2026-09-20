"""Qt regression tests: thread delivery, backend integration, persistence and dialogs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import threading
import time
from pathlib import Path
import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox
from ui.theme import apply_theme
from ui.main_window import MainWindow
from ui.workers.tasks import Tasks
from ui.workers import build_worker
from ui.dialogs.editors import SourceDialog, ProfileDialog
import ui.main_window as main
import ui.dialogs.editors as editors


@pytest.fixture(scope='session')
def qt():
    app = QApplication.instance() or QApplication([])
    font = Path('C:/Windows/Fonts/segoeui.ttf')
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    apply_theme(app)
    return app


def until(qt, predicate, timeout=5):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        qt.processEvents()
        time.sleep(.002)
    qt.processEvents()
    assert predicate(), 'Timed out waiting for Qt task'


@pytest.fixture
def window(qt, monkeypatch):
    monkeypatch.setattr(main, 'load_settings', lambda: {})
    monkeypatch.setattr(main, 'get_build_history', lambda: [])
    monkeypatch.setattr(main, 'check_source_version', lambda *a: {'status_text': 'Up to date', 'changes': ['commit']})
    w = MainWindow(auto_start=False)
    yield w
    until(qt, lambda: not w.tasks.active)
    w.geometry_saved = True
    w.close()
    w.deleteLater()
    qt.processEvents()


def seed(window):
    window.sources = [{'id': 'test', 'name': 'Test Source', 'repo_url': 'https://example.com/repo', 'branch': 'main'}]
    window.profiles = [{'name': 'Test CPU', 'build_type': 'CPU', 'cmake_flags': ['-DLLAMA_BUILD_UI=OFF']}]
    window.build_page.source.set_values(['Test Source'], 'Test Source')
    window.build_page.profile.set_values(['Test CPU'], 'Test CPU')


def test_pages_are_persistent_and_layout_matches(window, qt):
    assert list(window.pages) == ['Dashboard', 'System Check', 'Dependencies', 'Build', 'History', 'Sources', 'Profiles', 'Update']
    identities = [id(p) for p in window.pages.values()]
    assert window.size().width() == 1600
    assert window.size().height() == 1024
    assert window.sidebar.width() == 150
    for _ in range(3):
        for name, page in window.pages.items():
            window.show_view(name)
            assert window.stack.currentWidget() is page
            assert window.nav_buttons[name].isChecked()
    assert identities == [id(p) for p in window.pages.values()]


def test_worker_delivery_and_error_are_on_gui_thread(qt):
    tasks = Tasks()
    gui_thread = QThread.currentThread()
    values, failures, logs = [], [], []
    def work(log):
        assert QThread.currentThread() != gui_thread
        log('line 1')
        log('line 2')
        return 42
    def result(value):
        assert QThread.currentThread() == gui_thread
        values.append(value)
    tasks.start(work, result, failures.append, logs.append)
    until(qt, lambda: not tasks.active)
    assert values == [42]
    assert logs == ['line 1\nline 2']
    assert failures == []
    tasks.start(lambda log: 1 / 0, error=failures.append)
    until(qt, lambda: not tasks.active)
    assert 'division by zero' in failures[0]


def test_large_log_is_bounded_and_navigation_remains_responsive(window, qt):
    beat = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: beat.append(time.monotonic()))
    timer.start()
    def work(log):
        for n in range(20000):
            log(f'build line {n}')
            if n % 1000 == 0:
                time.sleep(.01)
    window.tasks.start(work, log=window.build_page.log.append)
    window.show_view('Build')
    window.show_view('Dashboard')
    until(qt, lambda: not window.tasks.active)
    timer.stop()
    assert window.build_page.log.document().blockCount() == 5000
    assert window.build_page.log.toPlainText().endswith('build line 19999')
    assert len(beat) > 5
    assert window.stack.currentWidget() is window.dashboard


@pytest.mark.parametrize('success', [True, False])
def test_build_calls_existing_backend_and_records_result(monkeypatch, success):
    calls, saves, logs = [], [], []
    monkeypatch.setattr(build_worker, 'validate_build_output_directory', lambda p: (p, 100))
    monkeypatch.setattr(build_worker, 'validate_windows_vulkan_path', lambda *a: None)
    monkeypatch.setattr(build_worker, 'save_setting', lambda *a: None)
    monkeypatch.setattr(build_worker, 'get_checkout_version', lambda p: {'commit': 'abc'})
    monkeypatch.setattr(build_worker, 'save_build_result', lambda *a: saves.append(a))
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        kwargs['callback']('compiler line')
        return success, ['error: compiler failed'], '' if success else 'compiler failed', ['server'], 'C:/build'
    monkeypatch.setattr(build_worker, 'run_build', run)
    options = dict(cpu_target='native', jobs=4, build_output_dir='C:/build', update_repo_flag=True,
                   clean_build=False, build_ui=False, core_only=True)
    result = build_worker.build({'id': 'main'}, {'build_type': 'CUDA', 'cuda_major': '13', 'cmake_flags': ['-DGGML_CUDA=ON']}, options, logs.append)
    assert result['success'] is success
    assert calls[0][0] == ('main', 'CUDA')
    assert calls[0][1]['custom_flags'] == ['-DGGML_CUDA=ON']
    assert calls[0][1]['cuda_major'] == '13'
    assert calls[0][1]['jobs'] == 4
    assert saves[0][2] is success
    assert any(('BUILD SUCCESSFUL!' if success else 'BUILD FAILED!') in line for line in logs)


@pytest.mark.parametrize('success', [True, False, None])
def test_build_ui_recovers_for_success_failure_and_exception(window, qt, monkeypatch, success):
    seed(window)
    def run(source, profile, options, log):
        assert QThread.currentThread() != qt.thread()
        log('compiler line')
        if success is None:
            raise RuntimeError('test failure')
        return {'success': success}
    monkeypatch.setattr(main, 'build', run)
    window.start_build()
    assert window.is_building
    assert not window.build_page.start.isEnabled()
    until(qt, lambda: not window.tasks.active)
    assert not window.is_building
    assert window.build_page.start.isEnabled()
    assert window.status.text() == {True: 'Build successful!', False: 'Build failed', None: 'Build error'}[success]
    assert 'compiler line' in window.build_page.log.toPlainText()


def test_profile_disables_npm_when_explicitly_off(window, qt):
    seed(window)
    window.build_page.web_ui.setChecked(True)
    window.build_page.profile_changed()
    assert not window.build_page.web_ui.isChecked()
    assert not window.build_page.web_ui.isEnabled()


def test_stale_branch_results_and_closed_dialog_are_ignored(window, qt, monkeypatch):
    first = threading.Event()
    def branches(url):
        if url.endswith('/old'):
            first.wait(2)
            return ['old'], 'old'
        return ['main', 'feature'], 'main'
    monkeypatch.setattr(editors, 'get_remote_branches', branches)
    dialog = SourceDialog(window)
    dialog.fields['repo_url'].setText('https://example.com/old')
    dialog.timer.stop()
    dialog.load_branches()
    dialog.fields['repo_url'].setText('https://example.com/new')
    dialog.timer.stop()
    dialog.load_branches()
    until(qt, lambda: dialog.branches == ['main', 'feature'])
    first.set()
    until(qt, lambda: not window.tasks.active)
    assert dialog.branch.currentText() == 'main'
    dialog.load_branches()
    dialog.reject()
    until(qt, lambda: not window.tasks.active)
    assert dialog.closed


def test_source_add_and_edit_use_backend(window, qt, monkeypatch):
    calls = []
    monkeypatch.setattr(window, 'reload_data', lambda: None)
    monkeypatch.setattr(editors, 'add_source', lambda **kw: (calls.append(kw) is None, 'added'))
    monkeypatch.setattr(editors, 'edit_source', lambda key, **kw: (calls.append((key, kw)) is None, 'saved'))
    for source in [None, {'id': 'custom', 'name': 'Existing', 'repo_url': '', 'branch': 'old'}]:
        dialog = SourceDialog(window, source)
        dialog.fields['name'].setText('Custom')
        dialog.fields['repo_url'].setText('https://example.com/custom')
        dialog.fields['commit'].setText('abc')
        dialog.fields['fetch_ref'].setText('pull/1/head')
        dialog.branch.setCurrentText('feature')
        dialog.timer.stop()
        dialog.save()
        until(qt, lambda: not window.tasks.active)
        assert dialog.result() == dialog.DialogCode.Accepted
    assert calls[0]['commit'] == 'abc'
    assert calls[0]['branch'] == 'feature'
    assert calls[1][0] == 'custom'
    assert calls[1][1]['fetch_ref'] == 'pull/1/head'


def test_profile_add_and_edit_use_backend(window, qt, monkeypatch):
    calls = []
    monkeypatch.setattr(window, 'reload_data', lambda: None)
    monkeypatch.setattr(editors, 'add_profile', lambda name, **kw: (calls.append((name, kw)) is None, 'added'))
    monkeypatch.setattr(editors, 'edit_profile', lambda profile_name, **kw: (calls.append((profile_name, kw)) is None, 'saved'))
    for profile in [None, {'name': 'Old', 'build_type': 'CPU', 'cmake_flags': []}]:
        dialog = ProfileDialog(window, profile)
        dialog.name.setText('Custom')
        dialog.kind.setCurrentText('Vulkan')
        dialog.flags.setPlainText('-DGGML_VULKAN=ON\n-DGGML_LTO=OFF')
        dialog.save()
        until(qt, lambda: not window.tasks.active)
        assert dialog.result() == dialog.DialogCode.Accepted
    assert calls[0][0] == 'Custom'
    assert calls[1][0] == 'Old'
    assert calls[1][1]['name'] == 'Custom'
    assert calls[0][1]['cmake_flags'] == ['-DGGML_VULKAN=ON', '-DGGML_LTO=OFF']


def test_delete_actions(window, qt, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(main, 'delete_source', lambda key: (calls.append(key) is None, 'deleted'))
    monkeypatch.setattr(main, 'delete_profile', lambda key: (calls.append(key) is None, 'deleted'))
    monkeypatch.setattr(window, 'reload_data', lambda: None)
    window.delete_item('Sources', {'id': 'src', 'name': 'Source'})
    window.delete_item('Profiles', {'name': 'Profile'})
    until(qt, lambda: not window.tasks.active)
    assert sorted(calls) == ['Profile', 'src']


def test_window_state_saved_without_losing_settings(window, qt, tmp_path, monkeypatch):
    import app_settings
    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps({'custom': 'keep', 'build_output_directory': 'D:/builds'}))
    monkeypatch.setattr(main, 'save_setting', lambda k, v: app_settings.save_setting(k, v, str(settings)))
    window.show()
    window.resize(1280, 900)
    window.move(30, 40)
    qt.processEvents()
    window.close()
    until(qt, lambda: window.geometry_saved and not window.tasks.active)
    stored = json.loads(settings.read_text())
    assert stored['custom'] == 'keep'
    assert stored['build_output_directory'] == 'D:/builds'
    assert stored['qt_geometry']
    assert len(stored['qt_build_splitter']) == 2
    monkeypatch.setattr(main, 'load_settings', lambda: stored)
    reopened = MainWindow(auto_start=False)
    assert reopened.minimumWidth() <= reopened.width() <= 1280
    assert reopened.minimumHeight() <= reopened.height() <= 900
    reopened.geometry_saved = True
    reopened.close()


def test_hardware_and_dependency_results(window, qt, monkeypatch):
    report = {'os': 'Windows', 'cpu': {'name': 'Test CPU', 'features': ['AVX2']}, 'ram': {'total_gb': 32}, 'gpu': {'gpus': []}}
    deps = {'git': {'found': True, 'version': '2.0'}}
    monkeypatch.setattr(main, 'run_full_check', lambda: report)
    monkeypatch.setattr(main, 'check_all', lambda: deps)
    window.run_hardware_check()
    until(qt, lambda: not window.tasks.active)
    assert 'Test CPU' in window.hardware_labels['CPU'].text()
    assert 'SYSTEM CHECK REPORT' in window.system_log.toPlainText()
    assert window.dependencies == deps
    window.check_dependencies()
    until(qt, lambda: not window.tasks.active)
    assert window.dependency_button.isEnabled()


def test_update_check_and_error(window, qt, monkeypatch):
    monkeypatch.setattr(main, 'check_update', lambda log: {'available': False})
    window.check_updates()
    until(qt, lambda: not window.tasks.active)
    assert window.update_status.text() == 'Up to date.'
    def fail(log):
        raise OSError('offline')
    monkeypatch.setattr(main, 'check_update', fail)
    window.check_updates()
    until(qt, lambda: not window.tasks.active)
    assert 'offline' in window.update_status.text()
    assert window.update_button.isEnabled()



def test_source_checks_coalesce_rapid_selection_changes(window, qt, monkeypatch):
    seed(window)
    calls = []
    release = threading.Event()
    def check(source, output, kind):
        calls.append(source['branch'])
        if len(calls) == 1:
            release.wait(2)
        return {'branch': source['branch'], 'status_text': 'Up to date'}
    monkeypatch.setattr(main, 'check_source_version', check)
    window.check_source_version()
    until(qt, lambda: calls == ['main'])
    for n in range(20):
        window.sources[0]['branch'] = f'branch-{n}'
        window.check_source_version()
    release.set()
    until(qt, lambda: not window.tasks.active)
    assert calls == ['main', 'branch-19']
    assert window.build_page.version['branch'].text() == 'branch-19'


def test_dependency_installation_uses_worker(window, qt, monkeypatch):
    window.dependencies = {'git': {'found': False}}
    monkeypatch.setattr(main, 'get_missing_for_build_type', lambda *a: ['git'])
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    def install(missing, callback):
        assert QThread.currentThread() != qt.thread()
        callback('installing git')
        return {'git': (True, 'installed')}
    monkeypatch.setattr(main, 'install_missing', install)
    monkeypatch.setattr(main, 'check_after_install', lambda: {'git': {'found': True}})
    window.install_dependencies()
    dialog = window.dialogs[-1]
    assert dialog.busy
    until(qt, lambda: not window.tasks.active)
    assert not dialog.busy
    assert window.dependencies['git']['found']
    assert 'installing git' in dialog.log.toPlainText()
    dialog.reject()


def test_output_directory_validation_runs_off_gui_thread(window, qt, monkeypatch):
    saved = []
    def validate(path):
        assert QThread.currentThread() != qt.thread()
        return 'D:/normalized', 100
    monkeypatch.setattr(main, 'validate_build_output_directory', validate)
    monkeypatch.setattr(main, 'save_setting', lambda k, v: saved.append((k, v)))
    window.build_page.output.setText('D:/chosen')
    window.save_output()
    until(qt, lambda: not window.tasks.active)
    assert window.build_page.output.text() == 'D:/normalized'
    assert ('build_output_directory', 'D:/normalized') in saved


def test_searchable_dropdown_filters_and_selects(window, qt):
    from PySide6.QtCore import Qt
    combo = window.build_page.source
    combo.set_values(['main', 'feature/cuda', 'fix/cuda', 'vulkan'])
    combo.completer().setCompletionPrefix('cuda')
    assert combo.completer().completionCount() == 2
    combo.setCurrentText('feature/cuda')
    assert combo.currentText() == 'feature/cuda'
    assert combo.completer().filterMode() == Qt.MatchFlag.MatchContains
