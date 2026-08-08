'use client';

import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Star, Download, Trash2, Search, Pencil, X, Check } from 'lucide-react';
import { fetchJSON, toArray, type ChatMessage } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import { toEpochMs, formatRelativeTime } from '@/lib/time';

export interface ConvoItem {
  id: string;
  title?: string;
  created_at?: number;
}

interface ConversationsPanelProps {
  conversations: ConvoItem[];
  convId: string;
  selectedWorkspace: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onExport: (title: string, messages: ChatMessage[]) => void;
}

const RENAME_KEY = 'chat_renames';
const PIN_KEY = 'chat_pins';

function loadMap(key: string): Record<string, string> {
  if (typeof window === 'undefined') return {};
  try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch { return {}; }
}

function groupOf(ts?: number): 'today' | 'yesterday' | 'week' | 'older' {
  const ms = toEpochMs(ts);
  if (ms == null) return 'older';
  const days = Math.floor((Date.now() - ms) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days <= 7) return 'week';
  return 'older';
}

const GROUP_ORDER = ['pinned', 'today', 'yesterday', 'week', 'older'] as const;
type GroupKey = typeof GROUP_ORDER[number];
const GROUP_LABEL: Record<GroupKey, string> = {
  pinned: 'Pinned',
  today: 'Today',
  yesterday: 'Yesterday',
  week: 'Previous 7 Days',
  older: 'Older',
};

function HighlightParts({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const q = query.toLowerCase();
  const parts: { text: string; hit: boolean }[] = [];
  let idx = 0;
  for (;;) {
    const found = text.toLowerCase().indexOf(q, idx);
    if (found === -1) {
      if (idx < text.length) parts.push({ text: text.slice(idx), hit: false });
      break;
    }
    if (found > idx) parts.push({ text: text.slice(idx, found), hit: false });
    parts.push({ text: text.slice(found, found + query.length), hit: true });
    idx = found + query.length;
  }
  return (
    <>
      {parts.map((p, i) =>
        p.hit ? (
          <mark key={i} className="bg-accent/30 text-text-primary rounded px-0.5">{p.text}</mark>
        ) : (
          <React.Fragment key={i}>{p.text}</React.Fragment>
        ),
      )}
    </>
  );
}

export default function ConversationsPanel({
  conversations,
  convId,
  selectedWorkspace,
  onSelect,
  onDelete,
  onExport,
}: ConversationsPanelProps) {
  const { addToast } = useToast();
  const [search, setSearch] = useState('');
  const [renames, setRenames] = useState<Record<string, string>>({});
  const [pins, setPins] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const editRef = useRef<HTMLInputElement>(null);
  const discardRef = useRef(false);

  useEffect(() => {
    setRenames(loadMap(RENAME_KEY));
    setPins(loadMap(PIN_KEY));
  }, []);

  useEffect(() => {
    if (editingId !== null && editRef.current) {
      editRef.current.focus();
      editRef.current.setSelectionRange(0, editRef.current.value.length);
    }
  }, [editingId]);

  const displayTitle = useCallback((c: ConvoItem) => renames[c.id] || c.title || c.id.slice(0, 8), [renames]);

  const grouped = useMemo(() => {
    const map: Record<GroupKey, ConvoItem[]> = { pinned: [], today: [], yesterday: [], week: [], older: [] };
    const q = search.trim().toLowerCase();
    for (const c of conversations) {
      if (q && !displayTitle(c).toLowerCase().includes(q) && !c.id.toLowerCase().includes(q)) continue;
      if (pins[c.id]) map.pinned.push(c);
      else map[groupOf(c.created_at)].push(c);
    }
    for (const key of Object.keys(map) as GroupKey[]) {
      map[key].sort((a, b) => (toEpochMs(b.created_at) || 0) - (toEpochMs(a.created_at) || 0));
    }
    return map;
  }, [conversations, search, pins, renames, displayTitle]);

  const startRename = (c: ConvoItem) => {
    discardRef.current = false;
    setEditText(displayTitle(c));
    setEditingId(c.id);
  };

  const saveRename = (id: string) => {
    if (discardRef.current) {
      discardRef.current = false;
      setEditingId(null);
      setEditText('');
      return;
    }
    setEditingId(null);
    const val = editText.trim();
    const next = { ...renames };
    if (val) next[id] = val; else delete next[id];
    setRenames(next);
    try { localStorage.setItem(RENAME_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };

  const cancelRename = () => {
    discardRef.current = true;
    setEditingId(null);
    setEditText('');
  };

  const togglePin = (c: ConvoItem) => {
    const next = { ...pins };
    if (next[c.id]) delete next[c.id]; else next[c.id] = '1';
    setPins(next);
    try { localStorage.setItem(PIN_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };

  const handleExport = async (c: ConvoItem) => {
    try {
      const qs = `?conv_id=${encodeURIComponent(c.id)}&workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`;
      const data = await fetchJSON(`/v1/chat/history${qs}`);
      const history = toArray<ChatMessage>(data);
      if (history.length === 0) { addToast('No messages to export', 'error'); return; }
      onExport(displayTitle(c), history);
    } catch {
      addToast('Export failed', 'error');
    }
  };

  const clearSearch = () => {
    setSearch('');
    searchRef.current?.focus();
  };

  return (
    <div className="flex flex-col h-full">
      <div className="relative px-3 pt-3 pb-2">
        <Search size={14} className="absolute left-5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
        <input
          ref={searchRef}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') clearSearch(); }}
          placeholder="Search conversations..."
          aria-label="Search conversations"
          className="input-base !pl-8 !pr-7 !py-2 !text-xs"
        />
        {search && (
          <button
            onClick={clearSearch}
            className="absolute right-4 top-1/2 -translate-y-1/2 p-0.5 text-text-muted hover:text-text-secondary rounded transition-colors"
            title="Clear search"
            aria-label="Clear search"
          >
            <X size={13} />
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 pb-3 space-y-3">
        {GROUP_ORDER.map((g) => {
          const items = grouped[g];
          if (items.length === 0) return null;
          return (
            <div key={g}>
              <div className="sticky top-0 z-10 bg-bg-secondary/95 backdrop-blur-sm px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-text-muted">
                {GROUP_LABEL[g]} <span className="text-text-muted/60">({items.length})</span>
              </div>
              <div className="space-y-1">
                {items.map((c) => (
                  <div
                    key={c.id}
                    aria-current={convId === c.id ? 'true' : undefined}
                    className={`group flex items-center gap-1.5 p-2 rounded-xl transition-all cursor-pointer border ${
                      convId === c.id
                        ? 'bg-accent-soft text-accent border-accent/20'
                        : 'hover:bg-bg-tertiary text-text-secondary border-transparent'
                    }`}
                  >
                    <button
                      onClick={() => togglePin(c)}
                      className={`p-1 rounded transition-colors shrink-0 ${pins[c.id] ? 'text-accent' : 'text-text-muted/50 hover:text-text-secondary opacity-0 group-hover:opacity-100'}`}
                      title={pins[c.id] ? 'Unpin' : 'Pin to top'}
                      aria-label={pins[c.id] ? 'Unpin conversation' : 'Pin conversation to top'}
                    >
                      <Star size={13} className={pins[c.id] ? 'fill-current' : ''} />
                    </button>
                    {editingId === c.id ? (
                      <input
                        ref={editRef}
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onBlur={() => saveRename(c.id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') { e.preventDefault(); saveRename(c.id); }
                          else if (e.key === 'Escape') { e.preventDefault(); cancelRename(); }
                        }}
                        aria-label="Rename conversation"
                        className="flex-1 min-w-0 bg-bg-primary/80 border border-accent/40 rounded px-1.5 py-1 text-xs text-text-primary focus:outline-none"
                      />
                    ) : (
                      <button
                        onClick={() => onSelect(c.id)}
                        onDoubleClick={() => startRename(c)}
                        className="flex-1 text-left text-xs truncate min-w-0"
                        title="Open · double-click to rename"
                      >
                        <span className="truncate font-medium block">
                          <HighlightParts text={displayTitle(c)} query={search.trim()} />
                        </span>
                        <span className="text-[10px] text-text-muted mt-0.5 block">
                          {c.created_at ? formatRelativeTime(c.created_at) : c.id.slice(0, 8)}
                        </span>
                      </button>
                    )}
                    {editingId !== c.id && (
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                        <button onClick={() => handleExport(c)} className="p-1 rounded hover:text-accent hover:bg-accent/10 transition-all" title="Export conversation" aria-label="Export conversation">
                          <Download size={12} />
                        </button>
                        <button onClick={() => startRename(c)} className="p-1 rounded hover:text-accent hover:bg-accent/10 transition-all" title="Rename" aria-label="Rename">
                          <Pencil size={12} />
                        </button>
                        {pendingDelete === c.id ? (
                          <>
                            <button onClick={() => { onDelete(c.id); setPendingDelete(null); }} className="p-1 rounded hover:text-danger hover:bg-danger/10 transition-all" title="Confirm delete" aria-label="Confirm delete">
                              <Check size={12} />
                            </button>
                            <button onClick={() => setPendingDelete(null)} className="p-1 rounded hover:text-text-secondary hover:bg-bg-tertiary transition-all" title="Cancel" aria-label="Cancel delete">
                              <X size={12} />
                            </button>
                          </>
                        ) : (
                          <button onClick={() => setPendingDelete(c.id)} className="p-1 rounded hover:text-danger hover:bg-danger/10 transition-all" title="Delete" aria-label="Delete">
                            <Trash2 size={12} />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        {conversations.length === 0 && (
          <p className="text-xs text-text-muted text-center py-6">No conversations yet</p>
        )}
        {conversations.length > 0 && Object.values(grouped).every((a) => a.length === 0) && (
          <p className="text-xs text-text-muted text-center py-6">No matches for “{search}”</p>
        )}
      </div>
    </div>
  );
}
