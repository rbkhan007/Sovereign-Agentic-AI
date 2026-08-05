# Sovereign-Agentic-AI

<p align="center">
  <img src="frontend/public/favicon.ico" width="64" height="64" alt="logo"/>
</p>

<p align="center">
  <b>A fully local, privacy-first, multi-agent LLM system that plans, routes, and executes — entirely on your hardware.</b>
</p>

<p align="center">
  <img alt="Tests" src="https://img.shields.io/badge/tests-703%20%2F%200-brightgreen">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="Backend" src="https://img.shields.io/badge/backend-llama.cpp%20(Vulkan)-orange">
  <img alt="Frontend" src="https://img.shields.io/badge/frontend-Next.js%20%2B%20TS-8A2BE2">
  <img alt="Audit" src="https://img.shields.io/badge/static%20audit-clean-success">
</p>

---

Sovereign-Agentic-AI is a local-first agentic stack: a small **Strategist** model
(`Hy-MT2-1.8B`) writes a plan, an **adaptive harness** ranks the best **Executor**
model for the job, and (optionally) several executors answer in parallel while the
strategist **judges** the best reply. Everything runs through `llama.cpp` on CPU/Vulkan
— no data leaves your machine unless you explicitly opt into a cloud fallback.

> **Privacy by design.** Chat, memory, the knowledge graph, image generation, vision,
> AutoML and the self-healing agent all run locally. The only network calls are the
> optional OpenAI/Claude/Groq/OpenRouter/Gemini fallback and (opt-in) web search.

---

## ✨ Features

| Area | What it does |
|------|--------------|
| **Multi-agent pipeline** | Strategist plans → Executor(s) run → Strategist judges (parallel mode). |
| **Adaptive routing** | Per-`(task, model)` fitness score with epsilon-greedy exploration. |
| **Parallel execution** | Up to `parallel_max` executors answer concurrently; best is selected by 0–10 judge score. |
| **Hardware auto-tune** | Detects RAM/VRAM, sets threads + context, runs a live safety monitor. |
| **Streaming + auto-stream** | SSE token streaming; auto-stream picks stream-vs-batch per request. |
| **Workspaces** | Isolated chats, file upload + chunk-embedded knowledge search. |
| **Knowledge graph** | Obsidian-style `[[wiki-links]]`, `#tags`, backlinks, vector + graph hybrid search, recursive-CTE shortest path. |
| **Agents & skills** | Named personas + reusable skills via API / CLI / MCP, persisted as JSON. |
| **Web UI** | Next.js + Tailwind glassmorphism dashboard (dark/light), live sparklines, streaming. |
| **Image generation** | Opt-in Stable Diffusion via `--image-gen` (CPU, RAM-guarded). |
| **Vision** | Opt-in `moondream2` image understanding via `--vision` (CPU). |
| **AutoML** | Opt-in Auto-Sklearn training via `--automl` (Linux). |
| **Self-healing agent** | Diagnoses + proposes fixes for Python; **execution gated** behind `--allow-unsafe-healing`. |
| **OpenAI-compatible API** | Drop-in `/v1/chat/completions`. |
| **Cloud fallback** | Optional, sliding-window rate-limited OpenAI/Claude/Groq/OpenRouter/Gemini. |

---

## 🏗️ Architecture

```mermaid
flowchart TD
    U[User / API / CLI] --> R[Router.classify_task]
    R --> O[Orchestrator]
    O --> P[Strategist: plan<br/>2 candidate plans]
    O --> M[(pgvector memory<br/>+ knowledge graph)]
    O --> W[Optional web search]
    P --> E[Executor(s) generate]
    E --> J[Strategist judges<br/>0-10 score]
    J --> H[Harness.record<br/>fitness update]
    H --> RES[Response + memory store]
    RES --> U

    subgraph Models
        S[Hy-MT2 1.8B · Strategist]
        X[MiniCPM 1B · Executor]
        G[Any auto-discovered .gguf]
    end
    O -.uses.-> Models
```

**Request lifecycle in one paragraph.** `Router.classify_task()` buckets the prompt
(`code|math|summarize|translate|tool|creative|general`). The `Orchestrator` retrieves
relevant memories + knowledge-graph context, asks the Strategist to **plan** (injecting
the plan as a system hint), then `ModelRouter.select_executors()` ranks executor models
by harness fitness and load state. In parallel mode the top `parallel_max` executors each
generate an answer; the Strategist **scores** every candidate 0–10 and the highest wins.
The chosen `(task, model, ok, latency, tokens)` updates the harness, and the final answer
is stored back to memory.

---

## ⚙️ How it works (the math)

### 1. Task classification
A keyword scan maps the prompt to a bucket:

```text
classify_task(text) → one of
  {code, math, summarize, translate, tool, creative, general}
```

### 2. Planning — two candidate plans
The Strategist generates **2 candidate plans** (`i ∈ {0,1}`) at slightly different
temperatures (`0.3 + i·0.1`). Each is scored and the best is kept:

```text
score(plan) = len(plan)
             + 10 · 𝟙{"FINAL_ANSWER" ∈ plan}
             +  5 · 𝟙{len(plan) > 50}

best_plan = argmax_candidates score(plan)
```

### 3. Adaptive harness — fitness score
Every `(task, model)` earns a fitness from measured **success**, **speed**, and
**recency**:

```text
success = 1 − errors / attempts

speed   = min(2.0, 1 / avg_latency)        # avg_latency in seconds
recent  = decay ^ age ,  age = generation − last_gen
            decay = 0.95 (default)

fitness(task, model) = 60·success + 30·speed + 10·recent
```

`ModelRouter.rank_for_task()` sorts executors by `fitness` (capability-matched first,
then already-loaded first). Exploration uses **epsilon-greedy**:

```text
choose(task, candidates):
    with probability ε (ε = 0.15):  return random(candidates)   # explore
    else:                           return ranked(task, candidates)[0]  # exploit
```

### 4. Parallel execution & judging
Up to `parallel_max` (default 2) executors answer concurrently
(`ThreadPoolExecutor`, ≤4 workers). The Strategist judges each 0–10:

```text
judge(Q, A) ∈ [0, 10]          # parsed from the strategist's numeric reply
final = argmax_{m ∈ candidates} judge(Q, A_m)
```

When the judge is unavailable, scoring falls back to answer length.

### 5. Auto-streaming decision
Per request, the orchestrator streams when appropriate and otherwise batches:

```text
should_auto_stream =
    auto_stream_enabled
    AND max_tokens ≤ auto_stream_max_tokens      # cap = 2048 (default)
    AND ( use_planning
        ∨ len(message) > 100
        ∨ message matches code|creative keywords )

# Streaming requests are hard-capped:
max_tokens := min(max_tokens, auto_stream_max_tokens)
```

The SSE protocol emits a terminal event so clients always know when a stream ends:

```json
{"type":"start",   "model":"minicpm-v9"}
{"type":"thinking","content":"..."}          // optional
{"type":"response","content":"..."}          // one per token chunk
{"type":"done",    "model":"minicpm-v9",
 "tokens": 142, "elapsed": 3.1}
```

### 6. Throughput
A 60-second sliding window gives a realistic tokens/sec that ignores the flat cumulative
average:

```text
tokens_per_sec_window = Σ tokens in last 60s  /  60
tokens_per_sec        = total_tokens_out / uptime
```

### 7. ARC reasoning accuracy
Grid-reasoning accuracy over `arc/training.json` (temperature 0, `max_tokens=512`):

```text
accuracy = correct / total

_matches(pred, target, exact):
    if exact:   return parse_grid(pred) == target
    else:       return (len(pred) ≤ len(target))
                ∧ (every pred row has len == len(target[0]))
                ∧ (element-wise pred == target)
```

---

## 📤 Outputs

What the system actually produces:

| Output | Shape | Notes |
|--------|-------|-------|
| **Chat completion** | OpenAI-style JSON | `choices[0].message.content` (+ optional `thinking`). |
| **Streaming events** | SSE `start → thinking? → response* → done` | Token-by-token; `done` carries `tokens` + `elapsed`. |
| **Plan / thinking** | text | Strategist plan, surfaced in UI and SSE. |
| **Ranked candidates** | dict | In parallel mode: each model's answer + judge score. |
| **Memory** | pgvector rows | Q/A pairs + graph nodes/edges stored for later retrieval. |
| **Knowledge graph** | nodes/edges/tags | Wiki-links, `#tags`, backlinks, shortest path. |
| **Images** | `generated/*.png` | From `--image-gen` (256–512 px, 8–40 steps). |
| **Vision** | description text | From `--vision` (moondream2). |
| **AutoML model** | `.pkl` | From `--automl` training. |
| **Metrics** | JSON | Per-model `success_rate`, `avg_latency`, `tokens_per_sec_window`. |
| **Harness stats** | JSON | Per-`(task,model)` fitness, reset/adjust/export. |

---

## 🚀 Quick start

### Option A — pip-installable package (recommended)

```bash
pip install -e .                    # backend + 4 CLI entry points
sovereign-llm                       # full mode: Web UI + CLI + API
```

| Command | Mode |
|---|---|
| `sovereign-llm` | Full mode: Web UI + CLI + API |
| `sovereign-llm-web` | Web UI + API only |
| `sovereign-llm-cli` | Terminal CLI only |
| `sovereign-llm-api` | API server only |

### Option B — run from source

```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
# GPU (Vulkan): set CMAKE_ARGS="-DGGML_VULKAN=on" && pip install --force-reinstall llama-cpp-python --no-cache-dir
python run.py                    # full mode (recommended)
```

Place `.gguf` files in `models/` (expected: `Hy-MT2-1.8B-Q4_K_M.gguf`,
`MiniCPM5-1B-Agentic-v9-f16.gguf`). Any `.gguf` dropped there is auto-discovered.

### Common flags

```bash
python run.py --port 8080 --api-token secret
python run.py --image-gen --vision --automl
python run.py --healing --allow-unsafe-healing   # healing EXECUTES code only with this flag
python run.py --db --db-password postgres        # PostgreSQL + pgvector memory
python run.py --nextjs                           # Next.js dev server on :3001
```

---

## 🔌 API (condensed)

All routes are under `http://localhost:{port}`. Full reference in
[AGENTS.md](AGENTS.md).

| Method | Path | Purpose |
|:--|:-----|:--|
| POST | `/v1/chat/completions` | OpenAI-compatible chat |
| POST | `/v1/chat/stream` · `/v1/chat/auto-stream` | Token streaming / adaptive streaming |
| GET | `/v1/models` · `/v1/models/load` · `/v1/models/unload` | Model lifecycle |
| POST | `/v1/memory/search` · `/v1/memory/store` | pgvector memory |
| GET/POST | `/v1/agents` · `/v1/skills` | Personas + skills CRUD |
| POST | `/v1/loras/train` · `/v1/images/generate` · `/v1/vision/analyze` | LoRA / image / vision |
| GET | `/v1/graph/hybrid` · `/v1/graph/path` | Graph search + shortest path |
| GET | `/v1/router/stats` · `/v1/metrics` · `/v1/hardware` | Telemetry |
| GET/POST | `/mcp` | MCP tool discovery + JSON-RPC |

---

## 🔐 Security & hardening (v1.0.0)

These were reviewed and fixed before release:

- **Self-healing RCE gate** — `heal()` refuses to run caller-supplied Python unless
  `--allow-unsafe-healing` is passed. `--healing` alone only enables diagnosis.
- **Stored XSS** — `/generated` is served by `SafeStaticFiles`: `X-Content-Type-Options:
  nosniff` and `Content-Disposition: attachment` for inline-dangerous types (`.html`,
  `.svg`, `.xml`, `.js`).
- **Graph referential integrity** — `#tags` are materialized as real graph nodes
  (`node_type='tag'`) and linked node→node, so tag edges no longer corrupt the
  `edges` FK.
- **Vision API** — switched to the correct `moondream2` `answer_question` pipeline.

> ⚠️ Keep `--allow-unsafe-healing` off on any machine reachable from untrusted
> networks. It executes arbitrary Python with the server's privileges.

---

## 🧪 Testing & quality

```bash
python test_all.py          # 703 offline tests, 0 failures (no model/DB loads)
python test_system.py 8070   # live integration tests (running server)
python test_load.py --port 8070
python run_deep_audit.py     # mypy + pyflakes + bandit + vulture + pydocstyle + ESLint
```

| Check | Result |
|-------|--------|
| Unit tests | **703 / 703 passed** |
| Pyflakes / Bandit / Vulture | clean |
| TypeScript build | pass (13 routes) |
| ESLint (frontend) | pass |

Non-critical, deferred items are tracked in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md); the
full audit narrative is in [`AUDIT_REPORT.md`](AUDIT_REPORT.md).

---

## 💻 Hardware profile (reference build)

| Component | Spec | Usage |
|-----------|------|-------|
| GPU | AMD Radeon RX 5600 XT (6 GB, Vulkan) | Hy-MT2 ~1.1 GB, MiniCPM ~2 GB |
| CPU | Intel i3-10100F (4C/8T) | threads auto-set to `cores // 2` |
| RAM | 16 GB | context capped to 2048 when < 16 GB |
| Disk | 256 GB SSD | pgvector + IVFFlat/HNSW indexes |

---

## 📊 Comparison

| Feature | **Sovereign-Agentic-AI** | Ollama | LM Studio | LocalAI |
|---|---|---|---|---|
| Multi-agent planning + judging | ✅ | ❌ | ❌ | ❌ |
| Adaptive harness routing | ✅ | ❌ | ❌ | ❌ |
| pgvector memory + graph | ✅ | ❌ | ❌ | ❌ |
| Parallel multi-model + judge | ✅ | ❌ | ❌ | ❌ |
| Self-healing (gated) | ✅ | ❌ | ❌ | ❌ |
| AutoML (Linux) | ✅ | ❌ | ❌ | ❌ |
| Hardware auto-tune + monitor | ✅ | manual | manual | manual |
| Vision + image-gen + LoRA (CPU) | ✅ | partial | partial | partial |

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

<p align="center"><sub>Built by <a href="https://rhasan-dev-bd-com.vercel.app/">Rakibul Hasan</a> (Rhasan_Indie_dev).</sub></p>
