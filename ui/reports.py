"""Existing report and manual-guide text extracted from the original GUI."""
import platform
from datetime import datetime
from hardware_check import get_recommendation, get_recommendation_reason, recommend_cuda_major
from dependency_installer import get_linux_package_manager
from config import BUILD_TYPE_DISPLAY, BUILD_TYPE_FLAGS

def system_report(report, target="portable"):
    """Update the System Check tab with report data."""
    lines = []
    lines.append("=" * 60)
    lines.append("SYSTEM CHECK REPORT")
    lines.append("=" * 60)
    lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("Operating System:")
    lines.append(f"  {report.get('os', 'Unknown')}")
    lines.append("")

    cpu = report.get("cpu", {})
    lines.append("CPU:")
    lines.append(f"  Model: {cpu.get('name', 'Unknown')}")
    lines.append(f"  Cores: {cpu.get('cores', 0)}")
    lines.append(f"  Threads: {cpu.get('threads', 0)}")
    lines.append(f"  Architecture: {cpu.get('arch') or report.get('arch') or 'unknown'}")
    lines.append(f"  Features: {', '.join(cpu.get('features', [])) or 'None detected'}")
    lines.append("")

    ram = report.get("ram", {})
    lines.append("RAM:")
    lines.append(f"  Total: {ram.get('total_gb', 0)} GB")
    lines.append(f"  Free: {ram.get('free_gb', 0)} GB")
    lines.append("")

    gpu = report.get("gpu", {})
    lines.append("GPU:")
    gpus = gpu.get("gpus", [])
    if gpus:
        for g in gpus:
            extra = ""
            if g.get("compute_cap"):
                extra += f", compute capability {g['compute_cap']}"
            if g.get("unified_memory"):
                extra += ", unified memory"
            lines.append(f"  {g.get('name', 'Unknown')} ({g.get('vendor', 'Unknown')}, "
                         f"{g.get('vram_gb', 0)} GB VRAM{extra})")
    else:
        lines.append("  None detected")
    lines.append("")

    lines.append("GPU Features:")
    lines.append(f"  NVIDIA: {'Yes' if gpu.get('has_nvidia') else 'No'}")
    if gpu.get('nvidia_driver_version'):
        lines.append(f"  Driver Version: {gpu['nvidia_driver_version']}")
    lines.append(f"  CUDA: {'Available' if gpu.get('cuda_available') else 'Not available'}")
    if gpu.get('cuda_version'):
        lines.append(f"  CUDA Toolkit: {gpu['cuda_version']}")
    if gpu.get('nvidia_driver_cuda_version'):
        lines.append(f"  CUDA supported by driver: up to {gpu['nvidia_driver_cuda_version']}"
                     f" (recommended toolkit: {recommend_cuda_major(report)}.x)")
    lines.append(f"  Vulkan: {'Available' if gpu.get('vulkan_available') else 'Not available'}")
    lines.append(f"  ROCm/HIP: {'Available' if gpu.get('rocm_available') else 'Not available'}")
    if gpu.get('amd_gfx_targets'):
        lines.append(f"  AMD gfx targets: {', '.join(gpu['amd_gfx_targets'])}")
    lines.append(f"  SYCL (Intel): {'Available' if gpu.get('sycl_available') else 'Not available'}")
    lines.append("")

    lines.append(f"Free Disk Space: {report.get('free_disk_gb', 0)} GB")
    lines.append("")

    rec = get_recommendation(report)
    lines.append(f"Recommended Build: {BUILD_TYPE_DISPLAY.get(rec, rec)} "
                  f"({BUILD_TYPE_FLAGS.get(rec, '')})")
    lines.append(f"  Why: {get_recommendation_reason(report)}")
    lines.append(f"  {cpu_target_hint(report, target)}")

    return "\n".join(lines)

def cpu_target_hint(report, target="portable"):
    """Explain what the chosen CPU target means for this machine."""
    features = set(report.get("cpu", {}).get("features", []))
    arch = report.get("arch") or report.get("cpu", {}).get("arch") or ""
    if arch == "arm64":
        return "CPU target: native (arm64 uses the compiler's own CPU detection)."
    if target == "native":
        return ("CPU target: native (requests GGML_NATIVE=ON). Detected: "
                + (", ".join(sorted(features)) or "unknown")
                + ". Effective instructions depend on compiler support and profile overrides.")
    if "AVX2" not in features and features:
        return "CPU target: portable (AVX2) - WARNING: this CPU reports no AVX2, choose 'native'."
    unused = [f for f in ("AVX512", "AMX") if f in features]
    if unused:
        return f"CPU target: portable (AVX2). This CPU also has {', '.join(unused)}; choose 'native' to use it."
    return "CPU target: portable (AVX2/FMA/F16C), matches this CPU."

def manual_guide():
    """Show manual installation guide."""
    system = platform.system()
    guide = ""

    if system == "Windows":
        guide = """
MANUAL INSTALLATION GUIDE (Windows)
====================================

Install the following programs manually:

1. Git:
   Download from: https://git-scm.com/download/win
   Or: winget install --id Git.Git -e --source winget

2. CMake:
   Download from: https://cmake.org/download/
   Or: winget install --id Kitware.CMake -e --source winget

3. Visual Studio Build Tools 2022:
   Download from: https://visualstudio.microsoft.com/downloads/
   Select "Desktop development with C++" workload
   Or: winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget

4. Ninja:
   Download from: https://github.com/ninja-build/ninja/releases
   Or: winget install --id Ninja-build.Ninja -e --source winget

5. CUDA Toolkit (for CUDA builds):
   Download from: https://developer.nvidia.com/cuda-downloads

6. Vulkan SDK (for Vulkan builds):
   Download from: https://vulkan.lunarg.com/sdk/home

7. Intel oneAPI Base Toolkit (for SYCL/Intel GPU builds):
   Download from: https://www.intel.com/content/www/us/en/developer/tools/oneapi/base-toolkit-download.html
   Or: winget install Intel.oneAPI.BaseToolkit
"""
    elif system == "Linux":
        pm = get_linux_package_manager()
        if pm == "apt":
            guide = """
MANUAL INSTALLATION GUIDE (Debian/Ubuntu)
==========================================

Run:
  sudo apt update
  sudo apt install -y git cmake build-essential ninja-build

For CUDA:
  Visit: https://developer.nvidia.com/cuda-downloads

For Vulkan SDK:
  sudo apt install -y vulkan-sdk
"""
        elif pm == "dnf":
            guide = """
MANUAL INSTALLATION GUIDE (Fedora)
===================================

Run:
  sudo dnf install -y git cmake gcc gcc-c++ make ninja-build

For CUDA and Vulkan, visit the respective download pages.
"""
        elif pm == "pacman":
            guide = """
MANUAL INSTALLATION GUIDE (Arch Linux)
=======================================

Run:
  sudo pacman -Syu --needed git cmake base-devel ninja

For CUDA and Vulkan, visit the respective download pages.
"""
        else:
            guide = """
MANUAL INSTALLATION GUIDE (Linux)
==================================

Install using your package manager:
  git, cmake, gcc/g++, make, ninja-build

For CUDA: https://developer.nvidia.com/cuda-downloads
For Vulkan: https://vulkan.lunarg.com/sdk/home
"""
    else:
        guide = "Please install Git, CMake, a C/C++ compiler, and Ninja manually."

    return guide.strip()
