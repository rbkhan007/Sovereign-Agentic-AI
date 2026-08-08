import sys
import time

import httpx

PORT = sys.argv[1] if len(sys.argv) > 1 else "8070"
BASE = f"http://localhost:{PORT}"

MODEL = "mythos-nano"
PASSED = 0
FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS  {name} {detail}")
    else:
        FAILED += 1
        print(f"FAIL  {name} {detail}")


def get(path, **kw):
    r = httpx.get(f"{BASE}{path}", timeout=10)
    check(f"GET {path} status", r.status_code == 200, f"({r.status_code})")
    return r


def post(path, payload, timeout=300):
    r = httpx.post(f"{BASE}{path}", json=payload, timeout=timeout)
    check(f"POST {path} status", r.status_code == 200, f"({r.status_code})")
    return r


HEAVY_TIMEOUT = 900  # agent/skill/MCP calls need minutes on CPU/limited VRAM


h = get("/v1/health").json()
check("health payload", h.get("status") == "healthy" and "models_loaded" in h)

m = get("/v1/models").json()
check("models list", len(m.get("data", [])) > 0, f"({len(m.get('data', []))} models)")

c = post("/v1/chat/completions", {
    "messages": [{"role": "user", "content": "Say hi in 3 words."}],
    "use_planning": False,
}).json()
content = c.get("choices", [{}])[0].get("message", {}).get("content", "")
check("no-plan reply", bool(content) and "Error" not in content, f"[{content[:40]}]")

time.sleep(1)

c = post("/v1/chat/completions", {
    "messages": [{"role": "user", "content": "What is 2+2? One word."}],
    "use_planning": True,
}).json()
content = c.get("choices", [{}])[0].get("message", {}).get("content", "")
check("planning reply", bool(content) and "Error" not in content, f"[{content[:40]}]")
check("planning has thinking field", "thinking" in c)

cfg = get("/v1/config").json()
check("config threads", isinstance(cfg.get("threads"), int) and cfg["threads"] > 0)
check("config parallel.enabled", "enabled" in cfg.get("parallel", {}))
check("config prune.interval_hours", "interval_hours" in cfg.get("prune", {}))

c = post("/v1/chat/completions", {
    "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
    "use_planning": False,
    "parallel": True,
}, timeout=300).json()
content = c.get("choices", [{}])[0].get("message", {}).get("content", "")
check("parallel reply", bool(content) and "Error" not in content, f"[{content[:40]}]")
check("parallel has runner_model", "runner_model" in c)
check("parallel has parallel_candidates", "parallel_candidates" in c)

g = post("/v1/generate", {
    "model": MODEL, "prompt": "Say hello in 2 words", "max_tokens": 50,
}, timeout=60).json()
text = g.get("choices", [{}])[0].get("text", "")
check("generate", bool(text) and "Error" not in text, f"[{text[:40]}]")

s = post("/v1/chat/completions", {
    "messages": [{"role": "user", "content": "Count 1 2 3."}],
    "use_planning": False,
    "stream": True,
}, timeout=120)
check("stream content-type", "text/event-stream" in s.headers.get("content-type", ""))
check("stream done marker", "data: [DONE]" in s.text, f"(got {len(s.text)} bytes)")

r_clear = post("/v1/chat/clear?conv_id=test-conv", {})
check("chat clear", r_clear.status_code == 200)

# Agents & skills & MCP
ag = get("/v1/agents").json()
check("agents list", len(ag.get("agents", [])) > 0, f"({len(ag.get('agents', []))} agents)")
sk = get("/v1/skills").json()
check("skills list", len(sk.get("skills", [])) > 0, f"({len(sk.get('skills', []))} skills)")
a1 = get("/v1/agents/general").json()
check("agent detail", bool(a1.get("system_prompt")))
s1 = get("/v1/skills/summarize").json()
check("skill detail", bool(s1.get("template")))

ra = post("/v1/agents/agent_x/run", {
    "message": "Write a python function that returns 42. Short.",
    "use_planning": False,
}, timeout=HEAVY_TIMEOUT).json()
rc = ra.get("response", "")
check("agent run reply", bool(rc) and "Error" not in rc, f"[{rc[:40]}]")

rs = post("/v1/skills/summarize/run", {
    "input": "The quick brown fox jumps over the lazy dog. It is a well-known pangram used in typing tests.",
}, timeout=HEAVY_TIMEOUT).json()
check("skill run reply", bool(rs.get("response")) and "Error" not in rs.get("response", ""), f"[{rs.get('response','')[:40]}]")

m = post("/mcp", {"jsonrpc": "2.0", "method": "tools/list", "id": 1}).json()
tools = m.get("result", [])
names = [t.get("name") for t in tools]
check("mcp tools list", "chat" in names and "agent_x" in names and "summarize" in names, f"({len(tools)} tools)")

m = post("/mcp", {"jsonrpc": "2.0", "method": "tools/call",
                  "params": {"name": "chat", "arguments": {"input": "Say hi in 2 words."}},
                  "id": 2}, timeout=HEAVY_TIMEOUT).json()
check("mcp tools/call", bool(m.get("result")) and "Error" not in str(m.get("result", "")), f"[{str(m.get('result',''))[:40]}]")

get("/")

print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
