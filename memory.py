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

    def set_system(self, prompt: str):
        self.system_prompt = prompt

    def add(self, role: str, content: str):
        with self._lock:
            self.messages.append(Message(role, content))
            if len(self.messages) > self.max_history:
                self.messages = self.messages[-self.max_history:]

    def get_context(self, include_system: bool = True, open_assistant: bool = True) -> str:
        with self._lock:
            parts = []
            role_map = {"user": "user", "assistant": "assistant"}
            if include_system and self.system_prompt:
                parts.append(CHAT_TEMPLATE.format(role="system", content=self.system_prompt))
            for msg in self.messages:
                r = role_map.get(msg.role, msg.role)
                parts.append(CHAT_TEMPLATE.format(role=r, content=msg.content))
            if open_assistant:
                parts.append("<|im_start|>assistant\n")
            return "\n".join(parts)

    def to_openai_format(self) -> List[Dict]:
        with self._lock:
            msgs = []
            if self.system_prompt:
                msgs.append({"role": "system", "content": self.system_prompt})
            for msg in self.messages:
                msgs.append({"role": msg.role, "content": msg.content})
            return msgs

    def clear(self):
        with self._lock:
            self.messages.clear()
            self.system_prompt = None


class MemoryManager:
    def __init__(self):
        self.conversations: Dict[str, Conversation] = {}
        self._access: Dict[str, float] = {}
        self._workspace_index: Dict[str, set] = {}
        self._lock = threading.Lock()

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
        """Return the conversation for a conv_id if it exists, else None."""
        with self._lock:
            return self.conversations.get(conv_id)

    def get_or_create(self, conv_id: str, workspace_id: str = "default") -> Conversation:
        with self._lock:
            self._access[conv_id] = time.time()
            if conv_id not in self.conversations:
                if len(self.conversations) >= _MAX_CONVS:
                    self._evict_if_needed()
                self.conversations[conv_id] = Conversation(workspace_id=workspace_id)
                self._workspace_index.setdefault(workspace_id, set()).add(conv_id)
            return self.conversations[conv_id]

    def delete(self, conv_id: str):
        with self._lock:
            conv = self.conversations.pop(conv_id, None)
            self._access.pop(conv_id, None)
            if conv:
                ws_set = self._workspace_index.get(conv.workspace_id)
                if ws_set:
                    ws_set.discard(conv_id)

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

    def delete_workspace(self, workspace_id: str):
        with self._lock:
            ids = list(self._workspace_index.get(workspace_id, set()))
            for cid in ids:
                self.conversations.pop(cid, None)
                self._access.pop(cid, None)
            self._workspace_index.pop(workspace_id, None)

    def conversations_for(self, workspace_id: str = "default") -> List[tuple]:
        with self._lock:
            ids = self._workspace_index.get(workspace_id, set())
            return [(cid, self.conversations[cid]) for cid in ids if cid in self.conversations]

    def clear_all(self):
        with self._lock:
            self.conversations.clear()
            self._access.clear()
            self._workspace_index.clear()
