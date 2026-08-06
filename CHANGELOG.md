# Changelog

All notable changes to **Sovereign-Agentic-AI** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

- GitHub Actions CI (Python offline suite + Next.js build) with live badge.
- README screenshots gallery (real captures of landing / dashboard / terminal / chat).

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
