param([string]$ScriptPath, [string]$Workspace)
$ErrorActionPreference = "Stop"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @("Assert-VulkanPathBudget", "Get-WebUiFlags", "Get-UnusedBuildPath", "Convert-FlashAttentionFlags", "Deploy-CudaRuntimeDlls", "ConvertFrom-EncodedCMakeFlags", "Get-FailedTestOnlyProjects")) {
    $definition = $ast.Find({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    if (-not $definition) { throw "Missing function: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Log($msg) {}
function OK($msg) {}
function Is-Available($cmd) { return $true }

Assert-VulkanPathBudget -Root 'C:\b' -Backend Vulkan
Assert-VulkanPathBudget -Root $Workspace -Backend HIP
Assert-VulkanPathBudget -Root $Workspace -Backend Vulkan -ActualBuildDir 'C:\b\build'
foreach ($case in @(
    @{ Root = 'L:\LAB\Llama.cpp-Build-Assistant\builds\validation-v2.3.7'; Backend = 'Vulkan' },
    @{ Root = 'C:\b'; Backend = 'Vulkan'; Suffix = ('custom_' * 20) },
    @{ Root = 'C:\b'; Backend = 'Vulkan'; ActualBuildDir = ('C:\' + ('deep\' * 40)) }
)) {
    $failed = $false
    try { Assert-VulkanPathBudget @case } catch {
        if ($_.Exception.Message -notmatch 'FTK1011/MSB8066') { throw }
        $failed = $true
    }
    if (-not $failed) { throw 'Over-budget Vulkan path accepted' }
}

$encodedFlags = @(
    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('-DFOO=ON')),
    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('-DCMAKE_CXX_FLAGS=-O3 -march=native')),
    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('-DCMAKE_CUDA_ARCHITECTURES=75;89'))
) -join ','
$decodedFlags = @(ConvertFrom-EncodedCMakeFlags -Value $encodedFlags)
if ($decodedFlags.Count -ne 3 -or
    $decodedFlags[0] -ne '-DFOO=ON' -or
    $decodedFlags[1] -ne '-DCMAKE_CXX_FLAGS=-O3 -march=native' -or
    $decodedFlags[2] -ne '-DCMAKE_CUDA_ARCHITECTURES=75;89') {
    throw "Encoded CMake profile flags were changed"
}
function npm.cmd {
    $script:Calls += ($args -join " ")
    Write-Output "npm stdout must not become a CMake argument"
    $global:LASTEXITCODE = $script:NpmExit
}
$script:NpmExit = 0

foreach ($layout in @("tools/ui", "tools/server/webui")) {
    $repo = Join-Path $Workspace ($layout.Replace('/', '_'))
    $ui = Join-Path $repo $layout
    New-Item -ItemType Directory -Path $ui -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $ui "package.json") | Out-Null
    New-Item -ItemType File -Path (Join-Path $ui "package-lock.json") | Out-Null
    $script:Calls = @()
    $flags = @(Get-WebUiFlags -Repo $repo -Enabled $true)
    if (($script:Calls -join ',') -ne 'ci,run build') { throw "npm did not build $layout" }
    if ($flags -notcontains '-DLLAMA_USE_PREBUILT_UI=OFF') { throw "Local UI was not selected" }
    if ($flags.Count -ne 2) { throw "npm output leaked into CMake flags" }
    $script:Calls = @()
    $flags = @(Get-WebUiFlags -Repo $repo -Enabled $false)
    if ($script:Calls.Count -or $flags -notcontains '-DLLAMA_USE_PREBUILT_UI=ON') {
        throw "Disabled source build did not use prebuilt UI"
    }
    $script:NpmExit = 1
    $before = (Get-Location).Path
    $failed = $false
    try { Get-WebUiFlags -Repo $repo -Enabled $true | Out-Null } catch { $failed = $true }
    if (-not $failed -or (Get-Location).Path -ne $before) { throw "npm failure was swallowed or cwd leaked" }
    $script:NpmExit = 0
}
$flags = @(Get-WebUiFlags -Repo $Workspace -Enabled $true)
if ($flags -notcontains '-DLLAMA_USE_PREBUILT_UI=ON') { throw "Missing source must use prebuilt UI" }

$InstallDir = $Workspace
$backend = "cpu"
$DIR_SUFFIX = "llama.cpp"
$existing = Join-Path $Workspace "b10000_cpu_llama.cpp"
New-Item -ItemType Directory -Path $existing | Out-Null
$candidate = Get-UnusedBuildPath "b10000"
if ($candidate -eq $existing -or -not (Test-Path $existing)) { throw "Existing output was not preserved" }
if ((Split-Path $candidate -Leaf) -notmatch '^b10000_run_\d+_cpu_llama\.cpp$') { throw "Bad output name" }

$options = Join-Path $Workspace "ggml"
New-Item -ItemType Directory -Path $options | Out-Null
$options = Join-Path $options "CMakeLists.txt"
Set-Content $options 'option(GGML_CUDA_FA_ALL_QUANTS "All quants" OFF)'
$flags = @(Convert-FlashAttentionFlags -Repo $Workspace -Flags @('-DGGML_CUDA_FA_ALL_QUANTS=ON'))
if ($flags -notcontains '-DGGML_CUDA_FA_ALL_QUANTS=ON') { throw "Old fork option changed" }
Set-Content $options 'set (GGML_CUDA_FA_QUANTS "f16-f16" CACHE STRING "Quants")'
$flags = @(Convert-FlashAttentionFlags -Repo $Workspace -Flags @('-DGGML_CUDA_FA_ALL_QUANTS=ON'))
if ($flags -notcontains '-DGGML_CUDA_FA_QUANTS=all' -or $flags -notcontains '-UGGML_CUDA_FA_ALL_QUANTS') {
    throw "Modern option was not migrated"
}
$flags = @(Convert-FlashAttentionFlags -Repo $Workspace -Flags @('-DGGML_CUDA_FA_ALL_QUANTS=OFF'))
if ($flags -notcontains '-UGGML_CUDA_FA_QUANTS') { throw "Legacy OFF did not restore the source default" }
$flags = @(Convert-FlashAttentionFlags -Repo $Workspace -Flags @('-DGGML_CUDA_FA_ALL_QUANTS=ON', '-DGGML_CUDA_FA_QUANTS:STRING=f16-f16'))
if ($flags -contains '-DGGML_CUDA_FA_QUANTS=all' -or $flags -notcontains '-DGGML_CUDA_FA_QUANTS:STRING=f16-f16') {
    throw "Explicit quant list was overridden"
}
$cudaBin = Join-Path $Workspace "CUDA SDK bin"
$destination = Join-Path $Workspace "output bin"
New-Item -ItemType Directory -Path $cudaBin | Out-Null
$dllNames = @("cudart64_13.dll", "cublas64_13.dll", "cublasLt64_13.dll",
              "nvJitLink_130_0.dll", "nvrtc64_130_0.dll", "nvrtc-builtins64_130.dll")
foreach ($name in $dllNames) { Set-Content (Join-Path $cudaBin $name) $name }
Deploy-CudaRuntimeDlls -CudaBin $cudaBin -Destination $destination
foreach ($name in $dllNames) {
    if ((Get-Content (Join-Path $destination $name)) -ne $name) { throw "CUDA DLL not copied: $name" }
}
$x64Bin = Join-Path $cudaBin "x64"
$arm64Bin = Join-Path $cudaBin "arm64"
New-Item -ItemType Directory -Path $x64Bin, $arm64Bin | Out-Null
foreach ($name in $dllNames) {
    Set-Content (Join-Path $x64Bin $name) "x64 $name"
    Set-Content (Join-Path $arm64Bin $name) "arm64 $name"
}
Deploy-CudaRuntimeDlls -CudaBin $cudaBin -Destination $destination
foreach ($name in $dllNames) {
    if ((Get-Content (Join-Path $destination $name)) -ne "x64 $name") { throw "Wrong CUDA architecture: $name" }
}
$incomplete = Join-Path $Workspace "incomplete CUDA bin"
New-Item -ItemType Directory -Path $incomplete | Out-Null
Set-Content (Join-Path $incomplete "cudart64_13.dll") "incomplete SDK"
$failed = $false
try { Deploy-CudaRuntimeDlls -CudaBin $incomplete -Destination $destination } catch { $failed = $true }
if (-not $failed) { throw "Stale destination DLLs masked an incomplete CUDA SDK" }
$fakeBuild = Join-Path $Workspace "build"
$testErr = "M:\x\tests\test-batch-alloc.cpp(785,33): error C2131: Ausdruck [$fakeBuild\tests\test-batch-alloc.vcxproj]"
$toolErr = "M:\x\src\llama.cpp(1,1): error C2065: foo [$fakeBuild\src\llama.vcxproj]"
$warn = "M:\x\src\llama.cpp(75,5): warning C4297: bar [$fakeBuild\src\llama.vcxproj]"
$only = @(Get-FailedTestOnlyProjects -Lines @($warn, $testErr, $testErr) -BuildDir $fakeBuild)
if ($only.Count -ne 1 -or $only[0] -ne "test-batch-alloc") { throw "Test-only build failure not recognised" }
if (@(Get-FailedTestOnlyProjects -Lines @($testErr, $toolErr) -BuildDir $fakeBuild).Count) { throw "Tool failure treated as test-only" }
if (@(Get-FailedTestOnlyProjects -Lines @("LINK : fatal error LNK1104: x") -BuildDir $fakeBuild).Count) { throw "Unattributed error treated as test-only" }
if (@(Get-FailedTestOnlyProjects -Lines @($warn) -BuildDir $fakeBuild).Count) { throw "Warnings treated as test failure" }
Write-Output "Build helper checks passed"
