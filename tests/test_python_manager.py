"""Tests for python_manager — version parsing + selection ranking."""
import python_manager as pm


class TestParseVersion:
    def test_full_version(self):
        assert pm.parse_version("3.13.1") == (3, 13, 1)

    def test_minor_only_defaults_patch_zero(self):
        assert pm.parse_version("Python 3.13") == (3, 13, 0)

    def test_prefixed(self):
        assert pm.parse_version("Python 3.14.6") == (3, 14, 6)

    def test_garbage(self):
        assert pm.parse_version("not a version") is None
        assert pm.parse_version("") is None


class TestVersionRank:
    def _p(self, ver, ready=False):
        info = pm.PyInfo("/nonexistent/python", ver, "test")
        info.imports_ok = len(pm.REQUIRED_IMPORTS) if ready else 0
        return pm._version_rank(info)

    def test_ready_beats_not_ready(self):
        ready_312 = self._p((3, 12, 0), ready=True)
        notready_313 = self._p((3, 13, 0), ready=False)
        assert ready_312 > notready_313

    def test_in_range_beats_out_of_range(self):
        in_range = self._p((3, 13, 0), ready=False)
        out_range = self._p((3, 14, 0), ready=False)
        assert in_range > out_range

    def test_newer_in_range_wins(self):
        a = self._p((3, 12, 0), ready=False)
        b = self._p((3, 13, 0), ready=False)
        assert b > a


class TestSelectBest:
    def test_prefers_ready_interpreter(self):
        found = [
            pm.PyInfo("/x/py314", (3, 14, 0), "a"),   # not ready, out of range
            pm.PyInfo("/x/py313", (3, 13, 0), "b"),   # not ready, in range
        ]
        found[0].imports_ok = 0
        found[1].imports_ok = len(pm.REQUIRED_IMPORTS)  # ready
        best = pm.select_best(found)
        assert best is not None
        assert best.version[:2] == (3, 13)

    def test_returns_none_when_nothing_supported(self):
        found = [pm.PyInfo("/x/py38", (3, 8, 0), "old")]
        assert pm.select_best(found) is None

    def test_falls_back_to_stable_range_when_not_ready(self):
        found = [
            pm.PyInfo("/x/py314", (3, 14, 0), "a"),
            pm.PyInfo("/x/py312", (3, 12, 0), "b"),
        ]
        for p in found:
            p.imports_ok = 0
        best = pm.select_best(found)
        assert best is not None
        assert best.version[:2] == (3, 12)
