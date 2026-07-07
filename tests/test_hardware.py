"""Tests for hardware_check — vendor/RDNA4 detection + recommendations."""
import hardware_check as hw


class TestDetectVendor:
    def test_nvidia(self):
        assert hw.detect_vendor("NVIDIA GeForce RTX 4090") == "NVIDIA"
        assert hw.detect_vendor("RTX 5090") == "NVIDIA"

    def test_amd(self):
        assert hw.detect_vendor("AMD Radeon RX 9070 XT") == "AMD"
        assert hw.detect_vendor("Radeon RX 7900 XTX") == "AMD"
        assert hw.detect_vendor("gfx1201") == "AMD"

    def test_intel(self):
        assert hw.detect_vendor("Intel Arc B580") == "Intel"

    def test_unknown(self):
        assert hw.detect_vendor("Mystery GPU") == "Unknown"


class TestRdna4:
    def test_rx9070_is_rdna4(self):
        assert hw.is_rdna4("AMD Radeon RX 9070 XT") is True

    def test_rx7900_is_not_rdna4(self):
        assert hw.is_rdna4("Radeon RX 7900 XTX") is False

    def test_gfx1201_is_rdna4(self):
        assert hw.is_rdna4("gfx1201") is True

    def test_empty(self):
        assert hw.is_rdna4("") is False
        assert hw.is_rdna4(None) is False


class TestRecommendation:
    def _report(self, **kw):
        base = {
            "gpus": [], "has_nvidia": False, "has_amd": False, "has_intel": False,
            "cuda_available": False, "rocm_available": False,
            "sycl_available": False, "vulkan_available": False,
        }
        base.update(kw)
        return {"gpu": base}

    def test_rdna4_forces_vulkan(self):
        report = self._report(gpus=[{"name": "AMD Radeon RX 9070", "vendor": "AMD"}],
                              rocm_available=True)
        assert hw.get_recommendation(report) == "Vulkan"

    def test_cuda_nvidia(self):
        report = self._report(has_nvidia=True, cuda_available=True)
        assert hw.get_recommendation(report) == "CUDA"

    def test_rocm_non_rdna4(self):
        report = self._report(has_amd=True, rocm_available=True,
                              gpus=[{"name": "Radeon RX 7900 XTX", "vendor": "AMD"}])
        assert hw.get_recommendation(report) == "HIP"

    def test_sycl_intel(self):
        report = self._report(has_intel=True, sycl_available=True)
        assert hw.get_recommendation(report) == "SYCL"

    def test_cpu_fallback(self):
        report = self._report()
        assert hw.get_recommendation(report) == "CPU"

    def test_macos_report_uses_metal(self):
        report = {"os": "macOS 15.0", "gpu": {"metal_available": True}}
        assert hw.get_recommendation(report) == "Metal"
