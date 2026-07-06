"""
Repository manager module.
Handles cloning, updating, and checking git repositories.
"""
import subprocess
import os
from logger import log_build, log_error


def run_git_command(cmd, cwd=None, callback=None):
    """Run a git command and optionally feed output to callback."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=600
        )
        if result.stdout and callback:
            for line in result.stdout.splitlines():
                callback(line)
        if result.stderr and callback:
            for line in result.stderr.splitlines():
                callback(line)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def clone_repo(repo_url, local_path, branch=None, callback=None, pr=None, submodules=False):
    """Clone a git repository.

    If *pr* is given, the base repo is cloned and the pull request
    refs/pull/<pr>/head is fetched into a local branch 'pr<pr>' and checked
    out (PR-based sources such as diffusion_gemma #24427).
    If *submodules* is True, clone with --recurse-submodules.
    """
    if pr:
        cmd = ["git", "clone", repo_url, local_path]
        log_build(f"Cloning base for PR #{pr}: {repo_url} -> {local_path}")
        if callback:
            callback(f"Cloning base repository for PR #{pr}: {repo_url}")
        success, stdout, stderr = run_git_command(cmd, callback=callback)
        if not success:
            log_error(f"Clone failed: {stderr}")
            if callback:
                callback(f"Clone failed: {stderr[:200]}")
            return success, stdout, stderr
        # Fetch the PR ref and check it out
        pr_branch = f"pr{pr}"
        fetch_cmd = ["git", "fetch", "origin", f"pull/{pr}/head:{pr_branch}"]
        checkout_cmd = ["git", "checkout", pr_branch]
        run_git_command(fetch_cmd, cwd=local_path, callback=callback)
        success2, out2, err2 = run_git_command(checkout_cmd, cwd=local_path, callback=callback)
        if submodules:
            run_git_command(["git", "submodule", "update", "--init", "--recursive"],
                            cwd=local_path, callback=callback)
        return success2, out2, err2

    cmd = ["git", "clone"]
    if submodules:
        cmd += ["--recurse-submodules", "--shallow-submodules"]
    if branch:
        cmd.extend(["-b", branch])
    cmd.extend([repo_url, local_path])

    log_build(f"Cloning: {repo_url} -> {local_path}")
    if callback:
        callback(f"Cloning repository: {repo_url}")

    success, stdout, stderr = run_git_command(cmd, callback=callback)

    if success:
        log_build(f"Repository cloned successfully to {local_path}")
        if callback:
            callback("Repository cloned successfully.")
    else:
        log_error(f"Clone failed: {stderr}")
        if callback:
            callback(f"Clone failed: {stderr[:200]}")

    return success, stdout, stderr


def update_repo(local_path, callback=None):
    """Update an existing git repository."""
    if not os.path.isdir(os.path.join(local_path, ".git")):
        if callback:
            callback(f"Not a git repository: {local_path}")
        return False, "", "Not a git repository"

    cmd = ["git", "pull", "--rebase"]
    log_build(f"Updating: {local_path}")
    if callback:
        callback(f"Updating repository: {local_path}")

    success, stdout, stderr = run_git_command(cmd, cwd=local_path, callback=callback)

    if success:
        log_build(f"Repository updated: {local_path}")
        if callback:
            callback("Repository updated successfully.")
    else:
        log_error(f"Update failed: {stderr}")
        if callback:
            callback(f"Update failed: {stderr[:200]}")

    return success, stdout, stderr


def check_repo_branch(local_path, branch, callback=None):
    """Check if a branch exists in the local repository."""
    cmd = ["git", "branch", "-a", "--list", branch]
    success, stdout, stderr = run_git_command(cmd, cwd=local_path)

    if success and stdout.strip():
        if callback:
            callback(f"Branch '{branch}' exists.")
        return True
    else:
        # Also check remote branches
        cmd2 = ["git", "ls-remote", "--heads", ".", branch]
        success2, stdout2, stderr2 = run_git_command(cmd2, cwd=local_path)
        if success2 and stdout2.strip():
            if callback:
                callback(f"Branch '{branch}' exists on remote.")
            return True

    if callback:
        callback(f"Branch '{branch}' not found.")
    return False


def checkout_branch(local_path, branch, callback=None):
    """Checkout a specific branch."""
    cmd = ["git", "checkout", branch]
    success, stdout, stderr = run_git_command(cmd, cwd=local_path, callback=callback)

    if success:
        if callback:
            callback(f"Checked out branch: {branch}")
    else:
        if callback:
            callback(f"Checkout failed: {stderr[:200]}")

    return success, stdout, stderr


def ensure_repo(repo_url, local_path, branch=None, update=False, callback=None,
                pr=None, submodules=False):
    """
    Ensure a repository exists locally.
    Clones if not present, updates if requested.
    Returns (success, message).
    """
    if os.path.isdir(local_path) and os.path.isdir(os.path.join(local_path, ".git")):
        if update:
            return update_repo(local_path, callback)
        else:
            if callback:
                callback("Repository already exists. Skipping update.")
            return True, "Repository already exists", ""
    else:
        return clone_repo(repo_url, local_path, branch, callback, pr=pr, submodules=submodules)


if __name__ == "__main__":
    print("Repository manager module loaded.")
