import logging
import queue
import sys
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from typing import Any, Dict, Optional, List

from config import CONFIG, ModelConfig
from metrics import metrics as _metrics

logger = logging.getLogger(__name__)

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None  # type: ignore[assignment,misc]
    logger.warning("llama-cpp-python not installed — local inference disabled; OpenAI fallback still available")

_load_times: Dict[str, float] = {}
_load_errors: Dict[str, str] = {}
_stats_lock = threading.Lock()
_openai_client = None
_openai_fingerprint = None
_openai_lock = threading.Lock()
_locks_guard = threading.Lock()
_last_used: Dict[str, float] = {}
_last_used_lock = threading.Lock()

_openai_calls: List[float] = []
_openai_failures: List[float] = []
_openai_ratelimit_lock = threading.Lock()

_tiktoken_cache: Dict[str, Any] = {}


def _tiktoken_encoder(model: str):
    """Return a cached tiktoken encoder for `model`, or None when unavailable."""
    if model not in _tiktoken_cache:
        enc = None
        try:
            import tiktoken  # optional dependency (lazy)
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = None
        _tiktoken_cache[model] = enc
    return _tiktoken_cache.get(model)


def _openai_can_call() -> bool:
    """Check the sliding-window OpenAI rate limit (default 10 calls/min)."""
    with _openai_ratelimit_lock:
        now = time.time()
        window = 60.0
        cutoff = now - window
        while _openai_calls and _openai_calls[0] <= cutoff:
            _openai_calls.pop(0)
        while _openai_failures and _openai_failures[0] <= cutoff:
            _openai_failures.pop(0)
        limit = getattr(CONFIG.openai, "rate_limit_per_min", 10)
        return len(_openai_calls) < max(1, limit)


def _openai_call_slot() -> None:
    with _openai_ratelimit_lock:
        _openai_calls.append(time.time())


def _record_openai_failure() -> None:
    with _openai_ratelimit_lock:
        _openai_failures.append(time.time())


def _openai_backoff_delay() -> float:
    """Exponential backoff delay based on recent failures in the window."""
    now = time.time()
    with _openai_ratelimit_lock:
        while _openai_failures and _openai_failures[0] <= now - 60.0:
            _openai_failures.pop(0)
        failures = len(_openai_failures)
    if failures == 0:
        return 0.0
    base = 1.0
    delay = base * (2 ** min(failures - 1, 5))
    return min(delay, getattr(CONFIG.openai, "backoff_max_s", 60.0))


def _touch(name: str):
    with _last_used_lock:
        _last_used[name] = time.time()


def _untouch(name: str):
    with _last_used_lock:
        _last_used.pop(name, None)


def _least_recently_used(except_names=()):
    with _last_used_lock:
        cands = [n for n in _last_used if n not in except_names]
        return min(cands, key=_last_used.get) if cands else None


def get_openai_client():
    global _openai_client, _openai_fingerprint
    if not CONFIG.openai.enabled or not CONFIG.openai.api_key:
        return None
    fingerprint = (CONFIG.openai.api_key, CONFIG.openai.base_url)
    if _openai_client is not None and fingerprint == _openai_fingerprint:
        return _openai_client
    with _openai_lock:
        if _openai_client is not None and fingerprint != _openai_fingerprint:
            _openai_client = None
        if _openai_client is None:
            try:
                from openai import OpenAI as _OpenAI
                _openai_client = _OpenAI(
                    api_key=CONFIG.openai.api_key,
                    base_url=CONFIG.openai.base_url,
                    timeout=60.0,
                )
                _openai_fingerprint = fingerprint
                logger.info(f"OpenAI client: {CONFIG.openai.base_url}")
            except ImportError:
                logger.warning("pip install openai")
    return _openai_client


def _record_load_time(name: str, elapsed: float):
    with _stats_lock:
        _load_times[name] = elapsed
        _load_errors.pop(name, None)


def _record_load_error(name: str, error: str):
    with _stats_lock:
        _load_errors[name] = error


def _clear_stats(name: str):
    with _stats_lock:
        _load_times.pop(name, None)
        _load_errors.pop(name, None)


def _clear_all_stats():
    with _stats_lock:
        _load_times.clear()
        _load_errors.clear()


def get_model_stats(manager: Optional["ModelManager"] = None):
    with _stats_lock:
        load_times = dict(_load_times)
        load_errors = dict(_load_errors)
    loaded = []
    for n in load_times:
        if n in load_errors:
            continue
        if manager is not None and n not in manager.instances:
            continue
        loaded.append(n)
    return {"load_times": load_times, "load_errors": load_errors, "loaded_count": len(loaded)}


class ModelManager:
    def __init__(self):
        self.instances: Dict[str, Llama] = {}
        self.configs: Dict[str, ModelConfig] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._executors: Dict[str, ThreadPoolExecutor] = {}
        self._exec_guard = threading.Lock()
        self._load_configs()
        try:
            from hardware import get_hw_monitor
            self._hw_monitor = get_hw_monitor(self)
        except Exception:
            self._hw_monitor = None

    def _load_configs(self):
        for mc in CONFIG.available_models:
            self.configs[mc.name] = mc

    def _get_lock(self, name: str) -> threading.Lock:
        with _locks_guard:
            lock = self._locks.get(name)
            if lock is None:
                lock = threading.Lock()
                self._locks[name] = lock
            return lock

    def _get_executor(self, name: str) -> ThreadPoolExecutor:
        with self._exec_guard:
            ex = self._executors.get(name)
            if ex is None:
                ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"gen-{name}")
                self._executors[name] = ex
            return ex

    def _kill_model(self, name: str, ex: ThreadPoolExecutor):
        """Discard a hung generation: drop the stuck instance + executor so the
        next call builds a fresh Llama on a fresh worker thread."""
        self.instances.pop(name, None)
        _untouch(name)
        with self._exec_guard:
            if self._executors.get(name) is ex:
                del self._executors[name]
        ex.shutdown(wait=False, cancel_futures=True)
        _metrics.record_completion(model=name, ok=False)
        logger.error(f"{name} generation hung; instance discarded, will reload on next call")

    def _clamp_max_tokens(self, llm, name: str, prompt: str, max_tokens: Optional[int]) -> int:
        """Cap max_tokens so the prompt + generation fit the model's context window,
        avoiding llama.cpp 'Requested tokens exceed context window' failures."""
        mc = self.configs.get(name)
        requested = max_tokens or (mc.max_tokens if mc else 2048) or 2048
        ctx = mc.n_ctx if mc else 2048
        try:
            prompt_tokens = len(llm.tokenize(prompt.encode("utf-8"), add_bos=True))
        except Exception:
            prompt_tokens = len(prompt.split()) + 4
        budget = max(ctx - prompt_tokens - 16, 8)  # small margin for EOG/stop token
        return min(requested, budget)

    def load(self, name: str) -> Llama:
        lock = self._get_lock(name)
        with lock:
            return self._load_unlocked(name)

    def _load_unlocked(self, name: str) -> Llama:
        if name in self.instances:
            return self.instances[name]
        if Llama is None:
            raise RuntimeError("llama-cpp-python is not installed. Install it with: pip install llama-cpp-python")
        mc = self.configs.get(name)
        if not mc:
            raise ValueError(f"Model '{name}' not found. Available: {list(self.configs.keys())}")
        logger.info(f"Loading {mc.name} ({mc.role}) from {mc.path}")
        logger.info(f"  threads={mc.n_threads}, gpu_layers={mc.n_gpu_layers}, ctx={mc.n_ctx}")
        sys.stdout.flush()
        start = time.time()
        try:
            lora_kwargs: Dict[str, Any] = {}
            if CONFIG.lora_enabled:
                try:
                    from lora_manager import get_active_lora_for_model
                    lora_adapter = get_active_lora_for_model(name)
                    if lora_adapter:
                        lora_kwargs["lora_path"] = lora_adapter.path
                        lora_kwargs["lora_base"] = mc.path
                        lora_kwargs["lora_scale"] = lora_adapter.scale
                        logger.info(f"  LoRA: {lora_adapter.name} (scale={lora_adapter.scale})")
                except Exception as e:
                    logger.warning(f"LoRA check failed: {e}")
            llm = Llama(
                model_path=mc.path,
                n_ctx=mc.n_ctx,
                n_threads=mc.n_threads,
                n_gpu_layers=mc.n_gpu_layers,
                verbose=False,
                use_mlock=True,
                **lora_kwargs,
            )
            self.instances[name] = llm
            elapsed = time.time() - start
            _record_load_time(name, elapsed)
            _metrics.record_load(name)
            logger.info(f"{mc.name} loaded in {elapsed:.2f}s")
            return llm
        except Exception as e:
            _record_load_error(name, str(e))
            raise

    def get(self, name: str) -> Optional[Llama]:
        return self.instances.get(name)

    def generate(self, name: str, prompt: str, max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None, stop: Optional[list] = None) -> str:
        lock = self._get_lock(name)
        with lock:
            try:
                llm = self._load_unlocked(name)
            except Exception as e:
                logger.error(f"Load {name} failed: {e}")
                if CONFIG.openai.enabled:
                    return self._openai_fallback(prompt, max_tokens)
                raise RuntimeError(f"Load {name} failed: {e}") from e
            mc = self.configs[name]
            kwargs: Dict[str, Any] = dict(
                prompt=prompt,
                max_tokens=self._clamp_max_tokens(llm, name, prompt, max_tokens),
                temperature=temperature if temperature is not None else mc.temperature,
                top_p=mc.top_p, echo=False, stop=stop or None,
            )
            start = time.time()
            ex = self._get_executor(name)
            fut = ex.submit(llm, **kwargs)
            try:
                response = fut.result(timeout=CONFIG.gen_timeout_s)
            except FutureTimeoutError:
                self._kill_model(name, ex)
                if CONFIG.openai.enabled:
                    return self._openai_fallback(prompt, max_tokens)
                raise RuntimeError(f"Generate on {name} timed out after {CONFIG.gen_timeout_s}s") from None
            except Exception as e:
                _metrics.record_completion(model=name, ok=False)
                logger.error(f"Generate on {name} failed: {e}; reloading on next call")
                self.instances.pop(name, None)
                _untouch(name)
                if CONFIG.openai.enabled:
                    return self._openai_fallback(prompt, max_tokens)
                raise RuntimeError(f"Generate on {name} failed: {e}") from e
            try:
                text = response["choices"][0]["text"].strip()  # type: ignore[index]
            except Exception as e:
                _metrics.record_completion(model=name, ok=False)
                logger.error(f"Generate on {name} failed: {e}; reloading on next call")
                self.instances.pop(name, None)
                _untouch(name)
                if CONFIG.openai.enabled:
                    return self._openai_fallback(prompt, max_tokens)
                raise RuntimeError(f"Generate on {name} failed: {e}") from e
            _touch(name)
            _metrics.record_completion(model=name, tokens_out=len(text.split()),
                                       latency=time.time() - start, ok=True)
            return text

    def generate_stream(self, name: str, prompt: str, max_tokens: Optional[int] = None,
                        temperature: Optional[float] = None, stop: Optional[list] = None):
        lock = self._get_lock(name)
        with lock:
            try:
                llm = self._load_unlocked(name)
            except Exception as e:
                logger.error(f"Load {name} failed: {e}")
                if CONFIG.openai.enabled:
                    yield self._openai_fallback(prompt, max_tokens)
                    return
                raise RuntimeError(f"Load {name} failed: {e}") from e
            mc = self.configs[name]
            kwargs = dict(
                prompt=prompt,
                max_tokens=self._clamp_max_tokens(llm, name, prompt, max_tokens),
                temperature=temperature if temperature is not None else mc.temperature,
                top_p=mc.top_p, echo=False, stop=stop or None,
                stream=True,
            )
            start = time.time()
            parts = []
            err = []
            q: queue.Queue = queue.Queue()
            _stop = threading.Event()

            def _run():
                try:
                    for chunk in llm(**kwargs):
                        piece = chunk["choices"][0]["text"]
                        if piece:
                            parts.append(piece)
                            if _stop.is_set():
                                return
                            q.put(piece)
                except Exception as e:
                    err.append(e)
                finally:
                    try:
                        q.put_nowait(None)
                    except queue.Full:
                        pass

            self._get_executor(name).submit(_run)
            try:
                while True:
                    try:
                        item = q.get(timeout=CONFIG.gen_timeout_s)
                    except queue.Empty:
                        self._kill_model(name, self._get_executor(name))
                        if CONFIG.openai.enabled:
                            yield self._openai_fallback(prompt, max_tokens)
                        else:
                            raise RuntimeError(
                                f"Generate on {name} timed out after {CONFIG.gen_timeout_s}s"
                            ) from None
                        return
                    if item is None:
                        break
                    yield item
            finally:
                _stop.set()
            if err:
                _metrics.record_completion(model=name, ok=False)
                logger.error(f"Generate on {name} failed: {err[0]}; reloading on next call")
                self.instances.pop(name, None)
                _untouch(name)
                if CONFIG.openai.enabled:
                    yield self._openai_fallback(prompt, max_tokens)
                else:
                    raise RuntimeError(f"Generate on {name} failed: {err[0]}") from err[0]
            else:
                _touch(name)
                _metrics.record_completion(model=name, tokens_out=len("".join(parts).split()),
                                           latency=time.time() - start, ok=True)

    def _openai_fallback(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        client = get_openai_client()
        if not client:
            raise RuntimeError("No model loaded and no OpenAI fallback")
        start = time.time()
        try:
            if not _openai_can_call():
                delay = _openai_backoff_delay()
                logger.warning(f"OpenAI rate limit reached; backing off {delay:.1f}s")
                time.sleep(delay)
                if not _openai_can_call():
                    raise RuntimeError("OpenAI rate limit exceeded (too many fallback calls)")
            _openai_call_slot()
            logger.info("Falling back to OpenAI")
            resp = client.chat.completions.create(
                model=CONFIG.openai.chat_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens or 2048,
            )
            choices = getattr(resp, "choices", None) or []
            msg = getattr(choices[0], "message", None) if choices else None
            content = getattr(msg, "content", None) if msg else None
            if not content:
                raise RuntimeError("OpenAI returned empty response")
            text = content.strip()
            _metrics.record_completion(model=f"openai/{CONFIG.openai.chat_model}", ok=True,
                                       tokens_out=len(text.split()), latency=time.time() - start)
            return text
        except Exception as e:
            _record_openai_failure()
            _metrics.record_completion(model=f"openai/{CONFIG.openai.chat_model}", ok=False,
                                       latency=time.time() - start)
            raise RuntimeError(f"OpenAI error: {e}") from e

    def chat(self, name: str, messages: List[Dict[str, str]],
             max_tokens: Optional[int] = None, temperature: Optional[float] = None) -> str:
        if name.startswith("openai/") or not name:
            client = get_openai_client()
            if not client:
                raise RuntimeError("OpenAI not configured")
            model = name.replace("openai/", "") or CONFIG.openai.chat_model
            try:
                if not _openai_can_call():
                    delay = _openai_backoff_delay()
                    logger.warning(f"OpenAI rate limit reached; backing off {delay:.1f}s")
                    time.sleep(delay)
                    if not _openai_can_call():
                        raise RuntimeError("OpenAI rate limit exceeded (too many fallback calls)")
                _openai_call_slot()
                resp = client.chat.completions.create(
                    model=model, messages=messages,
                    max_tokens=max_tokens if max_tokens is not None else 2048,
                    temperature=temperature if temperature is not None else 0.7,
                )
                choices = getattr(resp, "choices", None) or []
                msg = getattr(choices[0], "message", None) if choices else None
                content = getattr(msg, "content", None) if msg else None
                if not content:
                    raise RuntimeError("OpenAI returned empty response")
                return content.strip()
            except Exception as e:
                _record_openai_failure()
                raise RuntimeError(f"OpenAI error: {e}") from e
        last = [m for m in messages if m["role"] == "user"]
        if not last:
            return ""
        return self.generate(name, last[-1]["content"], max_tokens, temperature)

    def count_tokens(self, text: str, name: Optional[str] = None) -> int:
        """Count tokens for `text` using the most accurate tokenizer available.

        Uses the loaded llama.cpp instance's real tokenizer for local models,
        tiktoken (if installed) for OpenAI/cloud models, and falls back to a
        whitespace split so reporting never fails even when no tokenizer is
        available (e.g. a model that is not currently loaded).
        """
        if not text:
            return 0
        if name:
            llm = self.instances.get(name)
            if llm is not None and hasattr(llm, "tokenize"):
                try:
                    return len(llm.tokenize(text.encode("utf-8"), add_bos=False))
                except Exception:
                    pass
            enc = _tiktoken_encoder(name.replace("openai/", ""))
            if enc is not None:
                try:
                    return len(enc.encode(text))
                except Exception:
                    pass
        return len(text.split())

    def unload(self, name: str):
        lock = self._get_lock(name)
        with lock:
            self.instances.pop(name, None)
            _untouch(name)
            _clear_stats(name)
            logger.info(f"Unloaded {name}")

    def try_unload(self, name: str, timeout: float = 5.0) -> bool:
        """Unload a model only if its lock is free within `timeout` (seconds).
        Returns True when unloaded, False when the model is busy generating
        (so background monitors never block behind a hung generation)."""
        lock = self._get_lock(name)
        if not lock.acquire(timeout=timeout):
            return False
        try:
            self.instances.pop(name, None)
            _untouch(name)
            _clear_stats(name)
            logger.info(f"Unloaded {name}")
            return True
        finally:
            lock.release()

    def get_vram_estimate(self, name: str) -> int:
        mc = self.configs.get(name)
        if not mc:
            return 0
        if getattr(mc, "vram_mb", 0):
            return mc.vram_mb
        if getattr(mc, "n_gpu_layers", -1) == 0:
            return 0
        try:
            size_mb = os.path.getsize(mc.path) / (1024 * 1024)
        except OSError:
            return 0
        return int(size_mb * 1.15) + 256

    def vram_used(self) -> int:
        return sum(self.get_vram_estimate(n) for n in self.instances)

    def ensure_loaded(self, names, budget_mb=None, keep=None) -> list:
        return self.load_many(names, budget_mb=budget_mb, keep=keep)

    def load_many(self, names, budget_mb=None, keep=None) -> list:
        """Load several models at once, loading concurrently when the combined
        VRAM estimate fits the budget (TASK-HP-003). Falls back to sequential
        loading with LRU eviction when parallel loading would overshoot VRAM.
        Returns the subset of `names` that ended up loaded.
        """
        budget = budget_mb if budget_mb is not None else CONFIG.vram_budget_mb
        keep = set(keep or []) | set(names)
        targets: List[str] = []
        for name in names:
            if name in self.instances:
                _touch(name)
            elif name in self.configs:
                targets.append(name)
        if targets:
            try:
                from hardware import detect_hardware
                hw = detect_hardware()
                ram_avail = hw.get("ram_available_mb", 0)
                if ram_avail > 0 and ram_avail < 4096:
                    logger.warning(f"load_many blocked: RAM low {ram_avail} MB")
                    return [n for n in names if n in self.instances]
            except Exception:
                pass
            extra = sum(self.get_vram_estimate(n) for n in targets)
            fits = (not budget) or (self.vram_used() + extra <= budget)
            if fits and getattr(CONFIG, "parallel_load", True) and len(targets) > 1:
                self._load_parallel(targets, keep)
            else:
                self._load_sequential(targets, budget, keep)
        return [n for n in names if n in self.instances]

    def _load_sequential(self, targets, budget: int, keep: set):
        for name in targets:
            if name in self.instances:
                _touch(name)
                continue
            if budget and self.vram_used() + self.get_vram_estimate(name) > budget:
                self._unload_for_budget(budget, keep)
            try:
                self.load(name)
                _touch(name)
            except Exception as e:
                logger.warning(f"load_many {name} failed: {e}")

    def _load_parallel(self, targets, keep: set):
        workers = min(len(targets), max(1, getattr(CONFIG, "load_workers", 2)))
        if workers <= 1:
            self._load_sequential(targets, 0, keep)
            return
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="load") as ex:
            futs = {ex.submit(self._load_one, n): n for n in targets}
            for fut in as_completed(futs):
                n = futs[fut]
                try:
                    fut.result()
                except Exception as e:
                    logger.warning(f"Parallel load {n} failed: {e}")

    def _load_one(self, name: str):
        self.load(name)
        _touch(name)

    def _unload_for_budget(self, budget: int, keep: set):
        guard = 0
        while budget > 0 and self.vram_used() > budget:
            victim = _least_recently_used(except_names=keep)
            if victim is None:
                break
            try:
                self.unload(victim)
            except Exception:
                break
            guard += 1
            if guard > 64:
                break

    def unload_all(self):
        with _locks_guard:
            locks = []
            for n in list(self.instances.keys()):
                lock = self._locks.get(n)
                if lock is not None:
                    locks.append(lock)
        acquired = []
        for lock in locks:
            if lock.acquire(timeout=10.0):
                acquired.append(lock)
            else:
                logger.warning("Model lock busy during unload_all; skipping busy model")
        try:
            self.instances.clear()
            with _last_used_lock:
                _last_used.clear()
            _clear_all_stats()
        finally:
            for lock in acquired:
                lock.release()
