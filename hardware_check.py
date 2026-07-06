"""
Hardware detection module.
Detects CPU, RAM, GPU, CUDA, Vulkan, ROCm/HIP, OS, and free disk space.
Works on both Windows and Linux.
"""
import subprocess
import platform
import os
import json
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


def get_os_info():
    """Detect operating system and version."""
    system = platform.system()
    version = platform.version()
    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
            name = winreg.QueryValueEx(key, "ProductName")[0]
        except Exception:
            name = version
        return f"{name} {version}"
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
        return f"macOS {version}"
    else:
        return f"{system} {version}"


def get_cpu_info():
    """Detect CPU model, cores, and threads."""
    system = platform.system()
    cpu_name = "Unknown"
    cores = 0
    threads = 0

    if system == "Windows":
        # Try PowerShell first (more reliable on modern Windows)
        ps_output = run_powershell("Get-CimInstance -ClassName Win32_Processor | Select-Object -Property Name, NumberOfCores, NumberOfLogicalProcessors | ConvertTo-Json")
        if ps_output:
            try:
                cpu_data = json.loads(ps_output)
                if isinstance(cpu_data, list):
                    cpu_data = cpu_data[0]
                cpu_name = cpu_data.get("Name", "Unknown")
                cores = cpu_data.get("NumberOfCores", 0)
                threads = cpu_data.get("NumberOfLogicalProcessors", 0)
            except:
                pass
        
        # Fallback to wmic if PowerShell failed
        if cpu_name == "Unknown":
            cpu_name = run_cmd("wmic cpu get name")
            if cpu_name:
                cpu_name = cpu_name.split("\n")[-1].strip()
        
        # Fallback for cores/threads
        if cores == 0:
            cores = os.cpu_count() or 0
        if threads == 0:
            threads = os.cpu_count() or 0
    else:
        cpu_name = run_cmd("lscpu | grep 'Model name'")
        if cpu_name:
            cpu_name = cpu_name.split(":")[-1].strip()

        threads_out = run_cmd("lscpu | grep '^Thread(s) per core'")
        if threads_out:
            threads = int(threads_out.split(":")[-1].strip())

        cores_per_socket = int(run_cmd("lscpu | grep '^Core(s) per socket'")
                               .split(":")[-1].strip() if threads_out else "1")
        sockets = int(run_cmd("lscpu | grep '^Socket(s)'"
                              ).split(":")[-1].strip() if threads_out else "1")
        cores = cores_per_socket * sockets

    # Detect CPU features
    features = detect_cpu_features(system)

    return {
        "name": cpu_name,
        "cores": cores,
        "threads": threads,
        "features": features
    }


def detect_cpu_features(system):
    """Detect CPU instruction set features."""
    features = []

    if system == "Windows":
        # Try PowerShell first
        ps_output = run_powershell("Get-CimInstance -ClassName Win32_Processor | Select-Object -Property Caption | ConvertTo-Json")
        cpu_name = ""
        if ps_output:
            try:
                cpu_data = json.loads(ps_output)
                if isinstance(cpu_data, list):
                    cpu_data = cpu_data[0]
                cpu_name = cpu_data.get("Caption", "")
            except:
                pass
        
        # Fallback to wmic
        if not cpu_name:
            try:
                cpu_info = run_cmd("wmic cpu get Caption /format:list")
                if cpu_info:
                    for line in cpu_info.split("\n"):
                        if line.startswith("Caption="):
                            cpu_name = line.split("=", 1)[1].strip()
            except Exception:
                pass
        
        # Detect features based on CPU name
        if "Intel" in cpu_name:
            features.append("AVX")
            # Modern Intel CPUs support AVX2
            if any(gen in cpu_name for gen in ["i5", "i7", "i9", "Xeon"]):
                features.append("AVX2")
        elif "AMD" in cpu_name:
            features.append("AVX")
            # Modern AMD CPUs support AVX2
            if any(gen in cpu_name for gen in ["Ryzen", "EPYC"]):
                features.append("AVX2")
    else:
        cpuinfo = run_cmd("cat /proc/cpuinfo")
        if cpuinfo:
            if "avx" in cpuinfo.lower():
                features.append("AVX")
            if "avx2" in cpuinfo.lower():
                features.append("AVX2")
            if "avx-512" in cpuinfo.lower() or "avx512" in cpuinfo.lower():
                features.append("AVX512")

    return features


def get_ram_info():
    """Detect total and free RAM."""
    system = platform.system()

    if system == "Windows":
        # Try PowerShell first
        ps_output = run_powershell("Get-CimInstance -ClassName Win32_OperatingSystem | Select-Object -Property TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json")
        if ps_output:
            try:
                ram_data = json.loads(ps_output)
                total_kb = ram_data.get("TotalVisibleMemorySize", 0)
                free_kb = ram_data.get("FreePhysicalMemory", 0)
                return {
                    "total_gb": round(total_kb / 1024 / 1024, 1),
                    "free_gb": round(free_kb / 1024 / 1024, 1)
                }
            except:
                pass
        
        # Fallback to wmic
        total_str = run_cmd("wmic computersystem get totalphysicalmemory")
        if total_str:
            total_bytes = int(total_str.split("\n")[-1].strip())
        else:
            total_bytes = 0
        return {
            "total_gb": round(total_bytes / (1024**3), 1),
            "free_gb": 0
        }
    else:
        free_out = run_cmd("free -k | grep Mem")
        if free_out:
            parts = free_out.split()
            total_kb = int(parts[1])
            free_kb = int(parts[3])
            return {
                "total_gb": round(total_kb / 1024 / 1024, 1),
                "free_gb": round(free_kb / 1024 / 1024, 1)
            }
    return {"total_gb": 0, "free_gb": 0}


def get_gpu_info():
    """Detect GPU(s), VRAM, and vendor."""
    system = platform.system()
    gpus = []
    has_nvidia = False
    has_amd = False
    has_intel = False
    nvidia_driver_version = ""
    cuda_available = False
    cuda_version = ""
    vulkan_available = False
    vulkan_sdk = False
    opencl_available = False
    rocm_available = False
    sycl_available = False

    if system == "Windows":
        # Try PowerShell first for GPU detection
        ps_output = run_powershell("Get-CimInstance -ClassName Win32_VideoController | Select-Object -Property Name, AdapterRAM | ConvertTo-Json")
        if ps_output:
            try:
                gpu_data = json.loads(ps_output)
                if not isinstance(gpu_data, list):
                    gpu_data = [gpu_data]
                for gpu in gpu_data:
                    name = gpu.get("Name", "Unknown")
                    vram_bytes = gpu.get("AdapterRAM", 0)
                    vram_gb = round(vram_bytes / (1024**3), 1) if vram_bytes else 0
                    gpus.append({
                        "name": name,
                        "vendor": detect_vendor(name),
                        "vram_gb": vram_gb
                    })
            except:
                pass
        
        # Fallback to wmic if PowerShell failed
        if not gpus:
            gpu_out = run_cmd("wmic path win32_VideoController get name")
            if gpu_out:
                for line in gpu_out.split("\n"):
                    line = line.strip()
                    if line and "Controller" not in line and "Name" not in line:
                        gpus.append({"name": line, "vendor": detect_vendor(line)})

        # NVIDIA checks
        nvidia_smi = run_cmd("nvidia-smi --query-gpu=name,driver_version --format=csv,noheader")
        if nvidia_smi:
            has_nvidia = True
            nvidia_driver_version = ""
            for line in nvidia_smi.split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    nvidia_driver_version = parts[1]
                    # Update first GPU name if it's NVIDIA
                    if gpus and "NVIDIA" in parts[0]:
                        gpus[0]["name"] = parts[0]

        nvcc = run_cmd("nvcc --version")
        if nvcc:
            cuda_available = True
            for part in nvcc.split("\n"):
                if "release" in part:
                    cuda_version = part.strip().split()[-1]
                    break

        # Vulkan check
        vulkan_info = run_cmd("vulkaninfo --summary 2>nul")
        if vulkan_info:
            vulkan_available = True
        glslang_check = run_cmd("glslangValidator --version 2>nul")
        if glslang_check:
            vulkan_sdk = True
        else:
            import os as _os
            _vulkan_sdk_env = _os.environ.get("VULKAN_SDK", "")
            if _vulkan_sdk_env and _os.path.isfile(_os.path.join(_vulkan_sdk_env, "Bin", "glslangValidator.exe")):
                vulkan_sdk = True

        # ROCm check
        if run_cmd("hipconfig --version"):
            rocm_available = True

        # Intel oneAPI / SYCL check
        if run_cmd("icpx --version 2>nul") or run_cmd("icx --version 2>nul"):
            sycl_available = True
        
        # Detect GPU vendors (AMD / Intel)
        for gpu in gpus:
            vendor = gpu.get("vendor")
            if vendor == "AMD":
                has_amd = True
            elif vendor == "Intel":
                has_intel = True

    else:
        # Linux GPU detection
        lspci = run_cmd("lspci 2>/dev/null | grep -i vga")
        if lspci:
            for line in lspci.split("\n"):
                if line.strip():
                    gpus.append({"name": line.strip(), "vendor": detect_vendor(line)})

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

        vulkan_info = run_cmd("vulkaninfo --summary 2>/dev/null")
        if vulkan_info:
            vulkan_available = True
        glslang_check = run_cmd("glslangValidator --version 2>/dev/null")
        if glslang_check:
            vulkan_sdk = True
        elif run_cmd("test -d /usr/include/vulkan && echo yes"):
            vulkan_sdk = True

        rocm_check = run_cmd("rocminfo 2>/dev/null | head -1")
        if rocm_check:
            rocm_available = True

        # Intel oneAPI / SYCL check
        if run_cmd("icpx --version 2>/dev/null") or run_cmd("icx --version 2>/dev/null"):
            sycl_available = True
        
        # Detect GPU vendors (AMD / Intel)
        for gpu in gpus:
            vendor = gpu.get("vendor")
            if vendor == "AMD":
                has_amd = True
            elif vendor == "Intel":
                has_intel = True

    # Try to get VRAM
    for gpu in gpus:
        if "NVIDIA" in gpu.get("name", ""):
            vram = run_cmd("nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits")
            if vram:
                vram_line = vram.split("\n")[0].strip()
                try:
                    gpu["vram_gb"] = round(int(vram_line) / 1024, 1)
                except ValueError:
                    gpu["vram_gb"] = 0

    return {
        "gpus": gpus,
        "has_nvidia": has_nvidia,
        "has_amd": has_amd,
        "has_intel": has_intel,
        "nvidia_driver_version": nvidia_driver_version,
        "cuda_available": cuda_available,
        "cuda_version": cuda_version,
        "vulkan_available": vulkan_available,
        "vulkan_sdk": vulkan_sdk,
        "opencl_available": opencl_available,
        "rocm_available": rocm_available,
        "sycl_available": sycl_available
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
    return "Unknown"


def is_rdna4(gpu_name):
    """Detect AMD RDNA4 (Radeon RX 9000 series / gfx120x).

    RDNA4 GPUs have very poor/buggy ROCm (HIP) support; the recommended and
    proven backend for them is Vulkan with a recent SPIRV-Headers build.
    """
    if not gpu_name:
        return False
    low = gpu_name.lower()
    # Radeon RX 9070 / 9070 XT / 9000 series
    if "rx 90" in low or "radeon rx 9" in low or "9070" in low or "9 900" in low:
        return True
    # gfx1200 / gfx1201 (CDNA/RDNA code names reported by rocminfo/hip)
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
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path), None, None, ctypes.pointer(free_bytes))
            return round(free_bytes.value / (1024**3), 1)
        else:
            stat = os.statvfs(path)
            return round(stat.f_bavail * stat.f_frsize / (1024**3), 1)
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

    # Save report
    try:
        with open(SYSTEM_REPORT_FILE, "w") as f:
            json.dump(report, f, indent=2)
    except Exception:
        pass

    return report


def get_recommendation(report):
    """Recommend a build type based on hardware report."""
    gpu_info = report.get("gpu", {})

    # RDNA4 (Radeon RX 9000): ROCm/HIP is unreliable, Vulkan is the proven
    # backend. Recommend Vulkan even if ROCm happens to be installed.
    if has_rdna4_gpu(report):
        return "Vulkan"

    if gpu_info.get("cuda_available") and gpu_info.get("has_nvidia"):
        return "CUDA"
    elif gpu_info.get("rocm_available"):
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
