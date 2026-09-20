# Universal llama.cpp Build Script (Windows)
# Supports all sources and build types
#
# Usage:
#   .\build_llamacpp.ps1 -Source main -BuildType CPU
#   .\build_llamacpp.ps1 -Source turboquant -BuildType CUDA -CudaMajor 12
#   .\build_llamacpp.ps1 -Source ternary_bonsai -BuildType Vulkan -CpuTarget native
#
# Output: <InstallDir>\<bNNNN>_<backend>_<DirSuffix>\build\bin\Release\llama-server.exe
# bNNNN is "git rev-list --count HEAD", i.e. exactly the build number that
# llama-server --version reports, so the folder name never lies.

param(
    [Parameter(Mandatory=$true)]
    [string]$Source,

    [Parameter(Mandatory=$true)]
    [ValidateSet("CPU", "CUDA", "Vulkan", "HIP", "SYCL", "Metal")]
    [string]$BuildType,

    [string]$InstallDir = "",
    [string]$BuildDir = "",
    [string]$DepsDir = "",
    [int]$ParallelJobs = 0,
    [ValidateSet("portable", "native")]
    [string]$CpuTarget = "portable",
    [string]$CudaMajor = "",
    [string]$Targets = "",
    [switch]$BuildUi,   # force LLAMA_BUILD_UI=ON (npm)
    [switch]$Update,
    [switch]$CleanBuild,
    [string]$ExtraFlags = "",
    [string]$ExtraFlagsBase64 = "",
    [string]$RepoUrl = "",
    [string]$RepoBranch = "",
    [string]$DirSuffix = "",
    [string]$SourceCommit = "",
    [string]$FetchRef = "",
    [int]$RepoPr = 0,
    [switch]$RepoSubmodules
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

# The GUI reads our output as UTF-8. Make PowerShell emit UTF-8 so umlauts in
# MSBuild/CMake messages do not turn into mojibake.
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {}

# Do not keep MSBuild node processes alive after the build. Lingering nodes
# hold file handles that prevent cleaning up the checkout afterwards.
$env:MSBUILDDISABLENODEREUSE = "1"

# Directory containing this script (needed for the deps/ cache even when
# InstallDir is passed explicitly by the GUI).
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrEmpty($InstallDir)) { $InstallDir = Join-Path $scriptDir "builds" }
if ([string]::IsNullOrEmpty($DepsDir))    { $DepsDir    = Join-Path $scriptDir "deps" }

if ($ParallelJobs -le 0) {
    $ParallelJobs = [int]$env:NUMBER_OF_PROCESSORS
    if ($ParallelJobs -le 0) { $ParallelJobs = 4 }
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
        Branch = "master"
        Suffix = "tq_llama.cpp"
    }
    "ternary_bonsai" = @{
        Url = "https://github.com/PrismML-Eng/llama.cpp.git"
        Branch = "prism"
        Suffix = "2b_llama.cpp"
    }
    "ocr_llama" = @{
        Url = "https://github.com/ggml-org/llama.cpp.git"
        Branch = "master"
        PR = 17400
        Suffix = "ocr_llama.cpp"
    }
    "diffusion_gemma" = @{
        Url = "https://github.com/ggml-org/llama.cpp.git"
        Branch = "master"
        PR = 24427
        Suffix = "d_llama.cpp"
    }
}

$config = $sourceConfig[$Source]
if (-not $config -and [string]::IsNullOrWhiteSpace($RepoUrl)) {
    Write-Host "Unknown source '$Source' and no repository URL was provided." -ForegroundColor Red
    exit 1
}
$REPO_URL = if ($RepoUrl) { $RepoUrl } else { $config.Url }
$REPO_BRANCH = if ($RepoBranch) { $RepoBranch } else { $config.Branch }
$DIR_SUFFIX = if ($DirSuffix) { $DirSuffix } elseif ($config) { $config.Suffix } else { "${Source}_llama.cpp" }
$REPO_PR = if ($RepoPr -gt 0) { $RepoPr } elseif ($config) { $config.PR } else { $null }
$REPO_SUBMODULES = if ($RepoSubmodules) { $true } elseif ($config) { $config.Submodules } else { $false }

function Assert-VulkanPathBudget {
    param([string]$Root, [string]$Backend, [string]$Suffix = "llama.cpp",
          [string]$ActualBuildDir = "")
    if ($Backend -ne "Vulkan") { return }
    # Keep the representative suffix and 250-character budget in sync with
    # app_settings.py. Reserve ten version digits and the collision timestamp.
    $rootPath = [IO.Path]::GetFullPath($Root)
    if (-not $ActualBuildDir) {
        $ActualBuildDir = [IO.Path]::Combine($rootPath, "b0000000000_run_000000000000000000000_vulkan_$Suffix\build")
    }
    $ActualBuildDir = [IO.Path]::GetFullPath($ActualBuildDir)
    $nested = 'ggml\src\ggml-vulkan\vulkan-shaders-gen-prefix\src\vulkan-shaders-gen-build\CMakeFiles\CMakeScratch\TryCompile-XXXXXX\cmTC_XXXXX.dir\Debug\cmTC_XXXXX.tlog\link-cvtres.write.1.tlog'
    $length = ([IO.Path]::Combine($ActualBuildDir, $nested)).Length
    if ($length -gt 250) {
        throw "Windows/Vulkan path budget exceeded: $length/250 characters. Output root: $rootPath. Build directory: $ActualBuildDir. Nested MSBuild/FileTracker paths can fail with FTK1011/MSB8066. Select a shorter output root, for example C:\b, and configure a fresh build. Do not copy an old CMake cache. Existing outputs have not been moved or deleted."
    }
}

# Resolve explicit paths before any later Set-Location changes their meaning.
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
if ($BuildDir) { $BuildDir = [IO.Path]::GetFullPath($BuildDir) }
Assert-VulkanPathBudget -Root $InstallDir -Backend $BuildType -Suffix $DIR_SUFFIX -ActualBuildDir $BuildDir

# Metal is a macOS-only backend. Bail out early with guidance on Windows.
if ($BuildType -eq "Metal") {
    Write-Host "Metal backend is only available on macOS (Apple Silicon)." -ForegroundColor Red
    Write-Host "On Windows, choose CUDA (NVIDIA), Vulkan, HIP (AMD) or SYCL (Intel) instead." -ForegroundColor Yellow
    exit 1
}

function ConvertFrom-EncodedCMakeFlags {
    param([string]$Value)
    if (-not $Value) { return }
    foreach ($encodedFlag in ($Value -split ",")) {
        if (-not $encodedFlag) { continue }
        try {
            $decodedFlag = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedFlag)).Trim()
        } catch {
            throw "Invalid encoded CMake profile flag: $($_.Exception.Message)"
        }
        if ($decodedFlag) { $decodedFlag }
    }
}

# Parse extra CMake flags. User-supplied flags are appended last so they take
# precedence over defaults. ExtraFlags remains available for direct CLI use;
# the GUI uses the encoded form so every list item survives as one argument.
$extraFlagList = @()
if ($ExtraFlags) {
    $extraFlagList = $ExtraFlags -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}
if ($ExtraFlagsBase64) {
    $extraFlagList += @(ConvertFrom-EncodedCMakeFlags -Value $ExtraFlagsBase64)
}
$targetList = @()
if ($Targets) {
    $targetList = $Targets -split "[,;\s]+" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

function Test-ExtraFlag($prefix) {
    foreach ($f in $extraFlagList) { if ($f -like "$prefix*") { return $true } }
    return $false
}

# --- HELPER FUNCTIONS ---
function Log($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function WARN($msg) { Write-Host "    [!!] $msg" -ForegroundColor Yellow }

function Remove-PathWithRetry {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [int]$Retries = 8,
        [int]$DelayMs = 500
    )

    if (-not (Test-Path -LiteralPath $Path)) { return }

    for ($i = 1; $i -le $Retries; $i++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($i -eq $Retries) { throw }
            WARN "Could not remove '$Path' yet (attempt $i/$Retries): $($_.Exception.Message)"
            Start-Sleep -Milliseconds $DelayMs
        }
    }
}

function Move-PathWithRetry {
    param(
        [Parameter(Mandatory=$true)][string]$Source,
        [Parameter(Mandatory=$true)][string]$Destination,
        [int]$Retries = 8,
        [int]$DelayMs = 500
    )

    $sourceFull = [System.IO.Path]::GetFullPath($Source)
    $destinationFull = [System.IO.Path]::GetFullPath($Destination)
    $sourceParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $sourceFull))
    $destinationParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $destinationFull))

    for ($i = 1; $i -le $Retries; $i++) {
        try {
            if ($sourceParent -eq $destinationParent) {
                Rename-Item -LiteralPath $sourceFull -NewName (Split-Path -Leaf $destinationFull) -ErrorAction Stop
            } else {
                Move-Item -LiteralPath $sourceFull -Destination $destinationFull -Force -ErrorAction Stop
            }
            return
        } catch {
            if ($i -eq $Retries) { break }
            WARN "Could not move '$Source' to '$Destination' yet (attempt $i/$Retries): $($_.Exception.Message)"
            Start-Sleep -Milliseconds $DelayMs
        }
    }

    WARN "Move failed after $Retries attempts; falling back to robocopy."
    New-Item -ItemType Directory -Path $destinationFull -Force | Out-Null
    $robocopyArgs = @($sourceFull, $destinationFull, "/MIR", "/COPY:DAT", "/DCOPY:DAT", "/R:5", "/W:1", "/NFL", "/NDL", "/NP")
    & robocopy @robocopyArgs | Out-Null
    $code = $LASTEXITCODE
    if ($code -gt 7) {
        throw "robocopy fallback failed with exit code $code while copying '$sourceFull' to '$destinationFull'."
    }
    try {
        Remove-PathWithRetry $sourceFull -Retries 12 -DelayMs $DelayMs
    } catch {
        WARN "Copied to '$Destination', but cleanup of temporary directory '$Source' is still blocked: $($_.Exception.Message)"
    }
}

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

function Invoke-Native {
    # Run a native command and return its text output without letting stderr
    # chatter become a terminating error (PowerShell 5.1 + ErrorActionPreference Stop).
    param([Parameter(Mandatory=$true)][scriptblock]$Command)
    $prev = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $out = @(& $Command 2>&1 | ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { [string]$_.Exception.Message } else { [string]$_ } })
        $script:LastNativeExit = $LASTEXITCODE
        return ($out -join "`n").Trim()
    } finally {
        $ErrorActionPreference = $prev
    }
}

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$useWinget = $false

function Get-SystemCmake {
    $candidates = Get-Command cmake -All -ErrorAction SilentlyContinue
    foreach ($c in $candidates) {
        if ($c.Source -notlike "*Visual Studio*") {
            return $c.Source
        }
    }
    return (Get-Command cmake -ErrorAction SilentlyContinue).Source
}

function Get-VsWhere {
    $vsw = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vsw) { return $vsw }
    return $null
}

function Get-VsInstance {
    # Newest Visual Studio with the C++ x64 toolset: path, version, generator name.
    $vsw = Get-VsWhere
    if (-not $vsw) { return $null }
    $json = Invoke-Native { & $vsw -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json }
    if (-not $json) { return $null }
    try { $inst = @($json | ConvertFrom-Json)[0] } catch { return $null }
    if (-not $inst) { return $null }
    $version = [string]$inst.installationVersion
    $major = [int]($version.Split(".")[0])
    $generator = switch ($major) {
        18 { "Visual Studio 18 2026" }
        17 { "Visual Studio 17 2022" }
        16 { "Visual Studio 16 2019" }
        15 { "Visual Studio 15 2017" }
        14 { "Visual Studio 14 2015" }
        default { "Visual Studio $major" }
    }
    return [PSCustomObject]@{
        Path = [string]$inst.installationPath
        Version = $version
        Major = $major
        Generator = $generator
        DisplayName = [string]$inst.displayName
    }
}

function Import-VsDevEnvironment {
    # Import the x64 developer environment (INCLUDE/LIB/PATH) of the given
    # Visual Studio into this process. Needed for Ninja-based builds (HIP,
    # SYCL) so clang/icx find the MSVC headers and libraries.
    param([Parameter(Mandatory=$true)][string]$VsInstallPath)
    $vsDevCmd = Join-Path $VsInstallPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path $vsDevCmd)) { WARN "VsDevCmd.bat not found: $vsDevCmd"; return $false }
    $rows = & $env:ComSpec /d /s /c "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
    if ($LASTEXITCODE -ne 0) { WARN "VsDevCmd.bat failed with exit code $LASTEXITCODE"; return $false }
    foreach ($row in $rows) {
        if ($row -match '^([^=]+)=(.*)$') {
            Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2]
        }
    }
    OK "Imported Visual Studio x64 build environment"
    return $true
}

function Resolve-NinjaPath {
    # Ninja from PATH, else the copy every Visual Studio ships with its CMake tools.
    param([string]$VsInstallPath = "")
    $found = Get-Command ninja -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    if ($VsInstallPath) {
        $candidate = Join-Path $VsInstallPath "Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
        if (Test-Path $candidate) {
            Add-ToPath (Split-Path -Parent $candidate)
            return $candidate
        }
    }
    return $null
}

function Resolve-OneApiCompilerBin {
    # Resolve the Intel oneAPI compiler directory holding the SYCL runtime
    # DLLs (sycl*.dll, pi_*.dll, intel-ext*.dll, umf*.dll). Prefer env vars
    # exported by setvars.bat, then scan common install locations, including
    # the redist tree used by newer oneAPI releases.
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

function Copy-SyclRuntimeDlls {
    # Copy Intel oneAPI SYCL runtime DLLs next to the built executables.
    # Without these the binaries fail to start with errors like
    # "sycl8.dll not found" / "pi_win_proxy_loader.dll not found".
    param([Parameter(Mandatory=$true)][string]$TargetDir)

    $src = Resolve-OneApiCompilerBin
    if (-not $src) {
        WARN "Could not locate oneAPI compiler DLL directory."
        WARN "SYCL runtime DLLs were NOT copied - binaries may fail to start."
        WARN "Run from the 'Intel oneAPI command prompt', or copy the DLLs from"
        WARN "<oneAPI>\compiler\<version>\bin manually into: $TargetDir"
        return $false
    }

    if (-not (Test-Path $TargetDir)) { New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null }

    $patterns = @("sycl*.dll", "pi_*.dll", "intel-ext*.dll", "umf*.dll",
                  "libsycl*.dll", "sycl_*.dll", "ocloc*.dll")
    $copied = 0
    $copiedNames = @()
    foreach ($pat in $patterns) {
        Get-ChildItem -Path $src -Filter $pat -File -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Item $_.FullName -Destination $TargetDir -Force -ErrorAction SilentlyContinue
            if ($?) { $copied++; $copiedNames += $_.Name }
        }
    }

    if ($copied -gt 0) {
        OK "Copied $copied oneAPI SYCL runtime DLL(s):"
        $copiedNames | Select-Object -Unique | ForEach-Object { OK "  $_" }
        OK "  from $src"
        OK "  into $TargetDir"
        return $true
    } else {
        WARN "No SYCL runtime DLLs found to copy in $src"
        return $false
    }
}

function Resolve-MsvcClPath {
    # Return the full path to the x64 MSVC compiler. CMake's ASM language check
    # does not reliably resolve a bare "cl" when the script was launched from a
    # normal PowerShell instead of a Developer Prompt.
    param([Parameter(Mandatory=$true)][string]$VsInstallPath)

    $defaultVersionFile = Join-Path $VsInstallPath "VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt"
    if (Test-Path -LiteralPath $defaultVersionFile) {
        $toolVersion = (Get-Content -LiteralPath $defaultVersionFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($toolVersion) {
            $candidate = Join-Path $VsInstallPath "VC\Tools\MSVC\$toolVersion\bin\Hostx64\x64\cl.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }

    $toolsRoot = Join-Path $VsInstallPath "VC\Tools\MSVC"
    if (Test-Path -LiteralPath $toolsRoot) {
        $latest = Get-ChildItem -LiteralPath $toolsRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($latest) {
            $candidate = Join-Path $latest.FullName "bin\Hostx64\x64\cl.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }

    return $null
}

function Build-SpirvHeaders {
    # Build Khronos SPIRV-Headers from source into a local install prefix.
    # RDNA4 (Radeon RX 9000) requires a very recent SPIRV-Headers (shipped with
    # SPV_KHR_cooperative_matrix etc.) that is usually newer than the Vulkan
    # SDK's bundled copy. The install dir is cached, so this only runs once.
    param(
        [Parameter(Mandatory=$true)][string]$DepsDir,
        [Parameter(Mandatory=$true)][string]$Generator
    )

    $spirvSrc  = Join-Path $DepsDir "SPIRV-Headers"
    $spirvBld  = Join-Path $spirvSrc "build"
    $spirvInst = Join-Path $spirvSrc "install"
    # SPIRV-Headers installs include\spirv\unified1\spirv.hpp (not include\spirv\spirv.hpp).
    $marker    = Join-Path $spirvInst "include\spirv\unified1\spirv.hpp"
    $cmakeCfg  = Join-Path $spirvInst "share\cmake\SPIRV-Headers\SPIRV-HeadersConfig.cmake"

    if ((Test-Path $marker) -and (Test-Path $cmakeCfg)) {
        OK "SPIRV-Headers already installed: $spirvInst"
        return $spirvInst
    }
    if (-not (Is-Available "git")) {
        WARN "git not available - cannot build SPIRV-Headers"
        return $null
    }

    Log "Building SPIRV-Headers from source (RDNA4 / recent Vulkan support)"
    # IMPORTANT: route native command output to the host (Out-Host). Anything
    # written to the success stream inside this function would be captured by
    # "$spirvPrefix = Build-SpirvHeaders ..." and corrupt the returned path.
    if (-not (Test-Path (Join-Path $spirvSrc ".git"))) {
        if (Test-Path $spirvSrc) { Remove-PathWithRetry $spirvSrc }
        git clone --depth 1 https://github.com/KhronosGroup/SPIRV-Headers.git $spirvSrc | Out-Host
        if ($LASTEXITCODE -ne 0) { WARN "SPIRV-Headers clone failed"; return $null }
    }
    New-Item -ItemType Directory -Path $spirvBld -Force | Out-Null

    $cfgFlags = @("-S", $spirvSrc, "-B", $spirvBld, "-G", $Generator, "-A", "x64",
                  "-DCMAKE_INSTALL_PREFIX=$spirvInst", "-DSPIRV_HEADERS_ENABLE_TESTS=OFF")
    & $CMAKE_EXE @cfgFlags | Out-Host
    if ($LASTEXITCODE -ne 0) { WARN "SPIRV-Headers configure failed"; return $null }
    & $CMAKE_EXE --build $spirvBld --config Release | Out-Host
    if ($LASTEXITCODE -ne 0) { WARN "SPIRV-Headers build failed"; return $null }
    & $CMAKE_EXE --install $spirvBld --config Release | Out-Host
    if ($LASTEXITCODE -ne 0) { WARN "SPIRV-Headers install failed"; return $null }

    OK "SPIRV-Headers installed to $spirvInst"
    return $spirvInst
}

function Resolve-HipRoot {
    # Resolve the AMD HIP SDK root (the folder holding bin\clang.exe).
    # CMake's HIP language is not supported on Windows, so ggml-hip forces the
    # hipcc/clang compiler path - we must point CMAKE_C/CXX_COMPILER at it.
    $candidates = @()
    foreach ($v in @($env:HIP_PATH, $env:ROCM_PATH)) {
        if ($v) { $candidates += $v.TrimEnd('\') }
    }
    foreach ($base in @("C:\Program Files\AMD\ROCm", "C:\AMD\ROCm")) {
        if (Test-Path $base) {
            Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
                Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending |
                ForEach-Object { $candidates += $_.FullName }
        }
    }
    foreach ($c in $candidates) {
        if ((Test-Path $c) -and (Test-Path (Join-Path $c "bin\clang.exe"))) {
            return $c
        }
    }
    return $null
}

function Get-AmdGfxTarget {
    # Detect the installed AMD GPU gfx target(s) for HIP builds (e.g. gfx1201).
    # hipInfo.exe ships with the Windows HIP SDK; rocminfo is Linux-only.
    param([string]$HipRoot = "")
    $targets = @()
    $hipInfo = if ($HipRoot -and (Test-Path (Join-Path $HipRoot "bin\hipInfo.exe"))) { Join-Path $HipRoot "bin\hipInfo.exe" } elseif (Is-Available "hipInfo") { "hipInfo" } else { $null }
    if ($hipInfo) {
        $out = Invoke-Native { & $hipInfo }
        foreach ($m in [regex]::Matches($out, 'gcnArchName:\s*(gfx[0-9a-f]+)')) {
            $t = $m.Groups[1].Value
            if ($targets -notcontains $t) { $targets += $t }
        }
    }
    if ($targets.Count -eq 0) {
        foreach ($tool in @("rocm_agent_enumerator", "rocminfo")) {
            if (Is-Available $tool) {
                $out = Invoke-Native { & $tool }
                foreach ($m in [regex]::Matches($out, '\b(gfx[0-9a-f]{3,5})\b')) {
                    $t = $m.Groups[1].Value
                    if ($t -ne "gfx000" -and $targets -notcontains $t) { $targets += $t }
                }
            }
        }
    }
    if ($targets.Count -eq 0) { return $null }
    return ($targets -join ";")
}

function Get-HipCompatibilityResourceDir {
    # HIP SDK <= 7.2 clang headers declare __device__ cmath overloads AFTER MSVC's
    # <cmath> (14.5x) created implicit host+device constexpr overloads, so every
    # HIP TU fails with "cannot overload __host__ __device__ function" (fixed
    # upstream in LLVM PR #201563). Keep Program Files pristine: copy clang's
    # resource tree into deps/ and apply the upstream include reorder there,
    # then pass that private tree via -resource-dir. Returns "" when the
    # installed headers are already fixed.
    param(
        [Parameter(Mandatory=$true)][string]$Clang,
        [Parameter(Mandatory=$true)][string]$HipRoot,
        [Parameter(Mandatory=$true)][string]$DepsDir
    )
    $resourceDir = Invoke-Native { & $Clang -print-resource-dir }
    if (-not $resourceDir -or -not (Test-Path $resourceDir)) { return "" }
    $wrapper = Join-Path $resourceDir "include\__clang_hip_runtime_wrapper.h"
    if (-not (Test-Path $wrapper)) { return "" }
    $forwardInclude = "#include <__clang_cuda_math_forward_declares.h>"
    $cmathInclude = "#include <cmath>"
    $sourceText = Get-Content $wrapper -Raw
    $forwardIndex = $sourceText.IndexOf($forwardInclude, [StringComparison]::Ordinal)
    $cmathIndex = $sourceText.IndexOf($cmathInclude, [StringComparison]::Ordinal)
    if ($forwardIndex -lt 0 -or $cmathIndex -lt 0 -or $forwardIndex -lt $cmathIndex) {
        return ""   # already in the fixed order (or a layout we do not understand)
    }

    $hipVersion = Split-Path $HipRoot -Leaf
    $clangVersion = Split-Path $resourceDir -Leaf
    $patchedDir = Join-Path $DepsDir "toolchains\hip-${hipVersion}-clang-${clangVersion}-llvm-pr201563"
    $patchedWrapper = Join-Path $patchedDir "include\__clang_hip_runtime_wrapper.h"
    $sha = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.IO.File]::ReadAllBytes($wrapper))).Replace("-", "")
    $markerFile = Join-Path $patchedDir ".source-sha256"
    $reuse = $false
    if ((Test-Path $patchedWrapper) -and (Test-Path $markerFile)) {
        $reuse = ((Get-Content $markerFile -Raw).Trim() -eq $sha)
    }
    if (-not $reuse) {
        if (Test-Path $patchedDir) { Remove-PathWithRetry $patchedDir }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $patchedDir) | Out-Null
        Copy-Item -LiteralPath $resourceDir -Destination $patchedDir -Recurse -Force
        $newline = if ($sourceText.Contains("`r`n")) { "`r`n" } else { "`n" }
        $withoutLate = [regex]::Replace($sourceText, '(?m)^#include <__clang_cuda_math_forward_declares\.h>\r?\n', '')
        $patched = ([regex]'(?m)^(#if !defined\(__HIPCC_RTC__\)\r?\n)').Replace($withoutLate, ('$1' + $forwardInclude + $newline), 1)
        if ($patched -eq $withoutLate) {
            WARN "Could not apply the HIP cmath header fix (unexpected wrapper layout); building with stock headers."
            return ""
        }
        [System.IO.File]::WriteAllText($patchedWrapper, $patched, [System.Text.UTF8Encoding]::new($false))
        Set-Content -LiteralPath $markerFile -Value $sha -NoNewline -Encoding ascii
    }
    OK "Applied HIP cmath header fix (LLVM PR #201563): $patchedDir"
    return $patchedDir.Replace('\', '/')
}

function Copy-HipRuntimeDependencies {
    # Bundle the ROCm runtime DLLs next to the executables and link the Tensile
    # kernel libraries (rocblas/, hipblaslt/) so the folder works without ROCm
    # in PATH. Junctions avoid duplicating ~1 GiB per build.
    param(
        [Parameter(Mandatory=$true)][string]$BinDir,
        [Parameter(Mandatory=$true)][string]$HipRoot
    )
    $src = Join-Path $HipRoot "bin"
    $copied = 0
    foreach ($pattern in @("amdhip64_*.dll", "amd_comgr_*.dll", "hipblas.dll", "rocblas.dll", "hipblaslt.dll", "rocm_kpack.dll", "hiprtc*.dll")) {
        Get-ChildItem -Path $src -Filter $pattern -File -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Item $_.FullName -Destination $BinDir -Force
            $copied++
        }
    }
    foreach ($dirName in @("rocblas", "hipblaslt")) {
        $srcDir = Join-Path $src $dirName
        $dstDir = Join-Path $BinDir $dirName
        if (-not (Test-Path $srcDir)) { continue }
        if (Test-Path $dstDir) { continue }
        try {
            New-Item -ItemType Junction -Path $dstDir -Target $srcDir | Out-Null
        } catch {
            WARN "Could not link $dirName kernels ($($_.Exception.Message)); copying instead."
            Copy-Item -LiteralPath $srcDir -Destination $dstDir -Recurse -Force
        }
    }
    OK "Bundled $copied ROCm runtime DLL(s) from $src"
}

function Deploy-CudaRuntimeDlls {
    param(
        [Parameter(Mandatory=$true)][string]$CudaBin,
        [Parameter(Mandatory=$true)][string]$Destination
    )
    # New toolkits separate x64 and ARM64 DLLs; this script builds x64.
    $x64Bin = Join-Path $CudaBin "x64"
    if (Test-Path -LiteralPath $x64Bin -PathType Container) { $CudaBin = $x64Bin }
    if (-not (Test-Path -LiteralPath $CudaBin -PathType Container)) {
        throw "CUDA runtime directory not found: $CudaBin"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $required = @("cudart64_*.dll", "cublas64_*.dll", "cublasLt64_*.dll")
    # Validate the selected toolkit, so stale destination DLLs cannot mask an
    # incomplete SDK. JIT/NVRTC dependencies are deployed when supplied by it.
    foreach ($pattern in $required) {
        if (-not (Get-ChildItem -LiteralPath $CudaBin -Filter $pattern -File)) {
            throw "Required CUDA runtime DLL missing from ${CudaBin}: $pattern"
        }
    }
    $copied = 0
    foreach ($pattern in ($required + @("nvJitLink_*.dll", "nvrtc64_*.dll", "nvrtc-builtins64_*.dll"))) {
        foreach ($dll in (Get-ChildItem -LiteralPath $CudaBin -Filter $pattern -File)) {
            Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $Destination $dll.Name) -Force
            $copied++
        }
    }
    OK "Bundled $copied CUDA runtime DLL(s) from $CudaBin"
}

function Get-CudaToolkits {
    # All installed CUDA toolkits, newest first (numeric sort, not string sort).
    $base = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    $list = @()
    if (Test-Path $base) {
        Get-ChildItem $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Name -match '^v(\d+)\.(\d+)') {
                $list += [PSCustomObject]@{ Path = $_.FullName; Version = [version]"$($Matches[1]).$($Matches[2])"; Major = [int]$Matches[1] }
            }
        }
    }
    if ($env:CUDA_PATH -and (Test-Path $env:CUDA_PATH) -and -not ($list | Where-Object { $_.Path -eq $env:CUDA_PATH })) {
        $verText = Invoke-Native { & (Join-Path $env:CUDA_PATH "bin\nvcc.exe") --version }
        if ($verText -match 'release\s+(\d+)\.(\d+)') {
            $list += [PSCustomObject]@{ Path = $env:CUDA_PATH; Version = [version]"$($Matches[1]).$($Matches[2])"; Major = [int]$Matches[1] }
        }
    }
    return @($list | Where-Object { Test-Path (Join-Path $_.Path "bin\nvcc.exe") } | Sort-Object Version -Descending)
}

function Get-NvidiaInfo {
    # Driver-supported CUDA version and compute capabilities from nvidia-smi.
    $info = [PSCustomObject]@{ DriverCuda = $null; ComputeCaps = @(); Names = @() }
    if (-not (Is-Available "nvidia-smi")) { return $info }
    $banner = Invoke-Native { & nvidia-smi }
    if ($banner -match 'CUDA Version:\s*(\d+\.\d+)') { $info.DriverCuda = [version]$Matches[1] }
    $csv = Invoke-Native { & nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader }
    if ($script:LastNativeExit -eq 0 -and $csv) {
        foreach ($line in ($csv -split "`n")) {
            $parts = $line -split ","
            if ($parts.Count -ge 2 -and $parts[1].Trim() -match '^\d+\.\d+$') {
                $info.Names += $parts[0].Trim()
                $info.ComputeCaps += $parts[1].Trim()
            }
        }
    }
    return $info
}

# --- 0. INSTALL DIRECTORY ---
Log "Creating install directory $InstallDir"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}
OK $InstallDir

# --- 1. PACKAGE MANAGER (used only for missing prerequisites) ---
Log "Checking package manager"
$hasChoco = Is-Available "choco"
$hasWingetPkg = Is-Available "winget"
if ($hasWingetPkg) {
    $useWinget = $true
    OK "winget available (used for missing prerequisites)"
} elseif ($hasChoco) {
    OK "Chocolatey: $(choco --version)"
} else {
    WARN "No package manager found (winget/choco). Missing prerequisites must be installed manually."
}
if (-not $isAdmin) { Write-Host "    INFO: not running as Administrator (not required)." -ForegroundColor DarkGray }

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
}
if (-not (Is-Available "git")) { WARN "git is required: https://git-scm.com/download/win"; exit 1 }
OK "Git: $(git --version)"

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
if (-not $CMAKE_EXE) { WARN "cmake is required: https://cmake.org/download/"; exit 1 }
$cmakeVersionText = (& $CMAKE_EXE --version | Select-Object -First 1)
OK "CMake: $CMAKE_EXE ($cmakeVersionText)"
$cmakeVersion = if ($cmakeVersionText -match '(\d+)\.(\d+)') { [version]"$($Matches[1]).$($Matches[2])" } else { [version]"0.0" }

# --- 4. VISUAL STUDIO BUILD TOOLS ---
Log "Checking Visual Studio Build Tools"
$vs = Get-VsInstance
if (-not $vs) {
    Log "Installing Visual Studio Build Tools 2022 (C++ workload)..."
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
    $vs = Get-VsInstance
    if (-not $vs) { WARN "Visual Studio C++ tools still not found."; exit 1 }
}
OK "Visual Studio found: $($vs.DisplayName) (v$($vs.Version) -> $($vs.Generator))"
if ($vs.Major -ge 18 -and $cmakeVersion -lt [version]"4.1") {
    WARN "Visual Studio 2026 needs CMake 4.1 or newer (found $cmakeVersion). Update: winget upgrade Kitware.CMake"
    exit 1
}
$msvcClExe = Resolve-MsvcClPath -VsInstallPath $vs.Path
if (-not $msvcClExe) {
    WARN "Could not locate MSVC cl.exe under: $($vs.Path)"
    WARN "Install the C++ workload / MSVC x64 tools in Visual Studio Installer."
    exit 1
}
OK "MSVC cl.exe: $msvcClExe"

# --- 5. CUDA (only if BuildType = CUDA) ---
$cudaInstallDir = $null
$cudaToolkit = $null
$nvidiaInfo = $null
if ($BuildType -eq "CUDA") {
    Log "Checking CUDA Toolkit"
    $toolkits = Get-CudaToolkits
    if ($toolkits.Count -eq 0) {
        WARN "CUDA Toolkit not found! Please install it (with Visual Studio integration)."
        WARN "Download: https://developer.nvidia.com/cuda-downloads"
        exit 1
    }
    OK "Installed toolkits: $(($toolkits | ForEach-Object { $_.Version.ToString() }) -join ', ')"

    $nvidiaInfo = Get-NvidiaInfo
    if ($nvidiaInfo.DriverCuda) { OK "Driver supports CUDA up to $($nvidiaInfo.DriverCuda)" }
    if ($nvidiaInfo.ComputeCaps.Count -gt 0) { OK "GPU compute capability: $($nvidiaInfo.ComputeCaps -join ', ') ($($nvidiaInfo.Names -join ', '))" }

    if ($CudaMajor) {
        $cudaToolkit = $toolkits | Where-Object { $_.Major -eq [int]$CudaMajor } | Select-Object -First 1
        if (-not $cudaToolkit) {
            WARN "No CUDA $CudaMajor.x toolkit installed (found: $(($toolkits | ForEach-Object { $_.Version.ToString() }) -join ', '))."
            WARN "Install CUDA $CudaMajor.x or choose the other CUDA profile."
            exit 1
        }
    } else {
        $cudaToolkit = $toolkits[0]
    }
    $cudaInstallDir = $cudaToolkit.Path

    if ($nvidiaInfo.DriverCuda -and $cudaToolkit.Version -gt $nvidiaInfo.DriverCuda) {
        WARN "CUDA toolkit $($cudaToolkit.Version) is newer than what the NVIDIA driver supports ($($nvidiaInfo.DriverCuda))."
        WARN "The binaries will fail at runtime ('CUDA driver version is insufficient')."
        WARN "Update the driver or pick the CUDA 12.x profile."
        exit 1
    }
    if ($cudaToolkit.Major -ge 13 -and ($nvidiaInfo.ComputeCaps | Where-Object { [version]$_ -lt [version]"7.5" })) {
        WARN "CUDA 13 dropped support for GPUs older than Turing (compute capability < 7.5)."
        WARN "Use the CUDA 12.x profile for this GPU."
        exit 1
    }

    # Make nvcc/cudart of exactly this toolkit the first hit in PATH.
    $env:PATH = "$cudaInstallDir\bin;$env:PATH"
    $env:CUDA_PATH = $cudaInstallDir
    $env:CUDAToolkit_ROOT = $cudaInstallDir
    $cudaVerText = Invoke-Native { & (Join-Path $cudaInstallDir "bin\nvcc.exe") --version }
    $cudaVer = if ($cudaVerText -match 'release[^\r\n]*') { $Matches[0] } else { "" }
    OK "Using CUDA $($cudaToolkit.Version): $cudaInstallDir ($cudaVer)"

    # CUDA VS Integration
    Log "Setting up CUDA Visual Studio integration"
    $cudaVsIntSrc = "$cudaInstallDir\extras\visual_studio_integration\MSBuildExtensions"
    $cudaPropsInstalled = $false

    if (Test-Path $cudaVsIntSrc) {
        $vsTargetDirs = @()
        if ($vs.Major -ge 17) {
            $vsTargetDirs += Join-Path $vs.Path "MSBuild\Microsoft\VC\v170\BuildCustomizations"
        } elseif ($vs.Major -eq 16) {
            $vsTargetDirs += Join-Path $vs.Path "MSBuild\Microsoft\VC\v160\BuildCustomizations"
        } elseif ($vs.Major -eq 15) {
            $vsTargetDirs += Join-Path $vs.Path "MSBuild\Microsoft\VC\v150\BuildCustomizations"
        } elseif ($vs.Major -eq 14) {
            $vsTargetDirs += Join-Path $vs.Path "MSBuild\Microsoft\VC\v140\BuildCustomizations"
        }

        foreach ($target in $vsTargetDirs) {
            $alreadyThere = (Test-Path $target) -and (Get-ChildItem $cudaVsIntSrc -File | ForEach-Object { Test-Path (Join-Path $target $_.Name) }) -notcontains $false
            if ($alreadyThere) { OK "CUDA Props already present in $target"; $cudaPropsInstalled = $true; break }
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
    } else {
        WARN "CUDA MSBuildExtensions not found at $cudaVsIntSrc"
    }
    if (-not $cudaPropsInstalled) {
        WARN "CUDA Visual Studio integration is not installed; CMake will not find the CUDA toolset."
    }
}

# --- 6. VULKAN (only if BuildType = Vulkan) ---
$spirvPrefix = $null
if ($BuildType -eq "Vulkan") {
    Log "Checking Vulkan SDK"
    $vulkanFound = $false

    # llama.cpp needs glslc (Vulkan::glslc); glslangValidator ships alongside it.
    if ((Is-Available "glslc") -or (Is-Available "glslangValidator")) {
        OK "Vulkan SDK found (glslc in PATH)"
        $vulkanFound = $true
    } elseif ($env:VULKAN_SDK -and (Test-Path "$env:VULKAN_SDK\Bin\glslc.exe")) {
        Add-ToPath "$env:VULKAN_SDK\Bin"
        OK "Vulkan SDK found via VULKAN_SDK env ($env:VULKAN_SDK)"
        $vulkanFound = $true
    } else {
        foreach ($sdkBase in @("C:\VulkanSDK", "C:\Program Files\VulkanSDK")) {
            if (Test-Path $sdkBase) {
                $latestVer = Get-ChildItem $sdkBase -Directory | Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending | Select-Object -First 1
                if ($latestVer -and (Test-Path "$($latestVer.FullName)\Bin\glslc.exe")) {
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
    $spirvPrefix = Build-SpirvHeaders -DepsDir $DepsDir -Generator $vs.Generator
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
                foreach ($rel in @("compiler\latest\bin", "compiler\latest\windows\bin")) {
                    $compilerDir = Join-Path $oneapiBase $rel
                    if (Test-Path (Join-Path $compilerDir "icx.exe")) {
                        Add-ToPath $compilerDir
                        OK "Intel oneAPI found at $compilerDir"
                        $syclFound = $true
                        break
                    }
                }
                if ($syclFound) { break }
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

    $ninjaExe = Resolve-NinjaPath -VsInstallPath $vs.Path
    if (-not $ninjaExe) {
        Log "Installing Ninja (required for SYCL build)..."
        if ($useWinget) {
            winget install --id Ninja-build.Ninja -e --source winget --accept-source-agreements --accept-package-agreements
        } elseif ($hasChoco) {
            choco install ninja -y --no-progress
        }
        Refresh-Path
        $ninjaExe = Resolve-NinjaPath -VsInstallPath $vs.Path
    }
    if (-not $ninjaExe) {
        WARN "Ninja not found! Required for SYCL builds. Install: winget install Ninja-build.Ninja"
        exit 1
    }
    OK "Ninja: $ninjaExe"
}

# --- 6c. HIP / ROCm (only if BuildType = HIP) ---
$hipRoot = $null
$hipClangBin = $null
$amdGfxTarget = $null
$hipResourceDir = ""
if ($BuildType -eq "HIP") {
    Log "Checking AMD HIP SDK"

    # CMake does not support the HIP language on Windows, so ggml-hip builds
    # via the hipcc/clang compiler. This is fundamentally different from the
    # VS-generator + MSVC path used by CPU/CUDA/Vulkan - it needs Ninja.
    $hipRoot = Resolve-HipRoot
    if (-not $hipRoot) {
        WARN "AMD HIP SDK (clang/hipcc) not found!"
        WARN "Install the AMD HIP SDK and set HIP_PATH, or use Vulkan instead."
        WARN "RDNA4 (Radeon RX 9000 / AI PRO R9000) users should choose Vulkan - HIP on"
        WARN "Windows for gfx120x is known to be unreliable."
        exit 1
    }
    $hipClangBin = Join-Path $hipRoot "bin"
    $env:HIP_PATH = "$hipRoot\"
    $env:ROCM_PATH = $hipRoot
    Add-ToPath $hipClangBin
    OK "HIP SDK: $hipRoot"

    # Ninja + ROCm clang link against the MSVC ABI: import the exact VS environment.
    Import-VsDevEnvironment -VsInstallPath $vs.Path | Out-Null
    $ninjaExe = Resolve-NinjaPath -VsInstallPath $vs.Path
    if (-not $ninjaExe) {
        Log "Installing Ninja (required for HIP build)..."
        if ($useWinget) {
            winget install --id Ninja-build.Ninja -e --source winget --accept-source-agreements --accept-package-agreements
        } elseif ($hasChoco) {
            choco install ninja -y --no-progress
        }
        Refresh-Path
        $ninjaExe = Resolve-NinjaPath -VsInstallPath $vs.Path
    }
    if (-not $ninjaExe) {
        WARN "Ninja not found! Required for HIP builds. Install: winget install Ninja-build.Ninja"
        exit 1
    }
    OK "Ninja: $ninjaExe"

    # Detect the AMD gfx target so we compile for the right GPU.
    $amdGfxTarget = Get-AmdGfxTarget -HipRoot $hipRoot
    if ($amdGfxTarget) {
        OK "AMD GPU target(s): $amdGfxTarget"
        if ($amdGfxTarget -match "gfx120[01]") {
            WARN "Detected RDNA4 (gfx120x). HIP on Windows is unreliable for this"
            WARN "hardware - Vulkan is strongly recommended. Continuing HIP anyway."
        }
    } elseif (-not (Test-ExtraFlag "-DGPU_TARGETS=")) {
        WARN "Could not auto-detect the AMD gfx target (hipInfo.exe missing?)."
        WARN "Set -DGPU_TARGETS=gfxNNNN via Extra Flags; otherwise the HIP SDK default list is compiled (slow)."
    }

    $hipResourceDir = Get-HipCompatibilityResourceDir -Clang (Join-Path $hipClangBin "clang.exe") -HipRoot $hipRoot -DepsDir $DepsDir
}

# --- 7. FINAL CHECK ---
Log "Final check"
OK "git OK"
OK "cmake OK: $CMAKE_EXE"

# --- 8. CLONE REPO ---
Log "Checking $Source"
Set-Location $InstallDir

# Long paths (260 char limit) are enabled per repository, not in the global config.
$gitLongPaths = @("-c", "core.longpaths=true")

# Backend-qualified, Auto-Tuner-compatible folder name, e.g.
# "b10830_vulkan_llama.cpp". One folder per source+version+backend.
$backend = $BuildType.ToLower()
$versionPrefixPattern = "(?:b\d+|bUNKNOWN|pr\d+|pinned_[0-9a-f]+)(?:_run_[0-9_]+)?"
$existingDir = Get-ChildItem $InstallDir -Directory | Where-Object {
    $_.Name -match "^${versionPrefixPattern}_${backend}_$([regex]::Escape($DIR_SUFFIX))$" -and
    (Test-Path (Join-Path $_.FullName ".git"))
} | Sort-Object LastWriteTime -Descending | Select-Object -First 1

function Get-UnusedBuildPath([string]$Version) {
    $candidate = Join-Path $InstallDir "${Version}_${backend}_$DIR_SUFFIX"
    while (Test-Path -LiteralPath $candidate) {
        $stamp = Get-Date -Format "yyyyMMddHHmmssfffffff"
        $candidate = Join-Path $InstallDir "${Version}_run_${stamp}_${backend}_$DIR_SUFFIX"
    }
    return $candidate
}

function Get-BuildNumberName {
    # "bNNNN" from "git rev-list --count HEAD": llama.cpp's own build number
    # (cmake/build-info.cmake), so the folder name matches llama-server --version.
    param([Parameter(Mandatory=$true)][string]$Repo)
    $count = Invoke-Native { & git -C $Repo rev-list --count HEAD }
    if ($script:LastNativeExit -eq 0 -and $count -match '^\d+$') { return "b$count" }
    return "bUNKNOWN"
}

if ($existingDir) {
    $dir = $existingDir.FullName
    $checkBuildDir = if ($BuildDir) { $BuildDir } else { Join-Path $dir "build" }
    Assert-VulkanPathBudget -Root $InstallDir -Backend $BuildType -ActualBuildDir $checkBuildDir
    if ($Update) {
        Log "Updating existing checkout: $dir"
        Push-Location $dir
        if ($SourceCommit) {
            git @gitLongPaths fetch --all --prune
            if ($LASTEXITCODE -ne 0) { WARN "git fetch failed"; Pop-Location; exit 1 }
            if ($FetchRef) {
                git @gitLongPaths fetch --force origin $FetchRef
                if ($LASTEXITCODE -ne 0) { WARN "git fetch ref '$FetchRef' failed"; Pop-Location; exit 1 }
            }
            git @gitLongPaths checkout --detach $SourceCommit
            if ($LASTEXITCODE -ne 0) { WARN "git checkout commit '$SourceCommit' failed"; Pop-Location; exit 1 }
        } elseif ($REPO_PR) {
            git @gitLongPaths fetch --force origin "pull/$REPO_PR/head:pr$REPO_PR"
            if ($LASTEXITCODE -ne 0) { WARN "git fetch PR #$REPO_PR failed"; Pop-Location; exit 1 }
            git @gitLongPaths checkout "pr$REPO_PR"
            if ($LASTEXITCODE -ne 0) { WARN "git checkout PR #$REPO_PR failed"; Pop-Location; exit 1 }
            git @gitLongPaths reset --hard "pr$REPO_PR"
            if ($LASTEXITCODE -ne 0) { WARN "git reset PR #$REPO_PR failed"; Pop-Location; exit 1 }
        } else {
            git @gitLongPaths fetch --all --prune
            if ($LASTEXITCODE -ne 0) { WARN "git fetch failed"; Pop-Location; exit 1 }
            git @gitLongPaths reset --hard "origin/$REPO_BRANCH"
            if ($LASTEXITCODE -ne 0) { WARN "git reset failed"; Pop-Location; exit 1 }
        }
        git @gitLongPaths clean -fdx -e node_modules -e build
        if ($LASTEXITCODE -ne 0) { WARN "git clean failed"; Pop-Location; exit 1 }
        Pop-Location
        OK "Updated to latest '$REPO_BRANCH'"
        # The build number may have moved: rename the folder to stay truthful.
        $newName = "$(Get-BuildNumberName -Repo $dir)_${backend}_$DIR_SUFFIX"
        $newDir = Join-Path $InstallDir $newName
        if ($newDir -ne $dir) {
            if (Test-Path -LiteralPath $newDir) { $newDir = Get-UnusedBuildPath (Get-BuildNumberName -Repo $dir) }
            Move-PathWithRetry $dir $newDir
            $dir = $newDir
        }
    } else {
        OK "Found existing directory: $dir (skipping update)"
    }
} else {
    $tmpDir = Join-Path $InstallDir "_tmp_${Source}_${backend}_$([guid]::NewGuid().ToString('N'))"

    if ($SourceCommit) {
        Log "Cloning pinned source from $REPO_URL"
        git @gitLongPaths clone $REPO_URL $tmpDir
        if ($LASTEXITCODE -ne 0) { WARN "git clone failed"; exit 1 }
        if ($FetchRef) {
            git @gitLongPaths -C $tmpDir fetch --force origin $FetchRef
            if ($LASTEXITCODE -ne 0) { WARN "git fetch ref '$FetchRef' failed"; exit 1 }
        }
        git @gitLongPaths -C $tmpDir checkout --detach $SourceCommit
        if ($LASTEXITCODE -ne 0) { WARN "git checkout commit '$SourceCommit' failed"; exit 1 }
        if ($REPO_SUBMODULES) {
            git @gitLongPaths -C $tmpDir submodule update --init --recursive
            if ($LASTEXITCODE -ne 0) { WARN "git submodule update failed"; exit 1 }
        }
    } elseif ($REPO_PR) {
        # PR-based source: clone the base repo, then fetch the pull request
        # ref into a local branch and check it out.
        Log "Fetching PR #$REPO_PR from $REPO_URL"
        git @gitLongPaths clone $REPO_URL $tmpDir
        if ($LASTEXITCODE -ne 0) { WARN "git clone failed"; exit 1 }
        git @gitLongPaths -C $tmpDir fetch origin "pull/$REPO_PR/head:pr$REPO_PR"
        if ($LASTEXITCODE -ne 0) { WARN "git fetch PR #$REPO_PR failed"; exit 1 }
        git @gitLongPaths -C $tmpDir checkout "pr$REPO_PR"
        if ($LASTEXITCODE -ne 0) { WARN "git checkout PR #$REPO_PR failed"; exit 1 }
        if ($REPO_SUBMODULES) {
            git @gitLongPaths -C $tmpDir submodule update --init --recursive
            if ($LASTEXITCODE -ne 0) { WARN "git submodule update failed"; exit 1 }
        }
    } else {
        $cloneArgs = @("clone", "--branch", $REPO_BRANCH)
        if ($REPO_SUBMODULES) { $cloneArgs += @("--recurse-submodules", "--shallow-submodules") }
        $cloneArgs += @($REPO_URL, $tmpDir)
        git @gitLongPaths @cloneArgs
        if ($LASTEXITCODE -ne 0) { WARN "git clone failed"; exit 1 }
    }
    git -C $tmpDir config core.longpaths true | Out-Null
    $ver = Get-BuildNumberName -Repo $tmpDir
    $dir = Get-UnusedBuildPath $ver
    Set-Location $InstallDir
    Move-PathWithRetry $tmpDir $dir
    OK "Directory: $dir"
}
$headCommit = Invoke-Native { & git -C $dir rev-parse --short=9 HEAD }
OK "Source commit: $headCommit"

# --- 9. CMAKE CONFIGURE ---
Log "CMake configuration ($BuildType)"
if ([string]::IsNullOrEmpty($BuildDir)) {
    # Standard llama.cpp layout (build/bin/Release/...) so launchers such as
    # Auto-Tuner can auto-discover llama-server inside this folder.
    $buildDir = Join-Path $dir "build"
} else {
    $buildDir = $BuildDir
}

Assert-VulkanPathBudget -Root $InstallDir -Backend $BuildType -ActualBuildDir $buildDir
if ($CleanBuild -and (Test-Path $buildDir)) {
    Log "Deleting old build directory (clean build)..."
    Remove-PathWithRetry $buildDir
}
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

# CPU instruction-set target. "portable" = x86-64-v3 (AVX2/FMA/F16C/BMI2).
# AVX-VNNI requires newer CPUs and cannot be enabled in a portable binary.
# "native" = llama.cpp's own CPUID
# detection (AVX512/AMX) - only for the machine that builds it.
$cpuFlags = @()
if ($CpuTarget -eq "native") {
    $cpuFlags = @("-DGGML_NATIVE=ON")
} else {
    $cpuFlags = @("-DGGML_NATIVE=OFF", "-DGGML_AVX=ON", "-DGGML_AVX2=ON", "-DGGML_FMA=ON", "-DGGML_F16C=ON",
                  "-DGGML_AVX_VNNI=OFF", "-DGGML_BMI2=ON",
                  "-DGGML_AVX512=OFF", "-DGGML_AVX512_VBMI=OFF", "-DGGML_AVX512_VNNI=OFF", "-DGGML_AVX512_BF16=OFF")
}
OK "CPU target: $CpuTarget"

# Both layouts occur in supported forks. CMake consumes the npm output when
# LLAMA_USE_PREBUILT_UI=OFF; LLAMA_BUILD_UI alone does not build these assets.
function Get-WebUiFlags {
    param([string]$Repo, [bool]$Enabled)
    $uiFlags = @("-DLLAMA_BUILD_UI=ON", "-DLLAMA_USE_PREBUILT_UI=ON")
    $npmAvailable = Is-Available "npm.cmd"
    $uiSource = $null
    foreach ($relative in @("tools/ui", "tools/server/webui")) {
        $candidate = Join-Path $Repo $relative
        if (Test-Path (Join-Path $candidate "package.json")) { $uiSource = $candidate; break }
    }
    if ($Enabled -and $uiSource -and $npmAvailable) {
        Log "Building Web UI: $uiSource"
        Push-Location $uiSource
        try {
            if (Test-Path "package-lock.json") { & npm.cmd ci | Out-Host } else { & npm.cmd install | Out-Host }
            if ($LASTEXITCODE -ne 0) { throw "Web UI dependency install failed (exit $LASTEXITCODE)" }
            & npm.cmd run build | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "Web UI build failed (exit $LASTEXITCODE)" }
        } finally {
            Pop-Location
        }
        $uiFlags = @("-DLLAMA_BUILD_UI=ON", "-DLLAMA_USE_PREBUILT_UI=OFF")
        OK "Web UI: built from source"
    } else {
        OK "Web UI: using prebuilt assets (download requires internet)"
    }
    return $uiFlags
}

$uiFlags = @(Get-WebUiFlags -Repo $dir -Enabled ([bool]$BuildUi))

if ($Source -eq "ternary_bonsai" -and -not (Test-ExtraFlag "-DLLAMA_OPENSSL=")) {
    $uiFlags += "-DLLAMA_OPENSSL=OFF"
}

# The flash-attention option changed upstream; pinned forks retain the boolean.
function Convert-FlashAttentionFlags {
    param([string]$Repo, [string[]]$Flags)
    $optionsFile = Join-Path $Repo "ggml\CMakeLists.txt"
    if (-not (Test-Path $optionsFile) -or
        (Get-Content $optionsFile -Raw) -notmatch '(?m)^\s*set\s*\(\s*GGML_CUDA_FA_QUANTS\b') {
        return $Flags
    }
    "-UGGML_CUDA_FA_ALL_QUANTS"
    $explicitQuants = @($Flags | Where-Object { $_ -match '^-DGGML_CUDA_FA_QUANTS(?::STRING)?=' }).Count -gt 0
    foreach ($flag in $Flags) {
        if ($flag -match '^-DGGML_CUDA_FA_ALL_QUANTS(?::BOOL)?=(ON|OFF)$') {
            if (-not $explicitQuants) {
                if ($Matches[1] -eq "ON") { "-DGGML_CUDA_FA_QUANTS=all" } else {
                    # OFF meant the source's default subset, not a literal "off" list.
                    "-UGGML_CUDA_FA_QUANTS"
                }
            }
        } else { $flag }
    }
}
if ($BuildType -in @("HIP", "CUDA")) {
    $extraFlagList = @(Convert-FlashAttentionFlags -Repo $dir -Flags $extraFlagList)
}

$buildTargetArgs = @()
if ($targetList.Count -gt 0) { $buildTargetArgs = @("--target") + $targetList; OK "Targets: $($targetList -join ', ')" }

function Show-Result {
    param([string]$BinPath, [string]$Label)
    Log "BUILD SUCCESSFUL! ($Label)"
    OK "Binaries: $BinPath"
    $exes = Get-ChildItem $BinPath -Filter "*.exe" -ErrorAction SilentlyContinue
    Write-Host "LLAMA_BUILD_OUTPUT=$([IO.Path]::GetFullPath($buildDir))"
    if ($exes) { $exes | ForEach-Object { OK "  $($_.Name)" } }
    Write-Host "`nStart server:" -ForegroundColor Green
    Write-Host "  $BinPath\llama-server.exe -m <model.gguf> --host 0.0.0.0 --port 8080" -ForegroundColor Green
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
        "-DBUILD_SHARED_LIBS=ON", "-DLLAMA_BUILD_SERVER=ON",
        "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"
    ) + $cpuFlags + $uiFlags

    if ($extraFlagList.Count -gt 0) { $cmakeFlags += $extraFlagList; Log "Extra flags: $($extraFlagList -join ' ')" }
    Log "Starting SYCL build: $CMAKE_EXE $($cmakeFlags -join ' ')"
    & $CMAKE_EXE @cmakeFlags

    if ($LASTEXITCODE -ne 0) {
        WARN "CMake configuration failed! Code: $LASTEXITCODE"
        exit 1
    }
    OK "CMake configuration successful (SYCL/Ninja)"

    Log "Compiling $Source with SYCL using $ParallelJobs jobs..."
    & $CMAKE_EXE --build $buildDir --parallel $ParallelJobs @buildTargetArgs

    if ($LASTEXITCODE -ne 0) {
        WARN "Build failed! Code: $LASTEXITCODE"
        exit 1
    }

    Log "Copying Intel oneAPI SYCL runtime DLLs"
    $syclBin = Join-Path $buildDir "bin"
    Copy-SyclRuntimeDlls -TargetDir $syclBin | Out-Null

    Show-Result -BinPath (Join-Path $buildDir "bin") -Label "SYCL"
    exit 0
}

# --- HIP builds use Ninja + the AMD HIP SDK clang (NOT the VS generator) ---
if ($BuildType -eq "HIP") {
    $clangExe = Join-Path $hipClangBin "clang.exe"
    $clangxxExe = Join-Path $hipClangBin "clang++.exe"
    if (-not (Test-Path $clangxxExe)) {
        WARN "clang++ not found in $hipClangBin"
        WARN "Ensure the AMD HIP SDK is fully installed."
        exit 1
    }

    $cmakeFlags = @(
        "-S", $dir, "-B", $buildDir,
        "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_COMPILER=$clangExe",
        "-DCMAKE_CXX_COMPILER=$clangxxExe",
        "-DGGML_HIP=ON",
        "-DGGML_CUDA=OFF",
        "-DGGML_VULKAN=OFF",
        "-DGGML_CUDA_NO_PEER_COPY=ON",
        "-DBUILD_SHARED_LIBS=OFF", "-DLLAMA_BUILD_SERVER=ON",
        "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"
    ) + $cpuFlags + $uiFlags
    if ($amdGfxTarget -and -not (Test-ExtraFlag "-DGPU_TARGETS=")) { $cmakeFlags += "-DGPU_TARGETS=$amdGfxTarget" }
    if ($hipResourceDir) {
        $resourceFlag = '-resource-dir="' + $hipResourceDir.Replace('\', '/') + '"'
        $cmakeFlags += @("-DCMAKE_C_FLAGS=$resourceFlag", "-DCMAKE_CXX_FLAGS=$resourceFlag")
    }
    if ($extraFlagList.Count -gt 0) { $cmakeFlags += $extraFlagList; Log "Extra flags: $($extraFlagList -join ' ')" }

    Log "Starting HIP build: $CMAKE_EXE $($cmakeFlags -join ' ')"
    & $CMAKE_EXE @cmakeFlags
    if ($LASTEXITCODE -ne 0) { WARN "CMake configuration failed! Code: $LASTEXITCODE"; exit 1 }
    OK "CMake configuration successful (HIP/Ninja)"

    # HIP device compilation is memory hungry: cap the parallelism.
    $hipJobs = [Math]::Min($ParallelJobs, 12)
    Log "Compiling $Source with HIP using $hipJobs jobs..."
    & $CMAKE_EXE --build $buildDir --parallel $hipJobs @buildTargetArgs
    if ($LASTEXITCODE -ne 0) { WARN "Build failed! Code: $LASTEXITCODE"; exit 1 }

    $hipBin = Join-Path $buildDir "bin"
    Log "Bundling ROCm runtime next to the executables"
    Copy-HipRuntimeDependencies -BinDir $hipBin -HipRoot $hipRoot

    Show-Result -BinPath $hipBin -Label "HIP"
    exit 0
}

# --- Non-SYCL/HIP builds use the Visual Studio generator ---
$vsGenerator = $vs.Generator
OK "VS: $($vs.Path) (v$($vs.Version) -> $vsGenerator)"
Add-ToPath (Split-Path -Parent $msvcClExe)

$cmakeFlags = @(
    "-S", $dir, "-B", $buildDir,
    "-G", $vsGenerator, "-A", "x64",
    "-DCMAKE_BUILD_TYPE=Release",
    "-DLLAMA_BUILD_SERVER=ON",
    "-DLLAMA_CURL=OFF", "-DGGML_CCACHE=OFF"
) + $cpuFlags + $uiFlags

if ($BuildType -eq "CUDA") {
    $cmakeFlags += @("-DGGML_CUDA=ON", "-DGGML_VULKAN=OFF", "-DBUILD_SHARED_LIBS=OFF")
    if ($cudaInstallDir) {
        $cmakeFlags += "-DCUDAToolkit_ROOT=$cudaInstallDir"
        # Visual Studio generators pick the CUDA toolset via -T, not CMAKE_CUDA_COMPILER.
        $cmakeFlags += @("-T", "cuda=$cudaInstallDir")
    }
    # Compile only for the GPUs in this machine (fast build, smaller binary)
    # unless the user pinned CMAKE_CUDA_ARCHITECTURES via extra flags.
    if ($nvidiaInfo -and $nvidiaInfo.ComputeCaps.Count -gt 0 -and -not (Test-ExtraFlag "-DCMAKE_CUDA_ARCHITECTURES=")) {
        $archs = @()
        foreach ($cc in $nvidiaInfo.ComputeCaps) {
            $num = [int]($cc.Split('.')[0]) * 10 + [int]($cc.Split('.')[1])
            $arch = if ($num -ge 120) { "${num}a-real" } else { "${num}-real" }
            if ($archs -notcontains $arch) { $archs += $arch }
        }
        $cmakeFlags += "-DCMAKE_CUDA_ARCHITECTURES=$($archs -join ';')"
        OK "CUDA architectures: $($archs -join ';')"
    }
} elseif ($BuildType -eq "Vulkan") {
    # RDNA4 (Radeon RX 9000) Vulkan recipe: Vulkan backend + recent
    # SPIRV-Headers prefix + ASM/CMP0194 workarounds (llama.cpp #22100).
    # Use the full cl.exe path: a bare "cl" is not resolvable when this script
    # is launched from a normal PowerShell instead of a VS Developer Prompt.
    $cacheFile = Join-Path $buildDir "CMakeCache.txt"
    if (Test-Path -LiteralPath $cacheFile) {
        $cacheText = Get-Content -LiteralPath $cacheFile -Raw -ErrorAction SilentlyContinue
        if ($cacheText -match "CMAKE_ASM_COMPILER[^=]*=cl(\.exe)?(\r?\n|$)") {
            Log "Deleting stale Vulkan CMake cache with bare CMAKE_ASM_COMPILER=cl"
            Remove-PathWithRetry $buildDir
            New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
        }
    }

    $cmakeFlags += @(
        "-DGGML_VULKAN=ON",
        "-DGGML_CUDA=OFF",
        "-DGGML_VULKAN_CHECK_RESULTS=OFF",
        "-DCMAKE_POLICY_DEFAULT_CMP0194=OLD",
        "-DCMAKE_ASM_COMPILER=$msvcClExe",
        "-DBUILD_SHARED_LIBS=OFF"
    )
    if ($spirvPrefix) {
        $cmakeFlags += "-DCMAKE_PREFIX_PATH=$spirvPrefix"
        OK "Using SPIRV-Headers prefix: $spirvPrefix"
    }
} else {
    # CPU
    $cmakeFlags += @("-DGGML_CUDA=OFF", "-DGGML_VULKAN=OFF", "-DBUILD_SHARED_LIBS=OFF")
}

if ($extraFlagList.Count -gt 0) { $cmakeFlags += $extraFlagList; Log "Extra flags: $($extraFlagList -join ' ')" }
Log "Starting: $CMAKE_EXE $($cmakeFlags -join ' ')"
& $CMAKE_EXE @cmakeFlags

if ($LASTEXITCODE -ne 0) {
    WARN "CMake configuration failed! Code: $LASTEXITCODE"
    exit 1
}
OK "CMake configuration successful"

# --- 10. BUILD ---
Log "Compiling $Source with $BuildType using $ParallelJobs jobs..."
& $CMAKE_EXE --build $buildDir --config Release --parallel $ParallelJobs @buildTargetArgs

if ($LASTEXITCODE -ne 0) {
    WARN "Build failed! Code: $LASTEXITCODE"
    exit 1
}

$binPath = Join-Path $buildDir "bin\Release"
if ($BuildType -eq "CUDA" -and $cudaInstallDir) {
    Deploy-CudaRuntimeDlls -CudaBin (Join-Path $cudaInstallDir "bin") -Destination $binPath
}
Show-Result -BinPath $binPath -Label $BuildType
