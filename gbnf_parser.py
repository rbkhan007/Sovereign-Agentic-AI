"""Strict GBNF parser for [THINK]/[BASH]/[READ]/[WRITE]/[DONE] actions."""

from __future__ import annotations

import re
from typing import List, Optional

from action_models import Action, ActionType

_ACTION_LINE_RE = re.compile(
    r"^\s*\[(THINK|BASH|READ|WRITE|DONE)\]:\s*(.*?)\s*$"
)


class GbnfParseError(Exception):
    """Raised when the model output violates the GBNF contract."""


def parse_actions(text: str) -> List[Action]:
    """Parse all GBNF actions from a model response.

    Returns a list of :class:`Action` in encounter order.  For ``WRITE``
    actions the ``content`` field carries every line after the header up to
    the next action line (or EOF).

    Raises :class:`GbnfParseError` when the text is completely unparseable.
    """
    lines = text.split("\n")
    actions: List[Action] = []
    i = 0
    step = 0

    while i < len(lines):
        line = lines[i]
        m = _ACTION_LINE_RE.match(line)
        if not m:
            i += 1
            continue

        raw_type = m.group(1)
        payload = m.group(2).strip()
        step += 1

        try:
            action_type = ActionType(raw_type.lower())
        except ValueError:
            i += 1
            continue

        if action_type == ActionType.WRITE:
            content_lines: List[str] = []
            i += 1
            while i < len(lines) and not _ACTION_LINE_RE.match(lines[i]):
                content_lines.append(lines[i])
                i += 1
            actions.append(Action(
                type=action_type,
                content="\n".join(content_lines).rstrip("\n"),
                path=payload,
                step=step,
            ))
            continue

        actions.append(Action(
            type=action_type,
            content=payload,
            path=payload if action_type in (ActionType.READ, ActionType.BASH) else "",
            step=step,
        ))
        i += 1

    if not actions:
        raise GbnfParseError(
            "No valid GBNF action found. Expected exactly one of: "
            "[THINK]: .., [BASH]: .., [READ]: .., [WRITE]: .., [DONE]: .."
        )

    return actions


def parse_first_action(text: str) -> Action:
    """Return only the first parsed action, or raise."""
    actions = parse_actions(text)
    return actions[0]
