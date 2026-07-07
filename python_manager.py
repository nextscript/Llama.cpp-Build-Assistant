"""
Cross-platform Python interpreter manager.

This module uses ONLY the Python standard library so that it can run under
*any* available Python (e.g. a bleeding-edge 3.14) to set up a project-local
virtual environment and select it for the project's requirements.txt.

Strategy (v0.3+): project-local virtualenv
-------------------------------------------
Modern Linux distros (Ubuntu 23.04+, Debian 12+, Fedora) mark the system
interpreter as *externally managed* (PEP 668), so `pip install` into it fails
with "externally-managed-environment". Installing system-wide also risks
breaking the OS Python. The robust, sudo-free, cross-platform solution is to
create a virtualenv inside the project (``<root>/.venv``) and install the
dependencies there. This works identically on Windows, macOS and Linux and
supports Python 3.12 / 3.13 / 3.14.

Responsibilities
----------------
1. Discover every Python interpreter installed on the system.
2. Select a suitable base interpreter (3.9+, preferring the newest in the
   3.12–3.14 range).
3. Create (or reuse) a project virtualenv and install requirements.txt into it.
4. Only if NO usable interpreter exists at all, offer to install one from the
   official source (last resort).
5. Expose the chosen *venv* interpreter path for the launchers and the app.
"""
from __future__ import annotations

import os
import re
import sys
import json
import shutil
import subprocess
import platform
import urllib.request
from typing import List, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_FILE = os.path.join(ROOT_DIR, "requirements.txt")
VENV_DIR = os.path.join(ROOT_DIR, ".venv")

# Packages that the app actually imports at runtime. We probe these to decide
# whether a virtualenv is "ready".
REQUIRED_IMPORTS = {
    "customtkinter": "customtkinter",
    "psutil": "psutil",
    "py-cpuinfo": "cpuinfo",
    "GPUtil": "GPUtil",
    "packaging": "packaging",
    "rich": "rich",
}

# Python version policy.
#  - MIN_SUPPORTED: anything below is rejected outright.
#  - PREFERRED_MAX: we prefer interpreters at or below this. 3.14 is now a
#    first-class target (all deps are pure-Python or ship 3.14 wheels).
MIN_SUPPORTED = (3, 9)
PREFERRED_MAX = (3, 14)

# Version installed automatically when nothing usable is found at all.
RECOMMENDED_INSTALL = (3, 13)

# python.org metadata for fetching the latest patch release of a minor version.
PYTHON_VERSIONS_JSON = "https://www.python.org/ftp/python/"

# Timeout (seconds) for discovery subprocesses.
_PROBE_TIMEOUT = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: List[str], timeout: int = _PROBE_TIMEOUT) -> Tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out, err
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


def parse_version(version_str: str) -> Optional[Tuple[int, int, int]]:
    """Parse a version string like '3.13.1' or 'Python 3.13' into a tuple."""
    if not version_str:
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) else 0
    return (major, minor, patch)


def version_str(ver: Optional[Tuple[int, int, int]]) -> str:
    if not ver:
        return "?"
    return ".".join(str(x) for x in ver)


def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


# ---------------------------------------------------------------------------
# Discovery (unchanged)
# ---------------------------------------------------------------------------

def _get_python_version(exe: str) -> Optional[Tuple[int, int, int]]:
    """Return the version tuple of an interpreter, or None if it won't run."""
    rc, out, _ = _run([exe, "--version"])
    text = (out or "").strip()
    if rc != 0 or not text:
        rc2, _, err = _run([exe, "--version"])
        text = (err or "").strip() or text
    return parse_version(text)


def _package_ok(exe: str, import_name: str) -> bool:
    """True if a package imports cleanly under the given interpreter."""
    rc, _, _ = _run([exe, "-c", f"import {import_name}"], timeout=30)
    return rc == 0


def _requirements_importable(exe: str) -> int:
    """Return the number of required packages that import successfully."""
    ok = 0
    for import_name in REQUIRED_IMPORTS.values():
        if _package_ok(exe, import_name):
            ok += 1
    return ok


def _tkinter_ok(exe: str) -> bool:
    """customtkinter requires tkinter; check it is importable."""
    rc, _, _ = _run([exe, "-c", "import tkinter"], timeout=15)
    return rc == 0


class PyInfo:
    """A discovered Python interpreter."""

    def __init__(self, path: str, version: Optional[Tuple[int, int, int]],
                 source: str = ""):
        self.path = _norm(path)
        self.version = version
        self.source = source
        self.imports_ok = -1  # cached count of working required imports

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    @property
    def usable(self) -> bool:
        return bool(self.version) and self.exists

    def check_imports(self) -> int:
        if self.imports_ok < 0:
            self.imports_ok = _requirements_importable(self.path) if self.usable else 0
        return self.imports_ok

    @property
    def ready(self) -> bool:
        """True if *all* required packages import under this interpreter."""
        return self.check_imports() == len(REQUIRED_IMPORTS)

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "version": version_str(self.version) if self.version else None,
            "source": self.source,
            "required_imports_ok": self.check_imports(),
            "required_total": len(REQUIRED_IMPORTS),
            "ready": self.ready,
        }

    def __repr__(self) -> str:
        v = version_str(self.version) if self.version else "?"
        return f"PyInfo({v} @ {self.path} [{self.source}])"


def _add_unique(found: List[PyInfo], candidates: List[Tuple[str, str]]) -> None:
    """Add candidate (path, source) entries if not already present (by path)."""
    seen = {p.path for p in found}
    for path, source in candidates:
        if not path:
            continue
        path = _norm(path)
        if path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            ver = _get_python_version(path)
            if ver:
                found.append(PyInfo(path, ver, source))


def _discover_windows() -> List[PyInfo]:
    found: List[PyInfo] = []
    cands: List[Tuple[str, str]] = []

    # 1. py launcher (most reliable on Windows) -> `py -0p`
    rc, out, _ = _run(["py", "-0p"])
    if rc == 0 and out:
        for line in out.splitlines():
            line = line.strip()
            m = re.search(r"([A-Za-z]:\\.*python\.exe)", line, re.IGNORECASE)
            if m:
                cands.append((m.group(1), "py-launcher"))

    # 2. Registry (both per-user and all-users)
    try:
        import winreg  # type: ignore
        for hive, flags in [
            (winreg.HKEY_CURRENT_USER, winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_CURRENT_USER, winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
        ]:
            try:
                key = winreg.OpenKey(
                    hive, r"SOFTWARE\Python\PythonCore", 0, flags)
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                        i += 1
                        sk = winreg.OpenKey(key, f"{sub}\\InstallPath")
                        try:
                            ipath, _ = winreg.QueryValueEx(sk, None)
                        finally:
                            winreg.CloseKey(sk)
                        if ipath:
                            exe = os.path.join(ipath, "python.exe")
                            cands.append((exe, f"registry:{sub}"))
                    except OSError:
                        break
                winreg.CloseKey(key)
            except OSError:
                pass
    except Exception:
        pass

    # 3. Common install locations (Microsoft Store + python.org)
    common = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python"),
        os.path.expandvars(r"%ProgramFiles%\Python314"),
        os.path.expandvars(r"%ProgramFiles%\Python313"),
        os.path.expandvars(r"%ProgramFiles%\Python312"),
        os.path.expandvars(r"%ProgramFiles%\Python311"),
        os.path.expandvars(r"%ProgramFiles%\Python310"),
    ]
    for base in common:
        if os.path.isdir(base):
            for name in os.listdir(base):
                exe = os.path.join(base, name, "python.exe")
                if os.path.isfile(exe):
                    cands.append((exe, f"path:{base}"))

    # 4. PATH lookups
    for name in ("python", "python3", "python3.14", "python3.13", "python3.12", "python3.11"):
        resolved = shutil.which(name)
        if resolved:
            cands.append((resolved, f"PATH:{name}"))

    _add_unique(found, cands)
    return found


def _discover_unix() -> List[PyInfo]:
    found: List[PyInfo] = []
    cands: List[Tuple[str, str]] = []

    # 1. versioned binaries across well-known locations
    search_dirs = [
        "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/homebrew/opt",
        "/opt/conda/bin", os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.pyenv/versions"),
        os.path.expanduser("~/.conda/bin"),
    ]
    minor_versions = ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for mv in minor_versions:
            exe = os.path.join(d, f"python{mv}")
            if os.path.isfile(exe):
                cands.append((exe, f"dir:{d}"))
        if "pyenv" in d:
            for name in entries:
                exe = os.path.join(d, name, "bin", "python")
                if os.path.isfile(exe):
                    cands.append((exe, f"pyenv:{name}"))

    # 2. generic names on PATH
    for name in ("python3", "python", "python3.14", "python3.13", "python3.12", "python3.11"):
        resolved = shutil.which(name)
        if resolved:
            cands.append((resolved, f"PATH:{name}"))

    _add_unique(found, cands)
    return found


def discover_pythons() -> List[PyInfo]:
    """Discover every usable Python interpreter on this machine."""
    system = platform.system()
    found = _discover_windows() if system == "Windows" else _discover_unix()

    current = _norm(sys.executable)
    if current and not any(p.path == current for p in found):
        ver = _get_python_version(current)
        if ver:
            found.append(PyInfo(current, ver, "current-process"))

    found.sort(key=lambda p: p.version or (0, 0, 0), reverse=True)
    return found


# ---------------------------------------------------------------------------
# Virtualenv management (NEW — solves PEP 668)
# ---------------------------------------------------------------------------

def _venv_python_path() -> str:
    """Path to the venv's python executable (platform-aware)."""
    if platform.system() == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def venv_ready() -> bool:
    """True if the project venv exists AND all required packages import."""
    vpy = _venv_python_path()
    return bool(vpy and os.path.isfile(vpy)
                and _requirements_importable(vpy) == len(REQUIRED_IMPORTS))


def _bootstrap_pip_in_venv(base_exe: str, on_log=None) -> bool:
    """Create a venv without pip, then bootstrap pip via get-pip.py.

    Needed on Debian/Ubuntu where ``ensurepip`` is disabled and
    ``python -m venv`` refuses to install pip into the new environment.
    """
    def log(msg):
        if on_log:
            on_log(msg)
    rc, _, err = _run([base_exe, "-m", "venv", "--clear", "--without-pip", VENV_DIR],
                      timeout=120)
    vpy = _venv_python_path()
    if rc != 0 or not vpy or not os.path.isfile(vpy):
        log(f"venv (without pip) creation failed: {err.strip()[:200]}")
        return False
    log("Bootstrapping pip via get-pip.py (ensurepip is unavailable) ...")
    gp = os.path.join(VENV_DIR, "get-pip.py")
    try:
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", gp)
    except Exception as e:  # noqa: BLE001
        log(f"Could not download get-pip.py: {e}")
        return False
    rc, _, err = _run([vpy, gp, "--disable-pip-version-check"], timeout=180)
    if rc != 0:
        log(f"get-pip.py failed: {err.strip()[:200]}")
        return False
    return True


def _create_venv(base_exe: str, on_log=None) -> bool:
    """Create a fresh project venv from base_exe (with pip). Returns success."""
    def log(msg):
        if on_log:
            on_log(msg)

    # Standard creation (installs pip via ensurepip).
    rc, out, err = _run([base_exe, "-m", "venv", "--clear", VENV_DIR], timeout=180)
    vpy = _venv_python_path()
    if rc != 0 or not vpy or not os.path.isfile(vpy):
        # ensurepip likely disabled (Debian/Ubuntu) -> bootstrap pip manually.
        log("Standard venv creation failed; trying pip bootstrap ...")
        return _bootstrap_pip_in_venv(base_exe, on_log=on_log)

    # Verify pip is actually usable in the new venv.
    rc2, _, _ = _run([vpy, "-m", "pip", "--version"], timeout=30)
    if rc2 != 0:
        return _bootstrap_pip_in_venv(base_exe, on_log=on_log)
    return True


def ensure_venv(base_exe: str, on_log=None) -> Optional[str]:
    """Create or reuse the project virtualenv and install requirements.

    Returns the venv python path on success, or None on failure. Installing
    into a venv avoids the externally-managed-environment (PEP 668) error.
    """
    def log(msg):
        if on_log:
            on_log(msg)

    # Fast path: reuse an existing, ready venv.
    if venv_ready():
        log(f"Reusing existing virtualenv: {VENV_DIR}")
        return _venv_python_path()

    if not os.path.isfile(base_exe):
        log(f"Base interpreter not found: {base_exe}")
        return None

    base_ver = _get_python_version(base_exe)
    log(f"Creating virtualenv at {VENV_DIR} "
        f"(base: Python {version_str(base_ver)} @ {base_exe}) ...")

    if not _create_venv(base_exe, on_log=on_log):
        log("Could not create a virtualenv with this interpreter.")
        return None

    vpy = _venv_python_path()
    if not vpy or not os.path.isfile(vpy):
        return None

    # Upgrade pip, then install requirements into the venv.
    _run([vpy, "-m", "pip", "install", "--upgrade", "pip",
          "--disable-pip-version-check"], timeout=180)
    log("Installing requirements into virtualenv ...")
    rc, out, err = _run(
        [vpy, "-m", "pip", "install", "-r", REQUIREMENTS_FILE,
         "--disable-pip-version-check"],
        timeout=600,
    )
    if rc != 0:
        log(f"pip install failed (rc={rc})\n{err.strip()[:500]}")
        return None
    log("Requirements installed into virtualenv.")
    return vpy


def _warn_tkinter_if_missing(exe: str, on_log=None) -> None:
    """customtkinter needs tkinter; warn clearly if it is unavailable."""
    if _tkinter_ok(exe):
        return

    def log(msg):
        if on_log:
            on_log(msg)
    system = platform.system()
    log("WARNING: tkinter is not available for this interpreter.")
    log("The GUI (customtkinter) requires tkinter. Install it:")
    if system == "Linux":
        rc, out, _ = _run(["cat", "/etc/os-release"])
        low = out.lower()
        if "ubuntu" in low or "debian" in low:
            log("  sudo apt install python3-tk")
        elif "fedora" in low:
            log("  sudo dnf install python3-tkinter")
        elif "arch" in low:
            log("  sudo pacman -S tk")
        else:
            log("  Install the tk/tkinter package for your distribution.")
    elif system == "Darwin":
        log("  brew install python-tk   (or reinstall python.org Python)")
    else:
        log("  Reinstall Python from python.org with tcl/tk included.")


# ---------------------------------------------------------------------------
# Selection (base interpreter — the venv is created from it)
# ---------------------------------------------------------------------------

def _in_supported_range(ver: Optional[Tuple[int, int, int]]) -> bool:
    return bool(ver) and MIN_SUPPORTED <= ver[:2] <= PREFERRED_MAX


def select_best(discover: Optional[List[PyInfo]] = None,
                allow_install: bool = True,
                on_log=None) -> Optional[PyInfo]:
    """Select the best BASE interpreter to build the venv from.

    Prefers the newest interpreter inside the supported range; falls back to
    any supported interpreter (incl. bleeding edge) if none is in range.
    """
    def log(msg):
        if on_log:
            on_log(msg)
    found = discover if discover is not None else discover_pythons()
    supported = [p for p in found if p.version and p.version[:2] >= MIN_SUPPORTED]
    if not supported:
        return None
    in_range = [p for p in supported if p.version[:2] <= PREFERRED_MAX]
    pool = in_range if in_range else supported
    pool.sort(key=lambda p: p.version or (0, 0, 0), reverse=True)
    best = pool[0]
    log(f"Selected base interpreter Python {version_str(best.version)} ({best.path})")
    return best


# ---------------------------------------------------------------------------
# Official installation (last resort: no usable interpreter at all)
# ---------------------------------------------------------------------------

def _latest_patch(minor: Tuple[int, int], on_log=None) -> Optional[str]:
    """Find the latest patch release for a minor version via python.org."""
    def log(msg):
        if on_log:
            on_log(msg)
    try:
        with urllib.request.urlopen(PYTHON_VERSIONS_JSON, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        log(f"Could not reach python.org: {e}")
        return None
    prefix = f"{minor[0]}.{minor[1]}."
    patches = []
    for m in re.finditer(r'href="(\d+\.\d+\.\d+)/"', html):
        v = m.group(1)
        if v.startswith(prefix):
            patches.append(v)
    if not patches:
        return None
    patches.sort(key=lambda s: tuple(int(x) for x in s.split(".")), reverse=True)
    return patches[0]


def _install_windows(version: Tuple[int, int], on_log=None) -> Optional[str]:
    def log(msg):
        if on_log:
            on_log(msg)
    patch = _latest_patch(version, on_log=on_log)
    if not patch:
        log(f"Could not determine latest patch for Python {version[0]}.{version[1]}")
        return None
    url = f"https://www.python.org/ftp/python/{patch}/python-{patch}-amd64.exe"
    installer = os.path.join(os.environ.get("TEMP", os.getcwd()), f"python-{patch}-amd64.exe")
    log(f"Downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, installer)
    except Exception as e:  # noqa: BLE001
        log(f"Download failed: {e}")
        return None
    log("Installing Python (per-user, added to PATH) ...")
    args = [installer, "/quiet",
            "InstallAllUsers=0", "PrependPath=1", "Include_test=0",
            "Include_pip=1", "Include_tcltk=1", "Include_launcher=1"]
    rc, _, err = _run(args, timeout=600)
    if rc != 0:
        log(f"Installer failed (rc={rc}): {err}")
        return None
    base = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python")
    if os.path.isdir(base):
        for name in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, name, "python.exe")
            if os.path.isfile(cand):
                log(f"Installed Python {patch} -> {cand}")
                return cand
    log("Install finished but interpreter not found in expected location.")
    return None


def _install_macos(version: Tuple[int, int], on_log=None) -> Optional[str]:
    def log(msg):
        if on_log:
            on_log(msg)
    patch = _latest_patch(version, on_log=on_log)
    if not patch:
        return None
    url = f"https://www.python.org/ftp/python/{patch}/python-{patch}-macos11.pkg"
    pkg = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"python-{patch}-macos11.pkg")
    log(f"Downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, pkg)
    except Exception as e:  # noqa: BLE001
        log(f"Download failed: {e}")
        return None
    log("Installing Python .pkg (may prompt for password) ...")
    rc, _, err = _run(["sudo", "installer", "-pkg", pkg, "-target", "/"], timeout=600)
    if rc != 0:
        log(f"Installer failed (rc={rc}): {err}")
        return None
    exe = f"/Library/Frameworks/Python.framework/Versions/{version[0]}.{version[1]}/bin/python3"
    if os.path.isfile(exe):
        log(f"Installed Python {patch} -> {exe}")
        return exe
    return None


def _install_linux(version: Tuple[int, int], on_log=None) -> Optional[str]:
    def log(msg):
        if on_log:
            on_log(msg)
    ver_dot = f"{version[0]}.{version[1]}"
    exe = f"/usr/bin/python{ver_dot}"

    # Try deadsnakes PPA on Ubuntu. NOTE: python3-distutils no longer exists
    # since 3.12 (distutils was removed from the stdlib), so we only install
    # the interpreter and the venv package.
    rc, out, _ = _run(["cat", "/etc/os-release"])
    is_ubuntu = "ubuntu" in out.lower() or "debian" in out.lower()
    if is_ubuntu:
        log(f"Adding deadsnakes PPA and installing python{ver_dot} ...")
        pkgs = [f"python{ver_dot}", f"python{ver_dot}-venv"]
        cmds = [
            ["sudo", "add-apt-repository", "-y", "ppa:deadsnakes/ppa"],
            ["sudo", "apt-get", "update"],
            ["sudo", "apt-get", "install", "-y"] + pkgs,
        ]
        ok = True
        for c in cmds:
            rc, _, err = _run(c, timeout=600)
            if rc != 0:
                log(f"Command failed: {' '.join(c)}\n{err.strip()[:300]}")
                ok = False
                break
        if ok and os.path.isfile(exe):
            log(f"Installed Python {ver_dot} -> {exe}")
            return exe

    # Last resort: build from source (slow).
    patch = _latest_patch(version, on_log=on_log)
    if not patch:
        return None
    log(f"Building Python {patch} from source (this takes a while) ...")
    url = f"https://www.python.org/ftp/python/{patch}/Python-{patch}.tgz"
    tmp = os.environ.get("TMPDIR", "/tmp")
    tgz = os.path.join(tmp, f"Python-{patch}.tgz")
    src = os.path.join(tmp, f"Python-{patch}")
    try:
        urllib.request.urlretrieve(url, tgz)
    except Exception as e:  # noqa: BLE001
        log(f"Download failed: {e}")
        return None
    steps = [
        ["tar", "-xzf", tgz, "-C", tmp],
        ["sh", "-c", f"cd '{src}' && ./configure --enable-optimizations --prefix=/usr/local"],
        ["sh", "-c", f"cd '{src}' && make -j$(nproc)"],
        ["sh", "-c", f"cd '{src}' && sudo make altinstall"],
    ]
    for c in steps:
        rc, _, err = _run(c, timeout=1800)
        if rc != 0:
            log(f"Build step failed: {' '.join(c[:2])} ...\n{err[:500]}")
            return None
    built = f"/usr/local/bin/python{ver_dot}"
    if os.path.isfile(built):
        log(f"Built Python {patch} -> {built}")
        return built
    return None


def install_python(version: Tuple[int, int] = RECOMMENDED_INSTALL,
                   on_log=None) -> Optional[str]:
    """Download and install a Python version from the official source."""
    system = platform.system()
    if system == "Windows":
        return _install_windows(version, on_log=on_log)
    elif system == "Darwin":
        return _install_macos(version, on_log=on_log)
    elif system == "Linux":
        return _install_linux(version, on_log=on_log)
    return None


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def ensure_compatible_python(on_log=None, auto_install: bool = True) -> Optional[str]:
    """
    Return the path to a venv Python interpreter with all deps installed.

    Workflow:
      - discover all base interpreters
      - pick the best one (newest in the supported range)
      - create/reuse the project virtualenv and install requirements into it
      - (last resort) if no usable interpreter exists and auto_install,
        install one from python.org and build the venv from it
    """
    def log(msg):
        if on_log:
            on_log(msg)

    found = discover_pythons()
    log(f"Discovered {len(found)} Python interpreter(s):")
    for p in found:
        log(f"  - Python {version_str(p.version)} ({p.source})")

    best = select_best(found, allow_install=auto_install, on_log=on_log)
    if best:
        vpy = ensure_venv(best.path, on_log=on_log)
        if vpy:
            _warn_tkinter_if_missing(vpy, on_log=on_log)
            return vpy
        # venv creation failed with the best base -> try the others.
        others = [p for p in found if p.path != best.path and p.usable]
        others.sort(key=lambda p: p.version or (0, 0, 0), reverse=True)
        for alt in others:
            vpy = ensure_venv(alt.path, on_log=on_log)
            if vpy:
                _warn_tkinter_if_missing(vpy, on_log=on_log)
                return vpy

    if not auto_install:
        return None

    log(f"No usable interpreter found. Installing Python "
        f"{version_str(RECOMMENDED_INSTALL)} from the official source ...")
    new_exe = install_python(RECOMMENDED_INSTALL, on_log=on_log)
    if new_exe:
        vpy = ensure_venv(new_exe, on_log=on_log)
        if vpy:
            _warn_tkinter_if_missing(vpy, on_log=on_log)
            return vpy

    log("Could not set up a Python environment. Please install Python "
        f"{version_str(RECOMMENDED_INSTALL)}+ manually from "
        "https://www.python.org/downloads/ and re-run.")
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print(msg):
    print(msg)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "check" in argv
    bootstrap = "bootstrap" in argv or (not check_only)

    if check_only:
        found = discover_pythons()
        print(f"Discovered {len(found)} interpreter(s):")
        for p in found:
            print(f"  {version_str(p.version):10s} {p.path}  ({p.source})")
        best = select_best(found)
        if best:
            print(f"\nBest base interpreter: Python {version_str(best.version)} -> {best.path}")
        else:
            print("\nNo supported interpreter found.")
        vpy = _venv_python_path()
        if os.path.isfile(vpy):
            state = "READY" if venv_ready() else "exists (deps incomplete)"
            print(f"Project virtualenv: {VENV_DIR}  [{state}]")
        else:
            print(f"Project virtualenv: {VENV_DIR}  [not created]")
        return 0

    exe = ensure_compatible_python(on_log=_print, auto_install=bootstrap)
    if not exe:
        print("\n[python_manager] Could not obtain a compatible interpreter.")
        return 1
    print(f"\n[python_manager] Using virtualenv: {exe}")
    cache = os.path.join(ROOT_DIR, ".python-interpreter")
    try:
        with open(cache, "w") as f:
            f.write(exe)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
