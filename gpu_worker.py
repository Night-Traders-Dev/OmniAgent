#!/usr/bin/env python3
"""
OmniAgent GPU Worker — Runs on a second machine to offload heavy tasks.

Provides:
  - Image generation (Stable Diffusion / FLUX via diffusers or ComfyUI)
  - Video generation (AnimateDiff / SVD)
  - Result verification (run a prompt through a local LLM to double-check)

Auto-announces itself on the LAN via UDP broadcast so the main server
can discover it without manual configuration.

Works on: Linux, WSL2, Windows (with Python 3.10+)

First run:
    python gpu_worker.py          # auto-installs missing deps
    WORKER_SECRET=mykey python gpu_worker.py   # with E2E encryption
"""
import os
import sys
import json
import time
import socket
import base64
import secrets
import hashlib
import logging
import threading
import subprocess
from pathlib import Path
from contextlib import suppress


# ── First-time dependency installer ──────────────────────────
REQUIRED_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn[standard]",
    "torch": "torch",
    "diffusers": "diffusers[torch]",
    "transformers": "transformers",
    "accelerate": "accelerate",
    "cryptography": "cryptography",
    "pydantic": "pydantic",
}

def _check_and_install_deps():
    """Auto-install missing dependencies on first run."""
    missing = []
    for module, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return True

    print(f"\n{'='*50}")
    print("  OmniAgent GPU Worker — First-time Setup")
    print(f"{'='*50}")
    print(f"\nMissing packages: {', '.join(missing)}")

    # Detect CUDA for PyTorch
    has_nvidia = False
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        has_nvidia = r.returncode == 0
    except Exception:
        pass

    # On WSL, check if nvidia-smi works through /usr/lib/wsl/
    if not has_nvidia and os.path.exists("/usr/lib/wsl/lib/nvidia-smi"):
        try:
            r = subprocess.run(["/usr/lib/wsl/lib/nvidia-smi"], capture_output=True, timeout=5)
            has_nvidia = r.returncode == 0
        except Exception:
            pass

    # Install torch with CUDA if available
    if "torch" in missing:
        missing.remove("torch")
        if has_nvidia:
            print("\nNVIDIA GPU detected — installing PyTorch with CUDA support...")
            torch_cmd = [sys.executable, "-m", "pip", "install", "torch", "torchvision",
                        "--index-url", "https://download.pytorch.org/whl/cu124"]
        else:
            print("\nNo NVIDIA GPU detected — installing PyTorch (CPU only)...")
            torch_cmd = [sys.executable, "-m", "pip", "install", "torch", "torchvision"]
        print(f"  Running: {' '.join(torch_cmd)}")
        subprocess.run(torch_cmd, check=False)

    if missing:
        print(f"\nInstalling: {', '.join(missing)}")
        cmd = [sys.executable, "-m", "pip", "install"] + missing
        print(f"  Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=False)

    # Verify
    still_missing = []
    for module in REQUIRED_PACKAGES:
        try:
            __import__(module)
        except ImportError:
            still_missing.append(module)
    if still_missing:
        print(f"\n[ERROR] Failed to install: {', '.join(still_missing)}")
        print("Install manually: pip install " + " ".join(REQUIRED_PACKAGES[m] for m in still_missing))
        return False
    print("\nAll dependencies installed successfully!\n")
    return True


if not _check_and_install_deps():
    sys.exit(1)


# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [GPU-Worker] %(message)s")
log = logging.getLogger("gpu_worker")



# ── Config ───────────────────────────────────────────────────
WORKER_PORT = int(os.environ.get("WORKER_PORT", "8100"))
BROADCAST_PORT = 5199  # UDP broadcast port for discovery
BROADCAST_INTERVAL = 10  # seconds between announcements
UPLOAD_DIR = Path("./worker_outputs")
UPLOAD_DIR.mkdir(exist_ok=True)

# Shared secret for worker authentication (optional — set WORKER_SECRET env var)
WORKER_SECRET = os.environ.get("WORKER_SECRET", "")

# ── E2E Encryption ───────────────────────────────────────────
_FERNET = None

def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet key from the shared secret using HKDF-like derivation."""
    dk = hashlib.pbkdf2_hmac('sha256', secret.encode(), b'omniagent-gpu-e2e', 100_000)
    return base64.urlsafe_b64encode(dk)

def _init_encryption():
    global _FERNET
    if WORKER_SECRET:
        try:
            from cryptography.fernet import Fernet
            _FERNET = Fernet(_derive_fernet_key(WORKER_SECRET))
            log.info("E2E encryption enabled (Fernet/AES-128-CBC)")
        except ImportError:
            log.warning("cryptography not installed — E2E encryption disabled")

def decrypt_request(raw_body: bytes) -> dict:
    """Decrypt an incoming request body if E2E encrypted."""
    data = json.loads(raw_body)
    if data.get("encrypted") and data.get("payload") and _FERNET:
        return json.loads(_FERNET.decrypt(data["payload"].encode()).decode())
    return data

def encrypt_response(result: dict) -> dict:
    """Encrypt an outgoing response if E2E encryption is active."""
    if _FERNET:
        encrypted = _FERNET.encrypt(json.dumps(result).encode()).decode()
        return {"encrypted": True, "payload": encrypted}
    return result

# ── GPU Info ─────────────────────────────────────────────────
def get_gpu_info() -> dict:
    """Detect NVIDIA GPU info via nvidia-smi."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            return {
                "gpu_name": parts[0],
                "vram_total_mb": int(parts[1]),
                "vram_used_mb": int(parts[2]),
                "temp_c": int(parts[3]),
                "util_pct": int(parts[4]),
            }
    except Exception:
        pass
    return {"gpu_name": "Unknown", "vram_total_mb": 0, "vram_used_mb": 0, "temp_c": 0, "util_pct": 0}


# ── UDP Broadcast Announcer ──────────────────────────────────
def _get_lan_ip() -> str:
    """Get the real LAN IP address (works in WSL2, Linux, Windows)."""
    # Method 1: Connect to external address to determine outbound interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    # Method 2: WSL2 — parse ip addr
    try:
        r = subprocess.run(["ip", "-4", "addr", "show", "eth0"], capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
    except Exception:
        pass
    # Method 3: hostname
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "0.0.0.0"


def _broadcast_loop():
    """Periodically broadcast worker presence on LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    hostname = socket.gethostname()
    local_ip = _get_lan_ip()

    gpu = get_gpu_info()
    payload = json.dumps({
        "service": "OmniAgent-GPU-Worker",
        "version": "1.0",
        "port": WORKER_PORT,
        "ip": local_ip,
        "hostname": hostname,
        "gpu": gpu["gpu_name"],
        "vram_mb": gpu["vram_total_mb"],
    }).encode()

    log.info(f"Broadcasting on UDP {BROADCAST_PORT} — {local_ip}:{WORKER_PORT} ({gpu['gpu_name']})")
    while True:
        try:
            sock.sendto(payload, ("<broadcast>", BROADCAST_PORT))
        except Exception as e:
            log.warning(f"Broadcast failed: {e}")
        time.sleep(BROADCAST_INTERVAL)


# ── FastAPI App ──────────────────────────────────────────────
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="OmniAgent GPU Worker", version="1.0")
app.mount("/outputs", StaticFiles(directory=str(UPLOAD_DIR)), name="outputs")

# ── Auth middleware ──────────────────────────────────────────
@app.middleware("http")
async def check_worker_secret(request: Request, call_next):
    if WORKER_SECRET and request.url.path not in ("/identify", "/health"):
        token = request.headers.get("X-Worker-Secret", "")
        if token != WORKER_SECRET:
            return JSONResponse({"error": "Invalid worker secret"}, status_code=403)
    return await call_next(request)


# ── Identity / Health ────────────────────────────────────────
@app.get("/identify")
async def identify():
    gpu = get_gpu_info()
    return JSONResponse({
        "service": "OmniAgent-GPU-Worker",
        "version": "1.0",
        "gpu": gpu,
        "capabilities": _detect_capabilities(),
        "hostname": socket.gethostname(),
    })

@app.get("/health")
async def health():
    gpu = get_gpu_info()
    return JSONResponse({
        "status": "ok",
        "gpu": gpu,
        "uptime": int(time.time() - _start_time),
    })


# ── Image Generation ────────────────────────────────────────
class ImageGenReq(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    seed: int = -1
    model: str = ""  # optional model override

_diffusers_pipe = None
_diffusers_lock = threading.Lock()

def _load_pipe(model_id: str = ""):
    """Load diffusers pipeline. Cached in memory for the worker's lifetime."""
    global _diffusers_pipe
    if _diffusers_pipe is not None:
        return _diffusers_pipe
    try:
        import torch
        from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler

        model = model_id or os.environ.get("SD_MODEL", "runwayml/stable-diffusion-v1-5")
        log.info(f"Loading diffusers model: {model}")
        pipe = StableDiffusionPipeline.from_pretrained(
            model, torch_dtype=torch.float16, safety_checker=None,
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        pipe = pipe.to("cuda")
        pipe.enable_attention_slicing()
        # Try xformers for memory efficiency
        with suppress(Exception):
            pipe.enable_xformers_memory_efficient_attention()
        _diffusers_pipe = pipe
        log.info("Diffusers pipeline loaded on GPU")
        return pipe
    except Exception as e:
        log.error(f"Failed to load diffusers: {e}")
        return None


@app.post("/generate/image")
async def generate_image(request: Request):
    """Generate an image and return the URL (E2E encrypted)."""
    import asyncio
    body = await request.body()
    data = decrypt_request(body)
    req = ImageGenReq(**data)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _generate_image_sync, req)
    return JSONResponse(encrypt_response(result))

def _generate_image_sync(req: ImageGenReq) -> dict:
    with _diffusers_lock:
        pipe = _load_pipe(req.model)
        if pipe is None:
            return {"error": "No image generation backend available"}
        try:
            import torch
            w = (req.width // 8) * 8
            h = (req.height // 8) * 8
            w = max(64, min(2048, w))
            h = max(64, min(2048, h))

            gen = torch.Generator(device="cuda")
            if req.seed >= 0:
                gen.manual_seed(req.seed)
            else:
                gen.manual_seed(int.from_bytes(os.urandom(4)))

            image = pipe(
                prompt=req.prompt,
                negative_prompt=req.negative_prompt or "blurry, low quality, distorted",
                width=w, height=h,
                num_inference_steps=min(req.steps, 50),
                generator=gen,
            ).images[0]

            filename = f"gen_{secrets.token_hex(6)}.png"
            filepath = UPLOAD_DIR / filename
            image.save(str(filepath))
            log.info(f"Generated image: {filename} ({w}x{h}, {req.steps} steps)")
            return {"ok": True, "filename": filename, "url": f"/outputs/{filename}", "width": w, "height": h}
        except Exception as e:
            log.error(f"Image generation failed: {e}")
            return {"error": str(e)}


# ── Video Generation ─────────────────────────────────────────
class VideoGenReq(BaseModel):
    prompt: str
    negative_prompt: str = ""
    frames: int = 16
    width: int = 512
    height: int = 512
    fps: int = 8
    model: str = ""

@app.post("/generate/video")
async def generate_video(request: Request):
    """Generate a short video clip (E2E encrypted)."""
    import asyncio
    body = await request.body()
    data = decrypt_request(body)
    req = VideoGenReq(**data)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _generate_video_sync, req)
    return JSONResponse(encrypt_response(result))

def _generate_video_sync(req: VideoGenReq) -> dict:
    """Video generation via AnimateDiff or SVD."""
    try:
        import torch
        from diffusers import AnimateDiffPipeline, MotionAdapter, DDIMScheduler
        from diffusers.utils import export_to_gif

        adapter = MotionAdapter.from_pretrained("guoyww/animatediff-motion-adapter-v1-5-3", torch_dtype=torch.float16)
        model_id = req.model or "runwayml/stable-diffusion-v1-5"
        pipe = AnimateDiffPipeline.from_pretrained(model_id, motion_adapter=adapter, torch_dtype=torch.float16)
        pipe.scheduler = DDIMScheduler.from_pretrained(
            model_id, subfolder="scheduler", clip_sample=False, timestep_spacing="linspace",
            beta_schedule="linear", steps_offset=1,
        )
        pipe = pipe.to("cuda")
        pipe.enable_attention_slicing()

        gen = torch.Generator(device="cuda").manual_seed(int.from_bytes(os.urandom(4)))
        output = pipe(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt or "blurry, low quality",
            num_frames=min(req.frames, 32),
            width=(req.width // 8) * 8,
            height=(req.height // 8) * 8,
            num_inference_steps=20,
            generator=gen,
        )
        filename = f"vid_{secrets.token_hex(6)}.gif"
        filepath = UPLOAD_DIR / filename
        export_to_gif(output.frames[0], str(filepath), fps=req.fps)
        log.info(f"Generated video: {filename}")

        # Free memory
        del pipe, adapter
        import gc; gc.collect()
        torch.cuda.empty_cache()

        return {"ok": True, "filename": filename, "url": f"/outputs/{filename}"}
    except ImportError:
        return {"error": "AnimateDiff not available. Install: pip install diffusers[torch] transformers accelerate"}
    except Exception as e:
        log.error(f"Video generation failed: {e}")
        return {"error": str(e)}


# ── Result Verification ──────────────────────────────────────
class VerifyReq(BaseModel):
    original_prompt: str
    original_result: str
    verification_prompt: str = ""  # optional custom check

@app.post("/verify")
async def verify_result(request: Request):
    """Double-check a result using a local Ollama model (E2E encrypted)."""
    import asyncio
    body = await request.body()
    data = decrypt_request(body)
    req = VerifyReq(**data)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _verify_sync, req)
    return JSONResponse(encrypt_response(result))

def _verify_sync(req: VerifyReq) -> dict:
    """Run verification through local Ollama."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

        check_prompt = req.verification_prompt or (
            f"You are a verification assistant. The user asked: \"{req.original_prompt}\"\n\n"
            f"Another AI produced this result:\n\"\"\"\n{req.original_result[:3000]}\n\"\"\"\n\n"
            "Evaluate the result for:\n"
            "1. Correctness — Are there factual errors?\n"
            "2. Completeness — Did it fully answer the question?\n"
            "3. Safety — Any dangerous or harmful content?\n\n"
            "Respond with a JSON object: {\"correct\": true/false, \"score\": 0-10, \"issues\": [\"...\"], \"summary\": \"...\"}"
        )

        response = client.chat.completions.create(
            model=os.environ.get("VERIFY_MODEL", "qwen3:8b"),
            messages=[{"role": "user", "content": check_prompt}],
            temperature=0.1,
        )
        reply = response.choices[0].message.content
        # Try to parse as JSON
        try:
            # Find JSON in the response
            import re
            m = re.search(r'\{[^{}]*"correct"[^{}]*\}', reply, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                return {"ok": True, "verification": parsed, "raw": reply}
        except Exception:
            pass
        return {"ok": True, "verification": {"raw_response": reply}, "raw": reply}
    except Exception as e:
        return {"error": f"Verification failed: {e}"}


# ── Capability Detection ─────────────────────────────────────
def _detect_capabilities() -> dict:
    caps = {}
    # Image gen
    try:
        import diffusers
        caps["image_gen"] = True
    except ImportError:
        caps["image_gen"] = False
    # Video gen
    try:
        from diffusers import AnimateDiffPipeline
        caps["video_gen"] = True
    except ImportError:
        caps["video_gen"] = False
    # Verification (Ollama)
    try:
        import urllib.request
        r = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        caps["verification"] = True
    except Exception:
        caps["verification"] = False
    # GPU
    gpu = get_gpu_info()
    caps["gpu_name"] = gpu["gpu_name"]
    caps["vram_mb"] = gpu["vram_total_mb"]
    return caps


# ── Startup ──────────────────────────────────────────────────
_start_time = time.time()

def main():
    # Initialize E2E encryption
    _init_encryption()

    # Start broadcast thread
    t = threading.Thread(target=_broadcast_loop, daemon=True)
    t.start()

    lan_ip = _get_lan_ip()
    is_wsl = os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop") or "microsoft" in (os.uname().release if hasattr(os, 'uname') else "").lower()
    log.info(f"GPU Worker starting on port {WORKER_PORT}")
    log.info(f"LAN IP: {lan_ip}{'  (WSL2 detected)' if is_wsl else ''}")
    log.info(f"GPU: {get_gpu_info()['gpu_name']}")
    log.info(f"E2E Encryption: {'enabled' if _FERNET else 'disabled (set WORKER_SECRET)'}")
    log.info(f"Capabilities: {_detect_capabilities()}")
    if is_wsl:
        log.info("WSL2 Note: If auto-discovery doesn't work, add the worker manually:")
        log.info(f"  Main server → set WORKER_URL=http://{lan_ip}:{WORKER_PORT}")

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=WORKER_PORT, log_level="info")

if __name__ == "__main__":
    main()
