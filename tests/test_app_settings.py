import json
from collections import namedtuple

import pytest

import app_settings


def test_setting_round_trip_preserves_other_values(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"another_setting": True}), encoding="utf-8")

    app_settings.save_setting(
        app_settings.BUILD_OUTPUT_DIRECTORY_KEY, "D:/custom-builds", settings_path)

    assert app_settings.load_settings(settings_path) == {
        "another_setting": True,
        app_settings.BUILD_OUTPUT_DIRECTORY_KEY: "D:/custom-builds",
    }


def test_validate_build_output_directory_creates_and_tests_directory(tmp_path):
    selected = tmp_path / "new" / "builds"

    normalized, free_bytes = app_settings.validate_build_output_directory(
        str(selected), min_free_bytes=0)

    assert normalized == str(selected.resolve())
    assert selected.is_dir()
    assert free_bytes >= 0
    assert list(selected.iterdir()) == []


def test_validate_build_output_directory_rejects_insufficient_space(tmp_path, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(
        app_settings.shutil, "disk_usage", lambda _: Usage(100, 99, 1))

    with pytest.raises(ValueError, match="Not enough free disk space"):
        app_settings.validate_build_output_directory(
            str(tmp_path), min_free_bytes=2)
