import functools
import logging
import random  # nosec B311
import threading
from collections import defaultdict
from typing import List, Optional, Dict, Any

from config import CONFIG

logger = logging.getLogger(__name__)

EXECUTOR_ROLES = {"Executor", "ToolExecutor", "Strategist"}

TASK_KEYWORDS = {
    "code": ["code", "python", "javascript", "typescript", "function", "def ", "class",
             "refactor", "debug", "script", "regex", "sql", "html", "css", "json",
             "exception", "compile", "syntax", "variable", "import", "algorithm", "implement",
             "write a function", "program", "loop", "array", "string manipulation",
             "data structure"],
    "math": ["math", "calculate", "equation", "solve", "algebra", "geometry", "add", "subtract",
             "multiply", "divide", "percentage", "2+2", "integral", "derivative", "sum of",
             "probability", "statistics", "average", "median", "formula", "compute"],
    "summarize": ["summarize", "summary", "tl;dr", "condense", "abstract", "brief",
                  "tldr", "key points", "main idea"],
    "translate": ["translate", "translation", "in french", "in spanish", "in german",
                  "in english", "in japanese", "meaning of", "interpret", "in chinese",
                  "in arabic", "in hindi", "in korean", "in portuguese"],
    "tool": ["tool", "jsonrpc", "mcp", "terminal", "shell", "command", "extract", "convert",
             "format", "parse", "transform"],
    "creative": ["write a poem", "poem", "story", "essay", "joke", "creative", "compose",
                 "lyrics", "song", "write a story", "fiction", "narrative", "dialogue"],
}


@functools.lru_cache(maxsize=2048)
def classify_task(text: str) -> str:
    t = text.lower()
    for task, kws in TASK_KEYWORDS.items():
        if any(k in t for k in kws):
            return task
    return "general"


class Harness:
    """Adaptive / 'genetic' per-task model scorer.

    Learns a fitness score per (task, model) from measured success, latency and
    token output. Selection is epsilon-greedy so the best model is normally
    chosen but occasional exploration keeps the ranking fresh.
    """

    def __init__(self, epsilon: Optional[float] = None, decay: Optional[float] = None,
                 random_state: Optional[int] = None):
        self.epsilon = epsilon if epsilon is not None else CONFIG.harness_epsilon
        self.decay = decay if decay is not None else CONFIG.harness_decay
        self._rng = random.Random(random_state) if random_state is not None else random  # nosec B311
        self._lock = threading.Lock()
        self.generation = 0
        self._data: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {
            "attempts": 0, "errors": 0, "latency_sum": 0.0, "latency_n": 0,
            "tokens": 0, "last_gen": 0,
        })

    def record(self, task: str, model: str, ok: bool, latency: float = 0.0, tokens: int = 0):
        with self._lock:
            self.generation += 1
            d = self._data[(task, model)]
            d["attempts"] += 1
            d["tokens"] += tokens
            d["last_gen"] = self.generation
            d.pop("override", None)  # real measurements supersede a manual override
            if ok:
                d["latency_sum"] += latency
                d["latency_n"] += 1
            else:
                d["errors"] += 1

    def score(self, task: str, model: str) -> float:
        d = self._data.get((task, model))
        if not d or d["attempts"] == 0:
            return 0.0
        override = d.get("override")
        if override is not None:
            return float(override)
        success = 1.0 - (d["errors"] / d["attempts"])
        avg_latency = d["latency_sum"] / d["latency_n"] if d["latency_n"] else 0.0
        speed = 1.0 if avg_latency <= 0 else min(2.0, 1.0 / max(avg_latency, 1e-6))
        age = max(0, self.generation - d.get("last_gen", 0))
        recent = self.decay ** age
        return success * 60.0 + speed * 30.0 + recent * 10.0

    def has_recorded(self, task: str, candidates: List[str]) -> bool:
        """True if any candidate has at least one real measurement for the task."""
        with self._lock:
            return any(self._data.get((task, c), {}).get("attempts", 0) > 0
                       for c in candidates)

    def choose(self, task: str, candidates: List[str], default: Optional[str] = None) -> Optional[str]:
        if not candidates:
            return default
        if len(candidates) == 1:
            return candidates[0]
        with self._lock:
            explore = self._rng.random() < self.epsilon
            if explore:
                return self._rng.choice(candidates)
        return self.ranked(task, candidates)[0]

    def ranked(self, task: str, candidates: List[str]) -> List[str]:
        if not candidates:
            return []
        return sorted(candidates, key=lambda c: self.score(task, c), reverse=True)

    def stats(self) -> dict:
        with self._lock:
            data = {}
            for (t, m), d in self._data.items():
                data[f"{t}/{m}"] = {
                    "attempts": d["attempts"],
                    "errors": d["errors"],
                    "avg_latency": round(d["latency_sum"] / d["latency_n"], 3) if d["latency_n"] else 0.0,
                    "tokens": d["tokens"],
                    "recent": round(self.decay ** max(0, self.generation - d.get("last_gen", 0)), 3),
                    "score": round(self.score(t, m), 2),
                }
            return {"generation": self.generation, "epsilon": self.epsilon, "data": data}

    def reset(self):
        """Reset all harness data and generation counter."""
        with self._lock:
            self._data.clear()
            self.generation = 0

    def adjust(self, task: str, model: str, score_override: float):
        """Manually override the fitness score for a (task, model) pair.

        Stores an explicit override that `score()` returns verbatim until a real
        measurement arrives via `record()` (or the harness is reset).
        """
        with self._lock:
            d = self._data[(task, model)]
            d["attempts"] = max(d["attempts"], 1)
            d["override"] = max(0.0, min(100.0, score_override))
            d["last_gen"] = self.generation

    def export_stats(self) -> dict:
        """Export harness state for persistence."""
        with self._lock:
            data = {}
            for (t, m), d in self._data.items():
                data[f"{t}||{m}"] = {
                    "attempts": d["attempts"],
                    "errors": d["errors"],
                    "latency_sum": d["latency_sum"],
                    "latency_n": d["latency_n"],
                    "tokens": d["tokens"],
                    "last_gen": d["last_gen"],
                    "override": d.get("override"),
                }
            return {"generation": self.generation, "epsilon": self.epsilon, "data": data}

    def import_stats(self, state: dict):
        """Import harness state from export_stats()."""
        with self._lock:
            self.generation = state.get("generation", 0)
            if "epsilon" in state:
                self.epsilon = state["epsilon"]
            self._data.clear()
            for key, d in state.get("data", {}).items():
                parts = key.split("||", 1)
                if len(parts) == 2:
                    task, model = parts
                    self._data[(task, model)] = {
                        "attempts": d.get("attempts", 0),
                        "errors": d.get("errors", 0),
                        "latency_sum": d.get("latency_sum", 0.0),
                        "latency_n": d.get("latency_n", 0),
                        "tokens": d.get("tokens", 0),
                        "last_gen": d.get("last_gen", 0),
                        "override": d.get("override"),
                    }


class ModelRouter:
    """Selection room: picks the best available models for the upcoming task."""

    def __init__(self, model_manager, harness: Optional[Harness] = None):
        self.models = model_manager
        self.harness = harness or Harness()
        self._caps_cache: Dict[str, set] = {}

    def _capabilities(self, name: str) -> set:
        cached = self._caps_cache.get(name)
        if cached is not None:
            return cached
        mc = self.models.configs.get(name)
        if mc is None:
            self._caps_cache[name] = set()
            return set()
        caps = getattr(mc, "capabilities", None)
        if caps:
            result = set(caps)
        else:
            role = getattr(mc, "role", "") or ""
            if "Strategist" in role:
                result = {"plan", "analyze"}
            elif "ToolExecutor" in role:
                result = {"tool", "code"}
            elif "Executor" in role:
                result = {"general", "code"}
            else:
                result = {"general"}
        self._caps_cache[name] = result
        return result

    def executor_names(self) -> List[str]:
        names = [n for n, mc in self.models.configs.items()
                 if getattr(mc, "role", "") in EXECUTOR_ROLES]
        if not names:
            names = list(self.models.configs.keys())
        return names

    def rank_for_task(self, task: str, limit: int = 0) -> List[str]:
        cands = self.executor_names()
        primary = [n for n in cands if task in self._capabilities(n)]
        backup = [n for n in cands if n not in primary]
        if primary:
            # epsilon-greedy: once real measurements exist, occasionally explore
            # a non-top capable model so the harness keeps learning (choose()
            # falls back to ranked when not exploring or before any data lands)
            if self.harness.has_recorded(task, primary):
                picked = self.harness.choose(task, primary)
            else:
                picked = None
            ordered = ([picked] + [n for n in primary if n != picked] if picked else primary)
        else:
            ordered = []
        ordered = ordered + self.harness.ranked(task, backup)
        instances = getattr(self.models, "instances", {}) or {}
        loaded_first = []
        loaded_last = []
        for n in ordered:
            if n in instances:
                loaded_first.append(n)
            else:
                loaded_last.append(n)
        ranked = loaded_first + loaded_last
        if limit:
            return ranked[:limit]
        return ranked

    def select_executors(self, text: str, max_models: int, model_override: Optional[str] = None):
        task = classify_task(text)
        if model_override and model_override in self.models.configs:
            rest = [n for n in self.executor_names() if n != model_override]
            ranked = [model_override] + self.harness.ranked(task, rest)
            return task, ranked[:max(1, max_models)]
        ranked = self.rank_for_task(task, max_models)
        return task, ranked

    def primary(self, task: str = "general", model_override: Optional[str] = None) -> str:
        if model_override and model_override in self.models.configs:
            return model_override
        ranked = self.rank_for_task(task)
        return ranked[0] if ranked else ""
