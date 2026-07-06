"""
Cross-platform Python interpreter manager.

This module uses ONLY the Python standard library so that it can run under
*any* available Python (e.g. a bleeding-edge 3.14) to detect and select a
compatible interpreter for the project's requirements.txt.

Responsibilities
----------------
1. Discover every Python interpreter installed on the system
   (Windows py-launcher + registry + PATH, macOS/Linux alternatives +
   pyenv + Homebrew + /usr/bin).
2. Test each interpreter against requirements.txt (version sanity + whether
   the required packages are importable or installable).
3. Select the best compatible interpreter (newest *stable* version that is
   known to work; avoid bleeding-edge unless verified).
4. If no compatible interpreter is present, download and install a known-good
   version from the official source:
       - Windows / macOS: python.org official installers
       - Linux:           deadsnakes PPA (Ubuntu) or build-from-source fallback
5. Expose the chosen interpreter + pip path for the launchers and the app.

CLI usage
---------
    python python_manager.py            # print chosen interpreter + install deps
    python python_manager.py check      # only report, do not install anything
    python python_manager.py bootstrap  # ensure deps in chosen interpreter
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

# Packages that the app actually imports at runtime. We probe these to decide
# whether an interpreter is "ready" without needing a full pip dry-run.
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
#  - PREFERRED_MAX: we prefer interpreters at or below this for stability
#    (bleeding-edge releases like 3.14 often lack wheels for customtkinter /
#     GPUtil). Interpreters above PREFERRED_MAX are only used as a last resort
#    AND only if their required packages actually import successfully.
MIN_SUPPORTED = (3, 9)
PREFERRED_MAX = (3, 13)

# Version installed automatically when nothing compatible is found.
# Keep this on a well-supported, widely-wheeled release.
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


def version_str(ver: Tuple[int, int, int]) -> str:
    return ".".join(str(x) for x in ver)


def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _get_python_version(exe: str) -> Optional[Tuple[int, int, int]]:
    """Return the version tuple of an interpreter, or None if it won't run."""
    rc, out, _ = _run([exe, "--version"])
    text = (out or "").strip()
    if rc != 0 or not text:
        # Some very old Pythons print --version to stderr
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
            # format: " -V:3.13[-64]     C:\path\python.exe"
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
    for name in ("python", "python3", "python3.13", "python3.12", "python3.11"):
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
        # direct python3.X binaries
        for mv in minor_versions:
            exe = os.path.join(d, f"python{mv}")
            if os.path.isfile(exe):
                cands.append((exe, f"dir:{d}"))
        # pyenv version subfolders (each contains bin/python)
        if "pyenv" in d:
            for name in entries:
                exe = os.path.join(d, name, "bin", "python")
                if os.path.isfile(exe):
                    cands.append((exe, f"pyenv:{name}"))

    # 2. generic names on PATH
    for name in ("python3", "python", "python3.13", "python3.12", "python3.11"):
        resolved = shutil.which(name)
        if resolved:
            cands.append((resolved, f"PATH:{name}"))

    _add_unique(found, cands)
    return found


def discover_pythons() -> List[PyInfo]:
    """Discover every usable Python interpreter on this machine."""
    system = platform.system()
    found = _discover_windows() if system == "Windows" else _discover_unix()

    # The currently running interpreter should always be considered.
    current = _norm(sys.executable)
    if current and not any(p.path == current for p in found):
        ver = _get_python_version(current)
        if ver:
            found.append(PyInfo(current, ver, "current-process"))

    # Sort newest first for predictable selection.
    found.sort(key=lambda p: p.version or (0, 0, 0), reverse=True)
    return found


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _version_rank(p: PyInfo) -> Tuple[int, int, int, int]:
    """Ranking key: prefer (ready, in_preferred_range, newer). Higher = better."""
    ready = 1 if p.ready else 0
    in_range = 1 if (p.version and MIN_SUPPORTED <= p.version[:2] <= PREFERRED_MAX) else 0
    major, minor, patch = p.version or (0, 0, 0)
    # Within the preferred range we still prefer newer; outside we deprioritise.
    return (ready, in_range, major, minor)


def select_best(discover: Optional[List[PyInfo]] = None,
                allow_install: bool = True,
                on_log=None) -> Optional[PyInfo]:
    """
    Select the best compatible interpreter.

    Selection order:
      1. Any interpreter whose required packages ALL import (ready),
         preferring ones inside the stable version range, then newer.
      2. Any interpreter inside the stable version range whose version is
         supported (packages may still need installing).
      3. Any supported interpreter at all (last resort, incl. bleeding edge).

    Returns None if no supported interpreter exists (caller may then install).
    """
    found = discover if discover is not None else discover_pythons()

    def log(msg):
        if on_log:
            on_log(msg)

    supported = [p for p in found if p.version and p.version[:2] >= MIN_SUPPORTED]
    if not supported:
        return None

    # First: ready interpreters, ranked.
    ready = [p for p in supported if p.ready]
    if ready:
        ready.sort(key=_version_rank, reverse=True)
        best = ready[0]
        log(f"Selected ready interpreter {best.version} ({best.path})")
        return best

    # Second: stable-range interpreters needing a dependency install.
    stable = [p for p in supported if MIN_SUPPORTED <= p.version[:2] <= PREFERRED_MAX]
    if stable:
        stable.sort(key=_version_rank, reverse=True)
        best = stable[0]
        log(f"Selected interpreter {best.version} (deps need install) at {best.path}")
        return best

    # Third: any supported interpreter (bleeding edge included).
    found_sorted = sorted(supported, key=_version_rank, reverse=True)
    best = found_sorted[0]
    log(f"Fallback to {best.version} at {best.path} (outside preferred range)")
    return best


def get_pip(exe: str) -> str:
    """Return the pip command list for a given interpreter (ensures pip)."""
    # Try `-m pip` first (works everywhere, no separate pip needed in PATH).
    rc, _, _ = _run([exe, "-m", "pip", "--version"])
    if rc == 0:
        return exe  # caller uses [exe, "-m", "pip", ...]
    # Bootstrap pip via ensurepip.
    _run([exe, "-m", "ensurepip", "--upgrade"])
    return exe


def ensure_requirements(exe: str, on_log=None) -> bool:
    """Install/upgrade requirements.txt into the given interpreter."""
    def log(msg):
        if on_log:
            on_log(msg)

    if not os.path.isfile(REQUIREMENTS_FILE):
        log(f"requirements.txt not found at {REQUIREMENTS_FILE}")
        return False

    get_pip(exe)
    log(f"Installing requirements into {exe} ...")
    rc, out, err = _run(
        [exe, "-m", "pip", "install", "--upgrade", "-r", REQUIREMENTS_FILE],
        timeout=600,
    )
    if rc != 0:
        log(f"pip install failed (rc={rc})\n{err.strip()}")
        return False
    log("Requirements installed successfully.")
    return True


# ---------------------------------------------------------------------------
# Official installation (when nothing compatible exists)
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
    # pick the highest patch
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
    full = patch  # e.g. 3.13.1
    url = f"https://www.python.org/ftp/python/{full}/python-{full}-amd64.exe"
    installer = os.path.join(os.environ.get("TEMP", os.getcwd()), f"python-{full}-amd64.exe")
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
    # Locate the newly installed interpreter.
    base = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python")
    exe = None
    if os.path.isdir(base):
        for name in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, name, "python.exe")
            if os.path.isfile(cand):
                exe = cand
                break
    if exe and os.path.isfile(exe):
        log(f"Installed Python {full} -> {exe}")
        return exe
    log("Install finished but interpreter not found in expected location.")
    return None


def _install_macos(version: Tuple[int, int], on_log=None) -> Optional[str]:
    def log(msg):
        if on_log:
            on_log(msg)
    patch = _latest_patch(version, on_log=on_log)
    if not patch:
        return None
    full = patch
    url = f"https://www.python.org/ftp/python/{full}/python-{full}-macos11.pkg"
    pkg = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"python-{full}-macos11.pkg")
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
        log(f"Installed Python {full} -> {exe}")
        return exe
    return None


def _install_linux(version: Tuple[int, int], on_log=None) -> Optional[str]:
    def log(msg):
        if on_log:
            on_log(msg)
    ver_dot = f"{version[0]}.{version[1]}"
    exe = f"/usr/bin/python{ver_dot}"

    # Try deadsnakes PPA on Ubuntu/Debian first.
    rc, out, _ = _run(["cat", "/etc/os-release"])
    is_ubuntu = "ubuntu" in out.lower() or "debian" in out.lower()
    if is_ubuntu:
        log("Adding deadsnakes PPA and installing python{} ...".format(ver_dot))
        cmds = [
            ["sudo", "add-apt-repository", "-y", "ppa:deadsnakes/ppa"],
            ["sudo", "apt-get", "update"],
            ["sudo", "apt-get", "install", "-y",
             f"python{ver_dot}", f"python{ver_dot}-venv", f"python{ver_dot}-distutils"],
        ]
        ok = True
        for c in cmds:
            rc, _, err = _run(c, timeout=600)
            if rc != 0:
                log(f"Command failed: {' '.join(c)}\n{err}")
                ok = False
                break
        if ok and os.path.isfile(exe):
            log(f"Installed Python {ver_dot} -> {exe}")
            return exe

    # Fallback: build from source (slow but universal).
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
    Return the path to a compatible, ready-to-run Python interpreter.

    Workflow:
      - discover all interpreters
      - pick the best compatible one
      - if its deps aren't installed, install them
      - if nothing compatible exists and auto_install, install one from
        python.org and install its deps
    Returns the interpreter path (deps installed) or None on failure.
    """
    def log(msg):
        if on_log:
            on_log(msg)

    found = discover_pythons()
    log(f"Discovered {len(found)} Python interpreter(s):")
    for p in found:
        ready = "READY" if p.ready else f"imports {p.check_imports()}/{len(REQUIRED_IMPORTS)}"
        log(f"  - {p.version} ({p.source}) {ready}")

    best = select_best(found, allow_install=auto_install, on_log=on_log)
    if best:
        if not best.ready:
            if not ensure_requirements(best.path, on_log=on_log):
                # Deps failed to install -> this interpreter isn't usable.
                log(f"Could not install requirements into {best.path}")
                # Try to fall back to another discovered interpreter.
                others = [p for p in found if p.path != best.path and p.usable]
                for alt in sorted(others, key=_version_rank, reverse=True):
                    if ensure_requirements(alt.path, on_log=on_log):
                        return alt.path
                # last resort: install a fresh interpreter below
                best = None
            else:
                return best.path
        else:
            return best.path

    if not auto_install:
        return None

    log(f"No compatible interpreter found. Installing Python "
        f"{version_str(RECOMMENDED_INSTALL)} from the official source ...")
    new_exe = install_python(RECOMMENDED_INSTALL, on_log=on_log)
    if not new_exe:
        log("Automatic installation failed. Please install Python "
            f"{version_str(RECOMMENDED_INSTALL)}+ manually from "
            "https://www.python.org/downloads/")
        return None
    if ensure_requirements(new_exe, on_log=on_log):
        return new_exe
    log("Python installed but requirements could not be installed.")
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
            tag = "READY" if p.ready else f"imports {p.check_imports()}/{len(REQUIRED_IMPORTS)}"
            print(f"  {version_str(p.version):10s} {tag:30s} {p.path}")
        best = select_best(found)
        if best:
            print(f"\nBest compatible: {version_str(best.version)} -> {best.path}")
        else:
            print("\nNo supported interpreter found.")
        return 0

    exe = ensure_compatible_python(on_log=_print,
                                   auto_install=bootstrap and not check_only)
    if not exe:
        print("\n[python_manager] Could not obtain a compatible interpreter.")
        return 1
    print(f"\n[python_manager] Using: {exe}")
    # Write the chosen path to a file the launchers can read.
    cache = os.path.join(ROOT_DIR, ".python-interpreter")
    try:
        with open(cache, "w") as f:
            f.write(exe)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
