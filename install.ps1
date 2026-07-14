$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "    JobFlow Dependency Setup Script      " -ForegroundColor Cyan
Write-Host "=========================================`n" -ForegroundColor Cyan

# 1. Check/Install Node.js
Write-Host "Checking for Node.js..." -ForegroundColor Yellow
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nodeVersion = node --version
    Write-Host "[-] Node.js is installed: $nodeVersion" -ForegroundColor Green
} else {
    Write-Host "[!] Node.js is NOT installed. Attempting to install via winget..." -ForegroundColor Red
    winget install OpenJS.NodeJS --source winget --accept-package-agreements --accept-source-agreements
    Write-Host "[!] Node.js has been installed. Please restart your terminal and re-run this script to continue." -ForegroundColor Red
    exit
}

# 2. Check/Install Python
Write-Host "`nChecking for Python..." -ForegroundColor Yellow
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonVersion = python --version
    Write-Host "[-] Python is installed: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "[!] Python is NOT installed. Attempting to install via winget..." -ForegroundColor Red
    winget install Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
    Write-Host "[!] Python has been installed. Please restart your terminal and re-run this script to continue." -ForegroundColor Red
    exit
}

# 3. Setup Python Virtual Environment
Write-Host "`nSetting up Python Virtual Environment (.venv)..." -ForegroundColor Yellow
$venvPython = ".\.venv\Scripts\python.exe"

if (-Not (Test-Path $venvPython)) {
    Write-Host "[!] Virtual environment not found or incomplete. Creating..." -ForegroundColor Yellow
    if (Test-Path ".venv") {
        Remove-Item -Recurse -Force ".venv"
    }
    python -m venv .venv
    Write-Host "[-] Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "[-] Virtual environment already exists and appears valid." -ForegroundColor Green
}

# 4. Install Backend Dependencies
Write-Host "`nInstalling Backend Dependencies..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e .
Write-Host "[-] Backend dependencies installed." -ForegroundColor Green

# 5. Install Playwright Browsers
Write-Host "`nInstalling Playwright Browsers..." -ForegroundColor Yellow
$venvPlaywright = ".\.venv\Scripts\playwright.exe"
& $venvPlaywright install
Write-Host "[-] Playwright browsers installed." -ForegroundColor Green

# 6. Install Frontend Dependencies
Write-Host "`nInstalling Frontend Dependencies..." -ForegroundColor Yellow
if (Test-Path "ui") {
    Push-Location ui
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        npm install
        Write-Host "[-] Frontend dependencies installed." -ForegroundColor Green
    } else {
        Write-Host "[!] npm is not available. Please ensure Node.js installed correctly." -ForegroundColor Red
    }
    Pop-Location
} else {
    Write-Host "[!] 'ui' directory not found. Skipping frontend dependencies." -ForegroundColor Yellow
}

Write-Host "`n=========================================" -ForegroundColor Cyan
Write-Host "  All dependencies installed successfully! " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "To activate the virtual environment, run: .\.venv\Scripts\activate" -ForegroundColor Cyan
