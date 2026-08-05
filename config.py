import os
import multiprocessing
import logging
import hmac
from dataclasses import dataclass, field
from typing import List, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

CLOUD_PRESETS = {
    "openai": {"base_url": "https://api.openai.com/v1",
               "chat_model": "gpt-4o-mini", "label": "OpenAI"},
    "claude": {"base_url": "https://api.anthropic.com/v1",
               "chat_model": "claude-sonnet-4-20250514",
               "label": "Claude (Anthropic)"},
    "groq": {"base_url": "https://api.groq.com/openai/v1",
             "chat_model": "llama-3.3-70b-versatile", "label": "Groq"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                   "chat_model": "openrouter/auto",
                   "label": "OpenRouter"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com"
               "/v1beta/openai", "chat_model": "gemini-2.0-flash",
               "label": "Gemini"},
}


def optimal_threads():
    cores = multiprocessing.cpu_count()
    return max(1, cores // 2)


@dataclass
class DBConfig:
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = "postgres"
    database: str = "rhasan_indie_agentic_llm"
    enabled: bool = False
    maxconn: int = 4

    @property
    def uri_with_password(self):
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class OpenAIConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-4o-mini"
    enabled: bool = False
    rate_limit_per_min: int = 10
    backoff_max_s: float = 60.0


@dataclass
class ModelConfig:
    path: str
    name: str
    role: str
    n_ctx: int = 4096
    n_threads: int = 0
    n_gpu_layers: int = -1
    temperature: float = 0.2
    top_p: float = 0.95
    max_tokens: int = 2048
    capabilities: List[str] = field(default_factory=list)
    vram_mb: int = 0


@dataclass
class AppConfig:
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8070
    debug: bool = False
    threads: int = 0
    gpu_name: str = ""
    api_token: str = ""
    api_tokens: Tuple[str, ...] = ()
    parallel_enabled: bool = False
    parallel_max: int = 2
    parallel_judge: bool = True
    parallel_load: bool = True
    load_workers: int = 2
    cli_command_whitelist: Tuple[str, ...] = ()
    auto_stream_enabled: bool = True
    auto_stream_thinking: bool = True
    auto_stream_min_tokens: int = 50
    auto_stream_max_tokens: int = 2048
    prune_interval_hours: int = 6
    prune_max_age_days: int = 30
    sandbox: bool = False
    vram_budget_mb: int = 0
    auto_tune: bool = True
    auto_load: bool = True
    harness_epsilon: float = 0.15
    harness_decay: float = 0.95
    cloud_provider: str = ""
    gen_timeout_s: float = 240.0
    lora_enabled: bool = False
    lora_scale: float = 1.0
    lora_dir: str = ""
    web_search_enabled: bool = False
    image_gen: dict = field(default_factory=lambda: {
        "enabled": False,
        "model": "runwayml/stable-diffusion-v1-5",
        "width": 384,
        "height": 384,
        "steps": 18,
    })
    vision: dict = field(default_factory=lambda: {
        "enabled": False,
        "model": "vikhyat/moondream2",
        "max_tokens": 200,
    })
    automl: dict = field(default_factory=lambda: {
        "enabled": False,
        "model_dir": "",
        "time_limit": 60,
        "n_jobs": 2,
        "memory_limit_mb": 4096,
    })
    healing: dict = field(default_factory=lambda: {
        "enabled": False,
        "allow_unsafe": False,
        "max_retries": 2,
        "timeout_s": 30,
        "diagnostician_model": "hy-mt2",
        "fixer_model": "qwen2.5-3b",
    })
    db: DBConfig = field(default_factory=DBConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)

    models: List[ModelConfig] = field(default_factory=lambda: [
        ModelConfig(
            path=os.path.join(MODELS_DIR, "Hy-MT2-1.8B-Q4_K_M.gguf"),
            name="hy-mt2", role="Strategist",
            n_gpu_layers=-1, n_ctx=2048, temperature=0.3,
            capabilities=["plan", "analyze", "general", "code", "math",
                          "summarize", "translate", "creative", "tool"],
        ),
        ModelConfig(
            path=os.path.join(MODELS_DIR, "MiniCPM5-1B-Agentic-v9-f16.gguf"),
            name="minicpm-v9", role="Executor",
            n_gpu_layers=-1, temperature=0.15,
            capabilities=["general", "code", "math", "summarize", "translate"],
        ),
        ModelConfig(
            path=os.path.join(MODELS_DIR, "minicpm5-1b-agentic-tooluse.F16.gguf"),
            name="minicpm-tooluse", role="ToolExecutor",
            n_gpu_layers=-1, temperature=0.1,
            capabilities=["tool", "code"],
        ),
    ])

    def __post_init__(self):
        t = self.threads or optimal_threads()
        self.threads = t
        for m in self.models:
            if m.n_threads == 0:
                m.n_threads = t
        if not self.gpu_name:
            self.gpu_name = os.environ.get("LLM_GPU_NAME", "GPU")
        if os.environ.get("API_TOKEN"):
            self.set_api_token(os.environ["API_TOKEN"])
        _extra_tokens = os.environ.get("LLM_API_TOKENS", "").strip()
        if _extra_tokens:
            extras = [p.strip() for p in _extra_tokens.split(",") if p.strip()]
            merged = list(self.api_tokens)
            for e in extras:
                if e and e != self.api_token and e not in merged:
                    merged.append(e)
            self.api_tokens = tuple(merged)
        if os.environ.get("LLM_PARALLEL", "").strip().lower() in ("0", "false", "off", "no"):
            self.parallel_enabled = False
        if os.environ.get("LLM_PARALLEL_MAX", "").strip().isdigit():
            self.parallel_max = max(1, int(os.environ["LLM_PARALLEL_MAX"]))
        if os.environ.get("LLM_PARALLEL_LOAD", "").strip().lower() in ("0", "false", "off", "no"):
            self.parallel_load = False
        if os.environ.get("LLM_LOAD_WORKERS", "").strip().isdigit():
            self.load_workers = max(1, int(os.environ["LLM_LOAD_WORKERS"]))
        _cmds = os.environ.get("LLM_CLI_COMMANDS", "").strip()
        if _cmds:
            self.cli_command_whitelist = tuple(c.strip().lower() for c in _cmds.split(",") if c.strip())
        if os.environ.get("LLM_AUTO_STREAM", "").strip().lower() in ("0", "false", "off", "no"):
            self.auto_stream_enabled = False
        if os.environ.get("LLM_AUTO_STREAM_THINKING", "").strip().lower() in ("0", "false", "off", "no"):
            self.auto_stream_thinking = False
        if os.environ.get("LLM_AUTO_STREAM_MIN_TOKENS", "").strip().isdigit():
            self.auto_stream_min_tokens = max(10, int(os.environ["LLM_AUTO_STREAM_MIN_TOKENS"]))
        if os.environ.get("LLM_AUTO_STREAM_MAX_TOKENS", "").strip().isdigit():
            self.auto_stream_max_tokens = min(8192, int(os.environ["LLM_AUTO_STREAM_MAX_TOKENS"]))
        if os.environ.get("LLM_PRUNE_HOURS", "").strip().isdigit():
            self.prune_interval_hours = max(1, int(os.environ["LLM_PRUNE_HOURS"]))
        if os.environ.get("LLM_PRUNE_DAYS", "").strip().isdigit():
            self.prune_max_age_days = max(1, int(os.environ["LLM_PRUNE_DAYS"]))
        if os.environ.get("LLM_VRAM_MB", "").strip().isdigit():
            self.vram_budget_mb = max(256, int(os.environ["LLM_VRAM_MB"]))
        if os.environ.get("LLM_AUTO_LOAD", "").strip().lower() in ("0", "false", "off", "no"):
            self.auto_load = False
        raw_timeout = os.environ.get("LLM_GEN_TIMEOUT", "").strip()
        if raw_timeout:
            try:
                val = float(raw_timeout)
                if val > 0:
                    self.gen_timeout_s = max(5.0, val)
            except (ValueError, TypeError):
                pass
        if os.environ.get("LLM_CLOUD", "").strip():
            preset = CLOUD_PRESETS.get(os.environ["LLM_CLOUD"].strip().lower())
            if preset:
                self.openai.base_url = preset["base_url"]
                self.openai.chat_model = preset["chat_model"]
                self.cloud_provider = os.environ["LLM_CLOUD"].strip().lower()
                self.openai.enabled = bool(self.openai.api_key)
        if not self.openai.enabled and not self.openai.api_key:
            for var, provider in (("ANTHROPIC_API_KEY", "claude"), ("OPENROUTER_API_KEY", "openrouter"),
                                  ("GROQ_API_KEY", "groq"), ("GEMINI_API_KEY", "gemini"),
                                  ("OPENAI_API_KEY", "openai")):
                val = os.environ.get(var, "").strip()
                if val:
                    preset = CLOUD_PRESETS[provider]
                    self.openai.api_key = val
                    self.openai.base_url = preset["base_url"]
                    self.openai.chat_model = preset["chat_model"]
                    self.cloud_provider = provider
                    self.openai.enabled = True
                    break
        if os.environ.get("LLM_IMAGE_GEN", "").strip().lower() in ("1", "true", "yes", "on"):
            self.image_gen["enabled"] = True
        if os.environ.get("LLM_IMAGE_GEN_MODEL", "").strip():
            self.image_gen["model"] = os.environ["LLM_IMAGE_GEN_MODEL"].strip()
        if os.environ.get("LLM_VISION", "").strip().lower() in ("1", "true", "yes", "on"):
            self.vision["enabled"] = True
        if os.environ.get("LLM_VISION_MODEL", "").strip():
            self.vision["model"] = os.environ["LLM_VISION_MODEL"].strip()
        if os.environ.get("LLM_AUTOML", "").strip().lower() in ("1", "true", "yes", "on"):
            self.automl["enabled"] = True
        if os.environ.get("LLM_AUTOML_MODEL_DIR", "").strip():
            self.automl["model_dir"] = os.environ["LLM_AUTOML_MODEL_DIR"].strip()
        if os.environ.get("LLM_AUTOML_TIME_LIMIT", "").strip().isdigit():
            self.automl["time_limit"] = int(os.environ["LLM_AUTOML_TIME_LIMIT"].strip())
        if os.environ.get("LLM_HEALING", "").strip().lower() in ("1", "true", "yes", "on"):
            self.healing["enabled"] = True
        if not self.lora_dir:
            self.lora_dir = os.path.join(BASE_DIR, "loras")
        if os.environ.get("PGHOST", "").strip():
            self.db.host = os.environ["PGHOST"].strip()
        if os.environ.get("PGPORT", "").strip().isdigit():
            self.db.port = int(os.environ["PGPORT"])
        if os.environ.get("PGUSER", "").strip():
            self.db.user = os.environ["PGUSER"].strip()
        if os.environ.get("PGPASSWORD", "").strip():
            self.db.password = os.environ["PGPASSWORD"].strip()
        if os.environ.get("PGDATABASE", "").strip():
            self.db.database = os.environ["PGDATABASE"].strip()
        if os.environ.get("LLM_DB", "").strip().lower() in ("1", "true", "yes", "on", "auto"):
            self.db.enabled = True

    def sync_threads(self):
        """Propagate CONFIG.threads to every model's n_threads."""
        for m in self.models:
            m.n_threads = self.threads

    def set_api_token(self, value: str):
        """Set the primary API token, staging any comma-separated extras as rotation tokens."""
        parts = [p.strip() for p in value.split(",") if p.strip()]
        self.api_token = parts[0] if parts else ""
        self.api_tokens = tuple(parts[1:])

    def valid_api_tokens(self) -> frozenset:
        """All tokens currently accepted for API auth (primary + rotation set)."""
        toks = set(self.api_tokens)
        if self.api_token:
            toks.add(self.api_token)
        return frozenset(toks)

    def token_authorized(self, presented: str) -> bool:
        """Constant-time check that `presented` matches any configured API token."""
        if not presented:
            return False
        if self.api_token and hmac.compare_digest(presented, self.api_token):
            return True
        return any(hmac.compare_digest(presented, t) for t in self.api_tokens)

    def _discovered_models(self) -> List[ModelConfig]:
        """Register any .gguf dropped into models/ that is not already configured."""
        known_names = {m.name for m in self.models}
        known_paths = {os.path.normcase(os.path.abspath(m.path)) for m in self.models}
        result = []
        if os.path.isdir(MODELS_DIR):
            for fn in sorted(os.listdir(MODELS_DIR)):
                if not fn.lower().endswith(".gguf"):
                    continue
                path = os.path.join(MODELS_DIR, fn)
                if os.path.normcase(os.path.abspath(path)) in known_paths:
                    continue
                base = os.path.splitext(fn)[0]
                name = base.lower().replace(" ", "-").replace("_", "-")
                if name in known_names:
                    continue
                known_names.add(name)
                result.append(ModelConfig(
                    path=path,
                    name=name, role="Executor",
                    n_threads=self.threads, n_gpu_layers=-1, n_ctx=4096,
                    capabilities=["general"],
                ))
        return result

    @property
    def available_models(self):
        if not hasattr(self, '_cached_available_models'):
            self._cached_available_models = self._compute_available_models()
            self._cached_models_mtime = self._models_dir_mtime()
        current_mtime = self._models_dir_mtime()
        if current_mtime != self._cached_models_mtime:
            self._cached_available_models = self._compute_available_models()
            self._cached_models_mtime = current_mtime
        return self._cached_available_models

    def _compute_available_models(self) -> List[ModelConfig]:
        return [m for m in self.models if os.path.exists(m.path)] + self._discovered_models()

    def _models_dir_mtime(self) -> float:
        if os.path.isdir(MODELS_DIR):
            try:
                return os.path.getmtime(MODELS_DIR)
            except OSError:
                pass
        return 0.0


CONFIG = AppConfig()


def detect_gpu():
    import io
    import contextlib
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import llama_cpp
            result = llama_cpp.llama_supports_gpu_offload()
    except Exception:
        result = False
    return result


HAS_GPU = detect_gpu()
if not HAS_GPU:
    for m in CONFIG.models:
        m.n_gpu_layers = 0
