"""Agent profiles and skills registry for the local multi-agent LLM.

Agents are named personas with their own system prompt. Skills are reusable,
parameterized capabilities that wrap a user message into a focused prompt
(e.g. summarize, translate, code-review). Both are used by the CLI (/agent,
/skill), the HTTP API (/v1/agents, /v1/skills) and MCP tools.

User-defined agents and skills can be added at runtime via add_agent() /
add_skill(); they are persisted as JSON under the agents/ and skills/
directories so they survive restarts. MCP tools are built from these registries,
so newly added entries automatically appear as MCP tools.
"""

import json
import os
import re
import threading
from typing import Dict, List, Optional

_AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
_LOCK = threading.RLock()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-") or "item"


def _safe_filename(name: str) -> str:
    return _slug(name) + ".json"

AGENTS: Dict[str, dict] = {
    "general": {
        "name": "general",
        "role": "General Assistant",
        "description": "Default assistant: helpful, concise, well-rounded.",
        "system_prompt": (
            "You are a helpful, concise assistant. Answer directly, use code "
            "blocks for code, and ask a clarifying question only when the "
            "request is genuinely ambiguous."
        ),
        "keywords": ["general", "assistant", "help"],
    },
    "coder": {
        "name": "coder",
        "role": "Coding Agent",
        "description": "Expert software engineer: clean, idiomatic, working code.",
        "system_prompt": (
            "You are an expert software engineering assistant. Write clean, "
            "correct, idiomatic code. When asked to write or modify code, output "
            "the full file content in a fenced code block. Explain trade-offs "
            "briefly. Prefer concise answers and never invent APIs. If a task is "
            "ambiguous, ask one clarifying question before writing code."
        ),
        "keywords": ["code", "function", "bug", "debug", "script", "python", "refactor"],
    },
    "debugger": {
        "name": "debugger",
        "role": "Debugging Agent",
        "description": "Finds root causes, explains errors, suggests fixes.",
        "system_prompt": (
            "You are a meticulous debugging assistant. First restate the "
            "problem in one line, then list likely root causes from most to "
            "least probable, then propose the most likely fix with a code "
            "example. If more information is needed, list exactly what to "
            "gather. Be concrete and avoid generic advice."
        ),
        "keywords": ["bug", "error", "exception", "traceback", "crash", "fix", "debug"],
    },
    "writer": {
        "name": "writer",
        "role": "Writing Agent",
        "description": "Engaging writer for essays, stories, emails, marketing.",
        "system_prompt": (
            "You are a skilled writer. Match the requested tone and length. "
            "Write vivid, well-structured prose with a clear beginning, middle "
            "and end. Prefer concrete details over abstractions. Never pad."
        ),
        "keywords": ["essay", "email", "story", "letter", "article", "poem", "write"],
    },
    "translator": {
        "name": "translator",
        "role": "Translation Agent",
        "description": "Accurate translator that preserves tone and meaning.",
        "system_prompt": (
            "You are a professional translator. Translate faithfully, preserving "
            "meaning, tone and formatting. For idioms, choose the natural "
            "equivalent rather than a literal rendering. Return only the "
            "translated text unless asked to explain choices."
        ),
        "keywords": [
            "translate", "translation", "in french", "in spanish",
            "in german", "in english",
        ],
    },
    "summarizer": {
        "name": "summarizer",
        "role": "Summarizer Agent",
        "description": "Condenses long text into key points.",
        "system_prompt": (
            "You are a summarization specialist. Produce a concise summary that "
            "captures the essential points, then, if useful, a short bulleted "
            "list of key takeaways. Preserve any numbers, names and dates "
            "exactly. Do not add information that is not in the source."
        ),
        "keywords": ["summarize", "summary", "tl;dr", "condense", "key points"],
    },
    "researcher": {
        "name": "researcher",
        "role": "Research Agent",
        "description": "Structured analysis with evidence and trade-offs.",
        "system_prompt": (
            "You are a careful research assistant. Structure answers with "
            "sections and cite specific evidence when reasoning. Distinguish "
            "what is known, what is uncertain, and what would require more "
            "information. End with a short recommendation or next steps."
        ),
        "keywords": ["research", "compare", "analysis", "explain", "why", "what is"],
    },
    "teacher": {
        "name": "teacher",
        "role": "Teaching Agent",
        "description": "Explains concepts simply, step by step.",
        "system_prompt": (
            "You are a patient teacher. Explain step by step, starting from the "
            "simplest idea. Use analogies and short examples. Check for "
            "understanding and offer to go deeper on any part."
        ),
        "keywords": ["explain", "teach", "learn", "concept", "how does", "tutorial"],
    },
    "data_scientist": {
        "name": "data_scientist",
        "role": "Data Scientist",
        "description": "Automated ML specialist. Trains an Auto-Sklearn model on your CSV data.",
        "system_prompt": (
            "You are an automated data science assistant. Help users prepare CSV data, "
            "identify target columns, and run AutoML to find the best model. After training, "
            "summarize the accuracy score and the saved model file path."
        ),
        "keywords": ["csv", "data", "predict", "model", "automl", "analyze", "train"],
    },
}

DEFAULT_AGENT = "general"

# Skills: name -> {description, template, params}
# The template is filled with the user's input text (and optional params),
# then sent to the executor with a skill-specific system prompt.
SKILLS: Dict[str, dict] = {
    "summarize": {
        "name": "summarize",
        "description": "Condense the given text into key points.",
        "system_prompt": (
            "You are a summarization specialist. Return a concise summary and key takeaways."
        ),
        "template": (
            "Summarize the following text concisely, preserving important details:\n\n{input}"
        ),
        "params": [],
    },
    "translate": {
        "name": "translate",
        "description": "Translate text to a target language.",
        "system_prompt": "You are a professional translator. Output only the translated text.",
        "template": "Translate the following text to {language}:\n\n{input}",
        "params": [{"name": "language", "default": "English"}],
    },
    "code-review": {
        "name": "code-review",
        "description": "Review code for bugs, style and improvements.",
        "system_prompt": "You are a senior code reviewer. Be specific and constructive.",
        "template": (
            "Review the following code for correctness, style and potential improvements:\n\n"
            "{input}"
        ),
        "params": [],
    },
    "explain": {
        "name": "explain",
        "description": "Explain a concept step by step.",
        "system_prompt": "You are a patient teacher who explains step by step with examples.",
        "template": (
            "Explain the following concept step by step, starting from the basics:\n\n{input}"
        ),
        "params": [],
    },
    "rewrite": {
        "name": "rewrite",
        "description": "Rewrite text in a clearer, better style.",
        "system_prompt": (
            "You are a skilled editor. Improve clarity, flow and tone while keeping meaning."
        ),
        "template": (
            "Rewrite the following text to be clearer and more effective:\n\n{input}"
        ),
        "params": [],
    },
    "extract": {
        "name": "extract",
        "description": "Extract structured facts, names or keywords from text.",
        "system_prompt": "You are a data-extraction assistant. Return concise structured output.",
        "template": (
            "Extract the key facts, names, dates and numbers from the following text:\n\n{input}"
        ),
        "params": [],
    },
    "brainstorm": {
        "name": "brainstorm",
        "description": "Generate ideas and options around a topic.",
        "system_prompt": (
            "You are a creative brainstorming partner. Produce varied, useful options."
        ),
        "template": (
            "Brainstorm ideas around the following topic, giving several distinct options:\n\n"
            "{input}"
        ),
        "params": [],
    },
    "plan": {
        "name": "plan",
        "description": "Break a goal into concrete, ordered steps.",
        "system_prompt": "You are a project planner. Produce a clear, ordered action plan.",
        "template": "Create a step-by-step plan to accomplish the following goal:\n\n{input}",
        "params": [],
    },
}


def list_agents() -> List[str]:
    return sorted(AGENTS.keys())


def get_agent(name: str) -> Optional[dict]:
    if not name:
        return dict(AGENTS.get(DEFAULT_AGENT, {}))
    return AGENTS.get(name.strip().lower())


def agent_system_prompt(name: str) -> str:
    a = get_agent(name)
    return a["system_prompt"] if a else AGENTS[DEFAULT_AGENT]["system_prompt"]


def list_skills() -> List[str]:
    return sorted(SKILLS.keys())


def get_skill(name: str) -> Optional[dict]:
    return SKILLS.get(name.strip().lower())


def render_skill(name: str, input_text: str, params: Optional[dict] = None) -> Optional[dict]:
    """Render a skill into a {system_prompt, prompt} pair, or None if unknown.

    Fills the skill template with the input text and any supplied parameters
    (unknown params fall back to their defaults and are then left unfilled).
    """
    skill = get_skill(name)
    if not skill:
        return None
    fill = {}
    for p in skill.get("params", []):
        fill[p["name"]] = (params or {}).get(p["name"], p.get("default", ""))
    try:
        prompt = skill["template"].format(input=input_text, **fill)
    except (KeyError, ValueError):
        prompt = skill["template"].replace("{input}", input_text)
    return {
        "name": skill["name"],
        "system_prompt": skill["system_prompt"],
        "prompt": prompt,
    }


# ---------- user-defined agents & skills (runtime registration + JSON persistence) ----------

def _load_custom(dirname: str, registry: Dict[str, dict], builtin: Optional[set] = None):
    """Load user-defined entries from JSON files into the given registry.

    Entries whose name collides with a built-in are skipped so user files can
    never silently replace (and then lock) a built-in persona/skill.
    """
    if not os.path.isdir(dirname):
        return
    for fn in sorted(os.listdir(dirname)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(dirname, fn), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("name"):
                key = data["name"].strip().lower()
                if builtin and key in builtin:
                    continue
                registry[key] = data
        except (OSError, ValueError):
            continue


def _persist(dirname: str, name: str, data: dict) -> str:
    os.makedirs(dirname, exist_ok=True)
    path = os.path.join(dirname, _safe_filename(name))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


_BUILTIN_AGENTS = set(AGENTS)
_BUILTIN_SKILLS = set(SKILLS)

_load_custom(_AGENTS_DIR, AGENTS, _BUILTIN_AGENTS)
_load_custom(_SKILLS_DIR, SKILLS, _BUILTIN_SKILLS)


def add_agent(name: str, system_prompt: str, role: str = "",
              description: str = "", keywords: Optional[List[str]] = None) -> dict:
    """Register a new agent persona at runtime and persist it to disk."""
    key = name.strip().lower()
    if not key:
        raise ValueError("Agent name is required")
    if key in _BUILTIN_AGENTS:
        raise ValueError(f"'{name}' is a built-in agent and cannot be overridden")
    if not system_prompt or not system_prompt.strip():
        raise ValueError("system_prompt is required")
    agent = {
        "name": key,
        "role": role or "Custom Agent",
        "description": description or f"User-defined agent: {name}",
        "system_prompt": system_prompt,
        "keywords": list(keywords or [key]),
    }
    with _LOCK:
        AGENTS[key] = agent
        _persist(_AGENTS_DIR, key, agent)
    return agent


def delete_agent(name: str) -> bool:
    """Remove a user-defined agent. Built-in personas cannot be deleted."""
    key = name.strip().lower()
    if key in _BUILTIN_AGENTS:
        return False
    with _LOCK:
        if AGENTS.pop(key, None) is None:
            return False
        try:
            os.remove(os.path.join(_AGENTS_DIR, _safe_filename(key)))
        except OSError:
            pass
    return True


def add_skill(name: str, template: str, system_prompt: str = "",
              description: str = "", params: Optional[List[dict]] = None) -> dict:
    """Register a new skill at runtime and persist it to disk."""
    key = name.strip().lower()
    if not key:
        raise ValueError("Skill name is required")
    if key in _BUILTIN_SKILLS:
        raise ValueError(f"'{name}' is a built-in skill and cannot be overridden")
    if not template or "{input}" not in template:
        raise ValueError("template is required and must contain {input}")
    skill = {
        "name": key,
        "description": description or f"User-defined skill: {name}",
        "system_prompt": system_prompt or "You are a helpful assistant specialized in this task.",
        "template": template,
        "params": [
            {"name": str(p.get("name")), "default": p.get("default", "")}
            for p in (params or [])
            if isinstance(p, dict) and str(p.get("name", "")).strip()
        ],
    }
    with _LOCK:
        SKILLS[key] = skill
        _persist(_SKILLS_DIR, key, skill)
    return skill


def delete_skill(name: str) -> bool:
    """Remove a user-defined skill. Built-in skills cannot be deleted."""
    key = name.strip().lower()
    if key in _BUILTIN_SKILLS:
        return False
    with _LOCK:
        if SKILLS.pop(key, None) is None:
            return False
        try:
            os.remove(os.path.join(_SKILLS_DIR, _safe_filename(key)))
        except OSError:
            pass
    return True
