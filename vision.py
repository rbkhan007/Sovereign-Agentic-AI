"""Local image understanding via transformers VLMs (Gemma 3 / PaliGemma / moondream2), resource-safe.

The RX 5600 XT has no ROCm support and the installed llama-cpp-python build
lacks CLIP/vision support, so image understanding runs on CPU via transformers.
The default model is Google Gemma 3 4B (google/gemma-3-4b-it), with PaliGemma
and the older moondream2 supported as drop-in alternatives. To avoid overloading
the machine this module:

  * is enabled via CONFIG.vision.enabled (default on; model lazy-loads on demand);
  * lazy-loads the model once, guarded by a free-RAM check (>= 8 GB);
  * serializes inference behind a global lock (one analysis at a time);
  * releases the model on `vision.release()` / low-RAM emergency.

Gemma-family models use the processor + `generate` API (AutoProcessor /
AutoModelForImageTextToText); moondream2 keeps its `answer_question` pipeline.

Endpoints: GET /v1/vision/config, POST /v1/vision/analyze.
"""

import base64
import gc
import re
import threading
import time
from typing import Any

from config import CONFIG

_VISION_LOCK = threading.Lock()
_vision_model: Any = None
_vision_processor: Any = None
_vision_loaded = False
_MODEL_ID_DEFAULT = "google/gemma-3-4b-it"
_MIN_FREE_RAM_MB = 8192


def vision_enabled() -> bool:
    return bool(getattr(CONFIG, "vision", None) and CONFIG.vision.get("enabled"))


def _deps_available() -> bool:
    for mod in ("torch", "transformers", "PIL"):
        try:
            __import__(mod)
        except ImportError:
            return False
    return True


def _available_ram_mb() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().available / (1024 ** 2))
    except ImportError:
        # psutil missing: assume a conservative-but-usable amount so the guard
        # does not permanently block the feature on minimal installs.
        return 8192


def _is_gemma(model_id: str) -> bool:
    m = model_id.lower()
    return "gemma" in m or "paligemma" in m


def vision_config() -> dict:
    c = getattr(CONFIG, "vision", {}) or {}
    return {
        "enabled": vision_enabled(),
        "model": c.get("model", _MODEL_ID_DEFAULT),
        "max_tokens": c.get("max_tokens", 200),
        "device": "cpu",
        "deps_available": _deps_available(),
        "loaded": _vision_loaded,
    }


def _load_model():
    """Load the configured VLM (Gemma 3 / PaliGemma / moondream2) on CPU.

    Raises ValueError when dependencies are missing, RAM is too low, or the
    model cannot be fetched."""
    global _vision_model, _vision_processor, _vision_loaded
    with _VISION_LOCK:
        if _vision_loaded:
            return
        if not _deps_available():
            raise ValueError("Vision unavailable: install transformers + torch (pip install transformers torch)")
        if _available_ram_mb() < _MIN_FREE_RAM_MB:
            raise ValueError(
                f"Not enough free RAM ({_available_ram_mb()} MB < {_MIN_FREE_RAM_MB} MB) "
                "to load the vision model right now"
            )
        c = getattr(CONFIG, "vision", {}) or {}
        model_id = c.get("model", _MODEL_ID_DEFAULT)
        if _is_gemma(model_id):
            from transformers import AutoModelForImageTextToText, AutoProcessor  # noqa: PLC0415
            try:
                processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)  # nosec B615
                model = AutoModelForImageTextToText.from_pretrained(model_id, trust_remote_code=True)  # nosec B615
            except (ValueError, OSError, TypeError):
                # Fall back for PaliGemma checkpoints exposed as a causal LM.
                from transformers import AutoModelForCausalLM  # noqa: PLC0415
                processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)  # nosec B615
                model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)  # nosec B615
        else:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415
            processor = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)  # nosec B615
            model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)  # nosec B615
        model.to("cpu")
        model.eval()
        _vision_processor = processor
        _vision_model = model
        _vision_loaded = True


def release():
    """Free the loaded vision model + processor and collect garbage."""
    global _vision_model, _vision_processor, _vision_loaded
    with _VISION_LOCK:
        _vision_model = None
        _vision_processor = None
        _vision_loaded = False
    gc.collect()


def _strip_prompt_prefix(answer: str, prompt: str) -> str:
    text = answer.strip()
    if prompt and text.startswith(prompt):
        text = text[len(prompt):].strip()
    # Some VLMs echo a leading question / repeat of the prompt.
    for token in ("\n\n", "Question:"):
        if token in text and text.split(token)[0].strip() == (prompt.strip() if prompt else ""):
            text = text.split(token, 1)[1].strip()
            break
    return text


def _run_gemma_inference(img: Any, prompt: str, max_tokens: int) -> str:
    """Gemma 3 / PaliGemma: processor + generate. Returns the decoded answer."""
    import torch  # noqa: PLC0415
    processor = _vision_processor
    model = _vision_model
    if hasattr(processor, "apply_chat_template") and hasattr(processor, "image_processor"):
        # Gemma 3 chat-style inputs.
        messages = [{
            "role": "user",
            "content": [{"type": "image"}, {"type": "text", "text": prompt}],
        }]
        inputs = processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = {k: v.to("cpu") for k, v in inputs.items() if hasattr(v, "to")}
    else:
        # PaliGemma-style (images + text passed directly to the processor).
        inputs = processor(images=img, text=prompt, return_tensors="pt")
        inputs = {k: v.to("cpu") for k, v in inputs.items() if hasattr(v, "to")}
    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
    if "input_ids" in inputs:
        outputs = outputs[:, inputs["input_ids"].shape[1]:]
    answer = processor.decode(outputs[0], skip_special_tokens=True)
    return answer


def analyze_image(image: bytes, prompt: str = "Describe this image in detail.") -> dict:
    """Analyze an image from raw bytes and return a text description."""
    if not vision_enabled():
        raise ValueError(
            "Vision is disabled. Enable it with --vision or POST /v1/config key 'vision.enabled' = true."
        )
    if not image:
        raise ValueError("image data is required")
    if not _deps_available():
        raise ValueError("Vision unavailable: install transformers + torch (pip install transformers torch)")
    import PIL.Image  # noqa: PLC0415
    from io import BytesIO  # noqa: PLC0415
    try:
        img = PIL.Image.open(BytesIO(image)).convert("RGB")
    except Exception as e:
        raise ValueError(f"Could not decode image: {e}") from e
    img.thumbnail((1024, 1024))
    _load_model()
    start = time.time()
    try:
        with _VISION_LOCK:
            model_id = (getattr(CONFIG, "vision", {}) or {}).get("model", _MODEL_ID_DEFAULT)
            max_tokens = int((getattr(CONFIG, "vision", {}) or {}).get("max_tokens", 200))
            if _is_gemma(model_id):
                answer = _run_gemma_inference(img, prompt, max_tokens)
            else:
                answer = _vision_model.answer_question(img, prompt, _vision_processor)
    except Exception as e:
        release()
        raise RuntimeError(f"Vision inference failed: {e}") from e
    description = _strip_prompt_prefix(answer, prompt)
    return {
        "description": description or "(no description produced)",
        "prompt": prompt,
        "model": (getattr(CONFIG, "vision", {}) or {}).get("model", _MODEL_ID_DEFAULT),
        "device": "cpu",
        "elapsed_s": round(time.time() - start, 1),
    }


def analyze_image_base64(data: str, prompt: str = "Describe this image in detail.") -> dict:
    """Analyze an image given as a base64 string (optionally a data URI)."""
    if not data:
        raise ValueError("image data is required")
    if "," in data and data.split(",", 1)[0].startswith("data:"):
        data = data.split(",", 1)[1]
    data = re.sub(r"\s+", "", data)
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception as e:
        raise ValueError(f"Invalid base64 image data: {e}") from e
    if not raw:
        raise ValueError("image data is empty")
    return analyze_image(raw, prompt=prompt)


def describe_image_file(path: str, prompt: str = "Describe this image in detail.") -> str:
    """Best-effort description of an image file on disk (returns "" on failure)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return analyze_image(raw, prompt=prompt)["description"]
    except Exception:
        return ""
