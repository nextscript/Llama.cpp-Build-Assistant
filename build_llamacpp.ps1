# Universal llama.cpp Build Script
# Supports all sources and build types
#
# Usage:
#   .\build_llamacpp.ps1 -Source main -BuildType CPU
#   .\build_llamacpp.ps1 -Source turboquant -BuildType CUDA
#   .\build_llamacpp.ps1 -Source prismml_ternary -BuildType Vulkan

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("main", "turboquant", "turboquant_3_4", "prismml_ternary", 
                 "diffusion_gemma", "gemma_external_drafter", "ocr_llama", 
                 "luce", "dflash", "dspark")]
    [string]$Source,
    
    [Parameter(Mandatory=$true)]
    [ValidateSet("CPU", "CUDA", "Vulkan", "HIP", "SYCL")]
    [string]$BuildType,
    
    [string]$InstallDir = "",
    [int]$ParallelJobs = 12,
    [switch]$BuildUi
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

# Set default install directory to builds folder in script directory
if ([string]::IsNullOrEmpty($InstallDir)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $InstallDir = Join-Path $scriptDir "builds"
}

# Check for admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$useWinget = $false
if (-not $isAdmin) {
    Write-Host "INFO: Not running as Administrator. Using winget instead of Chocolatey where possible." -ForegroundColor Yellow
    if (Is-Available "winget") {
        $useWinget = $true
        OK "winget available - will use it for installations"
    } else {
        WARN "Neither Admin nor winget available. Some installations may fail."
    }
}

# --- SOURCE CONFIGURATION ---
$sourceConfig = @{
    "main" = @{
        Url = "https://github.com/ggml-org/llama.cpp.git"
        Branch = "master"
        Suffix = "llama.cpp"
    }
    "turboquant" = @{
        Url = "https://github.com/TheTom/llama-cpp-turboquant.git"
        Branch = "feature/turboquant-kv-cache"
        Suffix = "turboquant.cpp"
    }
    "turboquant_3_4" = @{
        Url = "https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant.git"
        Branch = "feature/turboquant-kv-cache"
        Suffix = "turboquant_3_4.cpp"
    }
    "prismml_ternary" = @{
        Url = "https://github.com/PrismML-Eng/llama.cpp.git"
        Branch = "prism"
        Suffix = "prismml.cpp"
    }
    "diffusion_gemma" = @{
        Url = "https://github.com/ggml-org/llama.cpp.git"
        Branch = "master"
        PR = 24427
        Suffix = "diffusion_gemma.cpp"
    }
    "gemma_external_drafter" = @{
        Url = "https://github.com/ggml-org/llama.cpp.git"
        Branch = "master"
        PR = 23211
        Suffix = "gemma_drafter.cpp"
    }
    "ocr_llama" = @{
        Url = "https://github.com/ggml-org/llama.cpp.git"
        Branch = "master"
        PR = 17400
        Suffix = "ocr_llama.cpp"
    }
    "luce" = @{
        Url = "https://github.com/Luce-Org/lucebox-hub.git"
        Branch = "main"
        Submodules = $true
        Suffix = "luce.cpp"
    }
    "dflash" = @{
        Url = "https://github.com/Anbeeld/beellama.cpp.git"
        Branch = "main"
        Suffix = "dflash.cpp"
    }
    "dspark" = @{
        Url = "https://github.com/ggml-org/llama.cpp.git"
        Branch = "master"
        Suffix = "dspark.cpp"
    }
}

$config = $sourceConfig[$Source]
$REPO_URL = $config.Url
$REPO_BRANCH = $config.Branch
$DIR_SUFFIX = $config.Suffix
$REPO_PR = $config.PR            # PR number for PR-based sources (e.g. 24427)
$REPO_SUBMODULES = $config.Submodules  # $true to clone with --recurse-submodules

# --- HELPER FUNCTIONS ---
function Log($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function WARN($msg) { Write-Host "    [!!] $msg" -ForegroundColor Yellow }

function Refresh-Path {
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
}

function Add-ToPath($p) {
    if ((Test-Path $p) -and ($env:PATH -notlike "*$p*")) {
        $env:PATH = "$p;$env:PATH"
        OK "PATH += $p"
    }
}

function Is-Available($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Get-SystemCmake {
    $candidates = Get-Command cmake -All -ErrorAction SilentlyContinue
    foreach ($c in $candidates) {
        if ($c.Source -notlike "*Visual Studio*") {
            return $c.Source
        }
    }
    return (Get-Command cmake -ErrorAction SilentlyContinue).Source
}

function Resolve-OneApiCompilerBin {
    # Resolve the Intel oneAPI compiler directory holding the SYCL runtime
    # DLLs (sycl*.dll, pi_*.dll, intel-ext*.dll, umf*.dll, ur_*.dll).
    # Prefer env vars exported by setvars.bat, then scan common install
    # locations, including the redist tree used by newer oneAPI releases.
    $candidates = @()

    if ($env:CMPLR_ROOT) {
        $candidates += Join-Path $env:CMPLR_ROOT "bin"
        $candidates += Join-Path $env:CMPLR_ROOT "windows\bin"
        $candidates += Join-Path $env:CMPLR_ROOT "redist\intel64_win\compiler"
    }
    if ($env:ONEAPI_ROOT) {
        $latest = Join-Path $env:ONEAPI_ROOT "compiler\latest"
        $candidates += Join-Path $latest "bin"
        $candidates += Join-Path $latest "windows\bin"
        $candidates += Join-Path $latest "redist\intel64_win\compiler"
    }

    foreach ($base in @(
        "C:\Program Files (x86)\Intel\oneAPI\compiler",
        "C:\Program Files\Intel\oneAPI\compiler"
    )) {
        if (Test-Path $base) {
            $candidates += Join-Path $base "latest\bin"
            $candidates += Join-Path $base "latest\windows\bin"
            $candidates += Join-Path $base "latest\redist\intel64_win\compiler"
            Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | ForEach-Object {
                    $candidates += Join-Path $_.FullName "bin"
                    $candidates += Join-Path $_.FullName "windows\bin"
                    $candidates += Join-Path $_.FullName "redist\intel64_win\compiler"
                }
        }
    }

    # First candidate that actually contains a sycl runtime DLL wins.
    foreach ($c in $candidates) {
        if ((Test-Path $c) -and (Get-ChildItem -Path $c -Filter "sycl*.dll" -ErrorAction SilentlyContinue)) {
            return $c
        }
    }
    return $null
}

function Resolve-OneApiDllDirs {
    # Return ALL oneAPI directories that may contain runtime DLLs needed by
    # SYCL binaries: compiler runtime, oneDNN, oneMKL, oneTBB, and Unified Runtime.
    $dirs = @()

    # --- Compiler / SYCL / UR runtime ---
    $compilerBin = Resolve-OneApiCompilerBin
    if ($compilerBin) { $dirs += $compilerBin }

    # --- oneDNN ---
    $dnnlCandidates = @()
    if ($env:ONEAPI_ROOT) {
        $dnnlCandidates += Join-Path $env:ONEAPI_ROOT "dnnl\latest\bin"
        $dnnlCandidates += Join-Path $env:ONEAPI_ROOT "dnnl\latest\redist\intel64_win\dnnl"
    }
    foreach ($base in @(
        "C:\Program Files (x86)\Intel\oneAPI\dnnl",
        "C:\Program Files\Intel\oneAPI\dnnl"
    )) {
        if (Test-Path $base) {
            $dnnlCandidates += Join-Path $base "latest\bin"
            $dnnlCandidates += Join-Path $base "latest\redist\intel64_win\dnnl"
            Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | ForEach-Object {
                    $dnnlCandidates += Join-Path $_.FullName "bin"
                    $dnnlCandidates += Join-Path $_.FullName "redist\intel64_win\dnnl"
                }
        }
    }
    # Also check inside compiler tree (newer oneAPI bundles dnnl there)
    if ($compilerBin) {
        $dnnlCandidates += Join-Path (Split-Path $compilerBin -Parent) "redist\intel64_win\dnnl"
        $dnnlCandidates += Join-Path $compilerBin "dnnl"
    }
    foreach ($d in $dnnlCandidates) {
        if ((Test-Path $d) -and (Get-ChildItem -Path $d -Filter "dnnl*.dll" -ErrorAction SilentlyContinue)) {
            $dirs += $d
            break
        }
    }

    # --- oneMKL ---
    $mklCandidates = @()
    if ($env:MKLROOT) {
        $mklCandidates += Join-Path $env:MKLROOT "bin"
        $mklCandidates += Join-Path $env:MKLROOT "bin\intel64"
        $mklCandidates += Join-Path $env:MKLROOT "redist\intel64"
    }
    if ($env:ONEAPI_ROOT) {
        $mklCandidates += Join-Path $env:ONEAPI_ROOT "mkl\latest\bin"
        $mklCandidates += Join-Path $env:ONEAPI_ROOT "mkl\latest\bin\intel64"
        $mklCandidates += Join-Path $env:ONEAPI_ROOT "mkl\latest\redist\intel64"
    }
    foreach ($base in @(
        "C:\Program Files (x86)\Intel\oneAPI\mkl",
        "C:\Program Files\Intel\oneAPI\mkl"
    )) {
        if (Test-Path $base) {
            $mklCandidates += Join-Path $base "latest\bin"
            $mklCandidates += Join-Path $base "latest\bin\intel64"
            $mklCandidates += Join-Path $base "latest\redist\intel64"
            Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | ForEach-Object {
                    $mklCandidates += Join-Path $_.FullName "bin"
                    $mklCandidates += Join-Path $_.FullName "bin\intel64"
                    $mklCandidates += Join-Path $_.FullName "redist\intel64"
                }
        }
    }
    foreach ($d in $mklCandidates) {
        if ((Test-Path $d) -and (Get-ChildItem -Path $d -Filter "mkl_sycl*.dll" -ErrorAction SilentlyContinue)) {
            $dirs += $d
            break
        }
    }

    # --- oneTBB (Threading Building Blocks, needed by MKL) ---
    $tbbCandidates = @()
    if ($env:TBBROOT) {
        $tbbCandidates += Join-Path $env:TBBROOT "bin"
        $tbbCandidates += Join-Path $env:TBBROOT "redist\intel64_win\tbb"
    }
    if ($env:ONEAPI_ROOT) {
        $tbbCandidates += Join-Path $env:ONEAPI_ROOT "tbb\latest\bin"
        $tbbCandidates += Join-Path $env:ONEAPI_ROOT "tbb\latest\redist\intel64_win\tbb"
    }
    foreach ($base in @(
        "C:\Program Files (x86)\Intel\oneAPI\tbb",
        "C:\Program Files\Intel\oneAPI\tbb"
    )) {
        if (Test-Path $base) {
            $tbbCandidates += Join-Path $base "latest\bin"
            $tbbCandidates += Join-Path $base "latest\redist\intel64_win\tbb"
            Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | ForEach-Object {
                    $tbbCandidates += Join-Path $_.FullName "bin"
                    $tbbCandidates += Join-Path $_.FullName "redist\intel64_win\tbb"
                }
        }
    }
    foreach ($d in $tbbCandidates) {
        if ((Test-Path $d) -and (Get-ChildItem -Path $d -Filter "tbb*.dll" -ErrorAction SilentlyContinue)) {
            $dirs += $d
            break
        }
    }

    return ($dirs | Select-Object -Unique)
}

function Copy-SyclRuntimeDlls {
    # Copy Intel oneAPI SYCL runtime DLLs next to the built executables.
    # Without these the binaries fail to start with errors like
    # "sycl8.dll not found" / "pi_win_proxy_loader.dll not found" /
    # "dnnl.dll not found" / "mkl_sycl_blas.6.dll not found" /
    # "ur_win_proxy_loader.dll not found" / "tbb12.dll not found".
    param([Parameter(Mandatory=$true)][string]$TargetDir)

    $srcDirs = Resolve-OneApiDllDirs
    if (-not $srcDirs -or $srcDirs.Count -eq 0) {
        WARN "Could not locate oneAPI compiler DLL directory."
        WARN "SYCL runtime DLLs were NOT copied — binaries may fail to start."
        WARN "Run from the 'Intel oneAPI command prompt', or copy the DLLs from"
        WARN "<oneAPI>\compiler\<version>\bin manually into: $TargetDir"
        return $false
    }

    if (-not (Test-Path $TargetDir)) { New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null }

    $patterns = @("sycl*.dll", "pi_*.dll", "intel-ext*.dll", "umf*.dll",
                  "libsycl*.dll", "sycl_*.dll", "ocloc*.dll",
                  "ur_*.dll", "dnnl*.dll", "mkl_sycl*.dll",
                  "mkl_core*.dll", "mkl_intel_thread*.dll",
                  "mkl_def*.dll", "mkl_avx*.dll", "mkl_rt*.dll",
                  "libiomp5md.dll", "libifcoremd.dll", "libmmd.dll",
                  "tbb*.dll")
    $copied = 0
    $copiedNames = @()
    foreach ($src in $srcDirs) {
        foreach ($pat in $patterns) {
            Get-ChildItem -Path $src -Filter $pat -File -ErrorAction SilentlyContinue | ForEach-Object {
                if ($_.Name -notin $copiedNames) {
                    Copy-Item $_.FullName -Destination $TargetDir -Force -ErrorAction SilentlyContinue
                    if ($?) { $copied++; $copiedNames += $_.Name }
                }
            }
        }
    }

    if ($copied -gt 0) {
        OK "Copied $copied oneAPI SYCL runtime DLL(s):"
        $copiedNames | Select-Object -Unique | ForEach-Object { OK "  $_" }
        OK "  from $($srcDirs -join ', ')"
        OK "  into $TargetDir"
        return $true
    } else {
        WARN "No SYCL runtime DLLs found to copy in: $($srcDirs -join ', ')"
        return $false
    }
}

function Get-VsGenerator {
    # Determine the Visual Studio CMake generator for the installed VS.
    $vsw = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vsw) {
        $vv = & $vsw -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationVersion 2>$null
        if ($vv) {
            $vm = [int]($vv.Split(".")[0])
            if     ($vm -ge 18) { return "Visual Studio 18 2026" }
            elseif ($vm -eq 17) { return "Visual Studio 17 2022" }
            elseif ($vm -eq 16) { return "Visual Studio 16 2019" }
            elseif ($vm -eq 15) { return "Visual Studio 15 2017" }
        }
    }
    return "Visual Studio 17 2022"
}

function Build-SpirvHeaders {
    # Build Khronos SPIRV-Headers from source into a local install prefix.
    # RDNA4 (Radeon RX 9000) requires a very recent SPIRV-Headers (shipped with
    # SPV_KHR_cooperative_matrix etc.) that is usually newer than the Vulkan
    # SDK's bundled copy. The install dir is cached, so this only runs once.
    param([Parameter(Mandatory=$true)][string]$DepsDir)

    $spirvSrc  = Join-Path $DepsDir "SPIRV-Headers"
    $spirvBld  = Join-Path $spirvSrc "build"
    $spirvInst = Join-Path $spirvSrc "install"
    $marker    = Join-Path $spirvInst "include\spirv\spirv.hpp"

    if (Test-Path $marker) {
        OK "SPIRV-Headers already installed: $spirvInst"
        return $spirvInst
    }
    if (-not (Is-Available "git")) {
        WARN "git not available — cannot build SPIRV-Headers"
        return $null
    }

    Log "Building SPIRV-Headers from source (RDNA4 / recent Vulkan support)"
    if (-not (Test-Path $spirvSrc)) {
        git clone --depth 1 https://github.com/KhronosGroup/SPIRV-Headers.git $spirvSrc
    }
    New-Item -ItemType Directory -Path $spirvBld -Force | Out-Null

    $gen = Get-VsGenerator
    $cfgFlags = @("-S", $spirvSrc, "-B", $spirvBld, "-G", $gen, "-A", "x64",
                  "-DCMAKE_INSTALL_PREFIX=$spirvInst")
    & $CMAKE_EXE @cfgFlags
    if ($LASTEXITCODE -ne 0) { WARN "SPIRV-Headers configure failed"; return $null }
    & $CMAKE_EXE --build $spirvBld --config Release
    if ($LASTEXITCODE -ne 0) { WARN "SPIRV-Headers build failed"; return $null }
    & $CMAKE_EXE --install $spirvBld --config Release
    if ($LASTEXITCODE -ne 0) { WARN "SPIRV-Headers install failed"; return $null }

    OK "SPIRV-Headers installed to $spirvInst"
    return $spirvInst
}

function Build-WebUi {
    # Build the llama.cpp web UI from source (npm ci + npm run build).
    param([Parameter(Mandatory=$true)][string]$RepoDir)
    $uiDir = Join-Path $RepoDir "tools\ui"
    if (-not (Test-Path (Join-Path $uiDir "package.json"))) { return $false }
    if (-not (Is-Available "npm")) {
        WARN "npm not found — skipping web UI build (DLLAMA_BUILD_UI needs it)"
        return $false
    }
    Log "Building web UI ($uiDir)"
    Push-Location $uiDir
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { WARN "npm ci failed"; return $false }
        npm run build
        if ($LASTEXITCODE -ne 0) { WARN "npm run build failed"; return $false }
    } finally {
        Pop-Location
    }
    OK "Web UI built"
    return $true
}

# --- 0. INSTALL DIRECTORY ---
Log "Creating install directory $InstallDir"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}
OK $InstallDir

# --- 1. CHOCOLATEY / WINGET ---
Log "Checking package manager"
$hasChoco = Is-Available "choco"
$hasWingetPkg = Is-Available "winget"

if ($isAdmin -and -not $hasChoco) {
    Log "Installing Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Refresh-Path
    Add-ToPath "$env:ALLUSERSPROFILE\chocolatey\bin"
    $hasChoco = Is-Available "choco"
} elseif ($hasChoco) {
    OK "Chocolatey: $(choco --version)"
} elseif ($hasWingetPkg) {
    $useWinget = $true
    OK "Using winget (no admin rights needed)"
} else {
    WARN "No package manager found (choco/winget). Dependency installs may fail."
}

# --- 2. GIT ---
Log "Checking Git"
if (-not (Is-Available "git")) {
    if ($useWinget) {
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
    } elseif ($hasChoco) {
        choco install git -y --no-progress
    }
    Refresh-Path
    Add-ToPath "C:\Program Files\Git\cmd"
} else {
    OK "Git: $(git --version)"
}

# --- 3. CMAKE ---
Log "Checking CMake"
Add-ToPath "C:\Program Files\CMake\bin"
if (-not (Is-Available "cmake")) {
    if ($useWinget) {
        winget install --id Kitware.CMake -e --source winget --accept-source-agreements --accept-package-agreements
    } elseif ($hasChoco) {
        choco install cmake --installargs 'ADD_CMAKE_TO_PATH=System' -y --no-progress
    }
    Refresh-Path
    Add-ToPath "C:\Program Files\CMake\bin"
}
$CMAKE_EXE = Get-SystemCmake
OK "CMake: $CMAKE_EXE ($(& $CMAKE_EXE --version | Select-Object -First 1))"

# --- 4. VISUAL STUDIO BUILD TOOLS ---
Log "Checking Visual Studio Build Tools"
$vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsFound = $false

if (Test-Path $vsWhere) {
    $vsJson = & $vsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json 2>$null
    if ($vsJson) {
        $vsInstalls = $vsJson | ConvertFrom-Json
        if ($vsInstalls) {
            $vsFound = $true
            OK "Visual Studio found: $($vsInstalls.displayName)"
        }
    }
}

if (-not $vsFound) {
    Log "Installing Visual Studio Build Tools 2022..."
    if ($useWinget) {
        winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget `
            --accept-source-agreements --accept-package-agreements `
            --override "--wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    } else {
        $vsBootstrap = "$env:TEMP\vs_buildtools.exe"
        Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vs_buildtools.exe" -OutFile $vsBootstrap -UseBasicParsing
        Start-Process -FilePath $vsBootstrap -ArgumentList @(
            "--quiet","--wait","--norestart","--nocache",
            "--add","Microsoft.VisualStudio.Workload.VCTools",
            "--add","Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "--add","Microsoft.VisualStudio.Component.Windows11SDK.22621",
            "--add","Microsoft.VisualStudio.Component.VC.CMake.Project"
        ) -Wait -NoNewWindow
    }
    Refresh-Path
    OK "Build Tools installed"
}

# --- 5. CUDA (only if BuildType = CUDA) ---
if ($BuildType -eq "CUDA") {
    Log "Checking CUDA Toolkit"
    $CUDA_BASE = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    $cudaFound = $false
    $nvccPaths = @(
        "$CUDA_BASE\v12.9\bin",
        "$CUDA_BASE\v12.8\bin",
        "$CUDA_BASE\v12.6\bin",
        "$CUDA_BASE\v12.4\bin",
        "$CUDA_BASE\v12.2\bin",
        "$CUDA_BASE\v12.0\bin",
        "$CUDA_BASE\v11.8\bin"
    )
    foreach ($p in $nvccPaths) { Add-ToPath $p }

    if (Is-Available "nvcc") {
        $cudaVer = nvcc --version 2>&1 | Select-String "release"
        OK "CUDA found: $cudaVer"
        $cudaFound = $true
    }

    if (-not $cudaFound) {
        WARN "CUDA not found! Please install CUDA Toolkit."
        WARN "Download: https://developer.nvidia.com/cuda-downloads"
        exit 1
    }

    # CUDA VS Integration
    Log "Setting up CUDA Visual Studio integration"
    $cudaInstallDir = $null
    if ($env:CUDA_PATH -and (Test-Path $env:CUDA_PATH)) {
        $cudaInstallDir = $env:CUDA_PATH
    } else {
        if (Test-Path $CUDA_BASE) {
            $latest = Get-ChildItem $CUDA_BASE | Sort-Object Name -Descending | Select-Object -First 1
            if ($latest) {
                $cudaInstallDir = $latest.FullName
                $env:CUDA_PATH = $cudaInstallDir
            }
        }
    }

    $cudaVsIntSrc = "$cudaInstallDir\extras\visual_studio_integration\MSBuildExtensions"
    $cudaPropsInstalled = $false
    
    if (Test-Path $cudaVsIntSrc) {
        # Find VS installation path using vswhere
        $vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
        $vsInstallPath = $null
        
        if (Test-Path $vsWhere) {
            $vsInstallPath = & $vsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
        }
        
        # Build target directories list
        $vsTargetDirs = @()
        
        # Add detected VS path first
        if ($vsInstallPath) {
            $vsVersion = & $vsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationVersion 2>$null
            $vsMajor = [int]($vsVersion.Split(".")[0])
            if ($vsMajor -ge 17) {
                $vsTargetDirs += Join-Path $vsInstallPath "MSBuild\Microsoft\VC\v170\BuildCustomizations"
            } elseif ($vsMajor -eq 16) {
                $vsTargetDirs += Join-Path $vsInstallPath "MSBuild\Microsoft\VC\v160\BuildCustomizations"
            } elseif ($vsMajor -eq 15) {
                $vsTargetDirs += Join-Path $vsInstallPath "MSBuild\Microsoft\VC\v150\BuildCustomizations"
            } elseif ($vsMajor -eq 14) {
                $vsTargetDirs += Join-Path $vsInstallPath "MSBuild\Microsoft\VC\v140\BuildCustomizations"
            }
        }
        
        # Add common paths as fallback (all versions)
        $vsTargetDirs += @(
            "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Microsoft\VC\v170\BuildCustomizations",
            "C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\MSBuild\Microsoft\VC\v170\BuildCustomizations",
            "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\MSBuild\Microsoft\VC\v160\BuildCustomizations",
            "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Microsoft\VC\v160\BuildCustomizations",
            "C:\Program Files (x86)\Microsoft Visual Studio\2017\BuildTools\MSBuild\Microsoft\VC\v150\BuildCustomizations",
            "C:\Program Files (x86)\Microsoft Visual Studio\2017\Community\MSBuild\Microsoft\VC\v150\BuildCustomizations",
            "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\MSBuild\Microsoft\VC\v170\BuildCustomizations",
            "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Microsoft\VC\v170\BuildCustomizations"
        )
        
        foreach ($target in $vsTargetDirs) {
            $vsBase = Split-Path (Split-Path (Split-Path (Split-Path $target)))
            if (Test-Path $vsBase) {
                try {
                    New-Item -ItemType Directory -Path $target -Force | Out-Null
                    Copy-Item "$cudaVsIntSrc\*" $target -Force -ErrorAction Stop
                    OK "CUDA Props -> $target"
                    $cudaPropsInstalled = $true
                    break
                } catch {
                    # Try with elevated privileges
                    Log "Requesting admin rights to copy CUDA props..."
                    $copyScript = @"
New-Item -ItemType Directory -Path '$target' -Force | Out-Null
Copy-Item '$cudaVsIntSrc\*' '$target' -Force
"@
                    $tempScript = [System.IO.Path]::GetTempFileName() + ".ps1"
                    $copyScript | Out-File -FilePath $tempScript -Encoding UTF8
                    
                    try {
                        $process = Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -File `"$tempScript`"" -Verb RunAs -Wait -PassThru
                        if ($process.ExitCode -eq 0) {
                            OK "CUDA Props -> $target (with admin rights)"
                            $cudaPropsInstalled = $true
                            break
                        }
                    } catch {
                        WARN "Could not copy to $target (admin rights denied)"
                    } finally {
                        Remove-Item $tempScript -Force -ErrorAction SilentlyContinue
                    }
                }
            }
        }
    } else {
        WARN "CUDA MSBuildExtensions not found at $cudaVsIntSrc"
    }
}

# --- 6. VULKAN (only if BuildType = Vulkan) ---
if ($BuildType -eq "Vulkan") {
    Log "Checking Vulkan SDK"
    $vulkanFound = $false

    if (Is-Available "glslangValidator") {
        OK "Vulkan SDK found (glslangValidator in PATH)"
        $vulkanFound = $true
    } elseif ($env:VULKAN_SDK -and (Test-Path "$env:VULKAN_SDK\Bin\glslangValidator.exe")) {
        Add-ToPath "$env:VULKAN_SDK\Bin"
        OK "Vulkan SDK found via VULKAN_SDK env ($env:VULKAN_SDK)"
        $vulkanFound = $true
    } else {
        foreach ($sdkBase in @("C:\VulkanSDK", "C:\Program Files\VulkanSDK")) {
            if (Test-Path $sdkBase) {
                $latestVer = Get-ChildItem $sdkBase -Directory | Sort-Object Name -Descending | Select-Object -First 1
                if ($latestVer -and (Test-Path "$($latestVer.FullName)\Bin\glslangValidator.exe")) {
                    $env:VULKAN_SDK = $latestVer.FullName
                    Add-ToPath "$($latestVer.FullName)\Bin"
                    OK "Vulkan SDK found at $($latestVer.FullName)"
                    $vulkanFound = $true
                    break
                }
            }
        }
    }

    if (-not $vulkanFound) {
        WARN "Vulkan SDK not found! Please install."
        WARN "Download: https://vulkan.lunarg.com/sdk/home"
        exit 1
    }

    # RDNA4 (Radeon RX 9000) needs SPIRV-Headers newer than the Vulkan SDK
    # ships. Build them from source once (cached under deps/) and feed the
    # install prefix to CMake via CMAKE_PREFIX_PATH.
    $spirvPrefix = Build-SpirvHeaders -DepsDir (Join-Path $scriptDir "deps")
}

# --- 6b. SYCL / Intel oneAPI (only if BuildType = SYCL) ---
$oneapiSetvarsPath = $null
if ($BuildType -eq "SYCL") {
    Log "Checking Intel oneAPI DPC++/C++ Compiler"
    $syclFound = $false

    # Find setvars.bat first (critical for SYCL environment)
    $oneapiPaths = @(
        "C:\Program Files (x86)\Intel\oneAPI",
        "C:\Program Files\Intel\oneAPI"
    )
    foreach ($oneapiBase in $oneapiPaths) {
        $setvars = Join-Path $oneapiBase "setvars.bat"
        if (Test-Path $setvars) {
            $oneapiSetvarsPath = $setvars
            OK "oneAPI setvars.bat found: $setvars"
            break
        }
    }

    if (Is-Available "icx") {
        OK "Intel oneAPI C++ found (icx in PATH)"
        $syclFound = $true
    } elseif (Is-Available "icpx") {
        OK "Intel oneAPI DPC++ found (icpx in PATH)"
        $syclFound = $true
    } else {
        foreach ($oneapiBase in $oneapiPaths) {
            if (Test-Path $oneapiBase) {
                $compilerDir = Join-Path $oneapiBase "compiler\latest\bin"
                if (Test-Path (Join-Path $compilerDir "icx.exe")) {
                    Add-ToPath $compilerDir
                    OK "Intel oneAPI found at $compilerDir"
                    $syclFound = $true
                    break
                }
                $compilerDir2 = Join-Path $oneapiBase "compiler\latest\windows\bin"
                if (Test-Path (Join-Path $compilerDir2 "icx.exe")) {
                    Add-ToPath $compilerDir2
                    OK "Intel oneAPI found at $compilerDir2"
                    $syclFound = $true
                    break
                }
            }
        }
    }

    if (-not $syclFound -and $oneapiSetvarsPath) {
        # Try sourcing setvars.bat and check again
        Log "Sourcing oneAPI environment via setvars.bat..."
        cmd.exe /c "`"$oneapiSetvarsPath`" intel64 >nul 2>&1 && set" | ForEach-Object {
            if ($_ -match "^(.+?)=(.*)$") {
                [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
            }
        }
        if (Is-Available "icx") {
            OK "icx found after sourcing setvars.bat"
            $syclFound = $true
        }
    }

    if (-not $syclFound) {
        WARN "Intel oneAPI DPC++/C++ Compiler not found!"
        WARN "Please install Intel oneAPI Base Toolkit."
        WARN "Download: https://www.intel.com/content/www/us/en/developer/tools/oneapi/base-toolkit-download.html"
        WARN "Or via winget: winget install Intel.oneAPI.BaseToolkit"
        exit 1
    }

    # Verify Ninja is available (required for SYCL builds)
    if (-not (Is-Available "ninja")) {
        Log "Installing Ninja (required for SYCL build)..."
        if ($useWinget) {
            winget install --id Ninja-build.Ninja -e --source winget --accept-source-agreements --accept-package-agreements
        } elseif ($hasChoco) {
            choco install ninja -y --no-progress
        }
        Refresh-Path
    }
    if (Is-Available "ninja") {
        OK "Ninja: $(ninja --version)"
    } else {
        WARN "Ninja not found! Required for SYCL builds."
        WARN "Install via: winget install Ninja-build.Ninja"
        exit 1
    }
}

# --- 7. FINAL CHECK ---
Log "Final check"
$allOk = $true
foreach ($cmd in @("git")) {
    if (Is-Available $cmd) {
        OK "$cmd OK"
    } else {
        WARN "$cmd MISSING"
        $allOk = $false
    }
}
if (-not $allOk) { exit 1 }
OK "cmake OK: $CMAKE_EXE"

# --- 8. CLONE REPO ---
Log "Checking $Source"
Set-Location $InstallDir

$existingDir = Get-ChildItem $InstallDir -Directory | Where-Object { $_.Name -match "^b\d+_$([regex]::Escape($DIR_SUFFIX))$" } | Sort-Object Name -Descending | Select-Object -First 1

if ($existingDir) {
    $dir = $existingDir.FullName
    OK "Found existing directory: $dir (skipping clone)"
} else {
    $tmpDir = Join-Path $InstallDir "_tmp_$Source"
    if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }

    if ($REPO_PR) {
        # PR-based source: clone the base repo, then fetch the pull request
        # ref into a local branch and check it out.
        Log "Fetching PR #$REPO_PR from $REPO_URL"
        git clone $REPO_URL $tmpDir
        if ($LASTEXITCODE -ne 0) { WARN "git clone failed"; exit 1 }
        Push-Location $tmpDir
        git fetch origin "pull/$REPO_PR/head:pr$REPO_PR"
        if ($LASTEXITCODE -ne 0) { WARN "git fetch PR #$REPO_PR failed"; Pop-Location; exit 1 }
        git checkout "pr$REPO_PR"
        if ($REPO_SUBMODULES) { git submodule update --init --recursive }
        $desc = git describe --tags --always 2>$null
        $ver  = [regex]::Match($desc, 'b\d+').Value
        if (-not $ver) { $ver = "pr$REPO_PR" }
        Pop-Location
    } else {
        $cloneArgs = @("clone", "--branch", $REPO_BRANCH)
        if ($REPO_SUBMODULES) { $cloneArgs += @("--recurse-submodules", "--shallow-submodules") }
        $cloneArgs += @($REPO_URL, $tmpDir)
        git @cloneArgs
        if ($LASTEXITCODE -ne 0) { WARN "git clone failed"; exit 1 }
        Push-Location $tmpDir
        $desc = git describe --tags --always 2>$null
        $ver  = [regex]::Match($desc, 'b\d+').Value
        if (-not $ver) { $ver = "bUNKNOWN" }
        Pop-Location
    }
    $dir = Join-Path $InstallDir "${ver}_$DIR_SUFFIX"
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    Rename-Item $tmpDir $dir
    OK "Directory: $dir"
}

# --- 9. CMAKE CONFIGURE ---
Log "CMake configuration ($BuildType)"
$buildDir = Join-Path $dir "build"

if (Test-Path $buildDir) {
    Log "Deleting old build directory..."
    Remove-Item $buildDir -Recurse -Force
}

# Create build directory
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

# If CUDA build and props were copied locally, copy them to build directory
if ($BuildType -eq "CUDA" -and $cudaInstallDir) {
    $cudaVsIntSrc = "$cudaInstallDir\extras\visual_studio_integration\MSBuildExtensions"
    if (Test-Path $cudaVsIntSrc) {
        Copy-Item "$cudaVsIntSrc\*" $buildDir -Force
        OK "CUDA props copied to build directory"
    }
}

# --- SYCL uses a completely different build process ---
if ($BuildType -eq "SYCL") {
    # Source oneAPI environment (CRITICAL for SYCL)
    if ($oneapiSetvarsPath) {
        Log "Sourcing Intel oneAPI environment..."
        cmd.exe /c "`"$oneapiSetvarsPath`" intel64 >nul 2>&1 && set" | ForEach-Object {
            if ($_ -match "^(.+?)=(.*)$") {
                [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
            }
        }
        OK "oneAPI environment loaded"
    }

    # Verify icx is now available
    if (-not (Is-Available "icx")) {
        WARN "icx compiler not found even after sourcing setvars.bat!"
        WARN "Please open 'Intel oneAPI command prompt' and verify icx is available."
        exit 1
    }

    # SYCL uses Ninja generator, NOT Visual Studio
    $cmakeFlags = @(
        "-S", $dir, "-B", $buildDir,
        "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_COMPILER=cl",
        "-DCMAKE_CXX_COMPILER=icx",
        "-DGGML_SYCL=ON",
        "-DGGML_SYCL_F16=ON",
        "-DGGML_NATIVE=OFF", "-DGGML_AVX2=ON", "-DGGML_FMA=ON", "-DGGML_F16C=ON",
        "-DBUILD_SHARED_LIBS=ON", "-DLLAMA_BUILD_SERVER=ON",
        "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"
    )

    Log "Starting SYCL build: $CMAKE_EXE $($cmakeFlags -join ' ')"
    & $CMAKE_EXE @cmakeFlags

    if ($LASTEXITCODE -ne 0) {
        WARN "CMake configuration failed! Code: $LASTEXITCODE"
        exit 1
    }
    OK "CMake configuration successful (SYCL/Ninja)"

    # Build
    Log "Compiling $Source with SYCL using $ParallelJobs jobs..."
    & $CMAKE_EXE --build $buildDir --parallel $ParallelJobs

    if ($LASTEXITCODE -ne 0) {
        WARN "Build failed! Code: $LASTEXITCODE"
        exit 1
    }

    # --- COPY SYCL RUNTIME DLLs ---
    # The built executables depend on oneAPI SYCL runtime DLLs that are NOT
    # placed next to the binaries automatically. Copy them so llama-server.exe
    # / llama-cli.exe start without "sycl8.dll not found" errors.
    Log "Copying Intel oneAPI SYCL runtime DLLs"
    $syclBin = Join-Path $buildDir "bin"
    Copy-SyclRuntimeDlls -TargetDir $syclBin | Out-Null

    # --- DONE ---
    Log "BUILD SUCCESSFUL! (SYCL)"
    $binPath = Join-Path $buildDir "bin"
    OK "Binaries: $binPath"
    $exes = Get-ChildItem $binPath -Filter "*.exe" -ErrorAction SilentlyContinue
    if ($exes) { $exes | ForEach-Object { OK "  $($_.Name)" } }
    Write-Host "`nStart server:" -ForegroundColor Green
    Write-Host "  $binPath\llama-server.exe -m <model.gguf> --host 0.0.0.0 --port 8080" -ForegroundColor Green
    exit 0
}

# --- Non-SYCL builds use Visual Studio generator ---
$vsWhere2 = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath2   = & $vsWhere2 -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
$vsVersion = & $vsWhere2 -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationVersion 2>$null

$vsMajor = [int]($vsVersion.Split(".")[0])
$vsGenerator = switch ($vsMajor) {
    18 { "Visual Studio 18 2026" }
    17 { "Visual Studio 17 2022" }
    16 { "Visual Studio 16 2019" }
    15 { "Visual Studio 15 2017" }
    14 { "Visual Studio 14 2015" }
    default { 
        # Für zukünftige Versionen: Verwende die gefundene Version
        "Visual Studio $vsMajor $($vsVersion.Split('.')[0])"
    }
}
OK "VS: $vsPath2 (v$vsVersion -> $vsGenerator)"

# Build the web UI from source when requested (before CMake configure,
# because LLAMA_USE_PREBUILT_UI=OFF expects the prebuilt assets present).
if ($BuildUi) {
    Build-WebUi -RepoDir $dir | Out-Null
}

# Build-specific flags. BUILD_SHARED_LIBS is chosen per backend:
#  - Vulkan (RDNA4): OFF (matches the proven static recipe)
#  - CUDA / HIP / CPU: ON
$cmakeFlags = @(
    "-S", $dir, "-B", $buildDir,
    "-G", $vsGenerator, "-A", "x64",
    "-DCMAKE_BUILD_TYPE=Release",
    "-DGGML_NATIVE=OFF", "-DGGML_AVX2=ON", "-DGGML_FMA=ON", "-DGGML_F16C=ON",
    "-DLLAMA_BUILD_SERVER=ON",
    "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"
)

if ($BuildType -eq "CUDA") {
    $cmakeFlags += @("-DGGML_CUDA=ON", "-DGGML_VULKAN=OFF", "-DBUILD_SHARED_LIBS=ON")
    
    # Set CUDA toolkit path explicitly
    if ($cudaInstallDir) {
        $cmakeFlags += "-DCUDAToolkit_ROOT=$cudaInstallDir"
        $cmakeFlags += "-DCUDA_TOOLKIT_ROOT_DIR=$cudaInstallDir"
        
        # If CUDA props were copied locally, copy them to the build directory
        $localCudaProps = Join-Path $buildDir "CUDA_Props"
        if (Test-Path $localCudaProps) {
            # Copy CUDA props to build directory for CMake to find
            Copy-Item "$localCudaProps\*" $buildDir -Force
            OK "CUDA props copied to build directory"
        }
    }
} elseif ($BuildType -eq "Vulkan") {
    # RDNA4 (Radeon RX 9000) Vulkan recipe: Vulkan backend + recent
    # SPIRV-Headers prefix + ASM/CMP0194 workarounds (llama.cpp #22100).
    $cmakeFlags += @(
        "-DGGML_VULKAN=ON",
        "-DGGML_CUDA=OFF",
        "-DGGML_VULKAN_CHECK_RESULTS=OFF",
        "-DCMAKE_POLICY_DEFAULT_CMP0194=OLD",
        "-DCMAKE_ASM_COMPILER=cl",
        "-DBUILD_SHARED_LIBS=OFF"
    )
    if ($spirvPrefix) {
        $cmakeFlags += "-DCMAKE_PREFIX_PATH=$spirvPrefix"
        OK "Using SPIRV-Headers prefix: $spirvPrefix"
    }
    if ($BuildUi) {
        $cmakeFlags += @("-DLLAMA_BUILD_UI=ON", "-DLLAMA_USE_PREBUILT_UI=OFF")
    }
} elseif ($BuildType -eq "HIP") {
    $cmakeFlags += @("-DGGML_HIP=ON", "-DGGML_CUDA=OFF", "-DBUILD_SHARED_LIBS=ON")
} else {
    # CPU
    $cmakeFlags += @("-DGGML_CUDA=OFF", "-DGGML_VULKAN=OFF", "-DBUILD_SHARED_LIBS=ON")
}

Log "Starting: $CMAKE_EXE $($cmakeFlags -join ' ')"
& $CMAKE_EXE @cmakeFlags

if ($LASTEXITCODE -ne 0) {
    WARN "CMake configuration failed! Code: $LASTEXITCODE"
    exit 1
}
OK "CMake configuration successful"

# --- 10. BUILD ---
Log "Compiling $Source with $BuildType using $ParallelJobs jobs..."
& $CMAKE_EXE --build $buildDir --config Release --parallel $ParallelJobs

if ($LASTEXITCODE -ne 0) {
    WARN "Build failed! Code: $LASTEXITCODE"
    exit 1
}

# --- DONE ---
Log "BUILD SUCCESSFUL!"
$binPath = Join-Path $buildDir "bin\Release"
OK "Binaries: $binPath"
$exes = Get-ChildItem $binPath -Filter "*.exe" -ErrorAction SilentlyContinue
if ($exes) { $exes | ForEach-Object { OK "  $($_.Name)" } }
Write-Host "`nStart server:" -ForegroundColor Green
Write-Host "  $binPath\llama-server.exe -m <model.gguf> --host 0.0.0.0 --port 8080" -ForegroundColor Green
