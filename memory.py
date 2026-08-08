import time
import threading
from typing import List, Dict, Optional


CHAT_TEMPLATE = "<|im_start|>{role}\n{content}<|im_end|>"

_MAX_CONVS = 500


class Message:
    def __init__(self, role: str, content: str, timestamp: Optional[float] = None):
        self.role = role
        self.content = content
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> Dict:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


class Conversation:
    def __init__(self, max_history: int = 100, workspace_id: str = "default"):
        self.messages: List[Message] = []
        self.max_history = max_history
        self.system_prompt: Optional[str] = None
        self.created_at: float = time.time()
        self.workspace_id: str = workspace_id
        self._lock = threading.Lock()
        self._persist = None  # Optional[Callable[[str, dict], None]] write-through hook

    def set_system(self, prompt: str):
        self.system_prompt = prompt
        if self._persist:
            try:
                self._persist("system", {"prompt": prompt})
            except Exception:
                pass

    def add(self, role: str, content: str):
        with self._lock:
            self.messages.append(Message(role, content))
            if len(self.messages) > self.max_history:
                self.messages = self.messages[-self.max_history:]
        if self._persist:
            try:
                self._persist("add", {"role": role, "content": content})
            except Exception:
                pass

    def get_context(self, include_system: bool = True, open_assistant: bool = True,
                    max_chars: Optional[int] = None,
                    max_msgs: Optional[int] = None) -> str:
        """Render the chat context as a prompt block.

        When ``max_chars`` is given, oldest messages are dropped until the
        rendered block fits, so multi-turn conversations cannot overflow the
        model context window. ``max_msgs`` additionally caps the number of
        retained messages (used after older turns have been summarized).
        """
        with self._lock:
            role_map = {"user": "user", "assistant": "assistant"}
            msgs = [CHAT_TEMPLATE.format(role=role_map.get(m.role, m.role), content=m.content)
                    for m in self.messages]
            if max_msgs is not None and len(msgs) > max_msgs:
                msgs = msgs[-max_msgs:]
            while max_chars is not None and len(msgs) > 2:
                joined = "\n".join(msgs)
                if len(joined) <= max_chars:
                    break
                msgs.pop(0)
            parts = []
            if include_system and self.system_prompt:
                parts.append(CHAT_TEMPLATE.format(role="system", content=self.system_prompt))
            parts.extend(msgs)
            if open_assistant:
                parts.append("<|im_start|>assistant\n")
            return "\n".join(parts)

    def to_openai_format(self, max_msgs: Optional[int] = None) -> List[Dict]:
        with self._lock:
            msgs = []
            if self.system_prompt:
                msgs.append({"role": "system", "content": self.system_prompt})
            history = self.messages
            if max_msgs is not None and len(history) > max_msgs:
                history = history[-max_msgs:]
            for msg in history:
                msgs.append({"role": msg.role, "content": msg.content})
            return msgs

    def clear(self):
        with self._lock:
            self.messages.clear()
            self.system_prompt = None
        if self._persist:
            try:
                self._persist("clear", {})
            except Exception:
                pass

    def rollback_to(self, index: int):
        """Drop any messages appended after ``index`` (concurrency-safe).

        Used to undo the user turn when generation fails. Because the index is
        captured before the user message is added, a concurrent request sharing
        this conversation can never pop another thread's message. The DB
        compensation deletes rows at-or-after the first rolled-back message's
        in-memory timestamp (the DB row timestamps are written strictly later,
        so the last kept message is never over-deleted).
        """
        removed_ts = 0.0
        with self._lock:
            if 0 <= index < len(self.messages):
                removed_ts = self.messages[index].timestamp or 0.0
                del self.messages[index:]
            else:
                return
        if self._persist:
            try:
                self._persist("rollback", {"after_ts": removed_ts})
            except Exception:
                pass


class MemoryManager:
    def __init__(self):
        self.conversations: Dict[str, Conversation] = {}
        self._access: Dict[str, float] = {}
        self._workspace_index: Dict[str, set] = {}
        self._lock = threading.Lock()

    def _db(self):
        """Return the database module when DB-backed conversations are live,
        else None. Cheap: checks the pool without attempting a connection."""
        try:
            import database as _db
            if _db.db_ready():
                return _db
        except Exception:
            pass
        return None

    def _make_persist(self, conv_id: str, conv: "Conversation"):
        """Build a write-through hook that persists conversation changes to DB.
        Returns None when the DB is unavailable (in-memory fallback). Reads the
        conversation's current workspace so reassigns stay consistent."""
        db = self._db()
        if db is None:
            return None

        def _persist(event: str, data: dict):
            try:
                ws = conv.workspace_id
                if event == "add":
                    db.append_conversation_message(
                        conv_id, ws, data.get("role") or "user", data.get("content") or ""
                    )
                elif event == "system":
                    db.save_conversation(conv_id, ws, system_prompt=data.get("prompt"))
                elif event == "rollback":
                    db.delete_conversation_messages_after(
                        conv_id, data.get("after_ts") or 0.0
                    )
                elif event == "clear":
                    db.clear_conversation_messages(conv_id)
            except Exception:
                pass

        return _persist

    def _evict_if_needed(self):
        while len(self.conversations) >= _MAX_CONVS:
            if self._access:
                oldest = min(self._access, key=self._access.get)
                self._access.pop(oldest, None)
                conv = self.conversations.pop(oldest, None)
                if conv:
                    ws_set = self._workspace_index.get(conv.workspace_id)
                    if ws_set:
                        ws_set.discard(oldest)
                        if not ws_set:
                            self._workspace_index.pop(conv.workspace_id, None)
            else:
                break

    def get(self, conv_id: str) -> Optional[Conversation]:
        """Return the conversation for a conv_id if it exists (hydrating from
        DB when available), else None. Does not create a conversation."""
        with self._lock:
            conv = self.conversations.get(conv_id)
        if conv is not None:
            return conv
        conv = self._load_from_db(conv_id)
        if conv is None:
            return None
        with self._lock:
            existing = self.conversations.get(conv_id)
            if existing is not None:
                return existing
            self._access[conv_id] = time.time()
            self.conversations[conv_id] = conv
            self._workspace_index.setdefault(conv.workspace_id, set()).add(conv_id)
        return conv

    def _build_from_data(self, conv_id: str, data: dict) -> Conversation:
        """Rebuild an in-memory Conversation from a DB row (no registration)."""
        ws = data.get("workspace_id") or "default"
        conv = Conversation(workspace_id=ws)
        conv.system_prompt = data.get("system_prompt") or None
        conv.created_at = data.get("created_at") or conv.created_at
        for m in data.get("messages") or []:
            conv.messages.append(Message(m.get("role"), m.get("content"), m.get("timestamp")))
        conv._persist = self._make_persist(conv_id, conv)
        return conv

    def _load_from_db(self, conv_id: str) -> Optional[Conversation]:
        """Try to load a conversation from the DB. Returns None when the DB is
        unavailable or the conversation does not exist."""
        db = self._db()
        if db is None:
            return None
        try:
            data = db.load_conversation(conv_id)
        except Exception:
            return None
        if not data:
            return None
        return self._build_from_data(conv_id, data)

    def _hydrate(self, conv_id: str, data: dict) -> Conversation:
        """Rebuild an in-memory Conversation from a DB row and register it."""
        conv = self._build_from_data(conv_id, data)
        with self._lock:
            self._access[conv_id] = time.time()
            self.conversations[conv_id] = conv
            self._workspace_index.setdefault(conv.workspace_id, set()).add(conv_id)
        return conv

    def get_or_create(self, conv_id: str, workspace_id: str = "default") -> Conversation:
        with self._lock:
            self._access[conv_id] = time.time()
            existing = self.conversations.get(conv_id)
            if existing is not None:
                return existing
            if len(self.conversations) >= _MAX_CONVS:
                self._evict_if_needed()
        conv = self._load_from_db(conv_id)
        if conv is None:
            conv = Conversation(workspace_id=workspace_id)
            conv._persist = self._make_persist(conv_id, conv)
        with self._lock:
            existing = self.conversations.get(conv_id)
            if existing is not None:
                return existing
            self.conversations[conv_id] = conv
            self._workspace_index.setdefault(conv.workspace_id, set()).add(conv_id)
        return conv

    def delete(self, conv_id: str):
        with self._lock:
            conv = self.conversations.pop(conv_id, None)
            self._access.pop(conv_id, None)
            if conv:
                ws_set = self._workspace_index.get(conv.workspace_id)
                if ws_set:
                    ws_set.discard(conv_id)
        db = self._db()
        if db is not None:
            try:
                db.delete_conversation(conv_id)
            except Exception:
                pass

    def reassign_workspace(self, conv_id: str, new_workspace_id: str):
        """Move an existing conversation into another workspace (used by import)."""
        with self._lock:
            conv = self.conversations.get(conv_id)
            if conv is None or conv.workspace_id == new_workspace_id:
                return
            old_ws = conv.workspace_id
            conv.workspace_id = new_workspace_id
            old_set = self._workspace_index.get(old_ws)
            if old_set:
                old_set.discard(conv_id)
                if not old_set:
                    self._workspace_index.pop(old_ws, None)
            self._workspace_index.setdefault(new_workspace_id, set()).add(conv_id)
        db = self._db()
        if db is not None:
            try:
                db.reassign_conversation(conv_id, new_workspace_id)
            except Exception:
                pass

    def delete_workspace(self, workspace_id: str):
        with self._lock:
            ids = list(self._workspace_index.get(workspace_id, set()))
            for cid in ids:
                self.conversations.pop(cid, None)
                self._access.pop(cid, None)
            self._workspace_index.pop(workspace_id, None)
        db = self._db()
        if db is not None:
            try:
                db.delete_workspace_conversations(workspace_id)
            except Exception:
                pass

    def conversations_for(self, workspace_id: str = "default") -> List[tuple]:
        db = self._db()
        if db is not None:
            try:
                for rec in db.list_conversations(workspace_id):
                    cid = rec.get("id")
                    with self._lock:
                        exists = cid in self.conversations
                    if not exists:
                        try:
                            data = db.load_conversation(cid)
                        except Exception:
                            data = None
                        if data:
                            self._hydrate(cid, data)
            except Exception:
                pass
        with self._lock:
            ids = self._workspace_index.get(workspace_id, set())
            return [(cid, self.conversations[cid]) for cid in ids if cid in self.conversations]

    def clear_all(self):
        with self._lock:
            self.conversations.clear()
            self._access.clear()
            self._workspace_index.clear()
