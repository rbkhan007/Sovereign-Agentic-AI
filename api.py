"""FastAPI application for the Rhasan Indie's Agentic LLM multi-agent system.

Provides OpenAI-compatible chat completions, streaming, model management,
PostgreSQL + pgvector memory, workspaces with knowledge graphs, LoRA adapter
management, agent personas, skills, MCP endpoint, and admin monitoring.
"""
import logging
import json
import time
import uuid
import asyncio
import threading
import re
import collections
import os
from typing import Optional, List, Dict, Any, Union
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, field_validator, ConfigDict

from models import ModelManager
from memory import MemoryManager
from orchestrator import Orchestrator
from config import CONFIG, HAS_GPU

logger = logging.getLogger(__name__)


class _RingHandler(logging.Handler):
    """In-memory ring buffer of recent log lines for the admin panel."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self.capacity = capacity
        self._buf: collections.deque[str] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        with self._lock:
            self._buf.append(msg)

    def lines(self, n: int):
        with self._lock:
            return list(self._buf)[-n:]


_log_ring = _RingHandler()
logging.getLogger().addHandler(_log_ring)
_start_ts = time.time()

_graph_sync_stop = threading.Event()
_graph_sync_thread: Optional[threading.Thread] = None


def _graph_sync_loop(interval_minutes: int = 5):
    """Periodically sync in-memory wiki-link graph to PostgreSQL graph store."""
    interval = max(1, interval_minutes) * 60
    while not _graph_sync_stop.wait(timeout=interval):
        try:
            if not CONFIG.db.enabled:
                continue
            from wiki_links import knowledge_graph
            for ws_id in list(knowledge_graph._docs.keys()):  # noqa: SLF001
                try:
                    import graph_store
                    graph_store.sync_wiki_links(ws_id)
                except Exception as ge:
                    logger.debug(f"Background graph sync failed for ws={ws_id}: {ge}")
        except Exception as e:
            logger.debug(f"Background graph sync loop error: {e}")


model_manager = ModelManager()
memory_manager = MemoryManager()
orchestrator = Orchestrator(model_manager, memory_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"GPU: {'Enabled' if HAS_GPU else 'Disabled'} ({CONFIG.gpu_name})")
    logger.info(f"Threads: {CONFIG.threads}")
    if CONFIG.auto_tune:
        try:
            import hardware
            hardware.auto_tune()
        except Exception as e:
            logger.warning(f"Auto-tune failed: {e}")
    # Dynamic safety monitor: evicts models on RAM/VRAM pressure and throttles
    # threads on sustained high CPU, so the box never sits pegged at 100%.
    try:
        import hardware
        hardware.get_hw_monitor(model_manager)
    except Exception as e:
        logger.warning(f"Hardware monitor failed to start: {e}")
    if not CONFIG.db.enabled:
        try:
            import database as db
            db.enable_if_available()
        except Exception as e:
            logger.warning(f"DB auto-detect failed: {e}")
    if CONFIG.db.enabled:
        logger.info(f"PostgreSQL: {CONFIG.db.database}")
    if CONFIG.openai.enabled:
        logger.info(f"OpenAI: {CONFIG.openai.base_url}")
    if CONFIG.db.enabled:
        import database as db
        db.start_auto_prune()
    # Start periodic graph sync (every 5 minutes)
    global _graph_sync_thread
    _graph_sync_stop.clear()
    _graph_sync_thread = threading.Thread(
        target=_graph_sync_loop, args=(5,), daemon=True, name="graph-sync"
    )
    _graph_sync_thread.start()
    yield
    _graph_sync_stop.set()
    if _graph_sync_thread:
        _graph_sync_thread.join(timeout=5)
    model_manager.unload_all()
    memory_manager.clear_all()
    if CONFIG.db.enabled:
        try:
            import database as db
            db.close()
        except Exception:  # noqa: B110
            pass  # best-effort cleanup on shutdown


app = FastAPI(title="Rhasan Indie's Agentic LLM API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\]|.*\.local|"
    r".*\.lan)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_auth(request: Request, call_next):
    if CONFIG.valid_api_tokens() and (
        request.url.path.startswith("/v1/") or request.url.path.startswith("/mcp")
    ):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if not CONFIG.token_authorized(auth[7:]):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)

# ---------- Pydantic Models ----------

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = ""
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = 2048
    stream: Optional[bool] = False
    use_planning: Optional[bool] = True
    parallel: Optional[bool] = None
    sandbox: Optional[bool] = False
    conversation_id: Optional[str] = None
    workspace_id: Optional[str] = None
    agent: Optional[str] = None
    skill: Optional[str] = None

    model_config = ConfigDict(str_min_length=0, str_max_length=200)

    @field_validator('temperature')
    @classmethod
    def validate_temperature(cls, v):  # noqa: unused
        if v is not None and (v < 0.0 or v > 2.0):
            raise ValueError('temperature must be between 0.0 and 2.0')
        return v

    @field_validator('max_tokens')
    @classmethod
    def validate_max_tokens(cls, v):  # noqa: unused
        if v is not None and (v < 1 or v > 32768):
            raise ValueError('max_tokens must be between 1 and 32768')
        return v

    @field_validator('messages')
    @classmethod
    def validate_messages(cls, v):  # noqa: unused
        if not v:
            raise ValueError('messages must not be empty')
        return v

class WorkspaceRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    system_prompt: Optional[str] = ""
    default_model: Optional[str] = ""

class WorkspaceUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    default_model: Optional[str] = None

class FileUploadRequest(BaseModel):
    name: str
    content: str

class ImportRequest(BaseModel):
    conversations: List[Dict[str, Any]]

class GenerateRequest(BaseModel):
    model: str = ""
    prompt: str
    max_tokens: Optional[int] = 1024
    temperature: Optional[float] = None
    stop: Optional[List[str]] = None

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Optional[dict] = None
    id: Optional[int] = None

class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 5
    min_score: float = 0.0

class MemoryStoreRequest(BaseModel):
    agent: str = "default"
    thought: str

class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = "sentence-transformers/all-MiniLM-L6-v2"

class ConfigUpdate(BaseModel):
    key: str
    value: Any

class BatchRequest(BaseModel):
    prompts: List[str]
    model: str = ""
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = None

# ---------- Model API ----------

@app.get("/v1/models")
def list_models():
    data = []
    for name, mc in model_manager.configs.items():
        loaded = name in model_manager.instances
        data.append({
            "id": name,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local",
            "role": mc.role,
            "n_ctx": mc.n_ctx,
            "loaded": loaded,
        })
    if CONFIG.openai.enabled:
        data.append({
            "id": f"openai/{CONFIG.openai.chat_model}",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "openai",
            "n_ctx": 128000,
            "loaded": True,
        })
    return {
        "object": "list",
        "data": data,
        "openai_enabled": CONFIG.openai.enabled,
    }


@app.post("/v1/models/load")
def load_model(name: str = Query(..., description="Model name to load")):
    if name not in model_manager.configs:
        available = ", ".join(model_manager.configs.keys())
        raise HTTPException(404, f"Model '{name}' not found. Available: {available}")
    try:
        model_manager.load(name)
        return {"status": "loaded", "model": name}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/models/unload")
def unload_model(name: str = Query(..., description="Model name to unload")):
    if name not in model_manager.instances:
        return {"status": "not_loaded", "model": name}
    model_manager.unload(name)
    return {"status": "unloaded", "model": name}

# ---------- Memory API ----------

@app.post("/v1/memory/search")
def memory_search(req: MemorySearchRequest):
    try:
        import database as db
        results = db.retrieve_similar(req.query, req.limit, min_score=req.min_score)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/memory/store")
def memory_store(req: MemoryStoreRequest):
    try:
        import database as db
        db.store_thought(req.agent, req.thought)
        return {"status": "stored"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/memory/stats")
def memory_stats():
    enabled = CONFIG.db.enabled
    count = 0
    if enabled:
        try:
            import database as db
            count = db.count_memories()
        except Exception:  # noqa: B110
            pass  # tolerate missing DB during health check
    return {"enabled": enabled, "count": count}


@app.get("/v1/db/stats")
def db_stats_api():
    try:
        import database as db
        return db.db_stats()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/memory/recent")
def memory_recent(limit: int = Query(default=20, le=100), agent: Optional[str] = None):
    try:
        import database as db
        results = db.recent_memories(limit=limit, agent=agent)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/memory/clear")
def memory_clear():
    try:
        import database as db
        deleted = db.clear_memories()
        return {"status": "cleared", "deleted": deleted}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/memory/prune")
def memory_prune(max_age_days: Optional[int] = None):
    try:
        import database as db
        deleted = db.prune_memories(max_age_days or CONFIG.prune_max_age_days)
        return {"status": "pruned", "deleted": deleted}
    except Exception as e:
        raise HTTPException(500, str(e))

# ---------- Embeddings API ----------

@app.post("/v1/embeddings")
def generate_embeddings(req: EmbeddingRequest):
    try:
        import database as db
        embedder = db.get_embedder()
        if not embedder:
            raise HTTPException(500, "Embedding model not loaded")
        inputs = req.input if isinstance(req.input, list) else [req.input]
        vecs = embedder.encode(inputs, normalize_embeddings=True).tolist()
        if not isinstance(vecs[0], list):
            vecs = [vecs]
        data = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]
        return {
            "object": "list",
            "data": data,
            "model": req.model,
            "usage": {
                "prompt_tokens": sum(len(x.split()) for x in inputs),
                "total_tokens": sum(len(x.split()) for x in inputs),
            },
        }
    except Exception as e:
        raise HTTPException(500, str(e))

# ---------- Health / System API ----------

@app.get("/v1/health")
def health_check():
    db_ok = False
    conn = None
    db_mod = None
    if CONFIG.db.enabled:
        try:
            import database as db_mod
            conn = db_mod.get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                db_ok = True
        except Exception as e:
            logger.debug(f"Health DB probe failed: {e}")
        finally:
            if conn and db_mod is not None:
                try:
                    db_mod.put_connection(conn)
                except Exception:  # noqa: B110
                    pass  # best-effort connection return
    return {
        "status": "healthy",
        "gpu": HAS_GPU,
        "gpu_name": CONFIG.gpu_name if HAS_GPU else "None",
        "threads": CONFIG.threads,
        "models_loaded": list(model_manager.instances.keys()),
        "models_available": [m.name for m in CONFIG.available_models],
        "database": {"enabled": CONFIG.db.enabled, "connected": db_ok},
        "openai": CONFIG.openai.enabled,
        "uptime": round(time.time() - _start_ts, 1),
    }


@app.get("/v1/system")
def system_info():
    from models import get_model_stats
    from metrics import metrics
    hardware = {}
    try:
        import hardware as hw
        hardware = hw.detect_hardware()
    except Exception:  # noqa: B110
        pass  # tolerate missing hardware module
    return {
        "gpu": HAS_GPU,
        "gpu_name": CONFIG.gpu_name if HAS_GPU else "None",
        "threads": CONFIG.threads,
        "models": [m.name for m in CONFIG.available_models],
        "database": CONFIG.db.enabled,
        "openai": CONFIG.openai.enabled,
        "model_stats": get_model_stats(model_manager),
        "hardware": hardware,
        "metrics": metrics.snapshot(),
    }


@app.get("/v1/models/stats")
def model_stats():
    from models import get_model_stats
    return get_model_stats(model_manager)


@app.get("/v1/metrics")
def api_metrics():
    from metrics import metrics
    return metrics.snapshot()


@app.get("/v1/router/stats")
def router_stats():
    return orchestrator.router.harness.stats()


@app.post("/v1/router/harness/reset")
def harness_reset():
    orchestrator.router.harness.reset()
    return {"status": "ok", "message": "Harness reset"}


class HarnessAdjustRequest(BaseModel):
    task: str
    model: str
    score: float


@app.post("/v1/router/harness/adjust")
def harness_adjust(req: HarnessAdjustRequest):
    orchestrator.router.harness.adjust(req.task, req.model, req.score)
    return {"status": "ok", "message": f"Set {req.task}/{req.model} score to {req.score}"}


@app.get("/v1/router/harness/export")
def harness_export():
    return orchestrator.router.harness.export_stats()


@app.get("/v1/hardware")
def hardware_info(refresh: bool = False):
    import hardware
    return hardware.detect_hardware(force=refresh)

# ---------- Config API ----------

@app.get("/v1/config")
def get_config():
    from config import CLOUD_PRESETS
    return {
        "host": CONFIG.host,
        "port": CONFIG.port,
        "threads": CONFIG.threads,
        "parallel": {
            "enabled": CONFIG.parallel_enabled,
            "max": CONFIG.parallel_max,
            "judge": CONFIG.parallel_judge,
        },
        "prune": {
            "interval_hours": CONFIG.prune_interval_hours,
            "max_age_days": CONFIG.prune_max_age_days,
        },
        "vram": {
            "budget_mb": CONFIG.vram_budget_mb,
            "auto_tune": CONFIG.auto_tune,
            "auto_load": CONFIG.auto_load,
        },
        "harness": {
            "epsilon": CONFIG.harness_epsilon,
            "decay": CONFIG.harness_decay,
        },
        "gen": {
            "timeout_s": CONFIG.gen_timeout_s,
        },
        "cloud": {
            "provider": CONFIG.cloud_provider,
            "base_url": CONFIG.openai.base_url,
            "chat_model": CONFIG.openai.chat_model,
            "presets": {
                k: {"label": v.get("label", k),
                     "base_url": v["base_url"],
                     "chat_model": v["chat_model"]}
                for k, v in CLOUD_PRESETS.items()
            },
        },
        "db": {
            "enabled": CONFIG.db.enabled,
            "database": CONFIG.db.database,
            "host": CONFIG.db.host,
            "port": CONFIG.db.port,
            "user": CONFIG.db.user,
        },
        "openai": {
            "enabled": CONFIG.openai.enabled,
            "base_url": CONFIG.openai.base_url,
            "chat_model": CONFIG.openai.chat_model,
            "rate_limit_per_min": CONFIG.openai.rate_limit_per_min,
            "backoff_max_s": CONFIG.openai.backoff_max_s,
        },
        "api_token": bool(CONFIG.valid_api_tokens()),
        "api_token_count": len(CONFIG.valid_api_tokens()),
        "models": [
            {
                "name": m.name,
                "role": m.role,
                "path": m.path,
                "n_ctx": m.n_ctx,
                "temperature": m.temperature,
                "top_p": m.top_p,
                "max_tokens": m.max_tokens,
            }
            for m in CONFIG.available_models
        ],
    }


@app.post("/v1/config")
def update_config(req: ConfigUpdate):
    key_map = {
        "threads": ("threads", int),
        "db.enabled": ("db.enabled", bool),
        "db.database": ("db.database", str),
        "openai.enabled": ("openai.enabled", bool),
        "openai.api_key": ("openai.api_key", str),
        "openai.base_url": ("openai.base_url", str),
        "openai.chat_model": ("openai.chat_model", str),
        "openai.rate_limit_per_min": ("openai.rate_limit_per_min", int),
        "openai.backoff_max_s": ("openai.backoff_max_s", float),
        "parallel.enabled": ("parallel_enabled", bool),
        "parallel.max": ("parallel_max", int),
        "parallel.judge": ("parallel_judge", bool),
        "prune.interval_hours": ("prune_interval_hours", int),
        "prune.max_age_days": ("prune_max_age_days", int),
        "vram.budget_mb": ("vram_budget_mb", int),
        "vram.auto_tune": ("auto_tune", bool),
        "vram.auto_load": ("auto_load", bool),
        "harness.epsilon": ("harness_epsilon", float),
        "harness.decay": ("harness_decay", float),
        "gen.timeout_s": ("gen_timeout_s", float),
        "cloud.provider": ("cloud_provider", str),
        "web_search.enabled": ("web_search_enabled", bool),
    }
    if req.key.startswith("image_gen."):
        attr = req.key.split(".")[1]
        if attr == "enabled":
            raw = str(req.value).strip().lower()
            CONFIG.image_gen["enabled"] = raw in ("1", "true", "yes", "on")
            return {"status": "updated", "key": req.key, "value": CONFIG.image_gen["enabled"]}
        if attr in ("width", "height"):
            v = int(req.value)
            if v < 256 or v > 512:
                raise HTTPException(400, f"{attr} must be between 256 and 512")
            CONFIG.image_gen[attr] = v
            return {"status": "updated", "key": req.key, "value": v}
        if attr == "steps":
            v = int(req.value)
            if v < 8 or v > 40:
                raise HTTPException(400, "steps must be between 8 and 40")
            CONFIG.image_gen[attr] = v
            return {"status": "updated", "key": req.key, "value": v}
        raise HTTPException(400, f"Unsupported image_gen key: {attr}")
    if req.key.startswith("vision."):
        attr = req.key.split(".")[1]
        if attr == "enabled":
            raw = str(req.value).strip().lower()
            CONFIG.vision["enabled"] = raw in ("1", "true", "yes", "on")
            return {"status": "updated", "key": req.key, "value": CONFIG.vision["enabled"]}
        if attr == "model":
            CONFIG.vision["model"] = str(req.value).strip()
            return {"status": "updated", "key": req.key, "value": CONFIG.vision["model"]}
        if attr == "max_tokens":
            v = int(req.value)
            if v < 16 or v > 1024:
                raise HTTPException(400, "vision.max_tokens must be between 16 and 1024")
            CONFIG.vision["max_tokens"] = v
            return {"status": "updated", "key": req.key, "value": v}
        raise HTTPException(400, f"Unsupported vision key: {attr}")
    if req.key.startswith("automl."):
        attr = req.key.split(".")[1]
        if attr == "enabled":
            raw = str(req.value).strip().lower()
            CONFIG.automl["enabled"] = raw in ("1", "true", "yes", "on")
            return {"status": "updated", "key": req.key, "value": CONFIG.automl["enabled"]}
        if attr == "model_dir":
            CONFIG.automl["model_dir"] = str(req.value).strip()
            return {"status": "updated", "key": req.key, "value": CONFIG.automl["model_dir"]}
        if attr == "time_limit":
            v = int(req.value)
            if v < 5 or v > 600:
                raise HTTPException(400, "automl.time_limit must be between 5 and 600")
            CONFIG.automl["time_limit"] = v
            return {"status": "updated", "key": req.key, "value": v}
        if attr == "n_jobs":
            v = int(req.value)
            if v < 1 or v > 8:
                raise HTTPException(400, "automl.n_jobs must be between 1 and 8")
            CONFIG.automl["n_jobs"] = v
            return {"status": "updated", "key": req.key, "value": v}
        if attr == "memory_limit_mb":
            v = int(req.value)
            if v < 256 or v > 32768:
                raise HTTPException(400, "automl.memory_limit_mb must be between 256 and 32768")
            CONFIG.automl["memory_limit_mb"] = v
            return {"status": "updated", "key": req.key, "value": v}
        raise HTTPException(400, f"Unsupported automl key: {attr}")
    if req.key.startswith("healing."):
        attr = req.key.split(".")[1]
        if attr == "enabled":
            raw = str(req.value).strip().lower()
            CONFIG.healing["enabled"] = raw in ("1", "true", "yes", "on")
            return {"status": "updated", "key": req.key, "value": CONFIG.healing["enabled"]}
        if attr == "max_retries":
            v = int(req.value)
            if v < 1 or v > 10:
                raise HTTPException(400, "healing.max_retries must be between 1 and 10")
            CONFIG.healing["max_retries"] = v
            return {"status": "updated", "key": req.key, "value": v}
        if attr == "timeout_s":
            v = int(req.value)
            if v < 5 or v > 600:
                raise HTTPException(400, "healing.timeout_s must be between 5 and 600")
            CONFIG.healing["timeout_s"] = v
            return {"status": "updated", "key": req.key, "value": v}
        raise HTTPException(400, f"Unsupported healing key: {attr}")
    if req.key == "api_token":
        CONFIG.set_api_token(str(req.value))
        return {"status": "updated", "key": req.key,
                "value": bool(CONFIG.api_token),
                "accepted": len(CONFIG.valid_api_tokens())}
    if req.key not in key_map and not req.key.startswith("model."):
        raise HTTPException(400, f"Unknown config key: {req.key}")

    if req.key.startswith("model."):
        return _update_model_config(req.key, req.value)

    attr_path, val_type = key_map[req.key]
    value: Any
    if val_type is bool:
        raw = str(req.value).strip().lower()
        value = raw in ("1", "true", "yes", "on")
    else:
        value = val_type(req.value)
    parts = attr_path.split(".")
    obj = CONFIG
    for p in parts[:-1]:
        obj = getattr(obj, p)
    setattr(obj, parts[-1], value)
    if attr_path == "threads":
        CONFIG.sync_threads()
    elif attr_path == "parallel_max":
        CONFIG.parallel_max = max(1, CONFIG.parallel_max)
        value = CONFIG.parallel_max
    elif attr_path == "prune_interval_hours":
        CONFIG.prune_interval_hours = max(1, CONFIG.prune_interval_hours)
        value = CONFIG.prune_interval_hours
    elif attr_path == "prune_max_age_days":
        CONFIG.prune_max_age_days = max(1, CONFIG.prune_max_age_days)
        value = CONFIG.prune_max_age_days
    elif attr_path == "vram_budget_mb":
        CONFIG.vram_budget_mb = max(0, CONFIG.vram_budget_mb)
        value = CONFIG.vram_budget_mb
    elif attr_path == "harness_epsilon":
        CONFIG.harness_epsilon = min(1.0, max(0.0, CONFIG.harness_epsilon))
        value = CONFIG.harness_epsilon
    elif attr_path == "harness_decay":
        CONFIG.harness_decay = min(1.0, max(0.5, CONFIG.harness_decay))
        value = CONFIG.harness_decay
    elif attr_path == "gen_timeout_s":
        CONFIG.gen_timeout_s = max(5.0, CONFIG.gen_timeout_s)
        value = CONFIG.gen_timeout_s
    elif attr_path == "cloud_provider":
        from config import CLOUD_PRESETS
        preset = CLOUD_PRESETS.get(str(value).strip().lower())
        if preset:
            CONFIG.openai.base_url = preset["base_url"]
            CONFIG.openai.chat_model = preset["chat_model"]
            CONFIG.cloud_provider = str(value).strip().lower()
            value = CONFIG.cloud_provider
        else:
            CONFIG.cloud_provider = "none"
            value = "none"
    return {"status": "updated", "key": req.key, "value": value}


def _update_model_config(key: str, value):
    """Handle dynamic keys like model.<name>.temperature / .max_tokens / .n_ctx / .role."""
    parts = key.split(".")
    if len(parts) != 3:
        raise HTTPException(400, f"Expected model.<name>.<attr>: {key}")
    _, name, attr = parts
    mc = next((m for m in CONFIG.available_models if m.name == name), None)
    if mc is None:
        mc = next((m for m in CONFIG.models if m.name == name), None)
    if mc is None:
        raise HTTPException(404, f"Model '{name}' not found")
    if attr not in ("temperature", "max_tokens", "n_ctx", "top_p", "role"):
        raise HTTPException(400, f"Unsupported model attribute: {attr}")
    if attr == "role":
        mc.role = str(value)
    elif attr == "temperature":
        mc.temperature = max(0.0, min(2.0, float(value)))
    elif attr == "top_p":
        mc.top_p = max(0.0, min(1.0, float(value)))
    elif attr in ("max_tokens", "n_ctx"):
        setattr(mc, attr, max(16, int(value)))
    return {"status": "updated", "key": key, "value": getattr(mc, attr)}

# ---------- Workspace API ----------

def _ws_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "ws").strip().lower()).strip("-")[:32]
    return (slug or "ws") + "-" + uuid.uuid4().hex[:6]


@app.get("/v1/workspaces")
def list_workspaces():
    try:
        import database as db
        return {"workspaces": db.list_workspaces()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/workspaces")
def create_workspace(req: WorkspaceRequest):
    try:
        import database as db
        if not req.name.strip():
            raise HTTPException(400, "workspace name required")
        ws_id = _ws_slug(req.name)
        ws = db.create_workspace(
            ws_id, req.name, req.description or "", req.system_prompt or "", req.default_model or ""
        )
        logger.info(f"Workspace created: {ws_id} ({req.name})")
        return {"workspace": ws, "id": ws_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/workspaces/{ws_id}/update")
def update_workspace(ws_id: str, req: WorkspaceUpdateRequest):
    try:
        import database as db
        fields = {k: v for k, v in req.model_dump().items() if v is not None}
        ws = db.update_workspace(ws_id, **fields)
        if ws is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        return {"status": "updated", "workspace": ws}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/workspaces/{ws_id}/delete")
def delete_workspace(ws_id: str):
    try:
        import database as db
        memory_manager.delete_workspace(ws_id)
        removed = db.delete_workspace(ws_id)
        if not removed:
            raise HTTPException(404, f"Workspace '{ws_id}' not found or is protected")
        logger.info(f"Workspace deleted: {ws_id}")
        return {"status": "deleted", "workspace_id": ws_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/files")
def list_workspace_files(ws_id: str):
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        files = db.list_workspace_files(ws_id)
        return {"files": files, "count": len(files)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/files/{name}/content")
def get_workspace_file_content(ws_id: str, name: str):
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        content = db.get_file_content(ws_id, name)
        if content is None:
            raise HTTPException(404, f"File '{name}' not found")
        return {"name": name, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/workspaces/{ws_id}/files/upload")
def upload_workspace_file(ws_id: str, req: FileUploadRequest):
    _MAX_FILE_BYTES = 5 * 1024 * 1024
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        name = (req.name or "file.txt").replace("\\", "/").split("/")[-1].strip()
        if not name:
            raise HTTPException(400, "file name required")
        content = req.content or ""
        if len(content.encode("utf-8", errors="replace")) > _MAX_FILE_BYTES:
            raise HTTPException(413, "File too large (max 5 MB)")
        chunks = db.chunk_text(content)
        stored = db.store_file_chunks(ws_id, name, chunks) if chunks else 0
        finfo = db.store_workspace_file(ws_id, name, len(content.encode("utf-8")), len(chunks))

        # Parse wiki-links, tags, headings for Obsidian-like knowledge graph
        link_info: dict[str, Any] = {"links": [], "tags": [], "headings": []}
        try:
            from wiki_links import knowledge_graph
            link_info = knowledge_graph.parse_document(ws_id, name, content)
            try:
                import graph_store
                graph_store.sync_wiki_links(ws_id)
            except Exception as ge:
                logger.warning(f"Graph sync failed for {name}: {ge}")
        except Exception as e:
            logger.warning(f"Wiki-link parse failed for {name}: {e}")

        logger.info(
            f"Uploaded {name} to workspace {ws_id}: {len(chunks)} chunks, {stored} embedded"
        )
        return {
            "status": "uploaded",
            "file": finfo,
            "chunks": len(chunks),
            "embedded": stored,
            "wiki_links": link_info.get("links", []),
            "tags": link_info.get("tags", []),
            "headings": link_info.get("headings", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/workspaces/{ws_id}/files/delete")
def delete_workspace_file(ws_id: str, name: str = Query(..., description="File name to delete")):
    try:
        import database as db
        removed = db.delete_workspace_file(ws_id, name)
        if not removed:
            raise HTTPException(404, f"File '{name}' not found in workspace '{ws_id}'")
        # Clean up knowledge graph
        try:
            from wiki_links import knowledge_graph
            knowledge_graph.remove_document(ws_id, name)
            try:
                import graph_store
                node_id = graph_store.find_node_by_title("document", name, ws_id)
                if node_id:
                    graph_store.delete_node(node_id)
            except Exception as ge:
                logger.warning(f"Graph node cleanup failed for {name}: {ge}")
        except Exception:  # noqa: B110
            pass  # best-effort KG cleanup
        return {"status": "deleted", "file": name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/knowledge/search")
def search_workspace_knowledge(ws_id: str, query: str = Query(..., description="Semantic query"),
                               limit: int = Query(default=5, le=50)):
    try:
        import database as db
        results = db.search_workspace_knowledge(ws_id, query, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------- Obsidian-like Knowledge Graph API ----------

@app.get("/v1/workspaces/{ws_id}/graph")
def get_knowledge_graph(ws_id: str):
    """Get the full knowledge graph: nodes (files), edges (wiki-links), tags."""
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        from wiki_links import knowledge_graph
        return knowledge_graph.get_graph(ws_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/backlinks")
def get_backlinks(ws_id: str, file: str = Query(..., description="Filename to find backlinks for")):
    """Get all documents that link to the specified file."""
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        from wiki_links import knowledge_graph
        backlinks = knowledge_graph.get_backlinks(ws_id, file)
        return {"file": file, "backlinks": sorted(backlinks), "count": len(backlinks)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/tags")
def get_all_tags(ws_id: str):
    """Get all tags in the workspace with file counts."""
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        from wiki_links import knowledge_graph
        tags = knowledge_graph.get_all_tags(ws_id)
        return {"tags": tags, "count": len(tags)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/tag/{tag}")
def get_files_by_tag(ws_id: str, tag: str):
    """Get all files that contain a specific tag."""
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        from wiki_links import knowledge_graph
        results = knowledge_graph.search_by_tag(ws_id, tag)
        return {"tag": tag, "files": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/orphans")
def get_orphaned_files(ws_id: str):
    """Find documents with no incoming or outgoing wiki-links."""
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        from wiki_links import knowledge_graph
        orphans = knowledge_graph.orphans(ws_id)
        return {"orphans": orphans, "count": len(orphans)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/recent")
def get_recent_files(ws_id: str, limit: int = Query(default=10, le=50)):
    """Get recently added documents."""
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        from wiki_links import knowledge_graph
        recent = knowledge_graph.recent(ws_id, limit=limit)
        return {"files": recent, "count": len(recent)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/v1/workspaces/{ws_id}/resolve")
def resolve_wikilink(
    ws_id: str,
    file: str = Query(..., description="Target filename"),
    heading: Optional[str] = Query(default=None, description="Optional heading to jump to"),
):
    """Resolve a [[wiki-link]] to its target document content."""
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        from wiki_links import knowledge_graph
        result = knowledge_graph.resolve_link(ws_id, file, heading=heading)
        if result is None:
            raise HTTPException(404, f"Document '{file}' not found in workspace")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------- Graph-Aware Vector Store API (nodes/edges/tags hybrid queries) ----------


@app.get("/v1/graph/stats")
def graph_stats():
    """Nodes/edges/tags counts and node-type breakdown."""
    import graph_store
    return graph_store.graph_stats()


@app.get("/v1/graph/tags")
def graph_tags():
    """List all global graph tags."""
    import graph_store
    return {"tags": graph_store.list_tags()}


@app.get("/v1/graph/recent")
def graph_recent(limit: int = Query(default=20, ge=1, le=100)):
    """List recently created graph nodes (global)."""
    import graph_store
    return {"nodes": graph_store.recent_nodes(limit=limit)}


@app.get("/v1/graph/nodes")
def graph_list_nodes(
    limit: int = Query(default=50, ge=1, le=500),
    node_type: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
):
    import graph_store
    return {"nodes": graph_store.list_nodes(limit=limit, node_type=node_type,
                                            workspace_id=workspace_id)}


@app.post("/v1/graph/nodes")
def graph_create_node(req: dict):
    """Create a node. Body: {node_type, title, content, metadata, workspace_id}."""
    import graph_store
    node_type = req.get("node_type", "concept")
    title = req.get("title", "")
    content = req.get("content", "")
    metadata = req.get("metadata")
    workspace_id = req.get("workspace_id", "default")
    node_id = graph_store.create_node(node_type, title, content, metadata,
                                      workspace_id=workspace_id, embed=True)
    if node_id is None:
        raise HTTPException(400, "title required (and DB must be enabled)")
    return {"id": node_id, "node": graph_store.get_node(node_id)}


@app.delete("/v1/graph/nodes/{node_id}")
def graph_delete_node(node_id: int):
    import graph_store
    if not graph_store.delete_node(node_id):
        raise HTTPException(404, f"Node {node_id} not found")
    return {"status": "deleted", "id": node_id}


@app.get("/v1/graph/nodes/{node_id}")
def graph_get_node(node_id: int):
    import graph_store
    node = graph_store.get_node(node_id)
    if node is None:
        raise HTTPException(404, f"Node {node_id} not found")
    return {"node": node}


@app.get("/v1/graph/search")
def graph_search(
    q: str = Query(..., description="Query text"),
    limit: int = Query(default=5, ge=1, le=20),
    node_type: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
):
    """Pure vector similarity search over nodes."""
    import graph_store
    return {"results": graph_store.search_nodes(q, limit=limit, node_type=node_type,
                                                workspace_id=workspace_id)}


@app.get("/v1/graph/hybrid")
def graph_hybrid_search(
    q: str = Query(..., description="Query text"),
    limit: int = Query(default=5, ge=1, le=20),
    workspace_id: Optional[str] = Query(default=None),
    expand: int = Query(default=3, ge=0, le=10),
):
    """Hybrid search: vector candidates + their graph neighbours and degrees."""
    import graph_store
    return {"results": graph_store.hybrid_search(q, limit=limit, workspace_id=workspace_id,
                                                 expand=expand)}


@app.get("/v1/graph/links/{node_id}")
def graph_node_links(node_id: int):
    """Outgoing + incoming edges for a node."""
    import graph_store
    return {
        "linked": graph_store.linked_nodes(node_id),
        "backlinked": graph_store.backlinks(node_id),
        "degrees": graph_store.node_degrees(node_id),
    }


@app.get("/v1/graph/edges")
def graph_edges(limit: int = Query(default=200, ge=1, le=1000)):
    import graph_store
    return {"edges": graph_store.list_edges(limit=limit)}


@app.post("/v1/graph/edges")
def graph_add_edge(req: dict):
    """Add an edge. Body: {source_id, target_id, edge_type, weight}."""
    import graph_store
    src_id = req.get("source_id")
    tgt_id = req.get("target_id")
    if not isinstance(src_id, int) or not isinstance(tgt_id, int):
        raise HTTPException(400, "source_id and target_id must be integers")
    ok = graph_store.add_edge(src_id, tgt_id,
                              req.get("edge_type", "wikilink"),
                              float(req.get("weight", 1.0)))
    if not ok:
        raise HTTPException(400, "source_id, target_id required (and DB must be enabled)")
    return {"status": "added"}


@app.get("/v1/graph/path")
def graph_path(
    start: int = Query(..., description="Start node id"),
    end: int = Query(..., description="End node id"),
    max_depth: int = Query(default=10, ge=1, le=15),
):
    """Shortest path between two node ids (recursive CTE)."""
    import graph_store
    return graph_store.shortest_path(start, end, max_depth=max_depth)


@app.get("/v1/graph/path/titles")
def graph_path_titles(
    workspace_id: str = Query(default="default"),
    title_a: str = Query(..., description="Start title"),
    title_b: str = Query(..., description="End title"),
    node_type: str = Query(default="concept"),
    max_depth: int = Query(default=10, ge=1, le=15),
):
    """Resolve two titles to nodes, then shortest path between them."""
    import graph_store
    return graph_store.path_between_titles(workspace_id, title_a, title_b,
                                           node_type=node_type, max_depth=max_depth)


@app.post("/v1/graph/sync")
def graph_sync(workspace_id: str = Query(default="default")):
    """Persist the in-memory knowledge graph (wiki-links/tags) into nodes/edges."""
    import graph_store
    return graph_store.sync_wiki_links(workspace_id)


@app.post("/v1/graph/migrate")
def graph_migrate():
    """One-time migration of agent_memory rows into nodes (node_type='memory')."""
    import graph_store
    return graph_store.migrate_memory_to_nodes()


@app.get("/v1/workspaces/{ws_id}/export")
def export_workspace(ws_id: str, format: str = Query(default="json", pattern="^(json|markdown)$")):
    try:
        import database as db
        ws = db.get_workspace(ws_id)
        if ws is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        convs = []
        for cid, conv in memory_manager.conversations_for(ws_id):
            convs.append({
                "id": cid,
                "title": _conv_title(cid, conv),
                "system_prompt": conv.system_prompt or "",
                "created_at": conv.created_at,
                "messages": [m.to_dict() for m in conv.messages],
            })
        if format == "markdown":
            md = [f"# Workspace: {ws['name']}", ""]
            if ws.get("description"):
                md += [ws["description"], ""]
            if ws.get("system_prompt"):
                md += ["> System prompt: " + ws["system_prompt"].replace("\n", "\n> "), ""]
            for c in convs:
                md += [f"## {c['title']}", ""]
                if c["system_prompt"]:
                    md += ["> System prompt: " + c["system_prompt"].replace("\n", "\n> "), ""]
                for m in c["messages"]:
                    who = "User" if m["role"] == "user" else "Assistant"
                    md += [f"**{who}:**", "", m["content"], ""]
            body = "\n".join(md)
            return PlainTextResponse(body, media_type="text/markdown")
        return {"workspace": ws, "conversations": convs, "count": len(convs)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/workspaces/{ws_id}/import")
def import_workspace(ws_id: str, req: ImportRequest):
    try:
        import database as db
        if db.get_workspace(ws_id) is None:
            raise HTTPException(404, f"Workspace '{ws_id}' not found")
        imported = 0
        for c in req.conversations:
            cid = str(c.get("id") or f"import-{uuid.uuid4().hex[:8]}")
            existing = memory_manager.conversations.get(cid)
            if existing is not None and existing.workspace_id != ws_id:
                memory_manager.reassign_workspace(cid, ws_id)
            conv = memory_manager.get_or_create(cid, ws_id)
            conv.clear()
            sys_p = c.get("system_prompt")
            if sys_p:
                conv.set_system(sys_p)
            for m in c.get("messages") or []:
                role = str(m.get("role") or "user")
                if role not in ("user", "assistant", "system"):
                    role = "user"
                content = str(m.get("content") or "")
                if role == "system":
                    conv.set_system(content)
                else:
                    conv.add(role, content)
            imported += 1
        logger.info(f"Imported {imported} conversations into workspace {ws_id}")
        return {"status": "imported", "conversations": imported}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------- Admin API ----------

@app.get("/v1/admin/logs")
def admin_logs(lines: int = Query(default=200, ge=1, le=2000)):
    out = _log_ring.lines(lines)
    return {"count": len(out), "lines": out}


@app.get("/v1/admin/threads")
def admin_threads():
    threads = []
    for t in threading.enumerate():
        threads.append({
            "name": t.name,
            "daemon": t.daemon,
            "alive": t.is_alive(),
            "ident": t.ident,
        })
    return {"count": len(threads), "threads": threads}


@app.get("/v1/admin/metrics")
def admin_metrics():
    from metrics import metrics
    snap = metrics.snapshot()
    snap["uptime_s"] = round(time.time() - _start_ts, 1)
    snap["threads"] = threading.active_count()
    return snap


# ---------- Computer Agent API ----------

@app.get("/v1/computer/tools")
def computer_tools():
    from computer_agent import create_computer_agent
    agent = create_computer_agent(model_manager, orchestrator)
    return {"tools": [{"name": t.name, "description": t.description,
                        "sandbox_safe": t.sandbox_safe, "dangerous": t.dangerous,
                        "parameters": t.parameters}
                       for t in agent.registry.list_tools()]}


class ComputerRunRequest(BaseModel):
    goal: str
    sandbox: bool = False
    max_steps: int = 25

    @field_validator('max_steps')
    @classmethod
    def validate_max_steps(cls, v):  # noqa: unused
        if v < 1 or v > 50:
            raise ValueError('max_steps must be between 1 and 50')
        return v


@app.post("/v1/computer/run")
def computer_run(req: ComputerRunRequest):
    from computer_agent import create_computer_agent
    agent = create_computer_agent(model_manager, orchestrator,
                                  sandbox=bool(CONFIG.sandbox or req.sandbox), max_steps=req.max_steps)
    result = agent.run(req.goal)
    return {
        "success": result.success,
        "final_answer": result.final_answer,
        "steps": [{"step": s.step_num, "thought": s.thought[:200],
                    "tool": s.tool_name, "args": str(s.tool_args)[:500],
                    "result": s.tool_result.output[:500] if s.tool_result else None,
                    "success": s.tool_result.success if s.tool_result else None,
                    "elapsed_s": round(s.elapsed_s, 2)}
                   for s in result.steps],
        "total_elapsed_s": round(result.total_elapsed_s, 2),
        "total_steps": len(result.steps),
    }


@app.post("/v1/computer/stream")
async def computer_stream(req: ComputerRunRequest):
    from computer_agent import create_computer_agent
    import json as _json

    agent = create_computer_agent(model_manager, orchestrator,
                                  sandbox=bool(CONFIG.sandbox or req.sandbox), max_steps=req.max_steps)

    async def event_gen():
        for event in agent.run_stream(req.goal):
            yield f"data: {_json.dumps(event)}\n\n"
        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    from starlette.responses import StreamingResponse
    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ---------- Conversation API ----------

def _conv_title(conv_id: str, conv) -> str:
    first = next((m.content for m in conv.messages if m.role == "user"), None)
    if first:
        return " ".join(first.split())[:80]
    return conv_id


@app.get("/v1/chat/history")
def chat_history(
    conv_id: str = "default",
    limit: int = Query(default=50, le=200),
    workspace_id: str = Query(default="default"),
):
    conv = memory_manager.conversations.get(conv_id)
    if conv is None:
        return {
            "conversation_id": conv_id,
            "workspace_id": workspace_id,
            "messages": [],
            "count": 0,
            "error": "not_found",
        }
    if conv.workspace_id != workspace_id:
        return {
            "conversation_id": conv_id,
            "workspace_id": workspace_id,
            "messages": [],
            "count": 0,
            "error": "workspace_mismatch",
        }
    msgs = [m.to_dict() for m in conv.messages[-limit:]]
    return {
        "conversation_id": conv_id,
        "workspace_id": workspace_id,
        "messages": msgs,
        "count": len(msgs),
    }


@app.post("/v1/chat/clear")
def chat_clear(conv_id: str = "default", workspace_id: str = Query(default="default")):
    conv = memory_manager.conversations.get(conv_id)
    if conv is not None and conv.workspace_id == workspace_id:
        memory_manager.delete(conv_id)
    return {"status": "cleared", "conversation_id": conv_id, "workspace_id": workspace_id}


@app.delete("/v1/chat/conversations")
def chat_delete(conv_id: str = Query(...), workspace_id: str = Query(default="default")):
    conv = memory_manager.conversations.get(conv_id)
    if conv is None or conv.workspace_id != workspace_id:
        raise HTTPException(404, "Conversation not found")
    memory_manager.delete(conv_id)
    return {"status": "deleted", "conversation_id": conv_id, "workspace_id": workspace_id}


@app.get("/v1/chat/conversations")
def list_conversations(labels: Optional[bool] = False,
                       workspace_id: str = Query(default="default")):
    convs = memory_manager.conversations_for(workspace_id)
    out = []
    for cid, conv in convs:
        entry = {"id": cid}
        if labels:
            entry.update({
                "title": _conv_title(cid, conv),
                "count": len(conv.messages),
                "created_at": conv.created_at,
            })
        out.append(entry)
    out.sort(key=lambda c: c.get("created_at", 0), reverse=True)
    return {"conversations": out, "workspace_id": workspace_id}

# ---------- Generate API ----------

@app.post("/v1/generate")
def raw_generate(req: GenerateRequest):
    if not model_manager.configs:
        raise HTTPException(400, "No models loaded")
    model = req.model or list(model_manager.configs.keys())[0]
    if not model or model not in model_manager.configs:
        raise HTTPException(400, f"Model '{model}' not available")
    try:
        messages = [{"role": "user", "content": req.prompt}]
        text = model_manager.chat(
            name=model,
            messages=messages,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        return {
            "id": f"gen-{uuid.uuid4().hex[:12]}",
            "model": model,
            "choices": [
                {"text": text, "index": 0, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": len(req.prompt.split()),
                "completion_tokens": len(text.split()),
            },
        }
    except Exception as e:
        raise HTTPException(500, str(e))

# ---------- Batch API ----------

@app.post("/v1/batch/generate")
def batch_generate(req: BatchRequest):
    if not model_manager.configs:
        raise HTTPException(400, "No models loaded")
    model = req.model or list(model_manager.configs.keys())[0]
    if not model or model not in model_manager.configs:
        raise HTTPException(400, f"Model '{model}' not available")
    results = []
    for i, prompt in enumerate(req.prompts):
        try:
            text = model_manager.generate(model, prompt, req.max_tokens, req.temperature)
            results.append({"index": i, "text": text, "status": "ok"})
        except Exception as e:
            results.append({"index": i, "text": "", "status": str(e)})
    return {"model": model, "results": results}

# ---------- Chat Completion API (OpenAI-compatible) ----------

def _workspace_system_prompt(workspace_id: str) -> Optional[str]:
    """Return the workspace's custom system prompt, if any."""
    if not workspace_id or workspace_id == "default":
        return None
    try:
        import database as db
        ws = db.get_workspace(workspace_id)
        if ws and ws.get("system_prompt"):
            return ws["system_prompt"]
    except Exception:  # noqa: B110
        pass  # tolerate missing DB during system prompt lookup
    return None


def _prepare_conversation(req: ChatRequest, workspace_id: str):
    """Replay the client's message history into a fresh conversation.

    Returns (conv_id, last_user_message, system_override). The last user
    message is what the orchestrator will answer; everything before it is
    kept as prior context for true multi-turn support.
    """
    conv_id = f"api-{uuid.uuid4().hex[:8]}"
    conv = memory_manager.get_or_create(conv_id, workspace_id)
    conv.clear()
    system_override = None
    history = []
    for m in req.messages:
        if m.role == "system":
            system_override = m.content
        else:
            history.append((m.role, m.content))
    user_idx = -1
    for i in range(len(history) - 1, -1, -1):
        if history[i][0] == "user":
            user_idx = i
            break
    if user_idx == -1:
        return conv_id, None, system_override
    for role, content in history[:user_idx]:
        conv.add(role, content)
    return conv_id, history[user_idx][1], system_override


def _resolve_conversation(req: ChatRequest, workspace_id: str):
    """Return (conv_id, last_user_message, system_override).

    With `conversation_id` the server keeps a live multi-turn conversation in
    memory and only the latest user message needs sending. Without it, the
    client's full message list is replayed into a fresh conversation.
    Workspace system prompts are injected when the request carries none.
    """
    system_override = next((m.content for m in req.messages if m.role == "system"), None)
    ws_sys = _workspace_system_prompt(workspace_id)
    if ws_sys:
        if system_override:
            system_override = f"{ws_sys}\n\n{system_override}"
        else:
            system_override = ws_sys
    if req.conversation_id:
        user_msg = next((m.content for m in reversed(req.messages) if m.role == "user"), None)
        if user_msg is None:
            raise HTTPException(400, "no user message")
        existing = memory_manager.get(req.conversation_id)
        if existing is not None and existing.workspace_id != workspace_id:
            raise HTTPException(
                403, f"conversation '{req.conversation_id}' "
                f"belongs to workspace '{existing.workspace_id}'"
            )
        return req.conversation_id, user_msg, system_override
    conv_id, user_msg, replay_system = _prepare_conversation(req, workspace_id)
    if user_msg is None:
        raise HTTPException(400, "no user message")
    if system_override is None:
        system_override = replay_system
    return conv_id, user_msg, system_override


def _apply_agent_skill(req: ChatRequest, user_msg: Optional[str], system_override):
    """Apply a selected agent persona (system prompt) and/or skill template
    to the resolved user message + system prompt, mirroring the dedicated
    /v1/agents/{name}/run and /v1/skills/{name}/run endpoints."""
    import agents as _agents

    if req.agent:
        a = _agents.get_agent(req.agent)
        if a is None:
            raise HTTPException(404, f"Unknown agent '{req.agent}'. Available: {_agents.list_agents()}")
        system_override = a.get("system_prompt") or system_override

    if req.skill:
        rendered = _agents.render_skill(req.skill, user_msg or "", {})
        if rendered is None:
            raise HTTPException(404, f"Unknown skill '{req.skill}'. Available: {_agents.list_skills()}")
        user_msg = rendered["prompt"]
        if rendered.get("system_prompt"):
            system_override = rendered["system_prompt"]

    return user_msg, system_override


@app.post("/v1/chat/completions")
def chat_completion(req: ChatRequest):
    if not req.messages:
        raise HTTPException(400, "messages required")
    workspace_id = (req.workspace_id or "default").strip() or "default"
    conv_id, user_msg, system_override = _resolve_conversation(req, workspace_id)
    user_msg, system_override = _apply_agent_skill(req, user_msg, system_override)
    if req.stream:
        return _stream_response(req, user_msg, conv_id, system_override, workspace_id)
    return _full_response(req, user_msg, conv_id, system_override, workspace_id)


def _full_response(req, user_msg, conv_id, system, workspace_id):
    try:
        result = orchestrator.run(
            user_message=user_msg,
            conv_id=conv_id,
            use_planning=req.use_planning,
            system_override=system,
            model_override=req.model or None,
            parallel=req.parallel,
            sandbox=req.sandbox,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            workspace_id=workspace_id,
        )
    except Exception as e:
        logger.exception("Orch error")
        raise HTTPException(500, str(e))
    content = result.get("response") or ""
    resp = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.get("model") or req.model or "local",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "thinking": result.get("thinking") or None,
        "conversation_id": conv_id,
        "usage": {
            "prompt_tokens": len(user_msg.split()),
            "completion_tokens": len(content.split()),
            "total_tokens": len(user_msg.split()) + len(content.split()),
        },
    }
    if result.get("parallel_candidates"):
        resp["runner_model"] = result["model"]
        resp["parallel_candidates"] = result["parallel_candidates"]
    return resp


def _run_stream_in_worker(events, queue, stop):
    """Push orchestrator stream events into an asyncio.Queue from a worker thread."""
    try:
        for evt in events:
            if stop.is_set():
                break
            queue.put_nowait(evt)
            if stop.is_set():
                break
    except Exception as e:
        queue.put_nowait({"type": "error", "content": str(e)})
    finally:
        queue.put_nowait({"type": "done"})


def _stream_response(req, user_msg, conv_id, system, workspace_id):
    async def generate():
        yield f"data: {json.dumps({'conversation_id': conv_id})}\n\n"
        queue = asyncio.Queue()
        stop = threading.Event()
        task = asyncio.get_running_loop().run_in_executor(
            None, _run_stream_in_worker,
            orchestrator.stream(
                user_message=user_msg,
                conv_id=conv_id,
                use_planning=req.use_planning,
                system_override=system,
                model_override=req.model or None,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                workspace_id=workspace_id,
                sandbox=bool(CONFIG.sandbox or req.sandbox),
            ),
            queue,
            stop,
        )
        try:
            while True:
                evt = await queue.get()
                if evt.get("type") == "done":
                    break
                yield f"data: {json.dumps(evt)}\n\n"
        finally:
            stop.set()
            if not task.done():
                task.cancel()
        yield "data: [DONE]\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

# ---------- Streaming with token-by-token output ----------

@app.post("/v1/chat/stream")
async def chat_stream_full(req: ChatRequest):
    if not req.messages:
        raise HTTPException(400, "messages required")
    workspace_id = (req.workspace_id or "default").strip() or "default"
    conv_id, user_msg, system_override = _resolve_conversation(req, workspace_id)
    user_msg, system_override = _apply_agent_skill(req, user_msg, system_override)

    async def generate():
        queue = asyncio.Queue()
        stop = threading.Event()
        task = asyncio.get_running_loop().run_in_executor(
            None, _run_stream_in_worker,
            orchestrator.stream(
                user_message=user_msg,
                conv_id=conv_id,
                use_planning=req.use_planning,
                system_override=system_override,
                model_override=req.model or None,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                workspace_id=workspace_id,
                sandbox=bool(CONFIG.sandbox or req.sandbox),
            ),
            queue,
            stop,
        )
        try:
            while True:
                evt = await queue.get()
                if evt.get("type") == "done":
                    break
                yield f"data: {json.dumps(evt)}\n\n"
        finally:
            stop.set()
            if not task.done():
                task.cancel()

    return StreamingResponse(generate(), media_type="text/event-stream")

# ---------- Auto-agentic streaming ----------

@app.post("/v1/chat/auto-stream")
async def chat_auto_stream(req: ChatRequest):
    """Auto-agentic streaming: orchestrator picks streaming vs batch per request
    and streams thinking + response in real-time (or falls back to batch)."""
    if not req.messages:
        raise HTTPException(400, "messages required")
    workspace_id = (req.workspace_id or "default").strip() or "default"
    conv_id, user_msg, system_override = _resolve_conversation(req, workspace_id)
    user_msg, system_override = _apply_agent_skill(req, user_msg, system_override)

    async def generate():
        queue = asyncio.Queue()
        stop = threading.Event()
        task = asyncio.get_running_loop().run_in_executor(
            None, _run_stream_in_worker,
            orchestrator.auto_stream(
                user_message=user_msg,
                conv_id=conv_id,
                use_planning=req.use_planning,
                system_override=system_override,
                model_override=req.model or None,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                workspace_id=workspace_id,
                sandbox=bool(CONFIG.sandbox or req.sandbox),
                stream_thoughts=CONFIG.auto_stream_thinking,
            ),
            queue,
            stop,
        )
        try:
            while True:
                evt = await queue.get()
                if evt.get("type") == "done":
                    break
                yield f"data: {json.dumps(evt)}\n\n"
        finally:
            stop.set()
            if not task.done():
                task.cancel()

    return StreamingResponse(generate(), media_type="text/event-stream")

# ---------- Chat file uploads ----------

@app.post("/v1/chat/upload")
async def upload_chat_file(file: UploadFile = File(...)):
    """Upload a file for use in chat. Stored under generated/chat_uploads/
    and returned as a markdown-referenceable URL (/generated/chat_uploads/...)."""
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "generated", "chat_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    orig = (file.filename or "file").replace("\\", "/").split("/")[-1]
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", orig)[:120] or "file"
    path = os.path.join(upload_dir, f"{uuid.uuid4().hex}_{safe}")
    written = 0
    try:
        with open(path, "wb") as out:
            while True:
                chunk = await file.read(256 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > 20 * 1024 * 1024:
                    raise HTTPException(413, "file too large (max 20MB)")
                out.write(chunk)
    except HTTPException:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    finally:
        await file.close()
    preview_text = None
    is_image = orig.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
    if orig.lower().endswith(".pdf"):
        preview_text = _extract_pdf_text(path)
    elif is_image:
        try:
            import vision  # noqa: PLC0415
            if vision.vision_enabled():
                desc = vision.describe_image_file(path)
                preview_text = (desc[:2000] + "...") if len(desc) > 2000 else (desc or None)
        except Exception:
            preview_text = None
    return {
        "name": orig,
        "url": f"/generated/chat_uploads/{os.path.basename(path)}",
        "preview_text": preview_text,
        "is_image": is_image,
    }


def _extract_pdf_text(path: str, limit: int = 8000) -> Optional[str]:
    """Best-effort PDF text extraction (requires pypdf or PyPDF2). Returns
    None when no extractor is installed or the document has no extractable text."""
    try:
        from pypdf import PdfReader as PdfReaderPypdf
        reader_cls = PdfReaderPypdf
    except ImportError:
        try:
            from PyPDF2 import PdfReader as PdfReaderLegacy
        except ImportError:
            return None
        reader_cls = PdfReaderLegacy
    try:
        parts = []
        total = 0
        reader = reader_cls(path)
        for page in reader.pages:
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                parts.append(text)
                total += len(text)
                if total >= limit:
                    break
        if not parts:
            return None
        return "\n\n".join(parts)[:limit] or None
    except Exception:
        return None

# ---------- Tool API ----------

class ToolRequest(BaseModel):
    text: str
    max_length: Optional[int] = 200

@app.post("/v1/tools/summarize")
def tool_summarize(req: ToolRequest):
    if not model_manager.configs:
        raise HTTPException(400, "No models loaded")
    if "minicpm-v9" in model_manager.configs:
        model = "minicpm-v9"
    else:
        model = list(model_manager.configs.keys())[0]
    prompt = f"Summarize the following text concisely:\n\n{req.text}\n\nSummary:"
    try:
        text = model_manager.generate(model, prompt, max_tokens=req.max_length)
        return {"summary": text}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/v1/tools/analyze")
def tool_analyze(req: ToolRequest):
    if not model_manager.configs:
        raise HTTPException(400, "No models loaded")
    if "hy-mt2" in model_manager.configs:
        model = "hy-mt2"
    else:
        model = list(model_manager.configs.keys())[0]
    prompt = (
        f"Analyze the following text. Identify key points, themes, and insights:\n\n"
        f"{req.text}\n\nAnalysis:"
    )
    try:
        text = model_manager.generate(model, prompt, max_tokens=req.max_length)
        return {"analysis": text}
    except Exception as e:
        raise HTTPException(500, str(e))


class TranslateRequest(BaseModel):
    text: str
    target_language: str = "English"

@app.post("/v1/tools/translate")
def tool_translate(req: TranslateRequest):
    if not model_manager.configs:
        raise HTTPException(400, "No models loaded")
    if "minicpm-v9" in model_manager.configs:
        model = "minicpm-v9"
    else:
        model = list(model_manager.configs.keys())[0]
    prompt = (
        f"Translate the following text to {req.target_language}:\n\n"
        f"{req.text}\n\nTranslation:"
    )
    try:
        text = model_manager.generate(model, prompt, max_tokens=512)
        return {"translation": text, "target_language": req.target_language}
    except Exception as e:
        raise HTTPException(500, str(e))

# ---------- Agents & Skills API ----------

class SkillRunRequest(BaseModel):
    input: str
    params: Optional[Dict[str, Any]] = None
    model: str = ""

class AgentRunRequest(BaseModel):
    message: str
    model: str = ""
    use_planning: bool = True
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

class AgentCreateRequest(BaseModel):
    name: str
    system_prompt: str = ""
    role: str = ""
    description: str = ""
    keywords: List[str] = []

class SkillCreateRequest(BaseModel):
    name: str
    template: str
    system_prompt: str = ""
    description: str = ""
    params: List[Dict[str, Any]] = []

@app.get("/v1/agents")
def list_agents():
    import agents
    return {
        "agents": [
            {"name": a["name"], "role": a["role"], "description": a["description"]}
            for a in (agents.get_agent(n) for n in agents.list_agents())
        ]
    }

@app.get("/v1/agents/{name}")
def get_agent(name: str):
    import agents
    a = agents.get_agent(name)
    if a is None:
        raise HTTPException(404, f"Unknown agent '{name}'. Available: {agents.list_agents()}")
    return {"name": a["name"], "role": a["role"], "description": a["description"],
            "system_prompt": a["system_prompt"]}

@app.post("/v1/agents/{name}/run")
def run_agent(name: str, req: AgentRunRequest):
    import agents
    a = agents.get_agent(name)
    if a is None:
        raise HTTPException(404, f"Unknown agent '{name}'. Available: {agents.list_agents()}")
    if not req.message.strip():
        raise HTTPException(400, "message required")
    try:
        result = orchestrator.run(
            user_message=req.message,
            conv_id=f"agent-{name}-{uuid.uuid4().hex[:8]}",
            use_planning=req.use_planning,
            system_override=a["system_prompt"],
            model_override=req.model or None,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        return {"agent": name, "response": result["response"], "model": result.get("model")}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/v1/skills")
def list_skills():
    import agents
    return {
        "skills": [
            {"name": s["name"], "description": s["description"],
             "params": [p["name"] for p in s.get("params", [])]}
            for s in (agents.get_skill(n) for n in agents.list_skills())
        ]
    }

@app.get("/v1/skills/{name}")
def get_skill(name: str):
    import agents
    s = agents.get_skill(name)
    if s is None:
        raise HTTPException(404, f"Unknown skill '{name}'. Available: {agents.list_skills()}")
    return {"name": s["name"], "description": s["description"],
            "system_prompt": s["system_prompt"], "template": s["template"],
            "params": s.get("params", [])}

@app.post("/v1/skills/{name}/run")
def run_skill(name: str, req: SkillRunRequest):
    import agents
    if not req.input.strip():
        raise HTTPException(400, "input required")
    try:
        rendered = agents.render_skill(name, req.input, req.params)
        if rendered is None:
            available = ", ".join(agents.list_skills())
            raise HTTPException(
                404, f"Unknown skill '{name}'. Available: {available}"
            )
        result = orchestrator.run(
            user_message=rendered["prompt"],
            conv_id=f"skill-{name}-{uuid.uuid4().hex[:8]}",
            use_planning=False,
            system_override=rendered["system_prompt"],
            model_override=req.model or None,
            max_tokens=1024,
        )
        return {
            "skill": rendered["name"],
            "response": result["response"],
            "model": result.get("model"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/v1/agents")
def create_agent(req: AgentCreateRequest):
    import agents
    try:
        a = agents.add_agent(
            name=req.name,
            system_prompt=req.system_prompt or (
                f"You are {req.name}, a helpful AI agent. "
                "Keep answers clear and concise."
            ),
            role=req.role,
            description=req.description,
            keywords=req.keywords,
        )
        return {"agent": a, "created": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))

@app.delete("/v1/agents/{name}")
def delete_agent(name: str):
    import agents
    if agents.delete_agent(name):
        return {"deleted": name}
    raise HTTPException(404, f"Agent '{name}' not found (or is built-in and cannot be deleted)")

@app.post("/v1/skills")
def create_skill(req: SkillCreateRequest):
    import agents
    try:
        s = agents.add_skill(
            name=req.name,
            template=req.template,
            system_prompt=req.system_prompt,
            description=req.description,
            params=req.params,
        )
        return {"skill": s, "created": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))

@app.delete("/v1/skills/{name}")
def delete_skill(name: str):
    import agents
    if agents.delete_skill(name):
        return {"deleted": name}
    raise HTTPException(404, f"Skill '{name}' not found (or is built-in and cannot be deleted)")

# ---------- MCP Endpoint ----------

def _build_mcp_tools() -> list:
    """Build the full MCP tools list from chat + agents + skills registries."""
    import agents as _agents
    tools = [
        {
            "name": "chat",
            "description": "Chat with the AI assistant using the orchestrator pipeline (planning, memory, routing).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "The user message to send to the chat."},
                },
                "required": ["input"],
            },
        }
    ]
    for n in _agents.list_agents():
        a = _agents.get_agent(n)
        if a is None:
            continue
        tools.append({
            "name": n,
            "description": a["description"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "The message to send to this agent."},
                },
                "required": ["input"],
            },
        })
    for n in _agents.list_skills():
        s = _agents.get_skill(n)
        if s is None:
            continue
        props: dict = {"input": {"type": "string", "description": "The input text to process."}}
        required = ["input"]
        for p in s.get("params", []):
            pname = p["name"]
            props[pname] = {
                "type": "string",
                "description": f"Parameter '{pname}' (default: {p.get('default', '')}).",
            }
        tools.append({
            "name": n,
            "description": s["description"],
            "inputSchema": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        })
    return tools


@app.get("/mcp")
def mcp_get_tools():
    """Return MCP tools list via GET for browser/admin panel discovery."""
    return {"tools": _build_mcp_tools()}


@app.post("/mcp")
def mcp_endpoint(req: MCPRequest):
    import agents
    if req.jsonrpc != "2.0":
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Invalid Request: only jsonrpc 2.0 supported"},
            "id": req.id,
        })
    if req.method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "result": _build_mcp_tools(),
            "id": req.id,
        }
    if req.method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "result": [],
            "id": req.id,
        }
    if req.method == "tools/call":
        params = req.params or {}
        tool = params.get("name", "")
        raw_args = params.get("arguments") or {}
        if not isinstance(raw_args, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32602, "message": "arguments must be an object"},
                    "id": req.id,
                }
            )
        args = raw_args
        if not tool and params.get("input"):
            tool, args = "chat", {"input": params["input"]}
        if not tool:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32602, "message": "Missing tool name"},
                    "id": req.id,
                }
            )
        user_message = str(args.get("input", "")).strip()
        if not user_message:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32602, "message": "input must not be empty"},
                    "id": req.id,
                }
            )
        try:
            if tool == "chat":
                conv_id = f"mcp-{uuid.uuid4().hex[:8]}"
                result = orchestrator.run(
                    user_message=user_message,
                    conv_id=conv_id,
                    use_planning=True,
                )
                return {
                    "jsonrpc": "2.0",
                    "result": {"content": [{"type": "text", "text": result["response"]}]},
                    "id": req.id,
                }
            if tool in agents.AGENTS:
                a = agents.get_agent(tool)
                if a is None:
                    return JSONResponse({
                        "jsonrpc": "2.0",
                        "error": {"code": -32602, "message": f"Agent '{tool}' not found"},
                        "id": req.id,
                    })
                result = orchestrator.run(
                    user_message=user_message,
                    conv_id=f"mcp-agent-{uuid.uuid4().hex[:8]}",
                    use_planning=args.get("use_planning", True),
                    system_override=a["system_prompt"],
                )
                return {
                    "jsonrpc": "2.0",
                    "result": {"content": [{"type": "text", "text": result["response"]}]},
                    "id": req.id,
                }
            if tool in agents.SKILLS:
                rendered = agents.render_skill(tool, user_message, {k: v for k, v in args.items() if k != "input"})
                if rendered is None:
                    return JSONResponse({
                        "jsonrpc": "2.0",
                        "error": {"code": -32602, "message": f"Unknown skill '{tool}'"},
                        "id": req.id,
                    })
                result = orchestrator.run(
                    user_message=rendered["prompt"],
                    conv_id=f"mcp-skill-{uuid.uuid4().hex[:8]}",
                    use_planning=False,
                    system_override=rendered["system_prompt"],
                )
                return {
                    "jsonrpc": "2.0",
                    "result": {"content": [{"type": "text", "text": result["response"]}]},
                    "id": req.id,
                }
        except HTTPException as e:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32602, "message": e.detail},
                    "id": req.id,
                }
            )
        except Exception as e:
            logger.error(f"MCP tools/call '{tool}' failed: {e}", exc_info=True)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                    "id": req.id,
                }
            )
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32602,
                    "message": f"Unknown tool '{tool}'",
                },
                "id": req.id,
            }
        )
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "error": {
                "code": -32601,
                "message": "Method not found",
            },
            "id": req.id,
        }
    )

# ---------- LoRA Adapter API ----------

@app.get("/v1/loras")
def list_loras():
    from lora_manager import list_adapters
    return {"loras": [{"name": a.name, "path": a.path, "base_model": a.base_model,
                       "enabled": a.enabled, "scale": a.scale} for a in list_adapters()]}


@app.post("/v1/loras/import")
def import_lora(req: dict):
    src = req.get("path", "")
    name = req.get("name", "")
    if not src:
        raise HTTPException(400, "path required")
    from lora_manager import import_adapter
    a = import_adapter(src, name)
    if a is None:
        raise HTTPException(400, "import failed")
    return {"status": "imported", "name": a.name}


@app.post("/v1/loras/{name}/enable")
def enable_lora(name: str, req: dict):
    model = req.get("model", "")
    from lora_manager import enable_adapter
    if not enable_adapter(name, model):
        raise HTTPException(404, f"LoRA '{name}' not found")
    return {"status": "enabled", "name": name, "model": model}


@app.post("/v1/loras/{name}/disable")
def disable_lora(name: str):
    from lora_manager import disable_adapter
    disable_adapter(name)
    return {"status": "disabled", "name": name}


@app.delete("/v1/loras/{name}")
def delete_lora(name: str):
    from lora_manager import delete_adapter
    if not delete_adapter(name):
        raise HTTPException(404, f"LoRA '{name}' not found")
    return {"status": "deleted", "name": name}


@app.post("/v1/loras/upload_dataset")
def upload_lora_dataset(req: dict):
    """Accept a LoRA training dataset (.txt content) and persist it to disk.

    Uses a JSON body (matching the workspace file upload) so no extra multipart
    dependency is required. Returns the absolute path the /v1/loras/train
    endpoint expects in its `dataset` field.
    """
    import os
    import re
    from datetime import datetime

    name = (req.get("name") or "").strip()
    content = req.get("content") or ""
    if not name:
        raise HTTPException(400, "name required")
    if not content.strip():
        raise HTTPException(400, "content required")
    if len(content) > 5_000_000:
        raise HTTPException(400, "dataset too large (max 5 MB)")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "dataset"
    if not safe.lower().endswith(".txt"):
        safe += ".txt"
    dset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lora_datasets")
    os.makedirs(dset_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(dset_dir, f"{stamp}_{safe}")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        raise HTTPException(500, f"Failed to save dataset: {e}")
    return {"status": "uploaded", "path": path, "name": safe}


@app.get("/v1/loras/datasets")
def list_lora_datasets():
    """List available LoRA training datasets under lora_datasets/."""
    import os

    dset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lora_datasets")
    items = []
    if os.path.isdir(dset_dir):
        for fn in sorted(os.listdir(dset_dir)):
            if fn.endswith(".txt"):
                full = os.path.join(dset_dir, fn)
                try:
                    size = os.path.getsize(full)
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        lines = sum(1 for _ in f)
                except OSError:
                    size = 0
                    lines = 0
                items.append({"name": fn, "path": full, "size": size, "lines": lines})
    return {"datasets": items}


@app.post("/v1/loras/train")
def train_lora_endpoint(req: dict):
    base_model = req.get("base_model", "")
    dataset = req.get("dataset", "")
    output_name = req.get("output_name", "")
    epochs = int(req.get("epochs", 3))
    if not base_model or not dataset or not output_name:
        raise HTTPException(400, "base_model, dataset, and output_name required")
    if epochs < 1:
        raise HTTPException(400, "epochs must be >= 1")
    if epochs > 10:
        raise HTTPException(400, "epochs must be <= 10 (protects CPU/GPU from overload)")
    try:
        import psutil
        if psutil.virtual_memory().available < 4 * 1024 ** 3:
            raise HTTPException(503, "Not enough free RAM (< 4 GB) for LoRA training right now")
    except ImportError:
        pass
    from lora_manager import train_lora
    out = train_lora(base_model, dataset, output_name, epochs=epochs)
    if out is None:
        missing = []
        for mod in ("peft", "datasets", "torch", "transformers"):
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)
        if missing:
            raise HTTPException(
                500,
                f"Training unavailable: install missing packages: {', '.join(missing)} "
                f"(pip install {(' '.join(missing))})",
            )
        raise HTTPException(500, "Training failed (check that the dataset path exists)")
    return {"status": "trained", "path": out}


# ---------- Image Generation API ----------

@app.get("/v1/images/config")
def image_gen_config():
    import image_gen
    return image_gen.image_gen_config()


class ImageGenRequest(BaseModel):
    prompt: str
    width: int = 0
    height: int = 0
    steps: int = 0


@app.post("/v1/images/generate")
def generate_image(req: ImageGenRequest):
    import image_gen
    try:
        return image_gen.generate_image(req.prompt, width=req.width,
                                        height=req.height, steps=req.steps)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------- Vision API ----------

@app.get("/v1/vision/config")
def vision_config():
    import vision
    return vision.vision_config()


class VisionRequest(BaseModel):
    image: str
    prompt: str = "Describe this image in detail."


@app.post("/v1/vision/analyze")
def analyze_image(req: VisionRequest):
    import vision
    try:
        return vision.analyze_image_base64(req.image, prompt=req.prompt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------- Data Science (AutoML) API ----------

_ds_agent = None


def get_ds_agent():
    global _ds_agent
    if _ds_agent is None:
        import data_science_agent  # noqa: PLC0415
        _ds_agent = data_science_agent.DataScienceAgent()
    return _ds_agent


class DataScienceRequest(BaseModel):
    csv_text: str
    target_column: str
    task_type: str = "classification"
    time_limit: int = 60


@app.get("/v1/datascience/config")
def datascience_config():
    import data_science_agent  # noqa: PLC0415
    return data_science_agent.automl_config()


@app.post("/v1/datascience/train")
def train_automl(req: DataScienceRequest):
    result = get_ds_agent().run_automl(
        csv_text=req.csv_text,
        target_column=req.target_column,
        task_type=req.task_type,
        time_limit=req.time_limit,
    )
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


class HealingRequest(BaseModel):
    code: str
    context: str = ""
    timeout_s: Optional[int] = None


@app.get("/v1/healing/config")
def healing_config():
    """Returns current self-healing agent configuration."""
    import healing_agent  # noqa: PLC0415
    return healing_agent.healing_config()


@app.post("/v1/healing/run")
def run_healing(req: HealingRequest):
    """Execute a Python snippet; if it fails, diagnose and auto-fix."""
    from healing_agent import HealerAgent, healing_enabled  # noqa: PLC0415
    if not healing_enabled():
        raise HTTPException(
            503,
            "Self-healing agent is disabled. Enable it with --healing or "
            "POST /v1/config key 'healing.enabled' = true.",
        )
    healer = HealerAgent(model_manager, memory_manager)
    return healer.heal(req.code, req.context, req.timeout_s)


# ---------- Web UI (handled by web_ui.py) ----------

if __name__ == "__main__":
    import importlib.util
    import uvicorn
    has_httptools = importlib.util.find_spec("httptools") is not None
    if has_httptools:
        uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, log_level="info", http="httptools")
    else:
        uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, log_level="info")
