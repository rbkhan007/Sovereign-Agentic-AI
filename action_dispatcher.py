"""Secure dispatcher for parsed GBNF actions."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Optional

from action_models import Action, ActionType, AgentContext

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_MAX_OUTPUT = 8000
_STEP_TIMEOUT = 120


_DANGEROUS_CMDS = {
    "rm -rf /", "rm -rf /*", "mkfs", "format c:", "format /q c:",
    ":(){ :|:& };:", "dd if=", "> /dev/sd", "chmod -R 777 /",
    "shutdown", "reboot", "halt", "init 0", "init 6", "rd /s", "rmdir /s",
    "sudo ", "sudo rm", "sudo mkfs", "sudo dd",
}

_DANGEROUS_TOKENS = {
    "shutdown", "reboot", "halt", "mkfs", "diskpart", "format",
    "dd", "del", "erase", "rd", "rmdir", "deltree", "rm", "remove", "unlink",
    "sudo",
}


def _is_dangerous(cmd: str) -> bool:
    if not cmd or not cmd.strip():
        return True
    low = " ".join(cmd.lower().split())
    if any(d in low for d in _DANGEROUS_CMDS):
        return True
    tokens = low.replace("(", " ").replace(")", " ").split()
    if not tokens:
        return False
    for tok in tokens:
        base = tok.strip("\"'`/\\").lstrip("-").split(".")[0]
        if base in _DANGEROUS_TOKENS and tok not in ("echo",):
            return True
    if any(op in low for op in ("> /dev/sd", ">\\\\.\\", "format /q")):
        return True
    if low.startswith(("python ", "python3 ", "cmd /c", "cmd.exe", "powershell")):
        if any(k in low for k in ("rmtree", "shutil.rmtree", "removefile",
                                   "os.remove", "os.unlink", "subprocess.call",
                                   "eval(", "exec(", "os.system")):
            return True
    return False


def _sandbox_scoped(path: str, root: str = _BASE_DIR) -> tuple[bool, str]:
    ap = os.path.realpath(os.path.expanduser(path))
    root_real = os.path.realpath(root)
    if ap == root_real or ap.startswith(root_real + os.sep):
        return True, ap
    return False, ap


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... ({len(text) - limit} chars omitted) ...\n" + text[-half:]


def dispatch(action: Action, ctx: AgentContext) -> Action:
    """Execute *action* and update it in-place inside *ctx*."""
    t0 = time.time()
    try:
        if action.type == ActionType.THINK:
            action.success = True
            action.elapsed_s = round(time.time() - t0, 3)
            ctx.record(action)
            return action

        if action.type == ActionType.BASH:
            result = _exec_bash(action.content, ctx)
        elif action.type == ActionType.READ:
            result = _exec_read(action.path or action.content, ctx)
        elif action.type == ActionType.WRITE:
            result = _exec_write(action.path or action.content, action.content, ctx)
        elif action.type == ActionType.DONE:
            result = Action(type=ActionType.DONE, content=action.content, success=True)
            ctx.done = True
            ctx.result = action.content
        else:
            result = Action(type=action.type, content="unknown action", success=False, error="invalid type")

        action.success = result.success
        action.error = result.error
        action.elapsed_s = round(time.time() - t0, 3)
        ctx.record(action)
        return action

    except Exception as e:
        action.success = False
        action.error = str(e)
        action.elapsed_s = round(time.time() - t0, 3)
        ctx.record(action)
        return action


def _exec_bash(cmd: str, ctx: AgentContext) -> Action:
    if _is_dangerous(cmd):
        return Action(type=ActionType.BASH, content=cmd, success=False, error="BLOCKED: dangerous command")
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,  # nosec B602
            timeout=_STEP_TIMEOUT, cwd=_BASE_DIR,
        )
        out = proc.stdout or ""
        if proc.returncode != 0:
            err = proc.stderr or ""
            if err:
                out += ("\n" if out else "") + err
        out = out.strip()
        if not out:
            out = f"[exit code {proc.returncode}]"
        err_msg = out if proc.returncode != 0 else None
        return Action(type=ActionType.BASH, content=cmd,
                      success=proc.returncode == 0, error=err_msg)
    except subprocess.TimeoutExpired:
        return Action(type=ActionType.BASH, content=cmd, success=False, error=f"Timed out after {_STEP_TIMEOUT}s")
    except Exception as e:
        return Action(type=ActionType.BASH, content=cmd, success=False, error=f"Shell error: {e}")


def _exec_read(path: str, ctx: AgentContext) -> Action:
    allowed, ap = _sandbox_scoped(path)
    if not allowed:
        err = f"Sandbox: read outside project blocked: {path}"
        return Action(type=ActionType.READ, content=path, success=False, error=err)
    try:
        if not os.path.isfile(ap):
            return Action(type=ActionType.READ, content=path, success=False, error=f"File not found: {path}")
        size = os.path.getsize(ap)
        if size > 2_000_000:
            err = f"File too large ({size} bytes). Use shell."
            return Action(type=ActionType.READ, content=path, success=False, error=err)
        with open(ap, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        numbered = [f"{i + 1:4d} | {l.rstrip()}" for i, l in enumerate(lines)]
        header = f"File: {ap} ({len(lines)} lines, {size} bytes)"
        out = header + "\n" + "\n".join(numbered)
        return Action(type=ActionType.READ, content=path, success=True, error=_truncate(out))
    except Exception as e:
        return Action(type=ActionType.READ, content=path, success=False, error=f"Read error: {e}")


def _exec_write(path: str, content: str, ctx: AgentContext) -> Action:
    allowed, ap = _sandbox_scoped(path)
    if not allowed:
        err = f"Sandbox: write outside project blocked: {path}"
        return Action(type=ActionType.WRITE, content=path, success=False, error=err)
    try:
        parent = os.path.dirname(ap)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(ap, "w", encoding="utf-8") as f:
            f.write(content or "")
        msg = f"Wrote {ap} ({len(content or '')} bytes)"
        return Action(type=ActionType.WRITE, content=path, success=True, error=msg)
    except Exception as e:
        return Action(type=ActionType.WRITE, content=path, success=False, error=f"Write error: {e}")
