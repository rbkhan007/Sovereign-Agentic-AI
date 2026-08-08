"""Local image generation via Stable Diffusion (diffusers), resource-safe.

The AMD RX 5600 XT has no ROCm support, so torch runs on CPU. To avoid
overloading the machine this module:

  * is opt-in via CONFIG.image_gen.enabled (default off);
  * runs on CPU only, one image at a time (global lock);
  * caps resolution and steps and checks free RAM before generating;
  * releases the pipeline (gc.collect) after every generation.

Output PNGs are written to generated/ and served back as a URL path so the
Web UI can render them directly.
"""

import gc
import os
import threading
import time
import uuid

from config import CONFIG

_GENERATED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
_LOCK = threading.Lock()


def _available_ram_mb() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().available / (1024 ** 2))
    except ImportError:
        # psutil missing: fall back to a conservative-but-usable estimate so the
        # guard does not permanently block the feature on minimal installs.
        return 8192


def image_gen_enabled() -> bool:
    return bool(getattr(CONFIG, "image_gen", None) and CONFIG.image_gen.get("enabled"))


def image_gen_config() -> dict:
    c = getattr(CONFIG, "image_gen", {}) or {}
    return {
        "enabled": bool(c.get("enabled")),
        "model": c.get("model", "runwayml/stable-diffusion-v1-5"),
        "width": c.get("width", 384),
        "height": c.get("height", 384),
        "steps": c.get("steps", 18),
        "device": "cpu",
        "deps_available": _deps_available(),
    }


def _deps_available() -> bool:
    for mod in ("diffusers", "torch", "PIL"):
        try:
            __import__(mod)
        except ImportError:
            return False
    return True


def _round8(value: int) -> int:
    """Round to the nearest multiple of 8 (the Stable Diffusion VAE requirement)."""
    return max(8, int(round(value / 8.0)) * 8)


def _cap(value, low, high, default):
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = default
    if v <= 0:
        # 0/omitted means "use the configured default", not the hard minimum.
        v = default
    # Clamp the default itself so a misconfigured config value cannot bypass
    # the documented hardware guards (e.g. width=2048 -> capped to 512).
    return max(low, min(high, v))


def generate_image(prompt: str, width: int = 0, height: int = 0,
                   steps: int = 0) -> dict:
    """Generate an image from a text prompt. Raises ValueError on misuse."""
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")
    if not image_gen_enabled():
        raise ValueError(
            "Image generation is disabled. Enable it with --image-gen or "
            "POST /v1/config key 'image_gen.enabled' = true."
        )
    if not _deps_available():
        raise ValueError(
            "Image generation unavailable: install diffusers (pip install diffusers)"
        )
    if _available_ram_mb() < 4096:
        raise ValueError("Not enough free RAM (< 4 GB) for image generation right now")

    c = getattr(CONFIG, "image_gen", {}) or {}
    width = _cap(width, 256, 512, c.get("width", 384))
    height = _cap(height, 256, 512, c.get("height", 384))
    steps = _cap(steps, 8, 40, c.get("steps", 18))
    width = _round8(width)
    height = _round8(height)
    model_id = c.get("model", "runwayml/stable-diffusion-v1-5")

    with _LOCK:
        return _run_sd(model_id, prompt.strip(), width, height, steps)


def _run_sd(model_id: str, prompt: str, width: int, height: int, steps: int) -> dict:
    start = time.time()
    os.makedirs(_GENERATED_DIR, exist_ok=True)
    pipe = None
    try:
        from diffusers import StableDiffusionPipeline
        import torch

        dtype = torch.float32
        pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=dtype)
        pipe = pipe.to("cpu")
        pipe.enable_attention_slicing()

        image = pipe(
            prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            generator=torch.Generator("cpu").manual_seed(int(time.time()) % (2 ** 31)),
        ).images[0]

        fname = f"{uuid.uuid4().hex[:12]}.png"
        path = os.path.join(_GENERATED_DIR, fname)
        image.save(path)
        elapsed = time.time() - start
        return {
            "status": "ok",
            "url": f"/generated/{fname}",
            "path": path,
            "model": model_id,
            "width": width,
            "height": height,
            "steps": steps,
            "elapsed_s": round(elapsed, 1),
        }
    finally:
        # Free the pipeline + any cached tensors so memory returns before the next op.
        if pipe is not None:
            try:
                del pipe
            except Exception:
                pass
        gc.collect()
