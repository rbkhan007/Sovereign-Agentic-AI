# Known Issues — Sovereign-Agentic-AI

Status as of **v1.3**: all v1.2.1 issues resolved (tests green: **808/0**, TypeScript clean,
zero lint issues). The open list is empty.

Severity: `BUG` (wrong behaviour), `DESIGN` (intentional limitation / refactor), `MINOR`,
`DEADCODE` (unused but kept for compatibility).

---

## Resolved in v1.3 (GBNF workflow + Model Management + CLI polish — tests green: 808/0)

### GBNF auto-approved workflow (action_models.py / gbnf_parser.py / orchestrator.py)
- Added `TraceEvent` dataclass for structured SSE events.
- Frontend `AgentTrace` panel now connected to `/v1/chat/auto-stream/workflow` via
  `workflowStream()` client; `runAgentic` branches on `selectedAgent === 'agent_x'`.
- `/v1/agent/auto` SSE endpoint added as alias for auto-approved agent workflow.

### Hardware monitor (hardware.py / api.py)
- `/v1/hardware/stream` SSE endpoint added (1s interval live readings).
- 30s background tick enforces VRAM/RAM budgets + CPU throttle with auto-restore.

### Model management (api.py / frontend/app/models/page.tsx)
- `/v1/models/installed` lists `.gguf` files with sizes.
- `/v1/models/pull` downloads models from URL with SSE progress (`percent`, `downloaded_mb`).
- Frontend Models page shows Pull Model form + Installed Models table.

### CLI polish (cli.py)
- Tab-completion: Windows msvcrt editor cycles matches + shows all; non-Windows uses
  `readline` completer.
- `/help` reorganized into Quick Start / System / Models / Planning / Agents / Generation /
  Conversations / Cloud / MCP / Examples / Shortcuts.

---

## Resolved in v1.2.1 (sandbox/healing hardening + file-by-file audit sweep — tests green: 808/0, DEEP AUDIT PASSED)

### Sandbox hardening (computer_agent.py / api.py)
- `/v1/terminal/exec` now enforces the new `computer_agent._sandboxed_shell_ok()` guard: a sandboxed `shell=True` subprocess is rejected (400) when the command escapes the project via `..` traversal (incl. spaced escapes), drive-absolute paths (`C:\`), UNC paths, or an absolute `cd` — previously `--sandbox` confined *files* but not shell commands.
- Confirmed the earlier terminal sandbox gates are intact (`/v1/terminal/python`, `/v1/terminal/fs/write|delete`, `_is_admin_mutation` coverage).

### Self-healing hardening (healing_agent.py / api.py)
- `healing_agent._exec_subprocess` now writes the candidate snippet with `encoding="utf-8"` (was the default locale encoding — non-ASCII code crashed the subprocess before it could run).
- `api.HealingRequest.timeout_s` is validated 1–120 so a caller can no longer spin a healing job for days.

### CLI fixes (cli.py)
- The `!!` re-run shortcut was dead: it starts with `!` but not `!!`, so the dispatch fell through to the shell branch and the literal string `!!` was sent to the model as a prompt. Now `!!` re-runs `_ask()` with the last prompt.
- TUI thinking events were `print()`ed over the fixed-screen layout, garbling the input row; they now render as a `thinking` message inside the TUI.
- `/mcp call` imported `api.orchestrator` (a different pipeline) instead of the CLI’s own orchestrator, so it ignored `/model`, `/agent`, `/temperature`, and the current conversation; it now uses the passed-in orchestrator.
- CLI command whitelist matching now normalizes the leading `/` on both sides, so `--cli-commands /model,lora` (or bare `model,lora`) all match `/model train` etc. instead of silently blocking bare forms.

### Harness & metrics correctness (orchestrator.py)
- `per_task[task].tokens_out` was always 0: `orchestrator.run()/stream()` called `record_completion(task=...)` without `tokens_out`. Both paths now pass the real token count, so `/v1/metrics` per-task numbers match per-model.

### DB rollback compensation off-by-timestamp (memory.py / database.py)
- `rollback_to()` used the last *kept* message’s in-memory timestamp as the DB delete boundary, but DB rows are timestamped strictly later, so the compensation also deleted the last kept message’s row. The boundary is now the first *removed* message’s in-memory timestamp with a `>=` comparison (ordering `mem[idx-1] < db[idx-1] < mem[idx] < db[idx]` guarantees correctness), and nothing is deleted when there is nothing to roll back (previously `after_ts=0.0` would wipe the whole conversation).

### Runtime config flags (run.py)
- `--db-password` default `"postgres"` was always truthy, so it clobbered the `PGPASSWORD` env var; default is now `None` (env/`postgres` fallback preserved).
- `--rate-light` / `--rate-heavy` unconditionally overwrote `LLM_RATE_LIGHT`/`LLM_RATE_HEAVY` env; now only applied when explicitly passed.
- `NEXT_PUBLIC_API_BASE` was baked from the pre-fallback `args.port`; port resolution now runs before the Next.js dev server spawns.

### Agent/skill registry resilience (agents.py)
- `render_skill()` raised an uncaught `TypeError` when a skill param was named `input` (collides with the reserved `{input}` placeholder); such params are skipped and `TypeError` added to the fallback handler.
- Distinct names that slug to the same file (`my agent` vs `my-agent`) silently overwrote each other’s JSON; `add_agent`/`add_skill` now reject the collision.
- Deleting an agent/skill with a live DB whose `delete_agent`/`delete_skill` failed left the DB row behind, which re-hydrated the entry on restart (resurrection); the registry + JSON are now restored and the delete reports failure.
- JSON persistence is now atomic (tempfile + `os.replace` + fsync) so a torn write can’t silently skip an entry on load.
- `get_agent()`/`get_skill()` return copies instead of live registry dicts.

### Hardware monitor (hardware.py)
- CPU recovery restored threads to `optimal_threads()` (cores/2) instead of the pre-throttle value, clobbering a user-set `--threads`; the monitor now remembers and restores the pre-throttle thread count.
- `_enforce()` VRAM budget lacked the `auto_tune()` 512 MB floor, so a sub-1 GB GPU could get a negative budget that silently disabled VRAM eviction.
- The live VRAM cache read-modify-write is now guarded by a lock.

### Misc (arc.py / image_gen.py / wiki_links.py / gui_automation.py)
- `arc.parse_grid()` mis-parsed a flat JSON array (`[1,2,3]` = one row) as one column per cell; single-dim arrays now parse as a single row.
- `image_gen.generate_image()` width/height now round to a multiple of 8 (the Stable Diffusion VAE requirement) after clamping.
- `wiki_links` `#tag` regex now excludes a preceding `#`, so `##Heading` no longer produces a false `#Heading` tag.
- `gui_automation.press()` mapped printable punctuation not in the VK table via `ord()` (e.g. `!` -> 0x21 = PageUp); such characters now go through the Unicode input path.

---

## Resolved in v1.2.0 (deep review sweep — tests green: 759/0, DEEP AUDIT PASSED)
### Security & sandbox (api.py / computer_agent.py)
- `/v1/terminal/python` was **unauthenticated, unsandboxed arbitrary code execution**: now sandbox-gated (403 when `--sandbox`, or when the caller's `sandbox` flag is set), passes `req.timeout` through to `_tool_python_exec`, and returns the correct `stderr` field.
- `/v1/terminal/fs/write` now enforces `_sandbox_scoped()` (path-traversal / outside-project writes blocked) instead of ignoring the sandbox.
- `_is_admin_mutation()` now covers `/v1/terminal/exec`, `/v1/terminal/python`, `/v1/terminal/fs/write|delete|mkdir`, so `--admin-key` guards terminal control-plane operations.
- `computer_agent._sandbox_scoped()` uses `os.path.realpath()` so symlinks/junctions cannot escape the project root.
- `computer_agent._tool_web_fetch()` blocks non-`http/https` schemes (a `file://` URL could previously exfiltrate local files).
- `computer_agent._tool_python_exec()` now runs in a daemon thread with a hard timeout (30s default), a result queue, and `contextlib.redirect_stdout/stderr` restored in `finally` — the old global `sys.stdout` swap clobbered concurrent calls and never restored output.

### Correctness (models.py / orchestrator.py)
- `generate_stream()` holds the per-model lock for the whole generator lifetime; `orchestrator.stream()` and `auto_stream()` now `close()` the inner generator in `finally` so the lock is released even when the consumer stops early (OpenAI fallback, error, disconnect).
- `_unload_for_budget()` evicts until `vram_used() + estimate <= budget` (was `vram_used() <= budget`), so a new model load can no longer overshoot the VRAM budget by one model's footprint.
- `orchestrator.run()` parallel path now filters executors to the models `ensure_loaded()` actually returned, instead of blindly launching threads for models that were never loaded.

### Database resilience (database.py / memory.py)
- `_get_conn()` on a broken pooled connection now returns it via `pool.putconn(conn, close=True)` (was `conn.close()` alone), which permanently pinned the psycopg2 thread-keyed pool; an all-dead pool is torn down via new `_mark_pool_down()` so the background reconnect thread can rebuild it — mid-run Postgres outages are now recoverable.
- `Conversation.rollback_to()` compensates the DB copy: new `delete_conversation_messages_after()` removes messages persisted after the rollback boundary, so a failed turn can't resurface on reload.
- `graph_store._embed_dim()` derives from `database.embed_dim()` instead of a hardcoded 384, so the nodes/tags schema matches a remote embedder's dimension.
- `data_science_agent` training lock is acquired *outside* the try block — the acquire-timeout early-return used to call `release()` on an un-acquired lock.
- `healing_agent.heal()` now honors `CONFIG.healing.timeout_s` / `max_retries` (was hardcoded `gen_timeout_s` / 2).

### Vision & LoRA (vision.py / lora_manager.py)
- `_is_gemma()` no longer matches `"paligemma"`; PaliGemma checkpoints now load via `AutoProcessor` + causal LM and run through a dedicated `_run_paligemma_inference()`; moondream2 uses `encode_image()` + `answer_question()`.
- Gemma 3 chat content block now uses `{"type": "image", "image": img}` (was missing the `image` key, so the processor saw zero images and raised).
- `lora_manager.train_lora()` no longer passes the removed `use_cache` kwarg to `prepare_model_for_kbit_training()` (peft ≥ 0.7 `TypeError`); CPU training sets `model.config.use_cache = False` instead.

### Frontend contract fixes (frontend/ — ESLint + `tsc --noEmit` clean)
- `toArray()` now recognizes `workspaces`/`files`/`memories`/`edges` keys (Workspace page lists were always empty).
- Workspace knowledge search sends `?query=` (api requires `query`, not `q`).
- Graph semantic tab maps `/v1/graph/hybrid` flat node dicts (`{title, similarity, linked, backlinked}`) to the expected `{node, score, neighbours}` shape; tags tab maps `{id, name, metadata}` → `{tag, count}`.
- Admin logs/threads now unwrap `{count, lines}` / `{count, threads}` responses (previously `Array.isArray` → always empty).
- Database page memory tabs map `recent_memories` (`thought`/`agent`) and plain-string `retrieve_similar` results to the rendered `{content, score, agent}` shape.

---

## Resolved in v1.0.0 (for reference)
- `graph_store.py` — tag-edge FK corruption → tags are now `nodes` of type `tag`.
- `healing_agent.py` — RCE via un-gated code execution → gated behind `--allow-unsafe-healing`.
- `web_ui.py` — stored XSS via `/generated` → `SafeStaticFiles` with `nosniff` + forced download.
- `vision.py` — moondream2 wrong API → `answer_question` pipeline; now superseded by Gemma 3 / PaliGemma processor-based generation (moondream2 kept as a fallback path).

## Resolved in v1.1.0 (tests green: 759/0)
- `orchestrator.py:70` — `_resolve_executor()` now honors `model_override` → `self.executor` → `router.primary()` fallback, and ranks for the *classified* task, so CLI `/model <name>` takes effect.
- `orchestrator.py:178-206,227` — `_build_exec_prompt()` now accepts and injects pgvector/workspace/graph memories, so RAG works with `use_planning=False` too.
- `orchestrator.py:513-528` — streaming `auto_stream()` and `stream()` emit a terminal `{"type":"done"}` event (model/tokens/elapsed), matching the batch protocol.
- `orchestrator.py:444-448` — `auto_stream_max_tokens` is now a real hard cap on forwarded `max_tokens`, not just a comparison threshold.
- `hardware.py:358` — `HardwareMonitor._enforce()` uses `detect_hardware(force=False)` (live sampler cache), so the monitor no longer re-runs expensive probes that inflate its own CPU reading.
- `hardware.py` — `get_hw_monitor()` rebinds the singleton to newly-created managers (CLI, arc, tests) instead of caching the first one forever.
- `hardware.py` — **AMD/Vulkan VRAM reporting**: `_vram_total_mb()` adds a DXGI `GetDesc` probe (real 6103 MB on the RX 5600 XT vs WMI's 4095 MB cap); `_vram_used_mb()` falls back to the registered `ModelManager.vram_used()` estimate when no nvidia-smi/torch probe exists, so `/v1/hardware` and the live dashboard report real loaded-model VRAM instead of 0.
- `cli.py:1941` — `full` mode reuses `api.model_manager` via `run_cli(model_manager=...)`; no double `ModelManager` / double VRAM in one process.
- `cli.py:497-511` — `_render_messages()` computes cell heights with `_message_cell_height()` (4 + wrapped lines) and scrolls by rows, not message count.
- `cli.py:475` — scroll-region reset writes `ESC[1;{h}r` instead of a one-line region.
- `cli.py:177-185` — `_COMMANDS` includes `/mcp`, `/temp`, `/shell`, `/max-tokens` (tab-completion + suggestions).
- `cli.py:1899-1909` — `/lora train` arg parsing fixed (requires `<base> <dataset> <output> [epochs]`).
- `router.py:92-101` — `rank_for_task()` now wires `Harness.choose()` (epsilon-greedy, gated on `has_recorded()` so fresh harnesses stay deterministic); `CONFIG.harness_epsilon` is live.
- `router.py:238-248` — `select_executors()` no longer demotes a loaded override behind other models.
- `router.py:15-19` — the `"code"` bucket only keeps genuinely code-specific tokens; general prompts route correctly again.
- `metrics.py:55-61,81` — failed completions no longer pollute `latency_sum`/`latency_n`; `success_rate` is clamped to `[0,1]`.
- `agents.py:277-280` — `render_skill()` catches `IndexError` from bare `{}`/`{0}` templates.
- `image_gen.py:63-71,92-94` — `_cap()` clamps the config default too (no 2048-width bypass).
- `run.py:452` — port auto-fallback syncs `CONFIG.port` (GET /v1/config reports the real port).
- `graph_store.py:704,670-676,795` — `list_nodes`/`hybrid_search`/`shortest_path` pass one held connection through (no nested pool acquisitions).
- `graph_store.py:770-786` — `shortest_path()` filters `edge_type` in both CTE arms.
- `graph_store.py:29-41` — `threading` imported at module top (no `NameError`, `_SCHEMA_ENSURE_LOCK` guard works).
- `arc.py:89` — removed non-existent `model_manager.default_model` read (dead branch).
- `frontend` — colorful density-based ASCII logo (light theme), Agents group in the sidebar with full persona names + role + icons, `?agent=` preselects the persona in chat, light-theme shadow/glass polish.
- `frontend` — multipage WebUI: landing `/` (architecture flow, hardware models, HF download guide, datasets, live pulse), live `/dashboard`, and `/terminal` rebuilt as a full CLI setup & usage guide; custom hand-drawn icon set (`components/icons.tsx`); ASCII logo shipped as PNG (`/static/ascii-logo.png` + `/ascii-logo.png` alias); fluid typography + entrance animations + glass hover glow.
- `api.py` — terminal endpoints (`/v1/terminal/exec|python|fs/*`) return real `HTTPException` statuses (400/404/408/500) instead of opaque `_api_error` strings.

---

## Notes
- `vulture` also flags ~110 "unused" items across the codebase; these are **false
  positives** (FastAPI route handlers registered via decorators, Pydantic model methods
  used at runtime, ctypes struct fields, dynamic attributes) and are intentionally not
  removed.
- `lora_manager.get_adapter()` and `ModelManager.get()` were dead code with zero callers
  in the repo; both were removed in v1.1.0.
- Testing: `python test_all.py` → **759 passed, 0 failed**; `python run_deep_audit.py` →
  **DEEP AUDIT PASSED** (pylint, mypy, pyflakes, bandit, vulture, pydocstyle, ESLint).
