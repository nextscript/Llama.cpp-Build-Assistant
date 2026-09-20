$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $projectDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
try {
    $python = @('py', 'python', 'python3') | ForEach-Object {
        Get-Command $_ -ErrorAction SilentlyContinue
    } | Select-Object -First 1
    if (-not $python) { throw 'Python 3.10 or newer is required.' }
    $bootstrap = Start-Process -FilePath $python.Source -WindowStyle Hidden -PassThru -Wait `
        -WorkingDirectory $projectDir `
        -ArgumentList ('"' + (Join-Path $projectDir 'python_manager.py') + '" bootstrap') `
        -RedirectStandardOutput (Join-Path $logDir 'bootstrap.log') `
        -RedirectStandardError (Join-Path $logDir 'bootstrap-error.log')
    if ($bootstrap.ExitCode -ne 0) { throw 'Python setup failed. See logs/bootstrap-error.log.' }
    $chosen = (Get-Content -LiteralPath (Join-Path $projectDir '.python-interpreter') -Raw).Trim()
    $windowless = Join-Path (Split-Path -Parent $chosen) 'pythonw.exe'
    if (Test-Path -LiteralPath $windowless) { $chosen = $windowless }
    Start-Process -FilePath $chosen -WindowStyle Hidden -WorkingDirectory $projectDir `
        -ArgumentList ('"' + (Join-Path $projectDir 'app.py') + '"') `
        -RedirectStandardOutput (Join-Path $logDir 'app-launch.log') `
        -RedirectStandardError (Join-Path $logDir 'app-launch-error.log')
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Llama.cpp Build Assistant') | Out-Null
    exit 1
}
