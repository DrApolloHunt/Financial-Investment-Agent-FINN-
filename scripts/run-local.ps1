# Refresh FINN's data from this laptop and publish it. One command, from the repo folder:
#
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1                 # full refresh
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -Doctor         # check data sources
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -Mode intraday  # filings only
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -Only INFY      # one company
#
# Use this if GitHub's servers are blocked by the exchanges. It asks for the Gemini key
# (hidden) unless GEMINI_API_KEY is already set, and never saves it to disk.
param([string]$Mode = "full", [string]$Only = "", [switch]$Doctor, [switch]$NoPush)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
  Write-Host "Creating the Python environment (first run only)..."
  python -m venv .venv
}
& $py -m pip install -q --disable-pip-version-check -r requirements-pipeline.txt
$env:PYTHONUTF8 = "1"

if (-not $env:GEMINI_API_KEY) {
  $sec = Read-Host "Paste your Gemini API key (it will not be shown)" -AsSecureString
  $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

if ($Doctor) { & $py -m pipeline.doctor INFY; exit $LASTEXITCODE }

$pyArgs = @("-m", "pipeline.run", "--mode", $Mode)
if ($Only) { $pyArgs += @("--only", $Only) }
& $py @pyArgs
if ($LASTEXITCODE -ne 0) { Write-Host "The pipeline failed; nothing was published."; exit $LASTEXITCODE }

if ($NoPush) { exit 0 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "git is not installed, so the data was not published. Install Git for Windows, or upload public\data on GitHub."
  exit 0
}
git add public/data
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Host "No new data to publish."; exit 0 }
git commit -m "data: laptop run $(Get-Date -Format s)"
git pull --rebase
git push
