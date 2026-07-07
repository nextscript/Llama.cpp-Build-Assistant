"""
Dependency installer module.
Installs missing programs using platform-appropriate package managers.
Windows: winget (preferred)
Linux: apt, dnf, pacman, zypper
No installation without user confirmation.
"""
import subprocess
import platform
import os
import shlex
import shutil
from config import INSTALL_LOG_FILE
from logger import log_install, log_error
from dependency_checker import check_all


def run_command(cmd, timeout=300):
    """Run a command and return (success, stdout, stderr).
    Handles winget special exit codes as success when appropriate."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                shell=True, timeout=timeout)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        
        # winget exit code 43 = already installed
        if result.returncode == 43:
            return True, stdout, stderr
        
        # winget exit code 2316632107 (0x89AB0003) = package already installed, no upgrade
        # Check output for German success messages
        if result.returncode == 2316632107:
            if "bereits" in stdout or "kein verfügbares Upgrade" in stdout:
                return True, stdout, stderr
        
        # winget exit code 2316632107 = also check for English messages
        if result.returncode == 2316632107:
            if "already" in stdout.lower() or "no available upgrade" in stdout.lower():
                return True, stdout, stderr
        
        return result.returncode == 0, stdout, stderr
    except subprocess.TimeoutExpired:
        return False, "", "Timeout"
    except Exception as e:
        return False, "", str(e)


def run_privileged(cmd, timeout=300):
    """Run a command that needs root privileges (Linux).

    GUI apps cannot safely use plain ``sudo``: when there is no usable TTY the
    password prompt is hidden or sudo fails with "a password is required" / "no
    tty present". Prefer an already-authenticated sudo session, otherwise use
    ``pkexec`` so polkit can show a native authentication dialog. If neither is
    possible, fail loudly and show an exact terminal command instead of silently
    skipping the dependency.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid and geteuid() == 0:
        return run_command(cmd, timeout=timeout)

    sudo = shutil.which("sudo")
    if sudo:
        try:
            cached = subprocess.run(
                [sudo, "-n", "true"],
                capture_output=True,
                text=True,
                timeout=10,
            ).returncode == 0
        except Exception:
            cached = False

        if cached:
            return run_command(
                f"{shlex.quote(sudo)} -n sh -c {shlex.quote(cmd)}",
                timeout=timeout,
            )

    pkexec = shutil.which("pkexec")
    if pkexec:
        # pkexec authenticates via a GUI dialog, then runs the command as root.
        return run_command(
            f"{shlex.quote(pkexec)} sh -c {shlex.quote(cmd)}",
            timeout=timeout,
        )

    manual_cmd = f"sudo sh -c {shlex.quote(cmd)}"
    return (
        False,
        "",
        "Root privileges are required, but automatic authentication is not "
        "available (no cached sudo session and pkexec was not found).\n"
        "Please run this command in a terminal, then re-run the dependency "
        f"check:\n  {manual_cmd}",
    )


def has_winget():
    """Check if winget is available on Windows."""
    return subprocess.run("winget --version", capture_output=True,
                          shell=True, timeout=10).returncode == 0


def has_sudo():
    """Check if sudo is available."""
    return subprocess.run("sudo --version", capture_output=True,
                          shell=True, timeout=10).returncode == 0


def has_brew():
    """Check if Homebrew is available (macOS)."""
    return shutil.which("brew") is not None


def get_linux_package_manager():
    """Detect the Linux package manager (by presence, not by execution)."""
    for pm in ["apt", "dnf", "pacman", "zypper"]:
        if shutil.which(pm):
            return pm
    return None


def install_git():
    """Install Git."""
    system = platform.system()
    if system == "Windows":
        if has_winget():
            return run_command("winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements")
    elif system == "Darwin":
        if has_brew():
            return run_command("brew install git")
        return False, "", "Homebrew not found. Install from https://brew.sh"
    elif system == "Linux":
        pm = get_linux_package_manager()
        if pm == "apt":
            return run_privileged("apt update && apt install -y git")
        elif pm == "dnf":
            return run_privileged("dnf install -y git")
        elif pm == "pacman":
            return run_privileged("pacman -Syu --needed git --noconfirm")
        elif pm == "zypper":
            return run_privileged("zypper install -y git")
    return False, "", "No supported package manager"


def install_cmake():
    """Install CMake."""
    system = platform.system()
    if system == "Windows":
        if has_winget():
            return run_command("winget install --id Kitware.CMake -e --source winget --accept-source-agreements --accept-package-agreements")
    elif system == "Darwin":
        if has_brew():
            return run_command("brew install cmake")
        return False, "", "Homebrew not found. Install from https://brew.sh"
    elif system == "Linux":
        pm = get_linux_package_manager()
        if pm == "apt":
            return run_privileged("apt install -y cmake")
        elif pm == "dnf":
            return run_privileged("dnf install -y cmake")
        elif pm == "pacman":
            return run_privileged("pacman -Syu --needed cmake --noconfirm")
        elif pm == "zypper":
            return run_privileged("zypper install -y cmake")
    return False, "", "No supported package manager"


def install_ninja():
    """Install Ninja."""
    system = platform.system()
    if system == "Windows":
        if has_winget():
            return run_command("winget install --id Ninja-build.Ninja -e --source winget --accept-source-agreements --accept-package-agreements")
    elif system == "Darwin":
        if has_brew():
            return run_command("brew install ninja")
        return False, "", "Homebrew not found. Install from https://brew.sh"
    elif system == "Linux":
        pm = get_linux_package_manager()
        if pm == "apt":
            return run_privileged("apt install -y ninja-build")
        elif pm == "dnf":
            return run_privileged("dnf install -y ninja-build")
        elif pm == "pacman":
            return run_privileged("pacman -Syu --needed ninja --noconfirm")
        elif pm == "zypper":
            return run_privileged("zypper install -y ninja")
    return False, "", "No supported package manager"


def install_vs_build_tools():
    """Install Visual Studio Build Tools."""
    if platform.system() != "Windows":
        return False, "", "Not Windows"
    if has_winget():
        # Check if already installed via vswhere
        vswhere = shutil.which("vswhere")
        if vswhere:
            return True, "Visual Studio Build Tools already installed (detected via vswhere)", ""
        return run_command(
            "winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget "
            "--accept-source-agreements --accept-package-agreements "
            "--override \"--wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended\""
        )
    return False, "", "winget not available"


def install_cuda_toolkit():
    """Install CUDA Toolkit."""
    system = platform.system()
    # Check if nvcc is already available
    if shutil.which("nvcc"):
        return True, "CUDA Toolkit already installed (nvcc found)", ""
    if system == "Windows":
        if has_winget():
            return run_command("winget install --id Nvidia.CUDA -e --source winget --accept-source-agreements --accept-package-agreements")
    # Linux CUDA installation is complex; better to guide manually
    return False, "", "CUDA installation requires manual setup. Please visit https://developer.nvidia.com/cuda-downloads"


def install_vulkan_sdk():
    """Install Vulkan SDK."""
    system = platform.system()
    # Check if vulkaninfo is already available
    if shutil.which("vulkaninfo"):
        return True, "Vulkan SDK already installed (vulkaninfo found)", ""
    if system == "Windows":
        if has_winget():
            return run_command("winget install --id KhronosGroup.VulkanSDK -e --source winget --accept-source-agreements --accept-package-agreements")
    elif system == "Linux":
        pm = get_linux_package_manager()
        if pm == "apt":
            return run_privileged("apt install -y vulkan-sdk")
        elif pm == "pacman":
            return run_privileged("pacman -Syu --needed vulkan-icd-loader --noconfirm")
    return False, "", "Vulkan SDK installation is complex. Please visit https://vulkan.lunarg.com/"


def install_intel_oneapi():
    """Install Intel oneAPI DPC++/C++ Compiler."""
    system = platform.system()
    # Check if already installed
    if shutil.which("icpx") or shutil.which("icx"):
        return True, "Intel oneAPI already installed (icpx/icx found)", ""
    
    if system == "Windows":
        if has_winget():
            return run_command("winget install --id Intel.oneAPI.BaseToolkit -e --source winget --accept-source-agreements --accept-package-agreements")
    elif system == "Linux":
        pm = get_linux_package_manager()
        if pm == "apt":
            return run_privileged("apt install -y intel-oneapi-compiler-dpcpp-cpp")
        elif pm == "dnf":
            return run_privileged("dnf install -y intel-oneapi-compiler-dpcpp-cpp")
    
    return False, "", "Intel oneAPI installation requires manual setup. Please visit https://www.intel.com/content/www/us/en/developer/tools/oneapi/base-toolkit-download.html"


def install_compiler():
    """Install a C/C++ compiler.
    On Windows, VS Build Tools is too large for auto-install — show manual guide instead."""
    system = platform.system()
    if system == "Windows":
        # VS Build Tools is too large and complex for automatic installation.
        # Return a message directing the user to manual installation.
        return (False,
                "VS Build Tools cannot be auto-installed (too large).\n"
                "Please install manually:\n"
                "  1. Download from https://visualstudio.microsoft.com/downloads/\n"
                "  2. Select 'Desktop development with C++' workload\n"
                "  3. Or run: winget install --id Microsoft.VisualStudio.2022.BuildTools -e\n"
                "  4. Restart the application after installation.",
                "")
    elif system == "Darwin":
        # Xcode Command Line Tools provide clang
        if not shutil.which("clang"):
            return run_command("xcode-select --install")
        return True, "Xcode Command Line Tools already installed", ""
    elif system == "Linux":
        pm = get_linux_package_manager()
        if pm == "apt":
            return run_privileged("apt install -y build-essential")
        elif pm == "dnf":
            return run_privileged("dnf install -y gcc gcc-c++ make")
        elif pm == "pacman":
            return run_privileged("pacman -Syu --needed base-devel --noconfirm")
        elif pm == "zypper":
            return run_privileged("zypper install -y gcc gcc-c++ make")
    return False, "", "No supported package manager"


# Map of dependency name to installer function
INSTALL_MAP = {
    "git": install_git,
    "cmake": install_cmake,
    "ninja": install_ninja,
    "vs_build_tools": install_vs_build_tools,
    "cuda_toolkit": install_cuda_toolkit,
    "vulkan_sdk": install_vulkan_sdk,
    "compiler": install_compiler,
    "intel_oneapi": install_intel_oneapi,
}


def install_missing(missing_deps, callback=None):
    """
    Install missing dependencies one by one.
    callback(line) is called for each output line (for live logging).
    Returns a dict of {dep: (success, message)}.
    """
    results = {}
    log_install(f"Starting installation of: {', '.join(missing_deps)}")

    for dep in missing_deps:
        installer = INSTALL_MAP.get(dep)
        if not installer:
            results[dep] = (False, f"No installer for '{dep}'")
            log_install(f"  {dep}: No installer available")
            continue

        if callback:
            callback(f"Installing {dep}...")

        success, stdout, stderr = installer()
        if success:
            msg = stdout.strip()
        else:
            msg = stderr.strip() or stdout.strip() or "Installation failed"
        results[dep] = (success, msg)

        log_install(f"  {dep}: {'OK' if success else 'FAILED'} - {msg}")

        if callback:
            if success:
                callback(f"{dep}: OK")
            else:
                callback(f"{dep}: FAILED - {msg}")

    return results


def get_install_commands(missing_deps):
    """Return the commands that would be executed for the given missing deps."""
    commands = []
    for dep in missing_deps:
        installer = INSTALL_MAP.get(dep)
        if installer:
            commands.append(installer.__doc__.strip() if installer.__doc__ else dep)
    return commands


def check_after_install():
    """Re-check all dependencies after installation."""
    return check_all()


if __name__ == "__main__":
    results = check_all()
    missing = [k for k, v in results.items() if not v.get("found", False)]
    print(f"Missing: {missing}")
    print("Would install:", get_install_commands(missing))
