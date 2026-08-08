"""
LoRA adapter manager for local GGUF models.

Supports:
- Listing available LoRA adapters
- Loading/unloading LoRA adapters at inference time
- Training new LoRA adapters via HuggingFace PEFT (optional dependency)
- Applying LoRA adapters to GGUF models via llama.cpp

llama.cpp LoRA support:
  model = Llama(model_path=gguf_path, lora_path=lora_path, lora_scale=1.0)
"""

import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import BASE_DIR

logger = logging.getLogger(__name__)


@dataclass
class LoRAAdapter:
    name: str
    path: str
    base_model: str = ""
    description: str = ""
    enabled: bool = False
    scale: float = 1.0
    metadata: Dict[str, str] = field(default_factory=dict)


_LORA_LOCK = threading.Lock()
_TRAIN_LOCK = threading.Lock()
_LORA_ADAPTERS: Dict[str, LoRAAdapter] = {}
_LORA_DIR = os.path.join(BASE_DIR, "loras")


def _safe_lora_name(name: str) -> str:
    """Sanitize a user-supplied LoRA name so it can never escape loras/."""
    name = os.path.basename(name.replace("\\", "/")).strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:80].strip()
    return name or "adapter"


def _ensure_lora_dir():
    os.makedirs(_LORA_DIR, exist_ok=True)


def scan_loras() -> List[LoRAAdapter]:
    """Scan the loras/ directory for available LoRA adapters."""
    _ensure_lora_dir()
    adapters = []
    for fn in sorted(os.listdir(_LORA_DIR)):
        if fn.endswith((".bin", ".gguf", ".safetensors")) or (
            os.path.isdir(os.path.join(_LORA_DIR, fn)) and
            os.path.exists(os.path.join(_LORA_DIR, fn, "adapter_config.json"))
        ):
            name = os.path.splitext(fn)[0] if not os.path.isdir(os.path.join(_LORA_DIR, fn)) else fn
            path = os.path.join(_LORA_DIR, fn)
            adapters.append(LoRAAdapter(name=name, path=path))
    return adapters


def _discover_on_disk():
    """Pre-register adapters found in loras/ so they show up in /v1/loras
    before any explicit import. Existing registrations are never clobbered."""
    for adapter in scan_loras():
        with _LORA_LOCK:
            if adapter.name not in _LORA_ADAPTERS:
                _LORA_ADAPTERS[adapter.name] = adapter


_discover_on_disk()


def list_adapters() -> List[LoRAAdapter]:
    with _LORA_LOCK:
        return list(_LORA_ADAPTERS.values())


def register_adapter(adapter: LoRAAdapter):
    with _LORA_LOCK:
        _LORA_ADAPTERS[adapter.name] = adapter


def enable_adapter(name: str, model_name: str = "") -> bool:
    with _LORA_LOCK:
        adapter = _LORA_ADAPTERS.get(name)
        if adapter is None:
            return False
        adapter.enabled = True
        if model_name:
            adapter.base_model = model_name
        return True


def disable_adapter(name: str):
    with _LORA_LOCK:
        adapter = _LORA_ADAPTERS.get(name)
        if adapter:
            adapter.enabled = False


def get_active_lora_for_model(model_name: str) -> Optional[LoRAAdapter]:
    with _LORA_LOCK:
        for adapter in _LORA_ADAPTERS.values():
            if adapter.enabled and adapter.base_model == model_name:
                return adapter
    return None


def import_adapter(src_path: str, name: str = "") -> Optional[LoRAAdapter]:
    """Import a LoRA adapter file/directory into the loras/ directory."""
    if not os.path.exists(src_path):
        return None
    _ensure_lora_dir()
    if os.path.isdir(src_path):
        ext = ""
    else:
        ext = os.path.splitext(src_path)[1]
    if not name:
        name = os.path.splitext(os.path.basename(src_path))[0]
    name = _safe_lora_name(name)
    dest = os.path.join(_LORA_DIR, f"{name}{ext}")
    if os.path.exists(dest):
        base, extension = os.path.splitext(dest)
        dest = f"{base}_{int(time.time())}{extension}"
    if os.path.isdir(src_path):
        shutil.copytree(src_path, dest)
    else:
        shutil.copy2(src_path, dest)
    adapter_name = (
        os.path.splitext(os.path.basename(dest))[0]
        if not os.path.isdir(dest)
        else os.path.basename(dest)
    )
    adapter = LoRAAdapter(name=adapter_name, path=dest)
    register_adapter(adapter)
    logger.info(f"Imported LoRA adapter: {adapter.name}")
    return adapter


def delete_adapter(name: str) -> bool:
    with _LORA_LOCK:
        adapter = _LORA_ADAPTERS.pop(name, None)
    if adapter is None:
        return False
    try:
        if os.path.exists(adapter.path):
            if os.path.isdir(adapter.path):
                shutil.rmtree(adapter.path)
            else:
                os.remove(adapter.path)
    except Exception as e:
        logger.warning(f"Failed to delete LoRA file {adapter.path}: {e}")
    return True


def train_lora(
    base_model: str,
    dataset_path: str,
    output_name: str,
    epochs: int = 3,
    batch_size: int = 4,
    lora_rank: int = 8,
    lora_alpha: int = 16,
    lora_dropout: float = 0.05,
    max_length: int = 512,
) -> Optional[str]:
    """Train a LoRA adapter using HuggingFace PEFT.

    Requires: transformers, torch, peft, datasets
    Install: pip install peft datasets

    Returns path to trained adapter directory, or None if dependencies missing.
    """
    try:
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
        from datasets import Dataset
    except ImportError as e:
        logger.error(f"LoRA training requires extra packages: {e}")
        logger.error("Install with: pip install peft datasets transformers")
        return None

    if not os.path.exists(dataset_path):
        logger.error(f"Dataset not found: {dataset_path}")
        return None

    output_name = _safe_lora_name(output_name)
    dset_dir = os.path.abspath(os.path.join(BASE_DIR, "lora_datasets"))
    resolved_dataset = os.path.abspath(dataset_path)
    try:
        inside = os.path.commonpath([dset_dir, resolved_dataset]) == dset_dir
    except ValueError:
        # Different drives (e.g. D:\ vs C:\ on Windows) make commonpath raise.
        inside = False
    if not inside:
        logger.error(f"Dataset must live under lora_datasets/: {dataset_path}")
        return None

    if not _TRAIN_LOCK.acquire(timeout=1):
        logger.error("Another LoRA training is already in progress")
        return None

    try:
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except Exception as e:
            logger.error(f"torch unavailable, cannot train LoRA: {e}")
            return None

        logger.info(f"Training LoRA adapter '{output_name}' on {base_model} (device: {'cuda' if has_cuda else 'cpu'})")

        tokenizer = AutoTokenizer.from_pretrained(base_model)  # nosec B615
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            device_map="auto" if has_cuda else None,
            torch_dtype="auto" if has_cuda else None,
        )  # nosec B615
        if has_cuda:
            model = prepare_model_for_kbit_training(model)
        else:
            # CPU training: peft >= 0.7 removed use_cache from this function.
            model = prepare_model_for_kbit_training(model)
            model.config.use_cache = False

        peft_config = LoraConfig(
            r=lora_rank,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
        )
        peft_model = get_peft_model(model, peft_config)

        with open(dataset_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        def tokenize(examples):
            return tokenizer(examples["text"], truncation=True, max_length=max_length, padding="max_length")

        ds = Dataset.from_dict({"text": lines})
        ds = ds.map(tokenize, batched=True, remove_columns=["text"])

        output_dir = os.path.join(_LORA_DIR, f"{output_name}_hf")
        args = TrainingArguments(  # pylint: disable=unexpected-keyword-arg
            output_dir=output_dir,
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            learning_rate=2e-4,
            fp16=has_cuda,
            no_cuda=not has_cuda,  # type: ignore[call-arg]
            save_strategy="epoch",
            logging_steps=10,
            report_to="none",
        )

        trainer = Trainer(model=peft_model, args=args, train_dataset=ds)
        trainer.train()
        peft_model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)

        logger.info(f"LoRA adapter '{output_name}' training complete -> {output_dir}")
        register_adapter(LoRAAdapter(name=output_name, path=output_dir, base_model=base_model, enabled=True))
        return output_dir
    finally:
        _TRAIN_LOCK.release()
