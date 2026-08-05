'use client';

import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { fetchJSON, toArray, toText, api, autoStreamChat, uploadChatFile, computerStream, type ModelItem, type ChatMessage, type Agent, type Skill, type Workspace, type StreamEvent, type ComputerToolEvent } from '@/lib/api';
import { getStorage, setStorageValue, removeStorageValue } from '@/lib/storage';
import { useToast } from '@/components/providers/ToastProvider';
import { useTheme } from '@/components/ThemeProvider';
import ThinkingIndicator from '@/components/ThinkingIndicator';
import Select from '@/components/ui/Select';
import Button from '@/components/ui/Button';
import AutocompletePopover, { type AutocompleteItem } from '@/components/chat/AutocompletePopover';
import ImagePreviewModal from '@/components/chat/ImagePreviewModal';
import EmptyStateCards from '@/components/chat/EmptyStateCards';
import MessageToolbar from '@/components/chat/MessageToolbar';
import ConversationsPanel from '@/components/chat/ConversationsPanel';
import ExportModal from '@/components/chat/ExportModal';
import CodeBlock from '@/components/chat/CodeBlock';
import ToolCallCard, { type ToolCall } from '@/components/chat/ToolCallCard';
import {
  Send, Square, Trash2, Bot, User, Loader2, MessageSquare, Plus, X, Keyboard,
  Download, Sparkles, Paperclip, FileImage, FileText, FileCode, ArrowDown, Mic, Globe, Brain,
  Slash, AtSign, History, Terminal,
} from 'lucide-react';
import { t } from '@/lib/i18n';

const STORAGE_KEYS = {
  model: 'chat_model',
  workspace: 'chat_workspace',
  messages: 'chat_messages',
  convId: 'chat_conv_id',
};

const MAX_TOKENS = 4096;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

function stripMarkdown(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, (m) => m.replace(/```\w*\n?/, '').replace(/```/, ''))
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_~>#]/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function getTrigger(value: string, caret: number): { type: 'slash' | 'mention'; query: string } | null {
  const before = value.slice(0, caret);
  const m = /(^|\s)([/@])(\S*)$/.exec(before);
  if (!m) return null;
  return { type: m[2] === '/' ? 'slash' : 'mention', query: m[3] };
}

interface SlashCommand {
  id: string;
  label: string;
  description: string;
  hint?: string;
  action: 'clear' | 'compact' | 'review' | 'test' | 'model' | 'help';
}

const SLASH_COMMANDS: SlashCommand[] = [
  { id: '/clear', label: '/clear', description: 'Clear the current conversation', hint: '⌫', action: 'clear' },
  { id: '/compact', label: '/compact', description: 'Compress conversation context', action: 'compact' },
  { id: '/review', label: '/review', description: 'Review code & show a diff', action: 'review' },
  { id: '/test', label: '/test', description: 'Generate unit tests', action: 'test' },
  { id: '/model', label: '/model', description: 'Switch the active model', action: 'model' },
  { id: '/help', label: '/help', description: 'Show available commands', hint: '?', action: 'help' },
];

interface ContextChip {
  id: string;
  label: string;
  kind: 'file' | 'agent' | 'skill' | 'web';
}

function MarkdownContent({ content }: { content: string }) {
  const { theme } = useTheme();
  return (
    <div className={`prose max-w-none prose-sm ${theme === 'dark' ? 'prose-invert' : ''}`}>
      <ReactMarkdown
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            const codeString = String(children).replace(/\n$/, '');
            const isInline = !match && !codeString.includes('\n');
            if (isInline) {
              return <code className="bg-bg-tertiary px-1.5 py-0.5 rounded text-accent text-xs font-mono" {...props}>{children}</code>;
            }
            return <CodeBlock code={codeString} language={match?.[1] || 'text'} />;
          },
          p({ children }) {
            return <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>;
          },
          ul({ children }) {
            return <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>;
          },
          a({ href, children }) {
            return <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover underline underline-offset-2">{children}</a>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default function ChatPage() {
  const [models, setModels] = useState<ModelItem[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [selectedSkill, setSelectedSkill] = useState('');
  const [selectedWorkspace, setSelectedWorkspace] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [autoStreaming, setAutoStreaming] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [thinkingText, setThinkingText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [conversations, setConversations] = useState<{ id: string; title?: string; created_at?: number }[]>([]);
  const [convId, setConvId] = useState('');
  const [modelLoading, setModelLoading] = useState(false);
  const [currentConvTitle, setCurrentConvTitle] = useState('');
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [exportTarget, setExportTarget] = useState<{ title: string; messages: ChatMessage[]; convId?: string } | null>(null);
  const [composerFocused, setComposerFocused] = useState(false);

  // Agentic tools mode (computer agent)
  const [agenticTools, setAgenticTools] = useState(false);
  const [liveToolCalls, setLiveToolCalls] = useState<ToolCall[]>([]);
  const [agenticActive, setAgenticActive] = useState(false);
  const nextToolId = useRef(0);

  // Autocomplete state
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [contextChips, setContextChips] = useState<ContextChip[]>([]);

  // Workspace files for @ mentions
  const [workspaceFiles, setWorkspaceFiles] = useState<{ name: string }[]>([]);

  // Image preview
  const [previewImage, setPreviewImage] = useState<{ url: string; name: string } | null>(null);
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);

  // Message toolbar state
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editText, setEditText] = useState('');
  const [feedback, setFeedback] = useState<Record<number, 'up' | 'down'>>({});

  // Scroll-to-bottom
  const [atBottom, setAtBottom] = useState(true);
  const [newMessageCount, setNewMessageCount] = useState(0);

  // Voice input
  const [listening, setListening] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const dragDepth = useRef(0);
  const touchStartX = useRef<number | null>(null);
  const recognitionRef = useRef<{ stop: () => void } | null>(null);
  const { addToast } = useToast();

  const sessionTokens = useMemo(
    () => messages.reduce((sum, m) => sum + estimateTokens(m.content), 0),
    [messages],
  );
  const sessionCost = (sessionTokens / 1000) * 0.0001;
  const activeModel = models.find((m) => m.id === selectedModel);
  const modelLoaded = !!activeModel?.loaded;
  const modelCtx = (() => {
    const n = Number(activeModel?.n_ctx ?? activeModel?.context_window ?? 0);
    if (!n) return null;
    if (n >= 1000) return `${Math.round(n / 1000)}k`;
    return String(n);
  })();

  useEffect(() => {
    const urls = files.map((f) => (f.type.startsWith('image/') ? URL.createObjectURL(f) : ''));
    setPreviewUrls(urls);
    return () => urls.forEach((u) => u && URL.revokeObjectURL(u));
  }, [files]);

  const refreshModels = async () => {
    const m = await fetchJSON('/v1/models');
    const modelList = toArray<ModelItem>(m);
    const loadedModels = modelList.filter((x) => x.loaded);
    setModels(loadedModels.length > 0 ? loadedModels : modelList);
    return { modelList, loadedModels };
  };

  const loadConversations = useCallback(async () => {
    try {
      const data = await fetchJSON(`/v1/chat/conversations?labels=1&workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`);
      const convList = toArray<{ id: string; title?: string; created_at?: number }>(data);
      setConversations(convList);
    } catch { /* ignore */ }
  }, [selectedWorkspace]);

  useEffect(() => {
    const savedModel = getStorage<string>(STORAGE_KEYS.model, '');
    const savedWorkspace = getStorage<string>(STORAGE_KEYS.workspace, '');
    const savedMessages = getStorage<ChatMessage[]>(STORAGE_KEYS.messages, []);
    const urlConvId = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('conv') : '';
    const savedConvId = urlConvId || getStorage<string>(STORAGE_KEYS.convId, '');

    let mounted = true;
    async function load() {
      try {
        const [a, s, w] = await Promise.all([
          fetchJSON('/v1/agents'),
          fetchJSON('/v1/skills'),
          fetchJSON('/v1/workspaces'),
        ]);
        if (!mounted) return;
        setAgents(toArray<Agent>(a));
        setSkills(toArray<Skill>(s));
        const wsList = toArray<Workspace>(w);
        setWorkspaces(wsList);

        const { modelList, loadedModels } = await refreshModels();

        const displayModels = loadedModels.length > 0 ? loadedModels : modelList;
        if (savedModel && displayModels.some((m) => m.id === savedModel)) {
          setSelectedModel(savedModel);
        } else {
          const foundDefault = displayModels.find((m) => (m.role || '').toLowerCase().includes('executor'))
            || displayModels[0]
            || modelList.find((m) => (m.role || '').toLowerCase().includes('executor'))
            || modelList[0];
          if (foundDefault) {
            setSelectedModel(foundDefault.id);
            setStorageValue(STORAGE_KEYS.model, foundDefault.id);
          }
        }

        const activeWs = savedWorkspace && wsList.some((w) => w.id === savedWorkspace)
          ? savedWorkspace
          : wsList.length ? wsList[0].id : '';
        if (activeWs) {
          setSelectedWorkspace(activeWs);
          setStorageValue(STORAGE_KEYS.workspace, activeWs);
        }

        if (savedConvId) {
          const wsParam = activeWs || 'default';
          const freshConvs = await fetchJSON(`/v1/chat/conversations?workspace_id=${encodeURIComponent(wsParam)}`).catch(() => []);
          const convList = toArray<{ id: string; title?: string }>(freshConvs);
          const exists = convList.some((c) => c.id === savedConvId);
          if (exists) {
            setConvId(savedConvId);
            const conv = convList.find((c) => c.id === savedConvId);
            if (conv?.title) setCurrentConvTitle(conv.title);
            try {
              const qs = `?conv_id=${encodeURIComponent(savedConvId)}&workspace_id=${encodeURIComponent(wsParam)}`;
              const historyData = await fetchJSON(`/v1/chat/history${qs}`);
              const history = toArray<ChatMessage>(historyData);
              if (history.length > 0 && mounted) {
                setMessages(history);
                setStorageValue(STORAGE_KEYS.messages, history);
              }
            } catch { /* ignore */ }
          } else if (savedMessages.length > 0) {
            setMessages(savedMessages);
          }
        } else if (savedMessages.length > 0) {
          setMessages(savedMessages);
        }

        const autoLoadTarget = loadedModels.length === 0
          ? (modelList.find((m) => (m.role || '').toLowerCase().includes('executor')) || modelList[0])
          : null;

        if (autoLoadTarget) {
          setModelLoading(true);
          try {
            await fetchJSON(`/v1/models/load?name=${encodeURIComponent(autoLoadTarget.id)}`, { method: 'POST' });
            addToast(`Loading ${autoLoadTarget.id}...`, 'success');
            setTimeout(() => { if (mounted) refreshModels(); }, 2000);
          } catch (e) {
            addToast(`Auto-load failed: ${toText(e)}`, 'error');
            setModels(modelList);
          } finally {
            if (mounted) setModelLoading(false);
          }
        }
      } catch {
        addToast('Failed to load chat data', 'error');
      }
    }
    load();
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (convId && conversations.length > 0) {
      const conv = conversations.find((c) => c.id === convId);
      if (conv?.title) setCurrentConvTitle(conv.title);
    }
  }, [convId, conversations]);

  const prevMsgLen = useRef(0);
  useEffect(() => {
    if (atBottom) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      setNewMessageCount(0);
    } else if (messages.length > prevMsgLen.current) {
      setNewMessageCount((c) => c + (messages.length - prevMsgLen.current));
    }
    prevMsgLen.current = messages.length;
  }, [messages, thinking, atBottom]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + 'px';
    }
  }, [input]);

  useEffect(() => {
    if (!selectedWorkspace) return;
    let mounted = true;
    async function loadConvs() {
      try {
        const data = await fetchJSON(`/v1/chat/conversations?labels=1&workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`);
        if (!mounted) return;
        const convList = toArray<{ id: string; title?: string; created_at?: number }>(data);
        setConversations(convList);
      } catch { /* ignore */ }
    }
    loadConvs();
    return () => { mounted = false; };
  }, [selectedWorkspace]);

  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch { /* ignore */ }
      }
    };
  }, []);

  const persistMessages = useCallback((msgs: ChatMessage[]) => {
    setMessages(msgs);
    setStorageValue(STORAGE_KEYS.messages, msgs.slice(-100));
  }, []);

  const persistConvId = useCallback((id: string) => {
    setConvId(id);
    setStorageValue(STORAGE_KEYS.convId, id);
  }, []);

  async function clearChat() {
    setMessages([]);
    setConvId('');
    setCurrentConvTitle('');
    setContextChips([]);
    removeStorageValue(STORAGE_KEYS.messages);
    removeStorageValue(STORAGE_KEYS.convId);
    await loadConversations();
    inputRef.current?.focus();
  }

  async function createNewChat() {
    await clearChat();
  }

  async function deleteConversation(id: string) {
    if (!window.confirm('Delete this conversation?')) return;
    try {
      await fetchJSON(`/v1/chat/conversations?conv_id=${encodeURIComponent(id)}&workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`, {
        method: 'DELETE',
      });
      addToast(t('chat.chatDeleted'), 'success');
      if (convId === id) {
        setConvId('');
        setMessages([]);
        setCurrentConvTitle('');
        removeStorageValue(STORAGE_KEYS.messages);
        removeStorageValue(STORAGE_KEYS.convId);
      }
      await loadConversations();
    } catch {
      addToast('Failed to delete chat', 'error');
    }
  }

  async function clearAllConversations() {
    if (!window.confirm('Clear all conversations in this workspace?')) return;
    try {
      const qs = `?workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`;
      await fetchJSON(`/v1/chat/clear${qs}`, { method: 'POST' });
      addToast(t('chat.allCleared'), 'success');
      setMessages([]);
      setConvId('');
      setCurrentConvTitle('');
      removeStorageValue(STORAGE_KEYS.messages);
      removeStorageValue(STORAGE_KEYS.convId);
      await loadConversations();
    } catch {
      addToast('Clear all failed', 'error');
    }
  }

  async function exportConversation() {
    if (messages.length === 0) { addToast('Nothing to export', 'error'); return; }
    setExportTarget({ title: currentConvTitle || 'Conversation', messages, convId: convId || undefined });
  }

  const runChat = useCallback(async (history: ChatMessage[]) => {
    if (sending || modelLoading || thinking || uploading) return;
    if (!selectedModel || !models.some((m) => m.id === selectedModel)) {
      addToast(t('chat.pleaseSelectModel'), 'error');
      return;
    }

    const controller = new AbortController();
    setAbortController(controller);
    setSending(true);
    setThinking(true);

    const body: Record<string, unknown> = {
      model: selectedModel,
      messages: history.map((m) => ({ role: m.role, content: m.content })),
      stream: streaming,
    };
    if (selectedAgent) body.agent = selectedAgent;
    if (selectedSkill) body.skill = selectedSkill;
    if (selectedWorkspace) body.workspace_id = selectedWorkspace;
    if (planning) body.use_planning = true;
    if (convId) body.conversation_id = convId;

    try {
      if (autoStreaming) {
        setMessages([...history, { role: 'assistant', content: '' }]);
        let assistantText = '';
        await autoStreamChat(
          history.map((m) => ({ role: m.role, content: m.content })),
          selectedModel,
          selectedWorkspace || 'default',
          planning,
          (evt: StreamEvent) => {
            if (evt.type === 'thinking' && typeof evt.content === 'string') {
              setThinking(true);
              setThinkingText(evt.content);
            } else if (evt.type === 'response' && typeof evt.content === 'string') {
              assistantText += evt.content;
              setMessages(prev => {
                const next = [...prev];
                next[next.length - 1] = { role: 'assistant', content: assistantText };
                return next;
              });
            }
          },
          controller.signal,
        );
        const finalMessages: ChatMessage[] = [...history, { role: 'assistant', content: assistantText }];
        persistMessages(finalMessages);
      } else if (streaming) {
        const res = await api('/v1/chat/stream', {
          method: 'POST',
          body: JSON.stringify(body),
        }, 300000, controller.signal);
        if (!res.ok) throw new Error('Stream failed');
        const reader = res.body?.getReader();
        if (!reader) throw new Error('No stream');
        const decoder = new TextDecoder();
        let assistantText = '';
        let buffer = '';
        setMessages([...history, { role: 'assistant', content: '' }]);
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data:')) continue;
            const payload = trimmed.slice(5).trim();
            if (payload === '[DONE]') continue;
            try {
              const evt = JSON.parse(payload);
              if (evt.type === 'response' && typeof evt.content === 'string') {
                assistantText += evt.content;
                setMessages(prev => {
                  const next = [...prev];
                  next[next.length - 1] = { role: 'assistant', content: assistantText };
                  return next;
                });
              } else if (evt.type === 'thinking' && typeof evt.content === 'string') {
                setThinking(true);
              } else if (evt.type === 'start') {
                setThinking(true);
              }
            } catch { /* ignore malformed frames */ }
          }
        }
        const finalMessages: ChatMessage[] = [...history, { role: 'assistant', content: assistantText }];
        persistMessages(finalMessages);
      } else {
        const data = await fetchJSON('/v1/chat/completions', {
          method: 'POST',
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        const choice = (data as { choices?: { message?: ChatMessage }[] }).choices?.[0]?.message;
        if (choice) {
          const assistantMsg: ChatMessage = { role: choice.role, content: toText(choice.content) };
          const finalMessages = [...history, assistantMsg];
          persistMessages(finalMessages);
        }
      }

      if (!convId) {
        try {
          const convsData = await fetchJSON(`/v1/chat/conversations?labels=1&workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`);
          const convList = toArray<{ id: string; title?: string; created_at?: number }>(convsData);
          setConversations(convList);
          if (convList.length > 0) {
            const latest = convList[0];
            persistConvId(latest.id);
            if (latest.title) setCurrentConvTitle(latest.title);
          }
        } catch { /* ignore */ }
      } else {
        await loadConversations();
      }

      addToast(t('chat.responseReceived'), 'success');
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        addToast(toText(e), 'error');
      }
    } finally {
      setSending(false);
      setThinking(false);
      setThinkingText('');
      setAbortController(null);
      setContextChips([]);
    }
  }, [sending, modelLoading, thinking, uploading, selectedModel, models, selectedAgent, selectedSkill, selectedWorkspace, planning, streaming, autoStreaming, convId, persistMessages, persistConvId, loadConversations, addToast]);

  const runAgentic = useCallback(async (history: ChatMessage[]) => {
    if (sending || modelLoading || thinking || uploading) return;
    if (!selectedModel || !models.some((m) => m.id === selectedModel)) {
      addToast(t('chat.pleaseSelectModel'), 'error');
      return;
    }

    const goalMsg = [...history].reverse().find((m) => m.role === 'user');
    if (!goalMsg) {
      addToast('No user message to run', 'error');
      return;
    }

    const controller = new AbortController();
    setAbortController(controller);
    setSending(true);
    setThinking(true);
    setAgenticActive(true);
    setLiveToolCalls([]);
    nextToolId.current = 0;

    setMessages([...history, { role: 'assistant', content: '' }]);

    let assistantText = '';
    try {
      await computerStream(
        goalMsg.content,
        { sandbox: false, maxSteps: 25 },
        (evt: ComputerToolEvent) => {
          if (evt.type === 'thinking' && typeof evt.content === 'string') {
            setThinking(true);
            setThinkingText((prev) => prev + evt.content);
          } else if (evt.type === 'tool_call') {
            const id = ++nextToolId.current;
            setLiveToolCalls((prev) => [...prev, {
              id,
              tool: evt.tool || 'tool',
              args: evt.args,
              status: evt.success ? 'success' : 'failed',
              output: evt.result,
              elapsed: evt.elapsed,
              step: evt.step,
            }]);
          } else if (evt.type === 'complete') {
            assistantText = evt.answer || '';
            setThinking(false);
            setThinkingText('');
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { role: 'assistant', content: assistantText };
              return next;
            });
          }
        },
        controller.signal,
      );
      const finalMessages: ChatMessage[] = [...history, { role: 'assistant', content: assistantText }];
      persistMessages(finalMessages);
      addToast('Agent run complete', 'success');
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        addToast(toText(e), 'error');
      }
    } finally {
      setSending(false);
      setThinking(false);
      setThinkingText('');
      setAgenticActive(false);
      setAbortController(null);
      setContextChips([]);
    }
  }, [sending, modelLoading, thinking, uploading, selectedModel, models, persistMessages, addToast]);

  async function sendMessage() {
    const trimmedInput = input.trim();
    if ((!trimmedInput && files.length === 0) || sending || modelLoading || thinking || uploading) return;

    let content = trimmedInput;
    if (files.length > 0) {
      const toUpload = files;
      setUploading(true);
      try {
        const uploadedFiles = await Promise.all(toUpload.map((f) => uploadChatFile(f)));
        const fileParts = uploadedFiles.map((f) => {
          let part = `[${f.name}](${f.url})`;
          if (f.preview_text) {
            part += `\n\nExtracted text from ${f.name}:\n\`\`\`\n${f.preview_text}\n\`\`\``;
          }
          return part;
        });
        const fileContext = fileParts.join('\n\n');
        content = trimmedInput ? `${fileContext}\n\n${trimmedInput}` : fileContext;
        addToast(`${toUpload.length} file(s) uploaded`, 'success');
      } catch (e) {
        addToast(toText(e), 'error');
        setUploading(false);
        return;
      } finally {
        setUploading(false);
        setFiles([]);
      }
    }

    if (contextChips.length > 0) {
      const refs = contextChips.map((c) => `@${c.label}`).join(', ');
      content = `Referenced context: ${refs}\n\n${content}`;
    }

    const userMsg: ChatMessage = { role: 'user', content };
    const nextMessages = [...messages, userMsg];
    persistMessages(nextMessages);
    setInput('');
    setSlashOpen(false);
    setMentionOpen(false);
    if (agenticTools) {
      await runAgentic(nextMessages);
    } else {
      await runChat(nextMessages);
    }
  }

  function abortGeneration() {
    if (abortController) {
      abortController.abort();
      setAbortController(null);
      setSending(false);
      setThinking(false);
      setThinkingText('');
      setAgenticActive(false);
      setLiveToolCalls([]);
    }
  }

  async function loadHistory(id: string) {
    try {
      const qs = `?conv_id=${encodeURIComponent(id)}&workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`;
      const data = await fetchJSON(`/v1/chat/history${qs}`);
      const history = toArray<ChatMessage>(data);
      persistMessages(history);
      persistConvId(id);
      const conv = conversations.find((c) => c.id === id);
      if (conv?.title) setCurrentConvTitle(conv.title);
      addToast(t('chat.historyLoaded'), 'success');
    } catch {
      addToast(t('chat.failedToLoadHistory'), 'error');
    }
  }

  const handleModelChange = (value: string) => {
    setSelectedModel(value);
    setStorageValue(STORAGE_KEYS.model, value);
  };

  const handleWorkspaceChange = (value: string) => {
    setSelectedWorkspace(value);
    setStorageValue(STORAGE_KEYS.workspace, value);
  };

  async function fetchWorkspaceFiles() {
    if (!selectedWorkspace) return;
    try {
      const data = await fetchJSON(`/v1/workspaces/${encodeURIComponent(selectedWorkspace)}/files`);
      const list = toArray<{ name: string }>(data);
      setWorkspaceFiles(list);
    } catch { /* ignore */ }
  }

  const mentionItems: AutocompleteItem[] = useMemo(() => {
    const items: AutocompleteItem[] = [];
    workspaceFiles.forEach((f) => items.push({ id: `file:${f.name}`, label: f.name, description: 'Workspace file', icon: <FileText size={15} /> }));
    agents.forEach((a) => items.push({ id: `agent:${a.name}`, label: a.name, description: a.role || 'Agent', icon: <Bot size={15} /> }));
    skills.forEach((s) => items.push({ id: `skill:${s.name}`, label: s.name, description: s.description || 'Skill', icon: <Sparkles size={15} /> }));
    return items;
  }, [workspaceFiles, agents, skills]);

  function closeMenus() {
    setSlashOpen(false);
    setMentionOpen(false);
  }

  function selectSlash(cmd: SlashCommand) {
    closeMenus();
    switch (cmd.action) {
      case 'clear':
        clearChat();
        break;
      case 'compact':
        setInput('Summarize and compress our conversation into a concise context I can continue with.');
        inputRef.current?.focus();
        break;
      case 'review':
        setInput('Review the code above and show a diff of your suggested changes.');
        inputRef.current?.focus();
        break;
      case 'test':
        setInput('Write unit tests for the code above, covering edge cases with assertions.');
        inputRef.current?.focus();
        break;
      case 'model':
        addToast('Pick a model from the toolbar selector above', 'success');
        break;
      case 'help':
        addToast('Commands: /clear · /compact · /review · /test · /model · /help', 'success');
        break;
    }
  }

  const runPreset = (action: SlashCommand['action']) => {
    const cmd = SLASH_COMMANDS.find((c) => c.action === action);
    if (cmd) selectSlash(cmd);
  };

  function applyMention(item: AutocompleteItem, caret: number) {
    const before = input.slice(0, caret);
    const after = input.slice(caret);
    const newBefore = before.replace(/(^|\s)@\S*$/, `$1@${item.label} `);
    const next = newBefore + after;
    setInput(next);
    const kind: ContextChip['kind'] = item.id.startsWith('file:') ? 'file' : item.id.startsWith('agent:') ? 'agent' : item.id.startsWith('skill:') ? 'skill' : 'file';
    setContextChips((prev) => {
      if (prev.some((c) => c.label === item.label && c.kind === kind)) return prev;
      return [...prev, { id: `${kind}:${item.label}`, label: item.label, kind }];
    });
    closeMenus();
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const value = e.target.value;
    setInput(value);
    const caret = e.target.selectionStart ?? value.length;
    const trigger = getTrigger(value, caret);
    if (trigger?.type === 'slash') {
      const q = trigger.query.toLowerCase().replace(/^\//, '');
      const filtered = SLASH_COMMANDS.filter((c) => c.id.slice(1).startsWith(q));
      setSlashOpen(true);
      setMentionOpen(false);
      setSlashIndex(0);
      if (filtered.length === 0) setSlashOpen(false);
    } else if (trigger?.type === 'mention') {
      setMentionOpen(true);
      setSlashOpen(false);
      setMentionIndex(0);
      fetchWorkspaceFiles();
    } else {
      closeMenus();
    }
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (slashOpen || mentionOpen) {
      const sList = SLASH_COMMANDS.filter((c) => c.id.slice(1).startsWith(getSlashQuery()));
      const mList = mentionItems.filter((it) => it.label.toLowerCase().includes(getMentionQuery()));
      const list = slashOpen ? sList : mList;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const idx = (slashOpen ? slashIndex : mentionIndex) + 1;
        if (slashOpen) setSlashIndex(idx % list.length); else setMentionIndex(idx % list.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        const idx = (slashOpen ? slashIndex : mentionIndex) - 1 + list.length;
        if (slashOpen) setSlashIndex(idx % list.length); else setMentionIndex(idx % list.length);
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        if (slashOpen && sList.length > 0) {
          selectSlash(sList[Math.min(slashIndex, sList.length - 1)]);
        } else if (!slashOpen && mList.length > 0) {
          applyMention(mList[Math.min(mentionIndex, mList.length - 1)], inputRef.current?.selectionStart ?? input.length);
        }
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        closeMenus();
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  function getSlashQuery(): string {
    const trigger = getTrigger(input, inputRef.current?.selectionStart ?? input.length);
    return trigger?.type === 'slash' ? trigger.query.toLowerCase().replace(/^\//, '') : '';
  }
  function getMentionQuery(): string {
    const trigger = getTrigger(input, inputRef.current?.selectionStart ?? input.length);
    return trigger?.type === 'mention' ? trigger.query.toLowerCase().toLowerCase() : '';
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      setFiles((prev) => [...prev, ...Array.from(e.target.files!)]);
    }
    e.target.value = '';
  }

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  function handleDragEnter(e: React.DragEvent) {
    e.preventDefault();
    dragDepth.current += 1;
    setIsDragging(true);
  }
  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
  }
  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setIsDragging(false);
    }
  }
  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    dragDepth.current = 0;
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFiles((prev) => [...prev, ...Array.from(e.dataTransfer.files)]);
    }
  }

  const getFileIcon = (file: File) => {
    if (file.type.startsWith('image/')) return <FileImage size={16} className="text-accent-2" />;
    if (file.type === 'text/markdown' || file.name.endsWith('.md')) return <FileText size={16} className="text-blue-400" />;
    if (file.type.includes('code') || /\.(py|js|ts|tsx|jsx|go|rs|java|c|cpp|sh|json)$/i.test(file.name)) return <FileCode size={16} className="text-yellow-400" />;
    return <FileText size={16} className="text-text-muted" />;
  };

  function startVoiceInput() {
    const SR = (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown }).SpeechRecognition
      || (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
    if (!SR) {
      addToast('Voice input not supported in this browser', 'error');
      return;
    }
    interface SpeechRecognitionResultItem { transcript: string; }
    interface SpeechRecognitionResultEvent { results: ArrayLike<ArrayLike<SpeechRecognitionResultItem>>; }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec = new (SR as any)() as {
      continuous: boolean;
      interimResults: boolean;
      lang: string;
      onresult: ((ev: SpeechRecognitionResultEvent) => void) | null;
      onerror: (() => void) | null;
      onend: (() => void) | null;
      start: () => void;
      stop: () => void;
    };
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';
    rec.onresult = (ev) => {
      let transcript = '';
      for (let i = 0; i < ev.results.length; i += 1) transcript += ev.results[i][0].transcript;
      setInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
    };
    rec.onerror = () => { setListening(false); };
    rec.onend = () => { setListening(false); };
    rec.start();
    recognitionRef.current = rec;
    setListening(true);
  }

  function stopVoiceInput() {
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
    }
    setListening(false);
  }

  function toggleWebSearch() {
    setContextChips((prev) => {
      const has = prev.some((c) => c.kind === 'web');
      if (has) return prev.filter((c) => c.kind !== 'web');
      return [...prev, { id: 'web:search', label: 'Web search', kind: 'web' }];
    });
  }

  function onScroll() {
    const el = messagesRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAtBottom(dist < 80);
    if (dist < 80) setNewMessageCount(0);
  }

  function scrollToBottom() {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }

  function startEdit(index: number) {
    setEditingIndex(index);
    setEditText(messages[index].content);
  }

  function saveEdit() {
    if (editingIndex === null) return;
    const next = messages.slice(0, editingIndex + 1);
    next[editingIndex] = { ...messages[editingIndex], content: editText };
    persistMessages(next);
    setEditingIndex(null);
    setEditText('');
  }

  function deleteMessage(index: number) {
    persistMessages(messages.filter((_, i) => i !== index));
  }

  function branchConversation() {
    setConvId('');
    removeStorageValue(STORAGE_KEYS.convId);
    addToast('Branched — next send starts a new conversation', 'success');
  }

  function regenerateFrom(index: number) {
    const subset = messages.slice(0, index);
    persistMessages(subset);
    void runChat(subset);
  }

  function readAloud(content: string) {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      addToast('Text-to-speech not supported', 'error');
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(stripMarkdown(content));
    window.speechSynthesis.speak(u);
  }

  function setFeedbackFor(index: number, kind: 'up' | 'down') {
    setFeedback((prev) => ({ ...prev, [index]: kind }));
  }

  function onEmptyCardSelect(card: { prompt: string; modelId?: string; agentName?: string }) {
    setInput(card.prompt);
    if (card.modelId && models.some((m) => m.id === card.modelId)) {
      setSelectedModel(card.modelId);
      setStorageValue(STORAGE_KEYS.model, card.modelId);
    }
    if (card.agentName) setSelectedAgent(card.agentName);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  const tokenEstimate = estimateTokens(input);
  const slashFiltered = SLASH_COMMANDS.filter((c) => c.id.slice(1).startsWith(getSlashQuery()));
  const mentionFiltered = mentionItems.filter((it) => it.label.toLowerCase().includes(getMentionQuery()));

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col min-w-0 relative">
        <div className="px-5 py-3 border-b border-border bg-bg-secondary/60 backdrop-blur-md">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white shadow-lg shadow-accent/25 shrink-0">
                <MessageSquare size={16} />
              </div>
              <div className="min-w-0">
                <h2 className="text-sm font-semibold truncate leading-tight">
                  {currentConvTitle || t('chat.howCanHelp')}
                </h2>
                <div className="flex items-center gap-2">
                  {convId && <span className="text-[10px] text-text-muted font-mono">{convId.slice(0, 8)}</span>}
                  {selectedWorkspace && (() => {
                    const ws = workspaces.find((w) => w.id === selectedWorkspace);
                    const sp = (ws as unknown as Record<string, unknown>)?.system_prompt as string | undefined;
                    return sp ? <span className="text-[10px] text-accent truncate max-w-[180px]" title={sp}>{`Prompt: ${sp.slice(0, 36)}${sp.length > 36 ? '...' : ''}`}</span> : null;
                  })()}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {selectedModel && (
                <>
                  <div className="hidden sm:flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-full border border-border bg-bg-tertiary/60" title={`${selectedModel} · ${modelLoaded ? 'loaded' : 'not loaded'}`}>
                    <span className={`w-2 h-2 rounded-full ${modelLoaded ? 'bg-success shadow-[0_0_6px] shadow-success/70' : 'bg-text-muted'}`} />
                    <span className="text-text-secondary">{modelLoaded ? 'Warm' : 'Cold'}</span>
                    {modelCtx && <span className="text-text-muted">· {modelCtx} ctx</span>}
                    <span className="text-text-muted capitalize hidden lg:inline">· {activeModel?.role || 'model'}</span>
                  </div>
                  <div className="hidden md:flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-full border border-border bg-bg-tertiary/60 text-text-secondary font-mono" title="Estimated session token usage & cost">
                    <span>{sessionCost < 0.01 ? `$${sessionCost.toFixed(4)}` : `$${sessionCost.toFixed(2)}`}</span>
                    <span className="text-text-muted">· {(sessionTokens / 1000).toFixed(1)}k tok</span>
                  </div>
                </>
              )}
              <button
                onClick={() => setDrawerOpen(true)}
                className="xl:hidden p-2 rounded-lg text-text-secondary hover:text-accent hover:bg-accent/10 transition-colors"
                title="Conversation history"
                aria-label="Open history"
              >
                <History size={18} />
              </button>
              {sending && abortController && (
                <Button variant="danger" size="sm" onClick={abortGeneration} className="!py-1.5 !px-2.5 gap-1">
                  <Square size={12} /> Stop
                </Button>
              )}
              <Button variant="secondary" size="sm" onClick={clearChat} className="!py-1.5 !px-2.5 gap-1">
                <Trash2 size={14} />
                <span className="hidden sm:inline">{t('chat.clear')}</span>
              </Button>
            </div>
          </div>

          <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-thin">
            <Select
              label=""
              value={selectedModel}
              onChange={(e) => handleModelChange(e.target.value)}
              options={models.map((m) => ({ value: m.id, label: `${m.id}${m.role ? ` (${m.role})` : ''}` }))}
              disabled={models.length === 0 || modelLoading}
              hint={modelLoading ? t('chat.loadingModel') : (models.length === 0 ? t('chat.noModels') : '')}
              className="!w-auto min-w-[180px]"
            />
            <Select
              label=""
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
              options={[{ value: '', label: t('chat.noAgent') }, ...agents.map((a) => ({ value: a.name, label: a.name }))]}
              className="!w-auto min-w-[140px]"
            />
            <Select
              label=""
              value={selectedSkill}
              onChange={(e) => setSelectedSkill(e.target.value)}
              options={[{ value: '', label: t('chat.noSkill') }, ...skills.map((s) => ({ value: s.name, label: s.name }))]}
              className="!w-auto min-w-[140px]"
            />
            <Select
              label=""
              value={selectedWorkspace}
              onChange={(e) => handleWorkspaceChange(e.target.value)}
              options={workspaces.map((w) => ({ value: w.id, label: w.name }))}
              className="!w-auto min-w-[140px]"
            />
            <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer whitespace-nowrap rounded-lg px-2 py-1.5 hover:bg-bg-tertiary transition-colors">
              <input id="chat-stream" type="checkbox" checked={streaming} onChange={(e) => setStreaming(e.target.checked)} className="accent-accent" />
              {t('chat.stream')}
            </label>
            <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer whitespace-nowrap rounded-lg px-2 py-1.5 hover:bg-bg-tertiary transition-colors" title="Automatically pick streaming vs batch; streams thinking in real-time">
              <input id="chat-auto-stream" type="checkbox" checked={autoStreaming} onChange={(e) => setAutoStreaming(e.target.checked)} className="accent-accent" />
              <Sparkles size={12} className="text-accent-2" />
              Auto
            </label>
            <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer whitespace-nowrap rounded-lg px-2 py-1.5 hover:bg-bg-tertiary transition-colors" title="Route through the computer agent — shows real terminal-style tool-call traces">
              <input id="chat-agentic" type="checkbox" checked={agenticTools} onChange={(e) => setAgenticTools(e.target.checked)} className="accent-accent" />
              <Terminal size={12} className={agenticTools ? 'text-accent' : 'text-text-muted'} />
              Agentic
            </label>
            <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer whitespace-nowrap rounded-lg px-2 py-1.5 hover:bg-bg-tertiary transition-colors" title="Press Enter to send, Shift+Enter for newline">
              <Keyboard size={12} />
              <span className="hidden sm:inline">Enter to send</span>
            </label>
            <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer whitespace-nowrap rounded-lg px-2 py-1.5 hover:bg-bg-tertiary transition-colors">
              <input id="chat-planning" type="checkbox" checked={planning} onChange={(e) => setPlanning(e.target.checked)} className="accent-accent" />
              <Sparkles size={12} className="text-accent" />
              {t('chat.planning')}
            </label>
          </div>
          <div className="flex items-center gap-1.5 pt-1 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider text-text-muted mr-0.5 hidden sm:inline">Quick</span>
            {(['compact', 'review', 'clear'] as const).map((a) => (
              <button
                key={a}
                onClick={() => runPreset(a)}
                className="chip hover:bg-accent/10 hover:text-accent transition-colors"
                title={`/${a}`}
              >
                /{a}
              </button>
            ))}
          </div>
        </div>

        <div
          ref={messagesRef}
          onScroll={onScroll}
          className={`flex-1 overflow-y-auto px-4 py-6 space-y-4 scrollbar-thin relative ${isDragging ? 'bg-accent-soft/30' : ''}`}
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {isDragging && (
            <div className="fixed inset-0 z-40 flex items-center justify-center bg-bg-primary/85 backdrop-blur-sm">
              <div className="dropzone-overlay border-2 border-dashed rounded-3xl m-6 w-[calc(100%-3rem)] h-[calc(100%-3rem)] flex items-center justify-center pointer-events-none">
                <div className="text-center">
                  <Paperclip size={48} className="text-accent mx-auto mb-3 animate-bounce" />
                  <p className="text-xl font-semibold gradient-text">Drop files to attach</p>
                  <p className="text-sm text-text-muted mt-1">Images, Markdown, Code, and Text files</p>
                </div>
              </div>
            </div>
          )}

          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 p-3 bg-bg-secondary/60 border border-border rounded-xl animate-fade-in">
              {files.map((file, i) => (
                <div key={i} className="flex items-center gap-2 px-2.5 py-1.5 bg-bg-tertiary/80 rounded-xl border border-border text-sm group/file">
                  {file.type.startsWith('image/') && previewUrls[i] ? (
                    <button onClick={() => setPreviewImage({ url: previewUrls[i], name: file.name })} className="shrink-0" title="Preview image">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={previewUrls[i]} alt={file.name} className="w-9 h-9 rounded-lg object-cover border border-border" />
                    </button>
                  ) : (
                    getFileIcon(file)
                  )}
                  <span className="max-w-[140px] truncate">{file.name}</span>
                  <span className="text-[10px] text-text-muted font-mono">{formatBytes(file.size)}</span>
                  <button onClick={() => removeFile(i)} className="text-text-muted hover:text-danger transition-colors ml-1" aria-label="Remove file">
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {messages.length === 0 && !thinking && (
            <EmptyStateCards onSelect={onEmptyCardSelect} />
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`group flex gap-3 animate-fade-in ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {msg.role === 'assistant' && (
                <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white shrink-0 shadow-md mt-1">
                  <Bot size={16} />
                </div>
              )}
              <div className={`max-w-[78%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-gradient-to-r from-accent to-accent-2 text-white rounded-br-md shadow-lg shadow-accent/20'
                  : 'bg-bg-secondary/80 border border-border rounded-bl-md'
              }`}>
                <div className="flex items-center justify-between gap-3 mb-1.5">
                  <span className="text-xs font-medium opacity-80">
                    {msg.role === 'user' ? 'You' : 'Assistant'}
                  </span>
                  <MessageToolbar
                    role={msg.role === 'system' ? 'assistant' : msg.role}
                    content={msg.content}
                    feedback={feedback[i] || null}
                    onEdit={msg.role === 'user' ? () => startEdit(i) : undefined}
                    onDelete={() => deleteMessage(i)}
                    onBranch={msg.role === 'user' ? branchConversation : undefined}
                    onRegenerate={msg.role === 'assistant' ? () => regenerateFrom(i) : undefined}
                    onReadAloud={msg.role === 'assistant' ? () => readAloud(msg.content) : undefined}
                    onFeedback={msg.role === 'assistant' ? (k) => setFeedbackFor(i, k) : undefined}
                    onCopyRaw={() => { navigator.clipboard.writeText(msg.content); addToast('Copied raw markdown', 'success'); }}
                    onCopyClean={() => { navigator.clipboard.writeText(stripMarkdown(msg.content)); addToast('Copied clean text', 'success'); }}
                  />
                </div>
                {editingIndex === i ? (
                  <div className="flex flex-col gap-2">
                    <textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      className="w-full bg-bg-primary/80 border border-accent/40 rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none resize-none"
                      rows={3}
                      autoFocus
                    />
                    <div className="flex gap-2 justify-end">
                      <Button size="sm" variant="secondary" onClick={() => setEditingIndex(null)}>Cancel</Button>
                      <Button size="sm" onClick={saveEdit}>Save & resend</Button>
                    </div>
                  </div>
                ) : (
                  <>
                    {agenticActive && i === messages.length - 1 && liveToolCalls.length > 0 && (
                      <div className="space-y-1.5 mb-2">
                        {liveToolCalls.map((call) => (
                          <ToolCallCard key={call.id} call={call} />
                        ))}
                      </div>
                    )}
                    <div className={`whitespace-pre-wrap break-words ${msg.role === 'assistant' && sending && i === messages.length - 1 ? 'streaming-caret' : ''}`}>
                      <MarkdownContent content={msg.content} />
                    </div>
                  </>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-xl bg-bg-tertiary flex items-center justify-center text-text-secondary shrink-0 mt-1">
                  <User size={16} />
                </div>
              )}
            </div>
          ))}

          {thinking && (
            autoStreaming || thinkingText ? (
              <ThinkingIndicator isThinking={thinking} thoughtText={thinkingText || undefined} />
            ) : (
              <div className="flex gap-3 animate-fade-in">
                <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white shrink-0 shadow-md mt-1">
                  <Bot size={16} />
                </div>
                <div className="bg-bg-secondary/80 border border-border rounded-2xl rounded-bl-md px-4 py-3">
                  {sending && !streaming ? (
                    <div className="flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin text-accent" />
                      <span className="text-xs text-text-muted">{t('chat.thinking')}</span>
                    </div>
                  ) : (
                    <div className="flex gap-1.5">
                      <span className="w-2 h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-2 h-2 bg-accent-2 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-2 h-2 bg-accent-3 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  )}
                </div>
              </div>
            )
          )}
          <div ref={chatEndRef} />
        </div>

        {!atBottom && (
          <button
            onClick={scrollToBottom}
            className="absolute bottom-28 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3.5 py-2 rounded-full bg-accent text-white shadow-lg shadow-accent/30 hover:bg-accent-hover transition-all animate-fade-in"
          >
            <ArrowDown size={15} />
            {newMessageCount > 0 && <span className="text-xs font-medium">{newMessageCount} new</span>}
          </button>
        )}

        <div className="px-5 py-4 border-t border-border bg-bg-secondary/60 backdrop-blur-md">
          <div className="max-w-4xl mx-auto relative">
            {slashOpen && (
              <AutocompletePopover
                items={slashFiltered.map((c) => ({ id: c.id, label: c.label, description: c.description, hint: c.hint, icon: <Slash size={15} /> }))}
                activeIndex={slashIndex}
                onSelect={(it) => { const cmd = SLASH_COMMANDS.find((c) => c.id === it.id); if (cmd) selectSlash(cmd); }}
                onHover={setSlashIndex}
                emptyLabel="No commands"
              />
            )}
            {mentionOpen && (
              <AutocompletePopover
                items={mentionFiltered}
                activeIndex={mentionIndex}
                onSelect={(it) => applyMention(it, inputRef.current?.selectionStart ?? input.length)}
                onHover={setMentionIndex}
                emptyLabel="No matches"
              />
            )}

            {contextChips.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {contextChips.map((chip) => (
                  <span key={chip.id} className="context-chip">
                    {chip.kind === 'web' ? <Globe size={12} /> : chip.kind === 'agent' ? <Bot size={12} /> : chip.kind === 'skill' ? <Sparkles size={12} /> : <AtSign size={12} />}
                    {chip.label}
                    <button onClick={() => setContextChips((prev) => prev.filter((c) => c.id !== chip.id))} className="hover:text-danger transition-colors" aria-label="Remove">
                      <X size={11} />
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className={`flex gap-2.5 items-end rounded-2xl border bg-bg-primary/80 px-2 py-2 transition-all ${
              composerFocused ? 'border-accent/40 shadow-accent/10' : 'border-border'
            }`}>
              <label className="cursor-pointer p-2.5 text-text-muted hover:text-accent hover:bg-accent/10 rounded-xl transition-all shrink-0" title={t('chat.attachFiles')}>
                <Paperclip size={20} />
                <input type="file" multiple className="hidden" onChange={handleFileSelect} disabled={sending || uploading} />
              </label>
              <textarea
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleInputKeyDown}
                onFocus={() => setComposerFocused(true)}
                onBlur={() => setComposerFocused(false)}
                placeholder={t('chat.placeholder')}
                rows={1}
                className="flex-1 bg-transparent border-0 px-1 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none resize-none max-h-48"
                disabled={sending || uploading}
              />
              <div className="flex items-center gap-1 shrink-0 pb-1">
                <button
                  onClick={listening ? stopVoiceInput : startVoiceInput}
                  className={`p-2 rounded-xl transition-all ${listening ? 'text-danger bg-danger/10 animate-pulse' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`}
                  title={listening ? 'Stop voice input' : 'Voice input'}
                >
                  <Mic size={18} />
                </button>
                <button
                  onClick={toggleWebSearch}
                  className={`p-2 rounded-xl transition-all ${contextChips.some((c) => c.kind === 'web') ? 'text-accent bg-accent/10' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`}
                  title="Toggle web search context"
                >
                  <Globe size={18} />
                </button>
                <button
                  onClick={() => setPlanning((p) => !p)}
                  className={`p-2 rounded-xl transition-all ${planning ? 'text-accent bg-accent/10' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`}
                  title="Deep thinking mode"
                >
                  <Brain size={18} />
                </button>
                <Button onClick={sendMessage} disabled={sending || uploading || (!input.trim() && files.length === 0)} className="!px-3.5 !py-2.5 bg-gradient-to-r from-accent to-accent-2 hover:from-accent-hover hover:to-accent-2/80">
                  {sending || uploading ? <Square size={18} /> : <Send size={18} />}
                </Button>
              </div>
            </div>
            <div className="flex items-center justify-between mt-1.5 px-1">
              <span className="text-[10px] text-text-muted flex items-center gap-2">
                <span><Keyboard size={10} className="inline" /> Enter to send</span>
                <span>Shift + Enter for newline</span>
                <span className="text-accent/70">/ commands · @ mentions</span>
              </span>
              <span className={`text-[10px] font-mono ${tokenEstimate > MAX_TOKENS ? 'text-danger' : 'text-text-muted'}`}>
                {tokenEstimate} / {MAX_TOKENS} tokens
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="w-72 border-l border-border bg-bg-secondary/40 p-4 hidden xl:flex flex-col overflow-hidden">
        <div className="flex items-center justify-between mb-3 px-0.5">
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">{t('chat.conversations')}</h3>
          <div className="flex gap-1">
            <button
              onClick={exportConversation}
              className="p-1.5 rounded-lg text-text-secondary hover:text-accent hover:bg-accent/10 transition-all"
              title="Export current conversation"
            >
              <Download size={15} />
            </button>
            <button
              onClick={createNewChat}
              className="p-1.5 rounded-lg text-text-secondary hover:text-accent hover:bg-accent/10 transition-all"
              title={t('chat.newChat')}
            >
              <Plus size={16} />
            </button>
            {conversations.length > 0 && (
              <button
                onClick={clearAllConversations}
                className="p-1.5 rounded-lg text-text-secondary hover:text-danger hover:bg-danger/10 transition-all"
                title={t('chat.clearAll')}
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </div>
        <ConversationsPanel
          conversations={conversations}
          convId={convId}
          selectedWorkspace={selectedWorkspace}
          onSelect={(id) => { loadHistory(id); setDrawerOpen(false); }}
          onDelete={deleteConversation}
          onExport={(title, msgs) => setExportTarget({ title, messages: msgs, convId: undefined })}
        />
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 xl:hidden">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setDrawerOpen(false)} />
          <div
            className="absolute inset-y-0 right-0 w-[85%] max-w-sm bg-bg-secondary border-l border-border shadow-2xl animate-slide-in-right flex flex-col"
            onTouchStart={(e) => { touchStartX.current = e.touches[0].clientX; }}
            onTouchEnd={(e) => {
              if (touchStartX.current !== null) {
                const dx = e.changedTouches[0].clientX - touchStartX.current;
                if (dx < -60) setDrawerOpen(false);
              }
              touchStartX.current = null;
            }}
          >
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">{t('chat.conversations')}</h3>
              <div className="flex gap-1">
                <button
                  onClick={exportConversation}
                  className="p-1.5 rounded-lg text-text-secondary hover:text-accent hover:bg-accent/10 transition-all"
                  title="Export current conversation"
                >
                  <Download size={15} />
                </button>
                <button
                  onClick={createNewChat}
                  className="p-1.5 rounded-lg text-text-secondary hover:text-accent hover:bg-accent/10 transition-all"
                  title={t('chat.newChat')}
                >
                  <Plus size={16} />
                </button>
                {conversations.length > 0 && (
                  <button
                    onClick={clearAllConversations}
                    className="p-1.5 rounded-lg text-text-secondary hover:text-danger hover:bg-danger/10 transition-all"
                    title={t('chat.clearAll')}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
                <button
                  onClick={() => setDrawerOpen(false)}
                  className="p-1.5 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-all"
                  aria-label="Close history"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
            <div className="flex-1 h-[calc(100dvh-3.5rem)]">
              <ConversationsPanel
                conversations={conversations}
                convId={convId}
                selectedWorkspace={selectedWorkspace}
                onSelect={(id) => { loadHistory(id); setDrawerOpen(false); }}
                onDelete={deleteConversation}
                onExport={(title, msgs) => { setExportTarget({ title, messages: msgs, convId: undefined }); setDrawerOpen(false); }}
              />
            </div>
          </div>
        </div>
      )}

      {previewImage && (
        <ImagePreviewModal url={previewImage.url} name={previewImage.name} onClose={() => setPreviewImage(null)} />
      )}

      {exportTarget && (
        <ExportModal
          open
          title={exportTarget.title}
          messages={exportTarget.messages}
          convId={exportTarget.convId}
          onClose={() => setExportTarget(null)}
        />
      )}
    </div>
  );
}
