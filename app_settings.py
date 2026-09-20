"""Persistent application settings and build output directory validation."""
import json
import ntpath
import os
import platform
import shutil
import tempfile

from config import SETTINGS_FILE


MIN_BUILD_FREE_BYTES = 10 * 1024 ** 3
BUILD_OUTPUT_DIRECTORY_KEY = "build_output_directory"
WINDOW_POSITION_KEY = "window_position"
CPU_TARGET_KEY = "cpu_target"
BUILD_JOBS_KEY = "build_jobs"

# MSBuild/FileTracker is not reliably long-path aware. Reserve 10 characters
# below MAX_PATH, including room for the terminator. Keep in sync with PS1.
VULKAN_PATH_BUDGET = 250
VULKAN_NESTED_PATH = (
    r"ggml\src\ggml-vulkan\vulkan-shaders-gen-prefix\src\vulkan-shaders-gen-build"
    r"\CMakeFiles\CMakeScratch\TryCompile-XXXXXX\cmTC_XXXXX.dir\Debug"
    r"\cmTC_XXXXX.tlog\link-cvtres.write.1.tlog"
)


def validate_windows_vulkan_path(root, build_type, dir_suffix="llama.cpp",
                                 *, system=None, checkout_name=None, build_dir=None):
    """Pure path-budget check; no directories are created or moved.

    Unknown versions reserve ten digits and the full collision timestamp.
    The script checks the actual path again, covering longer future versions.
    This representative upstream layout is a conservative estimate, not a
    guarantee for every future CMake version.
    """
    if (system or platform.system()) != "Windows" or build_type != "Vulkan":
        return
    root = ntpath.normpath(root)
    checkout_name = checkout_name or f"b0000000000_run_000000000000000000000_vulkan_{dir_suffix}"
    build_dir = build_dir or ntpath.join(root, checkout_name, "build")
    projected = ntpath.join(ntpath.normpath(build_dir), VULKAN_NESTED_PATH)
    length = len(projected.encode("utf-16-le")) // 2
    if length > VULKAN_PATH_BUDGET:
        raise ValueError(
            f"Windows/Vulkan path budget exceeded: {length}/{VULKAN_PATH_BUDGET} characters.\n"
            f"Output root: {root}\nBuild directory: {build_dir}\n\n"
            "Nested MSBuild/FileTracker paths can fail with FTK1011/MSB8066. "
            "Select a shorter output root, for example C:\\b, and configure a fresh build. "
            "Do not copy an old CMake cache. Existing outputs have not been moved or deleted.")


def normalize_build_choices(settings):
    target = settings.get(CPU_TARGET_KEY)
    if target not in ("portable", "native"):
        target = "portable"
    jobs = settings.get(BUILD_JOBS_KEY)
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs <= 0:
        jobs = os.cpu_count() or 4
    return target, jobs


def normalize_window_position(value):
    """Return a saved window position as an ``(x, y)`` tuple, if valid."""
    if not isinstance(value, dict):
        return None
    x = value.get("x")
    y = value.get("y")
    if (not isinstance(x, int) or isinstance(x, bool)
            or not isinstance(y, int) or isinstance(y, bool)):
        return None
    return x, y


def load_settings(path=None):
    """Load application settings, falling back to an empty mapping."""
    path = path or SETTINGS_FILE
    try:
        with open(path, "r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_setting(key, value, path=None):
    """Persist one setting without discarding settings added in the future."""
    path = path or SETTINGS_FILE
    settings = load_settings(path)
    settings[key] = value
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, indent=2)
            settings_file.write("\n")
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(temporary_path)
        except OSError:
            pass
        raise


def validate_build_output_directory(path, min_free_bytes=MIN_BUILD_FREE_BYTES):
    """Create and validate a writable build directory with sufficient space.

    Returns the normalized absolute path and the number of free bytes. Raises
    ValueError with a user-facing explanation when validation fails.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Please select a build output directory.")

    normalized = os.path.abspath(os.path.expanduser(path.strip()))
    try:
        os.makedirs(normalized, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            f"The build output directory could not be created:\n{normalized}\n\n{exc}"
        ) from exc

    if not os.path.isdir(normalized):
        raise ValueError(f"The selected build output path is not a directory:\n{normalized}")

    probe_path = None
    try:
        probe_fd, probe_path = tempfile.mkstemp(prefix=".write-test-", dir=normalized)
        os.close(probe_fd)
    except OSError as exc:
        raise ValueError(
            f"The selected build output directory is not writable:\n{normalized}\n\n{exc}"
        ) from exc
    finally:
        if probe_path:
            try:
                os.remove(probe_path)
            except OSError:
                pass

    try:
        free_bytes = shutil.disk_usage(normalized).free
    except OSError as exc:
        raise ValueError(
            f"Free disk space could not be determined for:\n{normalized}\n\n{exc}"
        ) from exc

    if free_bytes < min_free_bytes:
        free_gib = free_bytes / 1024 ** 3
        required_gib = min_free_bytes / 1024 ** 3
        raise ValueError(
            f"Not enough free disk space in the selected build output directory.\n\n"
            f"Available: {free_gib:.1f} GiB\nRequired: {required_gib:.1f} GiB"
        )

    return normalized, free_bytes
