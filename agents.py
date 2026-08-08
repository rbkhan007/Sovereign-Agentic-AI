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
import tempfile
import threading
from typing import Dict, List, Optional

_AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
_LOCK = threading.RLock()


def _db():
    """Return the database module when DB-backed persistence is live, else None.
    Cheap: checks the pool without attempting a connection."""
    try:
        import database as _db_mod
        if _db_mod.db_ready():
            return _db_mod
    except Exception:
        pass
    return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-") or "item"


def _safe_filename(name: str) -> str:
    return _slug(name) + ".json"


def _check_filename_collision(key: str, registry: Dict[str, dict], kind: str):
    """Reject a name whose safe filename would overwrite a different entry.

    Slugs collide when distinct keys normalize to the same filename (e.g. 'my
    agent' vs 'my-agent'). Silently persisting would let the second write
    clobber the first's JSON file, so that agent/skill would vanish on reload.
    """
    mine = _safe_filename(key)
    for other in registry:
        if other != key and _safe_filename(other) == mine:
            raise ValueError(
                f"{kind} name '{key}' collides with '{other}' on disk "
                f"(both write {mine}); pick a different name"
            )

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
    "agent_x": {
        "name": "agent_x",
        "role": "Agent X (All-in-One)",
        "description": "Universal autonomous problem-solver: delivers complete, production-ready, any-to-any results.",
        "model": "mythos-nano",
        "workflow": "auto_approved",
        "system_prompt": (
            "You are Agent X, a universal autonomous engineer and problem solver. "
            "You produce COMPLETE, PRODUCTION-READY, ACCURATE deliverables for "
            "ANY-TO-ANY work: code, data, analysis, planning, translation, "
            "debugging, summarization, research and orchestration.\n\n"
            "OPERATING PRINCIPLES\n"
            "- Follow the user's GOAL precisely and respect the project INDEX "
            "(the workspace file tree) so every file you create or edit lives in "
            "the correct place and integrates with what already exists.\n"
            "- Work AUTONOMOUSLY end to end. Do not ask clarifying questions unless "
            "the request is genuinely impossible to act on; when you must choose, "
            "pick the safest, most standard option and note the assumption.\n"
            "- Prefer the strongest reasoning: think step by step, then act. Aim "
            "for Claude-class accuracy and clarity in every answer.\n\n"
            "WORKFLOW\n"
            "1. Restate the goal in one line and the single best plan (1-2 lines).\n"
            "2. Inspect the relevant project index/context before changing anything.\n"
            "3. Decompose into small, ordered, verifiable steps and execute them, "
            "retrying with a different approach if a step fails.\n"
            "4. Deliver RUNNABLE, COPY-PASTE-READY output: emit the FULL file "
            "contents in a fenced code block (language-tagged) when code is "
            "involved, otherwise clear, structured prose.\n"
            "5. For software, include a minimal entry point, required "
            "dependencies/install command, and a quick self-check or test so the "
            "result is complete and verifiable.\n"
            "6. Verify the output against the original goal; end with a one-line "
            "summary of what was produced and any assumptions or limits.\n\n"
            "QUALITY BAR (production-ready)\n"
            "- Clean, idiomatic, well-structured code; single responsibility; "
            "no dead code; only the imports that are used.\n"
            "- Never invent APIs, libraries, functions or data. If a dependency is "
            "needed, state the exact install command.\n"
            "- Handle obvious edge cases and errors gracefully.\n"
            "- If a task spans multiple specialties, combine them into one coherent, "
            "consistent solution rather than disjoint fragments."
        ),
        "keywords": [
            "agent x", "anything", "any to any", "do everything", "task", "automate",
            "solve", "orchestrate", "universal", "complete", "end to end", "all in one",
            "production", "autonomous", "build project",
        ],
    },
}

DEFAULT_AGENT = "agent_x"

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
        agent = AGENTS.get(DEFAULT_AGENT)
        return dict(agent) if agent else None
    agent = AGENTS.get(name.strip().lower())
    return dict(agent) if agent else None


def agent_system_prompt(name: str) -> str:
    a = get_agent(name)
    return a["system_prompt"] if a else AGENTS[DEFAULT_AGENT]["system_prompt"]


def list_skills() -> List[str]:
    return sorted(SKILLS.keys())


def get_skill(name: str) -> Optional[dict]:
    skill = SKILLS.get(name.strip().lower())
    return dict(skill) if skill else None


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
        if p["name"] == "input":
            continue
        fill[p["name"]] = (params or {}).get(p["name"], p.get("default", ""))
    try:
        prompt = skill["template"].format(input=input_text, **fill)
    except (KeyError, ValueError, IndexError, TypeError):
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
    fd, tmp = tempfile.mkstemp(dir=dirname, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def _load_custom_db(kind: str, registry: Dict[str, dict], builtin: Optional[set] = None):
    """Hydrate user-defined entries from the DB into the given registry.

    Only runs when the DB is live (pool available). Entries whose name
    collides with a built-in are skipped so DB rows can never silently
    replace a built-in persona/skill. DB rows win over stale JSON files.
    """
    db = _db()
    if db is None:
        return
    try:
        rows = db.load_agents() if kind == "agents" else db.load_skills()
    except Exception:
        return
    for data in rows:
        key = data.get("name")
        if not key:
            continue
        key = key.strip().lower()
        if builtin and key in builtin:
            continue
        registry[key] = data


_BUILTIN_AGENTS = set(AGENTS)
_BUILTIN_SKILLS = set(SKILLS)

_load_custom(_AGENTS_DIR, AGENTS, _BUILTIN_AGENTS)
_load_custom(_SKILLS_DIR, SKILLS, _BUILTIN_SKILLS)
_load_custom_db("agents", AGENTS, _BUILTIN_AGENTS)
_load_custom_db("skills", SKILLS, _BUILTIN_SKILLS)


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
    with _LOCK:
        _check_filename_collision(key, AGENTS, "Agent")
        agent = {
            "name": key,
            "role": role or "Custom Agent",
            "description": description or f"User-defined agent: {name}",
            "system_prompt": system_prompt,
            "keywords": list(keywords or [key]),
        }
        AGENTS[key] = agent
        _persist(_AGENTS_DIR, key, agent)
        db = _db()
        if db is not None:
            try:
                db.save_agent(
                    key, agent["role"], agent["description"],
                    agent["system_prompt"], agent.get("keywords"),
                )
            except Exception:
                pass
    return agent


def delete_agent(name: str) -> bool:
    """Remove a user-defined agent. Built-in personas cannot be deleted."""
    key = name.strip().lower()
    if key in _BUILTIN_AGENTS:
        return False
    with _LOCK:
        agent = AGENTS.pop(key, None)
        if agent is None:
            return False
        removed = False
        try:
            os.remove(os.path.join(_AGENTS_DIR, _safe_filename(key)))
            removed = True
        except OSError:
            pass
        db = _db()
        if db is not None:
            try:
                db.delete_agent(key)
            except Exception:
                # DB delete failed: restore state so the row doesn't re-hydrate
                # on restart and resurrect a "deleted" agent.
                AGENTS[key] = agent
                if removed:
                    try:
                        _persist(_AGENTS_DIR, key, agent)
                    except Exception:
                        pass
                return False
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
    with _LOCK:
        _check_filename_collision(key, SKILLS, "Skill")
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
        SKILLS[key] = skill
        _persist(_SKILLS_DIR, key, skill)
        db = _db()
        if db is not None:
            try:
                db.save_skill(
                    key, skill["description"], skill["system_prompt"],
                    skill["template"], skill.get("params"),
                )
            except Exception:
                pass
    return skill


def delete_skill(name: str) -> bool:
    """Remove a user-defined skill. Built-in skills cannot be deleted."""
    key = name.strip().lower()
    if key in _BUILTIN_SKILLS:
        return False
    with _LOCK:
        skill = SKILLS.pop(key, None)
        if skill is None:
            return False
        removed = False
        try:
            os.remove(os.path.join(_SKILLS_DIR, _safe_filename(key)))
            removed = True
        except OSError:
            pass
        db = _db()
        if db is not None:
            try:
                db.delete_skill(key)
            except Exception:
                # DB delete failed: restore state so the row doesn't re-hydrate
                # on restart and resurrect a "deleted" skill.
                SKILLS[key] = skill
                if removed:
                    try:
                        _persist(_SKILLS_DIR, key, skill)
                    except Exception:
                        pass
                return False
    return True
