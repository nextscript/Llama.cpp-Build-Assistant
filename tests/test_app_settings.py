import json
from collections import namedtuple

import pytest

import app_settings


@pytest.mark.parametrize("root", [r"C:\b", "C:\\ä b"])
def test_short_vulkan_paths(root):
    app_settings.validate_windows_vulkan_path(root, "Vulkan", system="Windows")


@pytest.mark.parametrize("kwargs", [
    {"root": r"L:\LAB\Llama.cpp-Build-Assistant\builds\validation-v2.3.7"},
    {"root": r"C:\b", "dir_suffix": "custom_" * 20},
    {"root": r"C:\b", "checkout_name": "b" + "1" * 100},
    {"root": r"C:\b", "build_dir": "C:\\" + "deep\\" * 40},
])
def test_vulkan_path_budget_rejects_long_paths(kwargs):
    with pytest.raises(ValueError, match=r"250 characters.*") as error:
        app_settings.validate_windows_vulkan_path(build_type="Vulkan", system="Windows", **kwargs)
    assert "C:\\b" in str(error.value)
    assert "FTK1011/MSB8066" in str(error.value)


def test_path_budget_includes_collision_and_utf16():
    root = "C:\\" + "x" * 10
    app_settings.validate_windows_vulkan_path(root, "Vulkan", system="Windows", checkout_name="b11064_vulkan_llama.cpp")
    with pytest.raises(ValueError):
        app_settings.validate_windows_vulkan_path(root, "Vulkan", system="Windows")
    # Non-BMP characters occupy two Windows UTF-16 code units.
    with pytest.raises(ValueError):
        app_settings.validate_windows_vulkan_path("C:\\" + "😀" * 5, "Vulkan", system="Windows")


@pytest.mark.parametrize("system,backend", [("Linux", "Vulkan"), ("Darwin", "Vulkan"), ("Windows", "HIP"), ("Windows", "CPU")])
def test_other_platforms_and_backends_have_no_vulkan_guard(system, backend):
    app_settings.validate_windows_vulkan_path("x" * 400, backend, system=system)


@pytest.mark.parametrize("settings,expected", [
    ({"cpu_target": "native", "build_jobs": 20}, ("native", 20)),
    ({"cpu_target": "bad", "build_jobs": -1}, ("portable", 8)),
    ({"build_jobs": True}, ("portable", 8)),
    ({"build_jobs": "20"}, ("portable", 8)),
    ({}, ("portable", 8)),
])
def test_build_choices(settings, expected, monkeypatch):
    monkeypatch.setattr(app_settings.os, "cpu_count", lambda: 8)
    assert app_settings.normalize_build_choices(settings) == expected


def test_setting_round_trip_preserves_other_values(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"another_setting": True}), encoding="utf-8")

    app_settings.save_setting(
        app_settings.BUILD_OUTPUT_DIRECTORY_KEY, "D:/custom-builds", settings_path)

    assert app_settings.load_settings(settings_path) == {
        "another_setting": True,
        app_settings.BUILD_OUTPUT_DIRECTORY_KEY: "D:/custom-builds",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"x": 120, "y": 80}, (120, 80)),
        ({"x": -1920, "y": 0}, (-1920, 0)),
        (None, None),
        ({"x": "120", "y": 80}, None),
        ({"x": True, "y": 80}, None),
    ],
)
def test_normalize_window_position(value, expected):
    assert app_settings.normalize_window_position(value) == expected


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
