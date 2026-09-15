"""Exercise PowerShell helpers without installing tools or compiling llama.cpp."""
from pathlib import Path
import shutil
import subprocess

import pytest


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
