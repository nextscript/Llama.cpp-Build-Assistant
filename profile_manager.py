"""
Profile manager module.
Manages build profiles (pre-configured source + build type + flags combinations).
"""
import json
import os
from config import PROFILES_FILE, DEFAULT_BUILD_PROFILES


def load_profiles():
    """Load build profiles from JSON file."""
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass
    save_profiles(DEFAULT_BUILD_PROFILES)
    return DEFAULT_BUILD_PROFILES.copy()


def save_profiles(profiles):
    """Save build profiles to JSON file."""
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=2)


def add_profile(name, source, build_type, cmake_flags=None,
                clean_build=True, update_repo=True, test_after_build=False,
                experimental=False):
    """Add a new build profile."""
    profiles = load_profiles()

    new_profile = {
        "name": name,
        "source": source,
        "build_type": build_type,
        "cmake_flags": cmake_flags or [],
        "clean_build": clean_build,
        "update_repo": update_repo,
        "test_after_build": test_after_build,
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
                if key in prof:
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
        print(f"  {p['name']}: {p['source']} + {p['build_type']}")
