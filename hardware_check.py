"""
Hardware detection module.
Detects CPU, RAM, GPU, CUDA, Vulkan, ROCm/HIP, Metal, OS, and free disk space.
Works on Windows, Linux, and macOS.
"""
import subprocess
import platform
import os
import re
import json
import ctypes
from datetime import datetime
from config import SYSTEM_REPORT_FILE


def run_cmd(cmd, shell=True, timeout=30):
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), text=True,
                                shell=shell, timeout=timeout, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def run_powershell(cmd):
    """Run a PowerShell command and return stdout, or None on failure."""
    try:
        ps_cmd = ["powershell", "-NoProfile", "-Command", cmd]
        result = subprocess.run(ps_cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), text=True,
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


def get_arch():
    """Normalized machine architecture: x86_64, arm64, or the raw value."""
    machine = (platform.machine() or "").lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine or "unknown"


# ─── CPUID (Windows x86_64) ──────────────────────────────────────────────
# Reads the CPU feature flags directly via the CPUID instruction using a tiny
# slab of x86_64 machine code (VirtualAlloc+RWX). This is the only reliable
# way to learn AVX/AVX2/AVX512/FMA/F16C/AMX on Windows without native deps.
# Everything is wrapped so that any failure degrades gracefully to an empty
# feature list instead of crashing or mis-reporting features.
#
# Windows x64 calling convention: rcx = out pointer, edx = leaf, r8d = subleaf.
# The out pointer is copied to r9 first because CPUID itself clobbers ecx and
# the subleaf has to be loaded into ecx before the instruction executes.
_CPUID_CODE = bytes([
    0x53,                         # push rbx
    0x49, 0x89, 0xC9,             # mov r9, rcx         (save out pointer)
    0x89, 0xD0,                   # mov eax, edx        (leaf, arg2)
    0x44, 0x89, 0xC1,             # mov ecx, r8d        (subleaf, arg3)
    0x0F, 0xA2,                   # cpuid
    0x41, 0x89, 0x01,             # mov [r9],    eax    out[0]
    0x41, 0x89, 0x59, 0x04,       # mov [r9+4],  ebx    out[1]
    0x41, 0x89, 0x49, 0x08,       # mov [r9+8],  ecx    out[2]
    0x41, 0x89, 0x51, 0x0C,       # mov [r9+12], edx    out[3]
    0x5B,                         # pop rbx
    0xC3,                         # ret
])

_cpuid_func = None


def _get_cpuid():
    """Lazy-build a callable CPUID function (Windows x86_64 only)."""
    global _cpuid_func
    if _cpuid_func is not None:
        return _cpuid_func
    if platform.system() != "Windows" or get_arch() != "x86_64":
        return None
    try:
        PAGE_EXECUTE_READWRITE = 0x40
        MEM_COMMIT = 0x1000
        kernel32 = ctypes.windll.kernel32
        kernel32.VirtualAlloc.restype = ctypes.c_void_p
        kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                          ctypes.c_uint32, ctypes.c_uint32]
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
    """Detect CPU model, cores, threads, architecture and ISA features."""
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
        "arch": get_arch(),
        "cores": cores,
        "threads": threads,
        "features": detect_cpu_features(system)
    }


def _windows_avx_state_enabled():
    """Windows must save both SSE and AVX state before AVX can be used."""
    try:
        get_features = ctypes.windll.kernel32.GetEnabledXStateFeatures
        get_features.restype = ctypes.c_ulonglong
        get_features.argtypes = []
        return get_features() & 0x6 == 0x6
    except Exception:
        return False


def detect_cpu_features(system):
    """Detect CPU instruction set features (accurate, never mis-reports)."""
    features = []

    if system == "Windows":
        l1 = _cpuid(1, 0)
        l7 = _cpuid(7, 0)
        l7_1 = _cpuid(7, 1)
        if l1:
            eax1, ebx1, ecx1, edx1 = l1
            osxsave = bool(ecx1 & (1 << 27))
            avx = bool(ecx1 & (1 << 28))
            if avx and osxsave and _windows_avx_state_enabled():
                features.append("AVX")
            if ecx1 & (1 << 12):
                features.append("FMA")
            if ecx1 & (1 << 29):
                features.append("F16C")
        if l7 and "AVX" in features:
            eax7, ebx7, ecx7, edx7 = l7
            if ebx7 & (1 << 5):
                features.append("AVX2")
            if ebx7 & (1 << 8):
                features.append("BMI2")
            if ebx7 & (1 << 16):
                features.append("AVX512")
                if ecx7 & (1 << 1):
                    features.append("AVX512_VBMI")
                if ecx7 & (1 << 11):
                    features.append("AVX512_VNNI")
            if edx7 & (1 << 23):   # AMX-TILE
                features.append("AMX")
            if l7_1:
                eax71 = l7_1[0]
                if eax71 & (1 << 4):
                    features.append("AVX_VNNI")
                if "AVX512" in features and eax71 & (1 << 5):
                    features.append("AVX512_BF16")

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
        if "BMI2" in leaf7:
            features.append("BMI2")
        if "AVX512" in leaf7:
            features.append("AVX512")

    else:  # Linux
        cpuinfo = run_cmd("cat /proc/cpuinfo")
        if cpuinfo:
            flags = set()
            for line in cpuinfo.lower().splitlines():
                if line.startswith("flags") and ":" in line:
                    flags.update(line.split(":", 1)[1].split())
                    break
            if "avx" in flags:
                features.append("AVX")
            if "avx2" in flags:
                features.append("AVX2")
            if "bmi2" in flags:
                features.append("BMI2")
            if "avx512f" in flags:
                features.append("AVX512")
                if "avx512vbmi" in flags:
                    features.append("AVX512_VBMI")
                if "avx512_vnni" in flags:
                    features.append("AVX512_VNNI")
                if "avx512_bf16" in flags:
                    features.append("AVX512_BF16")
            if "fma" in flags:
                features.append("FMA")
            if "f16c" in flags:
                features.append("F16C")
            if "avx_vnni" in flags:
                features.append("AVX_VNNI")
            if "amx_tile" in flags:
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


# ─── GPU helpers ─────────────────────────────────────────────────────────
def _windows_registry_vram():
    """Read dedicated VRAM per adapter from the display-class registry keys.

    Win32_VideoController.AdapterRAM is a uint32 and wraps at 4 GiB, so AMD
    and Intel cards with more memory are reported as 4 GB. The driver stores
    the true size as HardwareInformation.qwMemorySize (QWORD). Returns a list
    of (driver_desc, bytes) in enumeration order.
    """
    result = []
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            if not sub.isdigit():
                continue
            try:
                key = winreg.OpenKey(root, sub)
                desc = winreg.QueryValueEx(key, "DriverDesc")[0]
                size, kind = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")
                if isinstance(size, bytes):
                    size = int.from_bytes(size[:8], "little")
                if desc and int(size) > 0:
                    result.append((str(desc), int(size)))
            except OSError:
                continue
    except Exception:
        pass
    return result


def _parse_nvidia_smi():
    """Return (gpus, driver_version, driver_cuda_version) from nvidia-smi.

    gpus is a list of {"name", "compute_cap", "vram_gb"} in nvidia-smi order.
    driver_cuda_version is the highest CUDA runtime the driver supports (from
    the nvidia-smi banner), which caps the toolkit a build may link against.
    """
    gpus = []
    driver = ""
    driver_cuda = ""
    csv = run_cmd("nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader,nounits")
    if csv is None:
        # Older drivers do not know compute_cap; retry without it.
        csv = run_cmd("nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits")
    if csv:
        for line in csv.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            entry = {"name": parts[0], "compute_cap": parts[3] if len(parts) > 3 else "", "vram_gb": 0}
            try:
                entry["vram_gb"] = round(int(parts[2]) / 1024, 1)
            except ValueError:
                pass
            driver = parts[1] or driver
            gpus.append(entry)
    banner = run_cmd("nvidia-smi")
    if banner:
        m = re.search(r"CUDA Version:\s*([0-9]+\.[0-9]+)", banner)
        if m:
            driver_cuda = m.group(1)
    return gpus, driver, driver_cuda


def _parse_nvcc_version(text):
    """Extract "12.8" from nvcc --version output."""
    if not text:
        return ""
    m = re.search(r"release\s+([0-9]+\.[0-9]+)", text)
    return m.group(1) if m else ""


def _detect_amd_gfx_targets(system):
    """Return the list of AMD gfx targets (e.g. ["gfx1201"]) or [].

    Windows ships hipInfo.exe with the HIP SDK; rocminfo and
    rocm_agent_enumerator only exist on Linux.
    """
    targets = []
    outputs = []
    if system == "Windows":
        outputs.append(run_cmd("hipInfo 2>nul"))
    else:
        outputs.append(run_cmd("rocm_agent_enumerator 2>/dev/null"))
        outputs.append(run_cmd("rocminfo 2>/dev/null"))
    for out in outputs:
        if not out:
            continue
        for m in re.finditer(r"\b(gfx[0-9a-f]{3,5})\b", out):
            name = m.group(1)
            if name == "gfx000":   # rocm_agent_enumerator lists the CPU as gfx000
                continue
            if name not in targets:
                targets.append(name)
    return targets


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
    nvidia_driver_cuda_version = ""
    cuda_available = False
    cuda_version = ""
    vulkan_available = False
    vulkan_sdk = False
    opencl_available = False
    rocm_available = False
    amd_gfx_targets = []
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

        # Accurate VRAM for every vendor from the display-class registry.
        reg_vram = _windows_registry_vram()
        used = set()
        for gpu in gpus:
            for idx, (desc, size) in enumerate(reg_vram):
                if idx in used:
                    continue
                if desc.strip().lower() == str(gpu.get("name", "")).strip().lower():
                    gpu["vram_gb"] = round(size / (1024 ** 3), 1)
                    used.add(idx)
                    break

        nvcc = run_cmd("nvcc --version")
        if nvcc:
            cuda_available = True
            cuda_version = _parse_nvcc_version(nvcc)

        if run_cmd("vulkaninfo --summary 2>nul"):
            vulkan_available = True
        if run_cmd("glslc --version 2>nul") or run_cmd("glslangValidator --version 2>nul"):
            vulkan_sdk = True
        else:
            _vulkan_sdk_env = os.environ.get("VULKAN_SDK", "")
            if _vulkan_sdk_env and (
                    os.path.isfile(os.path.join(_vulkan_sdk_env, "Bin", "glslc.exe"))
                    or os.path.isfile(os.path.join(_vulkan_sdk_env, "Bin", "glslangValidator.exe"))):
                vulkan_sdk = True

        hip_path = os.environ.get("HIP_PATH", "")
        if run_cmd("hipcc --version 2>nul") or (hip_path and os.path.isfile(os.path.join(hip_path, "bin", "hipcc.exe"))):
            rocm_available = True

        if run_cmd("icpx --version 2>nul") or run_cmd("icx --version 2>nul"):
            sycl_available = True

        if run_cmd("clinfo 2>nul"):
            opencl_available = True

    elif system == "Darwin":
        # system_profiler is the only reliable GPU source on macOS.
        sp = run_cmd("system_profiler SPDisplaysDataType")
        if sp:
            for block in re.split(r"\n\s*\n", sp):
                model = re.search(r"Chipset Model:\s*(.+)", block)
                vram = re.search(r"VRAM .*?:\s*([0-9]+)\s*MB", block)
                if not model:
                    continue
                name = model.group(1).strip()
                vram_gb = round(int(vram.group(1)) / 1024, 1) if vram else 0
                vendor = detect_vendor(name)
                if vendor == "Unknown" and "apple" in name.lower():
                    vendor = "Apple"
                gpus.append({"name": name, "vendor": vendor, "vram_gb": vram_gb})
        # Apple Silicon has unified memory: the GPU can use (almost) all RAM.
        if get_arch() == "arm64":
            total = run_cmd("sysctl -n hw.memsize")
            if total and total.isdigit():
                for gpu in gpus:
                    if gpu.get("vendor") == "Apple" and not gpu.get("vram_gb"):
                        gpu["vram_gb"] = round(int(total) / (1024 ** 3), 1)
                        gpu["unified_memory"] = True
        # Metal is only a sensible llama.cpp backend on Apple Silicon. Upstream
        # builds its macOS x64 releases with GGML_METAL=OFF.
        metal_available = get_arch() == "arm64"
        if run_cmd("nvcc --version 2>/dev/null"):
            cuda_available = True
            cuda_version = _parse_nvcc_version(run_cmd("nvcc --version") or "")
        if run_cmd("vulkaninfo --summary 2>/dev/null"):
            vulkan_available = True
        if run_cmd("glslc --version 2>/dev/null") or run_cmd("glslangValidator --version 2>/dev/null"):
            vulkan_sdk = True

    else:  # Linux
        lspci = run_cmd("lspci 2>/dev/null | grep -iE 'vga|3d|display'")
        if lspci:
            for line in lspci.split("\n"):
                if line.strip():
                    gpus.append({"name": line.strip(), "vendor": detect_vendor(line), "vram_gb": 0})

        nvcc = run_cmd("nvcc --version 2>/dev/null")
        if nvcc:
            cuda_available = True
            cuda_version = _parse_nvcc_version(nvcc)

        if run_cmd("vulkaninfo --summary 2>/dev/null"):
            vulkan_available = True
        if run_cmd("glslc --version 2>/dev/null") or run_cmd("glslangValidator --version 2>/dev/null"):
            vulkan_sdk = True
        elif run_cmd("test -d /usr/include/vulkan && echo yes"):
            vulkan_sdk = True

        if run_cmd("rocminfo 2>/dev/null | head -1") or run_cmd("hipcc --version 2>/dev/null"):
            rocm_available = True

        if run_cmd("icpx --version 2>/dev/null") or run_cmd("icx --version 2>/dev/null"):
            sycl_available = True

        if run_cmd("clinfo 2>/dev/null") or os.path.isdir("/etc/OpenCL/vendors"):
            opencl_available = True

    # NVIDIA: nvidia-smi is authoritative for name, VRAM, driver and CC.
    if system != "Darwin":
        nv_gpus, nvidia_driver_version, nvidia_driver_cuda_version = _parse_nvidia_smi()
        if nv_gpus:
            has_nvidia = True
            nvidia_slots = [g for g in gpus if g.get("vendor") == "NVIDIA"]
            for idx, nv in enumerate(nv_gpus):
                if idx < len(nvidia_slots):
                    target = nvidia_slots[idx]
                else:
                    target = {"vendor": "NVIDIA"}
                    gpus.append(target)
                target["name"] = nv["name"]
                target["vendor"] = "NVIDIA"
                if nv["vram_gb"]:
                    target["vram_gb"] = nv["vram_gb"]
                if nv["compute_cap"]:
                    target["compute_cap"] = nv["compute_cap"]

    # AMD: gfx targets (needed for HIP GPU_TARGETS and RDNA4 detection).
    if rocm_available or any(g.get("vendor") == "AMD" for g in gpus):
        amd_gfx_targets = _detect_amd_gfx_targets(system)

    # Linux AMD VRAM from /sys/class/drm.
    if system == "Linux":
        amd_vram_list = _linux_drm_vram()
        amd_idx = 0
        for gpu in gpus:
            if gpu.get("vendor") == "AMD" and amd_idx < len(amd_vram_list):
                gpu["vram_gb"] = round(amd_vram_list[amd_idx] / (1024 ** 3), 1)
                amd_idx += 1

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

    return {
        "gpus": gpus,
        "has_nvidia": has_nvidia,
        "has_amd": has_amd,
        "has_intel": has_intel,
        "has_apple": has_apple,
        "nvidia_driver_version": nvidia_driver_version,
        "nvidia_driver_cuda_version": nvidia_driver_cuda_version,
        "cuda_available": cuda_available,
        "cuda_version": cuda_version,
        "vulkan_available": vulkan_available,
        "vulkan_sdk": vulkan_sdk,
        "opencl_available": opencl_available,
        "rocm_available": rocm_available,
        "amd_gfx_targets": amd_gfx_targets,
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


# Marketing names of RDNA4 parts (gfx1200/gfx1201). Used only when no gfx
# target could be read from the HIP SDK / ROCm tools.
_RDNA4_NAME_PATTERNS = (
    r"\brx\s*90[0-9]0\b",          # RX 9070 XT, RX 9070, RX 9060 XT, RX 9070 GRE
    r"\bradeon\s+ai\s+pro\s+r9[0-9]{3}\b",  # Radeon AI PRO R9700 / R9600
    r"\br9[67]00\b",
    r"\bgfx120[01]\b",
    r"\brdna\s*4\b",
)


def is_rdna4(gpu_name):
    """Detect AMD RDNA4 (Radeon RX 9000 / Radeon AI PRO R9000, gfx120x).

    RDNA4 GPUs have poor/buggy ROCm (HIP) support on Windows; the recommended
    and proven backend for them is Vulkan with a recent SPIRV-Headers build.
    """
    if not gpu_name:
        return False
    low = gpu_name.lower()
    return any(re.search(p, low) for p in _RDNA4_NAME_PATTERNS)


def has_rdna4_gpu(report):
    """True if any GPU in the report is an AMD RDNA4 part."""
    gpu_info = report.get("gpu", {})
    if any(t.startswith("gfx120") for t in gpu_info.get("amd_gfx_targets", []) or []):
        return True
    return any(is_rdna4(g.get("name", "")) for g in gpu_info.get("gpus", []))


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
        "arch": get_arch(),
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


# ─── Recommendation ──────────────────────────────────────────────────────
def _report_is_macos(report):
    report_os = str(report.get("os", ""))
    return report_os.startswith("macOS") or report_os.startswith("Darwin")


def _report_arch(report):
    return report.get("arch") or report.get("cpu", {}).get("arch") or ""


def _version_tuple(text):
    try:
        return tuple(int(p) for p in str(text).split(".")[:2])
    except ValueError:
        return ()


def recommend_cuda_major(report):
    """Return "12" or "13": the CUDA toolkit generation to build with.

    CUDA 13 dropped Maxwell/Pascal/Volta (sm_50..sm_70) and needs a 580+
    driver. When the driver cannot run 13.x or a GPU is older than Turing,
    12.x is the only working choice. Without nvidia-smi data, 12 is the safe
    default.
    """
    gpu_info = report.get("gpu", {})
    driver_cuda = _version_tuple(gpu_info.get("nvidia_driver_cuda_version", ""))
    if not driver_cuda or driver_cuda < (13, 0):
        return "12"
    for gpu in gpu_info.get("gpus", []):
        if gpu.get("vendor") != "NVIDIA":
            continue
        cc = _version_tuple(gpu.get("compute_cap", ""))
        if cc and cc < (7, 5):
            return "12"
    return "13"


def get_recommendation(report):
    """Recommend a build type based on hardware report."""
    gpu_info = report.get("gpu", {})

    # macOS: Metal on Apple Silicon only. Intel Macs get a CPU build (upstream
    # ships its x64 macOS releases with GGML_METAL=OFF); Vulkan via MoltenVK
    # is available as a manual profile.
    if _report_is_macos(report) or gpu_info.get("has_apple"):
        if _report_arch(report) == "arm64" or gpu_info.get("has_apple"):
            return "Metal"
        return "CPU"

    # RDNA4 (Radeon RX 9000 / AI PRO R9000): ROCm/HIP on Windows is unreliable,
    # Vulkan is the proven backend. Recommend Vulkan even if ROCm is installed.
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


def get_recommendation_reason(report):
    """One short sentence explaining why get_recommendation() chose its type."""
    gpu_info = report.get("gpu", {})
    rec = get_recommendation(report)
    if rec == "Metal":
        return "Apple Silicon with unified memory: Metal is the native llama.cpp backend."
    if _report_is_macos(report) and rec == "CPU":
        return "Intel Mac: Metal is not maintained for x86 Macs, use the CPU build (or Vulkan via MoltenVK)."
    if rec == "Vulkan" and has_rdna4_gpu(report):
        names = ", ".join(g.get("name", "") for g in gpu_info.get("gpus", []) if g.get("vendor") == "AMD")
        return f"RDNA4 detected ({names}): HIP on Windows is unreliable for gfx120x, Vulkan is the proven backend."
    if rec == "CUDA":
        major = recommend_cuda_major(report)
        drv = gpu_info.get("nvidia_driver_cuda_version") or "unknown"
        return f"NVIDIA GPU with CUDA toolkit found. Driver supports CUDA {drv}; recommended toolkit generation: {major}.x."
    if rec == "HIP":
        targets = ", ".join(gpu_info.get("amd_gfx_targets", [])) or "target not detected"
        return f"AMD GPU with HIP SDK found ({targets})."
    if rec == "SYCL":
        return "Intel GPU with oneAPI compiler found."
    if rec == "Vulkan":
        return "Vulkan runtime found and no vendor toolkit installed: Vulkan works on any GPU."
    return "No usable GPU backend found: CPU build."


def select_profile_name(report, profiles):
    """Pick the best matching profile name for a report, or "" if none fits.

    Profiles may carry optional hints:
      - "cuda_major": "12" | "13"  (which toolkit generation the profile targets)
      - "platform":   "darwin-arm64" | "darwin-x86_64" | ... (restrict to a platform)
    """
    rec = get_recommendation(report)
    plat = ""
    if _report_is_macos(report):
        plat = f"darwin-{_report_arch(report) or 'x86_64'}"
    cuda_major = recommend_cuda_major(report) if rec == "CUDA" else ""

    candidates = [p for p in profiles if p.get("build_type") == rec and p.get("name")]
    if not candidates:
        return ""
    # 1. exact platform + cuda hints
    for p in candidates:
        if plat and p.get("platform") == plat:
            return p["name"]
    for p in candidates:
        if cuda_major and str(p.get("cuda_major", "")) == cuda_major:
            return p["name"]
    # 2. profiles without a conflicting hint
    for p in candidates:
        if p.get("platform") and p.get("platform") != plat:
            continue
        if cuda_major and p.get("cuda_major") and str(p.get("cuda_major")) != cuda_major:
            continue
        return p["name"]
    return candidates[0]["name"]


if __name__ == "__main__":
    report = run_full_check()
    print(json.dumps(report, indent=2))
    rec = get_recommendation(report)
    print(f"\nRecommended build: {rec}")
    print(get_recommendation_reason(report))
