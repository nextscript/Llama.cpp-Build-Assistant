"""
Hardware detection module.
Detects CPU, RAM, GPU, CUDA, Vulkan, ROCm/HIP, Metal, OS, and free disk space.
Works on Windows, Linux, and macOS.
"""
import subprocess
import platform
import os
import json
import ctypes
from datetime import datetime
from config import SYSTEM_REPORT_FILE


def run_cmd(cmd, shell=True):
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                shell=shell, timeout=30, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def run_powershell(cmd):
    """Run a PowerShell command and return stdout, or None on failure."""
    try:
        ps_cmd = ["powershell", "-Command", cmd]
        result = subprocess.run(ps_cmd, capture_output=True, text=True,
                                timeout=30, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ─── OS detection ────────────────────────────────────────────────────────
def get_os_info():
    """Detect operating system and version."""
    system = platform.system()
    version = platform.version()
    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
            # CurrentBuild >= 22000 means Windows 11. The "ProductName" value
            # still reads "Windows 10 Pro" on many Windows 11 installs, so we
            # derive the marketing name from the build number instead.
            try:
                build = int(winreg.QueryValueEx(key, "CurrentBuildNumber")[0])
            except Exception:
                build = 0
            try:
                edition = winreg.QueryValueEx(key, "EditionID")[0]
            except Exception:
                edition = ""
            try:
                display = winreg.QueryValueEx(key, "DisplayVersion")[0]
            except Exception:
                display = ""
            major_name = "Windows 11" if build >= 22000 else "Windows 10"
            parts = [major_name]
            if edition:
                parts.append(edition)
            if display:
                parts.append(display)
            parts.append(f"build {build}")
            return " ".join(parts) if parts else f"Windows {version}"
        except Exception:
            return f"Windows {version}"
    elif system == "Linux":
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        name = line.split("=", 1)[1].strip().strip('"')
                        return f"{name} {version}"
        except Exception:
            pass
        return f"{system} {version}"
    elif system == "Darwin":
        try:
            prod = run_cmd("sw_vers -productName") or "macOS"
            ver = run_cmd("sw_vers -productVersion") or version
            build = run_cmd("sw_vers -buildVersion") or ""
            return f"{prod} {ver} {build}".strip()
        except Exception:
            return f"macOS {version}"
    else:
        return f"{system} {version}"


# ─── CPUID (Windows x86_64) ──────────────────────────────────────────────
# Reads the CPU feature flags directly via the CPUID instruction using a tiny
# slab of x86_64 machine code (VirtualAlloc+RWX). This is the only reliable
# way to learn AVX/AVX2/AVX512/FMA/F16C/AMX on Windows without native deps.
# Everything is wrapped so that any failure degrades gracefully to an empty
# feature list instead of crashing or mis-reporting features.
_CPUID_CODE = bytes([
    0x53,                         # push rbx
    0x89, 0xD0,                   # mov eax, edx        (leaf, arg2)
    0x44, 0x89, 0xC1,             # mov ecx, r8d        (subleaf, arg3)
    0x0F, 0xA2,                   # cpuid
    0x89, 0x01,                   # mov [rcx],    eax   out[0]
    0x89, 0x59, 0x04,             # mov [rcx+4],  ebx   out[1]
    0x89, 0x49, 0x08,             # mov [rcx+8],  ecx   out[2]
    0x89, 0x51, 0x0C,             # mov [rcx+12], edx   out[3]
    0x5B,                         # pop rbx
    0xC3,                         # ret
])

_cpuid_func = None


def _get_cpuid():
    """Lazy-build a callable CPUID function (Windows x86_64 only)."""
    global _cpuid_func
    if _cpuid_func is not None:
        return _cpuid_func
    if platform.system() != "Windows" or platform.machine() not in ("AMD64", "x86_64"):
        return None
    try:
        import ctypes
        PAGE_EXECUTE_READWRITE = 0x40
        MEM_COMMIT = 0x1000
        MEM_RELEASE = 0x8000
        kernel32 = ctypes.windll.kernel32
        buf = kernel32.VirtualAlloc(None, len(_CPUID_CODE), MEM_COMMIT, PAGE_EXECUTE_READWRITE)
        if not buf:
            return None
        ctypes.memmove(buf, _CPUID_CODE, len(_CPUID_CODE))
        prototype = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_uint32),
                                     ctypes.c_uint32, ctypes.c_uint32)
        _cpuid_func = prototype(buf)

        # Keep references alive so the buffer is never freed while callable.
        _cpuid_func._keepalive = (kernel32, buf)

        # Best-effort: never release (process lifetime is short). Attempting a
        # cleanup helper risks calling VirtualFree with the wrong prototype.
        return _cpuid_func
    except Exception:
        return None


def _cpuid(leaf, subleaf=0):
    """Run CPUID(leaf, subleaf) and return (eax, ebx, ecx, edx) or None."""
    fn = _get_cpuid()
    if fn is None:
        return None
    try:
        out = (ctypes.c_uint32 * 4)()
        fn(out, leaf, subleaf)
        return int(out[0]), int(out[1]), int(out[2]), int(out[3])
    except Exception:
        return None


# ─── /proc parsers (Linux, no /sys dependency) ───────────────────────────
def _parse_proc_cpuinfo():
    """Parse /proc/cpuinfo into a list of per-processor dicts."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            text = f.read()
    except Exception:
        return []
    procs = []
    cur = {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                procs.append(cur)
                cur = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    if cur:
        procs.append(cur)
    return procs


def _parse_proc_meminfo():
    """Return (MemTotal_kb, MemAvailable_kb) from /proc/meminfo."""
    total_kb = 0
    avail_kb = 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
    except Exception:
        pass
    return total_kb, avail_kb


def _linux_drm_vram():
    """Return VRAM bytes for each AMD card from /sys/class/drm (sorted desc)."""
    import glob
    vals = []
    for card in sorted(glob.glob("/sys/class/drm/card*/device/mem_info_vram_total")):
        try:
            with open(card, "r") as f:
                vals.append(int(f.read().strip()))
        except Exception:
            pass
    return sorted(vals, reverse=True)


# ─── CPU detection ───────────────────────────────────────────────────────
def get_cpu_info():
    """Detect CPU model, cores, and threads."""
    system = platform.system()
    cpu_name = "Unknown"
    cores = 0
    threads = 0

    if system == "Windows":
        ps_output = run_powershell(
            "Get-CimInstance -ClassName Win32_Processor | "
            "Select-Object -Property Name, NumberOfCores, NumberOfLogicalProcessors | "
            "ConvertTo-Json")
        if ps_output:
            try:
                cpu_data = json.loads(ps_output)
                if isinstance(cpu_data, list):
                    cpu_data = cpu_data[0]
                cpu_name = cpu_data.get("Name", "Unknown")
                cores = cpu_data.get("NumberOfCores", 0) or 0
                threads = cpu_data.get("NumberOfLogicalProcessors", 0) or 0
            except Exception:
                pass

        if cpu_name == "Unknown":
            cpu_name = run_cmd("wmic cpu get name")
            if cpu_name:
                cpu_name = cpu_name.split("\n")[-1].strip()
        if cores == 0:
            cores = os.cpu_count() or 0
        if threads == 0:
            threads = os.cpu_count() or 0

    elif system == "Darwin":
        cpu_name = run_cmd("sysctl -n machdep.cpu.brand_string") or "Unknown"
        phys = run_cmd("sysctl -n hw.physicalcpu")
        log = run_cmd("sysctl -n hw.logicalcpu")
        cores = int(phys) if phys and phys.isdigit() else (os.cpu_count() or 0)
        threads = int(log) if log and log.isdigit() else (os.cpu_count() or 0)

    else:  # Linux — parse /proc/cpuinfo (works without /sys, unlike lscpu)
        info = _parse_proc_cpuinfo()
        if info:
            cpu_name = info[0].get("model name", "Unknown")
            threads = len(info)
            sockets = len({p.get("physical id", "0") for p in info})
            try:
                cores_per_socket = int(info[0].get("cpu cores", "1"))
            except ValueError:
                cores_per_socket = 1
            cores = cores_per_socket * sockets
        # Fall back to lscpu if /proc/cpuinfo was empty/unreadable
        if cpu_name == "Unknown":
            cpu_name_line = run_cmd("lscpu | grep 'Model name'")
            if cpu_name_line:
                cpu_name = cpu_name_line.split(":")[-1].strip()
        if threads <= 0:
            threads = os.cpu_count() or 0
        if cores <= 0:
            cores = os.cpu_count() or 0

    return {
        "name": cpu_name,
        "cores": cores,
        "threads": threads,
        "features": detect_cpu_features(system)
    }


def detect_cpu_features(system):
    """Detect CPU instruction set features (accurate, never mis-reports)."""
    features = []

    if system == "Windows":
        l1 = _cpuid(1, 0)
        l7 = _cpuid(7, 0)
        if l1:
            eax1, ebx1, ecx1, edx1 = l1
            osxsave = bool(ecx1 & (1 << 27))
            avx = bool(ecx1 & (1 << 28))
            if avx and osxsave:
                features.append("AVX")
            if ecx1 & (1 << 12):
                features.append("FMA")
            if ecx1 & (1 << 29):
                features.append("F16C")
        if l7 and "AVX" in features:
            eax7, ebx7, ecx7, edx7 = l7
            if ebx7 & (1 << 5):
                features.append("AVX2")
            if ebx7 & (1 << 16):
                features.append("AVX512")
            if edx7 & (1 << 23):   # AMX-TILE
                features.append("AMX")

    elif system == "Darwin":
        # Intel Macs expose x86 feature flags via sysctl. Apple Silicon has
        # none of these (compute goes through Metal), so the list stays empty.
        feats = (run_cmd("sysctl -n machdep.cpu.features") or "").upper()
        leaf7 = (run_cmd("sysctl -n machdep.cpu.leaf7_features") or "").upper()
        if "AVX1.0" in feats or " AVX " in feats:
            features.append("AVX")
        if "FMA" in feats:
            features.append("FMA")
        if "F16C" in feats:
            features.append("F16C")
        if "AVX2" in leaf7:
            features.append("AVX2")
        if "AVX512" in leaf7:
            features.append("AVX512")

    else:  # Linux
        cpuinfo = run_cmd("cat /proc/cpuinfo")
        if cpuinfo:
            cl = cpuinfo.lower()
            if "avx " in cl or "avx\n" in cl:
                features.append("AVX")
            if "avx2" in cl:
                features.append("AVX2")
            if "avx512" in cl or "avx-512" in cl:
                features.append("AVX512")
            if "fma" in cl:
                features.append("FMA")
            if "f16c" in cl:
                features.append("F16C")
            if "amx" in cl:
                features.append("AMX")

    return features


# ─── RAM detection ───────────────────────────────────────────────────────
def get_ram_info():
    """Detect total and free RAM."""
    system = platform.system()

    if system == "Windows":
        ps_output = run_powershell(
            "Get-CimInstance -ClassName Win32_OperatingSystem | "
            "Select-Object -Property TotalVisibleMemorySize, FreePhysicalMemory | "
            "ConvertTo-Json")
        if ps_output:
            try:
                ram_data = json.loads(ps_output)
                total_kb = ram_data.get("TotalVisibleMemorySize", 0) or 0
                free_kb = ram_data.get("FreePhysicalMemory", 0) or 0
                return {
                    "total_gb": round(total_kb / 1024 / 1024, 1),
                    "free_gb": round(free_kb / 1024 / 1024, 1)
                }
            except Exception:
                pass
        total_str = run_cmd("wmic computersystem get totalphysicalmemory")
        total_bytes = 0
        if total_str:
            try:
                total_bytes = int(total_str.split("\n")[-1].strip())
            except Exception:
                total_bytes = 0
        return {"total_gb": round(total_bytes / (1024 ** 3), 1), "free_gb": 0}

    elif system == "Darwin":
        total = run_cmd("sysctl -n hw.memsize")
        total_bytes = int(total) if total and total.isdigit() else 0
        page_size = run_cmd("sysctl -n hw.pagesize")
        ps = int(page_size) if page_size and page_size.isdigit() else 4096
        free_bytes = 0
        vm = run_cmd("vm_stat") or ""
        for line in vm.split("\n"):
            if line.lower().startswith("pages free"):
                num = "".join(ch for ch in line.split(":")[-1] if ch.isdigit())
                try:
                    free_bytes = int(num) * ps
                except Exception:
                    free_bytes = 0
                break
        return {
            "total_gb": round(total_bytes / (1024 ** 3), 1),
            "free_gb": round(free_bytes / (1024 ** 3), 1)
        }

    else:  # Linux — parse /proc/meminfo (works without /sys, unlike free)
        total_kb, avail_kb = _parse_proc_meminfo()
        if total_kb:
            return {
                "total_gb": round(total_kb / 1024 / 1024, 1),
                "free_gb": round((avail_kb or total_kb) / 1024 / 1024, 1)
            }
        free_out = run_cmd("free -k | grep Mem")
        if free_out:
            parts = free_out.split()
            try:
                total_kb = int(parts[1])
                free_kb = int(parts[3])
                return {
                    "total_gb": round(total_kb / 1024 / 1024, 1),
                    "free_gb": round(free_kb / 1024 / 1024, 1)
                }
            except Exception:
                pass
    return {"total_gb": 0, "free_gb": 0}


# ─── GPU detection ───────────────────────────────────────────────────────
def get_gpu_info():
    """Detect GPU(s), VRAM, and vendor."""
    system = platform.system()
    gpus = []
    has_nvidia = False
    has_amd = False
    has_intel = False
    has_apple = False
    nvidia_driver_version = ""
    cuda_available = False
    cuda_version = ""
    vulkan_available = False
    vulkan_sdk = False
    opencl_available = False
    rocm_available = False
    sycl_available = False
    metal_available = False

    if system == "Windows":
        ps_output = run_powershell(
            "Get-CimInstance -ClassName Win32_VideoController | "
            "Select-Object -Property Name, AdapterRAM | ConvertTo-Json")
        if ps_output:
            try:
                gpu_data = json.loads(ps_output)
                if not isinstance(gpu_data, list):
                    gpu_data = [gpu_data]
                for gpu in gpu_data:
                    name = gpu.get("Name", "Unknown")
                    vram_bytes = gpu.get("AdapterRAM", 0) or 0
                    # NOTE: AdapterRAM is uint32 and wraps at 4 GiB, so it is
                    # only a hint here; accurate VRAM is read per-vendor below.
                    gpus.append({
                        "name": name,
                        "vendor": detect_vendor(name),
                        "vram_gb": round(vram_bytes / (1024 ** 3), 1) if vram_bytes else 0
                    })
            except Exception:
                pass

        if not gpus:
            gpu_out = run_cmd("wmic path win32_VideoController get name")
            if gpu_out:
                for line in gpu_out.split("\n"):
                    line = line.strip()
                    if line and "Controller" not in line and "Name" not in line:
                        gpus.append({"name": line, "vendor": detect_vendor(line), "vram_gb": 0})

        nvidia_smi = run_cmd("nvidia-smi --query-gpu=name,driver_version --format=csv,noheader")
        if nvidia_smi:
            has_nvidia = True
            for line in nvidia_smi.split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    nvidia_driver_version = parts[1]
                    if gpus and "NVIDIA" in parts[0]:
                        gpus[0]["name"] = parts[0]

        nvcc = run_cmd("nvcc --version")
        if nvcc:
            cuda_available = True
            for part in nvcc.split("\n"):
                if "release" in part:
                    cuda_version = part.strip().split()[-1]
                    break

        if run_cmd("vulkaninfo --summary 2>nul"):
            vulkan_available = True
        if run_cmd("glslangValidator --version 2>nul"):
            vulkan_sdk = True
        else:
            _vulkan_sdk_env = os.environ.get("VULKAN_SDK", "")
            if _vulkan_sdk_env and os.path.isfile(os.path.join(_vulkan_sdk_env, "Bin", "glslangValidator.exe")):
                vulkan_sdk = True

        if run_cmd("hipconfig --version 2>nul") or run_cmd("hipcc --version 2>nul"):
            rocm_available = True

        if run_cmd("icpx --version 2>nul") or run_cmd("icx --version 2>nul"):
            sycl_available = True

        if run_cmd("clinfo 2>nul"):
            opencl_available = True

        for gpu in gpus:
            vendor = gpu.get("vendor")
            if vendor == "AMD":
                has_amd = True
            elif vendor == "Intel":
                has_intel = True

    elif system == "Darwin":
        # system_profiler is the only reliable GPU source on macOS.
        sp = run_cmd("system_profiler SPDisplaysDataType")
        if sp:
            import re
            for block in re.split(r"\n\s*\n", sp):
                model = re.search(r"Chipset Model:\s*(.+)", block)
                vram = re.search(r"VRAM .*?:\s*([0-9]+)\s*MB", block)
                metal = re.search(r"Metal:\s*(Supported,.+)", block)
                name = model.group(1).strip() if model else "Unknown"
                vram_gb = round(int(vram.group(1)) / 1024, 1) if vram else 0
                vendor = detect_vendor(name)
                if vendor == "Unknown" and "apple" in name.lower():
                    vendor = "Apple"
                gpus.append({"name": name, "vendor": vendor, "vram_gb": vram_gb})
        metal_available = True  # Metal is always available on modern macOS.
        if run_cmd("nvcc --version 2>/dev/null"):
            cuda_available = True
            for part in (run_cmd("nvcc --version") or "").split("\n"):
                if "release" in part:
                    cuda_version = part.strip().split()[-1]
                    break
        if run_cmd("vulkaninfo --summary 2>/dev/null"):
            vulkan_available = True
        for gpu in gpus:
            vendor = gpu.get("vendor")
            if vendor == "NVIDIA":
                has_nvidia = True
            elif vendor == "AMD":
                has_amd = True
            elif vendor == "Intel":
                has_intel = True
            elif vendor == "Apple":
                has_apple = True

    else:  # Linux
        lspci = run_cmd("lspci 2>/dev/null | grep -iE 'vga|3d|display'")
        if lspci:
            for line in lspci.split("\n"):
                if line.strip():
                    gpus.append({"name": line.strip(), "vendor": detect_vendor(line), "vram_gb": 0})

        nvidia_smi = run_cmd("nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null")
        if nvidia_smi:
            has_nvidia = True
            for line in nvidia_smi.split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    nvidia_driver_version = parts[1]
                    if gpus and "NVIDIA" in parts[0]:
                        gpus[0]["name"] = parts[0]

        nvcc = run_cmd("nvcc --version 2>/dev/null")
        if nvcc:
            cuda_available = True
            for part in nvcc.split("\n"):
                if "release" in part:
                    cuda_version = part.strip().split()[-1]
                    break

        if run_cmd("vulkaninfo --summary 2>/dev/null"):
            vulkan_available = True
        if run_cmd("glslangValidator --version 2>/dev/null"):
            vulkan_sdk = True
        elif run_cmd("test -d /usr/include/vulkan && echo yes"):
            vulkan_sdk = True

        if run_cmd("rocminfo 2>/dev/null | head -1") or run_cmd("hipcc --version 2>/dev/null"):
            rocm_available = True

        if run_cmd("icpx --version 2>/dev/null") or run_cmd("icx --version 2>/dev/null"):
            sycl_available = True

        if run_cmd("clinfo 2>/dev/null") or os.path.isdir("/etc/OpenCL/vendors"):
            opencl_available = True

        for gpu in gpus:
            vendor = gpu.get("vendor")
            if vendor == "NVIDIA":
                has_nvidia = True
            elif vendor == "AMD":
                has_amd = True
            elif vendor == "Intel":
                has_intel = True

    # Accurate VRAM per vendor (replaces the unreliable AdapterRAM hint).
    amd_vram_list = _linux_drm_vram() if system == "Linux" else []
    amd_idx = 0
    for gpu in gpus:
        name = gpu.get("name", "")
        if "NVIDIA" in name:
            vram = run_cmd("nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits")
            if vram:
                try:
                    gpu["vram_gb"] = round(int(vram.split("\n")[0].strip()) / 1024, 1)
                except ValueError:
                    gpu["vram_gb"] = gpu.get("vram_gb", 0)
        elif system == "Linux" and gpu.get("vendor") == "AMD" and amd_idx < len(amd_vram_list):
            # Best-effort: assign /sys/class/drm VRAM values to AMD GPUs in order.
            gpu["vram_gb"] = round(amd_vram_list[amd_idx] / (1024 ** 3), 1)
            amd_idx += 1

    return {
        "gpus": gpus,
        "has_nvidia": has_nvidia,
        "has_amd": has_amd,
        "has_intel": has_intel,
        "has_apple": has_apple,
        "nvidia_driver_version": nvidia_driver_version,
        "cuda_available": cuda_available,
        "cuda_version": cuda_version,
        "vulkan_available": vulkan_available,
        "vulkan_sdk": vulkan_sdk,
        "opencl_available": opencl_available,
        "rocm_available": rocm_available,
        "sycl_available": sycl_available,
        "metal_available": metal_available
    }


def detect_vendor(gpu_line):
    """Detect GPU vendor from a GPU name string."""
    gpu_lower = gpu_line.lower()
    if "nvidia" in gpu_lower or "geforce" in gpu_lower or "rtx" in gpu_lower or "gtx" in gpu_lower:
        return "NVIDIA"
    elif "amd" in gpu_lower or "radeon" in gpu_lower or "rx " in gpu_lower or "gfx" in gpu_lower:
        return "AMD"
    elif "intel" in gpu_lower:
        return "Intel"
    elif "apple" in gpu_lower:
        return "Apple"
    return "Unknown"


def is_rdna4(gpu_name):
    """Detect AMD RDNA4 (Radeon RX 9000 series / gfx120x).

    RDNA4 GPUs have very poor/buggy ROCm (HIP) support; the recommended and
    proven backend for them is Vulkan with a recent SPIRV-Headers build.
    """
    if not gpu_name:
        return False
    low = gpu_name.lower()
    if "rx 90" in low or "radeon rx 9" in low or "9070" in low or "9 900" in low:
        return True
    if "gfx1200" in low or "gfx1201" in low:
        return True
    if "rdna4" in low:
        return True
    return False


def has_rdna4_gpu(report):
    """True if any GPU in the report is an AMD RDNA4 part."""
    gpus = report.get("gpu", {}).get("gpus", [])
    return any(is_rdna4(g.get("name", "")) for g in gpus)


def get_free_disk_space(path=None):
    """Get free disk space in GB for the given path or system drive."""
    if path is None:
        path = os.getcwd()
    try:
        if platform.system() == "Windows":
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path), None, None, ctypes.pointer(free_bytes))
            return round(free_bytes.value / (1024 ** 3), 1)
        else:
            stat = os.statvfs(path)
            return round(stat.f_bavail * stat.f_frsize / (1024 ** 3), 1)
    except Exception:
        return 0


def run_full_check():
    """Run all hardware checks and return a comprehensive report."""
    report = {
        "os": get_os_info(),
        "cpu": get_cpu_info(),
        "ram": get_ram_info(),
        "gpu": get_gpu_info(),
        "free_disk_gb": get_free_disk_space(),
        "timestamp": datetime.now().isoformat()
    }

    try:
        with open(SYSTEM_REPORT_FILE, "w") as f:
            json.dump(report, f, indent=2)
    except Exception:
        pass

    return report


def get_recommendation(report):
    """Recommend a build type based on hardware report."""
    gpu_info = report.get("gpu", {})
    report_os = str(report.get("os", ""))
    report_is_macos = (
        report_os.startswith("macOS")
        or report_os.startswith("Darwin")
        or bool(gpu_info.get("metal_available"))
    )

    # On real macOS hardware reports, Metal is the relevant llama.cpp GPU
    # backend. Do not key this solely off platform.system(): CI runs the
    # synthetic Linux/Windows recommendation tests on macOS too.
    if report_is_macos:
        return "Metal"

    # RDNA4 (Radeon RX 9000): ROCm/HIP is unreliable, Vulkan is the proven
    # backend. Recommend Vulkan even if ROCm happens to be installed.
    if has_rdna4_gpu(report):
        return "Vulkan"

    if gpu_info.get("cuda_available") and gpu_info.get("has_nvidia"):
        return "CUDA"
    elif gpu_info.get("rocm_available") and gpu_info.get("has_amd"):
        return "HIP"
    elif gpu_info.get("sycl_available") and gpu_info.get("has_intel"):
        return "SYCL"
    elif gpu_info.get("vulkan_available"):
        return "Vulkan"
    else:
        return "CPU"


if __name__ == "__main__":
    report = run_full_check()
    print(json.dumps(report, indent=2))
    rec = get_recommendation(report)
    print(f"\nRecommended build: {rec}")
