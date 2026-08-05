# Known Issues — Sovereign-Agentic-AI

Status as of **v1.0.0**: the four security/correctness blockers from the second audit
pass are **fixed** (see `AUDIT_REPORT.md` → "Second Pass Corrections"). The items below
are lower-risk bugs, design limitations, or dead code that were deliberately **deferred
to v1.1.0** so v1.0.0 can ship. None of them cause data corruption or remote code
execution in the default (local, opt-in) configuration.

Severity: `BUG` (wrong behaviour), `DESIGN` (intentional limitation / refactor), `MINOR`,
`DEADCODE` (unused but kept for compatibility).

---

## Resolved in v1.0.0 (for reference)
- `graph_store.py` — tag-edge FK corruption → tags are now `nodes` of type `tag`.
- `healing_agent.py` — RCE via un-gated code execution → gated behind `--allow-unsafe-healing`.
- `web_ui.py` — stored XSS via `/generated` → `SafeStaticFiles` with `nosniff` + forced download.
- `vision.py` — moondream2 wrong API → `answer_question` pipeline.

## Resolved in v1.1.0 (deferred-pass, tests green: 703/0)
- `agents.py:279` — `render_skill()` now also catches `IndexError` from `str.format` (bare `{}`/`{0}` templates no longer 500).
- `image_gen.py:63` — `_cap()` now clamps the *config default* too, so a misconfigured `image_gen.width=2048` can't bypass the 256–512 / 8–40 guards.
- `metrics.py:81` — `success_rate` is clamped to `[0, 1]` (no longer goes negative when errors > requests).
- `run.py:452` — port auto-fallback now also sets `CONFIG.port` so `GET /v1/config` reports the real port.
- `cli.py:185` — `_COMMANDS` now includes `/mcp`, `/temp`, `/shell`, `/max-tokens` (tab-completion + suggestions).
- `cli.py:1899` — `/lora train` arg parsing fixed (requires `<base> <dataset> <output> [epochs]`; dataset no longer used as adapter name).
- `orchestrator.py:484` — `auto_stream_max_tokens` is now applied as a real hard cap on forwarded `max_tokens`.
- `orchestrator.py` — `stream()` now emits a terminal `{"type":"done", model, tokens, elapsed}` event (and the OpenAI early-return path does too), matching the batch protocol.

---

## Orchestrator (`orchestrator.py`)
- **BUG** `:70` — `_resolve_executor()` always returns `router.primary("general", override)`; `self.executor` is only a last resort, so CLI `/model <name>` has no effect and the executor is ranked for the literal task `"general"` instead of the classified task.
- **BUG** `:178-206,227` — pgvector/workspace/graph memories are passed only to `_select_best_plan()`; `_build_exec_prompt()` never receives them, so with `use_planning=False` the whole RAG result is discarded.
- **BUG** `:513-528` — the streaming `auto_stream()` branch (and `stream()` `:290-434`) never emits a terminal `{"type":"done"}` event while the batch branch does; SSE clients never get `done`/`model`/`tokens`/`elapsed` for streamed requests.
- **BUG** `:444-448` — `auto_stream_max_tokens` is only used as a comparison threshold, never applied as a cap on the `max_tokens` forwarded to `stream()`/`run()`.

## Hardware monitor (`hardware.py`)
- **BUG** `:387-394` — CPU throttle is one-way: a single `>75%` sample sets `CONFIG.threads = (cores+1)//3` (==1 on the 4-core i3) and nothing ever restores it → inference permanently drops to 1 thread after the first spike.
- **BUG** `:358` — `HardwareMonitor._enforce()` calls `detect_hardware(force=True)` every 30s, re-running PowerShell/nvidia-smi probes whose own CPU cost inflates the number it throttles on (the live sampler cache exists to avoid this).
- **BUG** `:417-424` — `get_hw_monitor()` caches the first `ModelManager` forever; managers created later (CLI `:1941`, `arc.py`, tests) are never watched, and the singleton keeps a strong reference to a possibly-dead manager.

## CLI (`cli.py`)
- **BUG** `:1941` — `full` mode builds a second `ModelManager` while `api.py` already created one in the same process → GGUFs loaded twice (double VRAM on a 6 GB card), two independent lock/LRU/metric sets, only the API's manager watched.
- **BUG** `:497-511` — `_render_messages()` uses `msg_area_h` as a *message* count, but each rendered cell is 4+ rows tall; with a few messages the render overruns the input area.
- **BUG** `:475` — scroll-region reset writes `ESC[{h};{h}r` (one-line region) instead of `ESC[1;{h}r` → broken scroll region after CLI output.
- **MINOR** `:177-185` — `_COMMANDS` omits `/mcp`, `/temp`, `/shell`, `/max-tokens` though they're handled; tab-completion and "did you mean" never offer them.
- **MINOR** `:1899-1909` — `/lora train` validates `len(parts) < 4` but reads `out_name` from `parts[4]` / `epochs` from `parts[5]`; with exactly 4 args the dataset path is used as the adapter name.

## Router (`router.py`)
- **DESIGN** `:92-101` — `Harness.choose()` (the epsilon-greedy exploration documented as the core of the selection room) has zero production callers; `rank_for_task`/`select_executors` only use `ranked()`. `CONFIG.harness_epsilon` is inert outside tests.
- **MINOR** `:238-248` — `select_executors()` prepends `model_override` then re-sorts with the loaded-first pass, so an unloaded override can be demoted behind loaded models.
- **MINOR** `:15-19` — the `"code"` bucket (checked first) contains generic tokens (`file`, `read`, `write`, `error`, `api`, `class`) → nearly every prompt classifies as `"code"`, collapsing harness stats/routing into one bucket.

## Metrics / Agents / Image-gen / Run (`metrics.py`, `agents.py`, `image_gen.py`, `run.py`)
- **MINOR** `metrics.py:55-61,81` — error paths call `record_completion(ok=False)` with `latency=0.0` and no matching `record_request`; `latency_n` is incremented for failures (avg latency skewed toward 0) and `success_rate = 1 - errors/requests` can go negative / divide by zero.
- **BUG** `agents.py:277-280` — `render_skill()` catches only `KeyError`/`ValueError`; a template containing a bare `{}` or `{0}` raises `IndexError` from `str.format` → 500 on `/v1/skills/{name}/run`.
- **BUG** `image_gen.py:63-71,92-94` — `_cap()` returns the *config* default unclamped when the request value is 0/invalid, so `POST /v1/config image_gen.width=2048` bypasses the documented 256–512 / 8–40 guards.
- **BUG** `run.py:442` vs `api.py:520` — port auto-fallback updates only `args.port`; `CONFIG.port` is never synced, so `GET /v1/config` advertises the wrong port.

## Graph store (`graph_store.py`)
- **BUG** `:704,670-676,795` — `list_nodes()`, `hybrid_search()`, `shortest_path()` call `node_degrees()`/`linked_nodes()`/`backlinks()`/`get_node()` per row while already holding a pooled connection → nested acquisitions on a 4-connection pool (silent `0`/`None` returns when exhausted).
- **MINOR** `:770-786` — `shortest_path()` recursive term doesn't filter `edge_type` while the anchor term does, and has no `LIMIT` inside the CTE (fully expands to depth 15 before `ORDER BY depth LIMIT 1`).
- **MINOR** `:29-41` — `_SCHEMA_DONE`/`_nodes_index_lock` are created at module scope using `threading` imported inside a guarded `try`; if that import fails the module raises `NameError`, so the `_SCHEMA_ENSURE_LOCK is None -> return` guard can never execute.
- **DEADCODE** `:511` — `remove_edges()` has no production caller (only `test_all.py`); keep (tests rely on it).

## Misc dead code
- **DEADCODE** `lora_manager.py:83` — `get_adapter()` has zero references anywhere in the repo. (Public-ish helper; left intentionally.)
- **DEADCODE** `models.py:260` — `ModelManager.get()` has zero callers; `arc.py:89` reads a non-existent `model_manager.default_model` attribute (permanently-false branch).

---

## Notes
- `vulture` also flags ~110 "unused" items across the codebase; these are **false
  positives** (FastAPI route handlers registered via decorators, Pydantic model methods
  used at runtime, ctypes struct fields, dynamic attributes) and are intentionally not
  removed.
- Testing: `python test_all.py` → **703 passed, 0 failed**.
