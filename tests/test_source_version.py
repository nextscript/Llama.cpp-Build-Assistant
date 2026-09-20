import os
import subprocess
from pathlib import Path

import pytest

import source_version


def _git(*args, cwd=None):
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        text=True, encoding="utf-8")
    return result.stdout.strip()


def _repositories(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    output = tmp_path / "builds"
    checkout = output / "b1_cpu_llama.cpp"
    _git("init", "--bare", "--initial-branch=master", str(remote))
    _git("init", "--initial-branch=master", str(work))
    _git("config", "user.name", "Tests", cwd=work)
    _git("config", "user.email", "tests@example.invalid", cwd=work)
    (work / "version.txt").write_text("one", encoding="utf-8")
    _git("add", "version.txt", cwd=work)
    _git("commit", "-m", "first", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("push", "-u", "origin", "master", cwd=work)
    output.mkdir()
    _git("clone", "--branch", "master", str(remote), str(checkout))
    local_commit = _git("rev-parse", "HEAD", cwd=checkout)

    (work / "version.txt").write_text("two", encoding="utf-8")
    _git("commit", "-am", "second", cwd=work)
    _git("push", "origin", "master", cwd=work)
    remote_commit = _git("rev-parse", "HEAD", cwd=work)
    return remote, output, checkout, local_commit, remote_commit


def test_branch_version_check_and_explicit_update(tmp_path):
    remote, output, checkout, local_commit, remote_commit = _repositories(tmp_path)
    source = {
        "id": "main", "type": "official", "repo_url": str(remote),
        "branch": "master",
    }

    result = source_version.check_source_version(source, str(output), "CPU")

    assert result["local_commit"] == local_commit
    assert result["remote_commit"] == remote_commit
    assert result["local_build"] == "b1"
    assert result["remote_build"] == "b2"
    assert result["behind"] == 1
    assert result["status"] == "update_available"
    assert result["update_allowed"]
    assert result["changes"] and "second" in result["changes"][0]
    retained = checkout / "build" / "artifact.bin"
    retained.parent.mkdir()
    retained.write_text("binary", encoding="utf-8")

    updated_path = source_version.update_source_checkout(source, str(checkout))

    assert os.path.basename(updated_path).startswith("b2_cpu_llama.cpp")
    assert _git("rev-parse", "HEAD", cwd=updated_path) == remote_commit
    assert (Path(updated_path) / "build" / "artifact.bin").read_text(
        encoding="utf-8") == "binary"


def test_pinned_source_reports_upstream_but_cannot_update(tmp_path, monkeypatch):
    remote, output, checkout, local_commit, remote_commit = _repositories(tmp_path)
    source = {
        "id": "turboquant", "type": "fork", "repo_url": str(remote),
        "branch": "master", "commit": local_commit,
    }
    monkeypatch.setattr(
        source_version, "find_local_checkout",
        lambda source, build_output_dir, build_type=None: str(checkout))

    result = source_version.check_source_version(source, str(output), "CPU")

    assert result["status"] == "pinned"
    assert not result["update_allowed"]
    assert result["remote_commit"] == remote_commit
    assert result["behind"] == 1
    with pytest.raises(source_version.SourceVersionError, match="Pinned"):
        source_version.update_source_checkout(source, str(checkout))


def test_pr_classification_takes_precedence_over_commit_pin():
    source = {
        "type": "pr", "pr": 17400, "fetch_ref": "pull/17400/head",
        "commit": "abc123",
    }
    assert source_version.source_kind(source) == "pr"


def test_remote_failure_is_reported_without_raising(monkeypatch, tmp_path):
    source = {
        "id": "custom", "type": "custom",
        "repo_url": "https://example.invalid/repo.git", "branch": "main",
    }
    monkeypatch.setattr(source_version, "find_local_checkout", lambda *args: "")
    monkeypatch.setattr(
        source_version, "_ls_remote",
        lambda source: (_ for _ in ()).throw(
            source_version.SourceVersionError("internet unavailable")))

    result = source_version.check_source_version(source, str(tmp_path), "CPU")

    assert result["status"] == "unable"
    assert result["status_text"] == "Unable to check"
    assert "internet unavailable" in result["message"]
    assert not result["update_allowed"]
