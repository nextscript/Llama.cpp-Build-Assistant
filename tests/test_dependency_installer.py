"""Tests for dependency installer privilege handling."""
from types import SimpleNamespace

import dependency_installer as inst


def test_run_privileged_uses_pkexec_when_sudo_needs_password(monkeypatch):
    commands = []

    monkeypatch.setattr(inst.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        inst.shutil,
        "which",
        lambda name: {"sudo": "/usr/bin/sudo", "pkexec": "/usr/bin/pkexec"}.get(name),
    )
    monkeypatch.setattr(
        inst.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    monkeypatch.setattr(
        inst,
        "run_command",
        lambda cmd, timeout=300: commands.append((cmd, timeout)) or (True, "", ""),
    )

    ok, _, _ = inst.run_privileged("apt update && apt install -y git", timeout=123)

    assert ok is True
    assert commands == [("/usr/bin/pkexec sh -c 'apt update && apt install -y git'", 123)]


def test_run_privileged_uses_cached_sudo_without_prompt(monkeypatch):
    commands = []

    monkeypatch.setattr(inst.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        inst.shutil,
        "which",
        lambda name: {"sudo": "/usr/bin/sudo", "pkexec": "/usr/bin/pkexec"}.get(name),
    )
    monkeypatch.setattr(
        inst.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        inst,
        "run_command",
        lambda cmd, timeout=300: commands.append((cmd, timeout)) or (True, "", ""),
    )

    ok, _, _ = inst.run_privileged("apt install -y cmake")

    assert ok is True
    assert commands == [("/usr/bin/sudo -n sh -c 'apt install -y cmake'", 300)]


def test_run_privileged_fails_loudly_with_safe_manual_command(monkeypatch):
    monkeypatch.setattr(inst.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(inst.shutil, "which", lambda name: None)

    ok, _, err = inst.run_privileged("apt update && apt install -y git")

    assert ok is False
    assert "automatic authentication is not available" in err
    assert "sudo sh -c 'apt update && apt install -y git'" in err


def test_install_missing_callback_includes_failure_reason(monkeypatch):
    lines = []

    monkeypatch.setitem(
        inst.INSTALL_MAP,
        "broken_dep",
        lambda: (False, "", "sudo: a password is required"),
    )

    results = inst.install_missing(["broken_dep"], callback=lines.append)

    assert results["broken_dep"] == (False, "sudo: a password is required")
    assert lines[-1] == "broken_dep: FAILED - sudo: a password is required"
