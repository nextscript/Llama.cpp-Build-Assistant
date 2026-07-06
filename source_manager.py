"""
Source manager module.
Manages all llama.cpp sources, forks, branches, and custom repositories.
Reads and writes to build_sources.json.
"""
import json
import os
from config import BUILD_SOURCES_FILE, DEFAULT_BUILD_SOURCES


def load_sources():
    """Load build sources from JSON file. Returns list of source dicts."""
    if os.path.exists(BUILD_SOURCES_FILE):
        try:
            with open(BUILD_SOURCES_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass
    # Default: save defaults and return them
    save_sources(DEFAULT_BUILD_SOURCES)
    return DEFAULT_BUILD_SOURCES.copy()


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


def add_source(name, repo_url, branch, local_path, source_type="custom",
               experimental=True, default_cmake_flags=None):
    """Add a new build source."""
    sources = load_sources()

    # Generate ID from name
    import re
    source_id = re.sub(r'[^a-z0-9_]', '_', name.lower().strip())

    # Check if already exists
    for src in sources:
        if src.get("id") == source_id:
            return False, "Source with this ID already exists"

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

    sources.append(new_source)
    save_sources(sources)
    return True, "Source added"


def edit_source(source_id, **kwargs):
    """Edit an existing build source. Pass kwargs for fields to change."""
    sources = load_sources()
    for i, src in enumerate(sources):
        if src.get("id") == source_id:
            for key, value in kwargs.items():
                if key in src:
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
