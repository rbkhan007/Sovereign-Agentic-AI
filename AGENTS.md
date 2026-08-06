# AGENTS.md - Project Reference

## Commands

python run.py                    # Full mode: web UI + CLI (recommended)
python run.py web                # Web UI only
python run.py cli                # Terminal CLI only
python run.py api                # API server only
python run.py --setup            # First-run config wizard
python test_all.py               # Offline test suite (all modules, no model/DB loads)
python test_system.py [port]     # Live integration tests (requires running server)
python run_deep_audit.py         # Full static audit: mypy + pyflakes + bandit + vulture + pydocstyle + ESLint
python run.py --port 8080        # Custom port
python run.py --threads 4        # Override CPU threads (propagated to models)
python run.py --api-token secret # Require Bearer token on /v1/* and /mcp (comma-separated = rotation set, first is primary; env API_TOKEN / LLM_API_TOKENS)
python run.py --admin-key secret # Require X-Admin-Key header for control-plane mutations (POST /v1/config, model load/unload, agents/skills/loras writes, harness reset/adjust, memory clear/prune, workspace/graph writes; env LLM_ADMIN_KEY)
python run.py --rate-limit         # Enable per-IP rate limiting on /v1/* and /mcp (light 120/min, heavy 10/min; env LLM_RATE_LIMIT=on)
python run.py --rate-light 300 --rate-heavy 20  # Tune rate-limit buckets per IP per minute (env LLM_RATE_LIGHT / LLM_RATE_HEAVY)
python run.py --no-rate-exempt-local            # Do NOT exempt 127.0.0.1/::1 from rate limits (env LLM_RATE_EXEMPT_LOCAL=off)
python run.py --no-parallel      # Disable parallel multi-model generation
python run.py --parallel-max 3   # Max models to run in parallel (default 2)
python run.py --no-parallel-load # Load models one at a time (disable concurrent loading)
python run.py --load-workers 3   # Max models to load concurrently (default 2)
python run.py --cli-commands /status,/model,/lora  # Restrict CLI slash commands to this whitelist (empty=all; /help /exit /quit /status always allowed)
python run.py --prune-hours 12   # Auto-prune interval (default 6h)
python run.py --prune-days 60    # Auto-prune max age (default 30d)
python run.py --sandbox          # Sandbox mode: no DB writes, isolated conversations
python run.py --vram 4096        # VRAM budget in MB (0=auto-detect)
python run.py --gen-timeout 60   # Generation timeout in seconds (default 240; hung inference auto-recovers)
python run.py --auto-stream          # Enable auto-agentic streaming (default: enabled)
python run.py --no-auto-stream       # Disable auto-agentic streaming (forces batch)
python run.py --auto-stream-thinking # Stream thinking steps (default: enabled)
python run.py --no-auto-stream-thinking  # Hide thinking steps (still stream final tokens)
python run.py --auto-stream-min-tokens 25  # Min tokens before streaming is worth it (default 50)
python run.py --auto-stream-max-tokens 512 # Hard cap for auto-streamed requests (default 2048)
python run.py --cloud groq       # Free-tier cloud preset: openai|groq|openrouter|gemini|claude
python run.py --parallel         # Enable parallel multi-model generation (default OFF)
python run.py --no-parallel      # Disable parallel multi-model generation
python run.py --parallel-max N   # Cap models run in parallel (default 2; cap only, does NOT enable)
python run.py --sandbox          # Force sandbox mode globally: no DB writes + isolated conversations (enforced in API + orchestrator)
python run.py --image-gen        # Enable local image generation via diffusers (CPU-only, opt-in)
python run.py --vision           # Enable local image understanding via Gemma 3 (CPU-only, on by default)
python run.py --vision-model NAME # Vision model id (default google/gemma-3-4b-it; env LLM_VISION / LLM_VISION_MODEL)
python run.py --automl          # Enable local AutoML (auto-sklearn) data-science agent (Linux-only, opt-in)
python run.py --automl-model-dir DIR # Directory to save trained AutoML models (default generated/automl_models)
python run.py --healing          # Enable the self-healing diagnostic agent (diagnoses + fixes Python code)
python run.py --allow-unsafe-healing  # PERMIT healing to execute caller-supplied Python (RCE risk; only with --healing)
python run.py --allow-gui        # Enable the computer agent's mouse & keyboard tools (human-like GUI control; local opt-in; env LLM_ALLOW_GUI=on)
python run.py --no-auto-tune     # Disable hardware auto-tune
python run.py --no-auto-load     # Disable selection-room preloading
python run.py --add-model PATH --add-model-name NAME --add-model-role Executor  # Register extra GGUF at runtime
python run.py --force-port       # Kill whatever is on the port (default: auto-switch to a free port)
python run.py --db --db-password postgres  # With PostgreSQL memory (env: PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE, LLM_DB=on)
python run.py --db --db-name mydb --db-user myuser --db-host localhost --db-password pass  # Custom DB connection
python run.py --openai-key sk-...         # With OpenAI cloud fallback (or auto-enable via OPENROUTER_API_KEY/GROQ_API_KEY/GEMINI_API_KEY/OPENAI_API_KEY/ANTHROPIC_API_KEY)
python run.py --openai-url https://...   # OpenAI-compatible base URL
python run.py --openai-model gpt-4o-mini # OpenAI model name
python run.py --nextjs                   # Start Next.js dev server alongside API (port 3001)

python test_load.py --port 8070  # Load/balance test: cheap API endpoints
python test_load.py --port 8070 --chat --chat-count 4   # Add real chat generations
python test_load.py --port 8070 --concurrency 12 --requests 300 --error-limit 2  # Tune load

start.bat                        # One-click launcher (DB mode)
start_simple.bat                 # One-click launcher (no DB)
launch.bat                       # One-click launcher (optimized for AMD RX 5600 XT)

## API Endpoints (all on http://localhost:{port})

GET  /v1/models                  # List models with load status
GET  /v1/models/stats              # Model loading stats (times, errors)
POST /v1/models/load               # Load a model (?name=...)
POST /v1/models/unload              # Unload a model (?name=...)
POST /v1/chat/completions           # OpenAI-compatible chat (body may include conversation_id + workspace_id for server-kept multi-turn)
POST /v1/chat/stream                # Token-by-token streaming
POST /v1/chat/auto-stream            # Auto-agentic streaming: per-request stream-vs-batch + real-time thinking/token SSE events
POST /v1/chat/upload                 # Upload a chat file (multipart, 20MB cap) -> stored under generated/chat_uploads/ as /generated/chat_uploads/{uuid}_{sanitized_name} (needs python-multipart; PDFs return preview_text via pypdf; images return is_image=true + vision preview_text when enabled)
POST /v1/chat/clear                 # Clear conversation (?conv_id=&workspace_id=)
GET  /v1/chat/history              # Get conversation history (?conv_id=&workspace_id=)
GET  /v1/chat/conversations      # List conversations (?workspace_id= scopes per workspace; ?labels=1 returns titles/counts)
POST /v1/generate                 # Raw text generation
POST /v1/batch/generate          # Batch generation
POST /v1/embeddings              # Generate embeddings
POST /v1/memory/search           # Search pgvector memory
POST /v1/memory/store            # Store to memory
GET  /v1/memory/stats            # Memory statistics
POST /v1/tools/summarize         # Text summarization
POST /v1/tools/analyze           # Text analysis
POST /v1/tools/translate         # Text translation
GET  /v1/agents                  # List agent personas (coder, debugger, writer, ...)
GET  /v1/agents/{name}           # Agent details (role, description, system_prompt)
POST /v1/agents/{name}/run       # Run a message under an agent persona
POST /v1/agents                  # Add agent at runtime ({name, role, description, system_prompt} -> persisted to agents/*.json)
DELETE /v1/agents/{name}         # Remove a user-defined agent (built-ins protected)
GET  /v1/skills                  # List skills (summarize, translate, code-review, ...)
GET  /v1/skills/{name}           # Skill details (template, params)
POST /v1/skills/{name}/run       # Run a skill on input text
POST /v1/skills                  # Add skill at runtime ({name, description, template w/ {input}, system_prompt, params[]} -> persisted to skills/*.json)
DELETE /v1/skills/{name}         # Remove a user-defined skill (built-ins protected)
POST /v1/loras/upload_dataset    # Upload LoRA training dataset ({name, text} -> lora_datasets/*.txt, 5MB cap)
GET  /v1/loras/datasets          # List available datasets under lora_datasets/ (name, lines, size, path)
POST /v1/loras/train             # LoRA fine-tune (epochs 1-10; 503 when RAM < 4GB; needs peft/datasets/transformers)
GET  /v1/images/config           # Image generation config (diffusers, CPU-only)
POST /v1/images/generate         # {prompt, width(256-512), height, steps(8-40)} -> generated/*.png (RAM-guarded)
GET  /v1/vision/config           # Vision config (Gemma 3, CPU-only, on by default)
POST /v1/vision/analyze          # {image(base64 or data URI), prompt?} -> {description, elapsed_s}
GET  /v1/datascience/config      # AutoML config (auto-sklearn, CPU-only, Linux-only, opt-in)
POST /v1/datascience/train       # {csv_text, target_column, task_type(classification|regression), time_limit} -> {model_path, score, leaderboard}
GET  /v1/healing/config          # Self-healing agent configuration
POST /v1/healing/run            # {code, context?, timeout_s?} -> {success, output, attempts, final_code}
GET  /v1/system                  # System info incl. hardware + metrics
GET  /v1/metrics                 # Runtime metrics (per model / per task)
GET  /v1/metrics/history         # Persisted metrics snapshots (?limit=; newest-first, DB-off ring fallback)
POST /v1/metrics/history         # Save a metrics snapshot ({...}) -> {status: saved}
POST /v1/metrics/history/prune   # Keep only newest ?max_rows= snapshots -> {deleted}
GET  /v1/sessions                # List persisted sessions (?limit=&user_id=)
POST /v1/sessions                # Create session ({session_id?, name?, user_id?, metadata?}) -> {session, id}
GET  /v1/sessions/{id}           # Get a session
POST /v1/sessions/{id}/update    # Update name/user_id/metadata (+ touch: bump last_active_at)
DELETE /v1/sessions/{id}         # Delete a session
POST /v1/sessions/prune          # Delete sessions inactive > ?max_age_days= -> {deleted}
GET  /v1/router/stats            # Adaptive harness fitness scores
POST /v1/router/harness/reset    # Reset harness scores to defaults
POST /v1/router/harness/adjust   # Manually adjust a task/model score
GET  /v1/router/harness/export   # Export harness stats as JSON
POST /v1/rate/reset              # Drop all per-IP rate-limit buckets
GET  /v1/hardware                # Detected RAM / VRAM / GPU backend (?refresh=1 forces a fresh probe; otherwise live readings are overlaid on cached static info)
GET  /v1/config                  # Get config (incl. models[], db.host/port/user, api_token)
POST /v1/config                  # Update config (threads, prune.*, vram.*, harness.*, gen.timeout_s, cloud.provider, image_gen.enabled, vision.enabled/model/max_tokens; dynamic model.<name>.temperature/max_tokens/n_ctx/top_p/role)
GET  /v1/health                  # Health check
GET  /mcp                        # MCP tool discovery (browser/admin UIs list available tools)
POST /mcp                        # MCP/JSON-RPC endpoint (tools: chat, agent personas, skills; new agents/skills appear automatically)
GET  /v1/db/stats                # DB status: connected, count, tokens, agents, ivfflat, table bytes, pool, auto-prune
GET  /v1/memory/recent           # Recent memories (?limit=&agent=)
POST /v1/memory/clear            # Clear all memories
POST /v1/memory/prune            # Prune old memories (?max_age_days=)

## Agentic Terminal API (sandboxed shell/python + project file ops; used by /terminal)

POST /v1/terminal/exec           # Run a sandboxed shell command ({command}) -> {stdout, exit_code}
POST /v1/terminal/python         # Execute code as Python ({code}) -> {stdout, exit_code}
GET  /v1/terminal/fs/tree        # Project file tree (?depth=&max_nodes=)
POST /v1/terminal/fs/read        # Open a file ({path, limit}) -> {content}
POST /v1/terminal/fs/write       # Save a file ({path, content})
POST /v1/terminal/fs/mkdir       # Create a folder ({path})
POST /v1/terminal/fs/delete      # Delete a file/folder ({path})
GET  /ascii-logo.png             # Legacy logo URL -> redirects/serves frontend/public/ascii-logo.png

## Workspace API (isolated chat areas backed by `workspaces`/`workspace_files` tables; in-memory fallback when DB off)

GET  /v1/workspaces                # List workspaces (default is protected)
POST /v1/workspaces                # Create workspace ({name, description, system_prompt, default_model})
POST /v1/workspaces/{ws_id}/update    # Update fields
POST /v1/workspaces/{ws_id}/delete    # Delete workspace + its chats/files (default is 404-protected)
GET  /v1/workspaces/{ws_id}/files     # List uploaded files (chunk counts)
POST /v1/workspaces/{ws_id}/files/upload   # {name, content} -> chunk_text (600/120) + embed under agent `workspace:<id>`
POST /v1/workspaces/{ws_id}/files/delete   # ?name=...
GET  /v1/workspaces/{ws_id}/knowledge/search   # pgvector search scoped to the workspace's file chunks
GET  /v1/workspaces/{ws_id}/export    # JSON or ?format=markdown (conversations + system prompts)
POST /v1/workspaces/{ws_id}/import    # Restore exported conversations (re-binds to target workspace)

## Knowledge Graph API (Obsidian-like: [[wiki-links]], #tags, headings, backlinks; extracted on upload into `wiki_links.py`)

GET  /v1/workspaces/{ws_id}/graph     # Full graph: nodes (files w/ out_degree, in_degree, tags, headings) + edges
GET  /v1/workspaces/{ws_id}/backlinks # ?file=<name> -> files linking to it
GET  /v1/workspaces/{ws_id}/tags      # All tags with file counts
GET  /v1/workspaces/{ws_id}/tag/{tag} # Files tagged #tag (with previews)
GET  /v1/workspaces/{ws_id}/orphans   # Files with no incoming/outgoing links
GET  /v1/workspaces/{ws_id}/recent    # Recently added files (?limit=)
GET  /v1/workspaces/{ws_id}/resolve   # ?file=<name>&heading=<h> -> section content
GET  /v1/graph/stats               # Node/edge/tag counts + recent nodes
GET  /v1/graph/nodes               # List all nodes (?type=document|concept|memory&workspace_id=&limit=)
GET  /v1/graph/nodes/{node_id}     # Get a single node (title, content, metadata, workspace_id)
POST /v1/graph/nodes               # Create node ({title, node_type, content, workspace_id, tags[]})
DELETE /v1/graph/nodes/{node_id}        # Delete a node (edges cascade)
GET  /v1/graph/search              # Semantic vector search over nodes (?q=&workspace_id=&top_k=&min_score=)
GET  /v1/graph/hybrid              # Vector + graph search (?q=...) -> ranked nodes w/ neighbours + degrees
GET  /v1/graph/links/{node_id}          # Outgoing + backlinks for a node
GET  /v1/graph/edges               # List edges (?limit=)
POST /v1/graph/edges               # Add edge ({source_id, target_id, edge_type, weight})
GET  /v1/graph/path                # Shortest path (?start=&end=&max_depth=) via recursive CTE
GET  /v1/graph/path/titles         # Path resolved to titles (?start_title=&end_title=&workspace_id=&max_depth=)
POST /v1/graph/sync                # Re-scan workspace files -> document/concept nodes + wikilink edges (?workspace_id=)
POST /v1/graph/migrate             # Import agent_memory rows as 'memory' nodes (?workspace_id=&limit=)
GET  /v1/admin/logs                # Ring-buffer log lines (?lines=200)
GET  /v1/admin/threads             # Running threads snapshot
GET  /v1/admin/metrics             # Metrics snapshot + uptime_s + thread count

## Key Files

run.py              # Unified launcher (full/web/cli/api) + port auto-fallback + --add-model
config.py           # App configuration (GPU, threads, DB, model paths, CLOUD_PRESETS incl. Claude/Anthropic, GGUF auto-discovery)
models.py           # Model manager (lazy loading with lazy llama_cpp import, GPU offload, OpenAI fallback, VRAM budget/LRU, per-model worker threads + generation watchdog)
memory.py           # In-memory conversation manager (workspace-indexed conversations, DB-backed persistence when pool live)
database.py         # pgvector memory (PostgreSQL + sentence-transformers or remote embedder) + workspaces/files layer + DB-backed conversations/agents/skills/sessions/metrics snapshots + auto-creates DB if missing + pgAdmin 4 auto-registration
router.py           # Selection room: classify_task + adaptive Harness scorer (reset/adjust/export/import) + ModelRouter
hardware.py         # Auto-tune: RAM/VRAM detection (PowerShell fallback), threads, VRAM budget, context caps
metrics.py          # Thread-safe MetricsCollector (loads, latency, tokens, per-model/task)
arc.py              # ARC reasoning eval harness (grid encode/parse + accuracy)
orchestrator.py     # Multi-agent pipeline (Hy-MT2 plans + Gemma 4 E4B / Qwen2.5-Omni / Mythos-nano execute; merges global + workspace-scoped knowledge; web search integration; auto-agentic streaming via auto_stream())
agents.py           # Agent personas + skills registry: runtime add_agent/add_skill/delete_agent/delete_skill persisted as JSON under agents/ and skills/ AND mirrored to PostgreSQL agents/skills tables when the DB is live (built-ins protected; DB rows hydrate over stale JSON at import; new entries auto-appear as MCP tools)
graph_store.py      # Knowledge graph store on PostgreSQL: nodes/edges/tags tables, vector + graph hybrid search, recursive-CTE shortest path, wiki-link sync, agent_memory -> 'memory' node migration
wiki_links.py       # Obsidian-style [[wiki-links]], #tags, headings, backlink extraction from markdown uploads
lora_manager.py     # LoRA adapters: list/load/unload for GGUF, HF-PEFT training (/v1/loras/train), GGUF conversion; CPU-only training with race condition fix
image_gen.py        # Local image generation via diffusers Stable Diffusion (CPU-only, RAM-guarded, resolution 256-512, steps 8-40, writes generated/*.png)
vision.py           # Local image understanding via transformers Gemma 3 (google/gemma-3-4b-it default; PaliGemma + moondream2 fallbacks) (CPU-only, on by default, RAM-guarded >= 8GB free, lazy load once, single-analysis lock, release() on failure/shutdown)
data_science_agent.py # Local AutoML via auto-sklearn (Linux-only, CPU, opt-in, RAM-guarded >= 3GB, n_jobs=2, single-job lock, ensemble released after scoring)
computer_agent.py     # ReAct computer-use agent: shell, file I/O, web, python, process mgmt + GUI (mouse/keyboard) tools
gui_automation.py     # Native Windows keyboard & mouse control (ctypes SendInput, zero deps; Pillow for screenshots) - "human hands" for the computer agent
api.py              # FastAPI server (all API endpoints incl. workspaces, LoRA upload/train, skills/agents CRUD, images + admin ring-buffer logs; HTTP/2 with httptools fallback; GET /mcp for tool discovery)
cli.py              # Terminal CLI: live token streaming by default, ensemble /parallel mode, /agent add|delete & /skill add|delete personas, /mcp tool listing + calling, /code, /harness (stats/reset/adjust/export/import), /cloud, /arc, /context, /status, sessions (JSON under sessions/), Windows line-editor input
web_ui.py           # Mounts Next.js build (frontend/build) + inline HTML fallback + /generated images; serves /,chat,/dashboard,/terminal,/workspace,/database,/models,/admin,/tools,/settings,/help with injected auth bootstrap
frontend/           # Next.js glassmorphism multipage UI (run.py --nextjs) in TypeScript (.tsx/.ts): Landing / (hero, architecture flow, hardware models + Hugging Face download guide, datasets, live system pulse, custom icon set) / Dashboard (live sparklines with useChartTheme hook) / Terminal (Agentic Terminal: 3-pane IDE + full CLI setup guide) / Chat (markdown rendering, suggestion chips, auto-resize textarea, conversation search + export as markdown, per-message copy) / Workspace (Protected badge on default workspace, file content preview) / Database (connection pool, IVFFlat, agent breakdown, table size) / Models (lazy load/unload, role filter chips, per-model n_ctx/temperature/max_tokens) / Tools (summarize·analyze·translate·agents·skills·images with copy-to-clipboard buttons) / Graph (node/tags/recent tabs, semantic hybrid search, click-to-view node content) / Admin (metrics, threads, logs, LoRA upload+train, skills/agents add+delete, interactive MCP tool calling, harness table with reset/adjust, per-tab loading skeletons) / Settings (API keys, live /v1/config editor, rate-limit reset to defaults) / Help (collapsible sections, pgvector/pgsql setup guide); components: ErrorBoundary, ThemeProvider (class-based dark/light), PageTransition, Sidebar (collapse/expand, backend health, mobile responsive); lib: api.ts (fetchJSON+token helpers), chartTheme.ts (useChartTheme hook), i18n.ts
test_load.py        # Load/balance stress tool (cheap endpoints + real chat generations)

## GPU Hardware
- AMD Radeon RX 5600 XT (6 GB VRAM, PCIe 3.0)
- Vulkan backend via ggml-vulkan.dll (built from source)
- Hy-MT2 1.8B Q4_K_M uses ~1.1 GB VRAM; Gemma 4 E4B Q2_K_XL ~3 GB; Qwen2.5-Omni 3B Q4_K_M ~2.5 GB; Mythos-nano Q5_K_M ~2.7 GB
- Models load one at a time and LRU-evict under the 6 GB budget

## CPU
- Intel i3-10100F (4C/8T, 3.6 GHz)
- Threads auto-set to n_cores // 2 (keeps CPU at 45-75%)

## Disk (C:\)
- WDC PC SN520 256GB SSD - pgvector data uses IVFFlat indexes on SSD
- PostgreSQL optimized: connection pool (1-4), LRU query cache (30s TTL), batch inserts

## Optimizations
- **Multi-candidate Planning**: Hy-MT2 generates 2 candidate plans, ranked by length + small random tiebreak (simple select-best, not a true A* search and no candidate expansion)
- **Parallel Execution**: on non-stream requests, up to `parallel_max` executor models (default 2) answer the same prompt concurrently in a thread pool; Hy-MT2 judges each on 0-10 and the best wins (`parallel=false` disables, `--no-parallel`)
- **Selection Room**: `router.classify_task` buckets the prompt (code/math/summarize/translate/tool/creative/general); `Harness` keeps an epsilon-greedy per-(task,model) fitness = success*60 + speed*30 + recency*10 (recency decays by `harness.decay` every 25 records); `ModelRouter` ranks executors harness-first with capability fallback; `CONFIG.auto_load` preloads ranked executors under `vram_budget_mb` with LRU eviction; `reset()`/`adjust()`/`export_stats()`/`import_stats()` for full lifecycle management
- **Hardware Auto-tune**: `hardware.auto_tune()` on startup (run.py + API lifespan) detects RAM/VRAM/backend, sets threads=cores//2, `vram_budget_mb=vram-1024` (min 512) when 0, caps n_ctx to 2048 when RAM<16GB (`--no-auto-tune`, `--vram <MB>`, `GET /v1/hardware`)
- **GPU batch tuning**: every model loads with `n_batch=2048` / `n_ubatch=512` (configurable per-`ModelConfig`), which speeds up prompt evaluation on the Vulkan backend; flash attention was benchmarked and gives no gain on AMD/Vulkan so it stays off
- **CPU throttle recovery**: `HardwareMonitor._enforce()` throttles threads only while CPU > 75% and **restores** `optimal_threads()` once pressure subsides, so inference is never permanently stuck at 1 thread after a spike (was a one-way degradation)
- **Metrics**: `metrics.snapshot()` records requests/tokens/latency per model and task (`GET /v1/metrics`); harness scores via `GET /v1/router/stats`
- **Realtime hardware sampler**: a daemon thread in `hardware.py` (interval 1.5s) refreshes a live cache (RAM available, VRAM used via 5s-TTL probe, non-blocking `psutil.cpu_percent(interval=None)`) that `detect_hardware()` overlays on cached static info, so `/v1/hardware` and `/v1/system` report moving CPU/RAM/VRAM values without re-probing subprocesses (`?refresh=1` forces a synchronous re-probe); `metrics.snapshot()` also emits `tokens_per_sec_window` (60s sliding-window average) which the Dashboard charts instead of the flat cumulative `tokens_per_sec`
- **ARC eval**: `arc.run_arc_eval()` measures grid-reasoning accuracy over `arc/training.json` (`/arc [n]` in CLI, `exact=` toggles prefix-vs-full match)
- **Single-pass execution**: one plan-then-execute pass per request (no iterative agentic loop; errors raise and roll back the unanswered turn)
- **Auto-agentic streaming**: `Orchestrator.auto_stream()` (POST `/v1/chat/auto-stream`) decides per-request between real-time streaming and batch: `_should_auto_stream()` streams when planning is on, the message is long (>100 chars), or code/creative keywords hit, and caps via `auto_stream_max_tokens` (min threshold `auto_stream_min_tokens`); streaming path delegates to `stream()` (thinking events filtered by `auto_stream_thinking`/`stream_thoughts`), batch path wraps `run()` in the same start/thinking/response/done/error SSE protocol; configurable via run.py `--auto-stream*` flags and `LLM_AUTO_STREAM*` env vars; frontend streams through `frontend/lib/api.ts autoStreamChat()` with a `ThinkingIndicator` panel (`frontend/components/ThinkingIndicator.tsx`)
- **Chat file uploads**: `POST /v1/chat/upload` (multipart, needs `python-multipart`) writes sanitized files under `generated/chat_uploads/` (20MB cap, uuid-prefixed, path-traversal-proof) served via the existing `/generated` StaticFiles mount; PDFs get best-effort text extraction (`_extract_pdf_text()`, needs `pypdf` or `PyPDF2`, 8k char cap) returned as `preview_text`; image uploads (png/jpg/gif/webp/bmp) return `is_image: true` and, when vision is enabled, a best-effort `preview_text` description via `vision.describe_image_file()` (never fails the upload); the chat UI supports drag & drop + a paperclip picker with file preview chips, uploads first, then inlines `[name](url)` markdown links (plus the extracted PDF text as code context) into the user message (`uploadChatFile()` in `frontend/lib/api.ts`)
- **Local vision**: `vision.py` adds CPU image understanding via Google **Gemma 3** (`google/gemma-3-4b-it` default; PaliGemma + moondream2 fallbacks; transformers, `trust_remote_code=True`, pinned to CPU); enabled by default through `CONFIG.vision.enabled` (run.py `--vision` / `--vision-model`, env `LLM_VISION` / `LLM_VISION_MODEL`, or `POST /v1/config vision.enabled/model/max_tokens`); lazily loads the model once behind a free-RAM guard (>= 8 GB; falls back to a usable estimate when psutil is missing) with a single-analysis lock, and `release()` frees it on inference failure / shutdown (release is called after the lock is released so it cannot self-deadlock); Gemma-family checkpoints run through the processor + `generate` API (`AutoProcessor`/`AutoModelForImageTextToText`, chat-template path for Gemma 3, direct images+text for PaliGemma); `POST /v1/vision/analyze` accepts a base64 or data-URI image (whitespace-tolerant) plus an optional prompt and returns `{description, prompt, model, device, elapsed_s}`; the Tools UI exposes it as a Vision tab (`frontend/app/tools/page.tsx`, `Eye` icon) and image uploads in chat auto-inline a description as context when enabled
- **Dynamic safety monitor**: `hardware.get_hw_monitor(model_manager)` is started in the API lifespan, activating the existing `HardwareMonitor` daemon (30s interval) that evicts LRU models when RAM < 4GB or VRAM exceeds budget and throttles `CONFIG.threads` when CPU > 75%, so the box never stays pegged at 100%. On GPU backends whose VRAM probe reads 0 (e.g. AMD/Vulkan), the monitor cross-checks `model_manager.vram_used()` (estimate-based) so eviction still fires; eviction uses a bounded `try_unload()` so the monitor never blocks behind a hung generation
- **Data Science (AutoML)**: `data_science_agent.py` adds an Auto-Sklearn-backed data-science agent (Linux-only — `auto-sklearn` ships SWIG/C-extension wheels not built for Windows, so `import data_science_agent` is import-safe and the feature reports "not available" rather than crashing). Opt-in via `CONFIG.automl.enabled` (run.py `--automl` / `--automl-model-dir`, env `LLM_AUTOML` / `LLM_AUTOML_MODEL_DIR` / `LLM_AUTOML_TIME_LIMIT`, or `POST /v1/config automl.*` keys); lazily imports autosklearn/pandas/scikit-learn/joblib only at training time, validates free RAM (>= 3 GB) via `hardware.detect_hardware`, serializes jobs with a lock, caps `n_jobs=2` + `memory_limit`, and releases the trained ensemble after scoring; exposed as the **Data Science** tab in the Tools UI. `auto-sklearn` is intentionally **not** added to `requirements.txt` (it would break `pip install` on Windows); install on Linux with `pip install auto-sklearn pandas scikit-learn joblib`
- **LoRA safety**: `lora_manager.import_adapter`/`train_lora` sanitize the adapter name and output name (basename + allowlist) to prevent path traversal into `loras/`; training datasets are restricted to `lora_datasets/`; a single training lock serializes `/v1/loras/train` requests so concurrent trainings cannot collide
- **Computer agent hardening**: `computer_agent` uses a brace-matching parser (`_balanced_json_block`) so tool calls with nested JSON args parse correctly; in sandbox mode `read_file`/`list_dir`/`search_files` are scoped to the project directory; `/v1/computer/*` caps `max_steps` (1-50) and the API enforces `sandbox = CONFIG.sandbox or req.sandbox` so `--sandbox` cannot be downgraded by a caller
- **GUI (human hands) automation**: `gui_automation.py` adds native Windows keyboard + mouse tools to the computer agent (`mouse_move`/`mouse_click`/`mouse_drag`/`mouse_scroll`/`keyboard_type`/`keyboard_press`/`cursor_position`/`screenshot`) built on ctypes SendInput with zero third-party deps (Pillow only for screenshots); gated behind `CONFIG.computer['allow_gui']` (run.py `--allow-gui`, env `LLM_ALLOW_GUI=on`, or CLI `/computer gui on`); these are `dangerous` tools, so sandbox mode blocks them; `screenshot` saves to `generated/gui_screenshots/` so the model can "see" the screen like a person
- **Workspaces**: isolated chat areas backed by PostgreSQL `workspaces`/`workspace_files` tables (in-memory fallback when DB off); conversations are workspace-indexed in `MemoryManager`, workspace `system_prompt` is injected into chats, file uploads are chunked (600 chars / 120 overlap) and embedded under agent `workspace:<id>` so `orchestrator.run/stream` merges global + workspace-scoped knowledge (de-duped); export/import re-binds conversations to the target workspace and never mutates a conversation owned by another workspace; the built-in `default` workspace is delete-protected
- **Embedder guard**: pgvector store/search functions return early when the pool is unavailable, so the sentence-transformers model is never loaded for embedding when PostgreSQL is off (avoids a multi-second stall on first DB-touching call)
- **Swappable embedder**: `CONFIG.embedder` (env `LLM_EMBEDDER_PROVIDER/MODEL/DIMENSION/API_KEY/BASE_URL`, `POST /v1/config embedder.*`) selects the embedding source — `local` (default sentence-transformers `all-MiniLM-L6-v2`) or a remote OpenAI-compatible `/embeddings` endpoint (`openai|azure|openrouter|groq|gemini`); `database.get_embedder()` returns a `_RemoteEmbedder` (urllib, L2-normalized, dim-truncated) and `embed_dim()` drives the schema; `_ensure_schema` builds `vector(%s)` from the configured dimension and `_migrate_vector_dim()` re-creates the pgvector column + drops the ivfflat/hnsw index when the dimension changes; `reset_embedder()` clears the cached embedder so config edits take effect live
- **Workspace-scoped memories**: `agent_memory` carries `workspace_id` (default `default`, indexed `idx_agent_memory_ws`); `store_thought`/`store_batch`/`retrieve_similar`/`count_memories`/`recent_memories`/`search_memories`/`prune_memories`/`clear_memories` all accept workspace scoping; `orchestrator.run/stream` scope retrieval to the active workspace (non-default) while still merging global + workspace knowledge; `delete_workspace` cascades the workspace's memories
- **Sessions**: `sessions` table (id/name/user_id/metadata JSONB/timestamps) + CRUD (`create_session` upserts, `get_session`, `list_sessions`, `touch_session` heartbeat, `delete_session`, `prune_sessions`) with in-memory ring fallback when DB off; exposed as `/v1/sessions*` (list/create/get/update/delete/prune) for multi-user identity and persisted contexts
- **Metrics snapshots**: `save_metrics_snapshot`/`list_metrics_snapshots`/`prune_metrics_snapshots` persist `MetricsCollector.snapshot()` JSONB into `metrics_snapshots` (in-memory ring fallback, capped 500) so `GET /v1/metrics/history` returns trending charts; the API lifespan runs a daemon thread (60s) that snapshots + prunes to 1000 rows while the DB is enabled
- **Concurrency**: per-model locks allow different models to generate in parallel; same-model calls are serialized; each model's llama_cpp calls run on its own pinned worker thread (single-thread executor) so GPU inference is never invoked from multiple threads
- **Generation watchdog**: a hung generation (known llama.cpp/Vulkan sampler stall on AMD) is killed after `gen.timeout_s` (default 240, `--gen-timeout`, `POST /v1/config gen.timeout_s`, env `LLM_GEN_TIMEOUT`); the stuck instance+worker are discarded and the next request auto-reloads the model (OpenAI fallback applies if enabled)
- **Streaming**: `/v1/chat/stream` and `stream=true` yield real tokens via `llama_cpp(stream=True)`; blocking inference runs in a worker thread so the event loop stays responsive
- **DB Auto-Creation**: `database.py` auto-creates the database if missing (connects to `postgres` DB, issues `CREATE DATABASE`, then reconnects); registers pgAdmin 4 connection in `servers.json` automatically on startup
- **DB Tuning**: adaptive pgvector index (<100 rows: none; 100-2000: HNSW; >2000: IVFFlat with lists=sqrt(rows)), auto recreated on threshold crossing, composite indexes, query cache (30s TTL), connection pool (1-4)
- **RAM**: Embedding model on CUDA if available, else CPU; context 2048 for strategist
- **Auto-prune**: `db.start_auto_prune()` deletes memories older than `prune_max_age_days` every `prune_interval_hours` while the DB is enabled (started by `run.py` and the API lifespan)
- **Port safety**: `run.py` auto-switches to a free common port when the requested one is busy (`--force-port` opt-in to kill the occupying process)
- **GGUF discovery**: any `.gguf` dropped into `models/` is auto-registered as an Executor (visible in `/v1/models` and the UI); `--add-model PATH` registers a file from anywhere
- **Cloud presets**: OpenAI, Claude (Anthropic), Groq, OpenRouter, Gemini with auto-detection of `ANTHROPIC_API_KEY` env var
- **API token rotation**: `CONFIG.set_api_token()` (run.py `--api-token`, env `API_TOKEN`, or `POST /v1/config` key `api_token`) accepts a comma-separated rotation set — first token is primary, rest staged as extras; `CONFIG.token_authorized()` validates any token in the set with constant-time compares, so operators can pre-stage a new key and cut over without breaking in-flight clients (`GET /v1/config` reports `api_token_count`)
- **OpenAI fallback rate limiting**: sliding-window limiter (`openai.rate_limit_per_min`, default 10 calls/min, `POST /v1/config`) + exponential backoff (`openai.backoff_max_s`, default 60) so cloud fallback never hammers the API; shared across `models.generate`/`chat` and `orchestrator._call_openai`
- **MCP**: `GET /mcp` serves tool discovery for browser/admin UIs; `POST /mcp` handles JSON-RPC `tools/call` and `tools/list`; `_build_mcp_tools()` extracted to eliminate duplication; skill params have individual schema entries with descriptions; CLI `/mcp` lists tools and `/mcp call <tool> <input>` invokes them
- **CLI Harness**: `/harness` shows per-task/model scores table; `/harness reset` resets scores; `/harness adjust <task> <model> <score>` manually adjusts; `/harness export`/`/harness import` for persistence
- **CLI command whitelist**: `CONFIG.cli_command_whitelist` (run.py `--cli-commands`, env `LLM_CLI_COMMANDS`, comma-separated) restricts which slash commands the CLI executes — anything unlisted prints `Blocked: ...`; `/help /? /exit /quit /status` are always allowed; tab-completion (`_visible_commands`) only offers permitted commands
- **Frontend Theme**: CSS variable-based light/dark theme with `MutationObserver`-driven chart hooks; `@tailwindcss/typography` for prose/markdown; glassmorphism cards with hover-lift; `suppressHydrationWarning` + inline FOUC prevention script; `ErrorBoundary` wraps page content; reduced-motion support; badge variants (success/danger); scrollbar polish; light theme input/button polish
- **Frontend Streaming**: proper `data:` frame SSE parsing with auth token; markdown rendering with `react-markdown` + `react-syntax-highlighter` + copy button; auto-resize textarea
- **Frontend Accessibility**: `aria-expanded` on collapsible sections; `aria-label` attributes; label-input linking; focus-visible outlines
- **Multipage WebUI**: `/` is a landing page (hero, architecture flow, hardware-optimized model cards, Hugging Face download guide, datasets, live system pulse), `/dashboard` is the live metrics dashboard, and `/terminal` is the Agentic Terminal (IDE workspace + full CLI setup guide); the ASCII logo is served as a PNG (`/static/ascii-logo.png`, legacy `/ascii-logo.png` redirects) and a hand-drawn custom SVG icon set (`components/icons.tsx`) replaces stock icons on the landing + sidebar; fluid `clamp()` typography, staggered entrance animations, glass hover glow, focus rings and `::selection` polish; brand renamed to "Sovereign AI" in the sidebar

---
**Built by Rakibul Hasan (Rhasan_Indie_dev).**
