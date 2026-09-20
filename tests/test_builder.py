"""Regression tests for output selection and the executable verification gate."""
import base64
import io
import json
import os
from unittest.mock import Mock

import pytest

import builder


@pytest.mark.parametrize("backend, replies, ok", [
    ("CPU", [(1, "missing DLL")], False),
    ("CPU", [(0, "version: test"), (1, "device probe failed")], False),
    ("CPU", [(0, "version: test"), (0, "ggml_cpu: init\nAvailable devices:\n")], True),
    ("CUDA", [(0, "version: test"), (0, "Available devices:\n")], False),
    ("HIP", [(0, "version: test"), (0, "ROCm0: AMD Radeon\n")], True),
    ("Vulkan", [(0, "version: test"), (0, "Vulkan0: AMD Radeon\nROCm0: AMD Radeon\n")], False),
    ("CPU", [(0, "version: test"), (0, "CUDA0: NVIDIA\n")], False),
])
def test_verification_gate(monkeypatch, backend, replies, ok):
    run = Mock(side_effect=replies)
    monkeypatch.setattr(builder, "_run_binary", run)
    result = builder.verify_build(["llama-server.exe"], backend)
    assert result["ok"] is ok
    if not ok:
        assert result["warnings"]
    if backend == "CPU" and ok:
        assert result["devices"] == []


def test_server_must_be_the_executable(monkeypatch):
    run = Mock()
    monkeypatch.setattr(builder, "_run_binary", run)
    assert not builder.verify_build(["llama-server.cpp"], "CPU")["ok"]
    run.assert_not_called()


def test_source_lookup_does_not_match_other_forks(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "BUILDS_DIR", str(tmp_path))
    monkeypatch.setattr(builder, "get_source_by_id", lambda _: {"id": "main"})
    main = tmp_path / "b10000_vulkan_llama.cpp"
    main.mkdir()
    fork = tmp_path / "b10001_vulkan_tq_llama.cpp"
    fork.mkdir()
    os.utime(fork, (2000000000, 2000000000))
    assert builder.find_source_checkout("main", "Vulkan") == str(main)


@pytest.mark.parametrize("valid", [False, True])
def test_build_uses_reported_output_and_keeps_complete_checkout(tmp_path, monkeypatch, valid):
    monkeypatch.setattr(builder, "BUILDS_DIR", str(tmp_path))
    monkeypatch.setattr(builder, "get_source_by_id", lambda _: {"id": "main"})
    # Avoid the windowed-console compatibility wrapper touching pytest streams.
    monkeypatch.setattr("sys.stdout", None)
    checkout = tmp_path / "b10000_cpu_llama.cpp"
    binary = checkout / "build" / "bin" / "llama-server.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    source = checkout / "CMakeLists.txt"
    source.write_text("source", encoding="utf-8")
    retained = [".git/config", "tools/ui/dist/index.html", "src/llama.cpp",
                "build/CMakeCache.txt", "build/llama.sln", "build/src/Release/llama.lib",
                "build/bin/Release/nvrtc64_130_0.dll"]
    for name in retained:
        path = checkout / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")
    other = tmp_path / "b10001_cpu_tq_llama.cpp"
    other.mkdir()
    os.utime(other, (2000000000, 2000000000))
    process = Mock(returncode=0, stdout=io.StringIO(
        f"LLAMA_BUILD_OUTPUT={checkout / 'build'}\n"))
    monkeypatch.setattr(builder.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(builder, "_run_binary", Mock(side_effect=(
        [(0, "version: test"), (0, "Available devices:\n")] if valid
        else [(1, "missing DLL")]
    )))
    result = builder.run_build("main", "CPU")
    assert result[0] is valid
    assert result[4] == str(checkout)
    assert source.read_text(encoding="utf-8") == "source"
    for name in retained:
        assert (checkout / name).read_text(encoding="utf-8") == name
    command = builder.subprocess.Popen.call_args.args[0]
    assert "-Targets" not in command and "-T" not in command
    assert binary.exists()
    assert other.exists()


@pytest.mark.parametrize("marker", ["", "relative/build"])
def test_missing_output_cannot_reuse_old_binaries(tmp_path, monkeypatch, marker):
    monkeypatch.setattr(builder, "BUILDS_DIR", str(tmp_path))
    monkeypatch.setattr(builder, "get_source_by_id", lambda _: {"id": "main"})
    monkeypatch.setattr("sys.stdout", None)
    process = Mock(returncode=0, stdout=io.StringIO(f"LLAMA_BUILD_OUTPUT={marker}\n"))
    monkeypatch.setattr(builder.subprocess, "Popen", Mock(return_value=process))
    verify = Mock()
    monkeypatch.setattr(builder, "verify_build", verify)
    result = builder.run_build("main", "CPU")
    assert not result[0]
    verify.assert_not_called()


def test_windows_profile_flags_are_transferred_losslessly(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "BUILDS_DIR", str(tmp_path))
    monkeypatch.setattr(builder, "get_source_by_id", lambda _: {"id": "main"})
    monkeypatch.setattr(builder.platform, "system", lambda: "Windows")
    monkeypatch.setattr("sys.stdout", None)
    checkout = tmp_path / "b10000_cpu_llama.cpp"
    binary = checkout / "build" / "bin" / "llama-server.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    process = Mock(returncode=0, stdout=io.StringIO(
        f"LLAMA_BUILD_OUTPUT={checkout / 'build'}\n"))
    monkeypatch.setattr(builder.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(builder, "_run_binary", Mock(side_effect=[
        (0, "version: test"), (0, "Available devices:\n")]))
    flags = ["-DFOO=ON", "-DCMAKE_CXX_FLAGS=-O3 -march=native",
             "-DCMAKE_CUDA_ARCHITECTURES=75;89"]

    result = builder.run_build("main", "CPU", custom_flags=flags)

    assert result[0]
    command = builder.subprocess.Popen.call_args.args[0]
    assert "-ExtraFlags" not in command
    value = command[command.index("-ExtraFlagsBase64") + 1]
    decoded = [base64.b64decode(item).decode("utf-8") for item in value.split(",")]
    assert decoded == flags


def test_build_output_directory_is_passed_per_invocation(tmp_path, monkeypatch):
    default_dir = tmp_path / "default-builds"
    custom_dir = tmp_path / "custom-builds"
    custom_dir.mkdir()
    monkeypatch.setattr(builder, "BUILDS_DIR", str(default_dir))
    monkeypatch.setattr(builder, "get_source_by_id", lambda _: {"id": "main"})
    monkeypatch.setattr("sys.stdout", None)
    checkout = custom_dir / "b10000_cpu_llama.cpp"
    binary = checkout / "build" / "bin" / "llama-server.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    process = Mock(returncode=0, stdout=io.StringIO(
        f"LLAMA_BUILD_OUTPUT={checkout / 'build'}\n"))
    monkeypatch.setattr(builder.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(builder, "_run_binary", Mock(side_effect=[
        (0, "version: test"), (0, "Available devices:\n")]))

    result = builder.run_build(
        "main", "CPU", build_output_dir=str(custom_dir))

    assert result[0]
    assert result[4] == str(checkout)
    command = builder.subprocess.Popen.call_args.args[0]
    directory_flag = "-InstallDir" if "-InstallDir" in command else "-d"
    assert command[command.index(directory_flag) + 1] == str(custom_dir)
    assert builder.BUILDS_DIR == str(default_dir)


def test_build_history_records_exact_source_version(tmp_path, monkeypatch):
    history_path = tmp_path / "build_history.json"
    monkeypatch.setattr(builder, "BUILD_HISTORY_FILE", str(history_path))
    monkeypatch.setattr(builder, "get_source_by_id", lambda _: {
        "name": "llama.cpp mainline", "repo_url": "https://example.invalid/repo",
        "branch": "master",
    })
    version_info = {
        "build_number": "b10871",
        "commit": "5f5fea56d5a39f603e5d2f57e7701b206861564d",
    }

    builder.save_build_result(
        "main", "CPU", True, "builds/b10871_cpu_llama.cpp",
        version_info=version_info)

    entry = json.loads(history_path.read_text(encoding="utf-8"))[0]
    assert entry["build_number"] == "b10871"
    assert entry["commit"] == version_info["commit"]
    assert entry["branch"] == "master"
