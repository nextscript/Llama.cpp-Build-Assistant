<p align="center"><img src="https://raw.githubusercontent.com/nextscript/Llama.cpp-Build-Assistant/refs/heads/main/logo_big.png"></p>

# Llama.cpp Build Assistant

A Python desktop application built with **PySide6 / Qt 6 + Fluent Widgets** that
automatically checks system hardware, ensures a
compatible Python toolchain, installs missing dependencies, and builds the
appropriate `llama.cpp` variant for **your** hardware — across **Windows 10/11,
macOS, Ubuntu and other Linux distros**.

## What's new in v2.3.9

The GUI now runs on **PySide6 / Qt 6 + Fluent Widgets**, retaining the dark
palette, 150-pixel sidebar, navigation order, cards and 1600 × 1024 initial
window size. The existing Python backend and build scripts are reused.

Builds, hardware and dependency checks, Git queries and updates run in Qt
worker threads. Pages remain loaded when switching views, and native Qt
layouts replace the previous Tk resize-freeze logic. Window position, size,
maximized state and the build/log splitter are saved alongside existing settings.

See the [v2.3.9 changelog](#239) and [migration and validation report](docs/qt-migration.md)
for details. The original `legacy_app.py` is retained for comparison until
interactive acceptance is complete; it is not loaded by the Qt application
or included in release executables.

## Features

- **Automatic Hardware Detection** — CPU, RAM, GPU, VRAM, CUDA, Vulkan, ROCm/HIP, SYCL, free disk
- **Dependency Checker / Auto-Install** — `winget` (Windows), `apt`/`dnf`/`pacman`/`zypper` (Linux), Homebrew (macOS)
- **Multiple Sources** — official + experimental `llama.cpp` forks, with automatic remote branch discovery for custom repositories
- **Build Profiles** — pre-configured profiles for quick setup
- **Custom Build Output** — choose and persist a build directory, with write-access and free-space checks
- **Build Version Status** — compare local and remote Git revisions and inspect new commits
- **Live Logs** — batched, read-only build output with a 5,000-line display limit
- **Build History** — saved results in a native Qt table; double-click for full details
- **Searchable Selectors** — filter sources, profiles and remote branches with keyboard support
- **Persistent Window State** — restore position, size, maximized state and build/log split

<h2>Screenshots</h2>

These screenshots show the original interface used as the visual reference for
the Qt migration; they are not new v2.3.9 captures.

<table>
  <tr>
    <td width="50%">
      <img src="Screens/screenshot1.PNG" width="100%">
    </td>
    <td width="50%">
      <img src="Screens/screenshot2.PNG" width="100%">
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="Screens/screenshot3.PNG" width="100%">
    </td>
    <td width="50%">
      <img src="Screens/screenshot4.PNG" width="100%">
    </td>
  </tr>
</table>

## Build Types

| Type | Backend | When to use |
|------|---------|-------------|
| CPU | `GGML_CPU` | No/disabled GPU, Intel Macs |
| CUDA 12.x | `GGML_CUDA` | NVIDIA, any GPU since Maxwell; driver 525+ |
| CUDA 13.x | `GGML_CUDA` | NVIDIA Turing or newer (compute capability 7.5+); driver 580+ |
| Vulkan | `GGML_VULKAN` | Any Vulkan GPU — **recommended for AMD RDNA4 (RX 9000 / AI PRO R9000)** |
| HIP/ROCm | `GGML_HIP` | AMD RDNA2/3 (use Vulkan for RDNA4); gfx target auto-detected |
| SYCL | `GGML_SYCL` | Intel GPU |
| Metal | `GGML_METAL` | Apple Silicon only (Intel Macs get CPU or Vulkan/MoltenVK) |

The hardware check picks the build type **and** the matching profile (for
example the CUDA generation your driver supports, or the Intel-Mac CPU
profile) and explains why on the dashboard.

**CPU target** (build tab): `portable` builds for AVX2/FMA/F16C so the binary
runs on any x86-64 CPU since Haswell/Zen 1; `native` lets llama.cpp enable
AVX-512/AMX for the machine that builds it. Profiles no longer pin the ISA.

**Output folders** follow the Auto-Tuner convention
`builds/<bNNNN>_<backend>_<suffix>/build/bin/…`, e.g.
`b10830_vulkan_llama.cpp`. `bNNNN` is `git rev-list --count HEAD`, the same
number `llama-server --version` prints. After the build the source tree is
retained together with Git metadata, web-UI assets, CMake projects, libraries,
and binaries. HIP builds bundle the ROCm runtime DLLs and link the
`rocblas/`/`hipblaslt/` kernel folders; CUDA builds bundle
`cudart`/`cublas`. Every build ends with `llama-server --version` and
`--list-devices` so a wrong backend is visible in the log.

## Supported Build Sources

| Source | Repository | Branch / PR | Folder suffix |
|--------|-----------|-------------|---------------|
| main | `ggml-org/llama.cpp` | `master` | `llama.cpp` |
| turboquant | `TheTom/llama-cpp-turboquant` | `master` (pinned commit) | `tq_llama.cpp` |
| PrismML Ternary/Bonsai | `PrismML-Eng/llama.cpp` | `prism` (pinned commit) | `2b_llama.cpp` |
| DeepSeek-OCR | `ggml-org/llama.cpp` | PR **#17400** (pinned commit) | `ocr_llama.cpp` |
| Diffusion-Gemma | `ggml-org/llama.cpp` | PR **#24427** (pinned commit) | `d_llama.cpp` |
| Custom | *user-defined* | — | `<id>_llama.cpp` (override with `dir_suffix`) |

> PR-based sources are fetched via `git fetch origin pull/<n>/head`, not plain
> clone. Pinned commits are stored in `data/sources.json`.

## Installation

### Quick start

**Windows** — double-click `start.bat` (picks the right Python, installs
deps, launches the GUI; no admin rights needed).

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

```text
├── app.py                   # QApplication entry point
├── ui/
│   ├── main_window.py       # Native Qt window and persistent page navigation
│   ├── theme.py             # Shared palette and Qt/Fluent widget styling
│   ├── widgets.py           # Cards, searchable selectors, tables and bounded logs
│   ├── pages/               # Build configuration, sources, profiles and history
│   ├── dialogs/             # Source/profile editors, installer and updater dialogs
│   ├── workers/             # Qt tasks, existing build-backend adapter and updater
│   ├── reports.py           # Existing report and manual-guide formatting
│   └── settings.py          # Serialized settings writes
├── python_manager.py        # Interpreter selection and dependency installation
├── hardware_check.py        # CPU/RAM/GPU and build recommendations
├── dependency_checker.py    # Dependency detection
├── dependency_installer.py  # Platform-specific dependency installation
├── builder.py               # Existing build orchestration
├── repo_manager.py          # Git clone/update, PRs and submodules
├── source_manager.py        # Source definitions and remote branches
├── source_version.py        # Local/remote build version checks
├── profile_manager.py       # Build profiles and CMake flags
├── app_settings.py          # Existing settings and output-path validation
├── config.py / logger.py    # Configuration and logging
├── build_llamacpp.ps1       # Windows build pipeline
├── build_llamacpp.sh        # macOS/Linux build pipeline
├── start.bat / start.sh     # Launchers using python_manager
├── data/                    # Source/profile definitions and runtime settings
├── scripts/check_*qt*.py    # DPI, responsiveness and frozen-EXE probes
├── tests/                   # Backend and Qt regression tests
├── docs/qt-migration.md     # Migration scope and acceptance checklist
├── legacy_app.py            # Original GUI retained for comparison only
└── pyproject.toml
```

## Requirements

- Python **3.10+** for source launches
- **PySide6 >= 6.8, < 7** and **PySide6-Fluent-Widgets >= 1.8, < 2** (installed by the launchers or `requirements.txt`)
- A C/C++ toolchain (VS Build Tools on Windows, GCC/Clang on Linux, Xcode/Clang on macOS)
- Git, CMake, Ninja
- A GPU backend toolkit when not building CPU-only (CUDA / Vulkan SDK / ROCm / Intel oneAPI)

## Testing

```bash
python -m pip install -e ".[dev]"
pytest
```

The suite covers backend behavior, hardware recommendations, Qt worker signal
delivery, build success/failure handling, source/profile CRUD, stale branch
responses, settings persistence, bounded logs and staged updater downloads.
The v2.3.9 validation run passed **110 tests**; Qt tests use the offscreen platform.

Additional native Windows checks:

```powershell
python scripts/check_qt_dpi.py
python scripts/check_qt_responsiveness.py
python scripts/check_frozen_qt.py dist/Llama.cpp-Build-Assistant-Windows.exe
```

DPI rendering was checked at 100%, 125%, 150%, 175% and 200%. The Windows
executable passed its startup/rendering smoke test with `qwindows.dll` present
and no Tk imports. Interactive drag/snap/multi-monitor checks, real compiler
builds, dependency installation and a live update/restart remain separate
[acceptance checks](docs/qt-migration.md#remaining-release-acceptance).

## Windows native CPU flags and Vulkan output paths

Native CPU builds started through the GUI/Python dispatcher explicitly request
detected AVX-VNNI and BMI2 on the Windows MSVC CPU/CUDA/Vulkan paths. Missing or
unknown features are set OFF to clear stale cache values. Profile flags come
last and can override these defaults, including typed `:BOOL` options. Portable,
HIP/SYCL and non-Windows compiler settings are unchanged. CPU target and build
jobs are saved when starting a build. Detection is not proof of the effective
compiler definitions; check the generated CPU project when validating a build.

Direct PowerShell callers can request these options explicitly on a supporting
host:

```powershell
-CpuTarget native -ExtraFlags "-DGGML_AVX_VNNI=ON`n-DGGML_BMI2=ON"
```

Only enable features supported by the build/run machine.

Windows/Vulkan builds now reject projected MSBuild FileTracker paths above
248 UTF-16 characters (12 below legacy MAX_PATH). The estimate includes the
`bUNKNOWN` version placeholder, custom source suffix and 21-digit collision
timestamp; the actual build path is checked again before cleaning/configuring.
This conservative estimate models the nested shader compiler probe in llama.cpp
b11064, not every future CMake layout. If rejected, select a fresh short output
root such as `C:\b` (a long custom suffix may also need shortening). Do not copy
an old CMake cache with absolute paths. Existing outputs are not relocated.
The same guard applies to direct PowerShell calls and explicit `-BuildDir`.

## Changelog

### 2.3.9

- Migrated the main GUI from CustomTkinter/Tk to **PySide6 / Qt 6 + Fluent Widgets**,
  retaining the dark palette, sidebar, page order, card layout and initial window size.
- Reduced `app.py` to the application entry point and moved the GUI into `ui/`,
  with centrally managed styling, reusable widgets, pages, dialogs and workers.
- Replaced Tk UI queues and resize-freeze logic with queued Qt signals, background
  workers and native layouts. Pages are reused through `QStackedWidget`.
- Added batched `QPlainTextEdit` build output with a 5,000-line display limit,
  searchable Qt selectors and native source/profile/history tables.
- Reconnected source/profile management, branch discovery, version checks,
  hardware/dependency checks and builds to the existing backend. Coalesced rapid
  source-version requests and ignored stale branch responses.
- Preserved existing settings and added window geometry, maximized-state and
  build/log splitter persistence; serialized settings writes across workers.
- Moved application updates into a worker service with verified HTTPS, staged
  downloads, rollback on replacement errors and preservation of runtime data.
- Updated launchers and PyInstaller packaging for Qt, Fluent resources and icons;
  source launches now require **Python 3.10+**. CustomTkinter is no longer a
  production dependency; the original GUI remains an optional comparison copy.
- Added Qt and updater regression tests: **110 tests passed**. Native Windows
  DPI rendering checks (100–200%), real hardware/dependency checks under log load
  and the packaged Windows startup/rendering smoke test passed. Full interactive
  acceptance and real compiler-build validation remain documented separately.

### 2.3.8

- Added Windows/Vulkan path-budget checks in the GUI, Python dispatcher and
  PowerShell script to prevent deep output paths from causing MSBuild
  FileTracker failures ([#6](https://github.com/nextscript/Llama.cpp-Build-Assistant/issues/6)).
  Checks account for custom source suffixes, collision timestamps and explicit
  build directories, with guidance to use a shorter output root before cloning
  or cleaning existing builds.
- Fixed missing AVX-VNNI/BMI2 options in native Windows/MSVC CPU, CUDA and Vulkan
  builds ([#5](https://github.com/nextscript/Llama.cpp-Build-Assistant/issues/5)).
  Supplemental flags use live CPU detection and check Windows AVX state support;
  unavailable features are explicitly disabled to clear stale cache values.
  User profile overrides retain precedence, while portable and other compiler
  paths keep their existing behavior.
- Persisted validated CPU-target and parallel-job choices and clarified that
  detected CPU features do not guarantee effective compiler settings.
- Added regression coverage for path validation, preservation of existing
  builds, native flag transport, profile overrides and saved settings;
  all 82 tests pass.

Thank you, DaWaste ([@DaWasteh](https://github.com/DaWasteh)), for reporting both issues
and providing detailed reproduction steps, build evidence and tested
workarounds!

### 2.3.7

- Persisted the main window position and restored it on the next launch,
  including positions on secondary monitors.
- Centered Add/Edit Build Source and Add/Edit Build Profile dialogs over the
  main window so they open on the same monitor in multi-monitor setups.

### 2.3.6

- Added asynchronous remote branch discovery for custom build sources using
  `git ls-remote`, including repository default-branch detection, refresh,
  custom refs, validation, and offline/error fallback.
- Replaced the branch field with a fast searchable selector that remains
  responsive with large repositories. Background Git queries no longer open a
  console window on Windows.
- Reorganized Build Configuration: Build Version Status now follows the
  selected profile, uses a compact four-row/two-column layout, and Build Output
  Directory appears below Build Options.
- The npm web-UI checkbox is disabled whenever the selected profile explicitly
  sets `LLAMA_BUILD_UI=OFF`.
- Improved dashboard recommendation alignment and status coloring.

### 2.3.5

- Removed the Update Source button and its GUI update workflow from Build
  Version Status.
- Kept asynchronous version checks, update-availability reporting, and the
  View Changes dialog intact.

### 2.3.4

- Added a persistent custom build output directory with Browse and Reset to
  Default controls, write-access checks, and free-space validation.
- Added asynchronous Git-based version status for branches, forks, custom
  sources, pinned commits, and pull requests.
- Added local/remote commits, build numbers, commit differences, branch and PR
  information, last-update dates, and a commit changes dialog.
- Recorded the exact build number, commit SHA, and branch in build history.
- Added regression coverage for settings, output routing, source-version
  checks, source updates, and history metadata.

### 2.3.3

- Added row-based CMake flag editing with add/remove controls and improved
  multiline profile editing with automatic dialog resizing.
- Added the CUDA 13.x NVIDIA profile for PrismML.
- Added K2Horizon.cpp and beellama.cpp build sources.
- Updated PrismML to track the current `prism` branch instead of a pinned
  commit and increased the build-source dialog height.

### 2.3.2

- Preserved profile CMake flags losslessly on Windows by encoding each flag as
  an individual command-line value.
- Normalized multiline custom flags, logged the effective profile flags, and
  ensured user flags retain precedence over build defaults.
- Added regression coverage for flags containing spaces and semicolons.

### 2.3.1

- Preserved complete llama.cpp source checkouts and build trees instead of
  trimming successful builds to `build/bin`.
- Built the complete tools/examples/test output, provisioned web-UI assets,
  and bundled required CUDA runtime dependencies.
- Tightened post-build backend verification and output-directory selection so
  a build cannot accidentally reuse binaries from another checkout.
- Added regression coverage for checkout preservation, UI layouts, CUDA DLL
  deployment, backend verification, and profile migration.

### 2.3.0

- Hardware check: CPUID feature detection on Windows fixed (the machine code
  clobbered the output pointer, so features were always empty); real VRAM
  for AMD/Intel on Windows (registry `qwMemorySize` instead of the 4 GB
  `AdapterRAM` cap); RDNA4 detected via `hipInfo` gfx target and a wider
  name list (Radeon AI PRO R9700 included); NVIDIA driver CUDA version and
  compute capability reported.
- Recommendation: separate CUDA 12.x / 13.x profiles chosen from driver and
  GPU generation; Apple Silicon → Metal, Intel Mac → CPU (Metal is not
  maintained for x86 Macs upstream); the dashboard explains the choice.
- Profiles: no hard-coded `GPU_TARGETS=gfx1201`, no ISA flags, no forced
  npm web-UI build. Untouched v2.2 default profiles are migrated once.
- Build script (Windows): HIP builds import the VS developer environment,
  detect the gfx target with `hipInfo`, apply the HIP SDK 7.2 / MSVC 14.5x
  `<cmath>` header fix (LLVM PR #201563) in a private copy under `deps/`,
  and bundle the ROCm runtime; CUDA picks the toolkit by generation, checks
  the driver, sets `CMAKE_CUDA_ARCHITECTURES` from the installed GPUs and
  bundles cudart/cublas; SPIRV-Headers cache works (wrong marker path);
  no Chocolatey install, no global `git config`; Ninja from the VS bundle;
  parallel jobs default to the CPU count; UTF-8 log output.
- Folder names use `git rev-list --count HEAD` (matches
  `llama-server --version`) and the Auto-Tuner suffixes (`_llama.cpp`).
- GUI: "Clean build" / "Update repository" checkboxes are honoured (profiles
  only pre-fill them); CPU target, parallel jobs and "core tools only"
  options; post-build verification (`--version`, `--list-devices`) and the
  actual error lines on failure.
- Dependency check: HIP found via `HIP_PATH`/Program Files, Vulkan via
  `glslc`, Ninja via the VS bundle, no `winget list` calls.
