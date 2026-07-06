"""Tests for repo_manager — PR fetching + submodule cloning."""
import repo_manager


class TestCloneRepo:
    def test_pr_source_fetches_pr_ref(self, patch_run_git):
        repo_manager.clone_repo("https://github.com/ggml-org/llama.cpp.git",
                                "/tmp/fake", pr=24427, callback=None)
        cmds = [c["cmd"] for c in patch_run_git]
        # First call: plain clone of the base repo
        assert cmds[0][:2] == ["git", "clone"]
        # A fetch of the PR ref must have occurred
        fetch_calls = [c for c in cmds if "fetch" in c and any("pull/24427" in a for a in c)]
        assert fetch_calls, "expected a git fetch of pull/24427/head"
        # A checkout of pr24427 must have occurred
        co = [c for c in cmds if "checkout" in c and "pr24427" in c]
        assert co, "expected checkout of pr24427"

    def test_branch_clone_uses_branch_flag(self, patch_run_git):
        repo_manager.clone_repo("https://example.com/r.git", "/tmp/fake2",
                                branch="feature/turboquant-kv-cache")
        first = patch_run_git[0]["cmd"]
        assert first[:2] == ["git", "clone"]
        assert "-b" in first
        assert "feature/turboquant-kv-cache" in first

    def test_submodules_adds_recurse_flag(self, patch_run_git):
        repo_manager.clone_repo("https://example.com/r.git", "/tmp/fake3",
                                branch="main", submodules=True)
        first = patch_run_git[0]["cmd"]
        assert "--recurse-submodules" in first
