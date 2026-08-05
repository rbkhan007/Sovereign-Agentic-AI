# Sovereign-Agentic-AI — Local Multi-Agent System

A fully local, privacy-first multi-agent chat system powered by llama.cpp. Two small specialized models cooperate to answer queries with planning and execution.

**Backend**: llama.cpp via `llama-cpp-python` (Vulkan on AMD GPUs)  
**Models**: Hy-MT2-1.8B (Strategist) + MiniCPM-1B (Executor/ToolExecutor)  
**Memory**: Optional PostgreSQL + pgvector (semantic memory)

## Features

- **Multi-agent pipeline**: Hy-MT2 plans, MiniCPM executes
- **Parallel execution**: Multiple executor models answer concurrently, judged by Hy-MT2
- **Adaptive routing**: Epsilon-greedy task classification picks the best model per task
- **Hardware auto-tune**: Detects RAM/VRAM, sets threads and context sizes automatically
- **Streaming**: Real token-by-token streaming via `/v1/chat/stream`
- **Workspaces**: Isolated chat areas with file upload and knowledge search
- **Knowledge graph**: Obsidian-style `[[wiki-links]]`, `#tags` and backlinks extracted from uploaded `.md` files with a visual graph in the Web UI; graph store (nodes/edges/tags) on PostgreSQL with vector + graph hybrid search and recursive-CTE shortest-path queries via `/v1/graph/*`
- **Agents & skills**: Named agent personas (coder, debugger, writer, ...) and reusable skills (summarize, translate, code-review, ...) via CLI, HTTP API and MCP; runtime add/delete from CLI (`/agent add`, `/skill add`) or web admin, persisted as JSON under `agents/` and `skills/`
- **Web UI**: Colorful auto-orchestrator dashboard with hardware monitoring, live sparklines, agent/skill selection, and real-time streaming
- **Next.js frontend**: Modern React + Tailwind CSS glassmorphism UI written in TypeScript (`.tsx`) with dark/light theme, dashboard, chat (markdown rendering, suggestion chips), workspace, database (connection pool, IVFFlat, agent breakdown), models (lazy load/unload), tools (summarize/analyze/translate/agents/skills/images), admin (metrics, logs, threads, LoRA upload+train, skills/agents CRUD, interactive MCP tool calling, harness table), settings (API keys, live `/v1/config` editor), and help (collapsible sections, pgvector/pgsql setup guide) pages (optional, run with `--nextjs`)
- **Image generation**: Opt-in local Stable Diffusion via `--image-gen` (CPU-only, RAM-guarded, writes to `generated/`)
- **Data Science (AutoML)**: Opt-in local Auto-Sklearn training via `--automl` (Linux-only; `pip install -e ".[data-science]"`), with `POST /v1/datascience/train` endpoint and a Data Science tab in the UI
- **Self-Healing Agent**: Diagnoses and auto-repairs broken Python snippets — runs code in a sandbox, captures tracebacks, uses Hy‑MT2 for root-cause analysis, and Qwen for fix suggestion (`--healing`, `POST /v1/healing/run`)
- **CLI**: Terminal interface with live streaming, sessions, slash commands, `/agent add|delete`, `/skill add|delete`, `/mcp` tool listing + calling, `/harness` (stats/reset/adjust/export/import), `/heal` (run self-healing on a snippet)
- **OpenAI-compatible API**: Drop-in replacement for `/v1/chat/completions`
- **Cloud fallback**: Optional OpenAI/Claude (Anthropic)/Groq/OpenRouter/Gemini integration (sliding-window rate-limited at 10 calls/min with exponential backoff by default; tune via `POST /v1/config openai.rate_limit_per_min` / `openai.backoff_max_s`)

## Quick Start

### Option A: pip-installable package (recommended)

```bash
pip install -e .                    # Install backend + 4 CLI entry points
sovereign-llm                       # Full mode: Web UI + CLI + API
```

After install, four console commands are available:

| Command | Mode |
|---|---|
| `sovereign-llm` | Full mode: Web UI + CLI + API |
| `sovereign-llm-web` | Web UI + API only |
| `sovereign-llm-cli` | Terminal CLI only |
| `sovereign-llm-api` | API server only |

> **Windows note:** the entry-point `.exe` shims are installed to `%APPDATA%\Python\PythonXY\Scripts\`. Add that directory to your `PATH` (or run `python run.py` directly).

### Option B: Run directly from source

```bash
python -m venv venv
venv\Scripts\activate          # Windows (or source venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
```

For GPU acceleration, rebuild `llama-cpp-python` against your backend:

```bash
set CMAKE_ARGS="-DGGML_VULKAN=on"
pip install --force-reinstall llama-cpp-python --no-cache-dir
```

### Models

Place `.gguf` files in the `models/` directory. Expected filenames:

| File | Name | Role |
|:-----|:-----|:-----|
| `Hy-MT2-1.8B-Q4_K_M.gguf` | `hy-mt2` | Strategist |
| `MiniCPM5-1B-Agentic-v9-f16.gguf` | `minicpm-v9` | Executor |
| `minicpm5-1b-agentic-tooluse.F16.gguf` | `minicpm-tooluse` | ToolExecutor |

Any `.gguf` dropped into `models/` is auto-discovered and registered as an Executor.

## Usage

```bash
python run.py                    # Full mode: web UI + CLI (recommended)
python run.py web                # Web UI only
python run.py cli                # Terminal CLI only
python run.py api                # API server only
sovereign-llm                    # Or: installed entry point (full mode)
python run.py --port 8080        # Custom port
python run.py --api-token secret # Require Bearer token on /v1/* and /mcp
python run.py --openai-key sk-...        # With OpenAI cloud fallback
python run.py --openai-url https://...  # OpenAI-compatible base URL
python run.py --openai-model gpt-4o-mini # OpenAI model name
python run.py --cloud groq       # Free-tier cloud preset: openai|groq|openrouter|gemini|claude
python run.py --image-gen        # Enable local image generation (diffusers, CPU-only, opt-in)
python run.py --vision           # Enable local image understanding via moondream2 (CPU-only, opt-in)
python run.py --vision-model NAME # Vision model id (default vikhyat/moondream2)
python run.py --automl           # Enable Auto-Sklearn AutoML data-science agent (Linux-only, opt-in)
python run.py --automl-model-dir DIR # Directory to save trained AutoML models (default: generated/automl_models)
python run.py --healing          # Enable the self-healing diagnostic agent (diagnoses + fixes Python code)
python run.py --db --db-password postgres  # With PostgreSQL memory
python run.py --db --db-name mydb --db-user myuser --db-host localhost --db-password pass
python run.py --nextjs           # Start Next.js dev server (port 3001)
```

### PostgreSQL + pgvector Memory

The app auto-creates the database if it doesn't exist (requires superuser or CREATEDB privilege). On first startup with `--db`:

1. Attempts to connect to the target database
2. If it doesn't exist, connects to `postgres` and runs `CREATE DATABASE`
3. Creates all required tables: `agent_memory`, `workspaces`, `workspace_files`, `nodes`, `edges`, `tags`
4. Enables the `vector` extension and creates an adaptive pgvector index (HNSW for 100-2,000 rows, IVFFlat with `lists=sqrt(rows)` after 2,000+; none below 100), auto-recreated on threshold crossing
5. Optionally registers the connection in pgAdmin 4

```bash
python run.py --db --db-password postgres  # Basic (uses defaults: localhost:5432, postgres user)
python run.py --db --db-name mydb --db-user myuser --db-host localhost --db-password pass  # Custom
```

### Next.js Frontend (Optional)

For a modern React + Tailwind CSS experience with dark/light theme:

```bash
cd frontend
npm install
npm run build
python run.py --nextjs            # Starts API on :8070 + Next.js on :3001
```

Or run Next.js dev server separately:

```bash
cd frontend
npm run dev                       # Dev server on :3001, proxies API to :8070
```

For production build without `--nextjs`:

```bash
cd frontend
npm run build
python run.py web                # Serves Next.js build if present
```

### One-click Launchers (Windows)

```bat
start.bat                        # Full mode with DB
start_simple.bat                 # No-DB mode
launch.bat                       # Optimized for AMD RX 5600 XT
```

## API Endpoints

| Method | Path | Description |
|:-------|:-----|:------------|
| GET | `/v1/models` | List models with load status |
| POST | `/v1/models/load?name=` | Load a model |
| POST | `/v1/models/unload?name=` | Unload a model |
| POST | `/v1/chat/completions` | OpenAI-compatible chat |
| POST | `/v1/chat/stream` | Token-by-token streaming |
| POST | `/v1/chat/clear` | Clear a conversation |
| GET | `/v1/chat/history` | Get conversation history |
| GET | `/v1/chat/conversations` | List conversations |
| POST | `/v1/generate` | Raw text generation |
| POST | `/v1/batch/generate` | Batch generation |
| POST | `/v1/embeddings` | Generate embeddings |
| POST | `/v1/memory/search` | Search pgvector memory |
| POST | `/v1/memory/store` | Store to memory |
| GET | `/v1/memory/stats` | Memory statistics |
| GET | `/v1/memory/recent` | Recent memories |
| POST | `/v1/memory/clear` | Clear all memories |
| POST | `/v1/memory/prune` | Prune old memories |
| POST | `/v1/tools/summarize` | Text summarization |
| POST | `/v1/tools/analyze` | Text analysis |
| POST | `/v1/tools/translate` | Text translation |
| GET | `/v1/agents` | List agent personas |
| POST | `/v1/agents/{name}/run` | Run a message under an agent persona |
| POST | `/v1/agents` | Add agent at runtime (persisted to `agents/*.json`) |
| DELETE | `/v1/agents/{name}` | Remove a user-defined agent (built-ins protected) |
| GET | `/v1/skills` | List skills |
| POST | `/v1/skills/{name}/run` | Run a skill on input text |
| POST | `/v1/skills` | Add skill at runtime (persisted to `skills/*.json`) |
| DELETE | `/v1/skills/{name}` | Remove a user-defined skill (built-ins protected) |
| POST | `/v1/loras/upload_dataset` | Upload LoRA training dataset (5MB cap) |
| GET | `/v1/loras/datasets` | List pre-built datasets under `lora_datasets/` |
| POST | `/v1/loras/train` | LoRA fine-tune (needs `peft`/`datasets`/`transformers`) |
| GET | `/v1/images/config` | Image generation config (CPU-only diffusers) |
| POST | `/v1/images/generate` | Generate image to `generated/*.png` |
| GET | `/v1/vision/config` | Vision config (moondream2, CPU-only, opt-in) |
| POST | `/v1/vision/analyze` | Analyze an image |
| GET | `/v1/datascience/config` | AutoML config (auto-sklearn, CPU-only, Linux-only, opt-in) |
| POST | `/v1/datascience/train` | Train Auto-Sklearn model from a CSV |
| GET | `/v1/graph/stats` | Graph node/edge/tag counts |
| GET | `/v1/graph/search` | Semantic vector search over graph nodes |
| GET | `/v1/graph/hybrid` | Vector + graph hybrid search |
| GET | `/v1/graph/path` | Shortest path between nodes |
| POST | `/v1/graph/sync` | Re-scan workspace files into graph nodes/edges |
| POST | `/v1/graph/migrate` | Import `agent_memory` rows as graph nodes |
| GET | `/v1/router/stats` | Adaptive harness fitness scores |
| POST | `/v1/router/harness/reset` | Reset harness scores to defaults |
| POST | `/v1/router/harness/adjust` | Manually adjust a task/model score |
| GET | `/v1/router/harness/export` | Export harness stats as JSON |
| GET | `/v1/db/stats` | DB status: connected, count, tokens, pool, indexes |
| GET | `/v1/system` | System info + hardware metrics |
| GET | `/v1/metrics` | Runtime metrics snapshot |
| GET | `/v1/hardware` | Detected RAM / VRAM / GPU backend |
| GET | `/v1/config` | Config (models, DB, API token) |
| POST | `/v1/config` | Update runtime config |
| GET | `/v1/health` | Health check |
| GET | `/mcp` | MCP tool discovery (browser/admin UIs) |
| POST | `/mcp` | MCP/JSON-RPC endpoint |

See [AGENTS.md](AGENTS.md) for the full endpoint reference.

## Architecture

```
User Request
    |
    v
[Router] -- classify_task() --> task type
    |
    v
[Hy-MT2 1.8B] -- plan --> 2 candidates --> pick best
    |
    v
[MiniCPM 1B] -- execute --> final answer
    |
    v
Response (+ optional pgvector memory store)
```

## Configuration

Key environment variables:

| Variable | Default | Description |
|:---------|:--------|:------------|
| `LLM_GPU_NAME` | `GPU` | GPU name for display |
| `API_TOKEN` | (empty) | Bearer token for API auth |
| `LLM_PARALLEL` | `true` | Enable parallel multi-model generation |
| `LLM_PARALLEL_MAX` | `2` | Max models in parallel |
| `LLM_VRAM_MB` | `0` (auto) | VRAM budget in MB |
| `LLM_GEN_TIMEOUT` | `240` | Generation timeout in seconds |
| `LLM_CLOUD` | (empty) | Cloud preset: openai, groq, openrouter, gemini, claude |
| `OPENROUTER_API_KEY` / `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | (auto) | If any is set, the matching cloud provider is auto-enabled for internet LLM fallback |
| `LLM_DB` | `off` | Auto-enable PostgreSQL memory (`on`/`auto`) |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE` | localhost:5432 / postgres / postgres | PostgreSQL connection settings |
| `LLM_IMAGE_GEN` | `off` | Enable local image generation (`on`) |
| `LLM_IMAGE_GEN_MODEL` | (default) | Diffusers model id for image generation |
| `LLM_VISION` / `LLM_VISION_MODEL` | `off` / `vikhyat/moondream2` | Enable local image understanding (CPU-only, opt-in) |
| `LLM_AUTOML` / `LLM_AUTOML_MODEL_DIR` | `off` / `generated/automl_models` | Enable Auto-Sklearn AutoML (Linux-only; install deps with `pip install auto-sklearn pandas scikit-learn joblib`) |
| `LLM_HEALING` | `off` | Enable the self-healing diagnostic agent (`on`) |

## Hardware Requirements

- **CPU**: x86_64 with AVX2; threads auto-set to `cpu_count() // 2`
- **RAM**: 8 GB minimum, 16 GB recommended
- **GPU (optional)**: Any GPU supported by llama.cpp (CUDA/Vulkan/Metal)
- **OS**: Windows / Linux / macOS
- **Python**: 3.10+

## Testing

```bash
python test_all.py               # Offline test suite (691 tests, no model/DB loads)
python test_system.py 8070       # Live integration tests (requires running server)
python test_load.py --port 8070  # Load/stress test
python run_deep_audit.py         # Full static audit (mypy, pyflakes, bandit, vulture, pydocstyle, ESLint)
```

## Comparison with Alternatives

| Feature | **Sovereign-Agentic-AI** | Ollama | LM Studio | LocalAI |
|---|---|---|---|---|
| Multi-agent planning | Full (Hy-MT2 + executor + judgment) | None | None | None |
| pgvector memory | PostgreSQL + adaptive indexing | None | None | None |
| Knowledge graph | Wiki-links + graph sync + hybrid search | None | None | None |
| Self-healing code repair | `--healing` flag | None | None | None |
| Auto-sklearn AutoML | `--automl` (Linux) | None | None | None |
| Hardware auto-tune | RAM/VRAM detection + dynamic monitor | Manual | Manual | Manual |
| Parallel multi-model | Yes (`--parallel-max`) | No | No | No |
| Token streaming | SSE with auto-agentic heuristics | Yes | Yes | Yes |
| Vision (CPU) | moondream2 | None | Yes | Optional |
| Image generation | Stable Diffusion | None | Optional | Optional |
| LoRA training (CPU) | Yes | No | No | No |
| Token rotation + sandbox | Yes | Single key | Single key | Single key |
| Offline test suite | 703 tests, 0 failures | None | None | None |
| Static audit | mypy + pyflakes + bandit + vulture + ESLint | None | None | None |

### WSL2 (Linux subsystem on Windows)

For full functionality including AutoML, set up WSL2 with PostgreSQL + pgvector:

```bash
# 1. Enable WSL2 with Ubuntu
wsl --install -d Ubuntu

# 2. Inside WSL2, install dependencies
sudo apt update
sudo apt install postgresql postgresql-contrib git build-essential
git clone https://github.com/pgvector/pgvector.git && cd pgvector && make && sudo make install

# 3. Start PostgreSQL
sudo service postgresql start
sudo -u postgres createuser -s llmmem
sudo -u postgres createdb sovereign_llm
sudo -u postgres psql -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4. Install the package with AutoML extras
pip install -e ".[data-science]"

# 5. Run with full stack
sovereign-llm --db --automl --healing
```

## License

MIT License - see [LICENSE](LICENSE) for details.

---

**Built by [Rakibul Hasan](https://rhasan-dev-bd-com.vercel.app/)**
