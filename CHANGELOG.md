# Changelog

All notable changes to **Sovereign-Agentic-AI** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

- GitHub Actions CI (Python offline suite + Next.js build) with live badge.
- README screenshots gallery (real captures of landing / dashboard / terminal / chat).
- **GBNF auto-approved workflow** (`action_models.py`, `gbnf_parser.py`, `orchestrator.py`):
  agentic loop with `[THINK]/[BASH]/[READ]/[WRITE]/[DONE]` tags, live SSE trace streaming,
  and `/v1/chat/auto-stream/workflow` + `/v1/agent/auto` endpoints.
- **Frontend AgentTrace integration** (`AgentTrace.tsx`, `workflowStream`): live action tracing
  for `agent_x` with color-coded status, elapsed time, and auto-scroll.
- **GPU-safe hardware monitor** (`hardware.py`): 30s background tick, LRU eviction on VRAM/RAM
  pressure, CPU throttle at >75% with auto-restore, `/v1/hardware/stream` SSE endpoint.
- **Web UI Model Management** (`frontend/app/models/page.tsx`): pull models from URL with
  progress bars, installed models table with sizes, load/unload toggles.
- **CLI polish** (`cli.py`): tab-completion for slash commands (Windows msvcrt + readline),
  reorganized categorized `/help` with examples, improved error guidance.
- **Code quality**: all long lines >120 chars fixed, zero debug prints, zero bare except,
  zero TODO/FIXME across `.py` files; TypeScript compiles cleanly.

## [v1.2.1] - 2026-08-08

### Security & sandbox

- `/v1/terminal/exec` enforces `computer_agent._sandboxed_shell_ok()`: a sandboxed
  `shell=True` command is rejected (400) when it escapes the project via `..` traversal
  (including spaced escapes), drive-absolute paths (`C:\`), UNC paths, or an absolute
  `cd` — `--sandbox` previously confined files but not shell commands.
- Self-healing snippets are written as UTF-8 (`healing_agent._exec_subprocess`), so
  non-ASCII code no longer crashes the candidate subprocess before it runs; the
  `HealingRequest.timeout_s` API field is validated to 1–120 s.

### Fixed

- CLI: the `!!` re-run shortcut was dead (it fell through to the shell branch and sent the
  literal `!!` to the model as a prompt); TUI thinking events were printed over the
  fixed-screen layout; `/mcp call` used `api.orchestrator` instead of the CLI's own
  pipeline (ignoring `/model`, `/agent`, `/temperature`, and the active conversation);
  the command whitelist now normalizes the leading `/` on both sides.
- Metrics: `per_task[task].tokens_out` was always 0 — `orchestrator.run()/stream()` now
  pass the real token count.
- DB rollback compensation off-by-timestamp: `rollback_to()` used the last *kept*
  message's in-memory timestamp as the delete boundary, which also deleted that message's
  DB row (DB rows are timestamped strictly later); the boundary is now the first
  *removed* message with a `>=` comparison, and nothing is wiped when there is nothing to
  roll back (previously `after_ts=0.0` deleted the whole conversation).
- `run.py`: `--db-password` default `"postgres"` clobbered the `PGPASSWORD` env var
  (default is now `None`); `--rate-light`/`--rate-heavy` unconditionally overwrote the
  `LLM_RATE_LIGHT`/`LLM_RATE_HEAVY` env vars (now applied only when explicitly passed);
  `NEXT_PUBLIC_API_BASE` was baked from the pre-fallback port (resolution now runs first).
- `agents.py`: `render_skill()` raised an uncaught `TypeError` when a skill param was named
  `input`; names that slug to the same file (`my agent` vs `my-agent`) silently overwrote
  each other (now rejected); a failed DB delete left a row that re-hydrated a "deleted"
  agent/skill on restart (state is now restored and delete reports failure); JSON
  persistence is atomic (tempfile + `os.replace` + fsync); `get_agent()`/`get_skill()`
  return copies instead of live registry dicts.
- `hardware.py`: CPU recovery restored threads to `optimal_threads()` (cores/2) instead of
  the pre-throttle value, clobbering a user-set `--threads`; `_enforce()` VRAM budget
  lacked the 512 MB floor from `auto_tune()`; the live VRAM cache is now lock-guarded.
- `arc.py`: a flat JSON array (`[1,2,3]`) was mis-parsed as one column per cell instead of
  a single row.
- `image_gen.py`: width/height now round to a multiple of 8 (Stable Diffusion VAE
  requirement) after clamping.
- `wiki_links.py`: the `#tag` regex now excludes a preceding `#`, so `##Heading` no longer
  yields a false `#Heading` tag.
- `gui_automation.py`: printable punctuation not in the VK table was mapped via `ord()`
  (e.g. `!` → 0x21 = PageUp); such characters now go through the Unicode input path.

## [v1.0.0] - 2026-08-06

### Added

- **Multi-agent pipeline** (`orchestrator.py`): a Hy-MT2 *strategist* generates 2 candidate
  plans, up to `parallel_max` executors answer concurrently, and the strategist *judges*
  each reply on a 0–10 scale before the best answer is returned.
- **Adaptive selection room** (`router.py`): `classify_task` buckets prompts into
  code/math/summarize/translate/tool/creative/general; a learned `Harness` keeps an
  epsilon-greedy per-(task, model) fitness = success·60 + speed·30 + recency·10, and
  `ModelRouter` ranks executors harness-first with capability fallback.
- **Lazy local inference** (`models.py`): GGUF via llama.cpp (Vulkan backend), LRU eviction
  under a VRAM budget, per-model worker threads, and a generation watchdog that kills hung
  samplers after `gen.timeout_s`.
- **pgvector memory** (`database.py`): PostgreSQL + sentence-transformers (or a swappable
  remote embedder), adaptive IVFFlat/HNSW indexes, connection pool, query cache, auto-DB
  creation and pgAdmin auto-registration.
- **Knowledge graph** (`graph_store.py` + `wiki_links.py`): Obsidian-style `[[wiki-links]]`,
  `#tags` and headings become nodes/edges; vector + graph hybrid search and recursive-CTE
  shortest path.
- **Workspaces & sessions**: isolated chat areas backed by `workspaces`/`workspace_files`,
  workspace-scoped memories, and a `sessions` table for multi-user identity.
- **Agent personas & skills** (`agents.py`): runtime add/delete persisted to JSON *and*
  mirrored to PostgreSQL; new entries appear automatically as MCP tools.
- **Agentic Terminal API** (`api.py`): sandboxed `POST /v1/terminal/exec|python` and
  `fs/*` (tree/read/write/mkdir/delete) with real `HTTPException` statuses.
- **Multipage Next.js WebUI**: landing `/` (architecture flow, hardware model cards,
  Hugging Face download guide, live system pulse), live `/dashboard`, `/terminal` rebuilt
  as a full CLI setup & usage guide, plus Graph, Admin, Tools, Settings and Help pages;
  hand-drawn custom icon set and "Sovereign AI" branding.
- **Opt-in capabilities**: local vision (Gemma 3), image generation (diffusers), AutoML
  (auto-sklearn, Linux), LoRA training, self-healing agent (gated), computer-use agent with
  GUI automation, OpenAI-compatible cloud fallback with rate limiting and token rotation.
- **OpenAI-compatible API + MCP**: `/v1/chat/completions`, streaming, auto-agentic
  streaming, and a JSON-RPC `/mcp` endpoint with tool discovery.
- **Auto-agentic streaming**: per-request stream-vs-batch decision with real-time
  thinking/token SSE events; configurable thresholds.
- **Hardware auto-tune & monitor**: detects RAM/VRAM/backend, sets threads and VRAM
  budget, caps context, throttles CPU and evicts models under memory pressure.

### Changed

- Refactored MCP tool building into `_build_mcp_tools()` to remove duplication.
- Terminal endpoints return real `HTTPException` statuses instead of opaque error strings.
- Vision moved to processor-based Gemma 3 generation (PaliGemma/moondream2 fallbacks).
- Frontend redesigned to a glassmorphism multipage UI with a custom icon set.

### Security

- Self-healing code execution is gated behind `--allow-unsafe-healing` (RCE risk by design).
- Sandbox mode enforces path traversal rejection and blocks dangerous GUI tools.
- `/generated` served via `SafeStaticFiles` with `nosniff` and attachment disposition.
- LoRA adapter names and datasets are sanitized against path traversal.

### Fixed

- Logo 404: ASCII logo served as PNG at `/static/ascii-logo.png` with a `/ascii-logo.png` alias.
- Long-line failure in `web_ui.py` (lines over 120 chars) — test suite back to 759/0.
- JSX escaping bugs in the `/terminal` setup guide (bare `\`, literal `{}` in JSX text).

---

Built by **Rakibul Hasan (Rhasan_Indie_dev)**. MIT licensed.
