"""Local AI Data Scientist via Auto-Sklearn.

`auto-sklearn` is **Linux-only** (it ships SWIG/C-extension `pyrfr` wheels that
are not built for Windows). Importing `autosklearn` at module load time would
therefore crash the app on Windows. This module never imports it at the top
level: `autosklearn`, `pandas`, `joblib` and `scikit-learn` are imported lazily
inside `run_automl()`, so `import data_science_agent` is always safe and the
agent simply reports "not available" on Windows or when the optional deps are
absent.

Resource safety (mirrors the project's other opt-in modules: image_gen/vision):
  * opt-in via CONFIG.automl.enabled (default off);
  * guarded by hardware.detect_hardware() free-RAM check (>= 3 GB);
  * serialized by a training lock (one AutoML job at a time);
  * n_jobs capped (2) and a hard memory_limit so it never pegs all cores / RAM;
  * the trained ensemble is dropped after scoring so it does not stay resident.

Endpoints: GET /v1/datascience/config, POST /v1/datascience/train.
"""

import gc
import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, Optional

from config import BASE_DIR, CONFIG

_TRAINING_LOCK = threading.Lock()

_MIN_FREE_RAM_MB = 3072
_MAX_TIME_LIMIT = 600


def _deps_available() -> bool:
    for mod in ("autosklearn", "pandas", "sklearn", "joblib"):
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
        return 8192


def automl_enabled() -> bool:
    return bool(getattr(CONFIG, "automl", None) and CONFIG.automl.get("enabled"))


def automl_config() -> dict:
    c = getattr(CONFIG, "automl", {}) or {}
    return {
        "enabled": automl_enabled(),
        "model_dir": _model_dir(),
        "time_limit": int(c.get("time_limit", 60)),
        "n_jobs": int(c.get("n_jobs", 2)),
        "memory_limit_mb": int(c.get("memory_limit_mb", 4096)),
        "deps_available": _deps_available(),
        "device": "cpu",
        "platform": _platform_tag(),
    }


def _platform_tag() -> str:
    import sys
    return sys.platform


def _model_dir() -> str:
    c = getattr(CONFIG, "automl", {}) or {}
    d = c.get("model_dir")
    if not d:
        d = os.environ.get("LLM_AUTOML_MODEL_DIR", "")
    if not d:
        d = os.path.join(BASE_DIR, "generated", "automl_models")
    return d


class DataScienceAgent:
    """Opt-in AutoML agent. Train a model from a CSV + target column."""

    def __init__(self):
        self.last_model_path: Optional[str] = None

    def check_hardware_safety(self) -> bool:
        try:
            import hardware  # noqa: PLC0415
            hw = hardware.detect_hardware(force=False)
            ram_free = hw.get("ram_available_mb", _available_ram_mb())
            return bool(ram_free) and ram_free >= _MIN_FREE_RAM_MB
        except Exception:
            return _available_ram_mb() >= _MIN_FREE_RAM_MB

    def run_automl(
        self,
        csv_text: str,
        target_column: str,
        task_type: str = "classification",
        time_limit: int = 60,
    ) -> Dict[str, Any]:
        """Train an Auto-Sklearn model on the provided CSV text."""
        if task_type not in ("classification", "regression"):
            return {"error": "task_type must be 'classification' or 'regression'"}

        time_limit = max(5, min(int(time_limit), _MAX_TIME_LIMIT))

        if not automl_enabled():
            return {"error": ("AutoML is not available on this platform. Enable it with --automl, "
                               "set env LLM_AUTOML=on, or POST /v1/config key 'automl.enabled' = true.")}

        if not _deps_available():
            return {"error": ("auto-sklearn/pandas are not installed. This feature is Linux-only. "
                              "On Linux install: pip install auto-sklearn pandas scikit-learn joblib")}

        if not self.check_hardware_safety():
            return {"error": "Insufficient free RAM (< 3 GB). Please free memory and try again."}

        csv_text = csv_text.strip()
        target_column = (target_column or "").strip()
        if not csv_text:
            return {"error": "csv_text is required"}
        if not target_column:
            return {"error": "target_column is required"}

        cfg = {
            "time_limit": time_limit,
            "n_jobs": int((getattr(CONFIG, "automl", {}) or {}).get("n_jobs", 2)),
            "memory_limit": int((getattr(CONFIG, "automl", {}) or {}).get("memory_limit_mb", 4096)),
        }

        csv_path = None
        automl = None
        start = time.time()
        if not _TRAINING_LOCK.acquire(timeout=1):
            return {"error": "Another AutoML training job is already running. Please wait."}
        try:
            import pandas as pd  # noqa: PLC0415
            import autosklearn  # noqa: PLC0415
            import autosklearn.classification  # noqa: PLC0415
            import autosklearn.regression  # noqa: PLC0415
            import joblib  # noqa: PLC0415

            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as fh:
                fh.write(csv_text)
                csv_path = fh.name

            df = pd.read_csv(csv_path)
            if target_column not in df.columns:
                return {"error": f"target_column '{target_column}' not found in CSV columns: {list(df.columns)}"}
            X = df.drop(columns=[target_column])
            y = df[target_column]

            if task_type == "classification":
                automl = autosklearn.classification.AutoSklearnClassifier(
                    time_left_for_this_task=cfg["time_limit"],
                    per_run_time_limit=min(30, cfg["time_limit"]),
                    n_jobs=cfg["n_jobs"],
                    memory_limit=cfg["memory_limit"],
                )
            else:
                automl = autosklearn.regression.AutoSklearnRegressor(
                    time_left_for_this_task=cfg["time_limit"],
                    per_run_time_limit=min(30, cfg["time_limit"]),
                    n_jobs=cfg["n_jobs"],
                    memory_limit=cfg["memory_limit"],
                )

            automl.fit(X.copy(), y.copy())

            os.makedirs(_model_dir(), exist_ok=True)
            model_path = os.path.join(_model_dir(), f"automl_{int(time.time())}.pkl")
            joblib.dump(automl, model_path)
            self.last_model_path = model_path

            try:
                score = round(float(automl.score(X, y)), 4)
            except Exception:
                score = None
            try:
                models = automl.show_models()
                best = json.dumps(models, default=str, indent=2) if models else ""
            except Exception:
                best = ""
            try:
                leaderboard = automl.leaderboard()
                if leaderboard is not None:
                    leaderboard = leaderboard.to_dict(orient="records")
            except Exception:
                leaderboard = []

            return {
                "status": "success",
                "model_path": model_path,
                "best_model": best,
                "score": score,
                "leaderboard": leaderboard,
                "elapsed_s": round(time.time() - start, 1),
                "platform": _platform_tag(),
            }
        except Exception as e:
            return {"error": str(e)}
        finally:
            _TRAINING_LOCK.release()
            if automl is not None:
                try:
                    del automl
                except Exception:
                    pass
                gc.collect()
            if csv_path and os.path.exists(csv_path):
                try:
                    os.unlink(csv_path)
                except OSError:
                    pass
