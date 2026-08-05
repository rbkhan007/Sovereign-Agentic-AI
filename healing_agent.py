"""Self-Healing Agent for Sovereign-Agentic-AI.

Executes Python snippets in a subprocess sandbox; on failure:
1. Captures traceback + code snippet (crime scene)
2. Diagnoses root cause using Hy-MT2 (Strategist)
3. Suggests a fix via Qwen (Executor)
4. Validates with ast, applies patch, retries

All attempts log to pgvector via your existing database.store_memory(),
feeding your feedback loop. Import-safe: no external deps beyond your
backend, no tenacity, no Linux-only requirements.

Usage:
    from healing_agent import HealerAgent
    healer = HealerAgent(model_manager, memory_manager)
    result = healer.heal('def foo(:\n  pass')
"""

import ast
import json
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
from typing import Any, Dict, Optional, Tuple

from config import CONFIG

logger = logging.getLogger(__name__)

# One healing attempt at a time, mirroring lora_manager / data_science_agent locks
_HEALING_LOCK = threading.Lock()
_DEFAULT_TIMEOUT = 30


class HealerAgent:
    """Diagnose + auto-fix failing Python code using the local model pipeline."""

    def __init__(self, model_manager, memory_manager,
                 diagnostician_model: str = "hy-mt2",
                 fixer_model: str = "qwen2.5-3b"):
        self.mm = model_manager
        self.mem = memory_manager
        self.diagnostician_model = diagnostician_model
        self.fixer_model = fixer_model

    # -- internal LLM helpers (exact signature verified: generate(name, prompt, ...)) --

    def _llm(self, model_name: str, prompt: str,
             max_tokens: int = 2048, temperature: float = 0.2) -> str:
        """One-line passthrough to ModelManager.generate()."""
        return self.mm.generate(model_name, prompt,
                                max_tokens=max_tokens,
                                temperature=temperature)

    def _diagnose(self, code: str, error: str, context: str = "") -> Dict[str, Any]:
        """Ask the Strategist to produce a structured root-cause diagnosis."""
        prompt = f"""You are a debugging expert. A Python snippet failed. Analyze the traceback
and source, then return ONLY a JSON object with these exact keys:
  root_cause (string), fix_type (string: 'syntax'|'import'|'logic'|'csv'|'other'),
  failing_line (string), confidence (int 0-10).

CODE:
---
{code}
---
TRACEBACK:
---
{error}
---
USER CONTEXT:
---
{context}
---
"""
        raw = self._llm(self.diagnostician_model, prompt, max_tokens=512, temperature=0.1)
        try:
            return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        except (json.JSONDecodeError, ValueError):
            return {"root_cause": "Unparseable diagnosis", "fix_type": "other",
                    "failing_line": "?", "confidence": 0}

    def _suggest_fix(self, code: str, diagnosis: Dict[str, Any]) -> str:
        """Ask the Executor to return a corrected version of the snippet."""
        prompt = f"""You are an expert code-fixing agent. Return the full corrected Python source
in a ```python block, nothing else. Fix only what is needed.

ORIGINAL CODE:
---
{code}
---
DIAGNOSIS:
{json.dumps(diagnosis, indent=2)}
"""
        raw = self._llm(self.fixer_model, prompt,
                        max_tokens=max(2048, len(code) * 2), temperature=0.2)
        if "```python" in raw:
            block = raw.split("```python", 1)[1]
            return textwrap.dedent(block.split("```", 1)[0].strip())
        return textwrap.dedent(raw.strip())

    # -- validation + execution --

    @staticmethod
    def _validate_syntax(code: str) -> Tuple[bool, Optional[str]]:
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

    def _exec_subprocess(self, code: str, timeout_s: int) -> Tuple[int, str, str]:
        """Run code in a temp file with timeout. Returns (rc, stdout, stderr)."""
        d = tempfile.mkdtemp(prefix="heal_src_")
        p = os.path.join(d, "snippet.py")
        with open(p, "w") as f:
            f.write(textwrap.dedent(code))
        try:
            proc = subprocess.run([sys.executable, p],
                                  capture_output=True, text=True, timeout=timeout_s, cwd=d)
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"Execution timed out after {timeout_s}s"
        finally:
            try:
                os.unlink(p)
            except OSError:
                pass

    def _log_attempt(self, payload: Dict[str, Any]) -> None:
        """Best-effort: store healing attempt to pgvector via your existing schema."""
        try:
            import database
            pool = database.get_pool()
            if pool:
                database.store_thought(
                    agent="healer",
                    thought=json.dumps(payload)[:1000],
                )
        except Exception:
            pass  # never break healing on a logging error

    # -- public entry point --

    def heal(self, code: str, context: str = "",
             timeout_s: Optional[int] = None,
             max_retries: Optional[int] = None) -> Dict[str, Any]:
        """Execute code; if it fails, diagnose -> fix -> retry.
        Returns: {success, output/error, attempts, final_code, diagnosis?}
        """
        if not _HEALING_LOCK.acquire(timeout=1):
            raise RuntimeError("A healing attempt is already running. Please wait.")

        timeout = timeout_s or int(getattr(CONFIG, "gen_timeout_s", _DEFAULT_TIMEOUT))
        max_r = max_retries if max_retries is not None else 2
        attempts = []
        current = code
        err = ""
        try:
            if not getattr(CONFIG, "healing", {}).get("allow_unsafe"):
                return {
                    "success": False,
                    "error": ("Healing code execution is disabled for safety. "
                              "Restart with --allow-unsafe-healing to permit the "
                              "agent to run caller-supplied Python."),
                }
            rc, out, err = self._exec_subprocess(code, timeout)
            if rc == 0:
                self._log_attempt({"success": True, "final_code": code})
                return {"success": True, "output": out,
                        "attempts": [{"phase": "initial", "success": True}],
                        "final_code": code}
            attempts.append({"phase": "initial", "success": False,
                             "error": err[:1500], "stdout": out})

            for i in range(1, max_r + 1):
                diag = self._diagnose(current, err, context)
                fixed = self._suggest_fix(current, diag)
                ok, syntax_err = self._validate_syntax(fixed)
                if not ok:
                    attempts.append({"phase": f"retry_{i}", "success": False,
                                     "syntax_error": syntax_err})
                    err = syntax_err or ""
                    continue
                rc2, out2, err2 = self._exec_subprocess(fixed, timeout)
                if rc2 == 0:
                    self._log_attempt({"success": True, "final_code": fixed,
                                       "diagnosis": diag})
                    return {"success": True, "output": out2, "attempts": attempts,
                            "final_code": fixed, "diagnosis": diag}
                err2_msg = err2[:1500] if err2 else ""
                attempts.append({"phase": f"retry_{i}", "success": False,
                                 "diagnosis": diag, "stdout": out2,
                                 "error": err2_msg})
                current = fixed
                err = err2

            self._log_attempt({"success": False, "final_code": current,
                               "last_error": err[:1500]})
            return {"success": False, "output": err, "attempts": attempts,
                    "final_code": current}
        finally:
            _HEALING_LOCK.release()


def healing_enabled() -> bool:
    return bool(getattr(CONFIG, "healing", None) and CONFIG.healing.get("enabled"))


def healing_config() -> dict:
    c = getattr(CONFIG, "healing", {}) or {}
    return {
        "enabled": healing_enabled(),
        "max_retries": int(c.get("max_retries", 2)),
        "timeout_s": int(c.get("timeout_s", _DEFAULT_TIMEOUT)),
        "diagnostician": c.get("diagnostician_model", "hy-mt2"),
        "fixer": c.get("fixer_model", "qwen2.5-3b"),
    }
