"""
Profile manager module.
Manages build profiles (build type + CMake flags combinations).
"""
import json
import os
from config import PROFILES_FILE, DEFAULT_BUILD_PROFILES

# Marker written once the v2.3.0 profile migration ran for this data dir.
_MIGRATION_MARKER = os.path.join(os.path.dirname(PROFILES_FILE), ".profiles-migrated-2.3.0")

# Exact default profiles shipped with v2.2.x. A stored profile that still
# equals one of these (name + flags untouched by the user) is replaced by
# its v2.3.0 successor: the old defaults pinned gfx1201, AVX2-only ISA flags
# and a forced npm web-UI build.
_LEGACY_ISA = [
    "-DGGML_NATIVE=OFF", "-DGGML_AVX2=ON", "-DGGML_AVX_VNNI=ON", "-DGGML_BMI2=ON",
    "-DGGML_AVX512=OFF", "-DGGML_AVX512_VBMI=OFF", "-DGGML_AVX512_VNNI=OFF",
    "-DGGML_AVX512_BF16=OFF", "-DGGML_LTO=OFF", "-DBUILD_SHARED_LIBS=OFF",
    "-DLLAMA_BUILD_SERVER=ON", "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_TOOLS=ON",
    "-DLLAMA_BUILD_EXAMPLES=ON",
]
_LEGACY_DEFAULTS = {
    "CPU": (
        "CPU",
        _LEGACY_ISA + ["-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"],
    ),
    "CUDA NVIDIA": (
        "CUDA 12.x NVIDIA",
        ["-DLLAMA_BUILD_IS_DEV=ON", "-DGGML_CUDA=ON", "-DGGML_VULKAN=OFF", "-DGGML_NATIVE=OFF",
         "-DGGML_AVX2=ON", "-DGGML_FMA=ON", "-DGGML_F16C=ON", "-DBUILD_SHARED_LIBS=OFF",
         "-DLLAMA_BUILD_SERVER=ON", "-DLLAMA_BUILD_UI=ON", "-DLLAMA_USE_PREBUILT_UI=ON",
         "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"],
    ),
    "Vulkan": (
        "Vulkan",
        ["-DGGML_VULKAN=ON", "-DGGML_HIP=OFF"] + _LEGACY_ISA + [
            "-DLLAMA_BUILD_UI=ON", "-DLLAMA_USE_PREBUILT_UI=ON", "-DLLAMA_CURL=OFF",
            "-DGGML_CCACHE=OFF", "-DGGML_VULKAN_CHECK_RESULTS=OFF", "-DGGML_VULKAN_DEBUG=OFF",
            "-DGGML_VULKAN_MEMORY_DEBUG=OFF", "-DGGML_VULKAN_SHADER_DEBUG_INFO=OFF",
            "-DGGML_VULKAN_VALIDATE=OFF", "-DGGML_VULKAN_RUN_TESTS=OFF"],
    ),
    "HIP ROCm AMD": (
        "HIP ROCm AMD",
        ["-DGGML_HIP=ON", "-DGGML_VULKAN=OFF", "-DGPU_TARGETS=gfx1201", "-DGGML_HIP_GRAPHS=ON",
         "-DGGML_HIP_NO_VMM=ON", "-DGGML_HIP_RCCL=OFF", "-DGGML_CUDA_NO_PEER_COPY=ON",
         "-DGGML_CUDA_FA=ON", "-DGGML_CUDA_FA_ALL_QUANTS=ON", "-DGGML_FMA=ON", "-DGGML_F16C=ON"]
        + _LEGACY_ISA + ["-DLLAMA_BUILD_UI=ON", "-DLLAMA_USE_PREBUILT_UI=ON",
                         "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"],
    ),
    "SYCL Intel GPU": (
        "SYCL Intel GPU",
        ["-DGGML_SYCL=ON", "-DGGML_SYCL_F16=ON", "-DGGML_NATIVE=ON", "-DBUILD_SHARED_LIBS=ON",
         "-DLLAMA_BUILD_SERVER=ON", "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"],
    ),
    "Metal macOS": (
        "Metal (Apple Silicon)",
        ["-DGGML_METAL=ON", "-DGGML_METAL_EMBED_LIBRARY=ON", "-DGGML_CUDA=OFF", "-DGGML_VULKAN=OFF",
         "-DBUILD_SHARED_LIBS=ON", "-DLLAMA_BUILD_SERVER=ON", "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"],
    ),
}


def _default_by_name(name):
    for prof in DEFAULT_BUILD_PROFILES:
        if prof.get("name") == name:
            return json.loads(json.dumps(prof))
    return None


def _migrate_profiles(profiles):
    """Upgrade untouched v2.2.x default profiles and add new defaults once.

    Returns (profiles, changed). User-modified profiles are never altered.
    """
    changed = False
    # Refresh untouched CUDA defaults even when the earlier migration ran.
    profiles = list(profiles)
    for index, profile in enumerate(profiles):
        default = _default_by_name(profile.get("name"))
        if not default or default.get("build_type") != "CUDA":
            continue
        old_flags = [flag.replace("-DLLAMA_BUILD_TESTS=ON", "-DLLAMA_BUILD_TESTS=OFF")
                     for flag in default["cmake_flags"]]
        if profile.get("build_type") == "CUDA" and profile.get("cmake_flags") == old_flags:
            profiles[index] = dict(profile, cmake_flags=list(default["cmake_flags"]))
            changed = True
    if os.path.exists(_MIGRATION_MARKER):
        return profiles, changed

    result = []
    for prof in profiles:
        name = prof.get("name")
        legacy = _LEGACY_DEFAULTS.get(name)
        if legacy and list(prof.get("cmake_flags", [])) == legacy[1]:
            replacement = _default_by_name(legacy[0])
            if replacement:
                # Keep the user's clean/update preferences.
                for key in ("clean_build", "update_repo"):
                    if key in prof:
                        replacement[key] = prof[key]
                result.append(replacement)
                changed = True
                continue
        result.append(prof)

    existing = {p.get("name") for p in result}
    for prof in DEFAULT_BUILD_PROFILES:
        if prof.get("name") not in existing:
            result.append(json.loads(json.dumps(prof)))
            changed = True

    try:
        with open(_MIGRATION_MARKER, "w", encoding="utf-8") as f:
            f.write("2.3.0\n")
    except Exception:
        pass
    return result, changed


def load_profiles():
    """Load build profiles from JSON file."""
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    normalized = []
                    changed = False
                    for profile in data:
                        if isinstance(profile, dict):
                            clean_profile = dict(profile)
                            if "source" in clean_profile:
                                clean_profile.pop("source", None)
                                changed = True
                            normalized.append(clean_profile)
                    normalized, migrated = _migrate_profiles(normalized)
                    if changed or migrated:
                        save_profiles(normalized)
                    return normalized
        except Exception:
            pass
    save_profiles([])
    return []


def save_profiles(profiles):
    """Save build profiles to JSON file."""
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=2)


def add_profile(name, source="", build_type="CPU", cmake_flags=None,
                clean_build=True, update_repo=True, test_after_build=False,
                experimental=False):
    """Add a new build profile."""
    profiles = load_profiles()
    if any(p.get("name") == name for p in profiles):
        return False, "Profile with this name already exists"

    new_profile = {
        "name": name,
        "build_type": build_type,
        "cmake_flags": cmake_flags or [],
        "clean_build": clean_build,
        "update_repo": update_repo,
        "experimental": experimental
    }

    profiles.append(new_profile)
    save_profiles(profiles)
    return True, "Profile added"


def edit_profile(profile_name, **kwargs):
    """Edit an existing build profile by name."""
    profiles = load_profiles()
    for i, prof in enumerate(profiles):
        if prof.get("name") == profile_name:
            for key, value in kwargs.items():
                if key in prof or key in ("build_type", "cmake_flags", "clean_build", "update_repo"):
                    prof[key] = value
            save_profiles(profiles)
            return True, "Profile updated"
    return False, "Profile not found"


def delete_profile(profile_name):
    """Delete a build profile by name."""
    profiles = load_profiles()
    new_profiles = [p for p in profiles if p.get("name") != profile_name]
    if len(new_profiles) == len(profiles):
        return False, "Profile not found"
    save_profiles(new_profiles)
    return True, "Profile deleted"


def get_profile_by_name(name):
    """Get a profile dict by name."""
    profiles = load_profiles()
    for prof in profiles:
        if prof.get("name") == name:
            return prof.copy()
    return None


def get_profile_names():
    """Return list of all profile names."""
    profiles = load_profiles()
    return [p.get("name") for p in profiles if p.get("name")]


if __name__ == "__main__":
    profiles = load_profiles()
    for p in profiles:
        print(f"  {p['name']}: {p['build_type']}")
