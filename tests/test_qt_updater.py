"""Updater changes are staged; user data and filesystem boundaries are preserved."""
from pathlib import Path
import pytest
from ui.workers import update_worker as updater


def test_updater_preserves_data_and_applies_downloads(tmp_path, monkeypatch):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'settings.json').write_text('user settings')
    (tmp_path / 'app.py').write_text('old app')
    monkeypatch.setattr(updater, 'ROOT_DIR', str(tmp_path))
    monkeypatch.setattr(updater, 'request', lambda path, raw=False: b'new app')
    count = updater.update_files(['app.py', 'data/settings.json', 'ui/new.py'], lambda _: None)
    assert count == 2
    assert (tmp_path / 'app.py').read_text() == 'new app'
    assert (tmp_path / 'ui' / 'new.py').read_text() == 'new app'
    assert (tmp_path / 'data' / 'settings.json').read_text() == 'user settings'


@pytest.mark.parametrize('filename', ['../outside', '/absolute', 'C:/outside', 'ui/../../outside', '.git/config', 'ui\\..\\outside'])
def test_updater_rejects_unsafe_paths(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(updater, 'ROOT_DIR', str(tmp_path))
    with pytest.raises(ValueError):
        updater.update_files([filename], lambda _: None)


def test_download_failure_does_not_partially_replace_application(tmp_path, monkeypatch):
    (tmp_path / 'app.py').write_text('old app')
    monkeypatch.setattr(updater, 'ROOT_DIR', str(tmp_path))
    def request(path, raw=False):
        if 'fail.py' in path:
            raise OSError('offline')
        return b'new app'
    monkeypatch.setattr(updater, 'request', request)
    with pytest.raises(OSError):
        updater.update_files(['app.py', 'fail.py'], lambda _: None)
    assert (tmp_path / 'app.py').read_text() == 'old app'
