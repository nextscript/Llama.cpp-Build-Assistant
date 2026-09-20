import pytest

import hardware_check


@pytest.mark.parametrize("os_support", [False, True])
def test_windows_avx_vnni_requires_os_state_support(monkeypatch, os_support):
    leaves = {
        (1, 0): (0, 0, (1 << 27) | (1 << 28), 0),
        (7, 0): (1, (1 << 5) | (1 << 8), 0, 0),
        (7, 1): (1 << 4, 0, 0, 0),
    }
    monkeypatch.setattr(hardware_check, "_cpuid", lambda leaf, subleaf: leaves[(leaf, subleaf)])
    monkeypatch.setattr(hardware_check, "_windows_avx_state_enabled", lambda: os_support)
    features = hardware_check.detect_cpu_features("Windows")
    assert ("AVX_VNNI" in features) is os_support
    assert ("AVX" in features) is os_support
