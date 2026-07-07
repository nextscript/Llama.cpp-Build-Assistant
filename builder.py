"""
Build module.
Creates CMake commands and runs the build process with live logging.
"""
import subprocess
import os
import json
import time
from datetime import datetime
from config import (
    BUILDS_DIR, BUILD_TYPE_FLAGS, BUILD_TYPE_DISPLAY,
    BUILD_HISTORY_FILE, ROOT_DIR
)
from logger import log_build, log_error, log_warning
from source_manager import get_source_by_id
from repo_manager import ensure_repo


def get_build_path(source_id, build_type):
    """Generate a build output path."""
    source_name = source_id.replace("_", "-")
    type_name = BUILD_TYPE_DISPLAY.get(build_type, build_type).lower().replace("/", "-")
    return os.path.join(BUILDS_DIR, f"{source_name}-{type_name}")


def setup_cuda_vs_integration():
    """Setup CUDA Visual Studio integration by copying MSBuild props."""
    import platform
    if platform.system() != "Windows":
        return False
    
    # Find CUDA installation
    cuda_base = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if not os.path.exists(cuda_base):
        return False
    
    # Find latest CUDA version
    cuda_versions = sorted([d for d in os.listdir(cuda_base) if d.startswith("v")], reverse=True)
    if not cuda_versions:
        return False
    
    cuda_path = os.path.join(cuda_base, cuda_versions[0])
    cuda_vs_int_src = os.path.join(cuda_path, "extras", "visual_studio_integration", "MSBuildExtensions")
    
    if not os.path.exists(cuda_vs_int_src):
        return False
    
    # Find VS installation using vswhere
    vswhere = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
    if not os.path.exists(vswhere):
        return False
    
    try:
        result = subprocess.run(
            [vswhere, "-latest", "-products", "*",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        
        vs_path = result.stdout.strip()
        
        # Determine VS version for BuildCustomizations path
        version_result = subprocess.run(
            [vswhere, "-latest", "-products", "*",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationVersion"],
            capture_output=True, text=True, timeout=10
        )
        if version_result.returncode != 0 or not version_result.stdout.strip():
            return False
        
        vs_version = version_result.stdout.strip().split(".")[0]
        vs_major = int(vs_version)
        
        if vs_major == 17:
            target_dir = os.path.join(vs_path, "MSBuild", "Microsoft", "VC", "v170", "BuildCustomizations")
        elif vs_major == 16:
            target_dir = os.path.join(vs_path, "MSBuild", "Microsoft", "VC", "v160", "BuildCustomizations")
        else:
            return False
        
        # Copy CUDA props
        os.makedirs(target_dir, exist_ok=True)
        import shutil
        for file in os.listdir(cuda_vs_int_src):
            src_file = os.path.join(cuda_vs_int_src, file)
            dst_file = os.path.join(target_dir, file)
            shutil.copy2(src_file, dst_file)
        
        return True
    except:
        return False


def generate_cmake_command(source, build_type, custom_flags=None, clean_build=False):
    repo_path = source.get("local_path", "")
    if not os.path.isabs(repo_path):
        repo_path = os.path.join(ROOT_DIR, repo_path)
    build_path = get_build_path(source.get("id", "unknown"), build_type)

    flags = source.get("default_cmake_flags", [])

    # Add build type flag
    if build_type in BUILD_TYPE_FLAGS:
        flags.append(BUILD_TYPE_FLAGS[build_type])

    # Add custom flags
    if custom_flags:
        flags.extend(custom_flags)

    # Clean build: remove old build directory
    if clean_build and os.path.exists(build_path):
        import shutil
        shutil.rmtree(build_path)

    # Use Visual Studio generator (proven to work with llama.cpp)
    import platform
    generator_flags = []
    if platform.system() == "Windows":
        # Find VS using vswhere
        vswhere = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
        if os.path.exists(vswhere):
            try:
                result = subprocess.run(
                    [vswhere, "-latest", "-products", "*", 
                     "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                     "-property", "installationVersion"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    vs_version = result.stdout.strip().split(".")[0]
                    vs_major = int(vs_version)
                    if vs_major == 17:
                        generator_flags = ["-G", "Visual Studio 17 2022", "-A", "x64"]
                    elif vs_major == 16:
                        generator_flags = ["-G", "Visual Studio 16 2019", "-A", "x64"]
                    elif vs_major == 15:
                        generator_flags = ["-G", "Visual Studio 15 2017", "-A", "x64"]
                    
                    # Find ml64.exe for ASM support
                    vs_path_result = subprocess.run(
                        [vswhere, "-latest", "-products", "*",
                         "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                         "-property", "installationPath"],
                        capture_output=True, text=True, timeout=10
                    )
                    if vs_path_result.returncode == 0 and vs_path_result.stdout.strip():
                        vs_path = vs_path_result.stdout.strip()
                        # Find MSVC version
                        msvc_base = os.path.join(vs_path, "VC", "Tools", "MSVC")
                        if os.path.exists(msvc_base):
                            versions = sorted(os.listdir(msvc_base), reverse=True)
                            if versions:
                                ml64_path = os.path.join(msvc_base, versions[0], "bin", "Hostx64", "x64", "ml64.exe")
                                if os.path.exists(ml64_path):
                                    # Add ASM compiler path
                                    flags.append(f"-DCMAKE_ASM_COMPILER={ml64_path}")
            except:
                pass

    # Add CMAKE_BUILD_TYPE for single-config generators
    if not generator_flags and not any("-DCMAKE_BUILD_TYPE" in f for f in flags):
        flags.insert(0, "-DCMAKE_BUILD_TYPE=Release")

    # Add recommended flags for llama.cpp. GGML_NATIVE=ON lets llama.cpp's
    # own CPUID detection enable AVX2/AVX512/FMA/F16C/AMX automatically; do
    # NOT hard-code AVX2/FMA/F16C here (that disables AVX512/AMX).
    if not any("-DGGML_NATIVE" in f for f in flags):
        flags.append("-DGGML_NATIVE=ON")

    # Build command as list (important for generator with spaces)
    cmd_parts = ["cmake", "-S", repo_path, "-B", build_path]
    cmd_parts.extend(generator_flags)
    for flag in flags:
        cmd_parts.append(flag)

    # Convert to string for shell execution
    cmd_str = " ".join(f'"{part}"' if " " in part else part for part in cmd_parts)
    
    return cmd_str, build_path, flags


def generate_build_command(build_path):
    """Generate the CMake build command."""
    # For Visual Studio generator, use --config Release
    # Check if Visual Studio was used (CMakeCache.txt contains generator info)
    cache_file = os.path.join(build_path, "CMakeCache.txt")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                content = f.read()
                if "Visual Studio" in content:
                    return f'cmake --build "{build_path}" --config Release --parallel'
        except:
            pass
    # Default for single-config generators (Ninja, Makefiles)
    return f'cmake --build "{build_path}" --parallel'


def run_build(source_id, build_type, update_repo_flag=False,
              custom_flags=None, clean_build=False, callback=None,
              build_ui=False):
    """
    Run the full build process using the platform build script.
    Windows uses build_llamacpp.ps1 (PowerShell); macOS/Linux use
    build_llamacpp.sh. Returns (success, output_lines, error_message, binaries).
    callback(line) is called for each output line.
    """
    import sys
    import io
    import platform

    # Set stdout encoding to UTF-8 to handle all characters
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass

    source = get_source_by_id(source_id)
    if not source:
        msg = f"Source '{source_id}' not found."
        if callback:
            callback(msg)
        return False, [msg], msg, []

    system = platform.system()

    # Custom CMake flags are passed as a newline-joined string so that flags
    # may contain spaces (e.g. -DCMAKE_PREFIX_PATH=...) without quoting issues.
    flags_str = "\n".join(custom_flags) if custom_flags else ""

    if system == "Windows":
        script_path = os.path.join(ROOT_DIR, "build_llamacpp.ps1")
        if not os.path.exists(script_path):
            msg = f"Build script not found: {script_path}"
            if callback:
                callback(msg)
            return False, [msg], msg, []
        # Use -File (not -Command) so args are bound cleanly and there are no
        # quoting headaches around -ExtraFlags / build paths.
        cmd = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", script_path,
               "-Source", source_id, "-BuildType", build_type]
        if update_repo_flag:
            cmd.append("-Update")
        if clean_build:
            cmd.append("-CleanBuild")
        if build_ui:
            cmd.append("-BuildUi")
        if flags_str:
            cmd += ["-ExtraFlags", flags_str]
        encoding = 'latin-1'
    else:
        script_path = os.path.join(ROOT_DIR, "build_llamacpp.sh")
        if not os.path.exists(script_path):
            msg = f"Build script not found: {script_path}"
            if callback:
                callback(msg)
            return False, [msg], msg, []
        cmd = ["bash", script_path, "-s", source_id, "-t", build_type]
        if update_repo_flag:
            cmd.append("-U")
        if clean_build:
            cmd.append("-c")
        if build_ui:
            cmd.append("-u")
        if flags_str:
            cmd += ["-F", flags_str]
        encoding = 'utf-8'

    if callback:
        callback("=" * 60)
        callback(f"Starting build ({system})")
        callback(f"  Source: {source_id}")
        callback(f"  Build Type: {build_type}")
        callback(f"  Script: {script_path}")
        callback("=" * 60)

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding=encoding,
            errors='replace'
        )

        all_output = []
        for line in process.stdout:
            line = line.rstrip('\n\r')
            all_output.append(line)
            if callback:
                callback(line)

        process.wait()

        if process.returncode != 0:
            msg = f"Build failed with exit code {process.returncode}"
            if callback:
                callback(msg)
            return False, all_output, msg, []

        # Find binaries
        build_path = get_build_path(source_id, build_type)
        binaries = find_binaries(build_path)

        if callback:
            callback("=" * 60)
            callback("BUILD SUCCESSFUL!")
            callback(f"Binaries found: {len(binaries)}")

        return True, all_output, None, binaries

    except Exception as e:
        msg = f"Build error: {str(e)}"
        if callback:
            callback(msg)
        return False, [msg], msg, []


def run_command(cmd, cwd=None, callback=None):
    """Run a shell command with live output."""
    try:
        process = subprocess.Popen(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )

        output_lines = []
        while True:
            line = process.stdout.readline()
            if not line:
                break
            line = line.rstrip("\n")
            output_lines.append(line)
            if callback:
                callback(line)

        process.wait()
        return process.returncode == 0, output_lines, "".join(output_lines)

    except Exception as e:
        err_msg = str(e)
        if callback:
            callback(f"Error running command: {err_msg}")
        return False, [err_msg], err_msg


def find_binaries(build_path):
    """Find built binaries in the build directory."""
    binaries = []
    if not os.path.isdir(build_path):
        return binaries

    for root, dirs, files in os.walk(build_path):
        for f in files:
            if f.startswith("llama-"):
                full_path = os.path.join(root, f)
                binaries.append(full_path)

    return binaries


def save_build_result(source_id, build_type, success, build_path,
                      binaries=None, duration=None, error_message=None):
    """Save build result to build_history.json."""
    source = get_source_by_id(source_id) if source_id else None

    entry = {
        "date": datetime.now().isoformat(),
        "source": source_id,
        "source_name": source.get("name", "unknown") if source else "unknown",
        "build_type": build_type,
        "success": success,
        "build_path": build_path,
        "duration_seconds": duration or 0,
        "error_message": error_message or ""
    }

    if binaries:
        entry["binaries"] = binaries

    if source:
        entry["repo_url"] = source.get("repo_url", "")
        entry["branch"] = source.get("branch", "")

    # Load existing history
    history = []
    if os.path.exists(BUILD_HISTORY_FILE):
        try:
            with open(BUILD_HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []

    history.append(entry)

    # Keep last 100 entries
    history = history[-100:]

    with open(BUILD_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

    return entry


def get_build_history():
    """Load build history."""
    if not os.path.exists(BUILD_HISTORY_FILE):
        return []
    try:
        with open(BUILD_HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def get_error_explanation(error_message):
    """Provide a human-readable explanation for common errors."""
    error_lower = error_message.lower() if error_message else ""
    
    # Check for "not found" or "not in PATH" patterns first
    if "cmake" in error_lower and ("not found" in error_lower or "not recognized" in error_lower or "is not recognized" in error_lower):
        return {
            "cause": "CMake not found or not in PATH",
            "solution": "Install CMake and restart the application.",
            "fallback": "Install CMake via winget or package manager."
        }
    elif "cuda" in error_lower and ("not found" in error_lower or "compiler" in error_lower or "toolkit" in error_lower):
        return {
            "cause": "CUDA Toolkit/compiler not found",
            "solution": "Install CUDA Toolkit or choose CPU/Vulkan build.",
            "fallback": "Use main llama.cpp CPU build."
        }
    elif "sycl" in error_lower or "icpx" in error_lower or "icx" in error_lower or "oneapi" in error_lower:
        return {
            "cause": "Intel oneAPI DPC++/C++ Compiler not found",
            "solution": "Install Intel oneAPI Base Toolkit or choose CPU/Vulkan build.",
            "fallback": "Use main llama.cpp CPU build."
        }
    elif "git" in error_lower and ("not found" in error_lower or "not recognized" in error_lower):
        return {
            "cause": "Git not found or not in PATH",
            "solution": "Install Git and restart the application.",
            "fallback": "Install Git via winget or package manager."
        }
    elif ("msvc" in error_lower or "cl.exe" in error_lower) and ("not found" in error_lower or "cannot open" in error_lower):
        return {
            "cause": "Visual Studio Build Tools (MSVC) not found",
            "solution": "Install Visual Studio Build Tools 2022.",
            "fallback": "Install via winget: Microsoft.VisualStudio.2022.BuildTools"
        }
    elif "ninja" in error_lower and ("not found" in error_lower or "not recognized" in error_lower):
        return {
            "cause": "Ninja not found",
            "solution": "Install Ninja. Recommended for faster and more stable builds.",
            "fallback": "Install via winget or package manager."
        }
    elif "disk" in error_lower or "space" in error_lower or "no space" in error_lower:
        return {
            "cause": "Not enough free disk space",
            "solution": "Free up disk space and try again.",
            "fallback": "Ensure at least 5GB free space."
        }
    elif "cuda" in error_lower and ("gpu" in error_lower or "device" in error_lower):
        return {
            "cause": "CUDA build chosen but no NVIDIA GPU detected",
            "solution": "Check GPU hardware or switch to CPU/Vulkan build.",
            "fallback": "Use main llama.cpp CPU build."
        }
    elif "configuring incomplete" in error_lower or "configuration failed" in error_lower:
        return {
            "cause": "CMake configuration failed",
            "solution": "Check the build log above for specific errors. Common causes: missing dependencies, incompatible compiler, or wrong CMake flags.",
            "fallback": "Try CPU build first, or check llama.cpp documentation for requirements."
        }
    elif "build failed" in error_lower or "compilation failed" in error_lower:
        return {
            "cause": "Build/compilation failed",
            "solution": "Check the build log above for specific compiler errors. May be due to code issues or incompatible compiler version.",
            "fallback": "Try main llama.cpp with CPU build."
        }
    elif "branch" in error_lower:
        return {
            "cause": "Specified branch not found in repository",
            "solution": "Check the branch name and try again.",
            "fallback": "Use 'master' branch."
        }
    elif "experimental" in error_lower:
        return {
            "cause": "Experimental build failed",
            "solution": "Experimental forks may have different build requirements.",
            "fallback": "Use main llama.cpp as a fallback."
        }

    return {
        "cause": "Unknown error",
        "solution": "Check the build log for details.",
        "fallback": "Try main llama.cpp CPU build."
    }


if __name__ == "__main__":
    print("Build module loaded.")
