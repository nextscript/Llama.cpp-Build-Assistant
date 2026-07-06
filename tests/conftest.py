"""Shared pytest fixtures.

Redirects the JSON data files used by source_manager / profile_manager /
builder / repo_manager to a temporary directory so tests never touch the
real project data/, builds/, or logs/ folders.
"""
import os
import json
import tempfile

import pytest


@pytest.fixture()
def tmp_project(tmp_path, monkeypatch):
    """Point all config path constants at a temporary project root."""
    import config
    import source_manager
    import profile_manager
    import builder

    data_dir = tmp_path / "data"
    builds_dir = tmp_path / "builds"
    logs_dir = tmp_path / "logs"
    repos_dir = tmp_path / "repos"
    for d in (data_dir, builds_dir, logs_dir, repos_dir):
        d.mkdir(parents=True, exist_ok=True)

    paths = {
        "ROOT_DIR": str(tmp_path),
        "DATA_DIR": str(data_dir),
        "BUILDS_DIR": str(builds_dir),
        "LOGS_DIR": str(logs_dir),
        "REPOS_DIR": str(repos_dir),
        "BUILD_SOURCES_FILE": str(data_dir / "build_sources.json"),
        "BUILD_HISTORY_FILE": str(data_dir / "build_history.json"),
        "SYSTEM_REPORT_FILE": str(data_dir / "system_report.json"),
        "PROFILES_FILE": str(data_dir / "profiles.json"),
    }
    for mod in (config, source_manager, profile_manager, builder):
        for k, v in paths.items():
            if hasattr(mod, k):
                monkeypatch.setattr(mod, k, v)

    # Seed default sources so source_manager has something to load.
    # DEFAULT_BUILD_SOURCES local_path values are absolute at import time
    # (e.g. C:\...\repos\name); convert them to portable relative form.
    sources = []
    for s in config.DEFAULT_BUILD_SOURCES:
        s2 = dict(s)
        lp = s2.get("local_path", "")
        if lp and os.path.isabs(lp):
            parts = lp.replace("\\", "/").split("/")
            if "repos" in parts:
                idx = parts.index("repos")
                s2["local_path"] = "/".join(parts[idx:])
            else:
                s2["local_path"] = os.path.basename(lp.rstrip("/\\"))
        sources.append(s2)
    with open(paths["BUILD_SOURCES_FILE"], "w") as f:
        json.dump(sources, f)

    return paths


@pytest.fixture()
def patch_run_git(monkeypatch):
    """Replace repo_manager.run_git_command with a stub that records calls."""
    import repo_manager
    calls = []

    def fake(cmd, cwd=None, callback=None):
        calls.append({"cmd": list(cmd), "cwd": cwd})
        return True, "", ""

    monkeypatch.setattr(repo_manager, "run_git_command", fake)
    return calls
