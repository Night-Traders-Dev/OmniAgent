# GPU Worker — Setup & Usage

The GPU Worker offloads heavy tasks (image generation, video generation, result verification) to a second PC on your LAN. It's entirely optional — OmniAgent works without it.

## Architecture

```
Main Server (PC 1)          GPU Worker (PC 2)
RTX 4060 / 8B models        RTX 5070 / 32B models
Port 8000                    Port 8100
        ←── UDP broadcast (auto-discovery) ──→
        ──── E2E encrypted REST calls ────→
```

## Quick Start

### On the second PC (Linux):
```bash
# Copy gpu_worker.py to the second machine
python gpu_worker.py
# First run auto-installs: PyTorch CUDA, diffusers, FastAPI
```

### On the second PC (Windows WSL2):
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\setup-gpu-worker-wsl.ps1
# Then:
wsl -d Ubuntu-22.04 -- bash -c "~/omniagent-worker/start.sh"
```

### On the main server:
```bash
# Auto-discovery (same LAN subnet):
python omni_agent.py
# The worker announces itself via UDP broadcast every 10 seconds

# Manual connection (different subnet or WSL2):
WORKER_URL=http://192.168.1.50:8100 python omni_agent.py
```

## E2E Encryption

All communication between the main server and GPU worker is encrypted with Fernet (AES-128-CBC + HMAC-SHA256). Set the same secret on both machines:

```bash
# GPU Worker
WORKER_SECRET=my-shared-key python gpu_worker.py

# Main Server
WORKER_SECRET=my-shared-key python omni_agent.py
```

The key is derived via PBKDF2 (100K iterations) from the shared secret. Without `WORKER_SECRET`, communication is unencrypted.

## Capabilities

### Image Generation
- Uses diffusers (Stable Diffusion v1.5) on the worker's GPU
- Pipeline cached in VRAM — no per-request load/free
- Falls back to local CPU generation if worker unavailable

### Video Generation
- AnimateDiff via diffusers
- Requires the motion adapter model (auto-downloaded on first use)
- Generates GIF output

### Result Verification
- Runs a prompt through the worker's local Ollama to double-check results
- Independent model checks the primary model's output for correctness
- Set `VERIFY_MODEL` env var to choose the verification model

### Large Model Routing
When enabled (toggle in Acceleration settings), complex coding tasks route to the worker's 32B model:
```bash
# On the worker, install a large model:
ollama pull qwen2.5-coder:32b
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/identify` | GET | Worker info, GPU stats, capabilities |
| `/health` | GET | Health check, uptime |
| `/generate/image` | POST | Generate image from prompt |
| `/generate/video` | POST | Generate video from prompt |
| `/verify` | POST | Verify a result with independent model |
| `/outputs/{file}` | GET | Download generated files |

## WSL2 Notes

WSL2 uses NAT networking, so UDP broadcasts don't reach the Windows LAN. Solutions:
1. Use `WORKER_URL=http://<wsl-ip>:8100` for manual connection
2. The setup script prints the WSL IP address
3. Port forwarding may be needed: `netsh interface portproxy add v4tov4 listenport=8100 listenaddress=0.0.0.0 connectport=8100 connectaddress=<wsl-ip>`

## Monitoring

Check worker status from the main server:
```bash
curl http://localhost:8000/api/workers
```

The worker count is shown in the metrics bar on all platforms.
