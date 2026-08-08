import builtins
import json
import logging
import os
import re
import struct
import subprocess
import sys
import time
import types
import uuid
from typing import Optional

from config import CONFIG, HAS_GPU, CLOUD_PRESETS
from memory import MemoryManager
from models import ModelManager
from orchestrator import Orchestrator
from computer_agent import create_computer_agent
import agents

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

_HISTORY: list = []
_MAX_HISTORY = 200
_USE_COLOR = None


def _enable_utf8():
    """Reconfigure stdout/stderr to UTF-8 so model Unicode never crashes the
    Windows console (cp1252 'charmap' can't encode e.g. em-dashes/emoji).
    errors='replace' keeps piping/redirects safe instead of raising."""
    for stream in (sys.stdout, sys.stderr):
        try:
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _init_color() -> bool:
    global _USE_COLOR
    if _USE_COLOR is not None:
        return _USE_COLOR
    _USE_COLOR = bool(sys.stdout.isatty()) and not os.environ.get("NO_COLOR")
    if _USE_COLOR:
        try:
            import colorama
            colorama.init()
        except Exception:
            try:
                os.system("")
            except Exception:
                pass
    return _USE_COLOR


def _paint(text, code):
    return f"\033[{code}m{text}\033[0m" if _init_color() else text


def _dim(text):
    return _paint(text, "2")


def _green(text):
    return _paint(text, "92")


def _yellow(text):
    return _paint(text, "93")


def _red(text):
    return _paint(text, "91")


def _cyan(text):
    return _paint(text, "96")


def _bold(text):
    return _paint(text, "1")


def _italic(text):
    return _paint(text, "3")


def _underline(text):
    return _paint(text, "4")


def _strikethrough(text):
    return _paint(text, "9")


def _inverse(text):
    return _paint(text, "7")


# Modern color palette (Gemini CLI / CodeCLI inspired)
def _muted(text):
    return _paint(text, "90")


def _subtle(text):
    return _paint(text, "37")


def _accent(text):
    return _paint(text, "36")


def _user_color(text):
    return _paint(text, "94")


def _assistant_color(text):
    return _paint(text, "32")


def _thinking_color(text):
    return _paint(text, "35")


def _tool_color(text):
    return _paint(text, "33")


def _error_color(text):
    return _paint(text, "31")


def _success_color(text):
    return _paint(text, "32")


def _warning_color(text):
    return _paint(text, "33")


def _info_color(text):
    return _paint(text, "36")


def _border(text):
    return _paint(text, "90")


def _border_light(text):
    return _paint(text, "37")


def _bg_dim(text):
    return _paint(text, "100")


# Box-drawing helpers for modern rounded corners
def _round_corner(text):
    return _g(text, "+")


def _round_h(text):
    return _g("\u2500", "-")


def _round_v(text):
    return _g("\u2502", "|")


def _corner_tl(text):
    return _g("\u256d", "+")


def _corner_tr(text):
    return _g("\u256e", "+")


def _corner_bl(text):
    return _g("\u2570", "\\")


def _corner_br(text):
    return _g("\u256f", "+")


def _tee_left(text):
    return _g("\u251c", "+")


def _tee_right(text):
    return _g("\u2524", "+")


def _tee_top(text):
    return _g("\u252c", "+")


def _tee_bottom(text):
    return _g("\u2534", "+")


def _cross(text):
    return _g("\u253c", "+")


def _g(s: str, fallback: str) -> str:
    """Return s if stdout's encoding can represent it, else fallback."""
    try:
        s.encode(getattr(sys.stdout, "encoding", None) or "utf-8")
        return s
    except (UnicodeEncodeError, LookupError):
        return fallback


def _box_line(text: str = "", width: int = 58) -> str:
    border = _g("\u2551", "|")
    return f"  {border}  {text:<{width}}  {border}"


def _box_rule(char: str) -> str:
    return "  " + _g(char, "+") + _g("\u2550", "=") * 62 + _g(char, "+")


WELCOME = _accent("\n".join([
    _g("\u256d", "+") + _g("\u2500", "-") * 64 + _g("\u256e", "+"),
    _g("\u2502", "|") + " " + _bold("Sovereign-Agentic-AI") + " " * 46 + _g("\u2502", "|"),
    _g("\u2502", "|") + " " + _dim("Local Multi-Agent LLM · Terminal") + " " * 32 + _g("\u2502", "|"),
    _g("\u251c", "+") + _g("\u2500", "-") * 64 + _g("\u2524", "+"),
    _g("\u2502", "|") + f" GPU: {'Enabled (' + CONFIG.gpu_name + ')' if HAS_GPU else 'Disabled'}",
    _g("\u2502", "|") + f" Threads: {CONFIG.threads}   Models: {len(CONFIG.available_models)}   DB: {'ON' if CONFIG.db.enabled else 'off'}",
    _g("\u2502", "|") + f" Cloud: {CONFIG.cloud_provider or 'none'}",
    _g("\u2570", "\\") + _g("\u2500", "-") * 64 + _g("\u256f", "+"),
    "",
    _g("  ", "") + _accent("Try:") + _g("  'explain quantum computing'", "") + _g("  |  ", "") +
    _g("'/code fix this'", "") + _g("  |  ", "") + _g("'/parallel on'", "") + _g("  |  ", "") +
    _g("'/arc 5'", ""),
    _dim("  Planning is ON · Toggle with /plan · Ensemble with /parallel"),
    "",
]))

HELP_TEXT = f"""
{_bold(_accent('  QUICK START'))}
  Ask anything:       explain quantum computing
  Use an agent:       /agent agent_x
  Switch model:       /model qwen2.5-omni-3b
  Run code:           /code on
  Shell command:      !dir
  Help:               /help

{_bold(_accent('  SYSTEM'))}
  /help                show this help
  /status              live status (HUD, VRAM, models, config)
  /debug on|off        toggle debug logging
  /new                 start a fresh conversation
  /retry               re-run your last prompt
  /clear               clear this conversation
  /exit                quit

{_bold(_accent('  MODELS'))}
  /model <name>        switch executor model
  /models              list all models (local + cloud)
  /preload <name>      load a model into VRAM now
  /unload [name]       unload model(s) from VRAM
  /vram                VRAM usage per loaded model

{_bold(_accent('  PLANNING & REASONING'))}
  /plan on|off         toggle planning/reasoning (strategist)
  /think on|off        toggle live reasoning output
  /harness             show adaptive model-selection scores
  /harness reset       clear all harness scores
  /harness adjust <task> <model> <score>  manually set a score
  /harness export|import persist/restore harness state
  /arc [n]             run ARC reasoning eval (needs arc/training.json)

{_bold(_accent('  AGENTS & SKILLS'))}
  /agent <name>        switch agent persona (see /agents)
  /agents              list agent personas (agent_x, general, custom...)
  /skills              list skills (summarize, translate, code-review, ...)
  /skill <name> <text> run a skill directly on text
  /code on|off         toggle coding mode (agent_x handles code)
  /computer <goal>     full computer-use agent (shell, files, web, system)
  /computer tools      list available computer agent tools
  /computer sandbox on|off  toggle sandbox mode (read-only)
  /lora <sub>          list|enable|disable|import|train|delete

{_bold(_accent('  GENERATION'))}
  /parallel on|off     ensemble mode: N models answer, a judge picks best
  /context show|set|clear  inspect / set system prompt, show recent context
  /temperature <0-2>   override sampling temperature
  /max <tokens>        override max output tokens
  /timeout <seconds>   change generation watchdog timeout
  /tokens              token usage this session

{_bold(_accent('  CONVERSATIONS'))}
  /save [name]         persist this conversation to disk
  /load <name>         restore a saved conversation
  /sessions            list saved conversations

{_bold(_accent('  CLOUD & MEMORY'))}
  /openai <key>        set OpenAI-compatible API key
  /cloud <name>        cloud preset: {', '.join(CLOUD_PRESETS)} (key via /openai)
  /db on|off|stats|clear|search|tables|index
                        toggle PostgreSQL, show stats, clear, search, list tables/indexes
  /prune               delete memories older than {CONFIG.prune_max_age_days} days
  /exec <cmd>          run a shell command   (or prefix with !)

{_bold(_accent('  MCP TOOLS'))}
  /mcp                 list all MCP tools (chat, agents, skills)
  /mcp call <tool> <input>  call an MCP tool from the terminal
  /mcp json            output tool list as JSON

{_bold(_accent('  EXAMPLES'))}
  /agent agent_x
  /model qwen2.5-omni-3b
  /computer find all .py files and count lines
  /code on
  /skill summarize Paste a long text here
  /mcp call chat What is machine learning?
  /harness adjust code hy-mt2 85.0

{_bold(_accent('  SHORTCUTS'))}
  !!                   re-run last prompt (same as /retry)
  !<command>           run shell command
  Enter to send, \\ at line end for multi-line, Ctrl+C to stop output
  Ctrl+A select all   Ctrl+C copy (or cancel)   Ctrl+V paste   Ctrl+X cut
  Ctrl+D del   Ctrl+W word-del   Ctrl+K del-to-end   Ctrl+U del-to-start
  Tab                  auto-complete commands
  Mouse: click to position cursor, drag to select, double-click a word,
         right-click to paste
"""

_COMMANDS = [
    "/help", "/status", "/debug", "/new", "/retry", "/clear", "/exit",
    "/model", "/models", "/preload", "/unload", "/vram",
    "/plan", "/think", "/harness", "/arc",
    "/agent", "/agents", "/skill", "/skills", "/code", "/computer",
    "/parallel", "/context", "/temperature", "/max", "/timeout", "/tokens",
    "/save", "/load", "/sessions",
    "/openai", "/cloud", "/db", "/prune", "/exec", "/lora",
    "/mcp", "/temp", "/shell", "/max-tokens",
]

_ALWAYS_ALLOWED = ("/help", "/?", "/exit", "/quit", "/status")


def _command_allowed(cmd: str) -> bool:
    """Whether a slash command may run under CONFIG.cli_command_whitelist.

    An empty whitelist (the default) allows every command. Control commands
    (/help, /?, /exit, /quit, /status) always remain available so the user can
    get help and escape even when a restrictive whitelist is active. Matching is
    on the base command name (leading slash ignored), so a whitelisted "lora"
    or "/lora" permits "/lora train".
    """
    if not cmd.startswith("/"):
        return True
    base = cmd.split(" ", 1)[0].lower().lstrip("/")
    if not CONFIG.cli_command_whitelist:
        return True
    allowed = {c.lower().lstrip("/") for c in CONFIG.cli_command_whitelist}
    always = {c.lstrip("/") for c in _ALWAYS_ALLOWED if c != "/"}
    return base in always or base in allowed


def _visible_commands() -> list[str]:
    """Commands offered for tab-completion, honoring the whitelist."""
    if not CONFIG.cli_command_whitelist:
        return list(_COMMANDS)
    allowed = {c.lower().lstrip("/") for c in CONFIG.cli_command_whitelist}
    always = {c.lstrip("/") for c in _ALWAYS_ALLOWED if c != "/"}
    return [c for c in _COMMANDS if c.lstrip("/") in always or c.lstrip("/") in allowed]


def _prompt() -> str:
    return _accent(_g("\u25b8 ", "> "))


def _split_args(line) -> list[str]:
    try:
        import shlex
        return shlex.split(line)
    except ValueError:
        return line.split()


def _session_path(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "session"
    return os.path.join(SESSIONS_DIR, safe + ".json")


def _save_session(name: str, mem: MemoryManager, conv_id: str, st: dict):
    conv = mem.get_or_create(conv_id)
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    data = {
        "name": name,
        "saved_at": time.time(),
        "system_prompt": conv.system_prompt,
        "messages": [m.to_dict() for m in conv.messages],
        "state": {
            "tokens": st.get("tokens", 0),
            "temperature": st.get("temperature"),
            "max_tokens": st.get("max_tokens", 2048),
            "last_prompt": st.get("last_prompt", ""),
            "agent": st.get("agent", "default"),
            "planning": st.get("planning", False),
            "parallel": st.get("parallel", False),
            "coding": st.get("coding", False),
            "last_model": st.get("last_model"),
            "conv_id": conv_id,
        },
    }
    with open(_session_path(name), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _load_session(name: str, mem: MemoryManager) -> Optional[dict]:
    path = _session_path(name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    # Restore into a dedicated session conversation so loading never wipes a
    # live conversation that happens to share the session name (e.g. "default").
    conv = mem.get_or_create(f"session:{name}")
    conv.clear()
    if data.get("system_prompt"):
        conv.set_system(data["system_prompt"])
    for m in data.get("messages", []):
        conv.add(m.get("role", "user"), m.get("content", ""))
    data.setdefault("state", {})
    return data


def _list_sessions() -> list:
    if not os.path.isdir(SESSIONS_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(SESSIONS_DIR) if f.endswith(".json"))


def _run_shell(cmd: str):
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)  # nosec B602
        out = proc.stdout or ""
        if proc.returncode != 0:
            out += (proc.stderr or "")
        if out.strip():
            print(out.rstrip())
        else:
            print(_dim(f"[exit {proc.returncode}]"))
    except subprocess.TimeoutExpired:
        print(_error_color("[Error] command timed out"))
    except Exception as e:
        print(_error_color(f"[Error] {e}"))


def _hud(st: dict, mm: ModelManager) -> str:
    cloud = CONFIG.cloud_provider or ("openai" if CONFIG.openai.enabled else "none")
    parts = [
        _accent(f"agent:{st.get('agent', '?')}"),
        _success_color(f"model:{st.get('last_model', '?')}"),
        _success_color("plan:ON") if st.get("planning") else _muted("plan:off"),
        _success_color("par:ON") if st.get("parallel") else _muted("par:off"),
        _success_color("code:ON") if st.get("coding") else _muted("code:off"),
        _info_color(f"cloud:{cloud}"),
        _muted(f"tok:{st.get('tokens', 0)}"),
    ]
    temperature = st.get("temperature")
    if temperature is not None:
        parts.append(_muted(f"temp:{temperature}"))
    max_tokens = st.get("max_tokens")
    if max_tokens:
        parts.append(_muted(f"max:{max_tokens}"))
    if mm.instances:
        parts.append(_success_color(f"loaded:{len(mm.instances)}"))
    return "  " + _dim(" · ").join(parts)


# ---------- TUI: chat-style interface with fixed input + scrollable message area ----------

class Message:
    __slots__ = ("role", "content", "timestamp", "model", "tokens", "elapsed")

    def __init__(self, role: str, content: str, **kwargs):
        self.role = role
        self.content = content
        self.timestamp = kwargs.get("timestamp", time.time())
        self.model = kwargs.get("model", "")
        self.tokens = kwargs.get("tokens", 0)
        self.elapsed = kwargs.get("elapsed", 0.0)

    def avatar(self) -> str:
        if self.role == "user":
            return "👤"
        if self.role == "assistant":
            return "🤖"
        if self.role == "system":
            return "⚙️ "
        if self.role == "thinking":
            return "💭"
        return "📌"

    def role_color(self) -> str:
        if self.role == "user":
            return "92"
        if self.role == "assistant":
            return "96"
        if self.role in ("system", "thinking"):
            return "93"
        return "95"

    def role_label(self) -> str:
        if self.role == "user":
            return "You"
        if self.role == "assistant":
            return "Assistant"
        if self.role == "thinking":
            return "Thinking"
        if self.role == "tool":
            return "Tool"
        return self.role.capitalize()


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)


# Modern Unicode icons (Gemini CLI / CodeCLI inspired)
_ICONS = {
    "user": "👤",
    "assistant": "🤖",
    "system": "⚙️ ",
    "thinking": "💭",
    "tool": "🔧",
    "error": "❌",
    "success": "✅",
    "warning": "⚠️ ",
    "info": "ℹ️ ",
    "model": "🧠",
    "tokens": "📊",
    "time": "⏱",
    "arrow": "▸",
    "bullet": "•",
    "dot": "·",
    "dash": "─",
    "pipe": "│",
    "cross": "┼",
    "tee": "├",
    "corner_tl": "╭",
    "corner_tr": "╮",
    "corner_bl": "╰",
    "corner_br": "╯",
    "h_line": "─",
    "v_line": "│",
}


class TUIRenderer:
    """Modern chat-style TUI inspired by Gemini CLI and OpenCode CodeCLI."""
    HEADER_H = 2
    INPUT_H = 3
    MIN_MSG_H = 5

    def __init__(self):
        self.messages: list[Message] = []
        self.scroll = 0
        self.selected = -1
        self.term_width = 80
        self.term_height = 24
        self.msg_area_h = 0
        self.msg_start_y = 0
        self.input_start_y = 0
        self._update_size()

    def _update_size(self):
        try:
            import shutil
            self.term_width = shutil.get_terminal_size().columns
            self.term_height = shutil.get_terminal_size().lines
        except Exception:
            self.term_width = 80
            self.term_height = 24
        self.msg_start_y = self.HEADER_H + 1
        self.input_start_y = max(self.msg_start_y + 1, self.term_height - self.INPUT_H)
        self.msg_area_h = max(self.MIN_MSG_H, self.input_start_y - self.msg_start_y)

    def add(self, role: str, content: str, **kwargs):
        self.messages.append(Message(role, content, **kwargs))
        self.scroll = max(0, len(self.messages) - self.msg_area_h)

    def clear(self):
        self.messages.clear()
        self.scroll = 0
        self.selected = -1

    def _wrap(self, text: str, width: int) -> list[str]:
        lines = text.split("\n")
        out: list[str] = []
        for line in lines:
            while len(line) > width:
                out.append(line[:width])
                line = line[width:]
            out.append(line)
        return out or [""]

    def _render_message_bubble(self, msg: Message, y: int, width: int) -> int:
        """Render a modern message bubble with rounded corners."""
        pad = 1
        inner_width = width - (pad * 2) - 2
        inner_width = max(10, inner_width)

        # Role-based styling
        if msg.role == "user":
            role_color = _user_color
            icon = _ICONS["user"]
            label = _bold(_user_color("You"))
            bubble_style = _border
        elif msg.role == "assistant":
            role_color = _assistant_color
            icon = _ICONS["assistant"]
            label = _bold(_assistant_color("Assistant"))
            bubble_style = _border_light
        elif msg.role == "thinking":
            role_color = _thinking_color
            icon = _ICONS["thinking"]
            label = _italic(_thinking_color("Thinking"))
            bubble_style = _border
        elif msg.role == "tool":
            role_color = _tool_color
            icon = _ICONS["tool"]
            label = _bold(_tool_color("Tool"))
            bubble_style = _border
        else:
            role_color = _muted
            icon = _ICONS.get(msg.role, "📌")
            label = _bold(_muted(msg.role.capitalize()))
            bubble_style = _border

        # Meta information
        meta_parts = []
        if msg.model:
            meta_parts.append(f"{_ICONS['model']} {msg.model}")
        if msg.tokens:
            meta_parts.append(f"{_ICONS['tokens']} {msg.tokens}")
        if msg.elapsed:
            meta_parts.append(f"{_ICONS['time']} {msg.elapsed:.1f}s")
        meta = _muted("  ".join(meta_parts)) if meta_parts else ""

        # Content lines
        lines = self._wrap(msg.content, inner_width)
        bubble_h = 3 + len(lines)  # header + separator + content + bottom

        # Top border with rounded corners
        sys.stdout.write(f"\033[{y};1H")
        top_border = _paint(" " * pad, "") + bubble_style(_corner_tl("╭") + _round_h("─") * (inner_width + 2) + _corner_tr("╮"))
        sys.stdout.write(top_border + "\n")
        y += 1

        # Header line
        sys.stdout.write(f"\033[{y};1H")
        header = bubble_style(_round_v("│")) + " " + icon + " " + label
        if meta:
            header += "  " + meta
        padding = " " * (inner_width + 2 - _strip_ansi_len(header) + 1)
        sys.stdout.write(header + padding + bubble_style(_round_v("│")) + "\n")
        y += 1

        # Separator
        sys.stdout.write(f"\033[{y};1H")
        sep = bubble_style(_tee_left("├") + _round_h("─") * (inner_width + 2) + _tee_right("┤"))
        sys.stdout.write(sep + "\n")
        y += 1

        # Content lines
        for line in lines:
            sys.stdout.write(f"\033[{y};1H")
            content_str = bubble_style(_round_v("│")) + " " + line.ljust(inner_width) + " " + bubble_style(_round_v("│"))
            sys.stdout.write(content_str + "\n")
            y += 1

        # Bottom border with rounded corners
        sys.stdout.write(f"\033[{y};1H")
        bottom_border = _paint(" " * pad, "") + bubble_style(_corner_bl("╰") + _round_h("─") * (inner_width + 2) + _corner_br("╯"))
        sys.stdout.write(bottom_border + "\n")
        return bubble_h + 1

    def render(self):
        self._update_size()
        width = self.term_width - 2
        width = max(width, 20)

        # Clear screen + hide cursor
        sys.stdout.write("\033[2J\033[H\033[?25l")
        sys.stdout.flush()

        # Header
        self._render_header(width)

        # Scroll region for messages
        top = self.msg_start_y
        bot = self.input_start_y - 1
        sys.stdout.write(f"\033[{top};{bot+1}r")
        sys.stdout.flush()

        # Messages
        self._render_messages(width)

        # Reset scroll region to full terminal
        sys.stdout.write(f"\033[1;{self.term_height}r")
        sys.stdout.flush()

        # Input area
        self._render_input_area(width)

        # Show cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def _render_header(self, width: int):
        # Modern header with status indicators
        title = _bold(_accent("◇")) + " " + _bold("Sovereign-Agentic-AI") + " " + _dim("·") + " " + _muted("Terminal")
        stats = _muted(f"{self.term_width}x{self.term_height}") + _dim(" · ") + _muted(f"{len(self.messages)} msgs")
        if self.scroll > 0:
            stats += _dim(" · ") + _muted(f"scroll {self.scroll}")

        line = title + "  " + stats
        if _strip_ansi_len(line) > width:
            line = _strip_ansi(line)[:width - 3] + _dim("...")

        sys.stdout.write(f"\033[1;1H{line}\n")
        sys.stdout.write(f"\033[2;1H{_muted(_round_h('─') * self.term_width)}\n")
        sys.stdout.flush()

    def _render_messages(self, width: int):
        if not self.messages:
            sys.stdout.write(f"\033[{self.msg_start_y};1H")
            sys.stdout.write(_muted("  No messages yet. Type something to start...") + "\n")
            sys.stdout.flush()
            return

        # Calculate visible messages
        available = max(1, self.msg_area_h)
        heights = []
        total_h = 0
        for i in range(len(self.messages) - 1, -1, -1):
            h = self._message_cell_height(self.messages[i], width)
            if total_h + h > available:
                break
            heights.append((i, h))
            total_h += h
        heights.reverse()

        end = len(self.messages)
        if self.scroll > 0:
            idx = len(heights) - 1
            offset = self.scroll
            while idx >= 0 and offset > 0:
                offset -= heights[idx][1]
                if offset > 0:
                    idx -= 1
            idx = max(0, idx)
            if heights:
                heights = heights[:idx + 1]

        y = self.msg_start_y
        for i, _h in heights:
            y += self._render_message_bubble(self.messages[i], y, width)

        # Scroll indicator
        if len(self.messages) > len(heights):
            start = heights[0][0] + 1 if heights else len(self.messages)
            info = _muted(f"  {start}-{end} of {len(self.messages)}")
            sys.stdout.write(f"\033[{self.input_start_y - 1};1H{info}")
            sys.stdout.flush()

    def _message_cell_height(self, msg: Message, width: int) -> int:
        pad = 1
        inner = max(1, width - (pad * 2) - 2)
        return 4 + len(self._wrap(msg.content, inner))

    def _render_input_area(self, width: int):
        y = self.input_start_y
        sys.stdout.write(f"\033[{y};1H{_muted(_round_h('─') * self.term_width)}\n")
        sys.stdout.write(f"\033[{y+1};1H" + _accent(_ICONS["arrow"] + " ") + "\n")
        hint = _muted("Type a message") + _dim(" · ") + _muted("/help for commands") + _dim(" · ") + _muted("Tab to complete")
        if _strip_ansi_len(hint) > width:
            hint = _strip_ansi(hint)[:width - 3] + _dim("...")
        sys.stdout.write(f"\033[{y+2};1H{hint}\n")
        sys.stdout.flush()

    def scroll_up(self, amount: int = 3):
        self.scroll = max(0, self.scroll - amount)

    def scroll_down(self, amount: int = 3):
        max_scroll = max(0, len(self.messages) - self.msg_area_h)
        self.scroll = min(max_scroll, self.scroll + amount)


def _strip_ansi_len(s: str) -> int:
    return len(_strip_ansi(s))

    def select_at(self, y: int):
        if y < self.msg_start_y or y >= self.input_start_y:
            self.selected = -1
            return
        # approximate selection by visible range
        visible = self.msg_area_h
        start = max(0, len(self.messages) - visible - self.scroll)
        idx = start + (y - self.msg_start_y)
        if 0 <= idx < len(self.messages):
            self.selected = idx
        else:
            self.selected = -1


def _clipboard_copy(text: str):
    import ctypes
    from ctypes import wintypes
    if not text:
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, wintypes.INT]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    if not user32.OpenClipboard(None):
        return
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(0x0042, len(data))
        if handle:
            ptr = kernel32.GlobalLock(handle)
            if ptr:
                ctypes.memmove(ptr, data, len(data))
                kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(13, handle)
    finally:
        user32.CloseClipboard()


def _clipboard_paste() -> str:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            size = kernel32.GlobalSize(handle)
            raw = ctypes.string_at(ptr, int(size))
        finally:
            kernel32.GlobalUnlock(handle)
        return raw.decode("utf-16-le", "ignore").split("\x00", 1)[0]
    finally:
        user32.CloseClipboard()


# ---------- interactive line editor (Windows) ----------

_CF_UNICODETEXT = 13
_GHND = 0x0042
_KEY_EVENT = 0x0001
_MOUSE_EVENT = 0x0002
_MOUSE_MOVED = 0x0001
_MOUSE_DOUBLE_CLICK = 0x0002
_MOUSE_WHEELED = 0x0004
_MS_LEFT = 0x0001
_MS_RIGHT = 0x0002
_VK_BACK = 0x08
_VK_TAB = 0x09
_VK_RETURN = 0x0D
_VK_ESCAPE = 0x1B
_VK_HOME = 0x24
_VK_END = 0x23
_VK_LEFT = 0x25
_VK_UP = 0x26
_VK_RIGHT = 0x27
_VK_DOWN = 0x28
_VK_DELETE = 0x2E
_VK_PRIOR = 0x21
_VK_NEXT = 0x22
_SHIFT = 0x0010
_CTRL = 0x000C


def _parse_record(raw: bytes):
    etype = struct.unpack_from("<H", raw, 0)[0]
    if etype == _KEY_EVENT:
        down = struct.unpack_from("<I", raw, 4)[0]
        repeat = struct.unpack_from("<H", raw, 8)[0]
        vk = struct.unpack_from("<H", raw, 10)[0]
        ch = struct.unpack_from("<H", raw, 14)[0]
        state = struct.unpack_from("<I", raw, 16)[0]
        return ("key", down, repeat, vk, chr(ch), state)
    if etype == _MOUSE_EVENT:
        x, y = struct.unpack_from("<hh", raw, 4)
        buttons = struct.unpack_from("<I", raw, 8)[0]
        state = struct.unpack_from("<I", raw, 12)[0]
        flags = struct.unpack_from("<I", raw, 16)[0]
        return ("mouse", x, y, buttons, state, flags)
    return ("other", etype)


def _word_bounds(buf: list, idx: int):
    if not buf:
        return 0, 0
    idx = max(0, min(idx, len(buf) - 1))
    a = idx
    while a > 0 and not buf[a - 1].isspace():
        a -= 1
    b = idx
    while b < len(buf) and not buf[b].isspace():
        b += 1
    return a, b


def _replace_selection(buf: list, pos: int, sel, text: str):
    if sel[0] >= 0 and sel[0] < sel[1]:
        a, b = sel[0], sel[1]
        buf[a:b] = list(text)
        pos = a + len(text)
        sel = (-1, -1)
    else:
        for ch in text:
            buf.insert(pos, ch)
            pos += 1
    return pos, sel


def _msvcrt_edit(prompt: str, tui: Optional[TUIRenderer] = None, row: Optional[int] = None) -> Optional[str]:
    import ctypes
    from ctypes import wintypes

    buf: list[str] = []
    pos = 0
    sel = (-1, -1)
    hist = _HISTORY
    hidx = len(hist)
    kernel32 = ctypes.windll.kernel32
    edit_row = row
    _tab_matches: list[str] = []
    _tab_index = 0
    _last_tab_prefix = ""

    stdin_handle = kernel32.GetStdHandle(wintypes.DWORD(-10))
    stdout_handle = kernel32.GetStdHandle(wintypes.DWORD(-11))

    class _COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class _SMALL_RECT(ctypes.Structure):
        _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT),
                    ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]

    class _CSBI(ctypes.Structure):
        _fields_ = [("dwSize", _COORD), ("dwCursorPosition", _COORD),
                    ("wAttributes", wintypes.WORD), ("srWindow", _SMALL_RECT),
                    ("dwMaximumWindowSize", _COORD)]

    kernel32.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_CSBI)]
    kernel32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL
    kernel32.ReadConsoleInputW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]
    kernel32.ReadConsoleInputW.restype = wintypes.BOOL

    mode = wintypes.DWORD(0)
    saved_mode = 0
    mode_changed = False
    if kernel32.GetConsoleMode(stdin_handle, ctypes.byref(mode)):
        saved_mode = mode.value
        new_mode = (saved_mode & ~0x0047) | 0x0010 | 0x0080
        kernel32.SetConsoleMode(stdin_handle, new_mode)
        mode_changed = True

    # Position cursor at the input row if specified
    if edit_row is not None:
        sys.stdout.write(f"\033[{edit_row};1H")
    sys.stdout.write("\033[?25l" + prompt)
    sys.stdout.flush()
    prompt_col = 0
    csbi = _CSBI()
    if kernel32.GetConsoleScreenBufferInfo(stdout_handle, ctypes.byref(csbi)):
        prompt_col = csbi.dwCursorPosition.X

    def _redraw():
        base = "".join(buf)
        if sel[0] >= 0 and sel[0] < sel[1]:
            a, b = sel[0], sel[1]
            rendered = base[:a] + "\033[7m" + base[a:b] + "\033[0m" + base[b:]
        else:
            rendered = base
        out = ["\r\033[K", prompt, rendered]
        back = len(prompt) + len(base) - pos
        if back:
            out.append(f"\033[{back}D")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _finish(line: str) -> Optional[str]:
        if edit_row is not None:
            sys.stdout.write(f"\033[{edit_row};1H\r\033[K")
        else:
            sys.stdout.write("\033[1B\r\033[K")
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        line = line.rstrip()
        if line:
            hist.append(line)
            if len(hist) > _MAX_HISTORY:
                hist.pop(0)
        return line

    try:
        while True:
            raw_buf = ctypes.create_string_buffer(64)
            num = wintypes.DWORD(0)
            if not kernel32.ReadConsoleInputW(stdin_handle, ctypes.cast(raw_buf, wintypes.LPVOID),
                                              1, ctypes.byref(num)):
                return None
            ev = _parse_record(raw_buf.raw[:20])
            kind = ev[0]
            if kind == "key":
                down, repeat, vk, ch, state = ev[1], ev[2], ev[3], ev[4], ev[5]
                if not down:
                    continue
                oc = ord(ch)
                if oc == 0:
                    ch = ""
                if ch in ("\r", "\n"):
                    return _finish("".join(buf))
                if ch == "\x1b":
                    return None
                if ch == "\x01":
                    sel = (0, len(buf)) if buf else (-1, -1)
                    pos = len(buf)
                    _redraw()
                    continue
                if ch == "\x03":
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        _clipboard_copy("".join(buf[sel[0]:sel[1]]))
                        sel = (-1, -1)
                    else:
                        sys.stdout.write("\033[1B\r\033[K\033[1A^C\n")
                        sys.stdout.write("\033[?25h")
                        sys.stdout.flush()
                        return None
                    _redraw()
                    continue
                if ch == "\x16":
                    text = _clipboard_paste()
                    pos, sel = _replace_selection(buf, pos, sel, text)
                    _redraw()
                    continue
                if ch == "\x18":
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        _clipboard_copy("".join(buf[sel[0]:sel[1]]))
                        del buf[sel[0]:sel[1]]
                        pos = sel[0]
                        sel = (-1, -1)
                    _redraw()
                    continue
                if ch == "\x04":
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        del buf[sel[0]:sel[1]]
                        pos = sel[0]
                        sel = (-1, -1)
                    elif pos < len(buf):
                        buf.pop(pos)
                    _redraw()
                    continue
                if ch == "\x0b":
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        del buf[sel[0]:sel[1]]
                        pos = sel[0]
                        sel = (-1, -1)
                    else:
                        del buf[pos:]
                    _redraw()
                    continue
                if ch == "\x15":
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        del buf[sel[0]:sel[1]]
                        pos = sel[0]
                        sel = (-1, -1)
                    else:
                        del buf[:pos]
                        pos = 0
                    _redraw()
                    continue
                if ch == "\x17":
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        del buf[sel[0]:sel[1]]
                        pos = sel[0]
                        sel = (-1, -1)
                    else:
                        start = pos
                        while start > 0 and buf[start - 1].isspace():
                            start -= 1
                        while start > 0 and not buf[start - 1].isspace():
                            start -= 1
                        del buf[start:pos]
                        pos = start
                    _redraw()
                    continue
                if vk == _VK_BACK:
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        del buf[sel[0]:sel[1]]
                        pos = sel[0]
                        sel = (-1, -1)
                    else:
                        for _ in range(min(max(1, repeat), pos)):
                            buf.pop(pos - 1)
                            pos -= 1
                    _redraw()
                    continue
                if vk == _VK_DELETE:
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        del buf[sel[0]:sel[1]]
                        pos = sel[0]
                        sel = (-1, -1)
                    else:
                        for _ in range(min(max(1, repeat), len(buf) - pos)):
                            buf.pop(pos)
                    _redraw()
                    continue
                if vk == _VK_LEFT:
                    shift = bool(state & _SHIFT)
                    ctrl = bool(state & _CTRL)
                    if ctrl:
                        # word left
                        a = pos
                        while a > 0 and buf[a - 1].isspace():
                            a -= 1
                        while a > 0 and not buf[a - 1].isspace():
                            a -= 1
                        if shift and sel[0] >= 0 and sel[0] < sel[1]:
                            sel = (min(a, sel[0]), max(a, sel[1]))
                            pos = a
                        else:
                            pos = a
                            sel = (-1, -1)
                    elif shift:
                        if sel[0] >= 0 and sel[0] < sel[1]:
                            pos = sel[0]
                        else:
                            pos = max(0, pos - max(1, repeat))
                            sel = (pos, sel[1]) if sel[1] > pos else (pos, pos)
                    else:
                        if sel[0] >= 0 and sel[0] < sel[1]:
                            pos = sel[0]
                        else:
                            pos = max(0, pos - max(1, repeat))
                        sel = (-1, -1)
                    _redraw()
                    continue
                if vk == _VK_RIGHT:
                    shift = bool(state & _SHIFT)
                    ctrl = bool(state & _CTRL)
                    if ctrl:
                        # word right
                        b = pos
                        while b < len(buf) and not buf[b].isspace():
                            b += 1
                        while b < len(buf) and buf[b].isspace():
                            b += 1
                        if shift and sel[0] >= 0 and sel[0] < sel[1]:
                            sel = (min(sel[0], b), max(pos, b))
                            pos = b
                        else:
                            pos = b
                            sel = (-1, -1)
                    elif shift:
                        if sel[0] >= 0 and sel[0] < sel[1]:
                            pos = sel[1]
                        else:
                            pos = min(len(buf), pos + max(1, repeat))
                            sel = (sel[0], pos) if sel[0] < pos else (pos, pos)
                    else:
                        if sel[0] >= 0 and sel[0] < sel[1]:
                            pos = sel[1]
                        else:
                            pos = min(len(buf), pos + max(1, repeat))
                        sel = (-1, -1)
                    _redraw()
                    continue
                if vk in (_VK_HOME,):
                    shift = bool(state & _SHIFT)
                    if shift and sel[0] >= 0 and sel[0] < sel[1]:
                        pos = 0
                        sel = (0, sel[1])
                    else:
                        pos = 0
                        sel = (-1, -1)
                    _redraw()
                    continue
                if vk in (_VK_END,):
                    shift = bool(state & _SHIFT)
                    if shift and sel[0] >= 0 and sel[0] < sel[1]:
                        pos = len(buf)
                        sel = (sel[0], len(buf))
                    else:
                        pos = len(buf)
                        sel = (-1, -1)
                    _redraw()
                    continue
                if vk == _VK_UP:
                    if hidx > 0:
                        hidx -= 1
                        buf[:] = list(hist[hidx])
                        pos = len(buf)
                    sel = (-1, -1)
                    _redraw()
                    continue
                if vk == _VK_DOWN:
                    if hidx < len(hist):
                        hidx += 1
                        buf[:] = list(hist[hidx]) if hidx < len(hist) else []
                        pos = len(buf)
                    sel = (-1, -1)
                    _redraw()
                    continue
                if ch == "\t":
                    if buf and buf[0] == "/":
                        prefix = "".join(buf)
                        if prefix != _last_tab_prefix:
                            _tab_matches = [c for c in _visible_commands() if c.startswith(prefix)]
                            _tab_index = 0
                            _last_tab_prefix = prefix
                        if _tab_matches:
                            if len(_tab_matches) == 1:
                                buf[:] = list(_tab_matches[0] + " ")
                                pos = len(buf)
                            else:
                                match = _tab_matches[_tab_index % len(_tab_matches)]
                                buf[:] = list(match + " ")
                                pos = len(buf)
                                _tab_index += 1
                            if len(_tab_matches) > 1:
                                print("\n  " + "  ".join(_tab_matches))
                    else:
                        buf.insert(pos, " ")
                        pos += 1
                    sel = (-1, -1)
                    _redraw()
                    continue
                if oc and oc >= 32:
                    pos, sel = _replace_selection(buf, pos, sel, ch * repeat)
                    _redraw()
                    continue
                continue
            if kind == "mouse":
                mx, my, buttons, flags = ev[1], ev[2], ev[3], ev[5]
                in_msg_area = tui is not None and my >= tui.msg_start_y and my < tui.input_start_y
                in_input_area = tui is not None and my == (edit_row if edit_row is not None else tui.input_start_y + 1)
                if flags & _MOUSE_WHEELED:
                    if tui is not None and not in_input_area:
                        if buttons & 0x80000000:
                            tui.scroll_down(3)
                        else:
                            tui.scroll_up(3)
                        tui.render()
                        sys.stdout.flush()
                    continue
                if in_msg_area:
                    assert tui is not None
                    if buttons & _MS_LEFT and (flags & _MOUSE_MOVED) == 0:
                        tui.select_at(my)
                        tui.render()
                        sys.stdout.flush()
                    elif buttons & _MS_LEFT and (flags & _MOUSE_MOVED):
                        tui.select_at(my)
                        tui.render()
                        sys.stdout.flush()
                    continue
                if buttons & _MS_RIGHT:
                    text = _clipboard_paste()
                    if text:
                        pos, sel = _replace_selection(buf, pos, sel, text)
                    _redraw()
                    continue
                if flags & _MOUSE_DOUBLE_CLICK:
                    idx = max(0, mx - prompt_col)
                    a, b = _word_bounds(buf, idx)
                    sel = (a, b) if a < b else (-1, -1)
                    pos = b if a < b else idx
                    if sel[0] >= 0 and sel[0] < sel[1]:
                        _clipboard_copy("".join(buf[sel[0]:sel[1]]))
                        sel = (-1, -1)
                    _redraw()
                    continue
                if buttons & _MS_LEFT:
                    idx = max(0, min(len(buf), mx - prompt_col))
                    pos = idx
                    sel = (-1, -1)
                    _redraw()
                    continue
            continue
    finally:
        if mode_changed:
            kernel32.SetConsoleMode(stdin_handle, saved_mode)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def _line_input(prompt: str = "", tui: Optional[TUIRenderer] = None, row: Optional[int] = None) -> Optional[str]:
    """Read a line. Uses a custom editor on a Windows console; plain input() elsewhere."""
    inp = builtins.input
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if isinstance(inp, types.BuiltinFunctionType) and interactive and os.name == "nt":
        return _msvcrt_edit(prompt, tui, row)
    if interactive:
        try:
            import readline
            readline.set_completer(_readline_completer)
            readline.parse_and_bind("tab: complete")
        except ImportError:
            pass
    try:
        return inp(prompt)
    except (EOFError, KeyboardInterrupt):
        return None
    finally:
        try:
            import readline
            readline.set_completer(None)
        except ImportError:
            pass


def _readline_completer(text: str, state: int) -> Optional[str]:
    """Readline tab-completion callback for slash commands."""
    if not text.startswith("/"):
        return None
    options = [c for c in _visible_commands() if c.startswith(text)]
    if state < len(options):
        return options[state]
    return None


def _read_prompt(prompt: str, tui: Optional[TUIRenderer] = None) -> Optional[str]:
    """Read a prompt with multi-line continuation."""
    lines: list[str] = []
    row = None
    if tui is not None:
        row = tui.input_start_y + 1  # input line is below the top border of the input area
    while True:
        line = _line_input(prompt if not lines else "...> ", tui, row)
        if line is None:
            return None if not lines else "\n".join(lines)
        if line.endswith("\\"):
            lines.append(line[:-1])
            if row is not None:
                row += 1
            continue
        lines.append(line)
        return "\n".join(lines)


# ---------- generation ----------

def _show_thinking(text: str, st: dict, tui: Optional[TUIRenderer] = None):
    if not text:
        return
    if tui is not None:
        tui.add("thinking", text[:600])
        tui.render()
        return
    if st["show_thinking"]:
        border = _g("\u2500", "-")
        print(_thinking_color(f"  {border} thinking {border}"))
        print(_dim(text[:600]))
        if len(text) > 600:
            print(_dim(f"  {border} {len(text) - 600} more chars {border}"))
    else:
        print(_thinking_color(f"  [thinking] {len(text)} chars"))


def _ask_stream(orch: Orchestrator, st: dict, kwargs: dict, tui: Optional[TUIRenderer] = None):
    gen = orch.stream(**kwargs)
    start = time.time()
    parts = []
    model = None
    try:
        for evt in gen:
            t = evt.get("type")
            if t == "start":
                model = evt.get("model")
                if tui is not None:
                    tui.add("assistant", "", model=model)
                    tui.render()
                else:
                    print(_accent(f"  ▸ {model}"))
            elif t == "thinking":
                _show_thinking(evt.get("content") or "", st, tui)
            elif t == "response":
                chunk = evt.get("content") or ""
                if chunk:
                    parts.append(chunk)
                    if tui is not None and tui.messages and tui.messages[-1].role == "assistant":
                        tui.messages[-1].content += chunk
                        tui.render()
                    else:
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
            elif t == "error":
                if tui is not None and tui.messages and tui.messages[-1].role == "assistant":
                    tui.messages[-1].content = _red(f"[Error] {evt.get('content')}")
                    tui.render()
                else:
                    print(_red(f"\n[Error] {evt.get('content')}"))
                return
    except KeyboardInterrupt:
        gen.close()
        if tui is not None and tui.messages and tui.messages[-1].role == "assistant":
            tui.messages[-1].content += _yellow("\n[Stopped]")
            tui.render()
        else:
            print(_yellow("\n[Stopped]"))
        return
    text = "".join(parts)
    st["tokens"] += len(text.split())
    elapsed = time.time() - start
    tps = (len(text.split()) / elapsed) if elapsed > 0 else 0.0
    if tui is not None and tui.messages and tui.messages[-1].role == "assistant":
        tui.messages[-1].elapsed = elapsed
        tui.messages[-1].tokens = len(text.split())
        tui.render()
    else:
        print()
        print(_accent(f"  [{model or st['last_model']}") + _dim(" · ") + _muted(f"{len(text.split())} tok") + _dim(" · ") + _muted(f"{tps:.1f} tps") + _dim(" · ") + _muted(f"{elapsed:.1f}s") + _accent("]"))


def _ask_parallel(orch: Orchestrator, st: dict, kwargs: dict, tui: Optional[TUIRenderer] = None):
    start = time.time()
    try:
        result = orch.run(parallel=True, **kwargs)
    except Exception as e:
        if tui is not None:
            tui.add("system", _red(f"[Error] {e}"))
            tui.render()
        else:
            print(_red(f"[Error] {e}"))
        return
    thinking = result.get("thinking") or ""
    response = result.get("response") or ""
    model = result.get("model") or st.get("last_model") or "unknown"
    _show_thinking(thinking, st)
    if tui is not None:
        tui.add("assistant", response, model=model, elapsed=time.time() - start, tokens=len(response.split()))
        tui.render()
    else:
        print(_assistant_color(response))
    st["tokens"] += len(response.split())
    extra = f"model={model}"
    candidates = result.get("parallel_candidates")
    if candidates:
        try:
            n = candidates if isinstance(candidates, int) else len(candidates)
            extra += f" candidates={n}"
        except Exception:
            pass
    if tui is None:
        print(_dim(f"  [{extra}") + _dim(" · ") + _muted(f"{time.time() - start:.1f}s") + _dim(" · ") + _muted(f"{st['tokens']} tok") + _dim("]"))


def _ask(orch: Orchestrator, st: dict, system_override: Optional[str] = None, tui: Optional[TUIRenderer] = None):
    kwargs = dict(
        user_message=st["last_prompt"],
        conv_id=st["conv_id"],
        use_planning=st["planning"],
        system_override=system_override,
        temperature=st["temperature"],
        max_tokens=st["max_tokens"],
    )
    if st["parallel"]:
        _ask_parallel(orch, st, kwargs, tui)
    else:
        _ask_stream(orch, st, kwargs, tui)


# ---------- commands ----------

def _handle_command(line: str, orch: Orchestrator, mm: ModelManager, mem: MemoryManager, st: dict):
    parts = _split_args(line)
    cmd = parts[0].lower()

    if not _command_allowed(cmd):
        print(f"Blocked: '{parts[0]}' is not in the CLI command whitelist.")
        return

    if cmd in ("/exit", "/quit"):
        print("Goodbye!")
        return "exit"
    if cmd in ("/help", "/?"):
        print(HELP_TEXT)
        return
    if cmd == "/status":
        print(_hud(st, mm))
        print(f"  Models loaded: {', '.join(mm.instances.keys()) or 'none'}")
        print(f"  VRAM: ~{mm.vram_used()} MB used / {CONFIG.vram_budget_mb or 'auto'} MB budget")
        print(f"  Threads: {CONFIG.threads}  GPU: {CONFIG.gpu_name}  "
              f"DB: {'ON' if CONFIG.db.enabled else 'off'}  Cloud: {CONFIG.cloud_provider or 'none'}")
        print(f"  Gen timeout: {CONFIG.gen_timeout_s}s  Harness epsilon: {CONFIG.harness_epsilon}  "
              f"Parallel max: {CONFIG.parallel_max}")
        print(f"  Session tokens: {st['tokens']}  Conversations: {len(mem.conversations)}")
        return
    if cmd == "/clear":
        mem.delete(st["conv_id"])
        print("Cleared.")
        return
    if cmd == "/debug":
        if len(parts) > 1:
            level = parts[1].lower()
            if level in ("on", "1", "true"):
                logging.getLogger().setLevel(logging.DEBUG)
                print("Debug logging: ON")
            else:
                logging.getLogger().setLevel(logging.INFO)
                print("Debug logging: OFF")
        else:
            current = logging.getLogger().level
            print(f"Debug logging: {'ON' if current <= logging.DEBUG else 'OFF'} (level={logging.getLevelName(current)})")
        return
    if cmd == "/plan":
        if len(parts) > 1:
            st["planning"] = parts[1].lower() == "on"
        else:
            st["planning"] = not st["planning"]
        print(f"Planning: {'ON' if st['planning'] else 'OFF'}")
        return
    if cmd == "/think":
        if len(parts) > 1:
            st["show_thinking"] = parts[1].lower() == "on"
        else:
            st["show_thinking"] = not st["show_thinking"]
        print(f"Show thinking: {'ON' if st['show_thinking'] else 'OFF'}")
        return
    if cmd == "/models":
        for name, mc in mm.configs.items():
            loaded = " [loaded]" if name in mm.instances else ""
            caps = getattr(mc, "capabilities", [])
            cap_str = f" [{', '.join(caps)}]" if caps else ""
            print(f"  {name} ({mc.role}){loaded}{cap_str}")
            print(f"    ctx={mc.n_ctx} temp={mc.temperature} max={mc.max_tokens}")
        if CONFIG.openai.enabled:
            print(f"  openai/{CONFIG.openai.chat_model} (cloud)")
        return
    if cmd == "/model":
        if len(parts) > 1:
            if parts[1] in mm.configs:
                orch.executor = parts[1]
                st["last_model"] = parts[1]
                print(f"Model: {parts[1]}")
            else:
                print(f"Unknown model. Available: {list(mm.configs.keys())}")
        else:
            print(f"Current: {orch.executor}")
        return
    if cmd == "/preload":
        if len(parts) < 2:
            print("Usage: /preload <model>")
        else:
            try:
                mm.load(parts[1])
                print(f"Loaded: {parts[1]}")
            except Exception as e:
                print(f"Load failed: {e}")
        return
    if cmd == "/unload":
        if len(parts) > 1:
            if parts[1] in mm.instances:
                mm.unload(parts[1])
                print(f"Unloaded: {parts[1]}")
            else:
                print(f"Not loaded: {parts[1]}")
        else:
            if mm.instances:
                for n in list(mm.instances.keys()):
                    mm.unload(n)
                print("All models unloaded.")
            else:
                print("Nothing loaded.")
        return
    if cmd == "/openai":
        if len(parts) > 1:
            CONFIG.openai.api_key = parts[1]
            CONFIG.openai.enabled = True
            print("OpenAI API key set")
        else:
            print("Usage: /openai <key>")
        return
    if cmd == "/db":
        if len(parts) <= 1:
            CONFIG.db.enabled = not CONFIG.db.enabled
        elif parts[1].lower() == "on":
            CONFIG.db.enabled = True
        elif parts[1].lower() == "off":
            CONFIG.db.enabled = False
        elif parts[1].lower() == "stats":
            try:
                import database as db
                stats = db.count_memories()
                print(f"  Memories: {stats}")
                if db.get_pool():
                    print("  Pool: active")
                else:
                    print("  Pool: disconnected")
            except Exception as e:
                print(f"  DB stats failed: {e}")
            return
        elif parts[1].lower() == "clear":
            try:
                import database as db
                db.clear_memories()
                print("  All memories cleared")
            except Exception as e:
                print(f"  Clear failed: {e}")
            return
        elif parts[1].lower() == "search":
            if len(parts) > 2:
                query = " ".join(parts[2:])
                try:
                    import database as db
                    results = db.retrieve_similar(query, limit=5)
                    if results:
                        for i, thought in enumerate(results, 1):
                            print(f"  {i}. {thought[:80]}")
                    else:
                        print("  No results found")
                except Exception as e:
                    print(f"  Search failed: {e}")
            else:
                print("Usage: /db search <query>")
            return
        elif parts[1].lower() == "tables":
            try:
                import database as db
                pool = db.get_pool()
                if pool:
                    conn = pool.getconn()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema = 'public'"
                            )
                            tables = cur.fetchall()
                            for t in tables:
                                name = t[0] if isinstance(t, tuple) else t
                                cur.execute(f"SELECT COUNT(*) FROM {name}")  # nosec B608
                                count = cur.fetchone()[0]
                                print(f"  {name}: {count} rows")
                    finally:
                        pool.putconn(conn)
                else:
                    print("  Database not connected")
            except Exception as e:
                print(f"  Tables query failed: {e}")
            return
        elif parts[1].lower() == "index":
            try:
                import database as db
                pool = db.get_pool()
                if pool:
                    conn = pool.getconn()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT indexname FROM pg_indexes "
                                "WHERE tablename = 'agent_memory'"
                            )
                            indexes = cur.fetchall()
                            if indexes:
                                for idx in indexes:
                                    name = idx[0] if isinstance(idx, tuple) else idx
                                    print(f"  {name}")
                            else:
                                print("  No indexes on agent_memory")
                    finally:
                        pool.putconn(conn)
                else:
                    print("  Database not connected")
            except Exception as e:
                print(f"  Index query failed: {e}")
            return
        print(f"Database memory: {'ON' if CONFIG.db.enabled else 'OFF'}")
        return
    if cmd == "/parallel":
        if len(parts) > 1:
            st["parallel"] = parts[1].lower() == "on"
        else:
            st["parallel"] = not st["parallel"]
        mode = "ensemble + judge" if st["parallel"] else "live streaming"
        print(f"Parallel: {'ON' if st['parallel'] else 'OFF'}  ({mode})")
        return
    if cmd == "/prune":
        try:
            import database as db
            deleted = db.prune_memories(CONFIG.prune_max_age_days)
            print(f"Pruned {deleted} old memories")
        except Exception as e:
            print(f"Prune failed: {e}")
        return
    if cmd == "/code":
        if len(parts) > 1:
            st["coding"] = parts[1].lower() == "on"
        else:
            st["coding"] = not st["coding"]
        st["agent"] = "agent_x" if st["coding"] else agents.DEFAULT_AGENT
        print(f"Coding agent: {'ON' if st['coding'] else 'OFF'} (agent: {st['agent']})")
        return
    if cmd == "/computer":
        sub = parts[1].lower() if len(parts) > 1 else ""
        if sub == "tools":
            agent = create_computer_agent(mm, orch, sandbox=st.get("computer_sandbox", False),
                                          allow_gui=bool(CONFIG.computer.get("allow_gui")))
            print(_cyan("  Computer Agent Tools:"))
            for t in agent.registry.list_tools():
                safe = " [sandbox-safe]" if t.sandbox_safe else ""
                print(f"    {t.name}{safe}: {t.description}")
            return
        if sub == "sandbox":
            if len(parts) > 2:
                st["computer_sandbox"] = parts[2].lower() in ("on", "true", "1")
            else:
                st["computer_sandbox"] = not st.get("computer_sandbox", False)
            mode = "ON (read-only)" if st.get("computer_sandbox") else "OFF (full access)"
            print(f"Computer sandbox: {mode}")
            return
        if sub == "gui":
            if len(parts) > 2:
                CONFIG.computer["allow_gui"] = parts[2].lower() in ("on", "true", "1")
            else:
                CONFIG.computer["allow_gui"] = not bool(CONFIG.computer.get("allow_gui"))
            mode = "ON (mouse+keyboard)" if CONFIG.computer.get("allow_gui") else "OFF"
            print(f"Computer GUI tools: {mode}")
            return
        if sub in ("cancel", "stop"):
            if "_computer_agent" in st and st["_computer_agent"] is not None:
                st["_computer_agent"].cancel()
                print(_yellow("Cancelling computer agent..."))
            else:
                print("No computer agent running.")
            return
        goal = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not goal:
            print("Usage: /computer <goal>")
            print("  e.g. /computer find all Python files and count lines of code")
            print("  /computer tools        list available tools")
            print("  /computer sandbox on   enable read-only mode")
            return
        sandbox = st.get("computer_sandbox", False)
        agent = create_computer_agent(mm, orch, sandbox=sandbox,
                                      allow_gui=bool(CONFIG.computer.get("allow_gui")))
        st["_computer_agent"] = agent
        mode_label = _warning_color("SANDBOX") if sandbox else _success_color("FULL ACCESS")
        print(_accent(f"\n  Computer Agent [{mode_label}]") + _dim(" · ") + _muted(f"Goal: {goal}"))
        print(_dim("  Ctrl+C to cancel\n"))

        def _agent_callback(step):
            icon = _success_color("OK") if step.tool_result and step.tool_result.success else _error_color("ERR")
            args_str = ""
            if step.tool_args:
                args_str = str(step.tool_args)[:120]
            print(_dim(f"  [{step.step_num}] ") + f"{step.tool_name} {args_str} [" + icon + _dim("] ") + _muted(f"{step.elapsed_s:.1f}s"))

        try:
            agent_result = agent.run(goal, callback=_agent_callback)
            print()
            print(_success_color("  " + "=" * 60))
            print(_success_color(f"  RESULT ({len(agent_result.steps)} steps, {agent_result.total_elapsed_s:.1f}s):"))
            print(_success_color("  " + "=" * 60))
            for ans_line in agent_result.final_answer.split("\n"):
                print(f"  {ans_line}")
            print()
        except KeyboardInterrupt:
            agent.cancel()
            print(_warning_color("\n  [Cancelled]"))
        except Exception as e:
            print(_error_color(f"\n  [Error] {e}"))
        finally:
            st.pop("_computer_agent", None)
        return
    if cmd == "/agent" and len(parts) > 1 and parts[1] == "add":
        if len(parts) < 5:
            print("Usage: /agent add <name> \"<description>\" \"<system_prompt>\" [role]")
            return
        try:
            agents.add_agent(name=parts[2], system_prompt=parts[4],
                             description=parts[3],
                             role=parts[5] if len(parts) > 5 else "")
            print(f"Agent added: {parts[2]}")
        except Exception as e:
            print(f"Failed to add agent: {e}")
        return
    if cmd == "/agent" and len(parts) > 1 and parts[1] in ("del", "delete", "rm"):
        if len(parts) < 3:
            print("Usage: /agent delete <name>")
        else:
            print(f"Agent deleted: {parts[2]}" if agents.delete_agent(parts[2])
                  else f"Agent '{parts[2]}' not found or is built-in")
        return
    if cmd == "/agent":
        if len(parts) > 1:
            a = agents.get_agent(parts[1])
            if a is None:
                print(f"Unknown agent '{parts[1]}'. Available: {', '.join(agents.list_agents())}")
            else:
                st["agent"] = a["name"]
                st["coding"] = a["name"] == "agent_x"
                print(f"Agent: {a['name']} ({a['role']})\n  {a['description']}")
        else:
            a = agents.get_agent(st["agent"])
            role = a["role"] if a else "unknown"
            print(f"Current agent: {st['agent']} ({role})")
        return
    if cmd == "/agents":
        for agent_name in agents.list_agents():
            agent_data = agents.get_agent(agent_name)
            if agent_data is None:
                continue
            cur = "  *" if agent_name == st["agent"] else ""
            print(f"  {agent_name}  {agent_data['role']}{cur}")
        print("\n  Switch with /agent <name>")
        print("  Add with /agent add <name> \"<description>\" \"<system_prompt>\" [role]")
        return
    if cmd == "/mcp":
        sub = parts[1].lower() if len(parts) > 1 else "list"
        if sub == "call":
            if len(parts) < 4:
                print("Usage: /mcp call <tool> <input text>")
                return
            tool_name = parts[2]
            tool_input = " ".join(parts[3:])
            print(f"  Calling MCP tool '{tool_name}'...")
            try:
                if tool_name == "chat":
                    result = orch.run(user_message=tool_input, conv_id=f"mcp-cli-{uuid.uuid4().hex[:8]}", use_planning=True)
                    print(f"\n{_green('Response:')}\n{result['response']}")
                elif tool_name in agents.AGENTS:
                    a = agents.get_agent(tool_name)
                    if a is None:
                        print(f"Unknown tool '{tool_name}'")
                        return
                    result = orch.run(user_message=tool_input, conv_id=f"mcp-cli-{uuid.uuid4().hex[:8]}",
                                       use_planning=True, system_override=a["system_prompt"])
                    print(f"\n{_green('Response:')}\n{result['response']}")
                elif tool_name in agents.SKILLS:
                    rendered = agents.render_skill(tool_name, tool_input)
                    if rendered is None:
                        print(f"Unknown tool '{tool_name}'")
                        return
                    result = orch.run(user_message=rendered["prompt"], conv_id=f"mcp-cli-{uuid.uuid4().hex[:8]}",
                                       use_planning=False, system_override=rendered["system_prompt"])
                    print(f"\n{_green('Response:')}\n{result['response']}")
                else:
                    print(f"Unknown tool '{tool_name}'. Use /mcp list to see available tools.")
            except Exception as e:
                print(f"MCP call failed: {e}")
            return
        if sub == "json":
            tools = ["chat"] + agents.list_agents() + agents.list_skills()
            tool_list: list = []
            for tname in tools:
                entry: dict = {"name": tname}
                if tname == "chat":
                    entry["description"] = "Chat with the AI assistant"
                    entry["inputSchema"] = {"type": "object", "properties": {"input": {"type": "string"}}}
                elif tname in agents.AGENTS:
                    a = agents.get_agent(tname)
                    entry["description"] = a["description"] if a else ""
                    entry["inputSchema"] = {"type": "object", "properties": {"input": {"type": "string"}}}
                elif tname in agents.SKILLS:
                    s = agents.get_skill(tname)
                    entry["description"] = s["description"] if s else ""
                    entry["inputSchema"] = {"type": "object", "properties": {"input": {"type": "string"}}}
                tool_list.append(entry)
            print(json.dumps({"tools": tool_list}, indent=2))
            return
        # Default: list tools with descriptions
        tools = ["chat"] + agents.list_agents() + agents.list_skills()
        print(f"\n  {_bold(_accent('MCP Tools'))} ({len(tools)}):")
        print(f"  {_muted('chat')}  - " + _dim("Chat with the AI assistant (orchestrator pipeline)"))
        for tool_name in agents.list_agents():
            a = agents.get_agent(tool_name)
            desc = a["description"] if a else ""
            print(f"  {_user_color(tool_name)}  - {desc}")
        for tool_name in agents.list_skills():
            s = agents.get_skill(tool_name)
            desc = s["description"] if s else ""
            params = ", ".join(p["name"] for p in s.get("params", [])) if s and s.get("params") else ""
            param_str = f" [{params}]" if params else ""
            print(f"  {_success_color(tool_name)}{param_str}  - {desc}")
        print(f"\n  {_dim('Call a tool:')}  /mcp call <tool> <input text>")
        print(f"  {_dim('JSON output:')}  /mcp json")
        print(_dim("  Each skill/agent you add becomes an MCP tool automatically."))
        return
    if cmd == "/skills":
        for n in agents.list_skills():
            s = agents.get_skill(n)
            if s is None:
                continue
            params = " (" + ", ".join(p["name"] for p in s.get("params", [])) + ")" if s.get("params") else ""
            print(f"  {n}{params}  - {s['description']}")
        print("\n  Run with /skill <name> <text>")
        print("  Add with /skill add <name> \"<description>\" \"<template with {input}>\" [system_prompt]")
        return
    if cmd == "/skill" and len(parts) > 1 and parts[1] == "add":
        if len(parts) < 5:
            print("Usage: /skill add <name> \"<description>\" \"<template with {input}>\" [system_prompt]")
            return
        try:
            agents.add_skill(name=parts[2], template=parts[4],
                             description=parts[3],
                             system_prompt=parts[5] if len(parts) > 5 else "")
            print(f"Skill added: {parts[2]}")
        except Exception as e:
            print(f"Failed to add skill: {e}")
        return
    if cmd == "/skill" and len(parts) > 1 and parts[1] in ("del", "delete", "rm"):
        if len(parts) < 3:
            print("Usage: /skill delete <name>")
        else:
            print(f"Skill deleted: {parts[2]}" if agents.delete_skill(parts[2])
                  else f"Skill '{parts[2]}' not found or is built-in")
        return
    if cmd == "/skill":
        if len(parts) < 3:
            print("Usage: /skill <name> <text to process>   (see /skills)")
        else:
            skill_name = parts[1]
            rendered = agents.render_skill(skill_name, " ".join(parts[2:]))
            if rendered is None:
                print(f"Unknown skill '{skill_name}'. Available: {', '.join(agents.list_skills())}")
                return
            st["last_prompt"] = rendered["prompt"]
            _ask(orch, st, system_override=rendered["system_prompt"])
        return
    if cmd == "/harness":
        sub = parts[1].lower() if len(parts) > 1 else "stats"
        if sub == "reset":
            orch.router.harness.reset()
            print("Harness reset: all scores cleared, generation=0")
            return
        if sub == "adjust":
            if len(parts) < 5:
                print("Usage: /harness adjust <task> <model> <score>")
                print("  e.g. /harness adjust code hy-mt2 85.0")
                return
            task_name = parts[2]
            model_name = parts[3]
            try:
                score_val = float(parts[4])
            except ValueError:
                print("Score must be a number (0-100)")
                return
            orch.router.harness.adjust(task_name, model_name, score_val)
            print(f"Set {task_name}/{model_name} score to {score_val}")
            return
        if sub == "export":
            state = orch.router.harness.export_stats()
            path = os.path.join(BASE_DIR, "harness_state.json")
            with open(path, "w") as f:
                json.dump(state, f, indent=2)
            print(f"Exported harness state to {path}")
            return
        if sub == "import":
            path = os.path.join(BASE_DIR, "harness_state.json")
            if not os.path.exists(path):
                print(f"No harness_state.json found at {path}")
                return
            with open(path) as f:
                state = json.load(f)
            orch.router.harness.import_stats(state)
            print(f"Imported harness state: generation={state.get('generation', 0)}")
            return
        # Default: show stats
        harness_stats = orch.router.harness.stats()
        print(f"Harness: generation={harness_stats['generation']} epsilon={harness_stats['epsilon']}")
        data = harness_stats.get("data", {})
        if data:
            print(f"  {_muted('Task/Model'):<25} {_accent('Score'):>6} {_muted('Attempts'):>8} {_muted('Errors'):>6} {_muted('Avg Lat'):>8} {_muted('Tokens'):>7}")
            print(f"  {_muted('-'*25)} {_muted('-'*6)} {_muted('-'*8)} {_muted('-'*6)} {_muted('-'*8)} {_muted('-'*7)}")
            for k, v in sorted(data.items(), key=lambda x: -x[1]["score"]):
                score_val = v['score']
                print(f"  {k:<25} {_success_color(f'{score_val:>6.1f}')} {v['attempts']:>8} {v['errors']:>6} "
                      f"{v['avg_latency']:>7.2f}s {v['tokens']:>7}")
        else:
            print(f"  {_dim('No model feedback yet. Use the system to generate responses.')}")
        print(f"\n  {_dim('Subcommands:')} stats (default), reset, adjust, export, import")
        return
    if cmd == "/cloud":
        if len(parts) > 1:
            preset = CLOUD_PRESETS.get(parts[1].lower())
            if preset:
                CONFIG.openai.base_url = preset["base_url"]
                CONFIG.openai.chat_model = preset["chat_model"]
                CONFIG.cloud_provider = parts[1].lower()
                print(f"Cloud preset: {parts[1].lower()} ({preset['chat_model']}) "
                      f"- set a key with /openai <key>")
            else:
                print(f"Unknown preset. Available: {', '.join(CLOUD_PRESETS)}")
        else:
            print(f"Current cloud: {CONFIG.cloud_provider or 'none'} "
                  f"[{', '.join(CLOUD_PRESETS)}]")
        return
    if cmd == "/arc":
        import arc
        try:
            arc_limit = int(parts[1]) if len(parts) > 1 else 3
        except ValueError:
            arc_limit = 3
        res = arc.run_arc_eval(model_manager=mm, limit=arc_limit)
        if not res.get("dataset"):
            print(f"ARC: {res.get('note', 'dataset not found')}")
        else:
            print(f"ARC eval ({res.get('model')}): {res.get('correct')}/{res.get('total')} "
                  f"({res.get('accuracy', 0) * 100:.0f}%)")
        return
    if cmd == "/context":
        conv = mem.get_or_create(st["conv_id"])
        sub = parts[1].lower() if len(parts) > 1 else "show"
        if sub == "show":
            if conv.system_prompt:
                print(f"  System: {conv.system_prompt}")
            else:
                print("  System: (default)")
            print(f"  Messages: {len(conv.messages)}")
            for m in conv.messages[-5:]:
                preview = m.content.replace("\n", " ")[:90]
                print(f"    {m.role}: {preview}")
        elif sub in ("set", "system"):
            if len(parts) < 3:
                print(f"Usage: /context {sub} <system prompt text>")
            else:
                conv.set_system(" ".join(parts[2:]))
                print("Context system prompt set.")
        elif sub in ("clear", "reset"):
            conv.set_system("")
            print("Context cleared (system prompt reset to default).")
        else:
            print("Usage: /context show|set <text>|clear")
        return
    if cmd in ("/temperature", "/temp"):
        if len(parts) > 1:
            try:
                t = float(parts[1])
                st["temperature"] = None if t < 0 else min(2.0, t)
                print(f"Temperature: {st['temperature']}")
            except ValueError:
                print("Usage: /temperature <0-2>")
        else:
            print(f"Temperature: {st['temperature'] if st['temperature'] is not None else 'default'}")
        return
    if cmd in ("/max", "/max-tokens"):
        if len(parts) > 1:
            try:
                max_tok = int(parts[1])
                st["max_tokens"] = None if max_tok <= 0 else min(8192, max_tok)
                print(f"Max tokens: {st['max_tokens'] or 'default'}")
            except ValueError:
                print("Usage: /max <tokens>")
        else:
            print(f"Max tokens: {st['max_tokens'] or 'default'}")
        return
    if cmd == "/timeout":
        if len(parts) > 1:
            try:
                timeout_val = float(parts[1])
                CONFIG.gen_timeout_s = max(5.0, timeout_val)
                print(f"Gen timeout: {CONFIG.gen_timeout_s}s")
            except ValueError:
                print("Usage: /timeout <seconds>")
        else:
            print(f"Gen timeout: {CONFIG.gen_timeout_s}s")
        return
    if cmd in ("/retry", "!!"):
        if not st["last_prompt"]:
            print("Nothing to retry yet.")
        else:
            _ask(orch, st)
        return
    if cmd == "/new":
        st["conv_id"] = f"cli-{int(time.time())}"
        st["tokens"] = 0
        st["last_prompt"] = ""
        print("New conversation started.")
        return
    if cmd == "/save":
        name = parts[1] if len(parts) > 1 else "default"
        _save_session(name, mem, st["conv_id"], st)
        print(f"Session saved: {name}")
        return
    if cmd == "/load":
        if len(parts) < 2:
            print("Usage: /load <name>   (see /sessions)")
        else:
            data = _load_session(parts[1], mem)
            if data is None:
                print(f"No session named '{parts[1]}'")
            else:
                st["conv_id"] = f"session:{parts[1]}"
                s = data.get("state") or {}
                st["tokens"] = s.get("tokens", 0)
                st["temperature"] = s.get("temperature")
                st["max_tokens"] = s.get("max_tokens", 2048)
                st["last_prompt"] = s.get("last_prompt", "")
                if "agent" in s:
                    st["agent"] = s["agent"]
                if "planning" in s:
                    st["planning"] = s["planning"]
                if "parallel" in s:
                    st["parallel"] = s["parallel"]
                if "coding" in s:
                    st["coding"] = s["coding"]
                if "last_model" in s:
                    st["last_model"] = s["last_model"]
                print(f"Session loaded: {parts[1]} ({len(data.get('messages', []))} messages)")
        return
    if cmd == "/sessions":
        names = _list_sessions()
        if names:
            for n in names:
                print(f"  {n}")
        else:
            print("No saved sessions.")
        return
    if cmd == "/tokens":
        print(f"Session tokens: {st['tokens']}")
        return
    if cmd == "/vram":
        if mm.instances:
            for n in mm.configs:
                if n in mm.instances:
                    print(f"  {n}: ~{mm.get_vram_estimate(n)} MB")
        else:
            print("  No models loaded.")
        print(f"  Total: ~{mm.vram_used()} MB / {CONFIG.vram_budget_mb or 'auto'} MB")
        return
    if cmd in ("/exec", "/shell"):
        if len(parts) < 2:
            print("Usage: /exec <shell command>  (or !command)")
        else:
            _run_shell(" ".join(parts[1:]))
        return
    if cmd == "/lora":
        if len(parts) < 2:
            print("Usage: /lora <list|enable|disable|import|train|delete> ...")
            return
        sub = parts[1].lower()
        if sub == "list":
            from lora_manager import list_adapters
            adapters = list_adapters()
            if not adapters:
                print("No LoRA adapters found in loras/")
            else:
                for adapter in adapters:
                    status = "ON" if adapter.enabled else "off"
                    print(f"  {adapter.name}  base={adapter.base_model or 'any'}  scale={adapter.scale}  [{status}]")
        elif sub == "enable":
            if len(parts) < 3:
                print("Usage: /lora enable <name> [model]")
            else:
                from lora_manager import enable_adapter
                model = parts[3] if len(parts) > 3 else ""
                if enable_adapter(parts[2], model):
                    print(f"LoRA enabled: {parts[2]} for model {model or 'auto'}")
                else:
                    print(f"LoRA not found: {parts[2]}")
        elif sub == "disable":
            if len(parts) < 3:
                print("Usage: /lora disable <name>")
            else:
                from lora_manager import disable_adapter
                disable_adapter(parts[2])
                print(f"LoRA disabled: {parts[2]}")
        elif sub == "import":
            if len(parts) < 3:
                print("Usage: /lora import <path> [name]")
            else:
                from lora_manager import import_adapter
                name = parts[3] if len(parts) > 3 else ""
                imported_adapter = import_adapter(parts[2], name)
                if imported_adapter is not None:
                    print(f"LoRA imported: {imported_adapter.name}")
                else:
                    print("LoRA import failed")
        elif sub == "train":
            if len(parts) < 5:
                print("Usage: /lora train <base_model> <dataset.txt> <output_name> [epochs]")
            else:
                from lora_manager import train_lora
                try:
                    epochs = int(parts[5]) if len(parts) > 5 else 3
                except ValueError:
                    epochs = 3
                out_name = parts[4]
                out = train_lora(parts[2], parts[3], out_name, epochs=epochs)
                if out:
                    print(f"LoRA trained: {out}")
                else:
                    print("LoRA training failed (missing peft/datasets?)")
        elif sub == "delete":
            if len(parts) < 3:
                print("Usage: /lora delete <name>")
            else:
                from lora_manager import delete_adapter
                if delete_adapter(parts[2]):
                    print(f"LoRA deleted: {parts[2]}")
                else:
                    print(f"LoRA not found: {parts[2]}")
        else:
            print("Unknown /lora subcommand")
        return

    from difflib import get_close_matches
    suggestions = get_close_matches(cmd, _COMMANDS, n=3, cutoff=0.6)
    print(_error_color(f"Unknown: {cmd}"))
    if suggestions:
        print(f"  Did you mean: {_accent(', '.join(suggestions))}?")
    else:
        print(f"  Type {_accent('/help')} for the full command list.")
    return


# ---------- main loop ----------

def main(model_manager=None):
    _enable_utf8()
    _init_color()
    if model_manager is None:
        mm = ModelManager()
    else:
        mm = model_manager
    mem = MemoryManager()
    orch = Orchestrator(mm, mem)

    st = {
        "planning": True,
        "show_thinking": True,
        "parallel": False,
        "coding": False,
        "agent": "general",
        "conv_id": "cli-session",
        "temperature": None,
        "max_tokens": 2048,
        "last_prompt": "",
        "tokens": 0,
        "last_model": orch.executor,
    }

    if not CONFIG.db.enabled:
        try:
            import database as db
            db.enable_if_available()
        except Exception:
            pass

    if CONFIG.db.enabled:
        try:
            import database as db
            conn = db.get_connection()
            if conn is not None:
                db.put_connection(conn)
        except Exception:
            pass

    print(WELCOME)
    tui = TUIRenderer()
    tui.render()

    while True:
        try:
            tui.render()
            line = _read_prompt(_prompt(), tui)
        except KeyboardInterrupt:
            print(_muted("\n👋 Goodbye!"))
            break
        except EOFError:
            print(_muted("\n👋 Goodbye!"))
            break
        if line is None:
            print(_muted("\n👋 Goodbye!"))
            break

        if not line.strip():
            continue

        if line == "!!":
            if not st["last_prompt"]:
                print("Nothing to retry yet.")
            else:
                try:
                    _ask(orch, st, tui=tui)
                except KeyboardInterrupt:
                    print(_yellow("\n[Stopped]"))
                except Exception as e:
                    print(_red(f"[Error] {e}"))
            continue

        if line.startswith("!") and not line.startswith("!!"):
            _run_shell(line[1:])
            continue

        if line.startswith("/"):
            try:
                if _handle_command(line, orch, mm, mem, st) == "exit":
                    break
                if st.get("_tui_needs_redraw"):
                    tui.render()
                    st.pop("_tui_needs_redraw", None)
            except KeyboardInterrupt:
                print(_yellow("\n[Stopped]"))
            except Exception as e:
                print(_red(f"[Error] {e}"))
            continue

        st["last_prompt"] = line
        tui.add("user", line)
        tui.render()
        try:
            agent_prompt = agents.agent_system_prompt(st["agent"])
            _ask(orch, st, system_override=agent_prompt, tui=tui)
        except KeyboardInterrupt:
            print(_warning_color("\n[Stopped]"))
            continue
        except Exception as e:
            print(_error_color(f"[Error] {e}"))
            continue

    mm.unload_all()


if __name__ == "__main__":
    main()
