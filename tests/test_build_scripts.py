"""Exercise PowerShell helpers without installing tools or compiling llama.cpp."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows helper checks require Windows path semantics")
def test_windows_build_helpers(tmp_path):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is not installed")
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "build workspace with spaces"
    workspace.mkdir()
    result = subprocess.run([
        powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(root / "tests" / "build_helpers.ps1"),
        "-ScriptPath", str(root / "build_llamacpp.ps1"),
        "-Workspace", str(workspace),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Build helper checks passed" in result.stdout


def test_direct_windows_preflight_preserves_existing_build(tmp_path):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is not installed")
    root = Path(__file__).resolve().parents[1]
    build = tmp_path / ("existing_build_" * 5)
    build.mkdir()
    marker = build / "keep.txt"
    marker.write_text("existing build")
    install = tmp_path / "not-created"
    result = subprocess.run([
        powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(root / "build_llamacpp.ps1"), "-Source", "main", "-BuildType", "Vulkan",
        "-InstallDir", str(install), "-BuildDir", str(build), "-CleanBuild",
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "FTK1011/MSB8066" in result.stdout + result.stderr
    assert marker.read_text() == "existing build"
    assert not install.exists()
