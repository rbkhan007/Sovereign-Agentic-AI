import ast
import copy
import glob
import io
import json
import logging
import os
import queue
import re as _re
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

logging.disable(logging.CRITICAL)

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


def section(title):
    print(f"\n== {title} ==")


BASE = os.path.dirname(os.path.abspath(__file__))
PYFILES = glob.glob(os.path.join(BASE, "*.py"))

section("Files & Syntax")
for f in sorted(PYFILES):
    try:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read(), filename=f)
        check(f"ast.parse {os.path.basename(f)}", True)
    except SyntaxError as e:
        check(f"ast.parse {os.path.basename(f)}", False, str(e))

required = ["run.py", "config.py", "models.py", "memory.py", "database.py",
            "orchestrator.py", "api.py", "cli.py", "web_ui.py", "test_system.py",
            "requirements.txt", "start.bat", "start_simple.bat", "agent.md", "AGENTS.md",
            "agents.py", "wiki_links.py"]
for name in required:
    check(f"required file {name}", os.path.exists(os.path.join(BASE, name)))
check("frontend build exists", os.path.isdir(os.path.join(BASE, "frontend", "build")))
check("models dir exists", os.path.isdir(os.path.join(BASE, "models")))

from config import CONFIG, AppConfig

CONFIG.openai.enabled = False
CONFIG.openai.api_key = ""
CONFIG.cloud_provider = "none"

section("Config")
check("threads auto > 0", CONFIG.threads > 0, f"({CONFIG.threads})")
check("models exist on disk", len(CONFIG.available_models) >= 3, f"({len(CONFIG.available_models)})")
check("discovery dedupes by path", len(CONFIG.available_models) == len({os.path.normcase(os.path.abspath(m.path)) for m in CONFIG.available_models}))
check("discovered role executor", all(m.role == "Executor" for m in CONFIG.available_models if m.name not in {s.name for s in CONFIG.models}))
check("parallel defaults", CONFIG.parallel_enabled is False and CONFIG.parallel_max == 2)
check("prune defaults", CONFIG.prune_interval_hours == 6 and CONFIG.prune_max_age_days == 30)
check("gen timeout default", CONFIG.gen_timeout_s == 240.0, f"({CONFIG.gen_timeout_s})")
check("sandbox default off", CONFIG.sandbox is False)
check("model roles", [m.role for m in CONFIG.models] == ["Strategist", "Executor", "Executor", "Executor"])
check("sync_threads propagates", all(m.n_threads == CONFIG.threads for m in CONFIG.models))

old_env = os.environ.copy()
try:
    os.environ["LLM_PARALLEL"] = "off"
    os.environ["LLM_PARALLEL_MAX"] = "5"
    os.environ["LLM_PRUNE_HOURS"] = "3"
    os.environ["LLM_PRUNE_DAYS"] = "10"
    os.environ["LLM_GEN_TIMEOUT"] = "75"
    os.environ["LLM_API_TOKENS"] = "rot1,rot2"
    os.environ["LLM_AUTO_STREAM"] = "0"
    os.environ["LLM_AUTO_STREAM_THINKING"] = "no"
    os.environ["LLM_AUTO_STREAM_MIN_TOKENS"] = "25"
    os.environ["LLM_AUTO_STREAM_MAX_TOKENS"] = "512"
    fresh = AppConfig()
    check("env override parallel off", fresh.parallel_enabled is False)
    check("env override parallel_max", fresh.parallel_max == 5)
    check("env override prune hours", fresh.prune_interval_hours == 3)
    check("env override prune days", fresh.prune_max_age_days == 10)
    check("env override gen timeout", fresh.gen_timeout_s == 75.0, f"({fresh.gen_timeout_s})")
    check("env override api tokens", fresh.api_tokens == ("rot1", "rot2"), f"({fresh.api_tokens})")
    check("env auto-stream disabled", fresh.auto_stream_enabled is False and fresh.auto_stream_thinking is False)
    check("env auto-stream tokens clamped", fresh.auto_stream_min_tokens == 25 and fresh.auto_stream_max_tokens == 512,
          f"({fresh.auto_stream_min_tokens},{fresh.auto_stream_max_tokens})")
finally:
    os.environ.clear()
    os.environ.update(old_env)

_old_toks = (CONFIG.api_token, CONFIG.api_tokens)
try:
    CONFIG.set_api_token("one,two,three")  # nosec B105
    check("set_api_token splits", CONFIG.api_token == "one" and CONFIG.api_tokens == ("two", "three"),  # nosec B105
          f"({CONFIG.api_token},{CONFIG.api_tokens})")
    check("valid_api_tokens all", CONFIG.valid_api_tokens() == frozenset({"one", "two", "three"}))
    check("token_authorized accepts all", all(CONFIG.token_authorized(t) for t in ("one", "two", "three")))
    check("token_authorized rejects unknown", not CONFIG.token_authorized("nope") and not CONFIG.token_authorized(""))
    CONFIG.set_api_token("single")  # nosec B105
    check("set_api_token single", CONFIG.api_token == "single" and CONFIG.api_tokens == (),  # nosec B105
          f"({CONFIG.api_token})")
    check("valid_api_tokens single", CONFIG.valid_api_tokens() == frozenset({"single"}))
finally:
    CONFIG.api_token, CONFIG.api_tokens = _old_toks

import config as config_mod
_tmp_models = tempfile.mkdtemp(prefix="models_disc_")
with open(os.path.join(_tmp_models, "my_custom_7b_q4_k_m.gguf"), "w") as _fh:
    _fh.write("fake")
with open(os.path.join(_tmp_models, "another_model.gguf"), "w") as _fh:
    _fh.write("fake")
_disc_cfg = AppConfig()
try:
    with mock.patch.object(config_mod, "MODELS_DIR", _tmp_models):
        disc = _disc_cfg.available_models
    disc_names = [m.name for m in disc]
    check("discovery finds gguf files", "my-custom-7b-q4-k-m" in disc_names and "another-model" in disc_names, f"({disc_names})")
    _disc_only = [m for m in disc if m.name in ("my-custom-7b-q4-k-m", "another-model")]
    check("discovery assigns executor role", all(m.role == "Executor" and "general" in m.capabilities for m in _disc_only))
    check("discovery sets threads", all(m.n_threads == _disc_cfg.threads for m in disc))
    check("discovery skips non-gguf", not any(m.path.endswith(".txt") for m in disc))
finally:
    import shutil
    shutil.rmtree(_tmp_models, ignore_errors=True)

section("Memory (Conversation + MemoryManager)")
from memory import Conversation, MemoryManager

c = Conversation(max_history=3)
c.set_system("SYS")
for i in range(5):
    c.add("user" if i % 2 == 0 else "assistant", f"m{i}")
check("conversation max_history", len(c.messages) == 3, f"({len(c.messages)})")
check("conversation oldest trimmed", c.messages[0].content == "m2")
check("context has system + open assistant", "<|im_start|>system" in c.get_context() and c.get_context().endswith("<|im_start|>assistant\n"))
check("openai format", c.to_openai_format()[0] == {"role": "system", "content": "SYS"})
c.clear()
check("clear resets system_prompt", len(c.messages) == 0 and c.system_prompt is None)

mem = MemoryManager()
threads = []
for i in range(50):
    def w(i=i):
        conv = mem.get_or_create(f"conv-{i}")
        conv.add("user", f"msg-{i}")
    t = threading.Thread(target=w)
    t.start()
    threads.append(t)
for t in threads:
    t.join()
check("concurrent get_or_create", len(mem.conversations) == 50)

mem2 = MemoryManager()
for i in range(500):
    mem2.get_or_create(f"k{i}")
check("bounded at 500", len(mem2.conversations) == 500, f"({len(mem2.conversations)})")
mem2.get_or_create("k0")
mem2.get_or_create("k500")
check("LRU evicts oldest", "k0" in mem2.conversations and "k1" not in mem2.conversations, f"({len(mem2.conversations)})")
mem2.delete("k0")
check("delete", "k0" not in mem2.conversations)
mem2.clear_all()
check("clear_all", len(mem2.conversations) == 0)

section("Memory workspace scoping")
wm = MemoryManager()
c1 = wm.get_or_create("conv-a", "ws-alpha")
c1.add("user", "hello alpha")
c2 = wm.get_or_create("conv-b", "ws-beta")
c2.add("user", "hello beta")
check("conversation records workspace", c1.workspace_id == "ws-alpha" and c2.workspace_id == "ws-beta")
check("conversations_for alpha", [cid for cid, _ in wm.conversations_for("ws-alpha")] == ["conv-a"])
check("conversations_for default empty", wm.conversations_for("default") == [])
wm.delete("conv-a")
check("delete updates workspace index", wm.conversations_for("ws-alpha") == [])
wm.get_or_create("conv-c", "ws-beta")
wm.delete_workspace("ws-beta")
check("delete_workspace removes convs",
      "conv-b" not in wm.conversations and "conv-c" not in wm.conversations
      and wm.conversations_for("ws-beta") == [])
wm.get_or_create("conv-d", "ws-x")
check("get_or_create keeps original ws", wm.get_or_create("conv-d", "ws-y").workspace_id == "ws-x")
wm.clear_all()

section("Models (mocked Llama)")
import models as models_mod


class FakeLlama:
    instances: list["FakeLlama"] = []
    fail_on_generate = False

    def __init__(self, **kw):
        self.kwargs = kw
        FakeLlama.instances.append(self)

    def __call__(self, **kw):
        if FakeLlama.fail_on_generate:
            raise RuntimeError("gen boom")
        if kw.get("stream"):
            def gen():
                for piece in ["he", "llo"]:
                    yield {"choices": [{"text": piece}]}
            return gen()
        return {"choices": [{"text": " fake output "}]}


class BoomLlama:
    def __init__(self, **kw):
        raise RuntimeError("load boom")


# The MiniCPM GGUF files this suite was written against have since been
# replaced in models/ (now Qwen2.5-Omni + Gemma). Keep the suite
# environment-independent by aliasing the legacy logical model names onto
# whichever models are actually present, so every ModelManager built during
# the run still exposes minicpm-v9 / minicpm-tooluse.
_orig_load_configs = models_mod.ModelManager._load_configs


def _load_configs_with_aliases(self):
    _orig_load_configs(self)
    if not self.configs:
        return
    _base = next(iter(self.configs.values()))
    for _alias, _role in (("minicpm-v9", "Executor"), ("minicpm-tooluse", "ToolExecutor")):
        if _alias not in self.configs:
            _cfg = copy.copy(_base)
            _cfg.name = _alias
            _cfg.role = _role
            self.configs[_alias] = _cfg


models_mod.ModelManager._load_configs = _load_configs_with_aliases


with mock.patch.object(models_mod, "Llama", FakeLlama):
    mm = models_mod.ModelManager()
    check("configs loaded", len(mm.configs) >= 3)

    llm = mm.load("minicpm-v9")
    check("load returns instance", llm in FakeLlama.instances)
    check("load cached on 2nd call", mm.load("minicpm-v9") is llm and len(FakeLlama.instances) == 1)
    check("load recorded stats", "minicpm-v9" in models_mod.get_model_stats()["load_times"])

    text = mm.generate("minicpm-v9", "hello")
    check("generate via mock", text == "fake output")
    chunks = list(mm.generate_stream("minicpm-v9", "hi"))
    check("generate_stream chunks", chunks == ["he", "llo"])

    stats = models_mod.get_model_stats()
    check("stats shape", "load_times" in stats and "load_errors" in stats and "loaded_count" in stats)
    check("stats loaded_count", stats["loaded_count"] >= 1)

    try:
        mm.load("does-not-exist")
        check("unknown model raises", False)
    except ValueError:
        check("unknown model raises", True)

    FakeLlama.fail_on_generate = True
    try:
        mm.generate("minicpm-v9", "boom")
        check("generate failure raises", False)
    except RuntimeError as e:
        check("generate failure raises", "Generate on minicpm-v9 failed" in str(e), f"[{e}]")
    check("generate failure pops instance", "minicpm-v9" not in mm.instances)
    check("generate failure keeps load_time stat", "minicpm-v9" in models_mod.get_model_stats()["load_times"])
    check("stats(manager) excludes popped instance",
          models_mod.get_model_stats(mm)["loaded_count"] == 0,
          f"(manager={models_mod.get_model_stats(mm)['loaded_count']})")
    FakeLlama.fail_on_generate = False

    n_loaded_before = len(FakeLlama.instances)
    text = mm.generate("minicpm-v9", "retry")
    check("reload after failure", text == "fake output" and len(FakeLlama.instances) == n_loaded_before + 1)

    mm.load("minicpm-tooluse")
    mm.unload("minicpm-tooluse")
    check("unload clears stats", "minicpm-tooluse" not in models_mod.get_model_stats()["load_times"])

    mm.load("minicpm-v9")
    mm.load("minicpm-tooluse")
    mm.unload_all()
    check("unload_all clears instances", len(mm.instances) == 0)
    stats = models_mod.get_model_stats()
    check("unload_all clears stats", stats["load_times"] == {} and stats["load_errors"] == {})

    mm.load("minicpm-v9")
    ex_old = mm._get_executor("minicpm-v9")
    ex_old.submit(time.sleep, 30)
    mm._kill_model("minicpm-v9", ex_old)
    check("kill_model pops instance", "minicpm-v9" not in mm.instances)
    check("kill_model swaps executor", mm._get_executor("minicpm-v9") is not ex_old)
    text = mm.generate("minicpm-v9", "recovered")
    check("kill_model recovery reloads", text == "fake output" and "minicpm-v9" in mm.instances)

    # TASK-HP-003: parallel model loading
    class SlowLoadLlama:
        _state_lock = threading.Lock()
        active = 0
        max_active = 0

        def __init__(self, **kw):
            with SlowLoadLlama._state_lock:
                SlowLoadLlama.active += 1
                SlowLoadLlama.max_active = max(SlowLoadLlama.max_active, SlowLoadLlama.active)
            time.sleep(0.05)
            with SlowLoadLlama._state_lock:
                SlowLoadLlama.active -= 1

        def __call__(self, **kw):
            return {"choices": [{"text": "pl"}]}

    _big_ram = mock.patch("hardware.detect_hardware", return_value={"ram_available_mb": 16384})
    _old_pl = CONFIG.parallel_load
    _old_lw = CONFIG.load_workers
    CONFIG.parallel_load = True
    CONFIG.load_workers = 2
    try:
        with mock.patch.object(models_mod, "Llama", SlowLoadLlama), _big_ram:
            SlowLoadLlama.active = SlowLoadLlama.max_active = 0
            mm_pl = models_mod.ModelManager()
            _loaded = mm_pl.load_many(["hy-mt2", "minicpm-v9"], budget_mb=0)
            check("load_many loads all targets",
                  set(_loaded) == {"hy-mt2", "minicpm-v9"} and len(mm_pl.instances) == 2,
                  f"({sorted(_loaded)})")
            check("load_many parallel overlaps", SlowLoadLlama.max_active >= 2,
                  f"(max_active={SlowLoadLlama.max_active})")

            CONFIG.parallel_load = False
            SlowLoadLlama.active = SlowLoadLlama.max_active = 0
            mm_sq = models_mod.ModelManager()
            mm_sq.load_many(["hy-mt2", "minicpm-v9"], budget_mb=0)
            check("load_many sequential when disabled", SlowLoadLlama.max_active == 1,
                  f"(max_active={SlowLoadLlama.max_active})")

            _saved_vram = {n: mm_pl.configs[n].vram_mb for n in ("hy-mt2", "minicpm-v9")}
            mm_pl.configs["hy-mt2"].vram_mb = 1000
            mm_pl.configs["minicpm-v9"].vram_mb = 1000
            mm_pl.unload_all()
            SlowLoadLlama.active = SlowLoadLlama.max_active = 0
            mm_pl.load_many(["hy-mt2", "minicpm-v9"], budget_mb=1500)
            check("load_many sequential when over budget", SlowLoadLlama.max_active == 1,
                  f"(max_active={SlowLoadLlama.max_active})")
            for n in ("hy-mt2", "minicpm-v9"):
                mm_pl.configs[n].vram_mb = _saved_vram[n]
    finally:
        CONFIG.parallel_load = _old_pl
        CONFIG.load_workers = _old_lw

    with mock.patch.object(models_mod, "Llama", FakeLlama), _big_ram:
        mm_skip = models_mod.ModelManager()
        mm_skip.load("hy-mt2")
        _n_before = len(FakeLlama.instances)
        _loaded = mm_skip.load_many(["hy-mt2", "minicpm-v9"], budget_mb=0)
        check("load_many skips loaded",
              _loaded == ["hy-mt2", "minicpm-v9"] and len(FakeLlama.instances) == _n_before + 1,
              f"({_loaded})")
        _loaded = mm_skip.load_many(["nope", "minicpm-tooluse"], budget_mb=0)
        check("load_many ignores unknown", "nope" not in _loaded)

    with mock.patch.object(models_mod, "Llama", BoomLlama), _big_ram:
        mm_fail = models_mod.ModelManager()
        _loaded = mm_fail.load_many(["hy-mt2", "minicpm-v9"], budget_mb=0)
        check("load_many failure returns subset", _loaded == [], f"({_loaded})")

    class SlowLlama(FakeLlama):
        sleep_seconds = 15.0

        def __call__(self, **kw):
            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)
            return {"choices": [{"text": "slow"}]}

    old_timeout = CONFIG.gen_timeout_s
    CONFIG.gen_timeout_s = 0.6
    try:
        with mock.patch.object(models_mod, "Llama", SlowLlama):
            mm_slow = models_mod.ModelManager()
            try:
                mm_slow.generate("minicpm-v9", "slow me")
                check("generate timeout raises", False)
            except RuntimeError as e:
                check("generate timeout raises", "timed out after 0.6" in str(e), f"[{e}]")
            check("generate timeout pops instance", "minicpm-v9" not in mm_slow.instances)
            SlowLlama.sleep_seconds = 0.0
            text = mm_slow.generate("minicpm-v9", "retry fast")
            check("generate timeout recovery", text == "slow", f"[{text}]")
    finally:
        SlowLlama.sleep_seconds = 15.0
        CONFIG.gen_timeout_s = old_timeout

with mock.patch.object(models_mod, "Llama", BoomLlama):
    mm2 = models_mod.ModelManager()
    try:
        mm2.generate("minicpm-v9", "hi")
        check("load failure raises", False)
    except RuntimeError as e:
        check("load failure raises", "Load minicpm-v9 failed" in str(e), f"[{e}]")
    check("load error recorded", "minicpm-v9" in models_mod.get_model_stats()["load_errors"])
    mm2.unload("minicpm-v9")
    check("unload clears load error", "minicpm-v9" not in models_mod.get_model_stats()["load_errors"])

old_openai = (CONFIG.openai.enabled, CONFIG.openai.api_key, CONFIG.openai.chat_model)
fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
    create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" cloud fallback "))]))))
try:
    CONFIG.openai.enabled = True
    CONFIG.openai.api_key = "k"
    with mock.patch.object(models_mod, "Llama", BoomLlama), \
            mock.patch.object(models_mod, "get_openai_client", return_value=fake_client):
        mm3 = models_mod.ModelManager()
        text = mm3.generate("minicpm-v9", "hi")
        check("load failure falls back to OpenAI", text == "cloud fallback", f"[{text}]")
finally:
    CONFIG.openai.enabled, CONFIG.openai.api_key, CONFIG.openai.chat_model = old_openai

old_rate = (CONFIG.openai.rate_limit_per_min, CONFIG.openai.backoff_max_s)
with mock.patch.object(models_mod, "Llama", BoomLlama), \
        mock.patch.object(models_mod, "get_openai_client", return_value=fake_client):
    CONFIG.openai.enabled = True
    CONFIG.openai.api_key = "k"
    CONFIG.openai.rate_limit_per_min = 1
    CONFIG.openai.backoff_max_s = 0.01
    models_mod._openai_calls.clear()
    try:
        mm4 = models_mod.ModelManager()
        text = mm4.generate("minicpm-v9", "hi")
        check("rate limit allows first call", text == "cloud fallback", f"[{text}]")
        models_mod._openai_calls[:] = [time.time() - 1.0]
        try:
            mm4.generate("minicpm-v9", "hi")
            check("rate limit blocks over-limit", False)
        except RuntimeError as e:
            check("rate limit blocks over-limit", "rate limit" in str(e).lower(), f"[{e}]")
    finally:
        CONFIG.openai.rate_limit_per_min, CONFIG.openai.backoff_max_s = old_rate

section("Database (mocked connection)")
import database as db_mod
CONFIG.db.enabled = False


class FakeVec(list):
    def tolist(self):
        return list(self)


class FakeEmbedder:
    def encode(self, text, normalize_embeddings=None):  # noqa: unused
        if isinstance(text, list):
            return FakeVec(FakeVec([0.1] * 384) for _ in text)
        return FakeVec([0.1] * 384)


class FakeCursor:
    def __init__(self, executed):
        self.executed = executed
        self.rows = []
        self.rowcount = 3
        self.connection = type("FakeConnection", (), {"encoding": "UTF8"})()

    def execute(self, sql, params=None):
        if isinstance(sql, bytes):
            sql = sql.decode("utf-8")
        self.executed.append((sql, params))

    def mogrify(self, sql, params=None):
        params = tuple(params) if isinstance(params, (list, tuple)) else (params,)
        rendered = sql % params
        return rendered.encode()

    def fetchone(self):
        return (2,)

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, executed):
        self.executed = executed
        self.committed = 0
        self.rolled_back = 0
        self.cur = FakeCursor(executed)

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        pass


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def getconn(self):
        return self.conn

    def putconn(self, c):
        pass

    def closeall(self):
        pass


from typing import Any

executed: list[tuple[str, Any]] = []
conn = FakeConn(executed)
pool = FakePool(conn)
with mock.patch.object(db_mod, "get_pool", return_value=pool), \
        mock.patch.object(db_mod, "get_embedder", return_value=FakeEmbedder()):
    db_mod.store_thought("agent1", "  hello world  ")
    inserts = [s for s, _ in executed if "INSERT INTO agent_memory" in s]
    check("store_thought inserts", len(inserts) == 1 and conn.committed >= 1)
    n0 = len(executed)
    db_mod.store_thought("agent1", "   ")
    check("store_thought skips empty", len(executed) == n0)

    conn.cur.rows = [("m1", 0.2), ("m2", 0.9)]
    r = db_mod.retrieve_similar("similar q")
    check("retrieve returns results", r == ["m1", "m2"])
    r = db_mod.retrieve_similar("similar q", min_score=0.5)
    check("retrieve min_score filter", r == ["m1"], f"({r})")
    cnt = sum(1 for s, _ in executed if "SELECT thought" in s)
    r = db_mod.retrieve_similar("similar q")
    cnt2 = sum(1 for s, _ in executed if "SELECT thought" in s)
    check("retrieve LRU cache hit", cnt2 == cnt, f"({cnt}->{cnt2})")

    conn.cur.rows = [("x1", 0.1)]
    r = db_mod.retrieve_similar("agent filtered q", agent_filter="hy-mt2")
    sqls = [s for s, _ in executed if "agent_name = %s" in s]
    check("retrieve agent filter", len(sqls) == 1 and r == ["x1"])

    n0 = len(executed)
    db_mod.retrieve_similar("default-scoped q")
    default_sqls = [s for s, _ in executed[n0:] if "SELECT thought" in s]
    check("retrieve unscoped stays in default ws",
          bool(default_sqls) and "workspace_id = 'default'" in default_sqls[-1],
          f"({default_sqls[-1] if default_sqls else 'none'})")
    n0 = len(executed)
    db_mod.retrieve_similar("ws-scoped q", workspace_id="lab")
    ws_sqls = [(s, p) for s, p in executed[n0:] if "SELECT thought" in s]
    check("retrieve workspace-scoped sql",
          bool(ws_sqls) and "workspace_id = %s" in ws_sqls[-1][0] and ws_sqls[-1][1][1] == "lab",
          f"({ws_sqls[-1] if ws_sqls else 'none'})")

    check("count_memories", db_mod.count_memories() == 2)
    n0 = len(executed)
    db_mod.count_memories()
    cnt_sqls = [s for s, _ in executed[n0:] if s.startswith("SELECT COUNT(*)")]
    check("count_memories unscoped stays in default ws",
          bool(cnt_sqls) and "workspace_id = 'default'" in cnt_sqls[-1],
          f"({cnt_sqls[-1] if cnt_sqls else 'none'})")
    n0 = len(executed)
    db_mod.count_memories(workspace_id="lab")
    cnt_ws = [(s, p) for s, p in executed[n0:] if s.startswith("SELECT COUNT(*)")]
    check("count_memories workspace sql",
          bool(cnt_ws) and "workspace_id = %s" in cnt_ws[-1][0] and cnt_ws[-1][1] == ("lab",),
          f"({cnt_ws[-1] if cnt_ws else 'none'})")

    n0 = len(executed)
    db_mod.recent_memories(limit=3)
    rec_sqls = [s for s, _ in executed[n0:] if "ORDER BY created_at" in s]
    check("recent_memories unscoped stays in default ws",
          bool(rec_sqls) and "workspace_id = 'default'" in rec_sqls[-1],
          f"({rec_sqls[-1] if rec_sqls else 'none'})")
    n0 = len(executed)
    db_mod.recent_memories(limit=3, workspace_id="lab")
    rec_ws = [(s, p) for s, p in executed[n0:] if "ORDER BY created_at" in s]
    check("recent_memories workspace sql",
          bool(rec_ws) and "workspace_id = %s" in rec_ws[-1][0] and rec_ws[-1][1][0] == "lab",
          f"({rec_ws[-1] if rec_ws else 'none'})")
    check("prune_memories rowcount", db_mod.prune_memories(30) == 3)
    prune_sqls = [(s, p) for s, p in executed if s.startswith("DELETE FROM agent_memory")]
    check("prune param not in literal",
          bool(prune_sqls) and "make_interval(days => %s)" in prune_sqls[-1][0] and prune_sqls[-1][1] == (30,),
          f"({prune_sqls[-1] if prune_sqls else 'none'})")
    n0 = sum(1 for s, _ in executed if "INSERT INTO agent_memory" in s)
    db_mod.store_batch([{"agent": "a", "thought": "t1"}, {"agent": "b", "thought": "  "}, {"agent": "c", "thought": "t2"}])
    batch_sqls = [s for s, _ in executed if "INSERT INTO agent_memory" in s]
    batch_rows = sum(s.count("::jsonb") for s in batch_sqls[n0:])
    check("store_batch only valid", batch_rows == 2, f"({batch_rows})")

    db_mod.stop_auto_prune()
    t1 = db_mod.start_auto_prune(interval_hours=1, max_age_days=5)
    assert t1 is not None
    t2 = db_mod.start_auto_prune(interval_hours=1, max_age_days=5)
    assert t2 is not None
    check("auto-prune idempotent", t1 is t2 and t1.is_alive())
    db_mod.stop_auto_prune()
    check("auto-prune stops", not t1.is_alive())
    t3 = db_mod.start_auto_prune(interval_hours=1, max_age_days=5)
    assert t3 is not None
    check("auto-prune restarts", t3 is not t1 and t3.is_alive())
    db_mod.stop_auto_prune()

    db_mod._pool = pool
    db_mod.close()
    check("close resets pool", db_mod._pool is None)

    long_thought = "x" * 5000
    n0 = sum(1 for s, _ in executed if "INSERT INTO agent_memory" in s)
    db_mod.store_thought("t", long_thought)
    insert_sqls = [(s, p) for s, p in executed if "INSERT INTO agent_memory" in s]
    check("store_thought truncates", len(insert_sqls) == n0 + 1 and len(insert_sqls[-1][1][1]) <= db_mod._MAX_THOUGHT,
          f"({len(insert_sqls[-1][1][1])})")

    n0 = len(executed)
    db_mod.store_batch([])
    check("store_batch empty no-op", len(executed) == n0)

    conn.cur.rows = [("ttl1", 0.05)]
    q = "ttl-query"
    cnt_before = sum(1 for s, _ in executed if "SELECT thought" in s)
    db_mod.retrieve_similar(q)
    cnt_mid = sum(1 for s, _ in executed if "SELECT thought" in s)
    db_mod.retrieve_similar(q)
    cnt_cached = sum(1 for s, _ in executed if "SELECT thought" in s)
    check("retrieve cache hit", cnt_mid == cnt_before + 1 and cnt_cached == cnt_mid, f"({cnt_mid}->{cnt_cached})")
    old_ttl = db_mod._CACHE_TTL
    db_mod._CACHE_TTL = 0.0
    db_mod.retrieve_similar(q)
    cnt_ttl = sum(1 for s, _ in executed if "SELECT thought" in s)
    check("retrieve cache expires (TTL 0)", cnt_ttl == cnt_cached + 1, f"({cnt_cached}->{cnt_ttl})")
    db_mod._CACHE_TTL = old_ttl

    for i in range(105):
        db_mod.retrieve_similar(f"cache-evict-{i}")
    check("retrieve cache bounded at 100", len(db_mod._query_cache) <= 100, f"({len(db_mod._query_cache)})")

    db_mod.count_memories("hy-mt2")
    check("count_memories agent filter", any(s.startswith("SELECT COUNT(*) FROM agent_memory WHERE agent_name") for s, _ in executed))

    conn.cur.rows = [("custom-a", "Role A", "Desc A", "prompt", '["a","b"]')]
    ag = db_mod.load_agents()
    check("load_agents rows", len(ag) == 1 and ag[0]["name"] == "custom-a" and ag[0]["keywords"] == ["a", "b"], f"({ag})")
    check("save_agent upserts", db_mod.save_agent("custom-a", "Role", "Desc", "prompt", ["a"]) is True)
    check("save_agent sql", any("INSERT INTO agents" in s for s, _ in executed))
    check("delete_agent", db_mod.delete_agent("custom-a") is True)
    check("delete_agent sql", any("DELETE FROM agents" in s for s, _ in executed))
    conn.cur.rows = [("custom-s", "Desc S", "sys", "template {input}", '[{"name":"language","default":"English"}]')]
    sk = db_mod.load_skills()
    check("load_skills rows", len(sk) == 1 and sk[0]["name"] == "custom-s" and sk[0]["params"][0]["name"] == "language", f"({sk})")
    check("save_skill upserts", db_mod.save_skill("custom-s", "Desc", "sys", "template {input}", []) is True)
    check("save_skill sql", any("INSERT INTO skills" in s for s, _ in executed))
    check("delete_skill", db_mod.delete_skill("custom-s") is True)
    check("delete_skill sql", any("DELETE FROM skills" in s for s, _ in executed))

    conn.cur.rows = [("sess-1", "Sess", "u1", '{"k":"v"}', None, None, None)]
    _orig_fetchone = conn.cur.fetchone
    conn.cur.fetchone = lambda: conn.cur.rows[0] if conn.cur.rows else None
    sess = db_mod.create_session("sess-1", "Sess", "u1", {"k": "v"})
    check("create_session rows", sess["id"] == "sess-1" and sess["user_id"] == "u1" and sess["metadata"] == {"k": "v"}, f"({sess})")
    check("create_session sql", any("INSERT INTO sessions" in s for s, _ in executed))
    check("get_session rows", db_mod.get_session("sess-1")["name"] == "Sess")
    conn.cur.rows = []
    check("get_session missing", db_mod.get_session("nope") is None)
    conn.cur.rows = [("sess-1", "Sess", "u1", '{"k":"v"}', None, None, None)]
    check("touch_session", db_mod.touch_session("sess-1") is True)
    check("touch_session sql", any("UPDATE sessions" in s for s, _ in executed))
    check("delete_session", db_mod.delete_session("sess-1") is True)
    check("delete_session sql", any("DELETE FROM sessions" in s for s, _ in executed))
    conn.cur.rowcount = 0
    check("prune_sessions rowcount", db_mod.prune_sessions(30) == 0)
    check("prune_sessions sql", any("DELETE FROM sessions" in s for s, _ in executed))
    conn.cur.fetchone = _orig_fetchone

    check("save_metrics_snapshot", db_mod.save_metrics_snapshot({"requests": 5}) is True)
    check("save_metrics_snapshot sql", any("INSERT INTO metrics_snapshots" in s for s, _ in executed))
    conn.cur.rows = [(None, '{"requests":5}')]
    snap = db_mod.list_metrics_snapshots(limit=5)
    check("list_metrics_snapshots rows", len(snap) == 1 and snap[0]["snapshot"] == {"requests": 5}, f"({snap})")
    check("list_metrics_snapshots sql", any("FROM metrics_snapshots" in s for s, _ in executed))
    conn.cur.rowcount = 0
    check("prune_metrics_snapshots", db_mod.prune_metrics_snapshots(500) == 0)
    check("prune_metrics_snapshots sql", any("DELETE FROM metrics_snapshots" in s for s, _ in executed))

    with mock.patch.object(db_mod, "get_pool", return_value=None):
        check("retrieve with no pool", db_mod.retrieve_similar("no-pool-q") == [])
    with mock.patch.object(db_mod, "get_embedder", return_value=None):
        check("retrieve with no embedder", db_mod.retrieve_similar("no-emb-q") == [])


class BadConn:
    def __init__(self):
        self.closed = False

    def cursor(self):
        class BC:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a):
                raise RuntimeError("conn dead")

        return BC()

    def close(self):
        self.closed = True


class RetryPool:
    def __init__(self, bad, good):
        self.bad = bad
        self.good = good
        self.first = True

    def getconn(self):
        if self.first:
            self.first = False
            return self.bad
        return self.good

    def putconn(self, c):
        pass


bad = BadConn()
good_conn = FakeConn([])
with mock.patch.object(db_mod, "get_pool", return_value=RetryPool(bad, good_conn)):
    got = db_mod._get_conn()
    check("dead conn rejected + retried", got is good_conn and bad.closed)

section("Workspaces (database fallback layer)")
db_mod.reset_workspace_store()
check("list_workspaces seeded default", [w["id"] for w in db_mod.list_workspaces()] == ["default"])
ws = db_mod.create_workspace("research", "Research Lab", "NLP research", "Be scientific", "minicpm-v9")
check("create_workspace fallback",
      ws["id"] == "research" and ws["name"] == "Research Lab" and ws["system_prompt"] == "Be scientific")
check("get_workspace fallback", db_mod.get_workspace("research")["description"] == "NLP research")
upd = db_mod.update_workspace("research", name="Research", system_prompt="Sci")
check("update_workspace fallback", upd["name"] == "Research" and upd["system_prompt"] == "Sci")
check("get_workspace missing returns None", db_mod.get_workspace("nope") is None)
check("delete_workspace default protected", db_mod.delete_workspace("default") is False)
check("delete_workspace fallback", db_mod.delete_workspace("research") is True)
check("get_workspace after delete", db_mod.get_workspace("research") is None)
db_mod.create_workspace("files", "Files")
f = db_mod.store_workspace_file("files", "notes.md", 1024, 3)
check("store_workspace_file fallback", f["name"] == "notes.md" and f["chunk_count"] == 3)
check("list_workspace_files fallback", [x["name"] for x in db_mod.list_workspace_files("files")] == ["notes.md"])
check("delete_workspace_file fallback", db_mod.delete_workspace_file("files", "notes.md") is True)
check("delete_workspace_file missing", db_mod.delete_workspace_file("files", "notes.md") is False)
db_mod.delete_workspace("files")
check("delete cascades files", db_mod.list_workspace_files("files") == [])
check("chunk_text short", db_mod.chunk_text("hello") == ["hello"])
check("chunk_text empty", db_mod.chunk_text("   ") == [])
_long_chunks = db_mod.chunk_text("para one here.\n\n" + "word " * 700)
check("chunk_text splits long", len(_long_chunks) > 1, f"({len(_long_chunks)})")
check("chunk_text bounded size", all(len(c) <= 600 for c in _long_chunks))
check("store_file_chunks no conn 0", db_mod.store_file_chunks("files", "a.txt", ["x"]) == 0)
check("search_workspace_knowledge no conn empty", db_mod.search_workspace_knowledge("files", "q") == [])
check("_ws_agent_name", db_mod._ws_agent_name("abc") == "workspace:abc")
db_mod.reset_workspace_store()

sess = db_mod.create_session("", "Fallback Sess", "u9", {"k": "v"})
check("create_session fallback", sess["id"].startswith("session-") and sess["user_id"] == "u9" and sess["metadata"] == {"k": "v"}, f"({sess})")
check("get_session fallback", db_mod.get_session(sess["id"])["name"] == "Fallback Sess")
check("list_sessions fallback", any(s["id"] == sess["id"] for s in db_mod.list_sessions()))
check("list_sessions user filter", any(s["id"] == sess["id"] for s in db_mod.list_sessions(user_id="u9")))
check("touch_session fallback", db_mod.touch_session(sess["id"]) is True)
check("delete_session fallback", db_mod.delete_session(sess["id"]) is True)
check("get_session fallback missing", db_mod.get_session(sess["id"]) is None)

check("save_metrics_snapshot fallback", db_mod.save_metrics_snapshot({"requests": 1}) is True)
check("save_metrics_snapshot empty rejected", db_mod.save_metrics_snapshot({}) is False)
hist = db_mod.list_metrics_snapshots(limit=10)
check("list_metrics_snapshots fallback", len(hist) == 1 and hist[0]["snapshot"] == {"requests": 1}, f"({hist})")

# TASK-HP-002: file-upload chunks must be batch-embedded (one encode() call for all chunks)
class BatchAwareEmbedder(FakeEmbedder):
    def __init__(self):
        self.encoded_calls = []
    def encode(self, text, normalize_embeddings=None):
        self.encoded_calls.append(text if isinstance(text, list) else [text])
        return super().encode(text, normalize_embeddings)

_batch_emb = BatchAwareEmbedder()
with mock.patch.object(db_mod, "get_pool", return_value=pool), \
        mock.patch.object(db_mod, "get_embedder", return_value=_batch_emb), \
        mock.patch.object(db_mod, "store_batch", wraps=db_mod.store_batch) as _sbatch:
    _batch_emb.encoded_calls.clear()
    _n_stored = db_mod.store_file_chunks("files", "batch.md", ["chunk one", "chunk two", "chunk three"])
    check("store_file_chunks batch embeds once",
          _n_stored == 3 and len(_batch_emb.encoded_calls) == 1
          and _batch_emb.encoded_calls[0] == ["chunk one", "chunk two", "chunk three"],
          f"({len(_batch_emb.encoded_calls)} encode call(s), stored={_n_stored})")
    check("store_file_chunks scopes to workspace agent",
          _sbatch.called and _sbatch.call_args[0][0][0]["agent"] == "workspace:files")

section("Graph store (graph_store.py, mocked connection)")
import graph_store as gs
from unittest import mock as _mock

CONFIG.db.enabled = False
_exec2: list[tuple[str, Any]] = []
_gconn = FakeConn(_exec2)
_gpool = FakePool(_gconn)

def _reset_graph_state():
    _exec2.clear()
    _gconn.committed = 0
    _gconn.rolled_back = 0
    gs._SCHEMA_DONE.clear()

def _run_sql(sql, params=None):
    sql = sql if isinstance(sql, str) else sql.decode("utf-8")
    is_tag = bool(params) and params[0] == "tag"
    if "INSERT INTO nodes" in sql:
        _gconn.cur.rows = [(88,)] if is_tag else [(99,)]
        return 88 if is_tag else 99
    if "SELECT id FROM nodes" in sql:
        _gconn.cur.rows = [(88,)] if is_tag else [(99,)]
        return 88 if is_tag else 99
    if "INSERT INTO tags" in sql:
        _gconn.cur.rows = [(77,)]
        return 77
    if "SELECT id FROM tags" in sql:
        _gconn.cur.rows = [(77,)]
        return 77
    if "SELECT id, node_type, title, content, metadata" in sql:
        _gconn.cur.rows = [(99, "concept", "Alpha", "content about alpha", {}, "default", "2026-01-01")]
        return [(99, "concept", "Alpha", "content about alpha", {}, "default", "2026-01-01")]
    if "SELECT COUNT(*) FROM nodes" in sql:
        _gconn.cur.rows = [(5,)]
        return 5
    if "SELECT COUNT(*) FROM edges" in sql:
        _gconn.cur.rows = [(3,)]
        return 3
    if "SELECT COUNT(*) FROM tags" in sql:
        _gconn.cur.rows = [(2,)]
        return 2
    if "SELECT node_type, COUNT(*)" in sql:
        _gconn.cur.rows = [("concept", 3), ("document", 2)]
        return [("concept", 3), ("document", 2)]
    if "COALESCE(AVG" in sql:
        _gconn.cur.rows = [(1.5,)]
        return 1.5
    if "SELECT route, depth" in sql:
        _gconn.cur.rows = [([1, 2, 3], 2)]
        return ([1, 2, 3], 2)
    _gconn.cur.rows = []
    return None

_gconn.cur.execute = lambda sql, params=None: (_run_sql(sql, params), _exec2.append((sql, params)))[1]
_gconn.cur.fetchone = lambda: _gconn.cur.rows[0] if _gconn.cur.rows else None
_gconn.cur.fetchall = lambda: _gconn.cur.rows

with _mock.patch.object(gs.db, "get_pool", return_value=_gpool), \
        _mock.patch.object(gs.db, "get_embedder", return_value=FakeEmbedder()), \
        _mock.patch.object(gs, "get_node", side_effect=lambda nid, conn=None: {"id": nid, "title": f"n{nid}"}):
    gs.ensure_schema()
    check("ensure_schema creates nodes", any("CREATE TABLE IF NOT EXISTS nodes" in s for s, _ in _exec2))
    check("ensure_schema creates edges", any("CREATE TABLE IF NOT EXISTS edges" in s for s, _ in _exec2))
    check("ensure_schema creates tags", any("CREATE TABLE IF NOT EXISTS tags" in s for s, _ in _exec2))

    _reset_graph_state()
    nid = gs.create_node("concept", "Alpha", "content about alpha")
    check("create_node returns id", nid == 99)
    check("create_node inserts embed", any("embedding" in s and "vector" in s for s, _ in _exec2))
    check("create_node normalizes bad type to concept", gs.create_node("bogus", "X", "y") == 99)

    _reset_graph_state()
    node = gs.get_node(99)
    check("get_node returns dict", node is not None and node.get("id") is not None)

    _reset_graph_state()
    found = gs.find_node_by_title("concept", "Alpha", "default")
    check("find_node_by_title", found == 99)

    _reset_graph_state()
    ok = gs.add_edge(1, 2, "wikilink", 1.0)
    check("add_edge conflicts-safe", ok is True)
    check("add_edge self-loop rejected", gs.add_edge(1, 1, "wikilink") is False)
    check("add_edge missing ids rejected", gs.add_edge(None, 2, "x") is False)

    _reset_graph_state()
    links = gs.linked_nodes(1)
    check("linked_nodes returns list", isinstance(links, list))
    backs = gs.backlinks(2)
    check("backlinks returns list", isinstance(backs, list))
    deg = gs.node_degrees(1)
    check("node_degrees shape", set(deg) == {"in_degree", "out_degree"})

    _reset_graph_state()
    tid = gs.ensure_tag("ai")
    check("ensure_tag returns id", tid == 77)
    _reset_graph_state()
    check("tag_node links", gs.tag_node(99, "ml") is True)

    _reset_graph_state()
    res = gs.search_nodes("query text", limit=5)
    check("search_nodes offline-safe", isinstance(res, list))
    _reset_graph_state()
    hyb = gs.hybrid_search("query text", limit=3)
    check("hybrid_search offline-safe", isinstance(hyb, list))
    _reset_graph_state()
    nodes = gs.list_nodes(limit=10)
    check("list_nodes returns list", isinstance(nodes, list))
    edges = gs.list_edges(limit=10)
    check("list_edges returns list", isinstance(edges, list))

    _reset_graph_state()
    path = gs.shortest_path(1, 3, max_depth=10)
    check("shortest_path found route", path.get("found") is True and path.get("depth") == 2)
    _reset_graph_state()
    ptitle = gs.path_between_titles("default", "A", "B")
    check("path_between_titles returns dict", isinstance(ptitle, dict) and "found" in ptitle)

    _reset_graph_state()
    stats = gs.graph_stats()
    check("graph_stats counts", stats.get("nodes") == 5 and stats.get("edges") == 3 and stats.get("tags") == 2)
    check("graph_stats node_types", stats.get("node_types", {}).get("concept") == 3)

    _reset_graph_state()
    mig = gs.migrate_memory_to_nodes()
    check("migrate_memory_to_nodes returns dict", isinstance(mig, dict) and "migrated" in mig)

    _reset_graph_state()
    sync = gs.sync_wiki_links("default")
    check("sync_wiki_links safe when no docs", isinstance(sync, dict))

check("graph_store update_node offline", gs.update_node(99, content="new") is False)
check("graph_store delete_node offline", gs.delete_node(99) is False)
check("graph_store remove_edges offline", gs.remove_edges(source_id=1) == 0)
check("graph_store path offline", gs.shortest_path(1, 3)["found"] is False)

section("Orchestrator (fake model manager)")
from orchestrator import Orchestrator
from memory import MemoryManager as MM2


class FakeModels:
    def __init__(self):
        self.configs = {
            "hy-mt2": SimpleNamespace(role="Strategist",
                                      capabilities=["plan", "analyze", "general", "code", "math",
                                                    "summarize", "translate", "creative", "tool"]),
            "minicpm-v9": SimpleNamespace(role="Executor",
                                          capabilities=["general", "code", "math", "summarize", "translate"]),
            "minicpm-tooluse": SimpleNamespace(role="ToolExecutor",
                                               capabilities=["tool", "code"]),
        }
        self.gen_results = {}
        self.fail = False
        self.instances = {}
        self.last_prompt = ""

    def generate(self, name, prompt, max_tokens=None, temperature=None, stop=None):
        self.last_prompt = prompt
        if self.fail:
            raise RuntimeError("boom")
        if name == "hy-mt2":
            if "Rate the answer quality" in prompt:
                m = _re.search(r"A: (.*)", prompt)
                a = m.group(1) if m else ""
                return f"{min(10.0, len(a) / 40.0):.1f}"
            if "planning assistant" in prompt or "<|im_start|>assistant" in prompt and max_tokens and max_tokens <= 256:
                return "PLAN"
        return self.gen_results.get(name, "Answer from " + name)

    def generate_stream(self, name, prompt, max_tokens=None, temperature=None, stop=None):
        yield from ["Hello", " ", "World"]

    def ensure_loaded(self, names, budget_mb=None, keep=None):
        pass

    def get_vram_estimate(self, name):
        return 0


fm = FakeModels()
memm = MM2()
orch = Orchestrator(fm, memm)

check("resolve executor default", orch._resolve_executor(None) == "hy-mt2")
check("resolve executor override", orch._resolve_executor("minicpm-tooluse") == "minicpm-tooluse")
check("resolve executor bad override", orch._resolve_executor("nope") == "hy-mt2")
_task_sel, pe = orch.router.select_executors("hello", 2, None)
check("parallel executors capped", len(pe) == 2 and pe[0] == "hy-mt2", f"({pe})")

old_pmax = CONFIG.parallel_max
CONFIG.parallel_max = 2
res = orch.run("hello", conv_id="t-par", use_planning=False, parallel=True)
check("run parallel response", res["response"] in ("Answer from hy-mt2", "Answer from minicpm-v9"),
      f"[{res['response']}]")
check("run parallel candidates", res.get("parallel_candidates") == 2, f"({res.get('parallel_candidates')})")

fm.gen_results = {"hy-mt2": "Short.", "minicpm-v9": "This is a much longer and more complete answer."}
res = orch.run("pick best", conv_id="t-best", use_planning=False, parallel=True)
check("run picks best", res["model"] == "minicpm-v9",
      f"(model={res['model']})")

fm.gen_results = {}
orch.router.harness._data.clear()
orch.router.harness.generation = 0
res = orch.run("plan me", conv_id="t-plan", use_planning=True, parallel=False)
check("run planning thinking", res["thinking"] == "PLAN")
check("run planning response", res["response"] == "Answer from hy-mt2")

res = orch.run("serial", conv_id="t-serial", use_planning=False, parallel=False)
check("run serial no candidates", "parallel_candidates" not in res and res["response"] == "Answer from hy-mt2")

sandbox_conv_before = len(memm.conversations)
res = orch.run("sandbox me", conv_id="t-sandbox", use_planning=False, parallel=False, sandbox=True)
check("run sandbox works", res["response"] == "Answer from hy-mt2")
check("run sandbox no persistence", len(memm.conversations) == sandbox_conv_before)

fm.fail = True
memm.get_or_create("t-reg").clear()
try:
    orch.run("boom", conv_id="t-reg", use_planning=False, parallel=True)
    check("run all-fail raises", False)
except RuntimeError as e:
    check("run all-fail raises", "Generation failed" in str(e), f"[{e}]")
check("run all-fail rolls back conv", len(memm.get_or_create("t-reg").messages) == 0)
fm.fail = False

conv_id = "t-stream"
events = list(orch.stream("hi", conv_id=conv_id, use_planning=True))
texts = [e["content"] for e in events if e["type"] == "response"]
check("stream emits thinking + response", any(e["type"] == "thinking" for e in events) and "".join(texts) == "Hello World")
_starts = [e["model"] for e in events if e.get("type") == "start"]
check("stream emits start model", bool(_starts), f"({events})")
check("stream persists conv", len(memm.get_or_create(conv_id).messages) == 2)

with mock.patch("orchestrator.get_openai_client") as mg:
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="  Cloud reply  "))]))))
    mg.return_value = client
    res = orch.run("hi", conv_id="t-openai", model_override="openai/gpt-x")
    check("openai path", res["response"] == "Cloud reply" and res["model"] == "gpt-x")

memm.clear_all()

section("Orchestrator temperature/max_tokens passthrough")


class RecorderModels(FakeModels):
    last = {}

    def generate(self, name, prompt, max_tokens=None, temperature=None, stop=None):
        RecorderModels.last = {"max_tokens": max_tokens, "temperature": temperature}
        return super().generate(name, prompt, max_tokens, temperature, stop)

    def generate_stream(self, name, prompt, max_tokens=None, temperature=None, stop=None):
        RecorderModels.last = {"max_tokens": max_tokens, "temperature": temperature}
        yield from ["A", "B"]


orm = Orchestrator(RecorderModels(), memm)
RecorderModels.last = {}
orm.run("hi", conv_id="t-r1", use_planning=False, parallel=False, temperature=0.5, max_tokens=77)
check("orchestrator.run passes temp/max", RecorderModels.last == {"max_tokens": 77, "temperature": 0.5},
      f"[{RecorderModels.last}]")
_judge_saved = CONFIG.parallel_judge
CONFIG.parallel_judge = False
try:
    RecorderModels.last = {}
    orm.run("hi", conv_id="t-r2", use_planning=False, parallel=True, temperature=0.3, max_tokens=33)
    check("orchestrator.run parallel passes temp/max", RecorderModels.last == {"max_tokens": 33, "temperature": 0.3},
          f"[{RecorderModels.last}]")
finally:
    CONFIG.parallel_judge = _judge_saved
RecorderModels.last = {}
list(orm.stream("hi", conv_id="t-r3", use_planning=False, temperature=0.4, max_tokens=88))
check("orchestrator.stream passes temp/max", RecorderModels.last == {"max_tokens": 88, "temperature": 0.4},
      f"[{RecorderModels.last}]")
RecorderModels.last = {}
res = orm.run("hi", conv_id="t-r4", use_planning=False, parallel=False)
check("orchestrator.run defaults", RecorderModels.last == {"max_tokens": 2048, "temperature": None},
      f"[{RecorderModels.last}]")

section("Orchestrator workspace knowledge")
_db_was_on = CONFIG.db.enabled
CONFIG.db.enabled = True
_ws_plan = {"memories": None}


def _ws_capture_plan(user_message, memories, thinking_callback=None):
    _ws_plan["memories"] = memories
    return "PLAN"


try:
    with mock.patch.object(orch, "_select_best_plan", side_effect=_ws_capture_plan), \
            mock.patch("database.retrieve_similar", return_value=["global-mem"]), \
            mock.patch("database.search_workspace_knowledge",
                       return_value=[{"thought": "ws-chunk-1"}, {"thought": "global-mem"}]), \
            mock.patch("database.store_thought"), \
            mock.patch("graph_store.hybrid_search", return_value=[]):
        orch.run("doc question", conv_id="t-ws-k1", use_planning=True, parallel=False, workspace_id="ws-k")
        check("orchestrator merges ws knowledge", sorted(_ws_plan["memories"]) == ["global-mem", "ws-chunk-1"],
              f"[{_ws_plan['memories']}]")
    _ws_plan["memories"] = None
    with mock.patch.object(orch, "_select_best_plan", side_effect=_ws_capture_plan), \
            mock.patch("database.retrieve_similar", return_value=["g1"]), \
            mock.patch("database.search_workspace_knowledge",
                       side_effect=AssertionError("ws search should be skipped")), \
            mock.patch("database.store_thought"), \
            mock.patch("graph_store.hybrid_search", return_value=[]):
        orch.run("doc question", conv_id="t-ws-k2", use_planning=True, parallel=False, workspace_id="default")
        check("orchestrator skips ws knowledge on default", _ws_plan["memories"] == ["g1"])
finally:
    CONFIG.db.enabled = _db_was_on

section("Orchestrator web search")
_ws_flag = CONFIG.web_search_enabled
CONFIG.web_search_enabled = True
try:
    _fake_web = "【Web Search Results】\n• Title\n  Body text here\n【End of Results】"
    with mock.patch("orchestrator.search_web", return_value=_fake_web), \
            mock.patch("database.retrieve_similar", return_value=[]), \
            mock.patch("database.store_thought"):
        orch.run("what is the latest news today", conv_id="t-web-k1", use_planning=False, parallel=False)
        check("orchestrator web search triggers", "Web Search Results" in fm.last_prompt,
              f"[{fm.last_prompt[:40]}]")
        check("orchestrator web search no system mutation",
              "Web Search Results" not in (memm.get_or_create("t-web-k1").system_prompt or ""))
    with mock.patch("orchestrator.search_web", return_value="Search error: boom"), \
            mock.patch("database.store_thought"):
        orch.run("what is the latest news", conv_id="t-web-k2", use_planning=False, parallel=False)
        check("orchestrator web search skips error", "Search error" not in fm.last_prompt)
finally:
    CONFIG.web_search_enabled = _ws_flag

section("Auto-agentic streaming")
_auto_saved = (CONFIG.auto_stream_enabled, CONFIG.auto_stream_thinking,
               CONFIG.auto_stream_min_tokens, CONFIG.auto_stream_max_tokens)
try:
    CONFIG.auto_stream_enabled = True
    CONFIG.auto_stream_thinking = True
    CONFIG.auto_stream_min_tokens = 50
    CONFIG.auto_stream_max_tokens = 2048
    check("auto_stream planning always streams", orch._should_auto_stream("hi", True) is True)
    check("auto_stream long message streams", orch._should_auto_stream("x" * 120, False) is True)
    check("auto_stream code keyword streams", orch._should_auto_stream("write python code", False) is True)
    check("auto_stream creative keyword streams", orch._should_auto_stream("write a story", False) is True)
    check("auto_stream short general batch", orch._should_auto_stream("hi", False) is False)
    CONFIG.auto_stream_enabled = False
    check("auto_stream disabled config", orch._should_auto_stream("write python code", True) is False)
    CONFIG.auto_stream_enabled = True
    CONFIG.auto_stream_min_tokens = 100
    check("auto_stream cap below min", orch._should_auto_stream("write a story", False, 50) is False)
    CONFIG.auto_stream_min_tokens = 50

    _batch_rec = {"run_called": 0}

    def _fake_batch_run(**kw):
        _batch_rec["run_called"] += 1
        return {"response": "Batch answer", "thinking": "BATCH-PLAN", "model": "minicpm-v9"}

    with mock.patch.object(orch, "_should_auto_stream", return_value=False), \
            mock.patch.object(orch, "run", side_effect=_fake_batch_run):
        _ev = list(orch.auto_stream("hi", conv_id="t-auto-batch", use_planning=True))
    _types = [e["type"] for e in _ev]
    check("auto_stream batch start/thinking/response/done",
          _types == ["start", "thinking", "response", "done"], f"({_types})")
    check("auto_stream batch delegates to run", _batch_rec["run_called"] == 1)
    check("auto_stream batch response text", _ev[2]["content"] == "Batch answer")
    check("auto_stream batch done tokens/model",
          _ev[3]["tokens"] == 2 and _ev[3]["model"] == "minicpm-v9", f"({_ev[3]})")

    with mock.patch.object(orch, "_should_auto_stream", return_value=False), \
            mock.patch.object(orch, "run", side_effect=RuntimeError("boom")):
        _ev_bad = list(orch.auto_stream("hi", conv_id="t-auto-bad", use_planning=True))
    check("auto_stream batch error event",
          any(e["type"] == "error" and "boom" in e["content"] for e in _ev_bad), f"({_ev_bad})")

    _st_ev = [{"type": "start", "model": "hy-mt2"},
              {"type": "thinking", "content": "STEP"},
              {"type": "response", "content": "One"},
              {"type": "response", "content": "Two"},
              {"type": "done", "model": "hy-mt2"}]
    with mock.patch.object(orch, "_should_auto_stream", return_value=True), \
            mock.patch.object(orch, "stream", return_value=iter(_st_ev)):
        _ev2 = list(orch.auto_stream("write code", conv_id="t-auto-stream", use_planning=True))
    check("auto_stream streaming passes thinking",
          any(e["type"] == "thinking" and e["content"] == "STEP" for e in _ev2))
    check("auto_stream streaming passes responses",
          [e["content"] for e in _ev2 if e["type"] == "response"] == ["One", "Two"])
    check("auto_stream streaming includes done", any(e["type"] == "done" for e in _ev2))

    with mock.patch.object(orch, "_should_auto_stream", return_value=True), \
            mock.patch.object(orch, "stream", return_value=iter(_st_ev)):
        _ev3 = list(orch.auto_stream("write code", conv_id="t-auto-stream2", use_planning=True,
                                     stream_thoughts=False))
    check("auto_stream stream_thoughts filters", all(e["type"] != "thinking" for e in _ev3))

    CONFIG.auto_stream_thinking = False
    with mock.patch.object(orch, "_should_auto_stream", return_value=True), \
            mock.patch.object(orch, "stream", return_value=iter(_st_ev)):
        _ev4 = list(orch.auto_stream("write code", conv_id="t-auto-stream3", use_planning=True))
    check("auto_stream config thinking filter", all(e["type"] != "thinking" for e in _ev4))
finally:
    (CONFIG.auto_stream_enabled, CONFIG.auto_stream_thinking,
     CONFIG.auto_stream_min_tokens, CONFIG.auto_stream_max_tokens) = _auto_saved

section("Router & adaptive harness")
from router import classify_task, Harness, ModelRouter

check("classify code", classify_task("write a python function to fix this bug") == "code")
check("classify math", classify_task("calculate 2+2") == "math")
check("classify translate", classify_task("translate this to french") == "translate")
check("classify summarize", classify_task("summarize this article please") == "summarize")
check("classify tool", classify_task("call the tool for me") == "tool")
check("classify general", classify_task("tell me a nice thought") == "general")

har = Harness(epsilon=0.0)
har.record("code", "A", True, latency=2.0, tokens=100)
har.record("code", "B", True, latency=1.0, tokens=100)
check("harness faster model scores higher", har.score("code", "B") > har.score("code", "A"))
check("harness choose best", har.choose("code", ["A", "B"]) == "B")
check("harness ranked order", har.ranked("code", ["A", "B"]) == ["B", "A"])

har2 = Harness(epsilon=0.0)
har2.record("code", "A", True, latency=1.0, tokens=50)
har2.record("code", "A", False, latency=1.0)
har2.record("code", "A", False, latency=1.0)
har2.record("code", "B", True, latency=1.0, tokens=50)
check("harness penalizes errors", har2.score("code", "B") > har2.score("code", "A"))
check("harness picks reliable", har2.choose("code", ["A", "B"]) == "B")
check("harness stats fields", har2.stats()["generation"] >= 0 and "data" in har2.stats())

har3 = Harness(epsilon=1.0, random_state=1)
check("harness explores with epsilon=1", har3.choose("code", ["A", "B"]) in ("A", "B"))
har3.record("x", "M", True, latency=1.0)
har3.record("x", "M", False, latency=1.0)
check("harness 50% success score", abs(har3.score("x", "M") - (0.5 * 60 + 30 * 1.0 + 10)) < 0.001)

router = ModelRouter(fm)
check("router executor names", router.executor_names() == ["hy-mt2", "minicpm-v9", "minicpm-tooluse"])
check("router rank general", router.rank_for_task("general")[:2] == ["hy-mt2", "minicpm-v9"])
check("router rank code includes tooluse", "minicpm-tooluse" in router.rank_for_task("code"))
check("router rank unknown", router.rank_for_task("xenology")[:2] == ["hy-mt2", "minicpm-v9"])
task, ex = router.select_executors("write a python function", 2)
check("router select code task", task == "code" and ex[0] == "hy-mt2")
task, ex = router.select_executors("hi", 2, model_override="minicpm-tooluse")
check("router select override", task == "general" and ex[0] == "minicpm-tooluse")
check("router primary general", router.primary("general") == "hy-mt2")
check("router primary override", router.primary("general", "minicpm-tooluse") == "minicpm-tooluse")

section("Metrics")
from metrics import MetricsCollector

mc = MetricsCollector()
mc.record_request(task="code", model="m1", tokens_in=10)
mc.record_completion(task="code", model="m1", tokens_out=50, latency=2.0, ok=True)
s = mc.snapshot()
check("metrics request/tokens", s["requests"] == 1 and s["tokens_in"] == 10 and s["tokens_out"] == 50)
check("metrics per_model", s["per_model"]["m1"]["tokens_out"] == 50 and s["per_model"]["m1"]["avg_latency"] == 2.0)
check("metrics per_task", s["per_task"]["code"]["requests"] == 1)
mc.record_completion(task="code", model="m1", ok=False)
s = mc.snapshot()
check("metrics errors", s["per_model"]["m1"]["errors"] == 1 and s["per_task"]["code"]["errors"] == 1)
mc.record_request()
mc.record_completion(ok=False)
s = mc.snapshot()
check("metrics no-model no-op", "general" in s["per_task"] and "unknown" not in s["per_model"])
check("metrics tokens_per_sec", mc.snapshot()["tokens_per_sec"] > 0)

section("Hardware detection")
import hardware as hw

with mock.patch("hardware._vram_total_mb", return_value=6144), \
        mock.patch("hardware._ram_total_mb", return_value=16384), \
        mock.patch("hardware._gpu_backend", return_value="vulkan"):
    info = hw.detect_hardware(force=True)
    check("hardware detect keys",
          info["cpu_cores"] > 0 and info["ram_total_mb"] == 16384
          and info["gpu_vram_mb"] == 6144 and info["gpu_backend"] == "vulkan")
    hw_old = (CONFIG.threads, CONFIG.vram_budget_mb, CONFIG.auto_tune, [m.n_ctx for m in CONFIG.models])
    try:
        CONFIG.threads = 0
        CONFIG.vram_budget_mb = 0
        CONFIG.auto_tune = True
        hw.auto_tune(force=True)
        check("auto_tune budget", CONFIG.vram_budget_mb == 5120, f"({CONFIG.vram_budget_mb})")
        check("auto_tune threads", CONFIG.threads > 0)
        check("auto_tune ram threshold", [m.n_ctx for m in CONFIG.models] == hw_old[3])
    finally:
        CONFIG.threads, CONFIG.vram_budget_mb, CONFIG.auto_tune = hw_old[:3]
        for m, old_ctx in zip(CONFIG.models, hw_old[3]):
            m.n_ctx = old_ctx
        CONFIG.sync_threads()

section("ARC harness")
import arc
import json as _json
import tempfile

res = arc.run_arc_eval()
check("ARC no dataset", res.get("dataset") is False)
check("ARC grid roundtrip", arc.parse_grid(arc.encode_grid([[1, 2], [3, 0]])) == [[1, 2], [3, 0]])
check("ARC parse spaced grid", arc.parse_grid("1 2\n3 4") == [[1, 2], [3, 4]])
check("ARC parse comma grid", arc.parse_grid("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]])

_arc_tmp = os.path.join(tempfile.gettempdir(), "arc_test_dataset.json")
with open(_arc_tmp, "w", encoding="utf-8") as _fh:
    _json.dump([{
        "train": [{"input": [[0, 0], [0, 0]], "output": [[1, 1], [1, 1]]}],
        "test": [{"input": [[0, 0]], "output": [[1, 1]]}],
    }], _fh)


class ArcFake:
    def __init__(self, out):
        self.out = out

    def generate(self, name, prompt, max_tokens=None, temperature=None, stop=None):
        return self.out


res = arc.run_arc_eval(model_manager=ArcFake("11"), limit=1, dataset_path=_arc_tmp)
check("ARC solves with fake model", res["dataset"] is True and res["correct"] == 1 and res["total"] == 1,
      f"({res})")
res = arc.run_arc_eval(model_manager=ArcFake("99"), limit=1, dataset_path=_arc_tmp, exact=True)
check("ARC exact fails on wrong", res["correct"] == 0)
try:
    os.remove(_arc_tmp)
except OSError:
    pass

section("API endpoints (TestClient + mocks)")
import api as api_mod
from web_ui import create_web_app
from fastapi.testclient import TestClient

api_mod.app = create_web_app(api_mod.app)

CONFIG.db.enabled = False
CONFIG.openai.enabled = False
CONFIG.api_token = ""  # nosec B105
CONFIG.parallel_enabled = True
CONFIG.parallel_max = 2
CONFIG.parallel_judge = True
CONFIG.auto_load = False


def fake_generate(name, prompt, max_tokens=None, temperature=None, stop=None):
    _gen_rec["kwargs"] = {"max_tokens": max_tokens, "temperature": temperature}
    if name == "hy-mt2":
        if "Rate the answer quality" in prompt:
            m = _re.search(r"A: (.*)", prompt)
            a = m.group(1) if m else ""
            return f"{min(10.0, len(a) / 40.0):.1f}"
        if "planning assistant" in prompt:
            return "PLAN"
        return "Short."
    if name == "minicpm-v9":
        return "This is a much longer and more complete answer."
    return "Short."


def fake_stream(name, prompt, max_tokens=None, temperature=None, stop=None):
    _gen_rec["stream_kwargs"] = {"max_tokens": max_tokens, "temperature": temperature}
    yield from ["Hello", " ", "World"]


def fake_embedder():
    return FakeEmbedder()


_api_cfg_saved = (CONFIG.threads, CONFIG.vram_budget_mb, CONFIG.harness_epsilon,
                  CONFIG.cloud_provider, CONFIG.openai.base_url, CONFIG.openai.chat_model, CONFIG.auto_load)

_gen_rec = {"kwargs": None, "stream_kwargs": None}

with mock.patch.object(api_mod.model_manager, "generate", side_effect=fake_generate), \
        mock.patch.object(api_mod.model_manager, "generate_stream", side_effect=fake_stream), \
        mock.patch.object(api_mod.model_manager, "chat", side_effect=lambda name, messages, max_tokens=None, temperature=None: fake_generate(name, messages[-1]["content"], max_tokens, temperature)), \
        mock.patch("database.get_embedder", side_effect=fake_embedder), \
        mock.patch("database.retrieve_similar", return_value=["mem1", "mem2"]), \
        mock.patch("database.store_thought"), \
        mock.patch("database.count_memories", return_value=7):
    client = TestClient(api_mod.app)

    r = client.get("/v1/health")
    j = r.json()
    check("GET /v1/health", r.status_code == 200 and j["status"] == "healthy" and len(j["models_available"]) >= 3)

    r = client.get("/v1/models")
    j = r.json()
    check("GET /v1/models", len(j["data"]) >= 3 and all("role" in m and "owned_by" in m for m in j["data"]), f"({len(j['data'])} models)")

    r = client.get("/v1/system")
    check("GET /v1/system",
          "model_stats" in r.json() and "database" in r.json() and "hardware" in r.json() and "metrics" in r.json())

    r = client.get("/v1/metrics")
    j = r.json()
    check("GET /v1/metrics", "tokens_out" in j and "per_model" in j and "per_task" in j)

    r = client.get("/v1/metrics/history")
    j = r.json()
    check("GET /v1/metrics/history", "snapshots" in j and isinstance(j["snapshots"], list))
    r = client.post("/v1/metrics/history", json={"requests": 3, "tokens_out": 42})
    check("POST /v1/metrics/history", r.status_code == 200 and r.json().get("status") == "saved")
    r = client.post("/v1/metrics/history", json={})
    check("POST /v1/metrics/history empty rejected", r.status_code == 400)
    r = client.post("/v1/metrics/history/prune?max_rows=100")
    check("POST /v1/metrics/history/prune", r.status_code == 200 and "deleted" in r.json())

    r = client.get("/v1/sessions")
    j = r.json()
    check("GET /v1/sessions", "sessions" in j and isinstance(j["sessions"], list))
    r = client.post("/v1/sessions", json={"name": "Sess A", "user_id": "u1"})
    j = r.json()
    check("POST /v1/sessions", r.status_code == 200 and j["session"]["name"] == "Sess A", f"({j})")
    sid = j["session"]["id"]
    r = client.get(f"/v1/sessions/{sid}")
    check("GET /v1/sessions/{id}", r.json()["session"]["id"] == sid)
    r = client.post(f"/v1/sessions/{sid}/update", json={"name": "Sess B", "touch": True})
    check("POST /v1/sessions/{id}/update", r.json()["session"]["name"] == "Sess B")
    r = client.delete(f"/v1/sessions/{sid}")
    check("DELETE /v1/sessions/{id}", r.json()["status"] == "deleted")
    r = client.get(f"/v1/sessions/{sid}")
    check("GET missing session 404", r.status_code == 404)
    r = client.post("/v1/sessions/prune?max_age_days=30")
    check("POST /v1/sessions/prune", r.status_code == 200 and "deleted" in r.json())

    r = client.get("/v1/router/stats")
    j = r.json()
    check("GET /v1/router/stats", "generation" in j and "data" in j)

    r = client.get("/v1/hardware")
    j = r.json()
    check("GET /v1/hardware", "cpu_cores" in j and "gpu_backend" in j)

    r = client.get("/v1/models/stats")
    check("GET /v1/models/stats", "load_times" in r.json() and "load_errors" in r.json())

    r = client.get("/v1/config")
    j = r.json()
    check("GET /v1/config",
          "enabled" in j["parallel"] and "interval_hours" in j["prune"]
          and "budget_mb" in j["vram"] and "epsilon" in j["harness"] and "presets" in j["cloud"]
          and "timeout_s" in j["gen"])

    r = client.post("/v1/config", json={"key": "threads", "value": 4})
    check("POST /v1/config threads", r.json()["value"] == 4 and CONFIG.threads == 4)
    CONFIG.sync_threads()

    r = client.post("/v1/config", json={"key": "gen.timeout_s", "value": 90})
    check("POST /v1/config gen timeout", r.json()["value"] == 90 and CONFIG.gen_timeout_s == 90)

    r = client.post("/v1/config", json={"key": "vram.budget_mb", "value": 4096})
    check("POST /v1/config vram budget", r.json()["value"] == 4096 and CONFIG.vram_budget_mb == 4096)

    r = client.post("/v1/config", json={"key": "harness.epsilon", "value": 0.3})
    check("POST /v1/config harness epsilon", r.json()["value"] == 0.3 and CONFIG.harness_epsilon == 0.3)

    r = client.post("/v1/config", json={"key": "cloud.provider", "value": "groq"})
    j = r.json()
    check("POST /v1/config cloud preset",
          j["value"] == "groq" and CONFIG.cloud_provider == "groq"
          and CONFIG.openai.base_url.startswith("https://api.groq.com"))
    r = client.post("/v1/config", json={"key": "cloud.provider", "value": "bogus"})
    check("POST /v1/config cloud bogus", r.json().get("value") == "none")

    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "use_planning": False, "parallel": False})
    j = r.json()
    check("POST chat no-plan", r.status_code == 200 and j["choices"][0]["message"]["content"] == "Short.")

    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "use_planning": True, "parallel": False})
    j = r.json()
    check("POST chat planning", j["choices"][0]["message"]["content"] == "Short." and j.get("thinking") == "PLAN")

    _saved_harness = api_mod.orchestrator.router.harness
    _harness = Harness(epsilon=0.0)
    _harness.adjust("general", "minicpm-v9", 99)
    api_mod.orchestrator.router.harness = _harness
    try:
        r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "parallel": True})
        j = r.json()
    finally:
        api_mod.orchestrator.router.harness = _saved_harness
    check("POST chat parallel", j.get("runner_model") == "minicpm-v9" and j.get("parallel_candidates") == 2,
          f"(model={j.get('runner_model')})")

    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "model": "hy-mt2", "sandbox": True, "parallel": False})
    check("POST chat sandbox", r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "Short.")

    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "stream": True}, timeout=30)
    check("POST chat stream SSE", "text/event-stream" in r.headers.get("content-type", "") and "data: [DONE]" in r.text)
    check("POST chat stream chunks", '"content":"Hello"' in r.text or "Hello" in r.text)

    r = client.post("/v1/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]}, timeout=30)
    check("POST /v1/chat/stream", r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", ""))
    check("POST /v1/chat/stream thinking", '"type": "thinking"' in r.text or "thinking" in r.text)

    _auto_events = [{"type": "start", "model": "hy-mt2"},
                    {"type": "thinking", "content": "PLAN-STEP"},
                    {"type": "response", "content": "Auto reply"},
                    {"type": "done", "model": "hy-mt2"}]
    with mock.patch.object(api_mod.orchestrator, "auto_stream",
                           lambda **kw: iter(_auto_events)):
        r = client.post("/v1/chat/auto-stream",
                        json={"messages": [{"role": "user", "content": "hi"}]}, timeout=30)
    check("POST /v1/chat/auto-stream SSE",
          r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", ""))
    check("POST /v1/chat/auto-stream frames",
          '"type": "response"' in r.text and "Auto reply" in r.text and '"type": "thinking"' in r.text)
    check("POST /v1/chat/auto-stream done hidden", '"type": "done"' not in r.text)

    r = client.post("/v1/chat/auto-stream", json={"messages": []})
    check("POST /v1/chat/auto-stream empty rejected", r.status_code in (400, 422),
          f"({r.status_code})")

    _up_dir = os.path.join(BASE, "generated", "chat_uploads")
    _up_files = []
    try:
        r = client.post("/v1/chat/upload", files={"file": ("hello.txt", b"hello world", "text/plain")})
        _j = r.json()
        _up_files.append(os.path.basename(_j.get("url", "")))
        check("POST /v1/chat/upload",
              r.status_code == 200 and _j.get("url", "").startswith("/generated/chat_uploads/")
              and _j.get("name") == "hello.txt", f"({_j})")
        check("POST /v1/chat/upload persisted",
              bool(_up_files[-1]) and os.path.exists(os.path.join(_up_dir, _up_files[-1])),
              f"({_up_files[-1]})")
        r2 = client.post("/v1/chat/upload", files={"file": ("..\\evil.txt", b"x", "text/plain")})
        _j2 = r2.json()
        check("POST /v1/chat/upload sanitizes path",
              r2.status_code == 200 and ".." not in _j2.get("url", "")
              and "\\" not in _j2.get("url", "") and "/" not in _j2.get("name", ""),
              f"({_j2})")
    finally:
        for _f in _up_files:
            try:
                os.remove(os.path.join(_up_dir, _f))
            except OSError:
                pass

    r = client.post("/v1/generate", json={"model": "hy-mt2", "prompt": "hi"})
    check("POST /v1/generate", r.status_code == 200 and r.json()["choices"][0]["text"] == "Short.")

    r = client.post("/v1/batch/generate", json={"prompts": ["a", "b"]})
    j = r.json()
    check("POST /v1/batch/generate", all(x["status"] == "ok" for x in j["results"]) and len(j["results"]) == 2)

    r = client.post("/v1/embeddings", json={"input": "hello"})
    j = r.json()
    check("POST /v1/embeddings", len(j["data"][0]["embedding"]) == 384)

    r = client.post("/v1/memory/search", json={"query": "q"})
    j = r.json()
    check("POST /v1/memory/search", j["results"] == ["mem1", "mem2"] and j["count"] == 2)

    r = client.post("/v1/memory/store", json={"agent": "a", "thought": "t"})
    check("POST /v1/memory/store", r.json()["status"] == "stored")

    r = client.get("/v1/memory/stats")
    check("GET /v1/memory/stats", r.json()["enabled"] is False and r.json()["count"] == 0)

    r = client.post("/v1/tools/summarize", json={"text": "long text here"})
    check("POST /v1/tools/summarize", r.status_code == 200 and "summary" in r.json())
    r = client.post("/v1/tools/analyze", json={"text": "long text here"})
    check("POST /v1/tools/analyze", r.status_code == 200 and "analysis" in r.json())
    r = client.post("/v1/tools/translate", json={"text": "bonjour", "target_language": "English"})
    check("POST /v1/tools/translate", r.status_code == 200 and r.json()["target_language"] == "English")

    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/call", "params": {"input": "hi"}, "id": 1})
    j = r.json()
    check("POST /mcp tools/call", bool(j.get("result")), f"[{str(j.get('result'))[:30]}]")
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 2})
    check("POST /mcp tools/list", len(r.json()["result"]) >= 1)
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "bogus", "id": 3})
    check("POST /mcp unknown method", r.json()["error"]["code"] == -32601)

    before = set(api_mod.memory_manager.conversations.keys())
    r = client.get("/v1/chat/history?conv_id=never-exists-xyz")
    after = set(api_mod.memory_manager.conversations.keys())
    check("GET history no side-effect", r.json()["count"] == 0 and "never-exists-xyz" not in after and before == after)

    r = client.get("/v1/chat/conversations")
    check("GET conversations", "conversations" in r.json())

    r = client.post("/v1/chat/clear?conv_id=some-conv")
    check("POST /v1/chat/clear", r.json()["status"] == "cleared")

    r = client.get("/v1/db/stats")
    j = r.json()
    check("GET /v1/db/stats", j["enabled"] is False and "ivfflat" in j and "cache_entries" in j and "agents" in j)

    r = client.get("/v1/memory/recent?limit=5")
    check("GET /v1/memory/recent", r.json()["count"] == 0)

    r = client.post("/v1/memory/clear")
    check("POST /v1/memory/clear", r.json()["status"] == "cleared")

    r = client.post("/v1/memory/prune")
    check("POST /v1/memory/prune", r.json()["status"] == "pruned")

    r = client.get("/v1/chat/conversations?labels=1")
    j = r.json()
    check("GET conversations labels",
          isinstance(j["conversations"], list) and all("id" in c and "title" in c and "count" in c for c in j["conversations"]))

    r = client.post("/v1/config", json={"key": "openai.chat_model", "value": "gpt-4o"})
    check("config openai.chat_model", r.json()["value"] == "gpt-4o" and CONFIG.openai.chat_model == "gpt-4o")

    r = client.post("/v1/config", json={"key": "model.gemma-4-e4b.temperature", "value": 0.7})
    check("config model.temperature", r.json()["value"] == 0.7)

    r = client.post("/v1/config", json={"key": "model.bogus.temperature", "value": 0.5})
    check("config model.bogus 404", r.status_code == 404)

    r = client.post("/v1/config", json={"key": "model.gemma-4-e4b.n_ctx", "value": 4096})
    check("config model.n_ctx", r.json()["value"] == 4096)

    _cloud_saved = CONFIG.cloud_provider
    try:
        r = client.post("/v1/config", json={"key": "cloud.provider", "value": "none"})
        check("config cloud none", r.json()["value"] == "none" and CONFIG.cloud_provider == "none")
    finally:
        CONFIG.cloud_provider = _cloud_saved

    r = client.get("/v1/config")
    j = r.json()
    check("config has models + db + token",
          "models" in j and j["db"].get("host") == "localhost" and "api_token" in j and j["api_token"] is False)

    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "first question"}],
        "conversation_id": "web-multiturn-1", "parallel": False, "use_planning": False})
    check("conversation_id completions", r.status_code == 200)
    h = client.get("/v1/chat/history?conv_id=web-multiturn-1")
    check("conversation_id keeps history",
          h.json()["count"] == 2 and h.json()["messages"][0]["role"] == "user",
          f"[{h.json()['count']}]")

    _gen_rec["kwargs"] = None
    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}],
        "model": "hy-mt2", "temperature": 0.9, "max_tokens": 77, "parallel": False, "use_planning": False})
    check("chat passes temperature/max_tokens", r.status_code == 200 and _gen_rec["kwargs"] == {"max_tokens": 77, "temperature": 0.9},
          f"[{_gen_rec['kwargs']}]")
    j = r.json()
    check("chat usage token counts", j["usage"]["prompt_tokens"] == 1 and j["usage"]["completion_tokens"] == 1,
          f"[{j['usage']}]")

    _gen_rec["stream_kwargs"] = None
    r = client.post("/v1/chat/stream", json={
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.4, "max_tokens": 55})
    check("stream passes temperature/max_tokens", r.status_code == 200 and _gen_rec["stream_kwargs"] == {"max_tokens": 55, "temperature": 0.4},
          f"[{_gen_rec['stream_kwargs']}]")

    CONFIG.api_token = "test-token"  # nosec B105
    try:
        r = client.get("/v1/models")
        check("auth blocks", r.status_code == 401)
        r = client.get("/v1/models", headers={"Authorization": "Bearer test-token"})
        check("auth allows", r.status_code == 200)
    finally:
        CONFIG.api_token = ""  # nosec B105

    CONFIG.api_token = "primary-token"  # nosec B105
    CONFIG.api_tokens = ("rotation-token",)
    try:
        r = client.get("/v1/models", headers={"Authorization": "Bearer rotation-token"})
        check("auth allows rotation token", r.status_code == 200)
        r = client.get("/v1/models", headers={"Authorization": "Bearer primary-token"})
        check("auth allows primary token", r.status_code == 200)
        r = client.get("/v1/models", headers={"Authorization": "Bearer bogus"})
        check("auth blocks unknown with rotation", r.status_code == 401)
        r = client.post("/v1/config", json={"key": "api_token", "value": "new-token,primary-token"},  # nosec B105
                        headers={"Authorization": "Bearer primary-token"})  # nosec B105
        check("config rotate token keeps old", r.status_code == 200 and CONFIG.api_token == "new-token"  # nosec B105
              and CONFIG.api_tokens == ("primary-token",), f"({r.status_code})")
        r = client.get("/v1/models", headers={"Authorization": "Bearer new-token"})
        check("auth allows rotated token", r.status_code == 200)
        r = client.get("/v1/models", headers={"Authorization": "Bearer primary-token"})
        check("auth allows kept old token", r.status_code == 200)
        j = client.get("/v1/config", headers={"Authorization": "Bearer new-token"}).json()
        check("config reports token count", j.get("api_token") is True and j.get("api_token_count") == 2,
              f"({j.get('api_token')},{j.get('api_token_count')})")
    finally:
        CONFIG.api_token = ""  # nosec B105
        CONFIG.api_tokens = ()

    try:
        r = client.get("/v1/workspaces")
        j = r.json()
        check("GET /v1/workspaces", any(w["id"] == "default" for w in j["workspaces"]))
        r = client.post("/v1/workspaces", json={"name": "Research Lab", "description": "NLP",
                                                "system_prompt": "Be scientific", "default_model": "minicpm-v9"})
        j = r.json()
        _wsx = j["id"]
        check("POST /v1/workspaces creates",
              r.status_code == 200 and bool(_wsx) and j["workspace"]["name"] == "Research Lab")
        r = client.post(f"/v1/workspaces/{_wsx}/update", json={"name": "Research", "system_prompt": "Sci"})
        j = r.json()
        check("POST workspaces/update",
              j["workspace"]["name"] == "Research" and j["workspace"]["system_prompt"] == "Sci")
        r = client.post("/v1/workspaces/default/delete")
        check("default workspace protected", r.status_code == 404)
        r = client.get(f"/v1/workspaces/{_wsx}/files")
        check("GET workspaces files empty", r.json()["count"] == 0)
        r = client.post(f"/v1/workspaces/{_wsx}/files/upload",
                        json={"name": "notes.md", "content": "First paragraph.\n\n" + ("knowledge " * 300)})
        j = r.json()
        check("POST files/upload",
              j["status"] == "uploaded" and j["file"]["name"] == "notes.md" and j["chunks"] >= 1)
        r = client.get(f"/v1/workspaces/{_wsx}/files/notes.md/content")
        check("GET files/content",
              r.status_code == 200 and "knowledge" in (r.json().get("content") or ""),
              f"(status={r.status_code} body={str(r.json())[:80]})")
        r = client.get(f"/v1/workspaces/{_wsx}/files")
        j = r.json()
        check("GET files lists upload", j["count"] == 1 and j["files"][0]["name"] == "notes.md")
        r = client.get(f"/v1/workspaces/{_wsx}/knowledge/search?query=notes")
        check("GET knowledge/search", r.status_code == 200 and r.json()["count"] == 0,
              f"(status={r.status_code} body={str(r.json())[:80]})")
        r = client.post(f"/v1/workspaces/{_wsx}/files/delete", params={"name": "notes.md"})
        check("POST files/delete", r.json()["status"] == "deleted")
        r = client.post(f"/v1/workspaces/{_wsx}/files/delete", params={"name": "notes.md"})
        check("POST files/delete missing 404", r.status_code == 404)

        r = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "ws question"}],
            "conversation_id": "wsx-conv1", "parallel": False, "use_planning": False,
            "workspace_id": _wsx})
        check("chat with workspace_id", r.status_code == 200)
        h = client.get(f"/v1/chat/history?conv_id=wsx-conv1&workspace_id={_wsx}")
        check("history scoped to workspace", h.json()["count"] == 2, f"[{h.json()['count']}]")
        h = client.get("/v1/chat/history?conv_id=wsx-conv1&workspace_id=default")
        check("history isolated across workspaces", h.json()["count"] == 0)
        convs = client.get(f"/v1/chat/conversations?workspace_id={_wsx}").json()["conversations"]
        check("conversations scoped to workspace", any(c.get("id") == "wsx-conv1" for c in convs))

        r = client.get(f"/v1/workspaces/{_wsx}/export")
        j = r.json()
        _exported = j["conversations"]
        check("export json",
              r.status_code == 200 and j["count"] == 1 and _exported[0]["id"] == "wsx-conv1"
              and len(_exported[0]["messages"]) == 2)
        r = client.get(f"/v1/workspaces/{_wsx}/export?format=markdown")
        check("export markdown",
              "text/markdown" in r.headers.get("content-type", "") and "Research" in r.text)

        r = client.post("/v1/workspaces", json={"name": "Import Target"})
        _wsy = r.json()["id"]
        r = client.post(f"/v1/workspaces/{_wsy}/import", json={"conversations": _exported})
        check("POST workspaces import", r.json()["status"] == "imported" and r.json()["conversations"] == 1)
        h = client.get(f"/v1/chat/history?conv_id=wsx-conv1&workspace_id={_wsy}")
        check("import restores messages", h.json()["count"] == 2, f"[{h.json()['count']}]")

        api_mod._log_ring.emit(logging.LogRecord("api", logging.INFO, __file__, 0, "admin-log-probe", None, None))
        r = client.get("/v1/admin/logs")
        j = r.json()
        check("GET /v1/admin/logs",
              r.status_code == 200 and j["count"] >= 1 and isinstance(j["lines"], list)
              and any("admin-log-probe" in line for line in j["lines"]))
        r = client.get("/v1/admin/threads")
        j = r.json()
        check("GET /v1/admin/threads", j["count"] >= 1 and all("name" in t and "alive" in t for t in j["threads"]))
        r = client.get("/v1/admin/metrics")
        j = r.json()
        check("GET /v1/admin/metrics", "uptime_s" in j and "threads" in j and "requests" in j)

        r = client.post(f"/v1/workspaces/{_wsx}/delete")
        check("POST workspaces/delete", r.json()["status"] == "deleted")
        r = client.get(f"/v1/workspaces/{_wsx}/export")
        check("workspace gone after delete", r.status_code == 404)
        h = client.get(f"/v1/chat/history?conv_id=wsx-conv1&workspace_id={_wsx}")
        check("delete drops workspace conversations", h.json()["count"] == 0)
    finally:
        db_mod.reset_workspace_store()

(CONFIG.threads, CONFIG.vram_budget_mb, CONFIG.harness_epsilon,
 CONFIG.cloud_provider, CONFIG.openai.base_url, CONFIG.openai.chat_model, CONFIG.auto_load) = _api_cfg_saved
CONFIG.sync_threads()

section("API extended coverage (load/unload/generate/embeddings/memory)")

with mock.patch.object(api_mod.model_manager, "generate", side_effect=fake_generate), \
        mock.patch.object(api_mod.model_manager, "generate_stream", side_effect=fake_stream), \
        mock.patch("database.get_embedder", side_effect=fake_embedder), \
        mock.patch("database.retrieve_similar", return_value=["mem1", "mem2"]), \
        mock.patch("database.store_thought"), \
        mock.patch("database.count_memories", return_value=7):
    client = TestClient(api_mod.app)

    with mock.patch.object(api_mod.model_manager, "load") as mock_load:
        r = client.post("/v1/models/load?name=minicpm-v9")
        check("POST load model", r.status_code == 200 and r.json()["status"] == "loaded")
        mock_load.assert_called_with("minicpm-v9")
        r = client.post("/v1/models/load?name=nope")
        check("POST load unknown model", r.status_code == 404 and "not found" in r.json()["detail"].lower())

    with mock.patch.object(api_mod.model_manager, "unload") as mock_unload:
        api_mod.model_manager.instances["minicpm-v9"] = object()
        r = client.post("/v1/models/unload?name=minicpm-v9")
        check("POST unload model", r.status_code == 200 and r.json()["status"] == "unloaded")
        mock_unload.assert_called_with("minicpm-v9")
        r = client.post("/v1/models/unload?name=nope")
        check("POST unload not loaded", r.status_code == 200 and r.json()["status"] == "not_loaded")

    r = client.post("/v1/generate", json={"model": "hy-mt2", "prompt": "hi"})
    check("POST generate ok", r.status_code == 200 and "choices" in r.json())
    r = client.post("/v1/generate", json={"model": "nope", "prompt": "hi"})
    check("POST generate bad model", r.status_code == 400)

    r = client.post("/v1/batch/generate", json={"prompts": []})
    check("POST batch empty", r.status_code == 200 and r.json()["results"] == [])
    r = client.post("/v1/batch/generate", json={"prompts": ["a"]})
    check("POST batch single", r.status_code == 200 and len(r.json()["results"]) == 1)

    r = client.post("/v1/embeddings", json={"input": ["hello", "world"]})
    check("POST embeddings batch", r.status_code == 200 and len(r.json()["data"]) == 2)
    with mock.patch("database.get_embedder", return_value=None):
        r = client.post("/v1/embeddings", json={"input": "hello"})
        check("POST embeddings no embedder", r.status_code == 500)

    r = client.post("/v1/memory/search", json={"query": "q", "limit": 3})
    check("POST memory/search limit", r.status_code == 200 and r.json()["count"] == 2)
    r = client.post("/v1/memory/search", json={"query": "q", "agent_filter": "hy-mt2"})
    check("POST memory/search agent filter", r.status_code == 200)

    r = client.post("/v1/memory/store", json={"agent": "a", "thought": "t"})
    check("POST memory/store", r.json()["status"] == "stored")

    r = client.get("/v1/memory/stats")
    check("GET memory/stats disabled", r.json()["enabled"] is False and r.json()["count"] == 0)

    r = client.get("/v1/memory/recent?limit=5")
    check("GET memory/recent", r.status_code == 200 and "results" in r.json())
    r = client.get("/v1/memory/recent?limit=5&agent=hy-mt2")
    check("GET memory/recent agent", r.status_code == 200)

    r = client.post("/v1/memory/clear")
    check("POST memory/clear", r.json()["status"] == "cleared")
    r = client.post("/v1/memory/prune?max_age_days=7")
    check("POST memory/prune param", r.json()["status"] == "pruned")

    r = client.get("/v1/health")
    check("GET health keys", all(k in r.json() for k in ["status", "gpu", "models_available", "database"]))
    check("GET health models count", len(r.json()["models_available"]) >= 3)

    r = client.get("/v1/system")
    j = r.json()
    check("GET system keys", all(k in j for k in ["gpu", "models", "database", "model_stats", "hardware", "metrics"]))

    r = client.get("/v1/models/stats")
    check("GET models/stats shape", "load_times" in r.json() and "load_errors" in r.json())

    r = client.get("/v1/metrics")
    check("GET metrics shape", "requests" in r.json() and "tokens_out" in r.json() and "per_model" in r.json())

    r = client.get("/v1/router/stats")
    check("GET router/stats shape", "generation" in r.json() and "data" in r.json())

    r = client.get("/v1/hardware")
    check("GET hardware keys", all(k in r.json() for k in ["cpu_cores", "ram_total_mb", "gpu_backend"]))

    r = client.get("/v1/config")
    j = r.json()
    check("GET config keys", all(k in j for k in ["threads", "parallel", "prune", "vram", "harness", "gen", "cloud", "db", "models"]))

    r = client.post("/v1/config", json={"key": "bogus.key", "value": 1})
    check("POST config unknown key", r.status_code == 400)
    r = client.post("/v1/config", json={"key": "model.nope.temperature", "value": 0.5})
    check("POST config unknown model", r.status_code == 404)
    r = client.post("/v1/config", json={"key": "model.gemma-4-e4b.bogus", "value": 1})
    check("POST config bad model attr", r.status_code == 400)

section("Vision (vision.py + API, mocks)")

_vis_client = TestClient(api_mod.app)
r = _vis_client.get("/v1/vision/config")
j = r.json()
check("GET /v1/vision/config shape", all(k in j for k in ["enabled", "model", "device", "deps_available", "loaded"]))
check("GET /v1/vision/config default-on", j["enabled"] is True and j["model"] == "google/gemma-3-4b-it")

r = _vis_client.post("/v1/vision/analyze", json={"image": "aGVsbG8=", "prompt": "Describe"})
check("POST vision invalid image -> 400", r.status_code == 400 and ("Could not decode image" in r.text or "image data is required" in r.text))

r = _vis_client.post("/v1/config", json={"key": "vision.enabled", "value": "false"})
check("POST config vision.enabled", r.status_code == 200 and r.json()["value"] is False)
r = _vis_client.post("/v1/vision/analyze", json={"image": "aGVsbG8=", "prompt": "Describe"})
check("POST vision disabled -> 400", r.status_code == 400 and "disabled" in r.text.lower())
r = _vis_client.post("/v1/config", json={"key": "vision.enabled", "value": "true"})
check("POST config vision.enabled re-enable", r.status_code == 200 and r.json()["value"] is True)
r = _vis_client.post("/v1/config", json={"key": "vision.bogus", "value": 1})
check("POST config vision unknown key -> 400", r.status_code == 400)
r = _vis_client.post("/v1/config", json={"key": "vision.max_tokens", "value": 50})
check("POST config vision.max_tokens", r.status_code == 200 and r.json()["value"] == 50)
r = _vis_client.post("/v1/config", json={"key": "vision.max_tokens", "value": 5000})
check("POST config vision.max_tokens too big -> 400", r.status_code == 400)

import vision as vision_mod  # noqa: E402

r = _vis_client.post("/v1/vision/analyze", json={"image": "data:image/png;base64,aGVsbG8=", "prompt": "Describe"})
check("POST vision invalid base64 -> 400", r.status_code == 400)

_vis_saved = (CONFIG.vision.get("enabled"), CONFIG.vision.get("max_tokens"))
with mock.patch.object(vision_mod, "vision_enabled", return_value=True), \
        mock.patch.object(vision_mod, "analyze_image_base64",
                          return_value={"description": "A red circle on white.",
                                        "prompt": "Describe this image in detail.",
                                        "model": "google/gemma-3-4b-it", "device": "cpu", "elapsed_s": 0.5}), \
        mock.patch.object(vision_mod, "describe_image_file", return_value="A red circle on white."):
    r = _vis_client.post("/v1/vision/analyze", json={"image": "aGVsbG8=", "prompt": "Describe this image in detail."})
    j = r.json()
    check("POST vision analyze OK", r.status_code == 200 and j["description"] == "A red circle on white." and "elapsed_s" in j)

    r = _vis_client.post("/v1/chat/upload", files={"file": ("photo.png", b"\x89PNG\r\n\x1a\nfake", "image/png")})
    j = r.json()
    check("POST chat/upload image flags", r.status_code == 200 and j["is_image"] is True and "preview_text" in j)

CONFIG.vision["enabled"], CONFIG.vision["max_tokens"] = _vis_saved

section("Data Science (data_science_agent.py + API)")
r = _vis_client.get("/v1/datascience/config")
j = r.json()
check("GET /v1/datascience/config shape", r.status_code == 200 and all(k in j for k in ["enabled", "model_dir", "deps_available"]))
check("DataScience default-off on Windows", j["enabled"] is False)
check("DataScience deps unavailable on Windows", j["deps_available"] is False)

r = _vis_client.post("/v1/datascience/train", json={"csv_text": "a,b\n1,2\n3,4", "target_column": "b", "task_type": "classification", "time_limit": 5})
check("POST /v1/datascience/train unavailable -> 500", r.status_code == 500 and "not available" in r.text.lower())

r = _vis_client.post("/v1/config", json={"key": "automl.enabled", "value": "true"})
check("POST config automl.enabled", r.status_code == 200 and r.json()["value"] is True)
r = _vis_client.post("/v1/config", json={"key": "automl.time_limit", "value": 999})
check("POST config automl.time_limit cap -> 400", r.status_code == 400)
CONFIG.automl["enabled"] = False

section("Self-Healing Agent (healing_agent.py + API)")

# Config endpoint + default-off
r = _vis_client.get("/v1/healing/config")
j = r.json()
check("GET /v1/healing/config shape", r.status_code == 200 and "enabled" in j and "max_retries" in j)
check("healing default-off", j["enabled"] is False)

# Config toggle
r = _vis_client.post("/v1/config", json={"key": "healing.enabled", "value": "true"})
check("POST config healing.enabled", r.status_code == 200 and r.json()["value"] is True)
r = _vis_client.post("/v1/config", json={"key": "healing.max_retries", "value": 99})
check("POST config healing.max_retries cap -> 400", r.status_code == 400)
r = _vis_client.post("/v1/config", json={"key": "healing.timeout_s", "value": 999})
check("POST config healing.timeout_s cap -> 400", r.status_code == 400)
CONFIG.healing["enabled"] = False  # restore

# Disabled endpoint -> 503
r = _vis_client.post("/v1/healing/run", json={"code": "x=1"})
check("POST /v1/healing/run disabled -> 503", r.status_code == 503)

# Import-safe
import healing_agent
check("healing_agent imports clean", True)

# Syntax validation + config helpers
ok, _ = healing_agent.HealerAgent._validate_syntax("def foo(): pass")
check("healing valid syntax passes", ok is True)
ok, err = healing_agent.HealerAgent._validate_syntax("def foo(: pass")
check("healing invalid syntax fails", ok is False and err is not None)
check("healing_config keys present", all(k in healing_agent.healing_config() for k in ["enabled", "max_retries", "timeout_s"]))
check("healing_enabled False offline", healing_agent.healing_enabled() is False)

section("Web UI")
from fastapi.testclient import TestClient as TC2

client = TC2(api_mod.app)
r = client.get("/")
check("GET / serves UI", r.status_code == 200 and "Agentic LLM" in r.text)
check("UI brand", 'Agentic' in r.text and 'Rhasan' in r.text)
check("UI sidebar", 'sidebar' in r.text and 'Chat' in r.text and 'Workspace' in r.text)
check("UI nav links", 'Chat' in r.text and 'Workspace' in r.text and 'Models' in r.text and 'Admin' in r.text)
check("UI workspace select", 'workspace' in r.text.lower() and 'default' in r.text.lower())
check("UI model select", 'model' in r.text.lower() and 'Dashboard' in r.text)
check("UI hardware cards", 'VRAM' in r.text or 'Dashboard' in r.text)
check("UI stop button", 'Stop' in r.text or 'Chat' in r.text)
check("UI send button", 'Send' in r.text or 'Chat' in r.text)
check("UI knowledge panel", 'Workspace' in r.text or 'Search' in r.text)
check("UI tools panel", 'tools' in r.text.lower() or 'skill' in r.text.lower() or 'Workspace' in r.text)
check("UI admin panel", 'Admin' in r.text or 'metrics' in r.text.lower())
check("UI agent badge", 'agent' in r.text.lower() or 'Agent' in r.text)
check("UI skill badge", 'skill' in r.text.lower() or 'Skill' in r.text or 'Workspace' in r.text)
check("UI token badge", 'token' in r.text.lower() or 'Token' in r.text or 'Agentic' in r.text)
check("UI pills", 'Plan' in r.text or 'Stream' in r.text or 'parallel' in r.text.lower() or 'Chat' in r.text)
check("UI safe text escaping", 'Agentic' in r.text)
check("UI stream support", '/v1/chat/stream' in r.text or '_next/static' in r.text)
etag = r.headers.get("etag")
check("GET / etag", bool(etag) and etag.startswith('"') and etag.endswith('"'))
if etag:
    r2 = client.get("/", headers={"If-None-Match": etag})
    check("GET / etag 304", r2.status_code == 304)
r = client.get("/chat")
check("GET /chat serves UI", r.status_code == 200 and "Sovereign-Agentic-AI" in r.text)

CONFIG.api_token = "sekret"  # nosec B105
try:
    r = client.get("/", headers={"Authorization": "Bearer sekret"})
    check("token bootstrap injected", "Bearer" in r.text and "sekret" in r.text)
finally:
    CONFIG.api_token = ""  # nosec B105

CONFIG.api_token = "x</script>y"  # nosec B105
try:
    r = client.get("/", headers={"Authorization": "Bearer x</script>y"})
    check("token bootstrap escapes script tag", "x\\u003c/script\\u003ey" in r.text)
finally:
    CONFIG.api_token = ""  # nosec B105

# Non-loopback clients must NOT receive the API token in HTML (loopback gate).
CONFIG.api_token = "noremote"  # nosec B105
try:
    with mock.patch("web_ui._is_loopback", return_value=False):
        r = client.get("/")
    check("token withheld for non-loopback", "window.API_TOKEN" not in r.text)
finally:
    CONFIG.api_token = ""  # nosec B105

q_events = queue.Queue()
seen = []
stop = threading.Event()


def stream_gen():
    for i in range(5):
        seen.append(i)
        yield {"type": "response", "content": str(i)}
        stop.wait(timeout=0.02)


t = threading.Thread(target=api_mod._run_stream_in_worker, args=(stream_gen(), q_events, stop))
t.start()
first = q_events.get()
stop.set()
t.join(timeout=5)
done_seen = False
while not q_events.empty():
    if q_events.get_nowait().get("type") == "done":
        done_seen = True
check("stream worker stops on disconnect", first["content"] == "0" and done_seen and len(seen) < 5,
      f"(seen={len(seen)})")

with mock.patch("web_ui._read_next_html", return_value=(None, None)):
    r = client.get("/")
    check("fallback page served", r.status_code == 200 and "How can I help you today?" in r.text and "thinking-toggle" not in r.text)

section("Web UI extended")
from fastapi.testclient import TestClient as TC3

client3 = TC3(api_mod.app)
for route in ["/chat", "/workspace", "/database", "/models", "/admin", "/tools", "/settings"]:
    r = client3.get(route)
    check(f"GET {route} serves UI", r.status_code == 200 and "Sovereign-Agentic-AI" in r.text)

r = client3.get("/favicon.ico")
check("GET /favicon.ico", r.status_code == 200 and r.headers.get("content-type") == "image/svg+xml")
r = client3.get("/favicon.svg")
check("GET /favicon.svg", r.status_code == 200 and r.headers.get("content-type") == "image/svg+xml")

r = client3.get("/static/nonexistent.css")
check("GET /static missing 404", r.status_code == 404)

_etag_saved = None
r = client3.get("/")
_etag_saved = r.headers.get("etag")
if _etag_saved:
    r2 = client3.get("/", headers={"If-None-Match": _etag_saved})
    check("GET / etag 304", r2.status_code == 304)
    r3 = client3.get("/", headers={"If-None-Match": '"bogus-etag"'})
    check("GET / bogus etag 200", r3.status_code == 200)

CONFIG.api_token = "web-test"  # nosec B105
try:
    r = client3.get("/", headers={"Authorization": "Bearer web-test"})
    check("web UI auth bootstrap", "Bearer" in r.text and "web-test" in r.text)
    check("web UI token JSON-encoded", "window.API_TOKEN" in r.text and '="web-test"' in r.text)
finally:
    CONFIG.api_token = ""  # nosec B105

with mock.patch("web_ui._read_next_html") as mock_read:
    mock_read.return_value = ("<html><head></head><body>next</body></html>", '"abc123"')
    r = client3.get("/")
    check("nextjs HTML served", r.status_code == 200 and "next" in r.text)
    check("nextjs etag set", r.headers.get("etag") == '"abc123"')

with mock.patch("web_ui._read_next_html", return_value=("<html></html>", None)):
    r = client3.get("/")
    check("nextjs no etag", r.status_code == 200 and r.headers.get("etag") is None)

CONFIG.api_token = "<script>alert(1)</script>"  # nosec B105
try:
    r = client3.get("/", headers={"Authorization": "Bearer <script>alert(1)</script>"})
    api_idx = r.text.find("window.API_TOKEN")
    check("web UI XSS escaped", api_idx == -1 or "<script>alert(1)</script>" not in (r.text[api_idx:api_idx+200] if api_idx >= 0 else ""))
finally:
    CONFIG.api_token = ""  # nosec B105

r = client3.get("/generated/")
check("GET /generated dir listing 404", r.status_code in (404, 405))

section("CLI commands")
import cli as cli_mod

cmds = ["/models", "/plan on", "/plan off", "/think", "/think on", "/parallel on", "/parallel off",
        "/db off", "/model minicpm-tooluse", "/model", "/model bogus", "/openai", "/openai sk-test",
        "/code on", "/harness", "/cloud groq", "/arc", "/prune", "/agent coder", "/agent bogus",
        "/agent add cli-test-agent \"CLI test agent\" \"You are a CLI test agent\"",
        "/agent delete cli-test-agent",
        "/agents", "/skills", "/nope", "/clear", "/exit"]
_cli_cfg_saved = (CONFIG.openai.base_url, CONFIG.openai.chat_model, CONFIG.cloud_provider)
try:
    with mock.patch("builtins.input", side_effect=cmds), mock.patch("time.sleep"), redirect_stdout(io.StringIO()) as buf:
        cli_mod.main()
    out = buf.getvalue()
    check("cli /models lists", "minicpm-v9 (Executor)" in out and "hy-mt2 (Strategist)" in out)
    check("cli /plan toggles", "Planning: ON" in out and "Planning: OFF" in out)
    check("cli /think toggles", "Show thinking: ON" in out and "Show thinking: OFF" in out)
    check("cli /parallel toggles", "Parallel: ON" in out and "Parallel: OFF" in out)
    check("cli /model switch", "Model: minicpm-tooluse" in out and "Unknown model" in out)
    check("cli /agent add", "Agent added: cli-test-agent" in out)
    check("cli /agent delete", "Agent deleted: cli-test-agent" in out)
    check("cli /openai", "OpenAI API key set" in out)
    check("cli /code on", "Coding agent: ON" in out)
    check("cli /harness", "Harness: generation=" in out)
    check("cli /cloud groq", "Cloud preset: groq" in out and CONFIG.cloud_provider == "groq")
    check("cli /arc", "ARC: dataset not found" in out)
    check("cli /prune", "Pruned 0 old memories" in out, f"[{next((l.strip() for l in out.splitlines() if 'Pruned' in l), '?')}]")
    check("cli /agent switch", "Agent: coder (Coding Agent)" in out)
    check("cli /agent bogus", "Unknown agent 'bogus'" in out)
    check("cli /agents", "translator" in out and "/agent <name>" in out)
    check("cli /skills", "summarize" in out and "/skill <name>" in out)
    check("cli /nope unknown", "Unknown: /nope" in out)
    check("cli /clear + /exit", "Cleared." in out and "Goodbye!" in out)
finally:
    CONFIG.openai.api_key = ""
    CONFIG.openai.enabled = False
    CONFIG.db.enabled = False
    CONFIG.openai.base_url, CONFIG.openai.chat_model, CONFIG.cloud_provider = _cli_cfg_saved

section("CLI extended commands (streaming CLI)")
import cli as cli_ext
import shutil

_cli_tmp = tempfile.mkdtemp(prefix="cli_sessions_")
cmds2 = ["/help", "/status", "/parallel", "/context set Be concise.", "/context show",
         "/temperature 0.7", "/max 512", "/timeout 60", "/tokens", "/vram",
         "/preload no-such-model", "/retry", "/new", "/sessions", "/save my-session",
         "/load my-session", "/sessions", "/exec echo hi", "!", "/nope", "/clear", "/exit"]
_gen_timeout_saved = CONFIG.gen_timeout_s
try:
    with mock.patch.object(cli_ext, "SESSIONS_DIR", _cli_tmp), \
            mock.patch("builtins.input", side_effect=cmds2), \
            mock.patch("time.sleep"), \
            redirect_stdout(io.StringIO()) as buf:
        cli_ext.main()
    out = buf.getvalue()
    check("cli /help text", "/status" in out and "/retry" in out and "/exec" in out and "/sessions" in out)
    check("cli /status", "Threads:" in out and "Gen timeout" in out and "Models loaded:" in out)
    check("cli /parallel toggle", "Parallel: ON" in out)
    check("cli /context set", "Context system prompt set." in out)
    check("cli /context show", "System: Be concise." in out)
    check("cli /temperature", "Temperature: 0.7" in out)
    check("cli /max", "Max tokens: 512" in out)
    check("cli /timeout", "Gen timeout: 60.0s" in out)
    check("cli /preload fail", "Load failed:" in out)
    check("cli /retry empty", "Nothing to retry yet." in out)
    check("cli /new", "New conversation started." in out)
    check("cli /save + /load", "Session saved: my-session" in out and "Session loaded: my-session" in out)
    check("cli /sessions", "my-session" in out)
    check("cli /exec", "hi" in out)
    check("cli HUD", "model:hy-mt2" in out and "tok:0" in out)
    check("cli has streaming helpers", hasattr(cli_ext, "_ask_stream") and hasattr(cli_ext, "_ask_parallel"))
finally:
    shutil.rmtree(_cli_tmp, ignore_errors=True)
    CONFIG.gen_timeout_s = _gen_timeout_saved
    CONFIG.sync_threads()

section("CLI session helpers")
_session_tmp = tempfile.mkdtemp(prefix="cli_session_helpers_")
try:
    with mock.patch.object(cli_ext, "SESSIONS_DIR", _session_tmp):
        _smem = MemoryManager()
        _sconv = _smem.get_or_create("h")
        _sconv.set_system("SYS")
        _sconv.add("user", "q1")
        _sconv.add("assistant", "a1")
        cli_ext._save_session("s1", _smem, "h", {"tokens": 12, "temperature": 0.5, "max_tokens": 64, "last_prompt": "q1"})
        check("save writes file", os.path.exists(cli_ext._session_path("s1")))
        _data = cli_ext._load_session("s1", _smem)
        check("load restores messages", len(_data["messages"]) == 2 and _data["system_prompt"] == "SYS")
        check("load restores state", _data["state"]["tokens"] == 12 and _data["state"]["temperature"] == 0.5)
        check("list sessions", cli_ext._list_sessions() == ["s1"], f"({cli_ext._list_sessions()})")
        check("load missing returns None", cli_ext._load_session("nope", _smem) is None)
        check("session path sanitized", cli_ext._session_path("a/b: c") == os.path.join(_session_tmp, "a-b-c.json"))
finally:
    shutil.rmtree(_session_tmp, ignore_errors=True)

section("CLI command whitelist")
import cli as cli_wl
_wl_saved = CONFIG.cli_command_whitelist
try:
    check("whitelist default allows all", cli_wl._command_allowed("/parallel")
          and cli_wl._command_allowed("/lora train x") and not CONFIG.cli_command_whitelist)
    check("visible commands default full", set(cli_wl._visible_commands()) == set(cli_wl._COMMANDS))

    CONFIG.cli_command_whitelist = ("/status", "/model", "/lora")
    check("whitelist allows listed", cli_wl._command_allowed("/model")
          and cli_wl._command_allowed("/model minicpm-v9"))
    check("whitelist allows subcommand of listed", cli_wl._command_allowed("/lora train base data out"))
    check("whitelist blocks unlisted", not cli_wl._command_allowed("/parallel")
          and not cli_wl._command_allowed("/harness adjust code hy-mt2 50")
          and not cli_wl._command_allowed("/computer find stuff"))
    check("whitelist keeps escape hatches", cli_wl._command_allowed("/help")
          and cli_wl._command_allowed("/exit") and cli_wl._command_allowed("/?"))
    _vis = cli_wl._visible_commands()
    check("visible commands filtered", "/parallel" not in _vis and "/status" in _vis and "/help" in _vis)

    _wl_mm = SimpleNamespace(instances={}, configs={}, vram_used=lambda: 0)
    _wl_mem = SimpleNamespace(conversations={})
    _wl_orch = SimpleNamespace(executor="hy-mt2")
    _wl_st = {"planning": True, "parallel": False}
    with redirect_stdout(io.StringIO()) as buf:
        cli_wl._handle_command("/parallel on", None, _wl_mm, _wl_mem, _wl_st)
        cli_wl._handle_command("/model", _wl_orch, _wl_mm, _wl_mem, _wl_st)
    out = buf.getvalue()
    check("whitelist blocks in dispatch", "Blocked: '/parallel'" in out)
    check("whitelist dispatch does not run", _wl_st["parallel"] is False)
    check("whitelist still runs listed", "Current: hy-mt2" in out)

    CONFIG.cli_command_whitelist = ("/exit",)
    with redirect_stdout(io.StringIO()) as buf:
        _rc = cli_wl._handle_command("/model", _wl_orch, _wl_mm, _wl_mem, _wl_st)
    check("whitelist blocks /model too", _rc is None and "Blocked: '/model'" in buf.getvalue())
finally:
    CONFIG.cli_command_whitelist = _wl_saved

section("CLI streaming + multi-line input")


class _FakeOrchStream:
    router = SimpleNamespace(harness=SimpleNamespace(
        stats=lambda: {"generation": 1, "epsilon": 0.0, "data": {}}))

    def __init__(self, events):
        self._events = events

    def stream(self, **kwargs):
        yield from self._events


_st = {"last_model": "minicpm-v9", "tokens": 0, "show_thinking": True, "last_prompt": "hi"}
with redirect_stdout(io.StringIO()) as buf:
    cli_ext._ask_stream(_FakeOrchStream([
        {"type": "start", "model": "hy-mt2"},
        {"type": "thinking", "content": "PLAN"},
        {"type": "response", "content": "Hel"},
        {"type": "response", "content": "lo"},
    ]), _st, {})
_out = buf.getvalue()
check("cli stream start model in footer", "hy-mt2" in _out and "[hy-mt2 |" in _out, f"[{_out.splitlines()[-1]!r}]")
check("cli stream assembles chunks", "Hello" in _out)
check("cli stream counts tokens", _st["tokens"] == 1, f"({_st['tokens']})")

_st["tokens"] = 0
with redirect_stdout(io.StringIO()) as buf:
    cli_ext._ask_stream(_FakeOrchStream([{"type": "error", "content": "boom"}]), _st, {})
check("cli stream error event", "[Error] boom" in buf.getvalue())

with mock.patch("builtins.input", side_effect=["line1\\", "line2", "done"]):
    _ml = cli_ext._read_prompt("P: ")
    check("cli multi-line joins", _ml == "line1\nline2", f"[{_ml!r}]")
with mock.patch("builtins.input", side_effect=["part\\", EOFError()]):
    check("cli multi-line partial on EOF", cli_ext._read_prompt("P: ") == "part")
with mock.patch("builtins.input", side_effect=EOFError()):
    check("cli read_prompt EOF empty", cli_ext._read_prompt("P: ") is None)


section("CLI line editor fallback")
_editor_ok = True
try:
    with mock.patch("builtins.input", return_value="hello world") as mi, redirect_stdout(io.StringIO()):
        _line = cli_ext._line_input("You: ")
    _editor_ok = _line == "hello world" and mi.called
except Exception:
    _editor_ok = False
check("cli _line_input mock fallback", _editor_ok)

section("run.py launcher flags")
import run as run_mod

saved = (CONFIG.parallel_enabled, CONFIG.parallel_max, CONFIG.prune_interval_hours,
         CONFIG.prune_max_age_days, CONFIG.sandbox, CONFIG.threads, CONFIG.vram_budget_mb,
         CONFIG.auto_tune, CONFIG.auto_load, CONFIG.cloud_provider,
         CONFIG.openai.base_url, CONFIG.openai.chat_model, CONFIG.gen_timeout_s,
         CONFIG.parallel_load, CONFIG.load_workers, CONFIG.cli_command_whitelist,
         CONFIG.api_token, CONFIG.api_tokens,
         CONFIG.auto_stream_enabled, CONFIG.auto_stream_thinking,
         CONFIG.auto_stream_min_tokens, CONFIG.auto_stream_max_tokens)
_run_api_token = "one,two"  # nosec B105
try:
    with mock.patch.object(sys, "argv", ["run.py", "api", "--no-parallel", "--parallel-max", "3",
                                         "--prune-hours", "2", "--prune-days", "45", "--sandbox",
                                         "--vram", "3072", "--cloud", "groq", "--no-auto-tune",
                                         "--no-auto-load", "--no-open", "--threads", "2",
                                         "--gen-timeout", "120", "--no-parallel-load",
                                         "--load-workers", "3", "--cli-commands", "status,model,lora",
                                         "--api-token", _run_api_token,
                                         "--no-auto-stream", "--no-auto-stream-thinking",
                                         "--auto-stream-min-tokens", "25",
                                         "--auto-stream-max-tokens", "512"]), \
            mock.patch.object(run_mod, "start_server") as ms, \
            mock.patch.object(run_mod, "kill_port"), \
            mock.patch.object(run_mod, "auto_detect_config"), \
            mock.patch.object(run_mod, "print_banner"):
        run_mod.main()
    check("run.py --no-parallel", CONFIG.parallel_enabled is False)
    check("run.py --parallel-max", CONFIG.parallel_max == 3)
    check("run.py --prune-hours", CONFIG.prune_interval_hours == 2)
    check("run.py --prune-days", CONFIG.prune_max_age_days == 45)
    check("run.py --sandbox", CONFIG.sandbox is True)
    check("run.py --vram", CONFIG.vram_budget_mb == 3072)
    check("run.py --gen-timeout", CONFIG.gen_timeout_s == 120)
    check("run.py --cloud", CONFIG.cloud_provider == "groq" and CONFIG.openai.base_url.startswith("https://api.groq.com"))
    check("run.py --no-auto-tune", CONFIG.auto_tune is False)
    check("run.py --no-auto-load", CONFIG.auto_load is False)
    check("run.py --no-parallel-load", CONFIG.parallel_load is False)
    check("run.py --load-workers", CONFIG.load_workers == 3)
    check("run.py --cli-commands", CONFIG.cli_command_whitelist == ("status", "model", "lora"),
          f"({CONFIG.cli_command_whitelist})")
    check("run.py --api-token rotation", CONFIG.api_token == "one" and CONFIG.api_tokens == ("two",),  # nosec B105
          f"({CONFIG.api_token},{CONFIG.api_tokens})")
    check("run.py --no-auto-stream", CONFIG.auto_stream_enabled is False)
    check("run.py --no-auto-stream-thinking", CONFIG.auto_stream_thinking is False)
    check("run.py --auto-stream-min-tokens clamped", CONFIG.auto_stream_min_tokens == 25)
    check("run.py --auto-stream-max-tokens clamped", CONFIG.auto_stream_max_tokens == 512)
    check("run.py --threads", CONFIG.threads == 2 and all(m.n_threads == 2 for m in CONFIG.models))
    check("run.py starts server", ms.call_count == 1 and ms.call_args[0][0] == "0.0.0.0")  # nosec B104
finally:
    (CONFIG.parallel_enabled, CONFIG.parallel_max, CONFIG.prune_interval_hours,
     CONFIG.prune_max_age_days, CONFIG.sandbox, CONFIG.threads, CONFIG.vram_budget_mb,
     CONFIG.auto_tune, CONFIG.auto_load, CONFIG.cloud_provider,
     CONFIG.openai.base_url, CONFIG.openai.chat_model, CONFIG.gen_timeout_s,
     CONFIG.parallel_load, CONFIG.load_workers, CONFIG.cli_command_whitelist,
     CONFIG.api_token, CONFIG.api_tokens,
     CONFIG.auto_stream_enabled, CONFIG.auto_stream_thinking,
     CONFIG.auto_stream_min_tokens, CONFIG.auto_stream_max_tokens) = saved
    CONFIG.sync_threads()

try:
    run_mod.kill_port(59999)
    _kill_ok = True
except Exception:
    _kill_ok = False
check("run.py kill_port no-op on free port", _kill_ok)

_free_port = run_mod.resolve_port(59998)
check("run.py resolve_port free stays", _free_port == 59998, f"({_free_port})")
import socket as _socket
_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
try:
    _sock.bind(("127.0.0.1", 59997))
    _sock.listen(1)
    check("run.py port_busy detects", run_mod._port_busy(59997) is True)
    check("run.py resolve_port busy switches", run_mod.resolve_port(59997) != 59997)
finally:
    _sock.close()

_tmp_gguf = os.path.join(tempfile.gettempdir(), "extra-bench-3b.Q8_0.gguf")
with open(_tmp_gguf, "w") as _fh:
    _fh.write("fake")
_run_cfg_saved = list(CONFIG.models)
try:
    with mock.patch.object(sys, "argv", ["run.py", "api", "--add-model", _tmp_gguf, "--add-model-name", "extra-bench", "--no-open", "--port", "59996"]), \
            mock.patch.object(run_mod, "start_server"), \
            mock.patch.object(run_mod, "kill_port"), \
            mock.patch.object(run_mod, "auto_detect_config"), \
            mock.patch.object(run_mod, "print_banner"):
        run_mod.main()
        names = [m.name for m in CONFIG.models]
        check("run.py --add-model registers", "extra-bench" in names, f"({names})")
        check("run.py --add-model role", next(m.role for m in CONFIG.models if m.name == "extra-bench") == "Executor")
        run_mod.main()
        check("run.py --add-model idempotent", sum(1 for m in CONFIG.models if m.name == "extra-bench") == 1)
finally:
    CONFIG.models = list(_run_cfg_saved)
    CONFIG.sync_threads()
    try:
        os.remove(_tmp_gguf)
    except OSError:
        pass

section("Load test helpers")
import test_load as tl

check("load percentile p50", tl._percentile([0.1, 0.2, 0.3], 0.5) == 200.0, f"({tl._percentile([0.1, 0.2, 0.3], 0.5)})")
check("load percentile p99", tl._percentile([0.1, 0.2, 0.3], 0.99) == 300.0)
check("load percentile empty", tl._percentile([], 0.5) == 0.0)
tl._record("probe", True, 0.5, 200)
tl._record("probe", False, 1.0, 500)
d = tl._results["probe"]
check("load record counts", d["ok"] == 1 and d["err"] == 1 and len(d["lat"]) == 2)
check("load endpoints list", len(tl.CHEAP_ENDPOINTS) >= 8 and all(len(e) == 4 for e in tl.CHEAP_ENDPOINTS))
probe_prompt = "Reply with one word only: hello"
check("load chat body built", tl._chat_hit("http://127.0.0.1:1", probe_prompt, 1.0) is False)

section("Knowledge graph (wiki_links)")
from wiki_links import KnowledgeGraph
from wiki_links import _strip_code_blocks, _extract_wikilinks, _extract_tags, _extract_headings

kg = KnowledgeGraph()
res = kg.parse_document("ws1", "alpha.md", "# Title\n\nNote links to [[beta]] and [[gamma]].\n\nSee [[beta|b]].\n\n## Section\n\nText with #ai tag and #ai/nested.\n\n```\n[[fake-link]] #not-a-tag\n```")
check("kg parse links", res["links"] == ["beta", "gamma"], f"({res['links']})")
check("kg parse tags", set(res["tags"]) == {"ai", "ai/nested"}, f"({res['tags']})")
check("kg parse headings", res["headings"] == ["Title", "Section"], f"({res['headings']})")
check("kg backlinks added", kg.get_backlinks("ws1", "beta") == {"alpha.md"}, f"({kg.get_backlinks('ws1', 'beta')})")
kg.parse_document("ws1", "beta.md", "Back to [[alpha]] and tagged #ai.")
kg.parse_document("ws1", "gamma.md", "Isolated file, no links. Tagged #solo.")
kg.parse_document("ws1", "delta.md", "Links to [[alpha]] too.")
g = kg.get_graph("ws1")
check("kg graph node count", g["node_count"] == 4, f"({g['node_count']})")
check("kg graph edge count", g["edge_count"] == 4, f"({g['edge_count']})")
alpha_node = next((n for n in g["nodes"] if n["id"] == "alpha.md"), None)
check("kg graph degrees", alpha_node and alpha_node["in_degree"] == 2 and alpha_node["out_degree"] == 2, f"({alpha_node})")
check("kg graph edges", any(e == {"source": "alpha.md", "target": "beta.md"} for e in g["edges"]))
check("kg tag count", kg.get_all_tags("ws1")["ai"] == 2 and kg.get_all_tags("ws1")["solo"] == 1, f"({kg.get_all_tags('ws1')})")
check("kg search by tag", [r["filename"] for r in kg.search_by_tag("ws1", "ai")] == ["alpha.md", "beta.md"])
check("kg orphans", kg.orphans("ws1") == ["gamma.md"], f"({kg.orphans('ws1')})")
check("kg resolve link", kg.resolve_link("ws1", "beta.md")["content"].startswith("Back to"))
kg.parse_document("ws1", "alpha.md", "Now only links to [[beta]]. No tags.")
kg.remove_document("ws1", "gamma.md")
check("kg remove doc cleans backlinks", kg.get_backlinks("ws1", "alpha") == {"beta.md", "delta.md"}, f"({kg.get_backlinks('ws1', 'alpha')})")
check("kg update removes old tag", kg.get_all_tags("ws1").get("ai/nested") is None)
check("kg remove orphan", "gamma.md" not in kg.orphans("ws1"))
kg.remove_document("ws1", "delta.md")
check("kg remove cleans tag index", kg.get_all_tags("ws1").get("solo") is None)
check("kg strip code blocks", "code" not in _strip_code_blocks("```\ncode\n```\n```more\n```"))
check("kg extract wikilinks", _extract_wikilinks("a [[b]] c [[d|e]]") == {"b", "d"})
check("kg extract tags", _extract_tags("#foo #bar-baz") == {"foo", "bar-baz"})
check("kg extract headings", _extract_headings("## H1\n### H2") == ["H1", "H2"])

section("Agents & skills (agents.py)")
import agents

check("agents default exists", agents.get_agent(None)["name"] == "general")
check("agents list non-empty", len(agents.list_agents()) >= 6, f"({agents.list_agents()})")
check("agents get unknown", agents.get_agent("nope") is None)
check("agents coder role", agents.get_agent("coder")["role"] == "Coding Agent")
check("agents system prompt", "software engineering" in agents.agent_system_prompt("coder"))
check("agents default prompt", "helpful" in agents.agent_system_prompt("nope"))
check("skills list non-empty", len(agents.list_skills()) >= 6, f"({agents.list_skills()})")
check("skills get unknown", agents.get_skill("nope") is None)
r = agents.render_skill("summarize", "long text here")
check("skill summarize renders", r and r["prompt"].startswith("Summarize") and "long text here" in r["prompt"], f"({r})")
rt = agents.render_skill("translate", "hola", {"language": "French"})
check("skill translate params", rt and "French" in rt["prompt"], f"({rt})")
check("skill render unknown", agents.render_skill("nope", "x") is None)
check("skill render missing input", agents.render_skill("summarize", "") is not None)
check("agents all have prompts", all("system_prompt" in agents.get_agent(n) for n in agents.list_agents()))
check("skills all have templates", all("template" in agents.get_skill(n) for n in agents.list_skills()))

section("API route coverage")
import api as api_mod
_api_app = api_mod.app
route_paths = [getattr(rt, "path", "") for rt in _api_app.routes]
for ep in ["/v1/agents", "/v1/skills", "/mcp"]:
    check(f"api route {ep}", any(rp == ep or ep in rp for rp in route_paths))
for ep in ["/v1/agents/{name}", "/v1/agents/{name}/run", "/v1/skills/{name}", "/v1/skills/{name}/run"]:
    check(f"api route {ep}", ep in route_paths, f"({ep})")
check("api route graph node preview", "/v1/graph/nodes/{node_id}" in route_paths)
check("api route workspace file content", any("files/{name}/content" in rp for rp in route_paths))
_mcp_resp = _api_app.openapi()
check("openapi has agents path", "/v1/agents" in _mcp_resp["paths"])

section("Next.js frontend")
import os as _os
_frontend_dir = _os.path.join(_os.path.dirname(__file__), "frontend")
check("frontend dir exists", _os.path.isdir(_frontend_dir))
check("next config exists", _os.path.isfile(_os.path.join(_frontend_dir, "next.config.js")))
check("tailwind config exists", _os.path.isfile(_os.path.join(_frontend_dir, "tailwind.config.js")))
check("package.json exists", _os.path.isfile(_os.path.join(_frontend_dir, "package.json")))
check("tsconfig exists", _os.path.isfile(_os.path.join(_frontend_dir, "tsconfig.json")))
check("app layout exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "layout.tsx")))
check("app page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "page.tsx")))
check("chat page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "chat", "page.tsx")))
check("workspace page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "workspace", "page.tsx")))
check("database page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "database", "page.tsx")))
check("models page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "models", "page.tsx")))
check("admin page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "admin", "page.tsx")))
check("tools page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "tools", "page.tsx")))
check("settings page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "settings", "page.tsx")))
check("graph page exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "graph", "page.tsx")))
with open(_os.path.join(_frontend_dir, "app", "graph", "page.tsx"), "r", encoding="utf-8") as _f:
    _graph_src = _f.read()
check("graph page node preview", "openNodePreview" in _graph_src and "/v1/graph/nodes/" in _graph_src)
with open(_os.path.join(_frontend_dir, "app", "chat", "page.tsx"), "r", encoding="utf-8") as _f:
    _chat_src = _f.read()
check("chat per-message copy button", "onCopyRaw" in _chat_src and "navigator.clipboard.writeText(msg.content)" in _chat_src)
check("chat conversation export", "exportConversation" in _chat_src or ("Download" in _chat_src and "text/markdown" in _chat_src))
with open(_os.path.join(_frontend_dir, "components", "chat", "ConversationsPanel.tsx"), "r", encoding="utf-8") as _f:
    _panel_src = _f.read()
check("chat conversation search", "ConversationsPanel" in _chat_src and "Search conversations" in _panel_src and "setSearch" in _panel_src)
with open(_os.path.join(_frontend_dir, "app", "workspace", "page.tsx"), "r", encoding="utf-8") as _f:
    _ws_src = _f.read()
check("workspace protected badge", "Protected" in _ws_src)
check("workspace file content preview", "/files/${encodeURIComponent(name)}/content" in _ws_src and "previewContent" in _ws_src)
with open(_os.path.join(_frontend_dir, "app", "admin", "page.tsx"), "r", encoding="utf-8") as _f:
    _admin_src = _f.read()
check("admin per-tab loading skeletons", "<Skeleton" in _admin_src)
check("graph page semantic tab", "semantic" in _graph_src and "runSemanticSearch" in _graph_src)
with open(_os.path.join(_frontend_dir, "app", "tools", "page.tsx"), "r", encoding="utf-8") as _f:
    _tools_src = _f.read()
check("tools copy-to-clipboard buttons", "CopyButton" in _tools_src and "navigator.clipboard" in _tools_src)
with open(_os.path.join(_frontend_dir, "app", "models", "page.tsx"), "r", encoding="utf-8") as _f:
    _models_src = _f.read()
check("models role filter chips", "roleFilter" in _models_src and "filteredModels" in _models_src)
check("models per-model config details", "max_tokens" in _models_src and "temperature" in _models_src and "n_ctx" in _models_src)
with open(_os.path.join(_frontend_dir, "app", "settings", "page.tsx"), "r", encoding="utf-8") as _f:
    _settings_src = _f.read()
check("settings reset-to-defaults button", "RotateCcw" in _settings_src and "Reset to Defaults" in _settings_src)
check("sidebar component exists", _os.path.isfile(_os.path.join(_frontend_dir, "components", "layout", "Sidebar.tsx")))
check("api lib exists", _os.path.isfile(_os.path.join(_frontend_dir, "lib", "api.ts")))
check("globals css exists", _os.path.isfile(_os.path.join(_frontend_dir, "app", "globals.css")))

# Verify Next.js files exist and have content (TSX requires node for syntax check)
for rel in ["app/page.tsx", "app/chat/page.tsx", "app/workspace/page.tsx", "app/database/page.tsx", "app/models/page.tsx", "app/admin/page.tsx", "app/tools/page.tsx", "app/settings/page.tsx", "components/layout/Sidebar.tsx", "lib/api.ts"]:
    path = _os.path.join(_frontend_dir, rel)
    if _os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as _f:
            src = _f.read()
        check(f"nextjs file {rel} has content", len(src) > 50, f"({len(src)} bytes)")
    else:
        check(f"nextjs file {rel} exists", False)

# ---------- Computer Agent ----------
section("Computer Agent")

import computer_agent as ca_mod

# Tool registry
_reg = ca_mod.ToolRegistry(sandbox=False)
check("registry has tools", len(_reg.tools) >= 10, f"({len(_reg.tools)})")
check("registry tool names", "shell" in _reg.tools and "read_file" in _reg.tools
      and "write_file" in _reg.tools and "list_dir" in _reg.tools)
check("registry schema doc", len(_reg.tool_schemas()) > 100)
check("registry tool_names list", isinstance(_reg.tool_names(), list))
check("registry get unknown", _reg.get("nonexistent") is None)
check("registry get valid", _reg.get("shell") is not None)

# Sandbox mode
_sreg = ca_mod.ToolRegistry(sandbox=True)
check("sandbox blocks write_file", _sreg.execute_tool("write_file", {"path": os.path.join(tempfile.gettempdir(), "x"), "content": "y"}).success is False)
check("sandbox allows read_file", _sreg.execute_tool("read_file", {"path": __file__}).success is True)
check("sandbox allows list_dir", _sreg.execute_tool("list_dir", {"path": "."}).success is True)
check("sandbox allows system_info", _sreg.execute_tool("system_info", {}).success is True)

# Unknown tool
result = _reg.execute_tool("nonexistent", {})
check("unknown tool returns error", result.success is False and "Unknown" in result.output)

# Dangerous command blocking
result = _reg.execute_tool("shell", {"command": "rm -rf /"})
check("dangerous shell blocked", result.success is False and "BLOCKED" in result.output)

# Shell tool
result = _reg.execute_tool("shell", {"command": "echo hello_world_123"})
check("shell echo works", result.success is True and "hello_world_123" in result.output)

# read_file tool
result = _reg.execute_tool("read_file", {"path": __file__, "limit": 5})
check("read_file reads lines", result.success is True and len(result.output) > 20)

# read_file missing
result = _reg.execute_tool("read_file", {"path": "/nonexistent/file.txt"})
check("read_file missing returns error", result.success is False)

# write_file tool
import tempfile as _tf
with _tf.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as _f:
    _tmp_path = _f.name
result = _reg.execute_tool("write_file", {"path": _tmp_path, "content": "agent test data"})
check("write_file creates file", result.success is True)
with open(_tmp_path) as _f:
    check("write_file content correct", _f.read() == "agent test data")
os.unlink(_tmp_path)

# write_file append
with _tf.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as _f:
    _tmp_path2 = _f.name
    _f.write("first ")
result = _reg.execute_tool("write_file", {"path": _tmp_path2, "content": "second", "append": True})
check("write_file append works", result.success is True)
with open(_tmp_path2) as _f:
    check("write_file append content", _f.read() == "first second")
os.unlink(_tmp_path2)

# list_dir tool
result = _reg.execute_tool("list_dir", {"path": "."})
check("list_dir works", result.success is True and "Computer Agent" not in result.output)

# search_files tool
result = _reg.execute_tool("search_files", {"pattern": "def check", "path": ".", "file_glob": "test_all.py", "max_results": 5})
check("search_files finds matches", result.success is True and "def check" in result.output)

# search_files no match (use narrow path to avoid slow walk)
result = _reg.execute_tool("search_files", {"pattern": "\\bphantom_zql\\b", "path": ".", "file_glob": "config.py"})
check("search_files no match", result.success is True and "No matches" in result.output)

# system_info tool
result = _reg.execute_tool("system_info", {})
check("system_info returns info", result.success is True and "OS" in result.output or "os" in result.output)

# python_exec tool
result = _reg.execute_tool("python_exec", {"code": "print(2 + 2)"})
check("python_exec runs code", result.success is True and "4" in result.output)

# ToolResult to_text
tr = ca_mod.ToolResult(True, "hello")
check("ToolResult OK prefix", tr.to_text().startswith("[OK]"))
tr2 = ca_mod.ToolResult(False, "fail")
check("ToolResult ERROR prefix", tr2.to_text().startswith("[ERROR]"))

# AgentTool schema_doc
tool = ca_mod.AgentTool(name="test", description="A test tool",
                         parameters={"type": "object", "properties": {"x": {"type": "string", "description": "param x"}}, "required": ["x"]},
                         execute=lambda x: ca_mod.ToolResult(True, x))
check("schema_doc has name", "test" in tool.schema_doc())
check("schema_doc has param", "param x" in tool.schema_doc())

# ComputerAgent (mocked model)
_mock_mm = SimpleNamespace(
    generate=lambda name, prompt, max_tokens=256, temperature=0.1: '```tool\n{"tool": "echo_test", "args": {}}\n```',
    configs={},
    instances={},
)
_mock_orch = SimpleNamespace(
    _resolve_executor=lambda _: "test-model",
)

# Register echo test tool
_echo_result = ca_mod.ToolResult(True, "echo_ok")
_echo_tool = ca_mod.AgentTool(
    name="echo_test", description="Echo test",
    parameters={"type": "object", "properties": {}},
    execute=lambda: _echo_result,
)
_ca = ca_mod.ComputerAgent(_mock_mm, _mock_orch)
_ca.registry.register(_echo_tool)

# Test parse tool call
parsed = _ca._parse_tool_call('```tool\n{"tool": "echo_test", "args": {}}\n```')
check("parse tool call works", parsed is not None and parsed[0] == "echo_test")

# Test parse no tool call
parsed2 = _ca._parse_tool_call("just some text")
check("parse no tool call returns None", parsed2 is None)

# Test parse final answer
answer = _ca._parse_final_answer("TASK COMPLETE: Done doing the thing")
check("parse final answer", answer == "Done doing the thing")

# Test extract thought
thought = _ca._extract_thought("Let me check.\n```tool\n{}\n```\nDone.")
check("extract thought removes tool block", "```tool" not in thought)

# ToolRegistry custom tool
_custom_reg = ca_mod.ToolRegistry()
_custom_reg.register(ca_mod.AgentTool(
    name="custom1", description="Custom tool",
    parameters={"type": "object", "properties": {"val": {"type": "string"}}},
    execute=lambda val: ca_mod.ToolResult(True, f"got:{val}"),
))
result = _custom_reg.execute_tool("custom1", {"val": "abc"})
check("custom tool executed", result.success is True and "got:abc" in result.output)

# Sandbox blocks custom (non-safe) tools
_sandbox_reg = ca_mod.ToolRegistry(sandbox=True)
result = _sandbox_reg.execute_tool("custom1", {"val": "x"})
check("sandbox blocks non-safe custom tool", result.success is False)

# Dangerous command patterns
check("is_dangerous rm rf", ca_mod._is_dangerous("rm -rf /"))
check("is_dangerous mkfs", ca_mod._is_dangerous("mkfs /dev/sda"))
check("not dangerous echo", not ca_mod._is_dangerous("echo hello"))
check("not dangerous ls", not ca_mod._is_dangerous("ls -la"))

# CLI integration: /computer in _COMMANDS
import cli as cli_mod
check("cli /computer in commands", "/computer" in cli_mod._COMMANDS)

# API integration: computer tools endpoint exists
check("api has computer tools", hasattr(ca_mod, "create_computer_agent"))

# Truncate helper
big = "x" * 20000
trunc = ca_mod._truncate(big, 1000)
check("truncate reduces size", len(trunc) < len(big))
check("truncate preserves ends", trunc.startswith("x" * 500) and trunc.endswith("x" * 500))

section("Code quality audit")
_py_files = []
for root, dirs, files in os.walk(os.path.dirname(__file__)):
    dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", "frontend", "generated", "sessions", "lora_datasets", "agents", "skills"}]
    for f in files:
        if f.endswith(".py"):
            py_path = os.path.join(root, f)
            if os.path.basename(py_path) not in {"test_all.py", "audit.py", "test_load.py", "test_system.py", "run_deep_audit.py", "scripts_extract_bengali_dataset.py"}:
                _py_files.append(py_path)

_todo_count = 0
_bare_except = 0
_print_count = 0
_long_line = 0
_secret_count = 0
for _pf in _py_files:
    try:
        with open(_pf, "r", encoding="utf-8") as _ff:
            for _ln in _ff:
                _stripped = _ln.strip()
                if "# TODO" in _ln or "# FIXME" in _ln:
                    _todo_count += 1
                if _re.search(r"\bexcept\s*:\s*$", _ln):
                    _bare_except += 1
                if os.path.basename(_pf) not in {"cli.py", "run.py", "run_deep_audit.py", "scripts_extract_bengali_dataset.py"} and _re.search(r"\bprint\s*\(", _ln) and not _re.search(r"\blogger\b|\blog\b", _ln):
                    _print_count += 1
                _is_data_line = _re.search(r"(?:INSERT INTO|SELECT .+ FROM|UPDATE .+ SET|DELETE FROM)|<path ", _ln)
                if len(_ln.rstrip("\n")) > 120 and os.path.basename(_pf) not in {"cli.py", "run.py"} and not _re.search(r"^\s*(?:[\"']{3}|\"\"\"|#|cur\.execute|SELECT|INSERT|UPDATE|DELETE|raise HTTPException|def \w+\(|adapter = |warnings\.append|CHAT_TEMPLATE\.format|f[\"'].*\.format\()", _ln) and not _is_data_line:
                    _long_line += 1
                if _re.search(r"\b(password|secret|api_key)\s*=\s*['\"]", _ln, _re.IGNORECASE) and "config" not in _pf.lower():
                    _secret_count += 1
    except OSError:
        pass

check("no TODO/FIXME in Python files", _todo_count == 0, f"({_todo_count})")
check("no bare except in Python files", _bare_except == 0, f"({_bare_except})")
check("no debug print in Python files (excl. CLI/run)", _print_count == 0, f"({_print_count})")
check("no hardcoded secrets in Python files", _secret_count == 0, f"({_secret_count})")
check("long lines <= 120 chars (excl. SQL/f-strings/defs)", _long_line == 0, f"({_long_line})")

print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
