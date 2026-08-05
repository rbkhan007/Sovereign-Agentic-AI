import logging
import re
import threading
import time as _time
from typing import Optional, List, Callable, Dict
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from models import (ModelManager, get_openai_client, _openai_can_call,
                     _openai_call_slot, _openai_backoff_delay,
                     _record_openai_failure)
from memory import MemoryManager, Conversation, CHAT_TEMPLATE
from config import CONFIG
from router import ModelRouter, classify_task
from metrics import metrics as _metrics
import database as db

logger = logging.getLogger(__name__)

_WEB_CACHE_TTL_S = 300
_WEB_CACHE_MAX = 64
_search_cache: dict = {}
_search_cache_lock = threading.Lock()


def _search_cache_get(key: str) -> Optional[str]:
    with _search_cache_lock:
        entry = _search_cache.get(key)
    if entry is None:
        return None
    if _time.time() - entry["ts"] > _WEB_CACHE_TTL_S:
        return None
    return entry["data"]


def _search_cache_put(key: str, data: str) -> None:
    now = _time.time()
    with _search_cache_lock:
        _search_cache[key] = {"ts": now, "data": data}
        if len(_search_cache) > _WEB_CACHE_MAX:
            for stale in sorted(
                _search_cache, key=lambda k: _search_cache[k]["ts"]
            )[: len(_search_cache) - _WEB_CACHE_MAX]:
                _search_cache.pop(stale, None)


def _ddg_search(query: str, max_results: int = 3) -> str:
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        results = []
        for r in ddgs.text(query, max_results=max_results):
            title = r.get('title', '').strip()
            body = r.get('body', '').strip()
            if body:
                results.append(f"• {title}\n  {body[:500]}")
            else:
                results.append(f"• {title}")
        if results:
            return "【Web Search Results】\n" + "\n\n".join(results) + "\n【End of Results】"
        return "No results found."


def search_web(query: str, max_results: int = 3) -> str:
    """Search DuckDuckGo with a TTL cache + one retry on transient failure."""
    key = f"{query}|{max_results}"
    cached = _search_cache_get(key)
    if cached is not None:
        return cached
    for attempt in range(2):
        try:
            data = _ddg_search(query, max_results)
            _search_cache_put(key, data)
            return data
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Web search failed (retrying): {e}")
                continue
            logger.warning(f"Web search failed: {e}")
            stale = _search_cache_get(key)
            if stale is not None:
                return stale
            return f"Search error: {e}"
    return "Search error: unavailable"

SYSTEM_PROMPT = (
    "You are a helpful, precise AI assistant. "
    "Follow instructions exactly. Be concise and direct. "
    "Do not repeat the question. Do not add extra commentary unless asked."
)
STRATEGIST_PROMPT = (
    "You are a planning assistant. Analyze the request step by step. "
    "Identify what is being asked, what information is needed, and the best approach. "
    "Keep your plan short and actionable. End with FINAL_ANSWER: followed by your plan summary."
)

THINK_MAX_TOKENS = 256
MAX_TOKENS_CAP = 8192


@dataclass
class PlanNode:
    content: str
    score: float = 0.0
    depth: int = 0


class Orchestrator:
    def __init__(self, model_manager: ModelManager, memory_manager: MemoryManager):
        self.models = model_manager
        self.memory = memory_manager
        self.executor = "hy-mt2"
        self.router = ModelRouter(model_manager)

    def _resolve_executor(self, model_override: Optional[str]) -> str:
        resolved = self.router.primary("general", model_override)
        if resolved:
            return resolved
        if model_override and model_override in self.models.configs:
            return model_override
        return self.executor

    def _generate_candidates(self, prompt: str, models: List[str], max_tokens: int,
                             temperature: Optional[float] = None) -> Dict[str, str]:
        results: Dict[str, str] = {}
        workers = min(len(models), 4)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(self.models.generate, m, prompt, max_tokens=max_tokens,
                                 temperature=temperature): m for m in models}
            for fut in as_completed(futures):
                m = futures[fut]
                try:
                    text = fut.result()
                    if text:
                        results[m] = text
                except Exception as e:
                    logger.warning(f"Parallel candidate {m} failed: {e}")
        return results

    def _judge_response(self, question: str, answer: str) -> float:
        try:
            prompt = (
                f"{CHAT_TEMPLATE.format(role='system', content='Rate the answer quality from 0 to 10. Reply with ONLY a number.')}\n"
                f"{CHAT_TEMPLATE.format(role='user', content=f'Q: {question[:1000]}\nA: {answer[:1500]}')}\n"
                f"<|im_start|>assistant\n"
            )
            text = self.models.generate("hy-mt2", prompt, max_tokens=16, temperature=0.0)
            m = re.search(r"\b(\d{1,2}(?:\.\d)?)\b", text or "")
            return min(float(m.group()), 10.0) if m else 5.0
        except Exception as e:
            logger.warning(f"Judge failed: {e}")
            return 5.0

    def _pick_best(self, question: str, candidates: Dict[str, str]) -> tuple:
        if len(candidates) <= 1:
            for m, t in candidates.items():
                return t, m
            return "", ""
        if CONFIG.parallel_judge and "hy-mt2" in self.models.configs:
            scores = {m: self._judge_response(question, t) for m, t in candidates.items()}
        else:
            scores = {m: (len(t) if len(t) > 20 else len(t) * 0.5) for m, t in candidates.items()}
        best = max(scores, key=lambda k: scores[k])
        logger.info(f"[Parallel] judged {len(candidates)} candidates, best={best} score={scores[best]:.1f}")
        return candidates[best], best

    def _build_exec_prompt(self, conv, thinking: str, web_context: str = "") -> str:
        blocks = [conv.get_context(open_assistant=False)]
        if web_context:
            blocks.append(CHAT_TEMPLATE.format(role="system", content=web_context))
        if thinking:
            blocks.append(CHAT_TEMPLATE.format(role="system",
                                               content=f"Plan: {thinking.strip()}"))
        blocks.append("<|im_start|>assistant\n")
        return "\n".join(blocks)

    def run(
        self,
        user_message: str,
        conv_id: str = "default",
        use_planning: bool = True,
        system_override: Optional[str] = None,
        model_override: Optional[str] = None,
        thinking_callback: Optional[Callable[[str], None]] = None,
        parallel: Optional[bool] = None,
        sandbox: Optional[bool] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        workspace_id: str = "default",
    ) -> dict:
        parallel = CONFIG.parallel_enabled if parallel is None else parallel
        if sandbox is None:
            sandbox = bool(getattr(CONFIG, "sandbox", False))
        max_tokens = min(max_tokens or 2048, MAX_TOKENS_CAP)
        if sandbox:
            conv = Conversation()
        else:
            conv = self.memory.get_or_create(conv_id, workspace_id)
        if system_override:
            conv.set_system(system_override)
        elif conv.system_prompt is None:
            conv.set_system(SYSTEM_PROMPT)
        conv.add("user", user_message)

        model = model_override or self.executor
        if model.startswith("openai/"):
            try:
                return self._call_openai(conv, model, max_tokens=max_tokens)
            except Exception:
                conv.messages.pop()
                raise

        exec_model = self._resolve_executor(model_override)
        logger.info(
            f"[Orchestrator] parallel={parallel} "
            f"model_override={model_override or 'none'} exec_model={exec_model}"
        )

        thinking = ""
        response = None
        memories = []
        parallel_count = 0

        if not sandbox and CONFIG.db.enabled:
            try:
                memories = db.retrieve_similar(user_message)
                if workspace_id and workspace_id != "default":
                    ws_mem = db.search_workspace_knowledge(workspace_id, user_message)
                    known = set(memories)
                    for m in ws_mem:
                        text = m.get("thought") if isinstance(m, dict) else str(m)
                        if text and text not in known:
                            memories.append(text)
                            known.add(text)
                # Graph-augmented retrieval: vector candidates + linked/backlinked nodes
                try:
                    import graph_store
                    graph_hits = graph_store.hybrid_search(user_message, limit=3,
                                                           workspace_id=workspace_id)
                    known = set(memories)
                    for hit in graph_hits:
                        for kind in ("linked", "backlinked"):
                            for linked in hit.get(kind, []):
                                text = linked.get("title") or ""
                                if text and text not in known:
                                    memories.append(text)
                                    known.add(text)
                except Exception:
                    logger.warning("Graph hybrid retrieval failed", exc_info=True)
            except Exception:
                logger.warning("Memory retrieval failed", exc_info=True)

        web_context = ""
        if CONFIG.web_search_enabled:
            search_triggers = ["news", "weather", "current", "latest", "today",
                               "who is", "what is", "when did", "how to",
                               "live", "breaking", "update"]
            if any(kw in user_message.lower() for kw in search_triggers):
                logger.info(f"[Web Search] Triggered: {user_message[:60]}...")
                web_context = search_web(user_message, max_results=3)
                if web_context and "error" not in web_context.lower() and "no results" not in web_context.lower():
                    logger.info(f"[Web Search] Injected {len(web_context)} chars into request context")
                else:
                    web_context = ""

        if use_planning and "hy-mt2" in self.models.configs:
            thinking = self._select_best_plan(user_message, memories, thinking_callback)
            if not CONFIG.auto_load and "hy-mt2" in self.models.instances and exec_model != "hy-mt2":
                self.models.unload("hy-mt2")

        task, ranked = self.router.select_executors(user_message, CONFIG.parallel_max, model_override)

        exec_prompt = self._build_exec_prompt(conv, thinking, web_context)

        if exec_model not in self.models.configs:
            conv.messages.pop()
            raise RuntimeError("No model available")

        _metrics.record_request(task=task, model=exec_model, tokens_in=len(user_message.split()))
        gen_start = _time.time()
        try:
            if CONFIG.auto_load and hasattr(self.models, "ensure_loaded"):
                keep = ["hy-mt2"] if (use_planning and "hy-mt2" in self.models.configs) else []
                target = ([exec_model] + [n for n in ranked if n != exec_model]) if parallel else [exec_model]
                self.models.ensure_loaded(target, keep=keep)
            if parallel:
                executors = ranked or [exec_model]
                if exec_model not in executors:
                    executors = [exec_model] + executors
                candidates = self._generate_candidates(exec_prompt, executors,
                                                       max_tokens=max_tokens or 2048,
                                                       temperature=temperature)
                if candidates:
                    response, exec_model = self._pick_best(user_message, candidates)
                    parallel_count = len(candidates)
            if response is None:
                response = self.models.generate(exec_model, exec_prompt,
                                                max_tokens=max_tokens or 2048,
                                                temperature=temperature)
            _metrics.record_completion(task=task, ok=True)
            self.router.harness.record(task, exec_model, True,
                                       latency=_time.time() - gen_start,
                                       tokens=len(response.split()))
        except Exception as e:
            _metrics.record_completion(task=task, ok=False)
            self.router.harness.record(task, exec_model, False)
            logger.error(f"{exec_model} failed: {e}")
            if CONFIG.openai.enabled:
                try:
                    return self._call_openai(conv, f"openai/{CONFIG.openai.chat_model}", max_tokens=max_tokens)
                except Exception as oe:
                    logger.error(f"OpenAI fallback failed: {oe}")
            conv.messages.pop()
            raise RuntimeError(f"Generation failed: {e}") from e
        finally:
            if not CONFIG.auto_load:
                if exec_model in self.models.instances:
                    self.models.unload(exec_model)
                if "hy-mt2" in self.models.configs and exec_model != "hy-mt2":
                    if "hy-mt2" in self.models.instances:
                        self.models.unload("hy-mt2")

        conv.add("assistant", response)

        if not sandbox and CONFIG.db.enabled and response:
            try:
                db.store_thought(exec_model, f"Q: {user_message}\nA: {response[:1000]}")
            except Exception:
                logger.warning("Memory store failed", exc_info=True)

        result = {"thinking": thinking, "response": response, "model": exec_model}
        if parallel_count:
            result["parallel_candidates"] = parallel_count
        return result

    def stream(
        self,
        user_message: str,
        conv_id: str = "default",
        use_planning: bool = True,
        system_override: Optional[str] = None,
        model_override: Optional[str] = None,
        thinking_callback: Optional[Callable[[str], None]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        workspace_id: str = "default",
        sandbox: Optional[bool] = None,
    ):
        max_tokens = min(max_tokens or 2048, MAX_TOKENS_CAP)
        if sandbox is None:
            sandbox = bool(getattr(CONFIG, "sandbox", False))
        if sandbox:
            conv = Conversation()
        else:
            conv = self.memory.get_or_create(conv_id, workspace_id)
        if system_override:
            conv.set_system(system_override)
        elif conv.system_prompt is None:
            conv.set_system(SYSTEM_PROMPT)
        conv.add("user", user_message)

        model = model_override or self.executor
        if model.startswith("openai/"):
            yield {"type": "start", "model": model}
            try:
                result = self._call_openai(conv, model, max_tokens=max_tokens)
                yield {"type": "response", "content": result["response"]}
                yield {"type": "done", "model": model,
                       "tokens": len(result["response"].split()), "elapsed": 0.0}
                return
            except Exception:
                conv.messages.pop()
                yield {"type": "error", "content": "OpenAI call failed"}
                return

        exec_model = self._resolve_executor(model_override)
        yield {"type": "start", "model": exec_model}

        memories = []
        if not sandbox and CONFIG.db.enabled:
            try:
                memories = db.retrieve_similar(user_message)
                if workspace_id and workspace_id != "default":
                    ws_mem = db.search_workspace_knowledge(workspace_id, user_message)
                    known = set(memories)
                    for m in ws_mem:
                        text = m.get("thought") if isinstance(m, dict) else str(m)
                        if text and text not in known:
                            memories.append(text)
                            known.add(text)
                try:
                    import graph_store
                    graph_hits = graph_store.hybrid_search(user_message, limit=3,
                                                           workspace_id=workspace_id)
                    known = set(memories)
                    for hit in graph_hits:
                        for kind in ("linked", "backlinked"):
                            for linked in hit.get(kind, []):
                                text = linked.get("title") or ""
                                if text and text not in known:
                                    memories.append(text)
                                    known.add(text)
                except Exception:
                    logger.warning("Graph hybrid retrieval failed (stream)", exc_info=True)
            except Exception:
                logger.warning("Memory retrieval failed (stream)", exc_info=True)

        web_context = ""
        if CONFIG.web_search_enabled:
            search_triggers = ["news", "weather", "current", "latest", "today",
                               "who is", "what is", "when did", "how to",
                               "live", "breaking", "update"]
            if any(kw in user_message.lower() for kw in search_triggers):
                logger.info(f"[Web Search] Triggered: {user_message[:60]}...")
                web_context = search_web(user_message, max_results=3)
                if web_context and "error" not in web_context.lower() and "no results" not in web_context.lower():
                    logger.info(f"[Web Search] Injected {len(web_context)} chars into request context")
                else:
                    web_context = ""

        thinking = ""
        if use_planning and "hy-mt2" in self.models.configs:
            thinking = self._select_best_plan(user_message, memories, thinking_callback)
            if not CONFIG.auto_load and "hy-mt2" in self.models.instances and exec_model != "hy-mt2":
                self.models.unload("hy-mt2")
        if thinking:
            yield {"type": "thinking", "content": thinking}

        task = classify_task(user_message)
        exec_prompt = self._build_exec_prompt(conv, thinking, web_context)

        parts = []
        if exec_model in self.models.configs:
            _metrics.record_request(task=task, model=exec_model, tokens_in=len(user_message.split()))
            gen_start = _time.time()
            try:
                if CONFIG.auto_load and hasattr(self.models, "ensure_loaded"):
                    self.models.ensure_loaded([exec_model])
                for chunk in self.models.generate_stream(exec_model, exec_prompt,
                                                         max_tokens=max_tokens or 2048,
                                                         temperature=temperature):
                    if chunk:
                        parts.append(chunk)
                        yield {"type": "response", "content": chunk}
                _metrics.record_completion(task=task, ok=True)
                self.router.harness.record(task, exec_model, True,
                                           latency=_time.time() - gen_start,
                                           tokens=len("".join(parts).split()))
            except Exception as e:
                _metrics.record_completion(task=task, ok=False)
                self.router.harness.record(task, exec_model, False)
                logger.error(f"{exec_model} stream failed: {e}")
                if CONFIG.openai.enabled:
                    try:
                        result = self._call_openai(conv, f"openai/{CONFIG.openai.chat_model}", max_tokens=max_tokens)
                        yield {"type": "response", "content": result["response"]}
                        return
                    except Exception as oe:
                        logger.error(f"OpenAI fallback failed: {oe}")
                conv.messages.pop()
                yield {"type": "error", "content": str(e)}
                return
            finally:
                if not CONFIG.auto_load:
                    if exec_model in self.models.instances:
                        self.models.unload(exec_model)
                    if "hy-mt2" in self.models.configs and exec_model != "hy-mt2":
                        if "hy-mt2" in self.models.instances:
                            self.models.unload("hy-mt2")
        else:
            conv.messages.pop()
            yield {"type": "error", "content": "No model available"}
            return

        response = "".join(parts)
        conv.add("assistant", response)

        if not sandbox and CONFIG.db.enabled and response:
            try:
                db.store_thought(exec_model, f"Q: {user_message}\nA: {response[:500]}")
            except Exception:
                logger.warning("Memory store failed (stream)", exc_info=True)

        yield {"type": "done", "model": exec_model,
               "tokens": len(response.split()),
               "elapsed": round(_time.time() - gen_start, 3)}

    def _should_auto_stream(self, user_message: str, use_planning: bool,
                            max_tokens: Optional[int] = None) -> bool:
        """Auto-detect whether streaming is appropriate for this request.

        Streams when planning is enabled, the message is long, or the content is
        code/creative. Falls back to batch generation when the answer is expected
        to be very short, or when auto-streaming is disabled in the config.
        """
        if not CONFIG.auto_stream_enabled:
            return False
        cap = max_tokens or CONFIG.auto_stream_max_tokens
        if cap < CONFIG.auto_stream_min_tokens:
            return False
        if use_planning:
            return True
        if len(user_message) > 100:
            return True
        text = user_message.lower()
        code_keywords = ("code", "function", "python", "javascript", "typescript",
                         "react", "api", "script", "program", "algorithm")
        creative_keywords = ("story", "poem", "essay", "write", "describe", "explain")
        if any(kw in text for kw in code_keywords):
            return True
        if any(kw in text for kw in creative_keywords):
            return True
        return False

    def auto_stream(
        self,
        user_message: str,
        conv_id: str = "default",
        use_planning: bool = True,
        system_override: Optional[str] = None,
        model_override: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        workspace_id: str = "default",
        sandbox: Optional[bool] = None,
        stream_thoughts: bool = True,
    ):
        """Auto-agentic streaming: picks streaming or batch per request.

        Streams real-time thinking + tokens when `_should_auto_stream` says yes,
        otherwise falls back to the batch `run()` pipeline and wraps its result
        in the same event protocol:
          {"type": "start" | "thinking" | "response" | "done" | "error", ...}
        """
        if sandbox is None:
            sandbox = bool(getattr(CONFIG, "sandbox", False))
        # Apply the documented hard cap for auto-streamed requests.
        if max_tokens is None or max_tokens > CONFIG.auto_stream_max_tokens:
            max_tokens = CONFIG.auto_stream_max_tokens
        if not self._should_auto_stream(user_message, use_planning, max_tokens):
            yield {"type": "start", "model": model_override or self.executor}
            start = _time.time()
            try:
                result = self.run(
                    user_message=user_message,
                    conv_id=conv_id,
                    use_planning=use_planning,
                    system_override=system_override,
                    model_override=model_override,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    workspace_id=workspace_id,
                    sandbox=sandbox,
                    parallel=False,
                )
            except Exception as e:
                logger.error(f"[auto_stream] batch fallback failed: {e}")
                yield {"type": "error", "content": str(e)}
                return
            if result.get("thinking"):
                yield {"type": "thinking", "content": result["thinking"]}
            yield {"type": "response", "content": result["response"]}
            yield {"type": "done", "model": result["model"],
                   "tokens": len(result["response"].split()),
                   "elapsed": round(_time.time() - start, 3)}
            return

        for evt in self.stream(
            user_message=user_message,
            conv_id=conv_id,
            use_planning=use_planning,
            system_override=system_override,
            model_override=model_override,
            temperature=temperature,
            max_tokens=max_tokens,
            workspace_id=workspace_id,
            sandbox=sandbox,
        ):
            if evt.get("type") == "thinking" and not stream_thoughts:
                continue
            if evt.get("type") == "thinking" and not CONFIG.auto_stream_thinking:
                continue
            yield evt

    def _select_best_plan(self, user_message: str, memories: list, callback: Optional[Callable] = None) -> str:
        mem_context = ""
        if memories:
            mem_context = "Relevant memories:\n" + "\n".join(f"- {m[:200]}" for m in memories)

        candidates = []
        planners = []
        if "hy-mt2" in self.models.configs:
            planners = ["hy-mt2"]
        elif self.executor and self.executor in self.models.configs:
            planners = [self.executor]
        for i in range(2):
            for planner in planners:
                try:
                    plan_prompt = (
                        f"{CHAT_TEMPLATE.format(role='system', content=STRATEGIST_PROMPT)}\n"
                        f"{CHAT_TEMPLATE.format(role='user', content=user_message)}\n"
                        f"<|im_start|>assistant\n"
                    )
                    if mem_context:
                        plan_prompt = (
                            f"{CHAT_TEMPLATE.format(role='system', content=mem_context)}\n"
                            f"{plan_prompt}"
                        )
                    text = self.models.generate(
                        planner,
                        plan_prompt,
                        max_tokens=THINK_MAX_TOKENS,
                        temperature=0.3 + (i * 0.1),
                        stop=["<|im_end|>", "\n\n\n"],
                    )
                    if text:
                        score = len(text)
                        if "FINAL_ANSWER" in text.upper():
                            score += 10
                        if len(text) > 50:
                            score += 5
                        candidates.append(PlanNode(content=text, score=score))
                except Exception as e:
                    logger.warning(f"Plan {i} failed with {planner}: {e}")

        if not candidates:
            return ""

        candidates.sort(key=lambda n: n.score, reverse=True)
        best = candidates[0].content

        if best and callback:
            callback(best)

        logger.info(f"[Plan] planner={planners[0] if planners else 'none'} chars={len(best)}")
        return best

    def _call_openai(self, conv, model_name: str, max_tokens: Optional[int] = None) -> dict:
        client = get_openai_client()
        if not client:
            raise RuntimeError("OpenAI not configured")
        model = model_name.replace("openai/", "") or CONFIG.openai.chat_model
        try:
            if not _openai_can_call():
                delay = _openai_backoff_delay()
                logger.warning(f"OpenAI rate limit reached; backing off {delay:.1f}s")
                _time.sleep(delay)
                if not _openai_can_call():
                    raise RuntimeError("OpenAI rate limit exceeded (too many fallback calls)")
            _openai_call_slot()
            resp = client.chat.completions.create(
                model=model,
                messages=conv.to_openai_format(),
                max_tokens=min(max_tokens or 2048, MAX_TOKENS_CAP),
            )
            text = resp.choices[0].message.content.strip()
            conv.add("assistant", text)
            return {"thinking": "", "response": text, "model": model}
        except Exception as e:
            _record_openai_failure()
            logger.error(f"OpenAI call failed: {e}")
            raise RuntimeError(f"OpenAI call failed: {e}") from e
