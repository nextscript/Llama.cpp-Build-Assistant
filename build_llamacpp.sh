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
#   ./build_llamacpp.sh -s ocr_llama -t Vulkan       # PR-based source
#
# Output: <INSTALL_DIR>/<bNNNN>_<backend>_<suffix>/build/bin/llama-server
# bNNNN is "git rev-list --count HEAD", i.e. exactly the build number that
# llama-server --version reports, so the folder name never lies.
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

SOURCE=""
BUILD_TYPE=""
INSTALL_DIR=""
BUILD_DIR_ARG=""
REPO_URL_ARG=""
REPO_BRANCH_ARG=""
DIR_SUFFIX_ARG=""
SOURCE_COMMIT_ARG=""
FETCH_REF_ARG=""
REPO_PR_ARG=""
REPO_SUB_ARG=0
JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 8)"
CPU_TARGET="portable"
CUDA_MAJOR=""
TARGETS=""
BUILD_UI=0
UPDATE_REPO=0
CLEAN_BUILD=0
EXTRA_FLAGS=()

usage() {
    cat <<EOF
Usage: $0 -s SOURCE -t TYPE [-d INSTALL_DIR] [-B BUILD_DIR] [-j JOBS] [-C portable|native] [-V 12|13] [-T targets] [-u] [-U] [-c] [-F FLAGS]
  -s SOURCE      main|turboquant|ternary_bonsai|ocr_llama|diffusion_gemma
  -t TYPE        CPU|CUDA|Vulkan|HIP|SYCL|Metal
  -d INSTALL_DIR dir holding the source checkout (default: ./builds)
  -B BUILD_DIR   CMake build/output dir (default: <checkout>/build)
  -j JOBS        parallel jobs (default: nproc)
  -C TARGET      CPU target: portable (AVX2, default) or native (this machine)
  -V MAJOR       CUDA toolkit generation to use (12 or 13; default: newest found)
  -T TARGETS     comma-separated CMake targets (default: everything)
  -u             build the web UI with npm (default: download prebuilt assets)
  -U             update the existing checkout (git fetch + reset)
  -c             wipe the build directory (clean configure)
  -F FLAGS       extra CMake flags, newline-separated (advanced)
EOF
    exit 1
}

while getopts ":s:t:d:B:j:C:V:T:uUcF:r:b:o:x:f:p:m" opt; do
    case "$opt" in
        s) SOURCE="$OPTARG" ;;
        t) BUILD_TYPE="$OPTARG" ;;
        d) INSTALL_DIR="$OPTARG" ;;
        B) BUILD_DIR_ARG="$OPTARG" ;;
        j) JOBS="$OPTARG" ;;
        C) CPU_TARGET="$OPTARG" ;;
        V) CUDA_MAJOR="$OPTARG" ;;
        T) TARGETS="$OPTARG" ;;
        u) BUILD_UI=1 ;;
        U) UPDATE_REPO=1 ;;
        c) CLEAN_BUILD=1 ;;
        F) while IFS= read -r _line; do [[ -n "$_line" ]] && EXTRA_FLAGS+=("$_line"); done <<< "$OPTARG" ;;
        r) REPO_URL_ARG="$OPTARG" ;;
        b) REPO_BRANCH_ARG="$OPTARG" ;;
        o) DIR_SUFFIX_ARG="$OPTARG" ;;
        x) SOURCE_COMMIT_ARG="$OPTARG" ;;
        f) FETCH_REF_ARG="$OPTARG" ;;
        p) REPO_PR_ARG="$OPTARG" ;;
        m) REPO_SUB_ARG=1 ;;
        *) usage ;;
    esac
done

[[ -z "$SOURCE" || -z "$BUILD_TYPE" ]] && usage
case "$BUILD_TYPE" in CPU|CUDA|Vulkan|HIP|SYCL|Metal) ;; *) echo "Bad type: $BUILD_TYPE"; usage ;; esac
case "$CPU_TARGET" in portable|native) ;; *) echo "Bad CPU target: $CPU_TARGET"; usage ;; esac
[[ "$JOBS" =~ ^[0-9]+$ && "$JOBS" -gt 0 ]] || JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 8)"

UNAME_S="$(uname)"
UNAME_M="$(uname -m)"

# Metal is macOS-only.
if [[ "$BUILD_TYPE" == "Metal" && "$UNAME_S" != "Darwin" ]]; then
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

has_extra_flag() {
    local prefix="$1" f
    for f in "${EXTRA_FLAGS[@]:-}"; do [[ "$f" == "$prefix"* ]] && return 0; done
    return 1
}

detect_amd_gfx_target() {
    # Best-effort detection of the installed AMD GPU gfx target(s) for HIP
    # builds. Returns a semicolon-separated list (e.g. "gfx1201"), or empty.
    local targets=""
    if have rocm_agent_enumerator; then
        targets="$(rocm_agent_enumerator 2>/dev/null | grep -oE 'gfx[0-9a-f]+' | grep -v '^gfx000$' | sort -u | paste -sd';' -)"
    fi
    if [[ -z "$targets" ]] && have rocminfo; then
        targets="$(rocminfo 2>/dev/null | grep -iE '^\s*Name:\s*gfx' | grep -oE 'gfx[0-9a-f]+' | sort -u | paste -sd';' -)"
    fi
    echo "$targets"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -z "$INSTALL_DIR" ]] && INSTALL_DIR="$SCRIPT_DIR/builds"
DEPS_DIR="$SCRIPT_DIR/deps"
mkdir -p "$INSTALL_DIR"

# ── Source configuration ──────────────────────────────────────────────────
# Fields: URL BRANCH PR(n or empty) SUBMODULES(0/1) SUFFIX (Auto-Tuner naming)
declare -A SRC_URL SRC_BRANCH SRC_PR SRC_SUB SRC_SUFFIX
cfg() { SRC_URL["$1"]="$2"; SRC_BRANCH["$1"]="$3"; SRC_PR["$1"]="$4"; SRC_SUB["$1"]="$5"; SRC_SUFFIX["$1"]="$6"; }

cfg main                   "https://github.com/ggml-org/llama.cpp.git"            "master"                       ""  0 "llama.cpp"
cfg turboquant             "https://github.com/TheTom/llama-cpp-turboquant.git"   "master"                       ""  0 "tq_llama.cpp"
cfg ternary_bonsai         "https://github.com/PrismML-Eng/llama.cpp.git"         "prism"                        ""  0 "2b_llama.cpp"
cfg ocr_llama              "https://github.com/ggml-org/llama.cpp.git"            "master"                   "17400" 0 "ocr_llama.cpp"
cfg diffusion_gemma        "https://github.com/ggml-org/llama.cpp.git"            "master"                   "24427" 0 "d_llama.cpp"

if [[ -z "${SRC_URL[$SOURCE]:-}" && -z "$REPO_URL_ARG" ]]; then echo "Unknown source: $SOURCE"; exit 1; fi
REPO_URL="${REPO_URL_ARG:-${SRC_URL[$SOURCE]:-}}"
REPO_BRANCH="${REPO_BRANCH_ARG:-${SRC_BRANCH[$SOURCE]:-master}}"
REPO_PR="${REPO_PR_ARG:-${SRC_PR[$SOURCE]:-}}"
REPO_SUB="${SRC_SUB[$SOURCE]:-0}"
if [[ "$REPO_SUB_ARG" == "1" ]]; then REPO_SUB=1; fi
DIR_SUFFIX="${DIR_SUFFIX_ARG:-${SRC_SUFFIX[$SOURCE]:-${SOURCE}_llama.cpp}}"

# ── Dependency checks ─────────────────────────────────────────────────────
log "Checking build prerequisites"
have git   || { warn "git missing";   exit 1; }
have cmake || { warn "cmake missing"; exit 1; }
ok "git:   $(git --version)"
ok "cmake: $(cmake --version | head -1)"
if have ninja; then ok "ninja: $(ninja --version)"; else warn "ninja not found (recommended; installing may help)"; fi

# macOS: ensure Xcode command line tools / Metal SDK
if [[ "$UNAME_S" == "Darwin" ]]; then
    if ! have clang; then
        log "Installing Xcode Command Line Tools"
        xcode-select --install 2>/dev/null || warn "Run: xcode-select --install"
    fi
fi

# Backend-specific toolchain checks
CUDA_HOME_SEL=""
case "$BUILD_TYPE" in
    CUDA)
        # Pick the toolkit: -V pins the major version, otherwise nvcc from PATH
        # or the newest /usr/local/cuda-* install.
        candidates=()
        if [[ -n "${CUDA_HOME:-}" ]]; then candidates+=("$CUDA_HOME"); fi
        if [[ -n "${CUDA_PATH:-}" ]]; then candidates+=("$CUDA_PATH"); fi
        for d in /usr/local/cuda-* /opt/cuda; do [[ -d "$d" ]] && candidates+=("$d"); done
        if have nvcc; then candidates+=("$(dirname "$(dirname "$(command -v nvcc)")")"); fi
        best=""; best_ver=""
        for d in "${candidates[@]:-}"; do
            [[ -x "$d/bin/nvcc" ]] || continue
            v="$("$d/bin/nvcc" --version 2>/dev/null | grep -oE 'release [0-9]+\.[0-9]+' | grep -oE '[0-9]+\.[0-9]+' | head -1)"
            [[ -n "$v" ]] || continue
            if [[ -n "$CUDA_MAJOR" && "${v%%.*}" != "$CUDA_MAJOR" ]]; then continue; fi
            if [[ -z "$best" ]] || [[ "$(printf '%s\n%s\n' "$best_ver" "$v" | sort -V | tail -1)" == "$v" && "$v" != "$best_ver" ]]; then
                best="$d"; best_ver="$v"
            fi
        done
        if [[ -z "$best" ]]; then
            if [[ -n "$CUDA_MAJOR" ]]; then warn "No CUDA $CUDA_MAJOR.x toolkit found (CUDA_HOME, /usr/local/cuda-*, PATH)."; fi
            warn "CUDA Toolkit (nvcc) not found: https://developer.nvidia.com/cuda-downloads"; exit 1
        fi
        CUDA_HOME_SEL="$best"
        export PATH="$best/bin:$PATH" CUDA_HOME="$best" CUDAToolkit_ROOT="$best"
        ok "CUDA $best_ver: $best"
        if have nvidia-smi; then
            drv="$(nvidia-smi 2>/dev/null | grep -oE 'CUDA Version: [0-9]+\.[0-9]+' | grep -oE '[0-9]+\.[0-9]+' | head -1 || true)"
            if [[ -n "$drv" && "$(printf '%s\n%s\n' "$drv" "$best_ver" | sort -V | tail -1)" != "$drv" ]]; then
                warn "CUDA toolkit $best_ver is newer than the driver supports ($drv). Update the driver or use -V 12."
                exit 1
            fi
            caps="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | tr -d ' ' | sort -u | paste -sd' ' - || true)"
            if [[ "${best_ver%%.*}" -ge 13 ]]; then
                for cc in $caps; do
                    if [[ "$(printf '%s\n%s\n' "$cc" "7.5" | sort -V | head -1)" != "7.5" ]]; then
                        warn "CUDA 13 dropped GPUs older than Turing (compute capability $cc). Use -V 12."; exit 1
                    fi
                done
            fi
            CUDA_ARCHS=""
            for cc in $caps; do
                num="$(( ${cc%%.*} * 10 + ${cc##*.} ))"
                if (( num >= 120 )); then a="${num}a-real"; else a="${num}-real"; fi
                [[ ";$CUDA_ARCHS;" == *";$a;"* ]] || CUDA_ARCHS="${CUDA_ARCHS:+$CUDA_ARCHS;}$a"
            done
            [[ -n "$CUDA_ARCHS" ]] && ok "CUDA architectures: $CUDA_ARCHS"
        fi
        ;;
    Vulkan)
        # glslc needed; SPIRV-Headers built below for RDNA4.
        if have glslc || have glslangValidator; then ok "Vulkan shader compiler found";
        elif [[ -n "${VULKAN_SDK:-}" && -x "$VULKAN_SDK/bin/glslc" ]]; then export PATH="$VULKAN_SDK/bin:$PATH"; ok "Vulkan SDK: $VULKAN_SDK";
        else warn "Vulkan SDK (glslc) not found: https://vulkan.lunarg.com/ - continuing anyway (SPIRV-Headers built from source)"; fi
        ;;
    HIP)
        have hipcc || { warn "ROCm/HIP (hipcc) not found: https://rocm.docs.amd.com"; exit 1; }
        ok "HIP: $(hipcc --version | tail -1)"
        ;;
    Metal)
        if [[ "$UNAME_M" != "arm64" ]]; then
            warn "Metal is only supported on Apple Silicon; upstream builds Intel Macs with GGML_METAL=OFF."
            warn "Use the CPU or Vulkan (MoltenVK) build type on this Mac."
            exit 1
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
    # SPIRV-Headers installs include/spirv/unified1/spirv.hpp (not include/spirv/spirv.hpp).
    local marker="$inst/include/spirv/unified1/spirv.hpp"
    local cmakecfg="$inst/share/cmake/SPIRV-Headers/SPIRV-HeadersConfig.cmake"
    if [[ -f "$marker" && -f "$cmakecfg" ]]; then ok "SPIRV-Headers already installed: $inst" >&2; echo "$inst"; return; fi
    log "Building SPIRV-Headers from source" >&2
    mkdir -p "$DEPS_DIR"
    if [[ ! -d "$src/.git" ]]; then
        rm -rf "$src"
        git clone --depth 1 https://github.com/KhronosGroup/SPIRV-Headers.git "$src" >&2
    fi
    ( cmake -S "$src" -B "$src/build" -DCMAKE_INSTALL_PREFIX="$inst" -DSPIRV_HEADERS_ENABLE_TESTS=OFF -G Ninja 2>/dev/null \
      || cmake -S "$src" -B "$src/build" -DCMAKE_INSTALL_PREFIX="$inst" -DSPIRV_HEADERS_ENABLE_TESTS=OFF ) >&2
    cmake --build "$src/build" --config Release >&2
    cmake --install "$src/build" --config Release >&2
    ok "SPIRV-Headers installed to $inst" >&2
    echo "$inst"
}

SPIRV_PREFIX=""
if [[ "$BUILD_TYPE" == "Vulkan" ]]; then
    SPIRV_PREFIX="$(build_spirv_headers)"
fi

# ── Clone repo ────────────────────────────────────────────────────────────
log "Preparing $SOURCE"
cd "$INSTALL_DIR"

build_number_name() {
    # "bNNNN" from "git rev-list --count HEAD": llama.cpp's own build number.
    local n
    n="$(git -C "$1" rev-list --count HEAD 2>/dev/null || true)"
    if [[ "$n" =~ ^[0-9]+$ ]]; then echo "b$n"; else echo "bUNKNOWN"; fi
}

dir=""
# Backend-qualified, Auto-Tuner-compatible folder name, e.g.
# "b10830_vulkan_llama.cpp". One folder per source+version+backend.
backend="$(printf '%s' "$BUILD_TYPE" | tr '[:upper:]' '[:lower:]')"
existing=$(find . -maxdepth 1 -type d -regex "\./\(b[0-9]+\|bUNKNOWN\|pr[0-9]+\|pinned_[0-9a-f]+\)_${backend}_${DIR_SUFFIX}" 2>/dev/null | sort -r | head -1 || true)
if [[ -n "$existing" && ! -d "$existing/.git" ]]; then
    # Legacy trimmed outputs have no source tree to resume; keep them intact.
    existing=""
fi
unused_build_path() {
    local version="$1" candidate="./${1}_${backend}_${DIR_SUFFIX}"
    while [[ -e "$candidate" ]]; do
        candidate="./${version}_run_$(date +%Y%m%d%H%M%S)_${RANDOM}_${backend}_${DIR_SUFFIX}"
    done
    printf '%s\n' "$candidate"
}
if [[ -n "$existing" ]]; then
    dir="$existing"
    if [[ "$UPDATE_REPO" == "1" ]]; then
        log "Updating existing checkout: $dir"
        if [[ -n "$SOURCE_COMMIT_ARG" ]]; then
            ( cd "$dir" \
                && git fetch --all --prune \
                && { [[ -z "$FETCH_REF_ARG" ]] || git fetch --force origin "$FETCH_REF_ARG"; } \
                && git checkout --detach "$SOURCE_COMMIT_ARG" \
                && git clean -fdx -e node_modules -e build )
        elif [[ -n "$REPO_PR" ]]; then
            ( cd "$dir" \
                && git fetch --force origin "pull/${REPO_PR}/head:pr${REPO_PR}" \
                && git checkout "pr${REPO_PR}" \
                && git reset --hard "pr${REPO_PR}" \
                && git clean -fdx -e node_modules -e build )
        else
            ( cd "$dir" \
                && git fetch --all --prune \
                && git reset --hard "origin/$REPO_BRANCH" \
                && git clean -fdx -e node_modules -e build )
        fi
        ok "Updated to latest '$REPO_BRANCH'"
        # The build number may have moved: rename the folder to stay truthful.
        newdir="./$(build_number_name "$dir")_${backend}_${DIR_SUFFIX}"
        if [[ "$newdir" != "$dir" ]]; then
            newdir="$(unused_build_path "$(build_number_name "$dir")")"
            mv "$dir" "$newdir"
            dir="$newdir"
        fi
    else
        ok "Existing directory: $dir (skipping update)"
    fi
else
    tmp="$(mktemp -d "./_tmp_${SOURCE}_${backend}_XXXXXXXX")"
    if [[ -n "$SOURCE_COMMIT_ARG" ]]; then
        log "Cloning pinned source from $REPO_URL"
        git clone "$REPO_URL" "$tmp"
        [[ -n "$FETCH_REF_ARG" ]] && git -C "$tmp" fetch --force origin "$FETCH_REF_ARG"
        git -C "$tmp" checkout --detach "$SOURCE_COMMIT_ARG"
        [[ "$REPO_SUB" == "1" ]] && git -C "$tmp" submodule update --init --recursive
    elif [[ -n "$REPO_PR" ]]; then
        log "Fetching PR #$REPO_PR from $REPO_URL"
        git clone "$REPO_URL" "$tmp"
        git -C "$tmp" fetch origin "pull/${REPO_PR}/head:pr${REPO_PR}"
        git -C "$tmp" checkout "pr${REPO_PR}"
        [[ "$REPO_SUB" == "1" ]] && git -C "$tmp" submodule update --init --recursive
    else
        clone_args=(clone --branch "$REPO_BRANCH")
        [[ "$REPO_SUB" == "1" ]] && clone_args+=(--recurse-submodules --shallow-submodules)
        git "${clone_args[@]}" "$REPO_URL" "$tmp"
    fi
    ver="$(build_number_name "$tmp")"
    dir="$(unused_build_path "$ver")"
    mv "$tmp" "$dir"
    ok "Directory: $dir"
fi
ok "Source commit: $(git -C "$dir" rev-parse --short=9 HEAD 2>/dev/null || echo unknown)"

# ── Web UI ────────────────────────────────────────────────────────────────
# Build assets explicitly for both the old and the current source layout.
ui_flags=(-DLLAMA_BUILD_UI=ON -DLLAMA_USE_PREBUILT_UI=ON)
ui_source=""
for relative in tools/ui tools/server/webui; do
    if [[ -f "$dir/$relative/package.json" ]]; then ui_source="$dir/$relative"; break; fi
done
if [[ "$BUILD_UI" == "1" && -n "$ui_source" ]] && have npm; then
    log "Building Web UI: $ui_source"
    (
        cd "$ui_source"
        if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
        npm run build
    )
    ui_flags=(-DLLAMA_BUILD_UI=ON -DLLAMA_USE_PREBUILT_UI=OFF)
    ok "Web UI: built from source"
else
    ok "Web UI: using prebuilt assets (download requires internet)"
fi
if [[ "$SOURCE" == "ternary_bonsai" ]]; then ui_flags+=(-DLLAMA_OPENSSL=OFF); fi

if [[ "$BUILD_TYPE" == "HIP" || "$BUILD_TYPE" == "CUDA" ]] &&
   grep -Eq '^[[:space:]]*set[[:space:]]*\([[:space:]]*GGML_CUDA_FA_QUANTS[[:space:]]' "$dir/ggml/CMakeLists.txt"; then
    ui_flags+=(-UGGML_CUDA_FA_ALL_QUANTS)
    converted_flags=()
    explicit_quants=0
    for flag in "${EXTRA_FLAGS[@]}"; do
        [[ "$flag" =~ ^-DGGML_CUDA_FA_QUANTS(:STRING)?= ]] && explicit_quants=1
    done
    for flag in "${EXTRA_FLAGS[@]}"; do
        if [[ "$flag" =~ ^-DGGML_CUDA_FA_ALL_QUANTS(:BOOL)?=(ON|OFF)$ ]]; then
            if [[ "$explicit_quants" == "0" ]]; then
                if [[ "${BASH_REMATCH[2]}" == "ON" ]]; then
                    converted_flags+=(-DGGML_CUDA_FA_QUANTS=all)
                else
                    converted_flags+=(-UGGML_CUDA_FA_QUANTS)
                fi
            fi
        else
            converted_flags+=("$flag")
        fi
    done
    EXTRA_FLAGS=("${converted_flags[@]}")
fi

# ── CMake configure + build ───────────────────────────────────────────────
if [[ -n "$BUILD_DIR_ARG" ]]; then
    build_dir="$BUILD_DIR_ARG"
else
    # Standard llama.cpp layout (build/bin/...) so launchers such as
    # Auto-Tuner can auto-discover llama-server inside this folder.
    build_dir="$dir/build"
fi
if [[ "$CLEAN_BUILD" == "1" ]]; then
    rm -rf "$build_dir"
fi
mkdir -p "$build_dir"

# CPU instruction-set target. On x86-64, "portable" pins AVX2/FMA/F16C
# (x86-64-v3) so the binary runs on any CPU since Haswell/Zen 1; "native"
# lets llama.cpp's own detection enable AVX512/AMX for this machine only.
# arm64 (Apple Silicon, Graviton, Pi) always uses the compiler's detection.
cpu_flags=()
case "$UNAME_M" in
    x86_64|amd64)
        if [[ "$CPU_TARGET" == "native" ]]; then
            cpu_flags=(-DGGML_NATIVE=ON)
        else
            cpu_flags=(-DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON
                       -DGGML_AVX_VNNI=OFF -DGGML_BMI2=ON
                       -DGGML_AVX512=OFF -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_AVX512_BF16=OFF)
        fi
        ;;
    *)
        cpu_flags=(-DGGML_NATIVE=ON)
        ;;
esac
ok "CPU target: $CPU_TARGET ($UNAME_M)"

# Base flags (single-config Ninja/Makefiles on Unix).
cmake_flags=(-S "$dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release
             -DLLAMA_BUILD_SERVER=ON -DLLAMA_CURL=OFF -DGGML_CCACHE=OFF
             "${cpu_flags[@]}")

case "$BUILD_TYPE" in
    CPU)
        cmake_flags+=(-DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DBUILD_SHARED_LIBS=OFF)
        # Intel Macs: Metal is not maintained for x86 Macs (upstream ships
        # GGML_METAL=OFF); make sure a "CPU" build really is CPU-only.
        if [[ "$UNAME_S" == "Darwin" && "$UNAME_M" != "arm64" ]]; then cmake_flags+=(-DGGML_METAL=OFF); fi
        ;;
    CUDA)
        cmake_flags+=(-DGGML_CUDA=ON -DGGML_VULKAN=OFF -DBUILD_SHARED_LIBS=OFF)
        [[ -n "$CUDA_HOME_SEL" ]] && cmake_flags+=(-DCUDAToolkit_ROOT="$CUDA_HOME_SEL" -DCMAKE_CUDA_COMPILER="$CUDA_HOME_SEL/bin/nvcc")
        if [[ -n "${CUDA_ARCHS:-}" ]] && ! has_extra_flag "-DCMAKE_CUDA_ARCHITECTURES="; then
            cmake_flags+=(-DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCHS")
        fi
        ;;
    Vulkan)
        # RDNA4 recipe: Vulkan + recent SPIRV-Headers, static build.
        cmake_flags+=(-DGGML_VULKAN=ON -DGGML_CUDA=OFF -DGGML_VULKAN_CHECK_RESULTS=OFF
                      -DBUILD_SHARED_LIBS=OFF)
        [[ -n "$SPIRV_PREFIX" ]] && cmake_flags+=(-DCMAKE_PREFIX_PATH="$SPIRV_PREFIX")
        # On macOS Vulkan means MoltenVK/KosmicKrisp; Metal must be off then.
        [[ "$UNAME_S" == "Darwin" ]] && cmake_flags+=(-DGGML_METAL=OFF)
        ;;
    HIP)
        cmake_flags+=(-DGGML_HIP=ON -DGGML_CUDA=OFF -DBUILD_SHARED_LIBS=OFF)
        # Explicitly target the installed AMD GPU(s). AMDGPU_TARGETS is
        # deprecated upstream; GPU_TARGETS is the supported name. Without an
        # explicit target, CMake only compiles for the GPU present at configure
        # time (breaks multi-GPU / headless setups).
        if ! has_extra_flag "-DGPU_TARGETS="; then
            amd_target="$(detect_amd_gfx_target)"
            if [[ -n "$amd_target" ]]; then cmake_flags+=("-DGPU_TARGETS=$amd_target"); ok "AMD GPU target(s): $amd_target";
            else warn "Could not detect the AMD gfx target; pass -DGPU_TARGETS=gfxNNNN via extra flags if the build fails."; fi
        fi
        ;;
    SYCL)
        cmake_flags=(-S "$dir" -B "$build_dir" -G Ninja -DCMAKE_BUILD_TYPE=Release
                     -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx
                     -DGGML_SYCL=ON -DGGML_SYCL_F16=ON
                     -DBUILD_SHARED_LIBS=ON -DLLAMA_BUILD_SERVER=ON
                     -DLLAMA_CURL=OFF -DGGML_CCACHE=OFF "${cpu_flags[@]}")
        ;;
    Metal)
        # macOS Metal backend. EMBED_LIBRARY bakes the .metallib into the
        # binary so it is self-contained (no external metallib lookup).
        cmake_flags+=(-DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON
                      -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DBUILD_SHARED_LIBS=ON)
        ;;
esac
cmake_flags+=(${ui_flags[@]+"${ui_flags[@]}"})

# Append any user-supplied extra CMake flags last (highest precedence).
[[ ${#EXTRA_FLAGS[@]} -gt 0 ]] && cmake_flags+=("${EXTRA_FLAGS[@]}")
log "CMake configure: cmake ${cmake_flags[*]}"
cmake "${cmake_flags[@]}"

target_args=()
if [[ -n "$TARGETS" ]]; then
    IFS=',' read -r -a _targets <<< "$TARGETS"
    target_args=(--target "${_targets[@]}")
    ok "Targets: ${_targets[*]}"
fi
log "Building $SOURCE ($BUILD_TYPE) with $JOBS jobs"
cmake --build "$build_dir" --config Release --parallel "$JOBS" ${target_args[@]+"${target_args[@]}"}

# ── Done ──────────────────────────────────────────────────────────────────
log "BUILD SUCCESSFUL! ($BUILD_TYPE)"
bin_path="$build_dir/bin"
ok "Binaries: $bin_path"
echo "LLAMA_BUILD_OUTPUT=$(cd "$build_dir" && pwd -P)"
( shopt -s nullglob; for f in "$bin_path"/llama-*; do ok "  $(basename "$f")"; done )
echo
echo "Start server:"
echo "  $bin_path/llama-server -m <model.gguf> --host 0.0.0.0 --port 8080"
