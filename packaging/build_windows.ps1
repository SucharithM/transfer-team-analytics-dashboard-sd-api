# Run on Windows from a Python virtual environment.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Build this executable on Windows.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is required for the publication-check tests. Install Git for Windows with command-line access, or add its cmd folder to this session''s PATH, then rerun the build.'
}
python -m pip install -r requirements-bootstrap.txt
if ($LASTEXITCODE -ne 0) { throw 'Installer update failed.' }
python -m pip install -r requirements-dev.txt -r packaging/requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no executable will be built.' }
python -m workflow_dashboard.build_identity --output build/build_identity.json
if ($LASTEXITCODE -ne 0) { throw 'Build identity generation failed.' }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WorkflowTransferDashboard --collect-all playwright --collect-all plotly --add-data 'workflow_dashboard/desktop_settings.toml;workflow_dashboard' --add-data 'build/build_identity.json;workflow_dashboard' desktop_launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
Write-Host 'Built dist/WorkflowTransferDashboard.exe.'
