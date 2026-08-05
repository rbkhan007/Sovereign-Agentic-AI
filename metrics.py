import threading
import time


class MetricsCollector:
    def __init__(self, window_secs: float = 60.0):
        self._lock = threading.Lock()
        self.started = time.time()
        self.requests = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.models: dict = {}
        self.tasks: dict = {}
        self._window_secs = window_secs
        self._tok_window: list = []

    def _model(self, name: str) -> dict:
        if name not in self.models:
            self.models[name] = {
                "requests": 0, "tokens_in": 0, "tokens_out": 0,
                "latency_sum": 0.0, "latency_n": 0, "errors": 0, "loads": 0, "last_used": 0.0,
            }
        return self.models[name]

    def _task(self, name: str) -> dict:
        if name not in self.tasks:
            self.tasks[name] = {"requests": 0, "errors": 0, "tokens_out": 0}
        return self.tasks[name]

    def record_load(self, model: str):
        with self._lock:
            self._model(model)["loads"] += 1

    def record_request(self, task: str = "general", model: str = "", tokens_in: int = 0):
        with self._lock:
            self.requests += 1
            self.tokens_in += tokens_in
            self._task(task)["requests"] += 1
            if model:
                m = self._model(model)
                m["requests"] += 1
                m["tokens_in"] += tokens_in
                m["last_used"] = time.time()

    def record_completion(self, task: str = "", model: str = "", tokens_out: int = 0,
                          latency: float = 0.0, ok: bool = True):
        with self._lock:
            self.tokens_out += tokens_out
            if task:
                t = self._task(task)
                t["tokens_out"] += tokens_out
                if not ok:
                    t["errors"] += 1
            if model:
                m = self._model(model)
                m["tokens_out"] += tokens_out
                m["latency_sum"] += latency
                m["latency_n"] += 1
                if not ok:
                    m["errors"] += 1
                m["last_used"] = time.time()
            if tokens_out > 0:
                now = time.time()
                self._tok_window.append((now, tokens_out))
                cutoff = now - self._window_secs
                while self._tok_window and self._tok_window[0][0] < cutoff:
                    self._tok_window.pop(0)

    def snapshot(self) -> dict:
        with self._lock:
            uptime = time.time() - self.started
            now = time.time()
            cutoff = now - self._window_secs
            while self._tok_window and self._tok_window[0][0] < cutoff:
                self._tok_window.pop(0)
            win_tokens = sum(t for _, t in self._tok_window)
            per_model = {}
            for n, d in self.models.items():
                row = dict(d)
                row["avg_latency"] = round(d["latency_sum"] / d["latency_n"], 3) if d["latency_n"] else 0.0
                if d["requests"]:
                    sr = max(0.0, min(1.0, round(1.0 - (d["errors"] / d["requests"]), 3)))
                else:
                    sr = 1.0
                row["success_rate"] = sr
                per_model[n] = row
            per_task = {n: dict(d) for n, d in self.tasks.items()}
            return {
                "uptime_s": round(uptime, 1),
                "requests": self.requests,
                "errors": sum(t["errors"] for t in self.tasks.values()),
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "tokens_per_sec": round(self.tokens_out / uptime, 2) if uptime else 0.0,
                "tokens_per_sec_window": round(win_tokens / self._window_secs, 2) if self._tok_window else 0.0,
                "per_model": per_model,
                "per_task": per_task,
            }


metrics = MetricsCollector()
