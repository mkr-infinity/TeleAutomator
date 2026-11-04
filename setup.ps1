# =============================================================================
# Windows PowerShell Setup Script for Telegram Chat Automation
# =============================================================================

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host " Telegram Chat Automation - Windows Setup" -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Cyan

# 1. Check Python
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3.10+ was not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/downloads/ and check 'Add python.exe to PATH'." -ForegroundColor Yellow
    exit 1
}

$pyVersion = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[*] Found Python: $pyVersion" -ForegroundColor Green

# 2. Virtual Environment
if (-not (Test-Path ".venv")) {
    Write-Host "[*] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    & $pythonCmd -m venv .venv
}

# 3. Activate & Install
Write-Host "[*] Installing dependencies..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
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
