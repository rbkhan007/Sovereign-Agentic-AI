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


WELCOME = _cyan("\n".join([
    _box_rule("\u2554"),
    _box_line("RHASAN INDIE'S AGENTIC LLM  -  TERMINAL"),
    _box_line(""),
    _box_line(f"GPU: {'Enabled (' + CONFIG.gpu_name + ')' if HAS_GPU else 'Disabled'}"),
    _box_line(f"Threads: {CONFIG.threads}   Models: {len(CONFIG.available_models)}   Database: {'ON' if CONFIG.db.enabled else 'off'}"),
    _box_line(f"Cloud: {CONFIG.cloud_provider or 'none'}   Type /help for all commands"),
    _box_rule("\u255a"),
    "",
    _g("  Try: ", "") + _cyan("'explain quantum computing'") + _g("   |   ", "") +
    _cyan("'/code fix this'") + _g("   |   ", "") + _cyan("'/parallel on'") + _g("   |   ", "") +
    _cyan("'/arc 5'"),
    _dim("  Planning is ON: complex questions route through the strategist. "
         "Toggle with /plan, ensemble with /parallel."),
]))

HELP_TEXT = f"""
{_cyan('  COMMANDS')}
  {_cyan('- system')}
    /help                  show this help
    /status                live status (HUD, VRAM, models, config)
    /debug on|off          toggle debug logging
    /new                   start a fresh conversation
    /retry                 re-run your last prompt
    /clear                 clear this conversation
    /exit                  quit
  {_cyan('- models')}
    /model <name>          switch executor model
    /models                list all models (local + cloud)
    /preload <name>        load a model into VRAM now
    /unload [name]         unload model(s) from VRAM
    /vram                  VRAM usage per loaded model
  {_cyan('- planning & reasoning')}
    /plan on|off           toggle planning/reasoning (strategist)
    /think on|off          toggle live reasoning output
    /harness               show adaptive model-selection scores
    /harness reset         clear all harness scores
    /harness adjust <task> <model> <score>  manually set a score
    /harness export|import persist/restore harness state
    /arc [n]               run ARC reasoning eval (needs arc/training.json)
  {_cyan('- agents & skills')}
    /agent <name>          switch agent persona (see /agents)
    /agents                list agent personas (coder, debugger, writer, translator, ...)
    /skills                list skills (summarize, translate, code-review, ...)
    /skill <name> <text>   run a skill directly on text
    /code on|off           coding-agent persona (alias for /agent coder)
    /computer <goal>       full computer-use agent (shell, files, web, system)
    /computer tools        list available computer agent tools
    /computer sandbox on|off  toggle sandbox mode (read-only)
    /lora <sub>            list|enable|disable|import|train|delete
  {_cyan('- generation')}
    /parallel on|off       ensemble mode: N models answer, a judge picks best
    /context show|set|clear  inspect / set system prompt, show recent context
    /temperature <0-2>     override sampling temperature
    /max <tokens>          override max output tokens
    /timeout <seconds>     change generation watchdog timeout
    /tokens                token usage this session
  {_cyan('- conversations')}
    /save [name]           persist this conversation to disk
    /load <name>           restore a saved conversation
    /sessions              list saved conversations
  {_cyan('- cloud & memory')}
    /openai <key>          set OpenAI-compatible API key
    /cloud <name>          cloud preset: {', '.join(CLOUD_PRESETS)} (key via /openai)
    /db on|off|stats|clear|search|tables|index
                         toggle PostgreSQL, show stats, clear, search, list tables/indexes
    /prune                 delete memories older than {CONFIG.prune_max_age_days} days
    /exec <cmd>            run a shell command   (or prefix with !)
  {_cyan('- mcp tools')}
    /mcp                   list all MCP tools (chat, agents, skills)
    /mcp call <tool> <input>  call an MCP tool from the terminal
    /mcp json              output tool list as JSON

  {_cyan('SHORTCUTS')}
    !!                     re-run last prompt (same as /retry)
    !<command>             run shell command
    Enter to send, \\ at line end for multi-line, Ctrl+C to stop output
    Ctrl+A select all   Ctrl+C copy (or cancel)   Ctrl+V paste   Ctrl+X cut
    Ctrl+D del   Ctrl+W word-del   Ctrl+K del-to-end   Ctrl+U del-to-start
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
    on the base command name, so a whitelisted "/lora" permits "/lora train".
    """
    if not cmd.startswith("/"):
        return True
    base = cmd.split(" ", 1)[0].lower()
    if not CONFIG.cli_command_whitelist:
        return True
    return base in _ALWAYS_ALLOWED or base in CONFIG.cli_command_whitelist


def _visible_commands() -> list[str]:
    """Commands offered for tab-completion, honoring the whitelist."""
    if not CONFIG.cli_command_whitelist:
        return list(_COMMANDS)
    return [c for c in _COMMANDS if c in _ALWAYS_ALLOWED or c in CONFIG.cli_command_whitelist]


def _prompt() -> str:
    return _cyan(_g("\u276f ", "> "))


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
        print((out or "").rstrip() or _dim(f"[exit {proc.returncode}]"))
    except subprocess.TimeoutExpired:
        print(_red("[Error] command timed out"))
    except Exception as e:
        print(_red(f"[Error] {e}"))


def _hud(st: dict, mm: ModelManager) -> str:
    cloud = CONFIG.cloud_provider or ("openai" if CONFIG.openai.enabled else "none")
    parts = [
        _cyan(f"agent:{st.get('agent', '?')}"),
        _green(f"model:{st.get('last_model', '?')}"),
        "plan:" + (_green("ON") if st.get("planning") else "off"),
        "par:" + (_green("ON") if st.get("parallel") else "off"),
        "code:" + (_green("ON") if st.get("coding") else "off"),
        f"cloud:{cloud}",
        f"tok:{st.get('tokens', 0)}",
    ]
    temperature = st.get("temperature")
    if temperature is not None:
        parts.append(f"temp:{temperature}")
    max_tokens = st.get("max_tokens")
    if max_tokens:
        parts.append(f"max:{max_tokens}")
    if mm.instances:
        parts.append(f"loaded:{len(mm.instances)}")
    return "  " + _dim(" | ").join(parts)


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
        return self.role.capitalize()


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)


class TUIRenderer:
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

    def _render_message_cell(self, msg: Message, y: int, width: int) -> int:
        pad = 1
        inner = width - (pad * 2) - 2
        color = msg.role_color()
        avatar = _g(msg.avatar(), "*")
        label = msg.role_label()
        meta_parts = []
        if msg.model:
            meta_parts.append(f"model={msg.model}")
        if msg.elapsed:
            meta_parts.append(f"{msg.elapsed:.1f}s")
        if msg.tokens:
            meta_parts.append(f"{msg.tokens} tok")
        meta = " \u00b7 ".join(meta_parts)
        header = f"{_g(avatar, '*')} {_bold(label)}"
        if meta:
            header += f"  {_dim(meta)}"

        lines = self._wrap(msg.content, inner)
        total = 3 + len(lines)  # header + pad + bottom rule

        # top border
        sys.stdout.write(f"\033[{y};1H")
        sys.stdout.write(_paint(" " * pad + _g("\u256d", "+") + _g("\u2500", "-") * (inner + 2) + _g("\u256e", "+"), color))
        y += 1

        # header line
        sys.stdout.write(f"\033[{y};1H")
        sys.stdout.write(_paint(_g("\u2502", "|") + " ", color) + header + _paint(" " + _g("\u2502", "|"), color))
        y += 1

        # separator
        sys.stdout.write(f"\033[{y};1H")
        sys.stdout.write(_paint(_g("\u2502", "|") + " " + _g("\u2500", "-") * inner + " " + _g("\u2502", "|"), color))
        y += 1

        # content lines
        for line in lines:
            sys.stdout.write(f"\033[{y};1H")
            sys.stdout.write(_paint(_g("\u2502", "|") + " ", color) + f"{line:<{inner}}" + _paint(" " + _g("\u2502", "|"), color))
            y += 1

        # bottom border
        sys.stdout.write(f"\033[{y};1H")
        sys.stdout.write(_paint(" " * pad + _g("\u2570", "\\") + _g("\u2500", "-") * (inner + 2) + _g("\u256f", "/"), color))
        return total + 1

    def render(self):
        self._update_size()
        width = self.term_width - 2
        width = max(width, 20)

        # clear screen + hide cursor
        sys.stdout.write("\033[2J\033[H\033[?25l")
        sys.stdout.flush()

        # header
        self._render_header(width)

        # scroll region for messages
        top = self.msg_start_y
        bot = self.input_start_y - 1
        sys.stdout.write(f"\033[{top};{bot+1}r")
        sys.stdout.flush()

        # messages
        self._render_messages(width)

        # reset scroll region
        sys.stdout.write(f"\033[{self.term_height};{self.term_height}r")
        sys.stdout.flush()

        # input area
        self._render_input_area(width)

        # show cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def _render_header(self, width: int):
        title = _bold(_cyan(_g("\u25b6", ">"))) + " RHASAN INDIE'S AGENTIC LLM  \u00b7  Terminal"
        stats = _dim(f"{self.term_width}x{self.term_height}  \u00b7  {len(self.messages)} msgs")
        if self.scroll > 0:
            stats += _dim(f"  \u00b7  scroll {self.scroll}")
        line = title + "  " + stats
        if len(_strip_ansi(line)) > width:
            line = line[: width - 3] + _dim("...")
        sys.stdout.write(f"\033[1;1H{line}\n")
        sys.stdout.write(f"\033[2;1H{_g('\u2500', '-') * self.term_width}\n")
        sys.stdout.flush()

    def _render_messages(self, width: int):
        if not self.messages:
            sys.stdout.write(f"\033[{self.msg_start_y};1H")
            sys.stdout.write(_dim("  No messages yet. Type something to start...") + "\n")
            sys.stdout.flush()
            return

        visible = self.msg_area_h
        start = max(0, len(self.messages) - visible - self.scroll)
        end = min(len(self.messages), start + visible)
        y = self.msg_start_y
        for i in range(start, end):
            msg = self.messages[i]
            h = self._render_message_cell(msg, y, width)
            y += h
        # scroll indicator at bottom of message area
        if len(self.messages) > visible:
            info = _dim(f"  {start+1}-{end} of {len(self.messages)}")
            sys.stdout.write(f"\033[{self.input_start_y - 1};1H{info}")
            sys.stdout.flush()

    def _render_input_area(self, width: int):
        y = self.input_start_y
        sys.stdout.write(f"\033[{y};1H{_g('\u2500', '-') * self.term_width}\n")
        sys.stdout.write(f"\033[{y+1};1H" + _cyan(_g("\u276f", ">")) + " \n")
        hint = _dim("Type a message  |  /help for commands  |  Mouse: scroll/select/dbl-click copy")
        if len(_strip_ansi(hint)) > width:
            hint = hint[: width - 3] + _dim("...")
        sys.stdout.write(f"\033[{y+2};1H{hint}\n")
        sys.stdout.flush()

    def scroll_up(self, amount: int = 3):
        self.scroll = max(0, self.scroll - amount)

    def scroll_down(self, amount: int = 3):
        max_scroll = max(0, len(self.messages) - self.msg_area_h)
        self.scroll = min(max_scroll, self.scroll + amount)

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
                        matches = [c for c in _visible_commands() if c.startswith(prefix)]
                        if matches:
                            buf[:] = list(matches[0] + " ")
                            pos = len(buf)
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
    try:
        return inp(prompt)
    except (EOFError, KeyboardInterrupt):
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

def _show_thinking(text: str, st: dict):
    if not text:
        return
    if st["show_thinking"]:
        border = _g("\u2500", "-")
        print(_cyan(f"  {border} thinking {border}"))
        print(_dim(text[:600]))
        if len(text) > 600:
            print(_dim(f"  {border} {len(text) - 600} more chars {border}"))
    else:
        print(_dim(f"  [thinking] {len(text)} chars"))


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
                    print(_cyan(f"  > {model}"))
            elif t == "thinking":
                _show_thinking(evt.get("content") or "", st)
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
        print(_cyan(f"  [{model or st['last_model']} | {len(text.split())} tok | {tps:.1f} tps | {elapsed:.1f}s]"))


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
        print(_green(response))
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
        print(_dim(f"  [{extra} | {time.time() - start:.1f}s | {st['tokens']} tok]"))


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
            print(f"  {name} ({mc.role}){loaded}")
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
        st["agent"] = "coder" if st["coding"] else "general"
        print(f"Coding agent: {'ON' if st['coding'] else 'OFF'} (agent: {st['agent']})")
        return
    if cmd == "/computer":
        sub = parts[1].lower() if len(parts) > 1 else ""
        if sub == "tools":
            agent = create_computer_agent(mm, orch, sandbox=st.get("computer_sandbox", False))
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
        agent = create_computer_agent(mm, orch, sandbox=sandbox)
        st["_computer_agent"] = agent
        mode_label = _yellow("SANDBOX") if sandbox else _green("FULL ACCESS")
        print(_cyan(f"\n  Computer Agent [{mode_label}] | Goal: {goal}"))
        print(_dim("  Ctrl+C to cancel\n"))

        def _agent_callback(step):
            icon = _green("OK") if step.tool_result and step.tool_result.success else _red("ERR")
            args_str = ""
            if step.tool_args:
                args_str = str(step.tool_args)[:120]
            print(_dim(f"  [{step.step_num}] ") + f"{step.tool_name} {args_str} [{icon}] {step.elapsed_s:.1f}s")

        try:
            agent_result = agent.run(goal, callback=_agent_callback)
            print()
            print(_green("  " + "=" * 60))
            print(_green(f"  RESULT ({len(agent_result.steps)} steps, {agent_result.total_elapsed_s:.1f}s):"))
            print(_green("  " + "=" * 60))
            for ans_line in agent_result.final_answer.split("\n"):
                print(f"  {ans_line}")
            print()
        except KeyboardInterrupt:
            agent.cancel()
            print(_yellow("\n  [Cancelled]"))
        except Exception as e:
            print(_red(f"\n  [Error] {e}"))
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
                st["coding"] = a["name"] == "coder"
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
                from api import orchestrator as _orch
                if tool_name == "chat":
                    result = _orch.run(user_message=tool_input, conv_id=f"mcp-cli-{uuid.uuid4().hex[:8]}", use_planning=True)
                    print(f"\n{_green('Response:')}\n{result['response']}")
                elif tool_name in agents.AGENTS:
                    a = agents.get_agent(tool_name)
                    if a is None:
                        print(f"Unknown tool '{tool_name}'")
                        return
                    result = _orch.run(user_message=tool_input, conv_id=f"mcp-cli-{uuid.uuid4().hex[:8]}",
                                       use_planning=True, system_override=a["system_prompt"])
                    print(f"\n{_green('Response:')}\n{result['response']}")
                elif tool_name in agents.SKILLS:
                    rendered = agents.render_skill(tool_name, tool_input)
                    if rendered is None:
                        print(f"Unknown tool '{tool_name}'")
                        return
                    result = _orch.run(user_message=rendered["prompt"], conv_id=f"mcp-cli-{uuid.uuid4().hex[:8]}",
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
        print(f"\n  {_bold('MCP Tools')} ({len(tools)}):")
        print(f"  {_dim('chat')}  - Chat with the AI assistant (orchestrator pipeline)")
        for tool_name in agents.list_agents():
            a = agents.get_agent(tool_name)
            desc = a["description"] if a else ""
            print(f"  {_cyan(tool_name)}  - {desc}")
        for tool_name in agents.list_skills():
            s = agents.get_skill(tool_name)
            desc = s["description"] if s else ""
            params = ", ".join(p["name"] for p in s.get("params", [])) if s and s.get("params") else ""
            param_str = f" [{params}]" if params else ""
            print(f"  {_green(tool_name)}{param_str}  - {desc}")
        print(f"\n  {_dim('Call a tool:')}  /mcp call <tool> <input text>")
        print(f"  {_dim('JSON output:')}  /mcp json")
        print("  Each skill/agent you add becomes an MCP tool automatically.")
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
            print(f"  {'Task/Model':<25} {'Score':>6} {'Attempts':>8} {'Errors':>6} {'Avg Lat':>8} {'Tokens':>7}")
            print(f"  {'-'*25} {'-'*6} {'-'*8} {'-'*6} {'-'*8} {'-'*7}")
            for k, v in sorted(data.items(), key=lambda x: -x[1]["score"]):
                print(f"  {k:<25} {v['score']:>6.1f} {v['attempts']:>8} {v['errors']:>6} "
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
    print(f"Unknown: {cmd}")
    if suggestions:
        print(f"  Did you mean: {_cyan(', '.join(suggestions))}?")
    else:
        print(f"  Type {_cyan('/help')} for the full command list.")
    return


# ---------- main loop ----------

def main():
    _init_color()
    mm = ModelManager()
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
            print("\n\n\ud83d\udc4b Goodbye!")
            break
        except EOFError:
            print("\n\n\ud83d\udc4b Goodbye!")
            break
        if line is None:
            print("Goodbye!")
            break

        if not line.strip():
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
            print(_yellow("\n[Stopped]"))
            continue
        except Exception as e:
            print(_red(f"[Error] {e}"))
            continue

    mm.unload_all()


if __name__ == "__main__":
    main()
