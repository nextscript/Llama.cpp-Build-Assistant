"""
Global configuration for the Llama.cpp Build Assistant.
All paths, URLs, and default settings are defined here.
"""
import os
import json

# Root directory of the project
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Subdirectories
REPOS_DIR = os.path.join(ROOT_DIR, "repos")
BUILDS_DIR = os.path.join(ROOT_DIR, "builds")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
DATA_DIR = os.path.join(ROOT_DIR, "data")

# Ensure directories exist
for d in [REPOS_DIR, BUILDS_DIR, LOGS_DIR, DATA_DIR]:
    os.makedirs(d, exist_ok=True)

# Data files
BUILD_SOURCES_FILE = os.path.join(DATA_DIR, "build_sources.json")
BUILD_HISTORY_FILE = os.path.join(DATA_DIR, "build_history.json")
SYSTEM_REPORT_FILE = os.path.join(DATA_DIR, "system_report.json")
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")

# Log files
BUILD_LOG_FILE = os.path.join(LOGS_DIR, "build.log")
INSTALL_LOG_FILE = os.path.join(LOGS_DIR, "install.log")
ERROR_LOG_FILE = os.path.join(LOGS_DIR, "error.log")

# Default build sources
DEFAULT_BUILD_SOURCES = [
    {
        "id": "main",
        "name": "main llama.cpp",
        "repo_url": "https://github.com/ggml-org/llama.cpp",
        "branch": "master",
        "local_path": os.path.join(REPOS_DIR, "llama.cpp-main"),
        "type": "official",
        "experimental": False,
        "default_cmake_flags": []
    },
    {
        "id": "turboquant",
        "name": "turboquant llama.cpp",
        "repo_url": "https://github.com/TheTom/llama-cpp-turboquant",
        "branch": "feature/turboquant-kv-cache",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-turboquant"),
        "type": "fork",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "turboquant_3_4",
        "name": "turboquant 3/4 llama.cpp",
        "repo_url": "https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant",
        "branch": "feature/turboquant-kv-cache",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-turboquant-3-4"),
        "type": "custom",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "prismml_ternary",
        "name": "PrismML Ternary llama.cpp",
        "repo_url": "https://github.com/PrismML-Eng/llama.cpp",
        "branch": "prism",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-prismml-ternary"),
        "type": "fork",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "diffusion_gemma",
        "name": "Diffusion Gemma llama.cpp",
        "repo_url": "https://github.com/ggml-org/llama.cpp",
        "branch": "master",
        "pr": 24427,
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-diffusion-gemma"),
        "type": "pr",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "gemma_external_drafter",
        "name": "Gemma External Drafter / Assistant llama.cpp",
        "repo_url": "https://github.com/ggml-org/llama.cpp",
        "branch": "master",
        "pr": 23211,
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-gemma-drafter"),
        "type": "pr",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "ocr_llama",
        "name": "OCR llama.cpp",
        "repo_url": "https://github.com/ggml-org/llama.cpp",
        "branch": "master",
        "pr": 17400,
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-ocr"),
        "type": "pr",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "luce",
        "name": "Luce llama.cpp",
        "repo_url": "https://github.com/Luce-Org/lucebox-hub",
        "branch": "main",
        "submodules": True,
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-luce"),
        "type": "fork",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "dflash",
        "name": "DFlash llama.cpp",
        "repo_url": "https://github.com/Anbeeld/beellama.cpp",
        "branch": "main",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-dflash"),
        "type": "fork",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "dspark",
        "name": "DSpark (Spark Attention) llama.cpp",
        "repo_url": "https://github.com/Anbild/beellama.cpp",
        "branch": "main",
        "note": "Spark Attention is a feature inside beellama.cpp (same repo as DFlash); build with Vulkan/CUDA.",
        "local_path": os.path.join(REPOS_DIR, "llama-cpp-dspark"),
        "type": "fork",
        "experimental": True,
        "default_cmake_flags": []
    },
    {
        "id": "custom",
        "name": "eigenes llama.cpp Repository",
        "repo_url": "",
        "branch": "master",
        "local_path": os.path.join(REPOS_DIR, "custom-llama-cpp"),
        "type": "custom",
        "experimental": True,
        "default_cmake_flags": []
    }
]

# Default build profiles
DEFAULT_BUILD_PROFILES = [
    {
        "name": "CPU schnell",
        "source": "main",
        "build_type": "CPU",
        "cmake_flags": ["-DGGML_NATIVE=ON"],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    },
    {
        "name": "CUDA NVIDIA empfohlen",
        "source": "main",
        "build_type": "CUDA",
        "cmake_flags": ["-DGGML_CUDA=ON"],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": True
    },
    {
        "name": "Vulkan kompatibel",
        "source": "main",
        "build_type": "Vulkan",
        "cmake_flags": ["-DGGML_VULKAN=ON"],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    },
    {
        "name": "ROCm AMD",
        "source": "main",
        "build_type": "HIP",
        "cmake_flags": ["-DGGML_HIP=ON"],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    },
    {
        "name": "SYCL Intel GPU",
        "source": "main",
        "build_type": "SYCL",
        "cmake_flags": ["-DGGML_SYCL=ON"],
        "clean_build": True,
        "update_repo": True,
        "test_after_build": False
    }
]

# Required programs for building
REQUIRED_FOR_ALL = ["git", "cmake", "compiler"]
REQUIRED_FOR_CUDA = ["cuda_toolkit"]
REQUIRED_FOR_VULKAN = ["vulkan_sdk"]
REQUIRED_FOR_HIP = ["rocmmhip"]
REQUIRED_FOR_SYCL = ["intel_oneapi"]

# Build type to CMake flag mapping
BUILD_TYPE_FLAGS = {
    "CPU": "-DGGML_NATIVE=ON",
    "CUDA": "-DGGML_CUDA=ON",
    "Vulkan": "-DGGML_VULKAN=ON",
    "HIP": "-DGGML_HIP=ON",
    "SYCL": "-DGGML_SYCL=ON"
}

# Build type display names
BUILD_TYPE_DISPLAY = {
    "CPU": "CPU",
    "CUDA": "CUDA",
    "Vulkan": "Vulkan",
    "HIP": "HIP/ROCm",
    "SYCL": "SYCL (Intel)"
}

# Build types list
BUILD_TYPES = ["CPU", "CUDA", "Vulkan", "HIP", "SYCL"]
