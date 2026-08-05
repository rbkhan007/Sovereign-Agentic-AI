import hashlib
import json
import logging
import os
import threading
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import CONFIG

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
NEXT_BUILD_DIR = os.path.join(FRONTEND_DIR, "build")

_CACHE_LOCK = threading.Lock()
_CACHE = {"mtime": None, "size": None, "html": None, "etag": None}
_STATIC_MOUNTED = False
_NEXT_MOUNTED = False

FALLBACK_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sovereign-Agentic-AI</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #1a1a2e; color: #e8e8f0; height: 100vh; display: flex; flex-direction: column; }
  .header { padding: 12px 24px; background: #16213e; border-bottom: 1px solid #2a2a4a;
            display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 16px; }
  .header select { margin-left: auto; background: #1a1a2e; color: #e8e8f0;
                   border: 1px solid #2a2a4a; border-radius: 6px; padding: 4px 8px; }
  .chat { flex: 1; overflow-y: auto; padding: 24px 20%; display: flex; flex-direction: column; gap: 16px; }
  @media (max-width: 900px) { .chat { padding: 16px; } }
  .msg { max-width: 780px; width: 100%; margin: 0 auto; }
  .msg.user { text-align: right; }
  .bubble { display: inline-block; text-align: left; background: #1e2a3e; border: 1px solid #2a2a4a;
            border-radius: 16px; padding: 12px 18px; font-size: 14px; line-height: 1.6;
            white-space: pre-wrap; word-break: break-word; max-width: 85%; }
  .msg.user .bubble { background: #2d2b6e; border: none; }
  .empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
           gap: 12px; color: #9898b0; }
  .empty h2 { color: #e8e8f0; font-size: 20px; }
  .input-area { padding: 16px 20%; background: #1a1a2e; border-top: 1px solid #2a2a4a; }
  @media (max-width: 900px) { .input-area { padding: 12px 16px; } }
  .input-wrap { max-width: 780px; margin: 0 auto; display: flex; gap: 10px;
                background: #16213e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 8px 12px; }
  .input-wrap:focus-within { border-color: #6c63ff; }
  textarea { flex: 1; background: transparent; border: none; color: #e8e8f0; font-size: 14px;
             font-family: inherit; resize: none; min-height: 24px; max-height: 120px; outline: none; }
  button { background: #6c63ff; color: white; border: none; border-radius: 8px;
           padding: 8px 18px; font-size: 14px; cursor: pointer; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
</head>
<body>
<div class="header">
  <h1>Sovereign-Agentic-AI</h1>
  <select id="modelSelect"></select>
</div>
<div class="chat" id="chat">
  <div class="empty" id="empty">
    <div style="font-size:48px">&#129302;</div>
    <h2>How can I help you today?</h2>
    <p>Multi-agent system running 100% locally on your GPU</p>
    <p>Rhasan Indie's Dashboard | Model | VRAM | Chat</p>
  </div>
</div>
<div class="input-area">
  <div class="input-wrap">
    <textarea id="inputBox" rows="1" placeholder="Ask anything..."></textarea>
    <button id="sendBtn">Send</button>
  </div>
</div>
<script>
let currentModel = '', processing = false;
const chat = document.getElementById('chat'), empty = document.getElementById('empty');
const inputBox = document.getElementById('inputBox'), sendBtn = document.getElementById('sendBtn');
const modelSelect = document.getElementById('modelSelect');

async function loadModels() {
  try {
    const res = await fetch('/v1/models');
    const data = await res.json();
    data.data.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.role ? m.id + ' (' + m.role + ')' : m.id;
      modelSelect.appendChild(opt);
    });
    const pref = data.data.find(m => (m.role || '').toLowerCase().includes('executor')) || data.data[0];
    if (pref) currentModel = modelSelect.value = pref.id;
  } catch (e) { console.error(e); }
}

function addMessage(role, content) {
  empty.style.display = 'none';
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const b = document.createElement('div');
  b.className = 'bubble';
  b.textContent = content;
  div.appendChild(b);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return b;
}

async function send() {
  const text = inputBox.value.trim();
  if (!text || processing) return;
  inputBox.value = '';
  sendBtn.disabled = true;
  processing = true;
  addMessage('user', text);
  const bubble = addMessage('assistant', 'Thinking...');
  let content = '';
  try {
    const res = await fetch('/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: currentModel, messages: [{ role: 'user', content: text }], use_planning: true }),
    });
    if (!res.ok || !res.body) throw new Error('Request failed (' + res.status + ')');
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\\n\\n')) !== -1) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        if (!raw.startsWith('data:')) continue;
        const dataStr = raw.slice(5).trim();
        if (!dataStr || dataStr === '[DONE]') continue;
        let evt;
        try { evt = JSON.parse(dataStr); } catch (_) { continue; }
        if (evt.type === 'response') {
          content += evt.content;
          bubble.textContent = content;
          chat.scrollTop = chat.scrollHeight;
        } else if (evt.type === 'error') {
          content = '[Error] ' + evt.content;
          bubble.textContent = content;
        }
      }
    }
    if (!content) bubble.textContent = '[No response]';
  } catch (e) {
    bubble.textContent = '[Error] ' + e.message;
  }
  sendBtn.disabled = false;
  processing = false;
}

sendBtn.onclick = send;
inputBox.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
loadModels();
</script>
</body>
</html>
"""


def _is_loopback(request: Request) -> bool:
    # Starlette's TestClient reports host "testclient", which simulates localhost.
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def _auth_bootstrap(loopback: bool = True) -> str:
    token = getattr(CONFIG, "api_token", "") or ""
    if not token:
        return ""
    # Only embed the API token for loopback clients. Embedding it in HTML served
    # on a non-loopback bind would hand the token to anyone who can reach the
    # port, defeating --api-token. Remote/LAN clients must authenticate out of band.
    if not loopback:
        logger.warning("API token set but client is non-loopback; token withheld from HTML")
        return ""
    token_js = json.dumps(token).replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        "<script>window.API_TOKEN=" + token_js +
        ";if(window.API_TOKEN){var _f=window.fetch;window.fetch=function(u,o){o=o||{};"
        "o.headers=o.headers||{};if(typeof u==='string'&&(u.indexOf('/v1/')===0||u.indexOf('/mcp')===0))"
        "{o.headers['Authorization']='Bearer '+window.API_TOKEN;}return _f.call(this,u,o);};}</script>"
    )


def _get_next_html_path(path: str) -> str:
    """Map URL path to Next.js static export HTML file."""
    # Normalize path
    if not path or path == "/":
        return os.path.join(NEXT_BUILD_DIR, "server", "app", "index.html")

    # Remove trailing slash
    path = path.rstrip("/")
    if not path:
        path = "/"

    # Prevent path traversal: ensure resolved path stays within NEXT_BUILD_DIR
    html_path = os.path.join(NEXT_BUILD_DIR, "server", "app", path.lstrip("/") + ".html")
    resolved = os.path.realpath(html_path)
    if not resolved.startswith(os.path.realpath(NEXT_BUILD_DIR)):
        return os.path.join(NEXT_BUILD_DIR, "server", "app", "index.html")

    # Check if HTML file exists for this route
    if os.path.isfile(html_path):
        return html_path

    # Check for nested routes (e.g., /chat/ -> /chat.html in static export)
    # Next.js static export puts nested routes as .html files too
    parts = path.strip("/").split("/")
    if len(parts) > 1:
        # Try parent directory
        parent = "/".join(parts[:-1])
        if parent:
            parent_html = os.path.join(NEXT_BUILD_DIR, "server", "app", parent + ".html")
            if os.path.isfile(parent_html):
                return parent_html

    # Default to index.html for SPA-like behavior
    return os.path.join(NEXT_BUILD_DIR, "server", "app", "index.html")


def _read_next_html(path: str, loopback: bool = True) -> tuple:
    """Read Next.js HTML file from build output and inject auth bootstrap."""
    html_path = _get_next_html_path(path)
    try:
        mtime = os.path.getmtime(html_path)
        size = os.path.getsize(html_path)
    except OSError:
        return None, None

    with _CACHE_LOCK:
        cache_key = (mtime, size, path, getattr(CONFIG, "api_token", "") or "")
        if _CACHE.get("cache_key") == cache_key and _CACHE.get("html") is not None:
            return _CACHE["html"], _CACHE["etag"]

        try:
            with open(html_path, "rb") as f:
                data = f.read()
        except OSError:
            return None, None

        html = data.decode("utf-8", errors="replace")
        # Inject auth bootstrap before </head> or at the start of <body>
        auth_script = _auth_bootstrap(loopback)
        if auth_script and '</head>' in html:
            html = html.replace('</head>', auth_script + '</head>', 1)
        elif auth_script and '<body>' in html:
            html = html.replace('<body>', '<body>' + auth_script, 1)

        etag = '"' + hashlib.md5(html.encode("utf-8"), usedforsecurity=False).hexdigest() + '"'
        _CACHE.update(cache_key=cache_key, mtime=mtime, size=size, html=html, etag=etag)  # type: ignore
        return html, etag


def _mount_nextjs(api_app: FastAPI):
    global _NEXT_MOUNTED
    if _NEXT_MOUNTED:
        return

    if not os.path.isdir(NEXT_BUILD_DIR):
        logger.info("No Next.js build directory at %s", NEXT_BUILD_DIR)
        return

    try:
        # Mount static assets from build/static/
        static_dir = os.path.join(NEXT_BUILD_DIR, "static")
        if os.path.isdir(static_dir):
            api_app.mount("/_next/static", StaticFiles(directory=static_dir), name="next-static")
            logger.info("Mounted Next.js static assets from %s", static_dir)

        # Also try mounting from chunks directory directly for compatibility
        chunks_dir = os.path.join(static_dir, "chunks")
        if os.path.isdir(chunks_dir):
            api_app.mount("/_next/static/chunks", StaticFiles(directory=chunks_dir), name="next-chunks")

        css_dir = os.path.join(static_dir, "css")
        if os.path.isdir(css_dir):
            api_app.mount("/_next/static/css", StaticFiles(directory=css_dir), name="next-css")

        _NEXT_MOUNTED = True
        logger.info("Next.js build mounted from %s", NEXT_BUILD_DIR)
    except Exception as e:
        logger.warning("Failed to mount Next.js build: %s", e)


def create_web_app(api_app: FastAPI) -> FastAPI:
    global _STATIC_MOUNTED
    os.makedirs(STATIC_DIR, exist_ok=True)

    if not _STATIC_MOUNTED and not any(getattr(r, "path", None) == "/static" for r in api_app.routes):
        api_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
        _STATIC_MOUNTED = True

    # Serve generated images (image_gen.py writes PNGs here).
    generated_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
    os.makedirs(generated_dir, exist_ok=True)
    if not any(getattr(r, "path", None) == "/generated" for r in api_app.routes):
        api_app.mount("/generated", StaticFiles(directory=generated_dir), name="generated")

    _mount_nextjs(api_app)

    FAVICON_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#6366f1"/>'
        '</linearGradient></defs>'
        '<rect x="2" y="2" width="60" height="60" rx="14" fill="url(#g)"/>'
        '<path d="M32 14c2.5 6 5.5 9 10 9.5-4.5.5-7.5 3.5-10 9.5 0-9.5-6-10-10-9.5 4.5-.5 7.5-3.5 10-9.5z" fill="#0b1020"/>'
        '<circle cx="32" cy="39" r="7" fill="#0b1020"/></svg>'
    )

    @api_app.get("/favicon.ico", include_in_schema=False)
    @api_app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return Response(
            content=FAVICON_SVG,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @api_app.get("/chat", include_in_schema=False)
    @api_app.get("/", include_in_schema=False)
    @api_app.get("/workspace", include_in_schema=False)
    @api_app.get("/database", include_in_schema=False)
    @api_app.get("/models", include_in_schema=False)
    @api_app.get("/admin", include_in_schema=False)
    @api_app.get("/tools", include_in_schema=False)
    @api_app.get("/settings", include_in_schema=False)
    @api_app.get("/graph", include_in_schema=False)
    @api_app.get("/help", include_in_schema=False)
    async def web_ui(request: Request):
        # HTML shells carry no data: auth is enforced on the /v1/* and /mcp
        # API routes. The auth bootstrap injects the token into the browser so
        # client-side fetch() calls are authenticated automatically. For
        # non-loopback clients the token is withheld (see _auth_bootstrap).
        loopback = _is_loopback(request)
        if _NEXT_MOUNTED and os.path.isdir(os.path.join(NEXT_BUILD_DIR, "server", "app")):
            html, etag = _read_next_html(request.url.path, loopback)
            if html is None:
                html, etag = _read_next_html("/", loopback)
        else:
            html, etag = None, None

        if html is None:
            html = FALLBACK_PAGE
            etag = '"' + hashlib.md5(html.encode("utf-8"), usedforsecurity=False).hexdigest() + '"'
            auth_script = _auth_bootstrap(loopback)
            if auth_script and '</head>' in html:
                html = html.replace('</head>', auth_script + '</head>', 1)
            elif auth_script and '<body>' in html:
                html = html.replace('<body>', '<body>' + auth_script, 1)

        if etag:
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304)
            headers = {"ETag": etag, "Cache-Control": "no-cache"}
        else:
            headers = {"Cache-Control": "no-cache"}
        return HTMLResponse(html, headers=headers)

    return api_app
