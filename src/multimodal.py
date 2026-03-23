"""
Multimodal capabilities: Vision, Image Generation, Voice (STT/TTS), Video Generation.

All integrations are optional — they detect available services and fail gracefully.
- Vision: Ollama multimodal models (Qwen3-VL, LLaVA, Qwen2-VL, llama3.2-vision)
- Image Gen: ComfyUI API or stable-diffusion-webui API (AUTOMATIC1111)
- Voice STT: faster-whisper (local) or Whisper API
- Voice TTS: Coqui XTTS, Bark, or piper-tts
- Video Gen: ComfyUI with AnimateDiff or SVD workflows
"""
import os
import json
import base64
import subprocess
import tempfile
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


# ============================================================
# Vision — Analyze images via Ollama multimodal models
# ============================================================

VISION_MODELS = [
    "qwen3-vl:8b",
    "qwen3-vl",
    "llama3.2-vision",
    "llava:13b",
    "llava:7b",
    "llava",
    "qwen2-vl",
    "minicpm-v",
]

def _detect_vision_model() -> str | None:
    """Find an installed vision-capable model on Ollama."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        installed = [m.get("name", "") for m in data.get("models", [])]
        for vm in VISION_MODELS:
            for inst in installed:
                if vm in inst:
                    return inst
        return None
    except Exception:
        return None


def analyze_image(image_path: str, prompt: str = "Describe this image in detail.") -> str:
    """Analyze an image using a multimodal Ollama model."""
    model = _detect_vision_model()
    if not model:
        return "ERROR: No vision model installed. Install one with: ollama pull qwen3-vl:8b"

    # Read and base64 encode the image
    image_path = os.path.realpath(image_path)
    if not os.path.exists(image_path):
        return f"ERROR: Image not found: {image_path}"
    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        return f"ERROR: Failed to read image: {e}"

    # Call Ollama with image
    try:
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        return data.get("response", "No response from vision model")
    except Exception as e:
        return f"ERROR: Vision analysis failed: {e}"


def analyze_image_base64(img_b64: str, prompt: str = "Describe this image in detail.") -> str:
    """Analyze a base64-encoded image."""
    model = _detect_vision_model()
    if not model:
        return "ERROR: No vision model installed."
    try:
        body = json.dumps({
            "model": model, "prompt": prompt, "images": [img_b64], "stream": False,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        return data.get("response", "No response")
    except Exception as e:
        return f"ERROR: Vision failed: {e}"


# ============================================================
# Image Generation — via ComfyUI or AUTOMATIC1111 API
# ============================================================

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://localhost:8188")
A1111_URL = os.environ.get("A1111_URL", "http://localhost:7860")


def _detect_image_gen_backend() -> str | None:
    """Detect which image gen backend is running."""
    for name, url in [("comfyui", COMFYUI_URL), ("a1111", A1111_URL)]:
        try:
            req = urllib.request.Request(f"{url}/", method="HEAD")
            urllib.request.urlopen(req, timeout=3)
            return name
        except Exception:
            continue
    return None


def _load_diffusers_pipe():
    """Load a Stable Diffusion pipeline on demand. NOT cached — freed after each generation to avoid OOM."""
    try:
        import torch, gc
        from diffusers import StableDiffusionPipeline

        model_id = os.environ.get("SD_MODEL", "runwayml/stable-diffusion-v1-5")

        pipe = StableDiffusionPipeline.from_pretrained(
            model_id, safety_checker=None, torch_dtype=torch.float32,
        )
        pipe.enable_attention_slicing()

        # Only use GPU if plenty of VRAM free
        if torch.cuda.is_available():
            try:
                free_vram = torch.cuda.mem_get_info()[0] / (1024**3)
                if free_vram >= 4.5:
                    pipe = pipe.to("cuda")
            except Exception:
                pass
        return pipe
    except Exception as e:
        import logging
        logging.getLogger("omniagent").warning(f"Failed to load diffusers: {e}")
        return None


def _free_diffusers_pipe(pipe):
    """Free pipeline memory after generation."""
    try:
        import torch, gc
        del pipe
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def generate_image(prompt: str, negative_prompt: str = "", width: int = 512, height: int = 512,
                   steps: int = 20, seed: int = -1) -> dict:
    """Generate an image from a text prompt. Returns {"path": str, "url": str} or {"error": str}.
    Tries GPU worker first (if available), then local backends."""
    if width < 64 or width > 2048 or height < 64 or height > 2048:
        return {"error": "Width/height must be between 64 and 2048"}
    # Round to nearest multiple of 8 (required by diffusers/SD)
    width = (width // 8) * 8
    height = (height // 8) * 8
    if width < 64: width = 64
    if height < 64: height = 64
    if steps < 1 or steps > 150:
        return {"error": "Steps must be between 1 and 150"}
    if not prompt or len(prompt) > 5000:
        return {"error": "Prompt must be 1-5000 characters"}

    # Try GPU worker first (offload to second PC if available)
    try:
        from src.gpu_client import pool
        result = pool.generate_image(prompt, negative_prompt, width, height, steps, seed)
        if result and result.get("ok"):
            return result
    except Exception:
        pass

    # Fall back to local backends
    backend = _detect_image_gen_backend()
    if not backend:
        return _generate_diffusers(prompt, negative_prompt, width, height, steps, seed)

    if backend == "a1111":
        return _generate_a1111(prompt, negative_prompt, width, height, steps, seed)
    elif backend == "comfyui":
        return _generate_comfyui(prompt, negative_prompt, width, height, steps, seed)
    return {"error": f"Unknown backend: {backend}"}


def _generate_a1111(prompt: str, neg: str, w: int, h: int, steps: int, seed: int) -> dict:
    """Generate via AUTOMATIC1111 txt2img API."""
    try:
        body = json.dumps({
            "prompt": prompt,
            "negative_prompt": neg or "blurry, low quality, distorted",
            "width": w, "height": h, "steps": steps,
            "seed": seed if seed >= 0 else -1,
            "sampler_name": "DPM++ 2M Karras",
        }).encode()
        req = urllib.request.Request(
            f"{A1111_URL}/sdapi/v1/txt2img",
            data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
        images = data.get("images", [])
        if not images:
            return {"error": "No images returned"}
        # Save first image
        img_data = base64.b64decode(images[0])
        import secrets
        filename = f"gen_{secrets.token_hex(6)}.png"
        filepath = UPLOAD_DIR / filename
        filepath.write_bytes(img_data)
        return {"path": str(filepath), "filename": filename, "url": f"/uploads/{filename}"}
    except Exception as e:
        return {"error": f"A1111 generation failed: {e}"}


def _generate_comfyui(prompt: str, neg: str, w: int, h: int, steps: int, seed: int) -> dict:
    """Generate via ComfyUI API (simplified workflow)."""
    try:
        # ComfyUI uses workflow JSON — we'll use a simple txt2img workflow
        import secrets
        client_id = secrets.token_hex(8)
        workflow = {
            "prompt": {
                "3": {"class_type": "KSampler", "inputs": {
                    "seed": seed if seed >= 0 else int.from_bytes(os.urandom(4)),
                    "steps": steps, "cfg": 7.0, "sampler_name": "euler",
                    "scheduler": "normal", "denoise": 1.0,
                    "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
                }},
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
                "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg or "blurry, low quality", "clip": ["4", 1]}},
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
                "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": f"omni_{client_id}", "images": ["8", 0]}},
            }
        }
        body = json.dumps(workflow).encode()
        req = urllib.request.Request(
            f"{COMFYUI_URL}/prompt",
            data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
        prompt_id = data.get("prompt_id", "")
        return {"status": "queued", "prompt_id": prompt_id, "note": "ComfyUI image generation queued. Check /api/image/status for completion."}
    except Exception as e:
        return {"error": f"ComfyUI generation failed: {e}"}


def _generate_diffusers(prompt: str, neg: str, w: int, h: int, steps: int, seed: int) -> dict:
    """Generate via HuggingFace diffusers pipeline. Loads and frees model each time to avoid OOM."""
    pipe = _load_diffusers_pipe()
    if pipe is None:
        return {"error": "No image generation available. Install: pip install diffusers torch, or start ComfyUI/A1111."}
    try:
        import torch
        import secrets as _secrets
        device = "cuda" if next(pipe.unet.parameters()).is_cuda else "cpu"
        generator = torch.Generator(device=device)
        if seed >= 0:
            generator.manual_seed(seed)
        else:
            generator.manual_seed(int.from_bytes(os.urandom(4)))

        image = pipe(
            prompt=prompt,
            negative_prompt=neg or "blurry, low quality, distorted",
            width=w, height=h, num_inference_steps=min(steps, 20),
            generator=generator,
        ).images[0]

        filename = f"gen_{_secrets.token_hex(6)}.png"
        filepath = UPLOAD_DIR / filename
        image.save(str(filepath))
        return {"path": str(filepath), "filename": filename, "url": f"/uploads/{filename}"}
    except Exception as e:
        return {"error": f"Diffusers generation failed: {e}"}
    finally:
        _free_diffusers_pipe(pipe)


# ============================================================
# Voice — Speech-to-Text (STT) via faster-whisper
# ============================================================

_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        return _whisper_model
    except ImportError:
        return None


def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio file to text using Whisper."""
    model = _get_whisper()
    if not model:
        return "ERROR: faster-whisper not installed. Install with: pip install faster-whisper"
    try:
        segments, info = model.transcribe(audio_path, beam_size=5)
        text = " ".join(seg.text for seg in segments)
        return text.strip()
    except Exception as e:
        return f"ERROR: Transcription failed: {e}"


def transcribe_audio_bytes(audio_bytes: bytes, fmt: str = "webm") -> str:
    """Transcribe audio from raw bytes."""
    with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as f:
        f.write(audio_bytes)
        f.flush()
        result = transcribe_audio(f.name)
    try:
        os.unlink(f.name)
    except Exception:
        pass
    return result


# ============================================================
# Voice — Text-to-Speech (TTS) via piper or Coqui
# ============================================================

PIPER_VOICE_DIR = Path(os.path.expanduser("~/.local/share/piper-voices"))
_piper_voice = None

def _get_piper_voice():
    """Load piper voice model (cached)."""
    global _piper_voice
    if _piper_voice is not None:
        return _piper_voice
    try:
        from piper import PiperVoice
        # Try to find a voice model
        for voice_name in ["en_US-amy-high", "en_US-amy-medium", "en_US-lessac-high", "en_US-lessac-medium", "en_US-libritts_r-medium"]:
            model_path = PIPER_VOICE_DIR / f"{voice_name}.onnx"
            config_path = PIPER_VOICE_DIR / f"{voice_name}.onnx.json"
            if model_path.exists():
                _piper_voice = PiperVoice.load(str(model_path), config_path=str(config_path) if config_path.exists() else None)
                return _piper_voice
        return None
    except ImportError:
        return None


def synthesize_speech(text: str, voice: str = "en_US-amy-medium") -> dict:
    """Convert text to speech using piper-tts Python API.
    Text is preprocessed to handle abbreviations, symbols, code syntax, etc.
    Returns {"path": str, "url": str} or {"error": str}."""
    import secrets
    import wave

    # Preprocess text for natural speech
    try:
        from src.tts_preprocessor import preprocess_for_tts
        text = preprocess_for_tts(text)
    except Exception:
        pass

    filename = f"tts_{secrets.token_hex(6)}.wav"
    filepath = UPLOAD_DIR / filename

    # Use piper Python API (fast, realistic, CPU-only)
    piper_voice = _get_piper_voice()
    if piper_voice is not None:
        try:
            wav_file = wave.open(str(filepath), "wb")
            piper_voice.synthesize_wav(text, wav_file)
            wav_file.close()
            if filepath.exists() and filepath.stat().st_size > 100:
                return {"path": str(filepath), "filename": filename, "url": f"/uploads/{filename}"}
        except Exception as e:
            pass  # Fall through to CLI

    # Fallback: piper CLI
    try:
        # Try to find the model file for the voice
        model_path = PIPER_VOICE_DIR / f"{voice}.onnx"
        if model_path.exists():
            result = subprocess.run(
                ["piper", "--model", str(model_path), "--output_file", str(filepath)],
                input=text, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and filepath.exists():
                return {"path": str(filepath), "filename": filename, "url": f"/uploads/{filename}"}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return {"error": "No TTS engine available. Install: pip install piper-tts && download a voice model to ~/.local/share/piper-voices/"}


# ============================================================
# Video Generation — via ComfyUI + AnimateDiff
# ============================================================

def generate_video(prompt: str, negative_prompt: str = "", frames: int = 16,
                   width: int = 512, height: int = 512, fps: int = 8) -> dict:
    """Generate a short video clip from a text prompt. Tries GPU worker first."""
    # Try GPU worker first
    try:
        from src.gpu_client import pool
        result = pool.generate_video(prompt, negative_prompt, frames, width, height, fps)
        if result and result.get("ok"):
            return result
    except Exception:
        pass

    # Fall back to local ComfyUI
    backend = _detect_image_gen_backend()
    if backend != "comfyui":
        return {"error": "Video generation requires ComfyUI with AnimateDiff. Start ComfyUI first."}
    try:
        import secrets
        client_id = secrets.token_hex(8)
        # AnimateDiff workflow — simplified
        workflow = {
            "prompt": {
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
                "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt or "blurry, low quality", "clip": ["1", 1]}},
                "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": frames}},
                "5": {"class_type": "KSampler", "inputs": {
                    "seed": int.from_bytes(os.urandom(4)),
                    "steps": 20, "cfg": 7.0, "sampler_name": "euler",
                    "scheduler": "normal", "denoise": 1.0,
                    "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                }},
                "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
                "7": {"class_type": "SaveAnimatedWEBP", "inputs": {
                    "filename_prefix": f"omni_vid_{client_id}",
                    "fps": fps, "lossless": False, "quality": 80, "method": "default",
                    "images": ["6", 0],
                }},
            }
        }
        body = json.dumps(workflow).encode()
        req = urllib.request.Request(
            f"{COMFYUI_URL}/prompt",
            data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return {"status": "queued", "prompt_id": data.get("prompt_id", ""),
                "note": "Video generation queued in ComfyUI. This may take several minutes."}
    except Exception as e:
        return {"error": f"Video generation failed: {e}"}


# ============================================================
# Capability Detection
# ============================================================

def detect_capabilities() -> dict:
    """Detect which multimodal capabilities are available (including GPU workers)."""
    caps = {}
    caps["vision"] = {"available": _detect_vision_model() is not None,
                      "model": _detect_vision_model() or "none"}
    img_backend = _detect_image_gen_backend()
    if img_backend:
        caps["image_gen"] = {"available": True, "backend": img_backend}
    else:
        # Check if diffusers is available as fallback
        try:
            import diffusers
            caps["image_gen"] = {"available": True, "backend": "diffusers"}
        except ImportError:
            caps["image_gen"] = {"available": False, "backend": "none"}
    # Check for GPU workers
    try:
        from src.gpu_client import pool
        ws = pool.get_status()
        if ws["worker_count"] > 0:
            worker = ws["workers"][0]
            if worker["capabilities"].get("image_gen") and not caps["image_gen"]["available"]:
                caps["image_gen"] = {"available": True, "backend": f"gpu-worker:{worker['hostname'] or worker['ip']}"}
            if worker["capabilities"].get("video_gen"):
                caps["video_gen"] = {"available": True, "backend": f"gpu-worker:{worker['hostname'] or worker['ip']}"}
            if worker["capabilities"].get("verification"):
                caps["verification"] = {"available": True, "backend": f"gpu-worker:{worker['hostname'] or worker['ip']}"}
        caps["gpu_workers"] = ws
    except Exception:
        caps["gpu_workers"] = {"worker_count": 0, "workers": []}
    caps["stt"] = {"available": _get_whisper() is not None}
    # TTS detection — check Python API first, then CLI
    if _get_piper_voice() is not None:
        caps["tts"] = {"available": True, "engine": "piper-python"}
    else:
        try:
            subprocess.run(["piper", "--help"], capture_output=True, timeout=5)
            caps["tts"] = {"available": True, "engine": "piper-cli"}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            caps["tts"] = {"available": False}
    caps["video_gen"] = {"available": _detect_image_gen_backend() == "comfyui"}
    return caps
