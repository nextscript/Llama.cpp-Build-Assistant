"""
Dependency checker module.
Checks whether required programs are installed and available in PATH.
"""
import subprocess
import shutil
import os
import platform
from config import REQUIRED_FOR_ALL, REQUIRED_FOR_CUDA, REQUIRED_FOR_VULKAN, REQUIRED_FOR_HIP, REQUIRED_FOR_SYCL


def check_command(name):
    """Check if a command is available in PATH."""
    return shutil.which(name) is not None


def get_command_version(name):
    """Try to get the version of a command."""
    cmd_map = {
        "git": ["git", "--version"],
        "cmake": ["cmake", "--version"],
        "ninja": ["ninja", "--version"],
        "python": ["python", "--version"],
        "gcc": ["gcc", "--version"],
        "g++": ["g++", "--version"],
        "clang": ["clang", "--version"],
        "nvcc": ["nvcc", "--version"],
    }
    cmd = cmd_map.get(name, [name, "--version"])
    out = run_cmd(cmd)
    if out:
        return out.split("\n")[0]
    return None


def run_cmd(cmd):
    """Run a command and return stdout or None."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def check_compiler():
    """Check if a compiler is available."""
    system = platform.system()

    if system == "Windows":
        # Check MSVC in PATH first.
        cl_path = shutil.which("cl")
        if cl_path:
            return {"found": True, "name": "MSVC (cl)", "path": cl_path}

        # Otherwise ask vswhere whether the VC++ tools workload is actually
        # installed (vswhere.exe itself exists even without C++ tools, so its
        # mere presence is NOT proof of a usable compiler).
        vswhere = shutil.which("vswhere") or \
            r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
        if os.path.isfile(vswhere):
            try:
                result = subprocess.run(
                    [vswhere, "-latest", "-products", "*",
                     "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                     "-property", "displayName"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0 and result.stdout.strip():
                    return {"found": True,
                            "name": f"MSVC via {result.stdout.strip().splitlines()[0]} (cl not in PATH)",
                            "path": "Run from a Visual Studio Developer Command Prompt"}
            except Exception:
                pass
        # Last-resort heuristic: winget-reported Build Tools (unverified).
        try:
            result = subprocess.run(
                ["winget", "list", "--id", "Microsoft.VisualStudio.2022.BuildTools"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and "Visual Studio Build Tools" in result.stdout:
                return {"found": True, "name": "VS Build Tools installed (cl not in PATH)",
                        "path": "Run from VS Developer Command Prompt or add to PATH"}
        except Exception:
            pass
        return {"found": False, "name": "MSVC", "path": None}
    else:
        # Check GCC
        gcc_path = shutil.which("gcc")
        if gcc_path:
            return {"found": True, "name": "GCC", "path": gcc_path}
        # Check Clang
        clang_path = shutil.which("clang")
        if clang_path:
            return {"found": True, "name": "Clang", "path": clang_path}
        return {"found": False, "name": "GCC/Clang", "path": None}


def check_cuda_toolkit():
    """Check if CUDA toolkit is installed."""
    nvcc = shutil.which("nvcc")
    if nvcc:
        version = get_command_version("nvcc")
        return {"found": True, "name": "CUDA Toolkit", "version": version, "path": nvcc}
    return {"found": False, "name": "CUDA Toolkit", "version": None, "path": None}


def check_vulkan_sdk():
    """Check if Vulkan SDK is installed (not just the runtime driver)."""
    glslang = shutil.which("glslangValidator")
    if glslang:
        return {"found": True, "name": "Vulkan SDK", "path": glslang}
    import os
    vulkan_sdk = os.environ.get("VULKAN_SDK", "")
    if vulkan_sdk and os.path.isdir(vulkan_sdk):
        glslang_path = os.path.join(vulkan_sdk, "Bin", "glslangValidator.exe")
        if os.path.isfile(glslang_path):
            return {"found": True, "name": "Vulkan SDK", "path": glslang_path}
    for check_path in [r"C:\VulkanSDK", r"C:\Program Files\VulkanSDK"]:
        if os.path.isdir(check_path):
            for ver in sorted(os.listdir(check_path), reverse=True):
                candidate = os.path.join(check_path, ver, "Bin", "glslangValidator.exe")
                if os.path.isfile(candidate):
                    return {"found": True, "name": "Vulkan SDK", "path": candidate}
    return {"found": False, "name": "Vulkan SDK", "path": None}


def check_rocm_hip():
    """Check if ROCm/HIP is installed."""
    hipcc = shutil.which("hipcc")
    if hipcc:
        return {"found": True, "name": "ROCm/HIP", "path": hipcc}
    return {"found": False, "name": "ROCm/HIP", "path": None}


def check_intel_oneapi():
    """Check if Intel oneAPI DPC++/C++ Compiler is installed."""
    import os
    # Check for icpx (Intel DPC++ compiler)
    icpx = shutil.which("icpx")
    if icpx:
        return {"found": True, "name": "Intel oneAPI DPC++", "path": icpx}
    
    # Check for icx (Intel C++ compiler)
    icx = shutil.which("icx")
    if icx:
        return {"found": True, "name": "Intel oneAPI C++", "path": icx}
    
    # Check common installation paths
    oneapi_paths = [
        r"C:\Program Files (x86)\Intel\oneAPI",
        r"C:\Program Files\Intel\oneAPI",
        "/opt/intel/oneapi",
        os.path.expanduser("~/intel/oneapi")
    ]
    
    for base_path in oneapi_paths:
        if os.path.isdir(base_path):
            # Look for compiler in common locations
            compiler_paths = [
                os.path.join(base_path, "compiler", "latest", "bin", "icpx"),
                os.path.join(base_path, "compiler", "latest", "bin", "icx"),
                os.path.join(base_path, "compiler", "latest", "windows", "bin", "icx.exe"),
            ]
            for compiler_path in compiler_paths:
                if os.path.isfile(compiler_path):
                    return {"found": True, "name": "Intel oneAPI", "path": compiler_path}
    
    return {"found": False, "name": "Intel oneAPI DPC++/C++", "path": None}


def check_all():
    """Check all common dependencies and return a status dict."""
    results = {}

    for dep in ["git", "cmake", "ninja", "python"]:
        results[dep] = {
            "found": check_command(dep),
            "name": dep,
            "version": get_command_version(dep) if check_command(dep) else None,
            "path": shutil.which(dep) if check_command(dep) else None
        }

    results["compiler"] = check_compiler()
    results["cuda_toolkit"] = check_cuda_toolkit()
    results["vulkan_sdk"] = check_vulkan_sdk()
    results["rocmmhip"] = check_rocm_hip()
    results["intel_oneapi"] = check_intel_oneapi()

    # Check VS Build Tools on Windows
    system = platform.system()
    if system == "Windows":
        cl_path = shutil.which("cl")
        vs_path = shutil.which("vswhere")
        # Also check via winget
        vs_via_winget = False
        try:
            import subprocess
            wresult = subprocess.run(
                ["winget", "list", "--id", "Microsoft.VisualStudio.2022.BuildTools"],
                capture_output=True, text=True, timeout=30
            )
            if wresult.returncode == 0 and "Visual Studio Build Tools" in wresult.stdout:
                vs_via_winget = True
        except Exception:
            pass
        results["vs_build_tools"] = {
            "found": cl_path is not None or vs_path is not None or vs_via_winget,
            "name": "Visual Studio Build Tools",
            "path": cl_path or vs_path or ("Installed via winget (cl not in PATH)" if vs_via_winget else None)
        }

    return results


def get_missing_for_build_type(check_results, build_type):
    """Return list of missing dependencies for a given build type."""
    missing = []

    # Always required
    for dep in REQUIRED_FOR_ALL:
        if dep == "compiler":
            if not check_results.get("compiler", {}).get("found", False):
                missing.append("compiler")
        else:
            if not check_results.get(dep, {}).get("found", False):
                missing.append(dep)

    if build_type == "CUDA":
        if not check_results.get("cuda_toolkit", {}).get("found", False):
            missing.append("cuda_toolkit")
    elif build_type == "Vulkan":
        if not check_results.get("vulkan_sdk", {}).get("found", False):
            missing.append("vulkan_sdk")
    elif build_type == "HIP":
        if not check_results.get("rocmmhip", {}).get("found", False):
            missing.append("rocmmhip")
    elif build_type == "SYCL":
        if not check_results.get("intel_oneapi", {}).get("found", False):
            missing.append("intel_oneapi")

    return missing


def get_missing_programs_text(missing):
    """Convert missing dependency list to human-readable text."""
    name_map = {
        "git": "Git",
        "cmake": "CMake",
        "ninja": "Ninja",
        "python": "Python",
        "compiler": "Compiler",
        "cuda_toolkit": "CUDA Toolkit",
        "vulkan_sdk": "Vulkan SDK",
        "rocmmhip": "ROCm/HIP",
        "intel_oneapi": "Intel oneAPI DPC++/C++",
        "vs_build_tools": "Visual Studio Build Tools"
    }
    return [name_map.get(m, m) for m in missing]


if __name__ == "__main__":
    results = check_all()
    for name, info in results.items():
        status = "OK" if info.get("found") else "MISSING"
        version = info.get("version", "")
        print(f"  {name}: {status} {version}")
