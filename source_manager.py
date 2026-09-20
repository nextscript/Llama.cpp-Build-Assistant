"""
Source manager module.
Manages all llama.cpp sources, forks, branches, and custom repositories.
Reads and writes to sources.json.
"""
import json
import os
import subprocess
from config import BUILD_SOURCES_FILE, LEGACY_BUILD_SOURCES_FILE, REPOS_DIR


class RemoteBranchError(RuntimeError):
    """Raised when branches cannot be read from a remote repository."""


def sort_remote_branches(branches, default_branch=""):
    """Return unique branches with main, master and the remote default first."""
    unique = {branch.strip() for branch in branches if branch and branch.strip()}
    preferred = []
    for branch in ("main", "master", default_branch):
        if branch and branch in unique and branch not in preferred:
            preferred.append(branch)
    return preferred + sorted(unique.difference(preferred), key=str.casefold)


def get_remote_branches(repo_url, timeout=30):
    """Return ``(branches, default_branch)`` without cloning the repository.

    ``--symref`` exposes the symbolic HEAD (when the server supports it), while
    the heads refspec keeps this implementation host-independent.
    """
    repo_url = (repo_url or "").strip()
    if not repo_url:
        raise RemoteBranchError("Invalid repository URL")

    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    git_env["GCM_INTERACTIVE"] = "Never"
    process_options = {}
    if os.name == "nt":
        # GUI builds must not flash a console window for the background Git
        # query (CREATE_NO_WINDOW also covers git.exe child processes).
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
        process_options.update(
            startupinfo=startup_info,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", "--", repo_url,
             "HEAD", "refs/heads/*"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=git_env, **process_options,
        )
    except FileNotFoundError as exc:
        raise RemoteBranchError("Git is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise RemoteBranchError("Repository query timed out") from exc
    except OSError as exc:
        raise RemoteBranchError(f"Could not start Git: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else "Repository unavailable"
        raise RemoteBranchError(message)

    prefix = "refs/heads/"
    branches = []
    default_branch = ""
    for line in result.stdout.splitlines():
        if line.startswith("ref:"):
            fields = line.split()
            if len(fields) >= 3 and fields[2] == "HEAD" and fields[1].startswith(prefix):
                default_branch = fields[1][len(prefix):]
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[1].startswith(prefix):
            branches.append(fields[1][len(prefix):])

    branches = sort_remote_branches(branches, default_branch)
    if not branches:
        raise RemoteBranchError("No remote branches found")
    return branches, default_branch


def load_sources():
    """Load build sources from JSON file. Returns list of source dicts."""
    if os.path.exists(BUILD_SOURCES_FILE):
        try:
            with open(BUILD_SOURCES_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass

    if os.path.exists(LEGACY_BUILD_SOURCES_FILE):
        try:
            with open(LEGACY_BUILD_SOURCES_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    save_sources(data)
                    return data
        except Exception:
            pass

    save_sources([])
    return []


def save_sources(sources):
    """Save build sources to JSON file."""
    os.makedirs(os.path.dirname(BUILD_SOURCES_FILE), exist_ok=True)
    with open(BUILD_SOURCES_FILE, "w") as f:
        json.dump(sources, f, indent=2)


def get_source_by_id(source_id):
    """Get a source dict by its id."""
    sources = load_sources()
    for src in sources:
        if src.get("id") == source_id:
            return src.copy()
    return None


def get_source_by_name(name):
    """Get a source dict by its name."""
    sources = load_sources()
    for src in sources:
        if src.get("name") == name:
            return src.copy()
    return None


def add_source(name, repo_url, branch, local_path=None, source_type="custom",
               experimental=True, default_cmake_flags=None, commit="",
               fetch_ref="", dir_suffix=""):
    """Add a new build source."""
    sources = load_sources()

    # Generate ID from name
    import re
    source_id = re.sub(r'[^a-z0-9_]', '_', name.lower().strip())

    # Check if already exists
    for src in sources:
        if src.get("id") == source_id:
            return False, "Source with this ID already exists"

    if not local_path:
        local_path = os.path.join(REPOS_DIR, source_id)

    new_source = {
        "id": source_id,
        "name": name,
        "repo_url": repo_url,
        "branch": branch,
        "local_path": local_path,
        "type": source_type,
        "experimental": experimental,
        "default_cmake_flags": default_cmake_flags or []
    }
    if commit:
        new_source["commit"] = commit
    if fetch_ref:
        new_source["fetch_ref"] = fetch_ref
    if dir_suffix:
        # Auto-Tuner-compatible output folder suffix (must end in "_llama.cpp").
        new_source["dir_suffix"] = dir_suffix

    sources.append(new_source)
    save_sources(sources)
    return True, "Source added"


def edit_source(source_id, **kwargs):
    """Edit an existing build source. Pass kwargs for fields to change."""
    sources = load_sources()
    for i, src in enumerate(sources):
        if src.get("id") == source_id:
            for key, value in kwargs.items():
                if key in ("commit", "fetch_ref") and not value:
                    src.pop(key, None)
                elif key in src or key in ("commit", "fetch_ref"):
                    src[key] = value
            save_sources(sources)
            return True, "Source updated"
    return False, "Source not found"


def delete_source(source_id):
    """Delete a build source by id."""
    sources = load_sources()
    new_sources = [s for s in sources if s.get("id") != source_id]
    if len(new_sources) == len(sources):
        return False, "Source not found"
    save_sources(new_sources)
    return True, "Source deleted"


def validate_source(source):
    """
    Validate a build source before cloning.
    Returns (valid, message).
    """
    if not source.get("repo_url"):
        return False, "No repository URL configured for this build source."

    if not source.get("branch"):
        return False, "No branch configured for this build source."

    local_path = source.get("local_path", "")
    if not local_path:
        return False, "No local path configured."

    # Check if path is valid (no invalid characters)
    if any(c in local_path for c in ['<', '>', ':', '"', '|', '?', '*']):
        return False, "Local path contains invalid characters."

    return True, "Source is valid"


def check_repo_exists(local_path):
    """Check if a local Git repository exists at the given path."""
    import os
    if not os.path.isdir(local_path):
        return False
    git_dir = os.path.join(local_path, ".git")
    return os.path.isdir(git_dir)


def check_repo_reachable(repo_url):
    """Check if a remote repository is reachable."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", repo_url, "HEAD"],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False


def get_all_source_ids():
    """Return list of all source IDs."""
    sources = load_sources()
    return [s.get("id") for s in sources if s.get("id")]


def get_all_source_names():
    """Return list of all source names."""
    sources = load_sources()
    return [s.get("name") for s in sources if s.get("name")]


def is_experimental(source_id):
    """Check if a source is marked as experimental."""
    source = get_source_by_id(source_id)
    return source is not None and source.get("experimental", False)


def get_default_source():
    """Get the default (main) source. Returns main llama.cpp."""
    return get_source_by_id("main")


if __name__ == "__main__":
    sources = load_sources()
    for s in sources:
        print(f"  {s['id']}: {s['name']} ({s['type']}) experimental={s.get('experimental')}")
