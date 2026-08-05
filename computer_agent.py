"""
computer_agent.py - Full computer-use AI agent with ReAct-style tool loop.

Gives the LLM hands-on access to the computer: shell commands, file I/O,
web search/fetch, process management, Python execution, and system info.
The agent observes, reasons, acts, and iterates until the goal is achieved.
"""
import json
import logging
import os
import platform
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_DANGEROUS_CMDS = {
    "rm -rf /", "rm -rf /*", "mkfs", "format c:", "format /q c:",
    ":(){ :|:& };:", "dd if=", "> /dev/sd", "chmod -R 777 /",
    "shutdown", "reboot", "halt", "init 0", "init 6", "rd /s", "rmdir /s",
}

_DANGEROUS_TOKENS = {
    "shutdown", "reboot", "halt", "mkfs", "diskpart", "format",
    "dd", "del", "erase", "rd", "rmdir", "deltree",
}

_MAX_TOOL_OUTPUT = 8000
_MAX_STEPS = 25
_TOOL_TIMEOUT = 120


def _sandbox_scoped(path: str, root: str = BASE_DIR) -> tuple:
    """Return (allowed, absolute_path) for a sandbox read.

    In sandbox mode file reads/listings must stay within the project tree so
    the read-only agent cannot exfiltrate arbitrary files (e.g. C:\\Users\\...
    or .env files outside the project).
    """
    ap = os.path.abspath(os.path.expanduser(path))
    if ap == root or ap.startswith(root + os.sep):
        return True, ap
    return False, ap


@dataclass
class ToolResult:
    success: bool
    output: str
    metadata: Optional[Dict[str, Any]] = None

    def to_text(self) -> str:
        prefix = "OK" if self.success else "ERROR"
        text = f"[{prefix}] {self.output}"
        if len(text) > _MAX_TOOL_OUTPUT:
            text = text[:_MAX_TOOL_OUTPUT] + "\n... (truncated)"
        return text


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: Dict[str, Any]
    execute: Callable[..., ToolResult]
    dangerous: bool = False
    sandbox_safe: bool = False

    def schema_doc(self) -> str:
        props = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])
        lines = [f"  {self.name}: {self.description}"]
        if props:
            for pname, pdef in props.items():
                req = " (required)" if pname in required else ""
                ptype = pdef.get("type", "string")
                pdesc = pdef.get("description", "")
                lines.append(f"    - {pname} ({ptype}){req}: {pdesc}")
        return "\n".join(lines)


def _truncate(text: str, limit: int = _MAX_TOOL_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... ({len(text) - limit} chars omitted) ...\n" + text[-half:]


def _is_dangerous(cmd: str) -> bool:
    """Token-aware guard against destructive shell commands.

    Catches both the literal blocklist patterns and obfuscated forms such as
    extra whitespace, quoting, ``python -c``/``cmd /c`` wrappers, and commands
    that recurse-delete a whole drive or root filesystem.
    """
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


def _tool_shell(command: str, timeout: int = _TOOL_TIMEOUT) -> ToolResult:
    if _is_dangerous(command):
        return ToolResult(False, f"BLOCKED: command matches dangerous pattern: {command}")
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,  # nosec B602
            timeout=timeout, cwd=os.getcwd(),
        )
        out = proc.stdout or ""
        if proc.returncode != 0:
            err = proc.stderr or ""
            if err:
                out += ("\n" if out else "") + err
        out = out.strip()
        if not out:
            out = f"[exit code {proc.returncode}]"
        return ToolResult(proc.returncode == 0, _truncate(out), {"returncode": proc.returncode})
    except subprocess.TimeoutExpired:
        return ToolResult(False, f"Command timed out after {timeout}s")
    except Exception as e:
        return ToolResult(False, f"Shell error: {e}")


def _tool_read_file(path: str, offset: int = 0, limit: int = 500, sandbox: bool = False) -> ToolResult:
    try:
        if sandbox:
            allowed, ap = _sandbox_scoped(path)
            if not allowed:
                return ToolResult(False, f"Sandbox: read access outside project directory blocked: {path}")
            path = ap
        else:
            path = os.path.expanduser(path)
        if not os.path.isfile(path):
            return ToolResult(False, f"File not found: {path}")
        size = os.path.getsize(path)
        if size > 2_000_000:
            return ToolResult(False, f"File too large ({size} bytes). Use shell to read.")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        selected = lines[offset:offset + limit]
        numbered = [f"{i + offset + 1:4d} | {l.rstrip()}" for i, l in enumerate(selected)]
        header = f"File: {path} ({total} lines, {size} bytes)"
        if offset > 0 or offset + limit < total:
            header += f" [showing lines {offset + 1}-{min(offset + limit, total)}]"
        return ToolResult(True, header + "\n" + "\n".join(numbered))
    except Exception as e:
        return ToolResult(False, f"Read error: {e}")


def _tool_write_file(path: str, content: str, append: bool = False) -> ToolResult:
    try:
        path = os.path.expanduser(path)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        action = "appended to" if append else "wrote"
        size = len(content)
        return ToolResult(True, f"{action} {path} ({size} bytes)")
    except Exception as e:
        return ToolResult(False, f"Write error: {e}")


def _tool_list_dir(path: str = ".", show_hidden: bool = False, sandbox: bool = False) -> ToolResult:
    try:
        if sandbox:
            allowed, ap = _sandbox_scoped(path or ".")
            if not allowed:
                return ToolResult(False, f"Sandbox: directory access outside project blocked: {path}")
            path = ap
        else:
            path = os.path.expanduser(path or ".")
        if not os.path.isdir(path):
            return ToolResult(False, f"Not a directory: {path}")
        entries = os.listdir(path)
        if not show_hidden:
            entries = [e for e in entries if not e.startswith(".")]
        entries.sort(key=lambda e: (not os.path.isdir(os.path.join(path, e)), e.lower()))
        lines = []
        for entry in entries:
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                lines.append(f"  {entry}/")
            else:
                size = os.path.getsize(full)
                if size < 1024:
                    sz = f"{size}B"
                elif size < 1_048_576:
                    sz = f"{size / 1024:.1f}K"
                else:
                    sz = f"{size / 1_048_576:.1f}M"
                lines.append(f"  {entry}  ({sz})")
        if not lines:
            return ToolResult(True, f"Empty directory: {path}")
        return ToolResult(True, f"Directory: {path} ({len(entries)} items)\n" + "\n".join(lines))
    except Exception as e:
        return ToolResult(False, f"List error: {e}")


def _tool_search_files(pattern: str, path: str = ".", file_glob: str = "*",
                       max_results: int = 30, sandbox: bool = False) -> ToolResult:
    try:
        if sandbox:
            allowed, ap = _sandbox_scoped(path or ".")
            if not allowed:
                return ToolResult(False, f"Sandbox: search access outside project blocked: {path}")
            path = ap
        else:
            path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return ToolResult(False, f"Not a directory: {path}")
        regex = re.compile(pattern, re.IGNORECASE)
        matches = []
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                       ("node_modules", "__pycache__", ".git", "venv", "env",
                        "lora_datasets", "frontend", "sessions", "generated")]
            import fnmatch
            for fname in fnmatch.filter(files, file_glob):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                rel = os.path.relpath(fpath, path)
                                matches.append(f"{rel}:{i}: {line.rstrip()[:200]}")
                                if len(matches) >= max_results:
                                    break
                except (OSError, UnicodeDecodeError):
                    pass
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break
        if not matches:
            return ToolResult(True, f"No matches for '{pattern}' in {path}")
        header = f"Found {len(matches)} matches for '{pattern}'"
        if len(matches) >= max_results:
            header += f" (showing first {max_results})"
        return ToolResult(True, header + "\n" + "\n".join(matches))
    except re.error as e:
        return ToolResult(False, f"Invalid regex: {e}")
    except Exception as e:
        return ToolResult(False, f"Search error: {e}")


def _tool_web_search(query: str, max_results: int = 5) -> ToolResult:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = []
            for r in ddgs.text(query, max_results=max_results):
                title = r.get("title", "").strip()
                body = r.get("body", "").strip()
                url = r.get("href", "")
                if body:
                    results.append(f"[{title}]({url})\n{body[:500]}")
                elif title:
                    results.append(f"[{title}]({url})")
        if results:
            return ToolResult(True, f"Search: '{query}'\n\n" + "\n\n".join(results))
        return ToolResult(True, f"No results for '{query}'")
    except ImportError:
        return ToolResult(False, "duckduckgo_search not installed. pip install duckduckgo_search")
    except Exception as e:
        return ToolResult(False, f"Search error: {e}")


def _tool_web_fetch(url: str, max_chars: int = 15000) -> ToolResult:
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AgenticLLM/1.0)"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
            raw = resp.read(500_000)
            content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type:
            text = raw.decode("utf-8", errors="replace")
        elif "html" in content_type or "text" in content_type:
            text = raw.decode("utf-8", errors="replace")
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        else:
            text = raw.decode("utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... (truncated, total {len(text)} chars)"
        return ToolResult(True, f"Fetched {url} ({len(text)} chars)\n\n{text}")
    except urllib.error.HTTPError as e:
        return ToolResult(False, f"HTTP {e.code}: {e.reason}")
    except Exception as e:
        return ToolResult(False, f"Fetch error: {e}")


def _tool_system_info() -> ToolResult:
    try:
        import psutil
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu_pct = psutil.cpu_percent(interval=0.5)
        info = {
            "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "cpu": f"{platform.machine()} ({psutil.cpu_count()} cores)",
            "cpu_usage": f"{cpu_pct}%",
            "ram_total_gb": round(mem.total / 1_073_741_824, 1),
            "ram_used_gb": round(mem.used / 1_073_741_824, 1),
            "ram_percent": f"{mem.percent}%",
            "disk_total_gb": round(disk.total / 1_073_741_824, 1),
            "disk_used_gb": round(disk.used / 1_073_741_824, 1),
            "disk_percent": f"{disk.percent}%",
            "cwd": os.getcwd(),
        }
        try:
            import torch
            if torch.cuda.is_available():
                info["gpu"] = torch.cuda.get_device_name(0)
                info["gpu_mem_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1_073_741_824, 1)
        except Exception:
            pass
        lines = [f"  {k}: {v}" for k, v in info.items()]
        return ToolResult(True, "System Info:\n" + "\n".join(lines))
    except ImportError:
        info = {
            "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "cpu": f"{platform.machine()} ({os.cpu_count()} cores)",
            "cwd": os.getcwd(),
        }
        lines = [f"  {k}: {v}" for k, v in info.items()]
        return ToolResult(True, "System Info (limited - install psutil):\n" + "\n".join(lines))
    except Exception as e:
        return ToolResult(False, f"System info error: {e}")


def _tool_process_list(filter_name: str = "", max_results: int = 30) -> ToolResult:
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                info = p.info
                name = info.get("name", "")
                if filter_name and filter_name.lower() not in name.lower():
                    continue
                cpu = info.get("cpu_percent", 0) or 0
                mem = info.get("memory_percent", 0) or 0
                procs.append((info["pid"], name, cpu, mem, info.get("status", "")))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x[3], reverse=True)
        procs = procs[:max_results]
        if not procs:
            return ToolResult(True, f"No processes matching '{filter_name}'" if filter_name else "No processes found")
        lines = ["PID     Name                          CPU%   MEM%   Status"]
        lines.append("-" * 65)
        for pid, name, cpu, mem, status in procs:
            lines.append(f"{pid:<7} {name[:30]:<30} {cpu:<6.1f} {mem:<6.1f} {status}")
        return ToolResult(True, f"Top {len(procs)} processes:\n" + "\n".join(lines))
    except ImportError:
        return ToolResult(False, "psutil not installed. pip install psutil")
    except Exception as e:
        return ToolResult(False, f"Process list error: {e}")


def _tool_python_exec(code: str) -> ToolResult:
    try:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        import io
        buf = io.StringIO()
        sys.stdout = buf
        sys.stderr = buf
        try:
            compiled = compile(code, "<agent>", "exec")
            exec(compiled, {"__builtins__": __builtins__})  # nosec B102  # pylint: disable=W0122
        except Exception:
            import traceback
            traceback.print_exc(file=buf)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = buf.getvalue()
        if not output.strip():
            output = "[executed successfully, no output]"
        return ToolResult(True, _truncate(output))
    except Exception as e:
        return ToolResult(False, f"Python exec error: {e}")


def _tool_process_kill(pid: int) -> ToolResult:
    try:
        import psutil
        p = psutil.Process(pid)
        name = p.name()
        p.terminate()
        try:
            p.wait(timeout=5)
        except psutil.TimeoutExpired:
            p.kill()
        return ToolResult(True, f"Killed process {pid} ({name})")
    except ImportError:
        return ToolResult(False, "psutil not installed")
    except psutil.NoSuchProcess:
        return ToolResult(False, f"Process {pid} not found")
    except psutil.AccessDenied:
        return ToolResult(False, f"Access denied to kill process {pid}")
    except Exception as e:
        return ToolResult(False, f"Kill error: {e}")


class ToolRegistry:
    def __init__(self, sandbox: bool = False):
        self.tools: Dict[str, AgentTool] = {}
        self.sandbox = sandbox
        self._register_builtins()

    def _register_builtins(self):
        self.register(AgentTool(
            name="shell",
            description="Execute a shell command. Returns stdout/stderr and exit code.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                },
                "required": ["command"],
            },
            execute=_tool_shell,
            dangerous=True,
        ))
        self.register(AgentTool(
            name="read_file",
            description="Read the contents of a file. Returns numbered lines.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "offset": {"type": "integer", "description": "Start line (0-based)"},
                    "limit": {"type": "integer", "description": "Max lines to read (default 500)"},
                },
                "required": ["path"],
            },
            execute=lambda path, offset=0, limit=500: _tool_read_file(path, offset, limit, sandbox=self.sandbox),
            sandbox_safe=True,
        ))
        self.register(AgentTool(
            name="write_file",
            description="Write content to a file. Creates parent directories. Overwrites unless append=true.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                    "append": {"type": "boolean", "description": "Append instead of overwrite"},
                },
                "required": ["path", "content"],
            },
            execute=lambda path, content, append=False: _tool_write_file(path, content, append),
            dangerous=True,
        ))
        self.register(AgentTool(
            name="list_dir",
            description="List contents of a directory with sizes. Directories marked with /.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: current)"},
                    "show_hidden": {"type": "boolean", "description": "Include hidden files"},
                },
            },
            execute=lambda path=".", show_hidden=False: _tool_list_dir(path, show_hidden, sandbox=self.sandbox),
            sandbox_safe=True,
        ))
        self.register(AgentTool(
            name="search_files",
            description="Search file contents using regex pattern across files in a directory.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in (default: cwd)"},
                    "file_glob": {"type": "string", "description": "File filter (e.g. *.py)"},
                    "max_results": {"type": "integer", "description": "Max matches to return"},
                },
                "required": ["pattern"],
            },
            execute=lambda pattern, path=".", file_glob="*", max_results=30:
                _tool_search_files(pattern, path, file_glob, max_results, sandbox=self.sandbox),
            sandbox_safe=True,
        ))
        self.register(AgentTool(
            name="web_search",
            description="Search the web via DuckDuckGo. Returns titles, URLs, and snippets.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
            execute=lambda query, max_results=5: _tool_web_search(query, max_results),
            sandbox_safe=True,
        ))
        self.register(AgentTool(
            name="web_fetch",
            description="Fetch a URL and extract text content (strips HTML tags).",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "max_chars": {"type": "integer", "description": "Max chars to return"},
                },
                "required": ["url"],
            },
            execute=lambda url, max_chars=15000: _tool_web_fetch(url, max_chars),
            sandbox_safe=True,
        ))
        self.register(AgentTool(
            name="system_info",
            description="Get system information: OS, CPU, RAM, disk, GPU.",
            parameters={"type": "object", "properties": {}},
            execute=_tool_system_info,
            sandbox_safe=True,
        ))
        self.register(AgentTool(
            name="process_list",
            description="List running processes sorted by memory usage.",
            parameters={
                "type": "object",
                "properties": {
                    "filter_name": {"type": "string", "description": "Filter by process name"},
                    "max_results": {"type": "integer", "description": "Max processes (default 30)"},
                },
            },
            execute=lambda filter_name="", max_results=30: _tool_process_list(filter_name, max_results),
            sandbox_safe=True,
        ))
        self.register(AgentTool(
            name="python_exec",
            description="Execute Python code and return output. Useful for calculations and data processing.",
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                },
                "required": ["code"],
            },
            execute=_tool_python_exec,
            dangerous=True,
        ))
        self.register(AgentTool(
            name="process_kill",
            description="Kill a process by PID.",
            parameters={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "Process ID to kill"},
                },
                "required": ["pid"],
            },
            execute=_tool_process_kill,
            dangerous=True,
        ))

    def register(self, tool: AgentTool):
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[AgentTool]:
        return self.tools.get(name)

    def list_tools(self) -> List[AgentTool]:
        return list(self.tools.values())

    def tool_schemas(self) -> str:
        return "\n".join(t.schema_doc() for t in self.tools.values())

    def tool_names(self) -> List[str]:
        return list(self.tools.keys())

    def execute_tool(self, name: str, args: Dict[str, Any]) -> ToolResult:
        tool = self.tools.get(name)
        if not tool:
            return ToolResult(False, f"Unknown tool: {name}. Available: {', '.join(self.tools.keys())}")
        if self.sandbox and not tool.sandbox_safe:
            return ToolResult(False, f"BLOCKED in sandbox mode: {name} is not sandbox-safe")
        if tool.dangerous:
            cmd = args.get("command", "")
            if name == "shell" and _is_dangerous(str(cmd)):
                return ToolResult(False, f"BLOCKED: dangerous command detected: {cmd}")
        try:
            result = tool.execute(**args)
            return result
        except TypeError as e:
            return ToolResult(False, f"Tool argument error: {e}")
        except Exception as e:
            return ToolResult(False, f"Tool execution error: {e}")


_AGENT_SYSTEM_PROMPT = textwrap.dedent("""\
You are an AI computer-use agent. You can interact with the computer to accomplish tasks.

AVAILABLE TOOLS:
{tools}

HOW TO USE TOOLS:
When you need to use a tool, output EXACTLY this format (one tool per step):

```tool
{{"tool": "tool_name", "args": {{"param1": "value1", "param2": "value2"}}}}
```

RULES:
1. Think step by step before acting. Explain your reasoning briefly.
2. Use one tool per step. Wait for the result before proceeding.
3. Read files before modifying them. Understand the codebase first.
4. Prefer read-only tools (read_file, list_dir, search_files, system_info) first.
5. When done, output your FINAL ANSWER starting with "TASK COMPLETE:" followed by a summary.
6. If a tool returns an error, analyze the error and try a different approach.
7. Never execute destructive commands without explaining what you will do.
8. Stay focused on the user's goal. Do not run unnecessary commands.

EXAMPLE:
User: What Python files are in the current directory?

Your response:
I'll list the directory contents to find Python files.

```tool
{{"tool": "list_dir", "args": {{"path": "."}}}}
```

After seeing the result:
TASK COMPLETE: Found 5 Python files: api.py, cli.py, config.py, models.py, run.py
""")

_TASK_COMPLETE_PREFIX = "TASK COMPLETE:"
_TERMINATOR_FENCE = "```tool"
_TASK_DONE_PATTERN = re.compile(r"TASK COMPLETE:\s*(.*)", re.DOTALL)


def _balanced_json_block(text: str) -> Optional[str]:
    """Extract the first balanced ``{...}`` JSON object after a ```tool fence.

    Unlike a non-greedy regex, this tracks string literals and brace depth so
    nested JSON (e.g. write_file content that is itself a JSON document) parses
    correctly instead of stopping at the first ``}``.
    """
    idx = text.find(_TERMINATOR_FENCE)
    if idx < 0:
        return None
    start = text.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    n = len(text)
    for i in range(start, n):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


@dataclass
class AgentStep:
    step_num: int
    thought: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[ToolResult] = None
    elapsed_s: float = 0.0


@dataclass
class AgentResult:
    success: bool
    final_answer: str
    steps: List[AgentStep]
    total_elapsed_s: float = 0.0


class ComputerAgent:
    def __init__(self, model_manager, orchestrator,
                 sandbox: bool = False, max_steps: int = _MAX_STEPS):
        self.model_manager = model_manager
        self.orchestrator = orchestrator
        self.registry = ToolRegistry(sandbox=sandbox)
        self.sandbox = sandbox
        self.max_steps = max_steps
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _build_system_prompt(self) -> str:
        return _AGENT_SYSTEM_PROMPT.format(tools=self.registry.tool_schemas())

    def _parse_tool_call(self, text: str) -> Optional[tuple]:
        raw = _balanced_json_block(text)
        if raw is None:
            return None
        try:
            call = json.loads(raw)
            tool_name = call.get("tool", "")
            args = call.get("args", {})
            return (tool_name, args)
        except (json.JSONDecodeError, AttributeError):
            return None

    def _parse_final_answer(self, text: str) -> Optional[str]:
        match = _TASK_DONE_PATTERN.search(text)
        if match:
            return match.group(1).strip()
        return None

    def _extract_thought(self, text: str) -> str:
        cleaned = text
        idx = cleaned.find(_TERMINATOR_FENCE)
        while idx >= 0:
            end = cleaned.find("```", idx + len(_TERMINATOR_FENCE))
            if end < 0:
                cleaned = cleaned[:idx]
                break
            cleaned = cleaned[:idx] + cleaned[end + 3:]
            idx = cleaned.find(_TERMINATOR_FENCE)
        cleaned = _TASK_DONE_PATTERN.sub("", cleaned)
        return cleaned.strip()

    def run(self, goal: str, callback: Optional[Callable] = None) -> AgentResult:
        self._cancelled = False
        start = time.time()
        steps: List[AgentStep] = []
        system_prompt = self._build_system_prompt()

        from memory import Conversation
        conv = Conversation(max_history=20)
        conv.set_system(system_prompt)
        conv.add("user", f"Goal: {goal}\n\nBegin working on this task. Think step by step and use tools as needed.")

        model_name = self.orchestrator._resolve_executor(None)
        last_answer = ""
        task_done = False

        for step_num in range(1, self.max_steps + 1):
            if self._cancelled:
                break

            step_start = time.time()
            context = conv.get_context()

            try:
                response = self.model_manager.generate(
                    model_name, context,
                    max_tokens=1024,
                    temperature=0.2,
                )
            except Exception as e:
                logger.error(f"Agent generation failed: {e}")
                break

            thought = self._extract_thought(response)
            step = AgentStep(step_num=step_num, thought=thought)

            final_answer = self._parse_final_answer(response)
            if final_answer:
                step.elapsed_s = time.time() - step_start
                steps.append(step)
                last_answer = final_answer
                task_done = True
                break

            tool_call = self._parse_tool_call(response)
            if tool_call is None:
                conv.add("assistant", response)
                conv.add("user", "Please use a tool in the format: ```tool\n{\"tool\": \"name\", \"args\": {...}}\n```")
                continue

            tool_name, tool_args = tool_call
            step.tool_name = tool_name
            step.tool_args = tool_args

            result = self.registry.execute_tool(tool_name, tool_args)
            step.tool_result = result
            step.elapsed_s = time.time() - step_start
            steps.append(step)

            if callback:
                callback(step)

            result_text = result.to_text()
            tool_msg = f"[Tool: {tool_name}] Result:\n{result_text}"
            conv.add("assistant", response)
            conv.add("user", tool_msg)

        total_elapsed = time.time() - start

        if not last_answer:
            if steps:
                last_result = steps[-1].tool_result
                if last_result:
                    last_answer = f"Agent stopped after {len(steps)} steps. Last result: {last_result.output[:500]}"
                else:
                    last_answer = f"Agent stopped after {len(steps)} steps without a final answer."
            else:
                last_answer = "Agent produced no steps."

        return AgentResult(
            success=task_done,
            final_answer=last_answer,
            steps=steps,
            total_elapsed_s=total_elapsed,
        )

    def run_stream(self, goal: str, callback: Optional[Callable] = None):
        self._cancelled = False
        start = time.time()
        steps: List[AgentStep] = []
        system_prompt = self._build_system_prompt()

        from memory import Conversation
        conv = Conversation(max_history=20)
        conv.set_system(system_prompt)
        conv.add("user", f"Goal: {goal}\n\nBegin working on this task. Think step by step and use tools as needed.")

        model_name = self.orchestrator._resolve_executor(None)

        for step_num in range(1, self.max_steps + 1):
            if self._cancelled:
                break

            step_start = time.time()
            context = conv.get_context()
            full_response = ""

            try:
                for chunk in self.model_manager.generate_stream(model_name, context, max_tokens=1024, temperature=0.2):
                    full_response += chunk
                    yield {"type": "thinking", "content": chunk}
            except Exception as e:
                yield {"type": "error", "content": str(e)}
                break

            thought = self._extract_thought(full_response)
            step = AgentStep(step_num=step_num, thought=thought)

            final_answer = self._parse_final_answer(full_response)
            if final_answer:
                step.elapsed_s = time.time() - step_start
                steps.append(step)
                yield {"type": "complete", "answer": final_answer, "steps": len(steps)}
                return

            tool_call = self._parse_tool_call(full_response)
            if tool_call is None:
                conv.add("assistant", full_response)
                conv.add("user", "Please use a tool in the format: ```tool\n{\"tool\": \"name\", \"args\": {...}}\n```")
                continue

            tool_name, tool_args = tool_call
            step.tool_name = tool_name
            step.tool_args = tool_args

            result = self.registry.execute_tool(tool_name, tool_args)
            step.tool_result = result
            step.elapsed_s = time.time() - step_start
            steps.append(step)

            yield {"type": "tool_call", "tool": tool_name, "args": tool_args,
                   "result": result.output[:500], "success": result.success,
                   "step": step_num, "elapsed": step.elapsed_s}

            if callback:
                callback(step)

            result_text = result.to_text()
            tool_msg = f"[Tool: {tool_name}] Result:\n{result_text}"
            conv.add("assistant", full_response)
            conv.add("user", tool_msg)

        total_elapsed = time.time() - start
        answer = f"Agent completed {len(steps)} steps in {total_elapsed:.1f}s"
        yield {"type": "complete", "answer": answer, "steps": len(steps)}


def create_computer_agent(model_manager, orchestrator, sandbox: bool = False,
                          max_steps: int = _MAX_STEPS) -> ComputerAgent:
    return ComputerAgent(model_manager, orchestrator, sandbox=sandbox,
                         max_steps=max_steps)
