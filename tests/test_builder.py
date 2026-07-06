"""Tests for builder (paths, binary discovery, error explanations) and dependencies."""
import os

import builder
import dependency_checker as dep


class TestBuildPath:
    def test_path_contains_source_and_type(self):
        p = builder.get_build_path("turboquant", "CUDA")
        assert "turboquant" in p
        assert "cuda" in p.lower()


class TestFindBinaries:
    def test_finds_llama_binaries(self, tmp_path):
        d = tmp_path / "build" / "Release"
        d.mkdir(parents=True)
        (d / "llama-server.exe").write_text("x")
        (d / "llama-cli").write_text("x")
        (d / "other.txt").write_text("x")
        found = builder.find_binaries(str(d))
        names = sorted(os.path.basename(f) for f in found)
        assert "llama-server.exe" in names
        assert "llama-cli" in names
        assert "other.txt" not in names

    def test_missing_dir_returns_empty(self):
        assert builder.find_binaries("/no/such/dir") == []


class TestErrorExplanation:
    def _expl(self, msg):
        return builder.get_error_explanation(msg)

    def test_cuda_missing(self):
        e = self._expl("CUDA toolkit not found in PATH")
        assert "CUDA" in e["cause"]

    def test_sycl_missing(self):
        e = self._expl("icpx compiler not found")
        assert "oneAPI" in e["cause"] or "SYCL" in e["cause"] or "Intel" in e["cause"]

    def test_cmake_missing(self):
        e = self._expl("cmake is not recognized as an internal command")
        assert "CMake" in e["cause"]

    def test_unknown_falls_back(self):
        e = self._expl("something completely unexpected happened")
        assert e["cause"] == "Unknown error"


class TestDependencies:
    def test_missing_for_cuda_requires_cuda_toolkit(self):
        results = {"git": {"found": True}, "cmake": {"found": True},
                   "ninja": {"found": True}, "compiler": {"found": True},
                   "cuda_toolkit": {"found": False}}
        missing = dep.get_missing_for_build_type(results, "CUDA")
        assert "cuda_toolkit" in missing

    def test_cpu_build_needs_no_gpu_deps(self):
        results = {"git": {"found": True}, "cmake": {"found": True},
                   "ninja": {"found": True}, "compiler": {"found": True}}
        assert dep.get_missing_for_build_type(results, "CPU") == []

    def test_missing_names_text(self):
        names = dep.get_missing_programs_text(["cmake", "cuda_toolkit"])
        assert "CMake" in names
        assert "CUDA Toolkit" in names
