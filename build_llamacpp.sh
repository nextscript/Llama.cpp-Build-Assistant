#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# Universal llama.cpp build script for macOS + Linux.
# Mirrors build_llamacpp.ps1 (Windows). The Python GUI dispatches here on
# non-Windows systems via builder.py.
#
# Usage:
#   ./build_llamacpp.sh -s main -t CPU
#   ./build_llamacpp.sh -s turboquant -t Vulkan
#   ./build_llamacpp.sh -s main -t HIP
#   ./build_llamacpp.sh -s diffusion_gemma -t Vulkan   # PR-based source
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

SOURCE=""
BUILD_TYPE=""
INSTALL_DIR=""
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 8)"
BUILD_UI=0
UPDATE_REPO=0
CLEAN_BUILD=0
EXTRA_FLAGS=()

usage() {
    cat <<EOF
Usage: $0 -s SOURCE -t TYPE [-d INSTALL_DIR] [-j JOBS] [-u] [-U] [-c] [-F FLAGS]
  -s SOURCE      main|turboquant|turboquant_3_4|prismml_ternary|
                 diffusion_gemma|gemma_external_drafter|ocr_llama|
                 luce|dflash|dspark
  -t TYPE        CPU|CUDA|Vulkan|HIP|SYCL|Metal
  -d INSTALL_DIR build output dir (default: ./builds)
  -j JOBS        parallel jobs (default: nproc)
  -u             build the web UI (needs npm)
  -U             update the existing checkout (git fetch + reset)
  -c             wipe the build directory (clean configure)
  -F FLAGS       extra CMake flags, newline-separated (advanced)
EOF
    exit 1
}

while getopts ":s:t:d:j:uUcF:" opt; do
    case "$opt" in
        s) SOURCE="$OPTARG" ;;
        t) BUILD_TYPE="$OPTARG" ;;
        d) INSTALL_DIR="$OPTARG" ;;
        j) JOBS="$OPTARG" ;;
        u) BUILD_UI=1 ;;
        U) UPDATE_REPO=1 ;;
        c) CLEAN_BUILD=1 ;;
        F) while IFS= read -r _line; do [[ -n "$_line" ]] && EXTRA_FLAGS+=("$_line"); done <<< "$OPTARG" ;;
        *) usage ;;
    esac
done

[[ -z "$SOURCE" || -z "$BUILD_TYPE" ]] && usage
case "$BUILD_TYPE" in CPU|CUDA|Vulkan|HIP|SYCL|Metal) ;; *) echo "Bad type: $BUILD_TYPE"; usage ;; esac

# Metal is macOS-only.
if [[ "$BUILD_TYPE" == "Metal" && "$(uname)" != "Darwin" ]]; then
    echo "Metal is only available on macOS. Use this build type only on a Mac." >&2
    exit 1
fi

# ── Colors ────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    C_RESET=$'\033[0m'; C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
else
    C_RESET=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""
fi
log()  { printf '\n%s==>%s %s\n' "$C_CYAN" "$C_RESET" "$*"; }
ok()   { printf '    %s[OK]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '    %s[!!]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

detect_amd_gfx_target() {
    # Best-effort detection of the installed AMD GPU gfx target(s) for HIP
    # builds. Returns a comma-separated list (e.g. "gfx1201"), or empty.
    local targets=""
    if have rocm_agent_list; then
        targets="$(rocm_agent_list 2>/dev/null | grep -oE 'gfx[0-9a-f]+' | sort -u | paste -sd, -)"
    fi
    if [[ -z "$targets" ]] && have rocminfo; then
        targets="$(rocminfo 2>/dev/null | grep -iE '^\s*Name:\s*gfx' | grep -oE 'gfx[0-9a-f]+' | sort -u | paste -sd, -)"
    fi
    if [[ -z "$targets" ]] && have hipconfig; then
        targets="$(hipconfig --droc-arch 2>/dev/null | grep -oE 'gfx[0-9a-f]+' | sort -u | paste -sd, -)"
    fi
    echo "$targets"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -z "$INSTALL_DIR" ]] && INSTALL_DIR="$SCRIPT_DIR/builds"
DEPS_DIR="$SCRIPT_DIR/deps"
mkdir -p "$INSTALL_DIR"

# ── Source configuration ──────────────────────────────────────────────────
# Fields: URL BRANCH PR(n or empty) SUBMODULES(0/1) SUFFIX
declare -A SRC_URL SRC_BRANCH SRC_PR SRC_SUB SRC_SUFFIX
cfg() { SRC_URL["$1"]="$2"; SRC_BRANCH["$1"]="$3"; SRC_PR["$1"]="$4"; SRC_SUB["$1"]="$5"; SRC_SUFFIX["$1"]="$6"; }

cfg main                   "https://github.com/ggml-org/llama.cpp.git"            "master"                       ""  0 "llama.cpp"
cfg turboquant             "https://github.com/TheTom/llama-cpp-turboquant.git"   "feature/turboquant-kv-cache"  ""  0 "turboquant.cpp"
cfg turboquant_3_4         "https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant.git" "feature/turboquant-kv-cache" "" 0 "turboquant_3_4.cpp"
cfg prismml_ternary        "https://github.com/PrismML-Eng/llama.cpp.git"         "prism"                        ""  0 "prismml.cpp"
cfg diffusion_gemma        "https://github.com/ggml-org/llama.cpp.git"            "master"                   "24427" 0 "diffusion_gemma.cpp"
cfg gemma_external_drafter "https://github.com/ggml-org/llama.cpp.git"            "master"                   "23211" 0 "gemma_drafter.cpp"
cfg ocr_llama              "https://github.com/ggml-org/llama.cpp.git"            "master"                   "17400" 0 "ocr_llama.cpp"
cfg luce                   "https://github.com/Luce-Org/lucebox-hub.git"          "main"                         ""  1 "luce.cpp"
cfg dflash                 "https://github.com/Anbild/beellama.cpp.git"           "main"                         ""  0 "dflash.cpp"
cfg dspark                 "https://github.com/Anbild/beellama.cpp.git"           "main"                         ""  0 "dspark.cpp"

if [[ -z "${SRC_URL[$SOURCE]:-}" ]]; then echo "Unknown source: $SOURCE"; exit 1; fi
REPO_URL="${SRC_URL[$SOURCE]}"
REPO_BRANCH="${SRC_BRANCH[$SOURCE]}"
REPO_PR="${SRC_PR[$SOURCE]}"
REPO_SUB="${SRC_SUB[$SOURCE]}"
DIR_SUFFIX="${SRC_SUFFIX[$SOURCE]}"

# ── Dependency checks ─────────────────────────────────────────────────────
log "Checking build prerequisites"
have git   || { warn "git missing";   exit 1; }
have cmake || { warn "cmake missing"; exit 1; }
ok "git:   $(git --version)"
ok "cmake: $(cmake --version | head -1)"
if have ninja; then ok "ninja: $(ninja --version)"; else warn "ninja not found (recommended; installing may help)"; fi

# macOS: ensure Xcode command line tools / Metal SDK
if [[ "$(uname)" == "Darwin" ]]; then
    if ! have clang; then
        log "Installing Xcode Command Line Tools"
        xcode-select --install 2>/dev/null || warn "Run: xcode-select --install"
    fi
fi

# Backend-specific toolchain checks
case "$BUILD_TYPE" in
    CUDA)
        have nvcc || { warn "CUDA Toolkit (nvcc) not found: https://developer.nvidia.com/cuda-downloads"; exit 1; }
        ok "CUDA: $(nvcc --version | grep release)"
        ;;
    Vulkan)
        # glslc / glslangValidator needed; SPIRV-Headers built below for RDNA4.
        if have glslc || have glslangValidator; then ok "Vulkan shader compiler found";
        else warn "Vulkan SDK not found: https://vulkan.lunarg.com/ — continuing anyway (SPIRV-Headers built from source)"; fi
        ;;
    HIP)
        have hipcc || { warn "ROCm/HIP (hipcc) not found: https://rocm.docs.amd.com"; exit 1; }
        ok "HIP: $(hipcc --version | tail -1)"
        ;;
    Metal)
        # Metal needs the macOS SDK / Xcode Command Line Tools (Metal framework).
        if [[ "$(uname)" != "Darwin" ]]; then
            warn "Metal backend is macOS-only."; exit 1
        fi
        if have xcrun; then ok "Xcode CLT: $(xcrun --find clang 2>/dev/null)";
        else warn "Run: xcode-select --install"; exit 1; fi
        ;;
    SYCL)
        if have icpx || have icx; then ok "Intel oneAPI DPC++ found"
        else
            warn "Intel oneAPI not found. Source setvars.sh first, e.g.:"
            warn '  source /opt/intel/oneapi/setvars.sh'
            exit 1
        fi
        ;;
esac

# ── SPIRV-Headers (RDNA4 / recent Vulkan) ─────────────────────────────────
build_spirv_headers() {
    local src="$DEPS_DIR/SPIRV-Headers"
    local inst="$src/install"
    local marker="$inst/include/spirv/spirv.hpp"
    if [[ -f "$marker" ]]; then ok "SPIRV-Headers already installed: $inst"; echo "$inst"; return; fi
    log "Building SPIRV-Headers from source"
    mkdir -p "$DEPS_DIR"
    [[ -d "$src" ]] || git clone --depth 1 https://github.com/KhronosGroup/SPIRV-Headers.git "$src"
    cmake -S "$src" -B "$src/build" -DCMAKE_INSTALL_PREFIX="$inst" -G Ninja 2>/dev/null || cmake -S "$src" -B "$src/build" -DCMAKE_INSTALL_PREFIX="$inst"
    cmake --build "$src/build" --config Release
    cmake --install "$src/build" --config Release
    ok "SPIRV-Headers installed to $inst"
    echo "$inst"
}

SPIRV_PREFIX=""
if [[ "$BUILD_TYPE" == "Vulkan" ]]; then
    SPIRV_PREFIX="$(build_spirv_headers)"
fi

# ── Clone repo ────────────────────────────────────────────────────────────
log "Preparing $SOURCE"
cd "$INSTALL_DIR"

# Enable long paths for Windows (260 char limit workaround)
git config --global core.longpaths true 2>/dev/null || true
ok "git core.longpaths enabled"

dir=""
existing=$(find . -maxdepth 1 -type d -regex "\./b[0-9]\+_${DIR_SUFFIX}" 2>/dev/null | sort -r | head -1 || true)
if [[ -n "$existing" ]]; then
    dir="$existing"
    if [[ "$UPDATE_REPO" == "1" ]]; then
        log "Updating existing checkout: $dir"
        ( cd "$dir" \
            && git fetch --all --prune \
            && git reset --hard "origin/$REPO_BRANCH" \
            && git clean -fdx -e node_modules )
        ok "Updated to latest '$REPO_BRANCH'"
    else
        ok "Existing directory: $dir (skipping update)"
    fi
else
    tmp="./_tmp_$SOURCE"
    rm -rf "$tmp"
    if [[ -n "$REPO_PR" ]]; then
        log "Fetching PR #$REPO_PR from $REPO_URL"
        git clone "$REPO_URL" "$tmp"
        git -C "$tmp" fetch origin "pull/${REPO_PR}/head:pr${REPO_PR}"
        git -C "$tmp" checkout "pr${REPO_PR}"
        [[ "$REPO_SUB" == "1" ]] && git -C "$tmp" submodule update --init --recursive
        ver="pr${REPO_PR}"
    else
        clone_args=(clone --branch "$REPO_BRANCH")
        [[ "$REPO_SUB" == "1" ]] && clone_args+=(--recurse-submodules --shallow-submodules)
        git "${clone_args[@]}" "$REPO_URL" "$tmp"
        desc=$(git -C "$tmp" describe --tags --always 2>/dev/null || true)
        ver=$(echo "$desc" | grep -oE 'b[0-9]+' | head -1 || true)
        [[ -z "$ver" ]] && ver="bUNKNOWN"
    fi
    dir="./${ver}_${DIR_SUFFIX}"
    rm -rf "$dir"
    mv "$tmp" "$dir"
    ok "Directory: $dir"
fi

# ── Web UI (optional) ─────────────────────────────────────────────────────
if [[ "$BUILD_UI" == "1" ]]; then
    if [[ -f "$dir/tools/ui/package.json" ]] && have npm; then
        log "Building web UI"
        (cd "$dir/tools/ui" && npm ci && npm run build)
    else
        warn "Skipping web UI build (no tools/ui or npm missing)"
    fi
fi

# ── CMake configure + build ───────────────────────────────────────────────
build_dir="$dir/build"
if [[ "$CLEAN_BUILD" == "1" ]]; then
    rm -rf "$build_dir"
fi
mkdir -p "$build_dir"

# Base flags (single-config Ninja/Makefiles on Unix).
# GGML_NATIVE=ON lets llama.cpp's own CPUID detection enable every available
# ISA (AVX2, AVX512, FMA, F16C, AMX, ...) automatically — far better than
# hard-coding AVX2/FMA/F16C, which leaves AVX512/AMX disabled on Zen4/Zen5
# and modern Intel Xeons.
cmake_flags=(-S "$dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release
             -DGGML_NATIVE=ON
             -DLLAMA_BUILD_SERVER=ON -DLLAMA_CURL=OFF -DGGML_CCACHE=OFF)

case "$BUILD_TYPE" in
    CPU)
        cmake_flags+=(-DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DBUILD_SHARED_LIBS=ON)
        ;;
    CUDA)
        cmake_flags+=(-DGGML_CUDA=ON -DGGML_VULKAN=OFF -DBUILD_SHARED_LIBS=ON)
        ;;
    Vulkan)
        # RDNA4 recipe: Vulkan + recent SPIRV-Headers, static build.
        cmake_flags+=(-DGGML_VULKAN=ON -DGGML_CUDA=OFF -DGGML_VULKAN_CHECK_RESULTS=OFF
                      -DBUILD_SHARED_LIBS=OFF)
        [[ -n "$SPIRV_PREFIX" ]] && cmake_flags+=(-DCMAKE_PREFIX_PATH="$SPIRV_PREFIX")
        [[ "$BUILD_UI" == "1" ]] && cmake_flags+=(-DLLAMA_BUILD_UI=ON -DLLAMA_USE_PREBUILT_UI=OFF)
        ;;
    HIP)
        cmake_flags+=(-DGGML_HIP=ON -DGGML_CUDA=OFF -DBUILD_SHARED_LIBS=ON)
        # Explicitly target the installed AMD GPU(s). AMDGPU_TARGETS is
        # deprecated upstream; GPU_TARGETS is the supported name. Without an
        # explicit target, CMake only compiles for the GPU present at configure
        # time (breaks multi-GPU / headless setups).
        amd_target="$(detect_amd_gfx_target)"
        [[ -n "$amd_target" ]] && cmake_flags+=("-DGPU_TARGETS=$amd_target")
        ;;
    SYCL)
        cmake_flags=(-S "$dir" -B "$build_dir" -G Ninja -DCMAKE_BUILD_TYPE=Release
                     -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx
                     -DGGML_SYCL=ON -DGGML_SYCL_F16=ON
                     -DGGML_NATIVE=ON
                     -DBUILD_SHARED_LIBS=ON -DLLAMA_BUILD_SERVER=ON
                     -DLLAMA_CURL=OFF -DGGML_CCACHE=OFF)
        ;;
    Metal)
        # macOS Metal backend. EMBED_LIBRARY bakes the .metallib into the
        # binary so it is self-contained (no external metallib lookup).
        cmake_flags+=(-DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON
                      -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DBUILD_SHARED_LIBS=ON)
        ;;
esac

log "CMake configure: cmake ${cmake_flags[*]}"
# Append any user-supplied extra CMake flags last (highest precedence).
[[ ${#EXTRA_FLAGS[@]} -gt 0 ]] && cmake_flags+=("${EXTRA_FLAGS[@]}")
cmake "${cmake_flags[@]}"

log "Building $SOURCE ($BUILD_TYPE) with $JOBS jobs"
cmake --build "$build_dir" --config Release --parallel "$JOBS"

# ── Done ──────────────────────────────────────────────────────────────────
log "BUILD SUCCESSFUL! ($BUILD_TYPE)"
bin_path="$build_dir/bin"
ok "Binaries: $bin_path"
( shopt -s nullglob; for f in "$bin_path"/llama-*; do ok "  $(basename "$f")"; done )
echo
echo "Start server:"
echo "  $bin_path/llama-server -m <model.gguf> --host 0.0.0.0 --port 8080"
