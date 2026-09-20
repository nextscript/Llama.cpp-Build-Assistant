"""Git-based version checks and explicit source checkout updates."""
import os
import re
import subprocess
import urllib.error
import urllib.request
import json
from datetime import datetime

from config import ROOT_DIR


class SourceVersionError(RuntimeError):
    """A source version could not be queried or updated."""


def _run(command, timeout=60):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceVersionError(str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise SourceVersionError(detail[-500:])
    return (result.stdout or "").strip()


def _git(repo_path, *args, timeout=60):
    return _run(["git", "-C", repo_path, *args], timeout=timeout)


def source_kind(source):
    """Classify a source, giving PR metadata precedence over a commit pin."""
    if source.get("pr") or source.get("fetch_ref", "").startswith("pull/"):
        return "pr"
    if source.get("commit"):
        return "pinned"
    source_type = str(source.get("type", "custom")).lower()
    if source_type in ("official", "fork", "custom"):
        return source_type
    return "custom"


def find_local_checkout(source, build_output_dir, build_type=None):
    """Find the checkout used for builds, with the legacy source path as fallback."""
    from builder import find_source_checkout

    source_id = source.get("id", "")
    checkout = find_source_checkout(source_id, build_type, build_output_dir)
    if checkout and os.path.isdir(os.path.join(checkout, ".git")):
        return checkout

    legacy_path = source.get("local_path", "")
    if legacy_path:
        if not os.path.isabs(legacy_path):
            legacy_path = os.path.join(ROOT_DIR, legacy_path)
        legacy_path = os.path.abspath(legacy_path)
        if os.path.isdir(os.path.join(legacy_path, ".git")):
            return legacy_path
    return ""


def _github_pr_state(source):
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        source.get("repo_url", ""), re.IGNORECASE)
    if not match or not source.get("pr"):
        return ""
    owner, repository = match.groups()
    url = f"https://api.github.com/repos/{owner}/{repository}/pulls/{source['pr']}"
    request = urllib.request.Request(url, headers={"User-Agent": "LlamaCppBuildAssistant"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("merged_at"):
            return "Merged"
        return "Open" if data.get("state") == "open" else "Closed"
    except (OSError, ValueError, urllib.error.URLError):
        return ""


def _remote_target(source):
    if source_kind(source) == "pr":
        pr_number = source.get("pr")
        fetch_ref = source.get("fetch_ref") or f"pull/{pr_number}/head"
        return fetch_ref, f"refs/{fetch_ref}" if not fetch_ref.startswith("refs/") else fetch_ref
    branch = source.get("branch") or "master"
    return branch, f"refs/heads/{branch}"


def _fetch_remote(repo_path, source):
    target, _ = _remote_target(source)
    if source_kind(source) == "pr":
        _git(repo_path, "fetch", "--force", "origin", target, timeout=120)
    else:
        _git(repo_path, "fetch", "--prune", "origin", target, timeout=120)
    return _git(repo_path, "rev-parse", "FETCH_HEAD")


def _ls_remote(source):
    _, remote_ref = _remote_target(source)
    output = _run(
        ["git", "ls-remote", "--exit-code", source.get("repo_url", ""), remote_ref],
        timeout=60)
    first_line = next((line for line in output.splitlines() if line.strip()), "")
    if not first_line:
        raise SourceVersionError("Remote branch or PR ref not found")
    return first_line.split()[0]


def _commit_date(repo_path, commit):
    timestamp = _git(repo_path, "show", "-s", "--format=%ct", commit)
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%d.%m.%Y")
    except (TypeError, ValueError, OSError):
        return "Unknown"


def check_source_version(source, build_output_dir, build_type=None):
    """Return local/remote Git version information without changing HEAD."""
    kind = source_kind(source)
    pinned = bool(source.get("commit"))
    result = {
        "source_id": source.get("id", ""),
        "kind": kind,
        "pinned": pinned,
        "branch": source.get("branch", "") or "master",
        "pr": source.get("pr"),
        "pr_state": "",
        "local_path": "",
        "local_commit": "",
        "remote_commit": "",
        "local_build": "",
        "remote_build": "",
        "behind": 0,
        "ahead": 0,
        "last_update": "",
        "status": "unable",
        "status_text": "Unable to check",
        "message": "",
        "update_allowed": False,
        "changes": [],
    }

    if kind == "pr":
        result["pr_state"] = _github_pr_state(source)

    checkout = find_local_checkout(source, build_output_dir, build_type)
    result["local_path"] = checkout
    if checkout:
        try:
            local_commit = _git(checkout, "rev-parse", "HEAD")
            result["local_commit"] = local_commit
            result["local_build"] = "b" + _git(checkout, "rev-list", "--count", local_commit)
            result["last_update"] = _commit_date(checkout, local_commit)
        except SourceVersionError as exc:
            result["message"] = f"Local Git checkout could not be read: {exc}"
            return result
    elif pinned:
        result["local_commit"] = str(source.get("commit", ""))

    try:
        remote_commit = (_fetch_remote(checkout, source) if checkout
                         else _ls_remote(source))
        result["remote_commit"] = remote_commit
    except SourceVersionError as exc:
        result["message"] = f"Remote repository unavailable: {exc}"
        if pinned:
            result["status"] = "pinned"
            result["status_text"] = "Pinned version"
        return result

    if checkout:
        try:
            result["remote_build"] = "b" + _git(
                checkout, "rev-list", "--count", result["remote_commit"])
            result["behind"] = int(_git(
                checkout, "rev-list", "--count",
                f"{result['local_commit']}..{result['remote_commit']}"))
            result["ahead"] = int(_git(
                checkout, "rev-list", "--count",
                f"{result['remote_commit']}..{result['local_commit']}"))
            if result["behind"]:
                log_output = _git(
                    checkout, "log", "--format=%h %s", "--max-count=50",
                    f"{result['local_commit']}..{result['remote_commit']}")
                result["changes"] = [line for line in log_output.splitlines() if line]
        except (SourceVersionError, ValueError) as exc:
            result["message"] = f"Commit comparison failed: {exc}"

    if pinned:
        result["status"] = "pinned"
        result["status_text"] = "Pinned version"
        result["update_allowed"] = False
    elif not checkout:
        result["status"] = "not_built"
        result["status_text"] = "No local build"
    elif result["local_commit"] == result["remote_commit"]:
        result["status"] = "up_to_date"
        result["status_text"] = "Up to date"
        result["update_allowed"] = kind != "pr" or result["pr_state"] in ("", "Open")
    else:
        result["status"] = "update_available"
        if kind == "pr":
            result["status_text"] = "New PR commits available"
        elif result["behind"]:
            result["status_text"] = f"{result['behind']} commits behind"
        else:
            result["status_text"] = "Update available"
        result["update_allowed"] = (
            kind != "pr" or result["pr_state"] in ("", "Open"))

    if kind == "pr" and result["pr_state"] in ("Closed", "Merged"):
        result["update_allowed"] = False
    return result


def update_source_checkout(source, checkout):
    """Explicitly update an unpinned branch/PR checkout and retain build files."""
    if source.get("commit"):
        raise SourceVersionError("Pinned sources cannot be updated automatically.")
    if not checkout or not os.path.isdir(os.path.join(checkout, ".git")):
        raise SourceVersionError("No local Git checkout is available to update.")

    remote_commit = _fetch_remote(checkout, source)
    _git(checkout, "reset", "--hard", remote_commit)
    _git(checkout, "clean", "-fdx", "-e", "node_modules", "-e", "build")
    build_count = _git(checkout, "rev-list", "--count", "HEAD")

    parent = os.path.dirname(checkout)
    name = os.path.basename(checkout)
    match = re.match(
        r"^(?:b\d+|bUNKNOWN|pr\d+|pinned_[0-9a-f]+)(?:_run_[0-9_]+)?(_.+)$",
        name)
    updated_path = checkout
    if match:
        new_name = f"b{build_count}{match.group(1)}"
        candidate = os.path.join(parent, new_name)
        if os.path.normcase(candidate) != os.path.normcase(checkout):
            if os.path.exists(candidate):
                stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
                new_name = f"b{build_count}_run_{stamp}{match.group(1)}"
                candidate = os.path.join(parent, new_name)
            os.rename(checkout, candidate)
            updated_path = candidate
    return updated_path
