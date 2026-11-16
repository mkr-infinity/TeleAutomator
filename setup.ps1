# =============================================================================
# Windows PowerShell Setup Script for Telegram Chat Automation
# =============================================================================

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host " TeleAutomator - Telegram Chat Automation Windows Setup" -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Cyan

# 1. Check Python
$pythonCmd = $null
foreach ($candidate in @("python", "py")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = $candidate
            break
        }
    }
}
if (-not $pythonCmd) {
    throw "Python 3.10+ is required. Install it and add it to PATH."
}

# 2. Virtual Environment
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[*] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    & $pythonCmd -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
}

& .\.venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Existing virtual environment requires Python 3.10+. Recreate it explicitly." }

# 3. Activate & Install
Write-Host "[*] Installing dependencies..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed; rerun setup to retry." }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed; rerun setup to retry." }
Write-Host "[✓] Dependencies installed." -ForegroundColor Green

# 4. Configuration
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[*] Created .env from .env.example. Please open .env and add your TG_API_ID and TG_API_HASH." -ForegroundColor Yellow
} else {
    Write-Host "[*] .env file already exists." -ForegroundColor Green
}

# 5. Data Directory
if (-not (Test-Path "data")) {
    New-Item -ItemType Directory -Path "data" | Out-Null
}

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host " Setup complete! Next steps:" -ForegroundColor Green
Write-Host "   1. Authenticate: .\.venv\Scripts\python.exe scripts\authenticate.py"
Write-Host "   2. Start Client: .\.venv\Scripts\python.exe -m app.main (or: python run.py)"
Write-Host "   3. Run Tests   : .\.venv\Scripts\python.exe -m pytest tests/"
Write-Host "========================================================================" -ForegroundColor Cyan
