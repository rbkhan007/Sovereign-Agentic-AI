"""
gui_automation.py - Native keyboard & mouse control for the computer agent.

Gives the LLM "human hands": move/click/drag/scroll the mouse and type/press
keys, exactly like a person using the machine. Implemented with the Windows
user32/kernel32 APIs through ctypes so there are NO third-party dependencies
(pyautogui/keyboard are optional; this works out of the box). Pillow is used
for screenshots when available.

Safety: every function is pure "input injection" - nothing here reads the
filesystem, network, or secrets, so it is safe to expose behind the computer
agent (it is still a `dangerous` tool: sandbox mode blocks it, and callers
must opt in via CONFIG.computer['allow_gui'] or the CLI flag).
"""
import ctypes
import logging
import os
import sys
import time
from typing import Dict, Optional

# pylint: disable=possibly-used-before-assignment
# The Windows-only bindings below are defined inside `if sys.platform == "win32"`,
# and every function calls `_ensure_win()` before touching them, so pylint's
# "possibly-used-before-assignment" warnings here are false positives.

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Windows user32 bindings (lazy, only on win32)
# --------------------------------------------------------------------------

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _user32.SetCursorPos.restype = ctypes.c_long
    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

    _SM_CXSCREEN = 0
    _SM_CYSCREEN = 1

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    _user32.GetCursorPos.restype = ctypes.c_long
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", _MOUSEINPUT),
            ("ki", _KEYBDINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("union", _INPUT_UNION)]

    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1

    # mouse event flags
    _MOVE = 0x0001
    _LEFTPRESS = 0x0002
    _LEFTRELEASE = 0x0004
    _RIGHTPRESS = 0x0008
    _RIGHTRELEASE = 0x0010
    _MIDDLEPRESS = 0x0020
    _MIDDLERELEASE = 0x0040
    _WHEEL = 0x0800
    _ABSOLUTE = 0x8000

    # keyboard event flags
    _KEYUP = 0x0002
    _UNICODE = 0x0004
    _SCANCODE = 0x0008

    # virtual-key codes for common keys
    _VK_MAP = {
        "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
        "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
        "del": 0x2E, "home": 0x24, "end": 0x23, "insert": 0x2D, "ins": 0x2D,
        "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
        "win": 0x5B, "windows": 0x5B, "lwin": 0x5B, "menu": 0x5D,
        "capslock": 0x14, "cap": 0x14, "numlock": 0x90, "scrolllock": 0x91,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
        "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
        "f11": 0x7A, "f12": 0x7B, "f13": 0x7C, "f14": 0x7D, "f15": 0x7E,
        "f16": 0x7F, "f17": 0x80, "f18": 0x81, "f19": 0x82, "f20": 0x83,
        "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
        "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
        "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
        "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
        "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
        "y": 0x59, "z": 0x5A,
        "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
        "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
        ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
        "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    }

    _PRINTABLE_KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789")

    def _send_input(inputs):
        """Push a list of _INPUT structs through SendInput atomically."""
        if not inputs:
            return
        arr = (_INPUT * len(inputs))(*inputs)
        sent = _user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            logger.warning("SendInput sent %s/%s events", sent, len(inputs))

    def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> _INPUT:
        inp = _INPUT()
        inp.type = _INPUT_MOUSE
        inp.union.mi.dx = dx
        inp.union.mi.dy = dy
        inp.union.mi.mouseData = data
        inp.union.mi.dwFlags = flags
        inp.union.mi.time = 0
        inp.union.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        return inp

    def _key_input(vk: int, keyup: bool = False, unicode_char: Optional[str] = None) -> _INPUT:
        inp = _INPUT()
        inp.type = _INPUT_KEYBOARD
        if unicode_char is not None:
            inp.union.ki.wScan = ord(unicode_char)
            inp.union.ki.dwFlags = _UNICODE | (_KEYUP if keyup else 0)
        else:
            inp.union.ki.wVk = vk
            inp.union.ki.dwFlags = _KEYUP if keyup else 0
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        return inp

    def _to_vk(key: str) -> Optional[int]:
        return _VK_MAP.get(str(key).lower())

else:  # non-Windows: degrade gracefully with clear errors
    _user32 = None


def _ensure_win():
    if _user32 is None:
        raise RuntimeError("GUI automation is only available on Windows")
    return _user32


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def screen_size() -> Dict[str, int]:
    """Return the primary screen resolution in pixels."""
    if _user32 is None:
        return {"width": 0, "height": 0}
    u = _ensure_win()
    return {
        "width": int(u.GetSystemMetrics(_SM_CXSCREEN)),
        "height": int(u.GetSystemMetrics(_SM_CYSCREEN)),
    }


def cursor_position() -> Dict[str, int]:
    """Return the current mouse cursor position (x, y)."""
    if _user32 is None:
        return {"x": 0, "y": 0}
    u = _ensure_win()
    pt = _POINT()
    u.GetCursorPos(ctypes.byref(pt))
    return {"x": int(pt.x), "y": int(pt.y)}


def move_mouse(x: int, y: int, absolute: bool = True) -> Dict[str, int]:
    """Move the mouse cursor to (x, y). Returns the new position."""
    u = _ensure_win()
    if absolute:
        if not u.SetCursorPos(int(x), int(y)):
            logger.warning("SetCursorPos failed for (%s, %s)", x, y)
    else:
        _send_input([_mouse_input(_MOVE, dx=int(x), dy=int(y))])
    return cursor_position()


def click(button: str = "left", x: Optional[int] = None, y: Optional[int] = None,
          clicks: int = 1) -> str:
    """Click the mouse at (x, y) (or current position when omitted)."""
    u = _ensure_win()
    if x is not None and y is not None:
        u.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
    btn = button.lower()
    if btn == "left":
        press, release = _LEFTPRESS, _LEFTRELEASE
    elif btn == "right":
        press, release = _RIGHTPRESS, _RIGHTRELEASE
    elif btn == "middle":
        press, release = _MIDDLEPRESS, _MIDDLERELEASE
    else:
        raise ValueError(f"Unknown button: {button} (use left|right|middle)")
    for _ in range(max(1, int(clicks))):
        _send_input([_mouse_input(press), _mouse_input(release)])
        time.sleep(0.03)
    return f"clicked {button} at {cursor_position()}"


def drag(start_x: int, start_y: int, end_x: int, end_y: int,
         button: str = "left", steps: int = 20) -> str:
    """Press the mouse at (start_x, start_y), glide to (end_x, end_y), release."""
    u = _ensure_win()
    btn = button.lower()
    if btn == "left":
        press, release = _LEFTPRESS, _LEFTRELEASE
    elif btn == "right":
        press, release = _RIGHTPRESS, _RIGHTRELEASE
    else:
        raise ValueError(f"Unknown button: {button} (use left|right)")
    u.SetCursorPos(int(start_x), int(start_y))
    time.sleep(0.03)
    _send_input([_mouse_input(press)])
    time.sleep(0.05)
    for i in range(1, max(1, int(steps)) + 1):
        t = i / float(steps)
        u.SetCursorPos(int(start_x + (end_x - start_x) * t),
                       int(start_y + (end_y - start_y) * t))
        time.sleep(0.01)
    time.sleep(0.05)
    _send_input([_mouse_input(release)])
    return f"dragged from ({start_x},{start_y}) to ({end_x},{end_y})"


def scroll(lines: int = 1) -> str:
    """Scroll the wheel. Positive lines = scroll up, negative = scroll down."""
    _ensure_win()
    clicks = int(lines)
    data = 120 * clicks  # WHEEL_DELTA per notch
    _send_input([_mouse_input(_WHEEL, data=data)])
    return f"scrolled {'up' if lines > 0 else 'down'} {abs(lines)} notch(es)"


def type_text(text: str, interval: float = 0.0) -> str:
    """Type `text` character-by-character through Unicode key events."""
    _ensure_win()
    typed = 0
    for ch in text:
        if ch == "\n":
            _send_input([_key_input(0x0D), _key_input(0x0D, keyup=True)])
            typed += 1
            continue
        # Unsupported printable chars go through the unicode path.
        _send_input([_key_input(0, unicode_char=ch), _key_input(0, keyup=True, unicode_char=ch)])
        typed += 1
        if interval and interval > 0:
            time.sleep(min(float(interval), 0.1))
    return f"typed {typed} characters"


def press(keys: str, interval: float = 0.05) -> str:
    """Press a key or a '+'/'-' joined combo (e.g. 'ctrl+c', 'ctrl+shift+s').

    Named keys use the VK table; single printable chars are typed directly.
    """
    _ensure_win()
    parts = [p.strip() for p in re_split_keys(keys)]
    if not parts:
        raise ValueError("No keys given")
    vks = []
    unicode_parts = []
    for part in parts:
        low = part.lower()
        if low in _VK_MAP:
            vks.append(_VK_MAP[low])
        elif len(part) == 1 and part.isprintable():
            # Printable punctuation (e.g. '!', '@', '+') has no reliable VK
            # code via ord(); use the Unicode path instead so the correct
            # character reaches the focused window.
            unicode_parts.append(part)
        else:
            raise ValueError(f"Unknown key: {part}")
    for vk in vks:
        _send_input([_key_input(vk)])
        time.sleep(interval)
    for ch in unicode_parts:
        _send_input([_key_input(0, unicode_char=ch), _key_input(0, keyup=True, unicode_char=ch)])
        time.sleep(interval)
    for vk in reversed(vks):
        _send_input([_key_input(vk, keyup=True)])
        time.sleep(interval)
    return f"pressed {keys}"


def re_split_keys(keys: str):
    import re as _re
    return _re.split(r"[+]", keys)


def screenshot(path: Optional[str] = None) -> str:
    """Capture the whole screen to `path` (default generated/gui_screenshots/).
    Returns the saved file path so the caller can show it to the model."""
    from PIL import ImageGrab
    if not path:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "generated", "gui_screenshots")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, f"screen_{int(time.time())}.png")
    img = ImageGrab.grab()
    img.save(path)
    size = os.path.getsize(path)
    return f"saved screenshot ({img.size[0]}x{img.size[1]}, {size} bytes) to {path}"


def describe_actions() -> str:
    """One-line summary of available GUI tools (used by the agent prompt)."""
    return (
        "mouse_move(x,y) | mouse_click(button,x,y,clicks) | mouse_drag(x1,y1,x2,y2) | "
        "mouse_scroll(lines) | keyboard_type(text) | keyboard_press('ctrl+c') | "
        "cursor_position() | screen_size() | screenshot(path)"
    )
