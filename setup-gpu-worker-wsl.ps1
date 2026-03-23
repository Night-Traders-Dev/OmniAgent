<#
.SYNOPSIS
    OmniAgent GPU Worker - WSL2 Setup Script
.DESCRIPTION
    Sets up WSL2 with Ubuntu, NVIDIA CUDA, Python, and the GPU worker.
    Run as Administrator on the Windows PC with the NVIDIA GPU.
.EXAMPLE
    Set-ExecutionPolicy Bypass -Scope Process -Force
    .\setup-gpu-worker-wsl.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  OmniAgent GPU Worker - WSL2 Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- Check Admin ---
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[!] This script requires Administrator privileges." -ForegroundColor Red
    Write-Host "    Right-click PowerShell -> Run as Administrator" -ForegroundColor Yellow
    exit 1
}

# --- Step 1: Enable WSL2 ---
Write-Host "[1/6] Checking WSL2..." -ForegroundColor Green

$wslInstalled = $false
try {
    $wslOutput = & wsl --version 2>&1 | Out-String
    if ($wslOutput -match "WSL") { $wslInstalled = $true }
} catch {}

if (-not $wslInstalled) {
    Write-Host "  Installing WSL2..." -ForegroundColor Yellow
    & wsl --install --no-distribution
    Write-Host ""
    Write-Host "[!] WSL2 installed. RESTART your computer, then run this script again." -ForegroundColor Red
    exit 0
} else {
    Write-Host "  WSL2 is installed." -ForegroundColor Gray
}

# --- Step 2: Install Ubuntu ---
Write-Host "[2/6] Checking Ubuntu distribution..." -ForegroundColor Green

$distros = & wsl -l -q 2>&1 | Out-String
if ($distros -notmatch "Ubuntu") {
    Write-Host "  Installing Ubuntu 22.04..." -ForegroundColor Yellow
    & wsl --install -d Ubuntu-22.04
    Write-Host "  Ubuntu installed. Set up your username/password when prompted." -ForegroundColor Yellow
    Write-Host "  Then run this script again." -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "  Ubuntu is installed." -ForegroundColor Gray
}

# --- Step 3: Verify NVIDIA GPU in WSL2 ---
Write-Host "[3/6] Checking NVIDIA GPU access in WSL2..." -ForegroundColor Green

$nvidiaSmi = & wsl -d Ubuntu-22.04 -- bash -c 'nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null; echo "EXIT:$?"' 2>&1 | Out-String
if ($nvidiaSmi -match "EXIT:0" -and $nvidiaSmi -notmatch "NVIDIA-SMI has failed") {
    $gpuName = ($nvidiaSmi -split "`n")[0].Trim()
    Write-Host "  GPU detected: $gpuName" -ForegroundColor Gray
} else {
    Write-Host "  [!] NVIDIA GPU not detected in WSL2." -ForegroundColor Red
    Write-Host "  Make sure you have:" -ForegroundColor Yellow
    Write-Host "    1. Latest NVIDIA Game Ready or Studio drivers on Windows" -ForegroundColor Yellow
    Write-Host "    2. Windows 11 or Windows 10 21H2+" -ForegroundColor Yellow
    Write-Host "  Download: https://www.nvidia.com/Download/index.aspx" -ForegroundColor Cyan
    exit 1
}

# --- Step 4: Install Python + Dependencies ---
Write-Host "[4/6] Installing Python and dependencies in WSL2..." -ForegroundColor Green

$installCmd = @(
    'set -e',
    'echo "  Updating packages..."',
    'sudo apt-get update -qq',
    'echo "  Installing Python..."',
    'sudo apt-get install -y -qq python3 python3-pip python3-venv > /dev/null 2>&1',
    'echo "  Creating virtual environment..."',
    'mkdir -p ~/omniagent-worker',
    'cd ~/omniagent-worker',
    'python3 -m venv .venv',
    'source .venv/bin/activate',
    'echo "  Installing PyTorch with CUDA (this may take a few minutes)..."',
    'pip install --quiet torch torchvision --index-url https://download.pytorch.org/whl/cu124',
    'echo "  Installing remaining dependencies..."',
    'pip install --quiet fastapi uvicorn diffusers transformers accelerate cryptography pydantic',
    'echo "  Done!"',
    'python3 -c "import torch; print(f\"  PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}\")"'
) -join '; '

& wsl -d Ubuntu-22.04 -- bash -c $installCmd

# --- Step 5: Copy gpu_worker.py ---
Write-Host "[5/6] Copying GPU worker script..." -ForegroundColor Green

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workerScript = Join-Path $scriptDir "gpu_worker.py"

if (Test-Path $workerScript) {
    $winPath = $workerScript -replace '\\', '/'
    $wslWorkerPath = & wsl -d Ubuntu-22.04 -- wslpath -u $winPath 2>&1 | Out-String
    $wslWorkerPath = $wslWorkerPath.Trim()
    & wsl -d Ubuntu-22.04 -- bash -c "cp '$wslWorkerPath' ~/omniagent-worker/gpu_worker.py"
    Write-Host "  Copied gpu_worker.py" -ForegroundColor Gray
} else {
    Write-Host "  [!] gpu_worker.py not found at: $workerScript" -ForegroundColor Red
    Write-Host "  Copy it manually into WSL: ~/omniagent-worker/gpu_worker.py" -ForegroundColor Yellow
}

# --- Step 6: Create start script ---
Write-Host "[6/6] Creating start script..." -ForegroundColor Green

$startLines = @(
    '#!/bin/bash',
    'cd ~/omniagent-worker',
    'source .venv/bin/activate',
    'echo "Starting OmniAgent GPU Worker..."',
    'GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null)',
    'echo "  GPU: $GPU_NAME"',
    'echo "  Port: 8100"',
    'if [ -n "$WORKER_SECRET" ]; then echo "  E2E Encryption: enabled"; else echo "  E2E Encryption: disabled (set WORKER_SECRET)"; fi',
    'echo ""',
    'python3 gpu_worker.py'
)
$startContent = $startLines -join "`n"

# Write via echo commands to avoid heredoc issues
& wsl -d Ubuntu-22.04 -- bash -c "rm -f ~/omniagent-worker/start.sh"
foreach ($line in $startLines) {
    $escaped = $line -replace "'", "'\''"
    & wsl -d Ubuntu-22.04 -- bash -c "echo '$escaped' >> ~/omniagent-worker/start.sh"
}
& wsl -d Ubuntu-22.04 -- bash -c "chmod +x ~/omniagent-worker/start.sh"

Write-Host "  Created ~/omniagent-worker/start.sh" -ForegroundColor Gray

# --- Done ---
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the GPU worker:" -ForegroundColor White
Write-Host '  wsl -d Ubuntu-22.04 -- bash -c "~/omniagent-worker/start.sh"' -ForegroundColor Cyan
Write-Host ""
Write-Host "With E2E encryption:" -ForegroundColor White
Write-Host '  wsl -d Ubuntu-22.04 -- bash -c "WORKER_SECRET=mykey ~/omniagent-worker/start.sh"' -ForegroundColor Cyan
Write-Host ""
Write-Host "To install Ollama for verification + Large Model routing:" -ForegroundColor White
Write-Host '  wsl -d Ubuntu-22.04 -- bash -c "curl -fsSL https://ollama.ai/install.sh | sh"' -ForegroundColor Cyan
Write-Host '  wsl -d Ubuntu-22.04 -- bash -c "ollama pull qwen2.5-coder:32b"' -ForegroundColor Cyan
Write-Host ""
Write-Host "On your main OmniAgent server:" -ForegroundColor White
Write-Host "  WORKER_SECRET=mykey python omni_agent.py" -ForegroundColor Cyan
Write-Host ""

# Try to show the WSL IP for manual connection
try {
    $wslIpRaw = & wsl -d Ubuntu-22.04 -- hostname -I 2>&1 | Out-String
    $wslIp = $wslIpRaw.Trim().Split(" ")[0]
    if ($wslIp -match "\d+\.\d+\.\d+\.\d+") {
        Write-Host "WSL2 IP: $wslIp" -ForegroundColor Gray
        Write-Host "If auto-discovery fails, add manually:" -ForegroundColor Gray
        Write-Host "  WORKER_URL=http://${wslIp}:8100 python omni_agent.py" -ForegroundColor Cyan
    }
} catch {}

Write-Host ""
