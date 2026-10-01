# Run on Windows from a Python virtual environment.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Build this executable on Windows.' }
python -m pip install -r requirements-bootstrap.txt
if ($LASTEXITCODE -ne 0) { throw 'Installer update failed.' }
python -m pip install -r requirements-dev.txt -r packaging/requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no executable will be built.' }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WorkflowTransferDashboard --collect-all playwright --collect-all plotly --add-data 'workflow_dashboard/desktop_settings.toml;workflow_dashboard' desktop_launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
Write-Host 'Built dist/WorkflowTransferDashboard.exe.'
