"""CUDA output defaults must also reach installations migrated previously."""
import copy

from config import DEFAULT_BUILD_PROFILES
import profile_manager


def test_cuda_output_defaults_migrate_once_without_changing_custom_profiles(tmp_path, monkeypatch):
    marker = tmp_path / "already-migrated"
    marker.touch()
    monkeypatch.setattr(profile_manager, "_MIGRATION_MARKER", str(marker))
    default = next(p for p in DEFAULT_BUILD_PROFILES if p["name"] == "CUDA 13.x NVIDIA")
    assert "-DLLAMA_BUILD_TESTS=ON" in default["cmake_flags"]
    old = copy.deepcopy(default)
    old["clean_build"] = False
    old["cmake_flags"] = [f.replace("-DLLAMA_BUILD_TESTS=ON", "-DLLAMA_BUILD_TESTS=OFF")
                          for f in old["cmake_flags"]]
    custom = copy.deepcopy(old)
    custom["cmake_flags"].append("-DCMAKE_CUDA_ARCHITECTURES=89")
    migrated, changed = profile_manager._migrate_profiles([old, custom])
    assert changed
    assert migrated[0]["cmake_flags"] == default["cmake_flags"]
    assert migrated[0]["clean_build"] is False
    assert migrated[1] == custom
    assert old["cmake_flags"] != default["cmake_flags"]
    again, changed = profile_manager._migrate_profiles(migrated)
    assert again == migrated
    assert not changed
