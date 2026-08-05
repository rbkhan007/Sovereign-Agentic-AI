# Sovereign-Agentic-AI — Local Multi-Agent System

**Backend**: llama.cpp via `llama-cpp-python` (Vulkan on AMD GPUs)
**Models**: Hy-MT2-1.8B (Strategist) + MiniCPM-1B (Executor/ToolExecutor)
**Memory**: Optional PostgreSQL + pgvector (semantic memory)

---

## System Overview

A fully local, privacy-first multi-agent chat system. Two small specialized models cooperate:

| Agent (Model) | Role | Typical Use |
| :--- | :--- | :--- |
| **Hy-MT2** 1.8B Q4_K_M | Strategist / Planner | Decomposes the user request and produces a short plan (2 candidate plans, best selected) |
| **MiniCPM** 1B (v9 / tooluse) | Executor / ToolExecutor | Produces the final answer from the plan |

The flow is **single-pass**: plan (if enabled) → execute. There is no iterative agentic loop and no automatic error-retry.

---

## Hardware & Software

- **CPU**: x86_64 with AVX2; threads auto-set to `cpu_count() // 2` (e.g. 4 on an i3-10100F).
- **RAM**: 8 GB minimum, 16 GB recommended.
- **GPU (optional)**: any GPU supported by a llama.cpp backend (CUDA/Vulkan/Metal). `n_gpu_layers=-1` offloads everything; set to `0` for CPU-only.
- **OS**: Windows / Linux / macOS. Python **3.10+** (tested on 3.12).

### Verified GPU (this project)
- AMD Radeon RX 5600 XT (6 GB VRAM) via the Vulkan backend (`ggml-vulkan.dll` built from source).
- Hy-MT2 1.8B Q4_K_M ≈ 1.1 GB VRAM; MiniCPM 1B F16 ≈ 2 GB. Typical usage ~3–4 GB (well within 6 GB budget).

---

## Installation

```bash
python -m venv venv
venv\Scripts\activate          # Windows (or source venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
```

For GPU acceleration, rebuild `llama-cpp-python` against your backend first, e.g.:

```bash
set CMAKE_ARGS="-DGGML_VULKAN=on"
pip install --force-reinstall llama-cpp-python --no-cache-dir
```

### Models

Place your `.gguf` files in the `models/` directory. Expected filenames are defined in `config.py`:

| File | Name | Role |
| :--- | :--- | :--- |
| `Hy-MT2-1.8B-Q4_K_M.gguf` | `hy-mt2` | Strategist |
| `MiniCPM5-1B-Agentic-v9-f16.gguf` | `minicpm-v9` | Executor |
| `minicpm5-1b-agentic-tooluse.F16.gguf` | `minicpm-tooluse` | ToolExecutor |

Any other `.gguf` dropped into `models/` is auto-discovered and registered as an `Executor` (general capability). Use `--add-model PATH --add-model-name NAME --add-model-role Executor` to register a file from outside `models/`. The web UI defaults to the first *executor*-role model. Models are loaded lazily on first use.

### Optional: PostgreSQL + pgvector memory

Requires PostgreSQL 15+ with the `vector` extension. The app auto-creates the database if missing (requires superuser or CREATEDB privilege).

```bash
python run.py --db --db-password your_password
```

If PostgreSQL is unavailable, the app logs a warning and continues in in-memory mode.

### Optional: OpenAI / Claude cloud fallback

```bash
python run.py --openai-key sk-...        # OpenAI cloud fallback
python run.py --cloud claude             # Claude (Anthropic) via ANTHROPIC_API_KEY env var
```

When set, model load/generation failures fall back to `openai/{chat_model}` (`gpt-4o-mini` by default). Cloud providers can also be auto-enabled via environment variables: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`.

---

## Running

```bash
python run.py                    # Full mode: web UI + CLI (recommended)
python run.py web                # Web UI only
python run.py cli                # Terminal CLI only
python run.py api                # API server only
python run.py --setup            # First-run config wizard
python run.py --port 8080        # Custom port
python run.py --threads 4        # CPU threads (propagated to all models)
python run.py --api-token secret # Require Bearer token on /v1/* and /mcp
python run.py --no-parallel      # Disable parallel multi-model generation
python run.py --parallel-max 3   # Max executor models to run in parallel
python run.py --prune-hours 12   # Auto-prune interval (default 6h)
python run.py --prune-days 60    # Auto-prune max age (default 30d)
python run.py --sandbox          # Sandbox mode: no DB writes, isolated conversations
python run.py --vram 4096        # VRAM budget in MB for model loading (0 = auto-detect)
python run.py --gen-timeout 60   # Generation timeout (default 240s; hung inference auto-recovers)
python run.py --cloud groq       # Free-tier cloud preset: openai|groq|openrouter|gemini|claude
python run.py --no-auto-tune     # Disable hardware auto-tune (RAM/VRAM/threads/ctx)
python run.py --no-auto-load     # Disable selection-room preloading of executor models
python run.py --add-model C:\path\to\model.gguf --add-model-name mymodel --add-model-role Executor
python run.py --force-port       # Kill the process on the port (default: auto-switch to a free port)
python run.py --db --db-password postgres
python run.py --openai-key sk-...
```

`start.bat` (DB mode), `start_simple.bat` (no DB), and `launch.bat` (AMD RX 5600 XT optimized) are one-click launchers.

**Load / balance testing:**

```bash
python test_load.py                          # quick check against :8070
python test_load.py --port 8080 --concurrency 16 --requests 500
python test_load.py --chat --chat-count 4    # include real model generations
python test_load.py --health-check           # single health check then exit
```

Flags: `--concurrency` (default 8), `--requests` (120), `--timeout` (30s), `--error-limit` (5.0%, drives PASS/FAIL verdict + exit code), `--chat-count` (3), `--quiet`. Cheap endpoints (health, system, models, metrics, router, hardware, config, conversations, memory, models/stats) are hammered from a thread pool; `--chat` adds real generations against `/v1/chat/completions`.

### CLI commands

```
/help                Show all commands
/status              Live status: HUD, VRAM, models loaded, config
/model <name>        Switch model
/models              List models
/preload <name>      Load a model into VRAM now
/unload [name]       Unload model(s) from VRAM
/plan on|off         Toggle planning/reasoning
/think on|off        Show/hide thinking output
/parallel on|off     Ensemble: N models answer, judge picks best (off = live token streaming)
/code on|off         Toggle coding-agent mode (code system prompt, code-capable model)
/context show|set|clear  Inspect / set system prompt, see recent context
/temperature <0-2>   Override sampling temperature
/max <tokens>        Override max output tokens
/timeout <seconds>   Change generation watchdog timeout
/retry               Re-run last prompt
/new                 Start a fresh conversation
/save [name]         Persist conversation to disk (sessions/)
/load <name>         Restore a saved conversation
/sessions            List saved conversations
/tokens              Token usage this session
/vram                VRAM usage per loaded model
/openai <key>        Set OpenAI API key
/db on|off           Toggle database memory
/prune               Manually prune old memories
/harness             Show adaptive harness scores per task/model
/harness reset       Reset harness scores to defaults
/harness adjust <task> <model> <score>  Manually adjust a task/model score
/harness export      Export harness stats to file
/harness import      Import harness stats from file
/cloud <name>        Switch cloud preset (openai|groq|openrouter|gemini|claude)
/arc [n]             Run ARC reasoning eval on n puzzles (needs arc/training.json)
/exec <cmd>          Run a shell command   (or prefix any line with !)
/mcp                 List available MCP tools
/mcp call <tool> <input>  Call an MCP tool from the terminal
/agent add <name>    Add agent persona
/agent delete <name> Remove agent persona
/skill add <name>    Add skill
/skill delete <name> Remove skill
/lora                LoRA adapter management
/clear               Clear current conversation
/exit                Quit
```

The CLI is **live-streaming by default**: tokens appear as they are generated, reasoning is shown dimmed, and each turn ends with a `[model | tokens | tokens/sec | seconds]` footer that reports the *actual* model that executed (from the orchestrator `start` event, so harness-selected executors are shown truthfully). `/parallel on` switches to the ensemble mode (multiple executors answer the same prompt, a judge scores them, the winner is shown). A compact status line (model, planning, parallel, coding, cloud, session tokens) is printed before every prompt. On Windows consoles the input line gets a built-in editor with arrow-key history, Home/End and Ctrl+C stop; when stdout is redirected or stdin is piped it falls back to plain `input()`. Multi-line prompts are supported by ending a line with a backslash `\`. Sessions are saved as JSON under `sessions/`.

---

## Claude-Style Features

### `/skill` - Specialized Skills
Skills provide domain-specific instructions and workflows. Future implementation:
```
/skill code           Enable code-writing mode
/skill debug          Enable debugging mode with stack traces
/skill translate      Enable translation mode
/skill summarize      Enable summarization mode
```

### `/doctors` - Multi-Agent Doctor System
Medical-style multi-agent consultation (future implementation):
```
/doctors              Start doctor consultation
Symptoms: ...
Diagnosis: ...
Treatment: ...
```

### `/context` - Context Management (implemented)
```
/context show         Show current conversation context
/context set <size>   Set max context size
/context clear        Clear conversation context
```

### `/efforts` - Task Tracking
```
/efforts              Show current tasks and progress
/efforts add <task>   Add a new task
/efforts done <id>    Mark task complete
```

---

## Architecture

| File | Responsibility |
| :--- | :--- |
| `config.py` | App config, model registry, thread auto-detection, GPU detection, CLOUD_PRESETS (OpenAI/Claude/Groq/OpenRouter/Gemini) |
| `models.py` | `ModelManager`: lazy loading (with lazy `llama_cpp` import), per-model locks, OpenAI fallback, token streaming, generation watchdog |
| `memory.py` | In-memory `Conversation`/`MemoryManager`, workspace-indexed conversations |
| `database.py` | pgvector semantic memory: embedding, query cache, connection pool, pruning, auto-creates DB if missing, pgAdmin 4 auto-registration |
| `orchestrator.py` | `Orchestrator.run`/`stream`: memory retrieval → planning → execution; web search integration |
| `router.py` | Selection room: `classify_task` + adaptive `Harness` scorer (reset/adjust/export/import) + `ModelRouter` |
| `hardware.py` | Auto-tune: RAM/VRAM detection (PowerShell fallback), threads, VRAM budget, context caps |
| `metrics.py` | Thread-safe `MetricsCollector` (loads, latency, tokens, per-model/task) |
| `arc.py` | ARC reasoning eval harness (grid encode/parse + accuracy over a dataset) |
| `api.py` | FastAPI server: all REST endpoints, SSE streaming, optional Bearer auth, HTTP/2 with httptools fallback, GET /mcp for tool discovery |
| `cli.py` | Terminal CLI: live token streaming, ensemble /parallel mode, /agent add|delete & /skill add|delete, /mcp tool listing + calling, /harness (stats/reset/adjust/export/import), /code, /cloud, /arc, /context, /status, sessions (JSON under sessions/), Windows line-editor input |
| `run.py` | Unified launcher (full/web/cli/api), port cleanup, first-run wizard |
| `web_ui.py` | Mounts Next.js build (frontend/build) + inline HTML fallback + /generated images; serves /,/chat,/workspace,/database,/models,/admin,/tools,/settings,/help with injected auth bootstrap |
| `agents.py` | Agent personas + skills registry: runtime add/delete persisted as JSON under agents/ and skills/ (built-ins protected; new entries auto-appear as MCP tools) |
| `graph_store.py` | Knowledge graph store on PostgreSQL: nodes/edges/tags tables, vector + graph hybrid search, recursive-CTE shortest path |
| `wiki_links.py` | Obsidian-style [[wiki-links]], #tags, headings, backlink extraction from markdown uploads |
| `lora_manager.py` | LoRA adapters: list/load/unload for GGUF, HF-PEFT training, CPU-only training with race condition fix |
| `image_gen.py` | Local image generation via diffusers (CPU-only, RAM-guarded, resolution 256-512, steps 8-40) |
| `frontend/` | Next.js glassmorphism UI in TypeScript (.tsx/.ts): Dashboard (live sparklines with useChartTheme hook) / Chat (markdown rendering, suggestion chips, auto-resize textarea, conversation search + export as markdown, per-message copy) / Workspace (Protected badge on default workspace, file content preview) / Database (connection pool, IVFFlat, agent breakdown, table size) / Models (lazy load/unload, role filter chips, per-model n_ctx/temperature/max_tokens) / Tools (summarize·analyze·translate·agents·skills·images with copy-to-clipboard buttons) / Graph (node/tags/recent tabs, semantic hybrid search, click-to-view node content) / Admin (metrics, threads, logs, LoRA upload+train, skills/agents add+delete, interactive MCP tool calling, harness table with reset/adjust, per-tab loading skeletons) / Settings (API keys, live /v1/config editor, rate-limit reset to defaults) / Help (collapsible sections, pgvector/pgsql setup guide) |
| `frontend/components/` | ErrorBoundary (crash recovery UI), ThemeProvider (class-based dark/light), PageTransition, Sidebar (collapse/expand, backend health, mobile responsive) |
| `frontend/lib/` | api.ts (fetchJSON + token helpers), chartTheme.ts (useChartTheme hook for Recharts), i18n.ts |

### Orchestration flow (`orchestrator.py`)

1. Replay/append the user turn into the conversation.
2. If DB memory is enabled, retrieve semantically similar past memories.
3. If planning is enabled and `hy-mt2` is present, generate **2 candidate plans** (temp 0.3/0.4, ≤256 tokens) and select the best by length + small random tiebreak.
4. Build a ChatML prompt (conversation + plan as a system message).
5. **Generate the answer**:
   - *Parallel mode (non-stream, default on)*: up to `parallel_max` executor models present on disk (`minicpm-v9`, `minicpm-tooluse`, …) answer the same prompt **concurrently in a thread pool**; Hy-MT2 then judges each candidate on a 0–10 scale and the best wins. Set `"parallel": false` on the request (or `--no-parallel`) to disable.
   - *Streaming mode*: tokens stream live from the primary executor via `/v1/chat/stream`.
6. Append the assistant turn to the conversation and (optionally) store `Q: … / A: …` into pgvector memory.

On failure the model layer **raises**; the unanswered user turn is rolled back and no error string is written to history or memory.

### Selection room & adaptive harness (`router.py`)

- `classify_task()` maps a prompt to a task family via keyword scoring (`code`, `math`, `summarize`, `translate`, `tool`, `creative`, else `general`).
- The **Harness** is a lightweight adaptive/"genetic" per-(task, model) fitness scorer. Each generation records success, latency and token output; fitness = `success×60 + speed×30 + recency×10` (speed is 1/latency capped at 2×; recency decays by `harness.decay` every 25 records). Selection is **epsilon-greedy**: normally the top-ranked model runs, but with probability `harness.epsilon` an explorer is picked so rankings stay fresh. Full lifecycle: `reset()` restores defaults, `adjust(task, model, score)` manually tweaks, `export_stats()`/`import_stats()` for persistence.
- The **ModelRouter** is the selection room: it ranks executor models per task (harness first, then capability fallback from each model's `capabilities`), and `Orchestrator.run` uses that ranking for the primary executor and for parallel candidates. `CONFIG.auto_load` preloads the chosen executors under the VRAM budget (LRU eviction otherwise).
- Stats: `GET /v1/router/stats` or `/harness` in the CLI. Harness management: `POST /v1/router/harness/reset`, `POST /v1/router/harness/adjust`, `GET /v1/router/harness/export`.

### Hardware auto-tune & metrics (`hardware.py`, `metrics.py`)

- On startup (`run.py` / API lifespan) `hardware.auto_tune()` detects RAM, VRAM and the GPU backend (CUDA/Vulkan/CPU) and, when `CONFIG.auto_tune` is on: sets threads to `cores//2`, derives `vram_budget_mb = vram − 1024` (min 512) when unset, and caps model contexts to 2048 when RAM < 16 GB. `--no-auto-tune` disables it; `--vram <MB>` overrides the budget. Inspect with `GET /v1/hardware`.
- `metrics.py` records loads, requests, tokens and latency per model and per task; `GET /v1/metrics` returns the snapshot and `/v1/system` embeds both.

### Coding agent mode (`/code on`)

Toggles a coding-focused system prompt and prefers a code-capable executor model; `/cloud <name>` switches the OpenAI-compatible endpoint to a free-tier preset (`openai`, `groq`, `openrouter`, `gemini`, `claude` — see `CLOUD_PRESETS` in `config.py`).

### ARC reasoning eval (`arc.py`)

`python -c "import arc; print(arc.run_arc_eval())"` or CLI `/arc [n]` runs an ARC-style grid-reasoning accuracy check over `arc/training.json` (JSON array of `{train, test}` puzzles). `encode_grid`/`parse_grid` convert between grids and text; `exact=False` allows partial (prefix) grid matches.

### Concurrency & streaming

- **Per-model locks**: different models can generate concurrently; same-model calls are serialized. Load/unload take the same lock.
- **Pinned worker threads**: each model's llama.cpp calls (and its `Llama` load) run on a dedicated single-thread executor, so GPU inference is never invoked from multiple threads (prevents llama.cpp cross-thread corruption).
- **Generation watchdog**: llama.cpp's Vulkan sampler can occasionally stall forever on AMD (confirmed via server stack dumps stuck in `llama_sampler_sample`). After `gen.timeout_s` (default 240; `--gen-timeout`, `POST /v1/config gen.timeout_s`, env `LLM_GEN_TIMEOUT`) the hung generation is killed, the stuck instance + worker are discarded, and the next request auto-reloads the model — no infinite hangs, OpenAI fallback applies if enabled.
- **Blocking inference runs in a worker thread**; the async event loop is never blocked (`run_in_executor` + `asyncio.Queue`).
- **Real token streaming**: `ModelManager.generate_stream` passes `stream=True` to llama.cpp; `/v1/chat/stream` emits SSE `{"type":"thinking"|"response"|"error"|"done"}` events and `/v1/chat/completions?stream=true` emits OpenAI-style `delta` chunks.

### Port safety & model discovery

- `run.py` probes the requested port before binding. If it is busy it **auto-switches to the next free common port** (8000 → 8080 → 8001 → 8081 → 8888 → 9000 → 3000) instead of killing an unrelated process. `--force-port` opts into killing whatever is on the port.
- **GGUF auto-discovery**: any `.gguf` dropped into `models/` is auto-registered as an `Executor` (capability `general`) — it appears in `/v1/models`, the web UI model dropdown and the harness. `--add-model PATH [--add-model-name NAME] [--add-model-role ROLE]` registers a model from anywhere; duplicates are skipped.
- **Cloud**: enable with `--openai-key sk-...` or `--cloud groq|openai|openrouter|gemini|claude`. Cloud models show up in `/v1/models` as `openai/<model>` and are used as fallback when a local generation fails or times out.

---

## Database Schema (`database.py`)

```sql
CREATE TABLE IF NOT EXISTS agent_memory (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL DEFAULT 'default',
    thought TEXT NOT NULL,
    embedding vector(384),
    tokens INT DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_agent_memory_ivfflat ON agent_memory
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_agent_memory_agent ON agent_memory (agent_name, created_at DESC);
CREATE INDEX idx_agent_memory_created ON agent_memory (created_at DESC);
```

- Embeddings: `sentence-transformers/all-MiniLM-L6-v2` (384 dims), on CUDA if available else CPU.
- Query cache: 30s TTL, max 100 entries. Connection pool: min 1 / max 4.
- **Auto-DB creation**: if the target database doesn't exist, `database.py` connects to the `postgres` DB, issues `CREATE DATABASE`, and reconnects.
- **pgAdmin 4**: on startup, the connection is auto-registered in pgAdmin 4's `servers.json` (Windows: `%APPDATA%\pgAdmin\servers.json`, Linux: `~/.pgadmin/servers.json`).
- **Auto-prune**: `db.start_auto_prune()` (started by `run.py` and the API lifespan) deletes memories older than `prune_max_age_days` (default 30) every `prune_interval_hours` (default 6) while the DB is enabled.

---

## API Endpoints

| Method | Path | Description |
| :--- | :--- | :--- |
| GET | `/v1/models` | List models with load status |
| POST | `/v1/models/load?name=` | Load a model |
| POST | `/v1/models/unload?name=` | Unload a model |
| POST | `/v1/chat/completions` | OpenAI-compatible chat (non-stream + `stream=true`) |
| POST | `/v1/chat/stream` | SSE token streaming |
| POST | `/v1/chat/clear` | Clear a conversation |
| GET | `/v1/chat/history` | Get conversation history |
| GET | `/v1/chat/conversations` | List conversations |
| POST | `/v1/generate` | Raw text generation |
| POST | `/v1/batch/generate` | Batch generation |
| POST | `/v1/embeddings` | Generate embeddings |
| POST | `/v1/memory/search` / `/v1/memory/store` | pgvector memory |
| GET | `/v1/memory/stats` | Memory statistics |
| GET | `/v1/memory/recent` | Recent memories (?limit=&agent=) |
| POST | `/v1/memory/clear` | Clear all memories |
| POST | `/v1/memory/prune` | Prune old memories (?max_age_days=) |
| POST | `/v1/tools/summarize` / `/v1/tools/analyze` / `/v1/tools/translate` | Text tools |
| GET | `/v1/system` / `/v1/config` | System info / config (incl. hardware + metrics) |
| POST | `/v1/config` | Update runtime config |
| GET | `/v1/metrics` | Runtime metrics snapshot (per model / per task) |
| GET | `/v1/router/stats` | Adaptive harness fitness scores |
| POST | `/v1/router/harness/reset` | Reset harness scores to defaults |
| POST | `/v1/router/harness/adjust` | Manually adjust a task/model score |
| GET | `/v1/router/harness/export` | Export harness stats as JSON |
| GET | `/v1/hardware` | Detected RAM / VRAM / GPU backend |
| GET | `/v1/health` | Health check |
| GET | `/v1/models/stats` | Model loading stats (times, errors) |
| GET | `/v1/db/stats` | DB status: connected, count, tokens, pool, indexes |
| GET | `/v1/agents` | List agent personas |
| GET | `/v1/agents/{name}` | Agent details (role, description, system_prompt) |
| POST | `/v1/agents/{name}/run` | Run a message under an agent persona |
| POST | `/v1/agents` | Add agent at runtime ({name, role, description, system_prompt} -> persisted to agents/*.json) |
| DELETE | `/v1/agents/{name}` | Remove a user-defined agent (built-ins protected) |
| GET | `/v1/skills` | List skills |
| GET | `/v1/skills/{name}` | Skill details (template, params) |
| POST | `/v1/skills/{name}/run` | Run a skill on input text |
| POST | `/v1/skills` | Add skill at runtime ({name, description, template w/ {input}, system_prompt, params[]} -> persisted to skills/*.json) |
| DELETE | `/v1/skills/{name}` | Remove a user-defined skill (built-ins protected) |
| GET | `/v1/workspaces` | List workspaces |
| POST | `/v1/workspaces` | Create workspace |
| POST | `/v1/workspaces/{ws_id}/update` | Update workspace fields |
| POST | `/v1/workspaces/{ws_id}/delete` | Delete workspace + chats/files |
| GET | `/v1/workspaces/{ws_id}/files` | List uploaded files |
| GET | `/v1/workspaces/{ws_id}/files/{name}/content` | Get a single uploaded file's text content |
| POST | `/v1/workspaces/{ws_id}/files/upload` | Upload file (chunked + embedded) |
| POST | `/v1/workspaces/{ws_id}/files/delete` | Delete uploaded file |
| GET | `/v1/workspaces/{ws_id}/knowledge/search` | Search workspace file chunks |
| GET | `/v1/workspaces/{ws_id}/export` | Export workspace JSON/markdown |
| POST | `/v1/workspaces/{ws_id}/import` | Import workspace conversations |
| GET | `/v1/workspaces/{ws_id}/graph` | Full knowledge graph for the workspace |
| GET | `/v1/workspaces/{ws_id}/backlinks` | Files linking to a given file |
| GET | `/v1/workspaces/{ws_id}/tags` | All #tags with file counts |
| GET | `/v1/workspaces/{ws_id}/tag/{tag}` | Files tagged #tag (with previews) |
| GET | `/v1/workspaces/{ws_id}/orphans` | Files with no incoming/outgoing links |
| GET | `/v1/workspaces/{ws_id}/recent` | Recently added files |
| GET | `/v1/workspaces/{ws_id}/resolve` | Resolve file/heading to section content |
| GET | `/v1/graph/stats` | Graph node/edge/tag counts |
| GET | `/v1/graph/nodes` | List graph nodes |
| GET | `/v1/graph/nodes/{node_id}` | Get a single node (title, content, metadata) |
| POST | `/v1/graph/nodes` | Create graph node |
| DELETE | `/v1/graph/nodes/{node_id}` | Delete node (edges cascade) |
| GET | `/v1/graph/search` | Semantic vector search over nodes |
| GET | `/v1/graph/hybrid` | Vector + graph hybrid search |
| GET | `/v1/graph/links/{node_id}` | Outgoing + backlinks for a node |
| GET | `/v1/graph/edges` | List edges |
| POST | `/v1/graph/edges` | Add edge |
| GET | `/v1/graph/path` | Shortest path via recursive CTE |
| GET | `/v1/graph/path/titles` | Path resolved to titles |
| POST | `/v1/graph/sync` | Re-scan workspace files into graph |
| POST | `/v1/graph/migrate` | Import agent_memory as graph nodes |
| GET | `/v1/admin/logs` | Ring-buffer log lines (?lines=200) |
| GET | `/v1/admin/threads` | Running threads snapshot |
| GET | `/v1/admin/metrics` | Metrics snapshot + uptime |
| GET | `/v1/loras` | List LoRA adapters |
| POST | `/v1/loras/import` | Import LoRA adapter |
| POST | `/v1/loras/{name}/enable` | Enable LoRA adapter |
| POST | `/v1/loras/{name}/disable` | Disable LoRA adapter |
| DELETE | `/v1/loras/{name}` | Delete LoRA adapter |
| POST | `/v1/loras/upload_dataset` | Upload LoRA training dataset |
| GET | `/v1/loras/datasets` | List available datasets |
| POST | `/v1/loras/train` | LoRA fine-tune |
| GET | `/v1/images/config` | Image generation config |
| POST | `/v1/images/generate` | Generate image |
| GET | `/mcp` | MCP tool discovery (browser/admin UIs) |
| POST | `/mcp` | MCP/JSON-RPC endpoint |

Multi-turn: `messages` history is replayed into the conversation (system prompt honored). Set `--api-token` to require `Authorization: Bearer <token>` on `/v1/*` and `/mcp`. Set `"parallel": true|false` on a chat request to override parallel execution per request. Tune `parallel.enabled` / `parallel.max` / `parallel.judge`, `prune.interval_hours` / `prune.max_age_days`, `vram.budget_mb` / `vram.auto_tune` / `vram.auto_load`, `harness.epsilon` / `harness.decay` and `cloud.provider` (preset name) via `POST /v1/config`.

---

## Frontend (Next.js)

The Next.js frontend (`frontend/`) is a modern React + Tailwind CSS glassmorphism UI with:

- **Dark/Light theme**: CSS variable-based with `MutationObserver`-driven chart hooks
- **Dashboard**: Recharts sparklines for hardware metrics, model stats, live system info
- **Chat**: Markdown rendering with syntax highlighting, suggestion chips, auto-resize textarea, conversation search, per-conversation export as markdown, per-message copy, real-time streaming via SSE
- **Workspace**: Isolated chat areas with file upload + content preview, Protected badge on the default workspace, knowledge search, export/import
- **Database**: Connection pool display, IVFFlat index status, agent breakdown, table size, auto-prune status
- **Models**: Lazy load/unload with confirm dialogs, role filter chips, per-model `n_ctx`/`temperature`/`max_tokens`, hardware info
- **Tools**: Summarize/analyze/translate, agent personas, skills, image generation, copy-to-clipboard buttons
- **Graph**: Node/tags/recent tabs, click-to-view node content, semantic hybrid search
- **Admin**: Metrics, thread snapshots, logs (color-coded), LoRA upload+train, skills/agents CRUD, interactive MCP tool calling, harness table with reset/adjust, per-tab loading skeletons
- **Settings**: API keys for cloud providers (OpenAI, Claude, Groq, OpenRouter, Gemini), live `/v1/config` editor, rate-limit reset-to-defaults
- **Help**: Collapsible sections, pgvector/pgsql setup guide, hardware docs
- **Accessibility**: `aria-expanded` on collapsible sections, `aria-label` attributes, focus-visible outlines, reduced-motion support

Build: `cd frontend && npm run build` then `python run.py --nextjs` (API on :8070 + Next.js on :3001).

---

## Troubleshooting

| Issue | Fix |
| :--- | :--- |
| Slow generation | Verify GPU offload (`n_gpu_layers=-1`), check threads, use a smaller context. |
| `llama_supports_gpu_offload()` = False | Rebuild `llama-cpp-python` with your backend (Vulkan/CUDA/Metal). |
| No models found | Place `.gguf` files in `models/` matching names in `config.py`. |
| DB memory not persisting | Ensure PostgreSQL + `vector` extension are running; check `pg_hba.conf`. |
| Port already in use | `run.py` frees the port automatically, or use `--port`. |
| Embedding dimension mismatch | `all-MiniLM-L6-v2` = 384 dims; update the schema if you change embedders. |
| App falls back to in-memory | DB connection failed; app still works but data is not persistent. |
| pgAdmin can't connect | Verify `pg_hba.conf` allows connections from 127.0.0.1. |

---

## License Notes

- **Hy-MT2 / MiniCPM**: open-weights, license per their respective HuggingFace repositories.
- **llama.cpp**: MIT. **pgvector**: PostgreSQL License. **This app code**: provided as-is for the project.

---

**Built by [Rakibul Hasan](https://rhasan-dev-bd-com.vercel.app/)**
