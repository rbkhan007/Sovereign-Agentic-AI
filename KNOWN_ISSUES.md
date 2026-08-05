# Known Issues — Sovereign-Agentic-AI

Status as of **v1.1.0**: the deferred v1.1.0 bug list is fully resolved (tests green:
**759/0**, deep audit PASS). The only items left are dead code kept for compatibility.

Severity: `BUG` (wrong behaviour), `DESIGN` (intentional limitation / refactor), `MINOR`,
`DEADCODE` (unused but kept for compatibility).

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

---

## Misc dead code
- **DEADCODE** `lora_manager.py:83` — `get_adapter()` has zero references anywhere in the repo. (Public-ish helper; left intentionally.)
- **DEADCODE** `models.py:260` — `ModelManager.get()` has zero callers. (Public-ish helper; left intentionally.)

---

## Notes
- `vulture` also flags ~110 "unused" items across the codebase; these are **false
  positives** (FastAPI route handlers registered via decorators, Pydantic model methods
  used at runtime, ctypes struct fields, dynamic attributes) and are intentionally not
  removed.
- Testing: `python test_all.py` → **759 passed, 0 failed**; `python run_deep_audit.py` →
  **DEEP AUDIT PASSED** (pylint, mypy, pyflakes, bandit, vulture, pydocstyle, ESLint).
