"""Persistent application settings and build output directory validation."""
import json
import os
import shutil
import tempfile

from config import SETTINGS_FILE


MIN_BUILD_FREE_BYTES = 10 * 1024 ** 3
BUILD_OUTPUT_DIRECTORY_KEY = "build_output_directory"


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
