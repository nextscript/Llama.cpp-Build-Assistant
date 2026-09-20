import subprocess

import pytest

import source_manager


def test_sort_remote_branches_prioritizes_conventional_and_default():
    result = source_manager.sort_remote_branches(
        ["testing", "develop", "master", "main", "feature/cuda", "develop"],
        "develop",
    )

    assert result == ["main", "master", "develop", "feature/cuda", "testing"]


def test_get_remote_branches_parses_heads_and_symbolic_head(monkeypatch):
    output = """ref: refs/heads/develop\tHEAD
abc123\tHEAD
abc123\trefs/heads/develop
def456\trefs/heads/feature/test
"""
    monkeypatch.setattr(
        source_manager.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, output, ""),
    )

    branches, default_branch = source_manager.get_remote_branches("https://example.test/repo.git")

    assert branches == ["develop", "feature/test"]
    assert default_branch == "develop"


def test_get_remote_branches_reports_missing_git(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(source_manager.subprocess, "run", missing)

    with pytest.raises(source_manager.RemoteBranchError, match="Git is not available"):
        source_manager.get_remote_branches("https://example.test/repo.git")


def test_get_remote_branches_rejects_empty_remote(monkeypatch):
    monkeypatch.setattr(
        source_manager.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    with pytest.raises(source_manager.RemoteBranchError, match="No remote branches found"):
        source_manager.get_remote_branches("https://example.test/empty.git")
