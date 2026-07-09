<img src="https://raw.githubusercontent.com/nextscript/Llama.cpp-Build-Assistant/refs/heads/main/preview.PNG">

# Llama.cpp Build Assistant

A Python GUI application that automatically checks system hardware, ensures a
compatible Python toolchain, installs missing dependencies, and builds the
appropriate `llama.cpp` variant for **your** hardware — across **Windows 10/11,
macOS, Ubuntu and other Linux distros**.

## Features

- **Automatic Hardware Detection** — CPU, RAM, GPU, VRAM, CUDA, Vulkan, ROCm/HIP, SYCL, free disk
- **Dependency Checker / Auto-Install** — `winget` (Windows), `apt`/`dnf`/`pacman`/`zypper` (Linux), Homebrew (macOS)
- **Multiple Sources** — official + experimental `llama.cpp` forks (see below)
- **Build Profiles** — pre-configured profiles for quick setup
- **Live Logs** — real-time build output
- **Build History** — all build results saved for reference

## Build Types

| Type | Backend | When to use |
|------|---------|-------------|
| CPU | `GGML_NATIVE` | No/disabled GPU |
| CUDA | `GGML_CUDA` | NVIDIA |
| Vulkan | `GGML_VULKAN` | Any Vulkan GPU — **recommended for AMD RDNA4** |
| HIP/ROCm | `GGML_HIP` | AMD RDNA2/3 (use Vulkan for RDNA4) |
| SYCL | `GGML_SYCL` | Intel GPU |

## Supported Build Sources (verified 2026-07-06)

| Source | Repository | Branch / PR |
|--------|-----------|-------------|
| main | `ggml-org/llama.cpp` | `master` |
| turboquant | `TheTom/llama-cpp-turboquant` | `feature/turboquant-kv-cache` |
| turboquant 3/4 | `AtomicBot-ai/atomic-llama-cpp-turboquant` | `feature/turboquant-kv-cache` |
| PrismML Ternary | `PrismML-Eng/llama.cpp` | `prism` |
| OCR | `ggml-org/llama.cpp` | PR **#17400** |
| Luce | `Luce-Org/lucebox-hub` | `main` (with submodules) |
| DFlash | `Anbild/beellama.cpp` | `main` |
| DSpark (Spark Attention) | `Anbild/beellama.cpp` | `main` |
| Custom | *user-defined* | — |

> **Note:** DFlash, TurboQuant/TCQ and Spark Attention all live in
> [`Anbeeld/beellama.cpp`](https://github.com/Anbild/beellama.cpp). PR-based
> sources are fetched via `git fetch origin pull/<n>/head`, not plain clone.

## Installation

### Quick start

**Windows** — double-click `start.bat` (requests admin, picks the right Python,
installs deps, launches the GUI).

**macOS / Linux** — run:
```bash
./start.sh
```

### Manual

```bash
python python_manager.py bootstrap   # picks/installs a compatible interpreter
python -m pip install -r requirements.txt
python app.py
```

## Project Structure

```
├── app.py                   # Main GUI (CustomTkinter)
├── python_manager.py        # Cross-platform interpreter selection + install
├── hardware_check.py        # CPU/RAM/GPU/CUDA/Vulkan/ROCm/SYCL + RDNA4 detection
├── dependency_checker.py    # Dependency detection
├── dependency_installer.py  # Auto-install (winget/apt/dnf/pacman/zypper/brew)
├── builder.py               # Build orchestration (dispatches by platform)
├── repo_manager.py          # Git clone/update (PRs + submodules)
├── source_manager.py        # Build source management
├── profile_manager.py       # Build profile management
├── config.py                # Global config + default sources
├── logger.py                # Logging
├── build_llamacpp.ps1       # Windows build pipeline
├── build_llamacpp.sh        # macOS/Linux build pipeline
├── start.bat / start.sh     # Launchers (use python_manager)
├── tests/                   # pytest suite
├── data/                    # Config + history JSON
└── pyproject.toml
```

## Requirements

- A C/C++ toolchain (VS Build Tools on Windows, GCC/Clang on Linux, Xcode/Clang on macOS)
- Git, CMake, Ninja
- A GPU backend toolkit when not building CPU-only (CUDA / Vulkan SDK / ROCm / Intel oneAPI)

## Testing

```bash
python -m pip install -e ".[dev]"
pytest
```
