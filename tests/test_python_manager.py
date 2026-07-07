"""Tests for python_manager — version parsing + base interpreter selection.

The interpreter selection now picks the newest base interpreter inside the
supported range (3.9–3.14) to build the project virtualenv from. Base
"readiness" (whether deps already import) is no longer a selection factor,
because the dependencies are always installed into the project venv — so the
tests check range/newest ordering rather than a ready/not-ready ranking.
"""
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


class TestSelectBest:
    def _p(self, ver):
        return pm.PyInfo("/nonexistent/python", ver, "test")

    def test_prefers_newest_in_range(self):
        found = [self._p((3, 12, 0)), self._p((3, 14, 2)), self._p((3, 13, 0))]
        best = pm.select_best(found)
        assert best is not None
        assert best.version[:2] == (3, 14)

    def test_newer_in_range_beats_older_in_range(self):
        found = [self._p((3, 12, 0)), self._p((3, 13, 0))]
        best = pm.select_best(found)
        assert best is not None
        assert best.version[:2] == (3, 13)

    def test_prefers_in_range_over_out_of_range(self):
        # 3.15 is above PREFERRED_MAX (3.14); 3.13 is in range -> 3.13 wins.
        found = [self._p((3, 15, 0)), self._p((3, 13, 0))]
        best = pm.select_best(found)
        assert best is not None
        assert best.version[:2] == (3, 13)

    def test_returns_none_when_nothing_supported(self):
        found = [self._p((3, 8, 0))]
        assert pm.select_best(found) is None

    def test_falls_back_to_out_of_range_when_nothing_in_range(self):
        # 3.8 below MIN (rejected); 3.15 above range but supported -> fallback.
        found = [self._p((3, 8, 0)), self._p((3, 15, 0))]
        best = pm.select_best(found)
        assert best is not None
        assert best.version[:2] == (3, 15)
