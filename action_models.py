"""Core dataclasses for the GBNF execution engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionType(str, Enum):
    """Allowed GBNF action tokens."""
    THINK = "think"
    BASH = "bash"
    READ = "read"
    WRITE = "write"
    DONE = "done"


@dataclass
class Action:
    """A single parsed GBNF action."""
    type: ActionType
    content: str = ""
    path: str = ""
    step: int = 0
    elapsed_s: float = 0.0
    success: bool = False
    error: Optional[str] = None


@dataclass
class TraceEvent:
    """Structured event emitted during auto-approved workflow execution."""
    type: str  # "status", "trace", "trace_result", "complete", "error"
    action: Optional[str] = None
    content: Optional[str] = None
    result: Optional[str] = None
    step: Optional[int] = None
    message: Optional[str] = None


@dataclass
class AgentContext:
    """Execution context for an auto-approved agentic run."""
    goal: str
    conv_id: str
    workspace_id: str = "default"
    agent_name: str = "agent_x"
    executor_model: str = ""
    max_steps: int = 25
    step_timeout_s: float = 120.0
    scratchpad: str = ""
    actions: list[Action] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    done: bool = False
    result: str = ""

    def record(self, action: Action) -> None:
        self.actions.append(action)
        self.scratchpad += (
            f"\n[{action.type.value.upper()}] {action.path or action.content}"
        )
        if action.error:
            self.scratchpad += f"\nError: {action.error}"

    def elapsed(self) -> float:
        return round(time.time() - self.start_time, 3)
