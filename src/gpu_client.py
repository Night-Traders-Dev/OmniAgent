"""
GPU Worker client — discovers and communicates with remote GPU workers on the LAN.

Workers are discovered via UDP broadcast (port 5199). The client maintains a
list of available workers and routes requests to the best one. If no worker is
available, all methods return None so the main server can fall back to local generation.

All communication uses end-to-end encryption:
  - Shared secret → Fernet key (HKDF-SHA256)
  - Request bodies encrypted with Fernet before sending
  - Responses decrypted on receipt
  - /identify and /health are unencrypted (no sensitive data)
"""
import json
import socket
import threading
import time
import logging
import hashlib
import base64
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("gpu_client")

BROADCAST_PORT = 5199
WORKER_SECRET = ""  # Set via set_secret() if the worker requires auth
_FERNET = None  # Initialized when secret is set


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet key from the shared secret using HKDF-like derivation."""
    # Per-secret salt (derived from the secret itself) + 600k iterations (2024 standard)
    salt = hashlib.sha256(b'omniagent-gpu-e2e-' + secret.encode()).digest()
    dk = hashlib.pbkdf2_hmac('sha256', secret.encode(), salt, 600_000)
    return base64.urlsafe_b64encode(dk)

def _get_fernet():
    global _FERNET
    if _FERNET is None and WORKER_SECRET:
        from cryptography.fernet import Fernet
        _FERNET = Fernet(_derive_fernet_key(WORKER_SECRET))
    return _FERNET

def _encrypt_payload(data: dict) -> str:
    f = _get_fernet()
    if not f:
        return json.dumps(data)
    return f.encrypt(json.dumps(data).encode()).decode()

def _decrypt_payload(data: str) -> dict:
    f = _get_fernet()
    if not f:
        return json.loads(data)
    try:
        return json.loads(f.decrypt(data.encode()).decode())
    except Exception:
        return json.loads(data)  # Fallback for unencrypted responses


@dataclass
class GPUWorker:
    ip: str
    port: int
    hostname: str = ""
    gpu_name: str = ""
    vram_mb: int = 0
    capabilities: dict = field(default_factory=dict)
    last_seen: float = 0.0
    base_url: str = ""

    def __post_init__(self):
        self.base_url = f"http://{self.ip}:{self.port}"

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < 30  # 30s timeout


class GPUWorkerPool:
    """Manages discovered GPU workers. Thread-safe."""

    def __init__(self):
        self._workers: dict[str, GPUWorker] = {}  # key: ip:port
        self._lock = threading.Lock()
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False

    def start_discovery(self):
        """Start listening for UDP broadcast announcements."""
        if self._running:
            return
        self._running = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()
        log.info("GPU worker discovery started on UDP %d", BROADCAST_PORT)

    def stop_discovery(self):
        self._running = False

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.bind(("", BROADCAST_PORT))
        sock.settimeout(5.0)

        while self._running:
            try:
                data, addr = sock.recvfrom(4096)
                msg = json.loads(data.decode())
                if msg.get("service") == "OmniAgent-GPU-Worker":
                    ip = msg.get("ip", addr[0])
                    port = msg.get("port", 8100)
                    key = f"{ip}:{port}"
                    with self._lock:
                        if key not in self._workers:
                            log.info("Discovered GPU worker: %s (%s, %dMB VRAM)",
                                     key, msg.get("gpu", "?"), msg.get("vram_mb", 0))
                            # Fetch full capabilities
                            caps = self._fetch_capabilities(ip, port)
                            self._workers[key] = GPUWorker(
                                ip=ip, port=port,
                                hostname=msg.get("hostname", ""),
                                gpu_name=msg.get("gpu", ""),
                                vram_mb=msg.get("vram_mb", 0),
                                capabilities=caps,
                                last_seen=time.time(),
                            )
                        else:
                            self._workers[key].last_seen = time.time()
            except socket.timeout:
                continue
            except Exception as e:
                log.debug("Discovery error: %s", e)

    def _fetch_capabilities(self, ip: str, port: int) -> dict:
        try:
            req = urllib.request.Request(f"http://{ip}:{port}/identify")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return data.get("capabilities", {})
        except Exception:
            return {}

    @property
    def workers(self) -> list[GPUWorker]:
        with self._lock:
            return [w for w in self._workers.values() if w.is_alive]

    def best_worker(self, capability: str = "") -> Optional[GPUWorker]:
        """Get the best available worker, optionally filtering by capability."""
        alive = self.workers
        if capability:
            alive = [w for w in alive if w.capabilities.get(capability)]
        if not alive:
            return None
        # Prefer worker with most VRAM
        return max(alive, key=lambda w: w.vram_mb)

    def get_status(self) -> dict:
        """Get status summary for UI display."""
        alive = self.workers
        return {
            "worker_count": len(alive),
            "workers": [
                {
                    "ip": w.ip, "port": w.port, "hostname": w.hostname,
                    "gpu": w.gpu_name, "vram_mb": w.vram_mb,
                    "capabilities": w.capabilities,
                    "last_seen": int(time.time() - w.last_seen),
                }
                for w in alive
            ],
        }

    # ── API Calls ────────────────────────────────────────────

    def _call(self, worker: GPUWorker, path: str, body: dict, timeout: int = 300) -> Optional[dict]:
        """Make an E2E encrypted POST to a worker. Returns None on failure."""
        try:
            encrypted = _encrypt_payload(body)
            data = json.dumps({"encrypted": True, "payload": encrypted}).encode()
            req = urllib.request.Request(
                f"{worker.base_url}{path}",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "X-Worker-Secret": WORKER_SECRET,
                    "X-E2E": "fernet",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
                resp_json = json.loads(raw)
                # Decrypt response if encrypted
                if resp_json.get("encrypted") and resp_json.get("payload"):
                    return _decrypt_payload(resp_json["payload"])
                return resp_json
        except Exception as e:
            log.warning("Worker %s:%d call failed: %s", worker.ip, worker.port, e)
            return None

    def generate_image(self, prompt: str, negative_prompt: str = "",
                       width: int = 512, height: int = 512,
                       steps: int = 20, seed: int = -1) -> Optional[dict]:
        """Offload image generation to a GPU worker. Returns None if no worker available."""
        worker = self.best_worker("image_gen")
        if not worker:
            return None
        result = self._call(worker, "/generate/image", {
            "prompt": prompt, "negative_prompt": negative_prompt,
            "width": width, "height": height, "steps": steps, "seed": seed,
        })
        if result and result.get("ok"):
            # Download the image from worker to local uploads
            return self._fetch_output(worker, result)
        return result

    def generate_video(self, prompt: str, negative_prompt: str = "",
                       frames: int = 16, width: int = 512, height: int = 512,
                       fps: int = 8) -> Optional[dict]:
        """Offload video generation to a GPU worker."""
        worker = self.best_worker("video_gen")
        if not worker:
            return None
        result = self._call(worker, "/generate/video", {
            "prompt": prompt, "negative_prompt": negative_prompt,
            "frames": frames, "width": width, "height": height, "fps": fps,
        }, timeout=600)
        if result and result.get("ok"):
            return self._fetch_output(worker, result)
        return result

    def verify_result(self, original_prompt: str, original_result: str,
                      verification_prompt: str = "") -> Optional[dict]:
        """Send a result to a worker for independent verification."""
        worker = self.best_worker("verification")
        if not worker:
            return None
        return self._call(worker, "/verify", {
            "original_prompt": original_prompt,
            "original_result": original_result,
            "verification_prompt": verification_prompt,
        }, timeout=120)

    def _fetch_output(self, worker: GPUWorker, result: dict) -> dict:
        """Download a generated file from the worker to local uploads."""
        filename = result.get("filename", "")
        remote_url = result.get("url", "")
        if not filename or not remote_url:
            return result
        try:
            from pathlib import Path
            local_dir = Path(__file__).resolve().parent.parent / "uploads"
            local_dir.mkdir(exist_ok=True)
            full_url = f"{worker.base_url}{remote_url}"
            req = urllib.request.Request(full_url, headers={"X-Worker-Secret": WORKER_SECRET})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            local_path = local_dir / filename
            local_path.write_bytes(data)
            return {
                "ok": True,
                "filename": filename,
                "path": str(local_path),
                "url": f"/uploads/{filename}",
                "source": f"gpu-worker:{worker.hostname or worker.ip}",
                "width": result.get("width"),
                "height": result.get("height"),
            }
        except Exception as e:
            log.warning("Failed to fetch output from worker: %s", e)
            return result


# ── Global instance ──────────────────────────────────────────
pool = GPUWorkerPool()


def set_secret(secret: str):
    global WORKER_SECRET, _FERNET
    WORKER_SECRET = secret
    _FERNET = None  # Force re-derive on next use
    if secret:
        _get_fernet()  # Pre-derive key


def add_worker_manually(url: str):
    """Manually register a GPU worker by URL (for WSL2 or non-broadcast setups).
    E.g.: add_worker_manually("http://192.168.1.50:8100")
    """
    url = url.rstrip("/")
    parts = url.replace("http://", "").replace("https://", "").split(":")
    ip = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 8100
    key = f"{ip}:{port}"
    caps = {}
    hostname = ""
    gpu_name = ""
    vram = 0
    try:
        req = urllib.request.Request(f"http://{ip}:{port}/identify")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            caps = data.get("capabilities", {})
            hostname = data.get("hostname", "")
            gpu_info = data.get("gpu", {})
            gpu_name = gpu_info.get("gpu_name", "")
            vram = gpu_info.get("vram_total_mb", 0)
    except Exception as e:
        log.warning("Failed to reach worker at %s: %s", url, e)
        return False

    with pool._lock:
        pool._workers[key] = GPUWorker(
            ip=ip, port=port, hostname=hostname,
            gpu_name=gpu_name, vram_mb=vram,
            capabilities=caps, last_seen=time.time(),
        )
    log.info("Manually added worker: %s (%s, %dMB VRAM)", key, gpu_name, vram)
    return True
