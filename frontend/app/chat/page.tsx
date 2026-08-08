'use client';

import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { fetchJSON, toArray, toText, api, autoStreamChat, uploadChatFile, computerStream, workflowStream, ensureMsgId, type ModelItem, type ChatMessage, type Agent, type Skill, type Workspace, type StreamEvent, type ComputerToolEvent, type WorkflowEvent } from '@/lib/api';
import { getStorage, setStorageValue, removeStorageValue } from '@/lib/storage';
import { useToast } from '@/components/providers/ToastProvider';
import { useTheme } from '@/components/ThemeProvider';
import ScrollToBottomButton from '@/components/chat/ScrollToBottomButton';
import DragOverlay from '@/components/chat/DragOverlay';
import FileChips from '@/components/chat/FileChips';
import ContextChips from '@/components/chat/ContextChips';
import ModesPopover from '@/components/chat/ModesPopover';
import MessageBubble from '@/components/chat/MessageBubble';
import Composer from '@/components/chat/Composer';
import ChatHeader from '@/components/chat/ChatHeader';
import MessagesArea from '@/components/chat/MessagesArea';
import ChatSidebar from '@/components/chat/ChatSidebar';
import MobileDrawer from '@/components/chat/MobileDrawer';
import ImagePreviewModal from '@/components/chat/ImagePreviewModal';
import ExportModal from '@/components/chat/ExportModal';
import EmptyStateCards from '@/components/chat/EmptyStateCards';
import MessageToolbar from '@/components/chat/MessageToolbar';
import ConversationsPanel from '@/components/chat/ConversationsPanel';
import ToolCallCard, { type ToolCall } from '@/components/chat/ToolCallCard';
import AgentTrace, { type TraceAction } from '@/components/chat/AgentTrace';
import ThinkingIndicator from '@/components/ThinkingIndicator';
import MarkdownContent from '@/components/chat/MarkdownContent';
import CodeBlock from '@/components/chat/CodeBlock';
import Select from '@/components/ui/Select';
import Button from '@/components/ui/Button';
import AutocompletePopover, { type AutocompleteItem } from '@/components/chat/AutocompletePopover';
import {
  MessageSquare, Plus, X, History, Trash2, Square, Check, Slash,
  FileText, Sparkles, Bot, Send, Keyboard, Loader2, ArrowDown, Mic, Globe, Brain,
  User, Paperclip, FileImage, FileCode, SlidersHorizontal, AtSign, Download,
} from 'lucide-react';
import { t } from '@/lib/i18n';
import {
  MAX_TOKENS, estimateTokens, stripMarkdown, getTrigger, formatBytes,
  SLASH_COMMANDS, type SlashCommand, type ContextChip,
} from '@/lib/chatUtils';

const STORAGE_KEYS = {
  model: 'chat_model',
  workspace: 'chat_workspace',
  messages: 'chat_messages',
  convId: 'chat_conv_id',
};


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
  const abortControllerRef = useRef<AbortController | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [exportTarget, setExportTarget] = useState<{ title: string; messages: ChatMessage[]; convId?: string } | null>(null);
  const [composerFocused, setComposerFocused] = useState(false);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  // Modes popover (stream / auto / agentic / planning)
  const [modesOpen, setModesOpen] = useState(false);
  const modesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!modesOpen) return;
    function onClick(e: MouseEvent) {
      if (modesRef.current && !modesRef.current.contains(e.target as Node)) setModesOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setModesOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [modesOpen]);

  // Agentic tools mode (computer agent)
  const [agenticTools, setAgenticTools] = useState(false);
  const [codeAgent, setCodeAgent] = useState(false);
  const [liveToolCalls, setLiveToolCalls] = useState<ToolCall[]>([]);
  const [liveActions, setLiveActions] = useState<TraceAction[]>([]);
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
  const filesFetchedForWs = useRef<string | null>(null);

  // Image preview
  const [previewImage, setPreviewImage] = useState<{ url: string; name: string } | null>(null);
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);

  // Message toolbar state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [feedback, setFeedback] = useState<Record<string, 'up' | 'down'>>({});

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
    return () => urls.filter(Boolean).forEach((u) => URL.revokeObjectURL(u));
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
    const urlConvId = new URLSearchParams(window.location.search).get('conv') || '';
    const savedConvId = urlConvId || getStorage<string>(STORAGE_KEYS.convId, '');
    const urlAgent = new URLSearchParams(window.location.search).get('agent') || '';

    let mounted = true;
    async function load() {
      try {
        const [a, s, w] = await Promise.all([
          fetchJSON('/v1/agents'),
          fetchJSON('/v1/skills'),
          fetchJSON('/v1/workspaces'),
        ]);
        if (!mounted) return;
        const agentList = toArray<Agent>(a);
        setAgents(agentList);
        setSkills(toArray<Skill>(s));
        const wsList = toArray<Workspace>(w);
        setWorkspaces(wsList);
        if (urlAgent) {
          if (agentList.some((ag) => ag.name === urlAgent)) setSelectedAgent(urlAgent);
        }
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
      chatEndRef.current?.scrollIntoView({ behavior: (sending || streaming || autoStreaming || agenticActive) ? 'auto' : 'smooth' });
      setNewMessageCount(0);
    } else if (messages.length > prevMsgLen.current) {
      setNewMessageCount((c) => c + (messages.length - prevMsgLen.current));
    }
    prevMsgLen.current = messages.length;
  }, [messages, thinking, atBottom, sending, streaming, autoStreaming, agenticActive]);

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
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
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
    if (pendingAction !== 'clear') {
      setPendingAction('clear');
      return;
    }
    setPendingAction(null);
    await doClearChat();
  }

  async function doClearChat() {
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
    await doClearChat();
  }

  async function deleteConversation(id: string) {
    if (pendingAction !== `delete-${id}`) {
      setPendingAction(`delete-${id}`);
      return;
    }
    setPendingAction(null);
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
    if (pendingAction !== 'clear-all') {
      setPendingAction('clear-all');
      return;
    }
    setPendingAction(null);
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
    abortControllerRef.current = controller;
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
        setMessages([...history.map(ensureMsgId), ensureMsgId({ role: 'assistant', content: '' })]);
        let assistantText = '';
        let assistantModel: string | undefined;
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
              if (evt.model) assistantModel = evt.model;
              setMessages(prev => {
                const next = [...prev];
                const last = next[next.length - 1];
                next[next.length - 1] = { ...last, role: 'assistant', content: assistantText };
                return next;
              });
            }
          },
          controller.signal,
        );
        const finalMessages: ChatMessage[] = [...history, { role: 'assistant', content: assistantText, model: assistantModel || selectedModel || undefined }];
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
        let assistantModel: string | undefined;
        let buffer = '';
        setMessages([...history.map(ensureMsgId), ensureMsgId({ role: 'assistant', content: '' })]);
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
                if (evt.model) assistantModel = evt.model;
                setMessages(prev => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  next[next.length - 1] = { ...last, role: 'assistant', content: assistantText };
                  return next;
                });
              } else if (evt.type === 'thinking' && typeof evt.content === 'string') {
                setThinking(true);
                setThinkingText(evt.content);
              } else if (evt.type === 'start') {
                setThinking(true);
              }
            } catch { /* ignore malformed frames */ }
          }
        }
        const finalMessages: ChatMessage[] = [...history.map(ensureMsgId), ensureMsgId({ role: 'assistant', content: assistantText, model: assistantModel || selectedModel || undefined })];
        persistMessages(finalMessages);
      } else {
        const data = await fetchJSON('/v1/chat/completions', {
          method: 'POST',
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        const choice = (data as { choices?: { message?: ChatMessage }[] }).choices?.[0]?.message;
        if (choice) {
          const assistantMsg: ChatMessage = ensureMsgId({ role: choice.role, content: toText(choice.content), model: (data as { model?: string }).model || selectedModel || undefined });
          const finalMessages = [...history.map(ensureMsgId), assistantMsg];
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
      abortControllerRef.current = null;
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
    abortControllerRef.current = controller;
    setSending(true);
    setThinking(true);
    setAgenticActive(true);
    setLiveToolCalls([]);
    setLiveActions([]);
    nextToolId.current = 0;

    setMessages([...history, { role: 'assistant', content: '' }]);

    let assistantText = '';
    try {
      if (selectedAgent === 'agent_x') {
        await workflowStream(
          goalMsg.content,
          { workspace: selectedWorkspace || 'default', maxSteps: 25, model: selectedModel },
          (evt: WorkflowEvent) => {
            if (evt.type === 'status' && typeof evt.message === 'string') {
              setThinking(true);
              setThinkingText(evt.message);
            } else if (evt.type === 'trace') {
              if (!evt.action) return;
              const actionUpper = evt.action.toUpperCase();
              const id = ++nextToolId.current;
              setLiveActions((prev) => [...prev, {
                id,
                action: actionUpper,
                payload: evt.content || evt.path || '',
                status: 'running',
                step: evt.step,
              }]);
              if (evt.success === false || evt.action) {
                setLiveActions((prev) => {
                  const next = [...prev];
                  for (let i = next.length - 1; i >= 0; i--) {
                    if (next[i].status === 'running') {
                      next[i] = {
                        ...next[i],
                        status: evt.success === false ? 'failed' : 'success',
                        elapsed: evt.elapsed_s,
                      };
                      break;
                    }
                  }
                  return next;
                });
              }
            } else if (evt.type === 'complete') {
              assistantText = evt.result || evt.content || '';
              setThinking(false);
              setThinkingText('');
              setLiveActions((prev) => prev.map((a) => a.status === 'running' ? { ...a, status: 'success' } : a));
              setMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                next[next.length - 1] = { ...last, role: 'assistant', content: assistantText };
                return next;
              });
            }
          },
          controller.signal,
        );
      } else {
        await computerStream(
          goalMsg.content,
          { sandbox: false, maxSteps: 25, protocol: codeAgent ? 'actions' : 'json' },
          (evt: ComputerToolEvent) => {
            if (evt.type === 'thinking' && typeof evt.content === 'string') {
              setThinking(true);
              setThinkingText((prev) => prev + evt.content);
            } else if (evt.type === 'action') {
              const id = ++nextToolId.current;
              setLiveActions((prev) => [...prev, {
                id,
                action: evt.action || 'STEP',
                payload: evt.payload || '',
                status: 'running',
                step: evt.step,
              }]);
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
              setLiveActions((prev) => {
                const next = [...prev];
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].status === 'running') {
                    next[i] = { ...next[i], status: evt.success ? 'success' : 'failed', elapsed: evt.elapsed };
                    break;
                  }
                }
                return next;
              });
            } else if (evt.type === 'complete') {
              assistantText = evt.answer || '';
              setThinking(false);
              setThinkingText('');
              setLiveActions((prev) => prev.map((a) => a.status === 'running' ? { ...a, status: 'success' } : a));
              setMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                next[next.length - 1] = { ...last, role: 'assistant', content: assistantText };
                return next;
              });
            }
          },
          controller.signal,
        );
      }
      const finalMessages: ChatMessage[] = [...history.map(ensureMsgId), ensureMsgId({ role: 'assistant', content: assistantText, model: selectedModel || undefined })];
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
      setLiveToolCalls([]);
      setLiveActions([]);
      abortControllerRef.current = null;
      setContextChips([]);
    }
  }, [sending, modelLoading, thinking, uploading, selectedModel, models, codeAgent, selectedAgent, selectedWorkspace, persistMessages, addToast]);

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

    const userMsg: ChatMessage = ensureMsgId({ role: 'user', content });
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
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setSending(false);
      setThinking(false);
      setThinkingText('');
      setAgenticActive(false);
      setLiveToolCalls([]);
      setLiveActions([]);
    }
  }

  const historyReqSeq = useRef(0);
  async function loadHistory(id: string) {
    const seq = ++historyReqSeq.current;
    try {
      const qs = `?conv_id=${encodeURIComponent(id)}&workspace_id=${encodeURIComponent(selectedWorkspace || 'default')}`;
      const data = await fetchJSON(`/v1/chat/history${qs}`);
      if (seq !== historyReqSeq.current) return; // a newer selection won the race
      const history = toArray<ChatMessage>(data).map(ensureMsgId);
      persistMessages(history);
      persistConvId(id);
      const conv = conversations.find((c) => c.id === id);
      if (conv?.title) setCurrentConvTitle(conv.title);
      addToast(t('chat.historyLoaded'), 'success');
    } catch {
      if (seq === historyReqSeq.current) {
        addToast(t('chat.failedToLoadHistory'), 'error');
      }
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
    if (filesFetchedForWs.current === selectedWorkspace) return;
    filesFetchedForWs.current = selectedWorkspace;
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
        addToast('Commands: /clear Â· /compact Â· /review Â· /test Â· /model Â· /help', 'success');
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
    return trigger?.type === 'mention' ? trigger.query.toLowerCase() : '';
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (files && files.length > 0) {
      setFiles((prev) => [...prev, ...Array.from(files)]);
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
    const msg = messages[index];
    if (!msg) return;
    setEditingId(msg.id ?? null);
    setEditText(msg.content);
  }

  function saveEdit() {
    if (editingId === null) return;
    const idx = messages.findIndex((m) => m.id === editingId);
    if (idx === -1) {
      setEditingId(null);
      return;
    }
    const next = messages.slice(0, idx + 1);
    next[idx] = { ...messages[idx], content: editText };
    persistMessages(next);
    setEditingId(null);
    setEditText('');
  }

  function deleteMessage(index: number) {
    persistMessages(messages.filter((_, i) => i !== index));
  }

  function branchConversation() {
    setConvId('');
    removeStorageValue(STORAGE_KEYS.convId);
    addToast('Branched â€” next send starts a new conversation', 'success');
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

  function setFeedbackFor(id: string, kind: 'up' | 'down') {
    setFeedback((prev) => ({ ...prev, [id]: kind }));
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
        <div className="px-4 py-3 border-b border-border bg-bg-secondary/60 backdrop-blur-md">
          <div className="flex items-center justify-between gap-3">
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
                  <div className="hidden sm:flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-full border border-border bg-bg-tertiary/60" title={`${selectedModel} Â· ${modelLoaded ? 'loaded' : 'not loaded'}${Array.isArray(activeModel?.capabilities) && activeModel.capabilities.length ? ' Â· ' + activeModel.capabilities.slice(0, 3).join(', ') : ''}`}>
                    <span className={`w-2 h-2 rounded-full ${modelLoaded ? 'bg-success shadow-[0_0_6px] shadow-success/70' : 'bg-text-muted'}`} />
                    <span className="text-text-secondary">{modelLoaded ? 'Warm' : 'Cold'}</span>
                    {modelCtx && <span className="text-text-muted">Â· {modelCtx} ctx</span>}
                    <span className="text-text-muted capitalize hidden lg:inline">Â· {activeModel?.role || 'model'}</span>
                    {Array.isArray(activeModel?.capabilities) && activeModel.capabilities.length ? <span className="text-text-muted hidden lg:inline">Â· {activeModel.capabilities[0]}</span> : null}
                  </div>
                  <div className="hidden md:flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-full border border-border bg-bg-tertiary/60 text-text-secondary font-mono" title="Estimated session token usage & cost">
                    <span>{sessionCost < 0.01 ? `$${sessionCost.toFixed(4)}` : `$${sessionCost.toFixed(2)}`}</span>
                    <span className="text-text-muted">Â· {(sessionTokens / 1000).toFixed(1)}k tok</span>
                  </div>
                </>
              )}
              <button
                onClick={createNewChat}
                className="flex items-center gap-1.5 p-2 rounded-xl text-text-secondary hover:text-accent hover:bg-accent/10 transition-colors text-xs font-medium"
                title={t('chat.newChat')}
              >
                <Plus size={16} />
                <span className="hidden sm:inline">New</span>
              </button>
              <button
                onClick={() => setDrawerOpen(true)}
                className="xl:hidden p-2 rounded-xl text-text-secondary hover:text-accent hover:bg-accent/10 transition-colors"
                title="Conversation history"
                aria-label="Open history"
              >
                <History size={18} />
              </button>
              {sending && abortControllerRef.current && (
                <Button variant="danger" size="sm" onClick={abortGeneration} className="!py-1.5 !px-2.5 gap-1">
                  <Square size={12} /> Stop
                </Button>
              )}
              {pendingAction === 'clear' ? (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-text-secondary">Confirm?</span>
                  <Button variant="danger" size="sm" onClick={clearChat} className="!py-1.5 !px-2.5 gap-1 text-xs">Yes</Button>
                  <Button variant="secondary" size="sm" onClick={() => setPendingAction(null)} className="!py-1.5 !px-2.5 gap-1 text-xs">No</Button>
                </div>
              ) : (
                <Button variant="secondary" size="sm" onClick={clearChat} className="!py-1.5 !px-2.5 gap-1">
                  <Trash2 size={14} />
                  <span className="hidden sm:inline">{t('chat.clear')}</span>
                </Button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 mt-2.5 overflow-x-auto pb-0.5 scrollbar-thin">
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
            <div className="relative shrink-0" ref={modesRef}>
              <button
                onClick={() => setModesOpen((v) => !v)}
                className={`flex items-center gap-1.5 text-xs rounded-xl px-2.5 py-1.5 border transition-colors whitespace-nowrap ${
                  modesOpen || planning || streaming || autoStreaming || agenticTools || codeAgent
                    ? 'border-accent/30 text-accent bg-accent/10'
                    : 'border-border text-text-secondary hover:bg-bg-tertiary'
                }`}
                aria-expanded={modesOpen}
              >
                <SlidersHorizontal size={13} />
                <span className="hidden sm:inline">Modes</span>
                {(planning || streaming || autoStreaming || agenticTools || codeAgent) && (
                  <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                )}
              </button>
              {modesOpen && (
                <div className="absolute left-0 top-full mt-1.5 w-60 glass-card p-1.5 z-30 animate-fade-in rounded-xl">
                  <div className="px-2 pt-1 pb-1.5 text-[10px] uppercase tracking-wider text-text-muted font-semibold">Generation modes</div>
                  {[
                    { key: 'stream', label: t('chat.stream'), checked: streaming, set: setStreaming, desc: 'Stream tokens in real time' },
                    { key: 'auto', label: 'Auto stream', checked: autoStreaming, set: setAutoStreaming, desc: 'Auto-pick streaming vs batch; live thinking' },
                    { key: 'agentic', label: 'Agentic', checked: agenticTools, set: setAgenticTools, desc: 'Computer agent with tool-call traces' },
                    { key: 'code', label: 'Code Agent', checked: codeAgent, set: (v: boolean) => { setCodeAgent(v); if (v) setAgenticTools(true); }, desc: 'GBNF-forced [BASH]/[READ]/[WRITE]/[DONE] loop + auto env scan' },
                    { key: 'planning', label: t('chat.planning'), checked: planning, set: setPlanning, desc: 'Strategist drafts a plan first' },
                  ].map((m) => (
                    <label key={m.key} className="flex items-start gap-2.5 rounded-xl px-2 py-1.5 cursor-pointer hover:bg-bg-tertiary transition-colors" title={m.desc}>
                      <input
                        type="checkbox"
                        checked={m.checked}
                        onChange={(e) => m.set(e.target.checked)}
                        className="accent-accent mt-0.5 shrink-0"
                      />
                      <span className="flex flex-col min-w-0">
                        <span className="text-xs font-medium text-text-primary">{m.label}</span>
                        <span className="text-[10px] text-text-muted leading-snug">{m.desc}</span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1.5 pt-1.5 flex-wrap">
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
          <DragOverlay visible={isDragging} />
          <FileChips files={files} previewUrls={previewUrls} onRemove={removeFile} onPreviewImage={(url, name) => setPreviewImage({ url, name })} />

          {messages.length === 0 && !thinking && (
            <EmptyStateCards onSelect={onEmptyCardSelect} />
          )}

          {messages.map((msg, i) => (
            <div
              key={msg.id ?? i}
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
                    {msg.role === 'assistant' && msg.model && (
                      <span className="text-text-muted opacity-90 font-normal ml-1.5">Â· {msg.model}</span>
                    )}
                  </span>
                  <MessageToolbar
                    role={msg.role === 'system' ? 'assistant' : msg.role}
                    content={msg.content}
                    feedback={msg.id ? feedback[msg.id] || null : null}
                    onEdit={msg.role === 'user' ? () => startEdit(i) : undefined}
                    onDelete={() => deleteMessage(i)}
                    onBranch={msg.role === 'user' ? branchConversation : undefined}
                    onRegenerate={msg.role === 'assistant' ? () => regenerateFrom(i) : undefined}
                    onReadAloud={msg.role === 'assistant' ? () => readAloud(msg.content) : undefined}
                    onFeedback={msg.role === 'assistant' ? (k) => setFeedbackFor(msg.id ?? String(i), k) : undefined}
                    onCopyRaw={() => { navigator.clipboard.writeText(msg.content); addToast('Copied raw markdown', 'success'); }}
                    onCopyClean={() => { navigator.clipboard.writeText(stripMarkdown(msg.content)); addToast('Copied clean text', 'success'); }}
                  />
                </div>
                {editingId === (msg.id ?? String(i)) ? (
                  <div className="flex flex-col gap-2">
                    <textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      className="w-full bg-bg-primary/80 border border-accent/40 rounded-xl px-3 py-2 text-sm text-text-primary focus:outline-none resize-none"
                      rows={3}
                      autoFocus
                    />
                    <div className="flex gap-2 justify-end">
                      <Button size="sm" variant="secondary" onClick={() => setEditingId(null)}>Cancel</Button>
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

          {codeAgent && (agenticActive || liveActions.length > 0) && (
            <AgentTrace actions={liveActions} active={agenticActive} />
          )}

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

        <ScrollToBottomButton visible={!atBottom} onClick={scrollToBottom} newMessageCount={newMessageCount} />

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

            <div className={`flex gap-1.5 items-end rounded-2xl border bg-bg-primary/90 px-2 py-2 transition-all ${
              composerFocused ? 'border-accent/50 shadow-lg shadow-accent/10 ring-1 ring-accent/20' : 'border-border hover:border-text-muted/30'
            }`}>
              <label className="cursor-pointer p-2.5 text-text-muted hover:text-accent hover:bg-accent/10 rounded-xl transition-all shrink-0" title={t('chat.attachFiles')}>
                <Paperclip size={19} />
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
                className="flex-1 bg-transparent border-0 px-1 py-3 text-sm text-text-primary placeholder:text-text-muted focus:outline-none resize-none max-h-48"
                disabled={sending || uploading}
              />
              <div className="flex items-center gap-0.5 shrink-0 pb-1">
                <button
                  onClick={listening ? stopVoiceInput : startVoiceInput}
                  className={`p-2.5 rounded-xl transition-all ${listening ? 'text-danger bg-danger/10 animate-pulse' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`}
                  title={listening ? 'Stop voice input' : 'Voice input'}
                >
                  <Mic size={18} />
                </button>
                <button
                  onClick={toggleWebSearch}
                  className={`p-2.5 rounded-xl transition-all ${contextChips.some((c) => c.kind === 'web') ? 'text-accent bg-accent/10' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`}
                  title="Toggle web search context"
                >
                  <Globe size={18} />
                </button>
                <button
                  onClick={() => setPlanning((p) => !p)}
                  className={`p-2.5 rounded-xl transition-all ${planning ? 'text-accent bg-accent/10' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`}
                  title="Deep thinking mode"
                >
                  <Brain size={18} />
                </button>
                <Button onClick={sendMessage} disabled={sending || uploading || (!input.trim() && files.length === 0)} className="!px-3.5 !py-2.5 ml-1 bg-gradient-to-r from-accent to-accent-2 hover:from-accent-hover hover:to-accent-2/80 shadow-md shadow-accent/20">
                  {sending || uploading ? <Square size={18} /> : <Send size={18} />}
                </Button>
              </div>
            </div>
            <div className="flex items-center justify-between mt-1.5 px-1">
              <span className="text-[10px] text-text-muted flex items-center gap-2">
                <span><Keyboard size={10} className="inline" /> Enter to send</span>
                <span className="hidden sm:inline">Shift + Enter for newline</span>
                <span className="hidden md:inline text-accent/70">/ commands Â· @ mentions</span>
                {selectedModel && (
                  <span className="hidden lg:inline text-text-secondary truncate max-w-[220px]">
                    â†’ {activeModel?.role ? `${activeModel.role}: ` : ''}{selectedModel}
                  </span>
                )}
              </span>
              <span className={`text-[10px] font-mono shrink-0 ${tokenEstimate > MAX_TOKENS ? 'text-danger' : 'text-text-muted'}`}>
                {tokenEstimate} / {MAX_TOKENS} tokens
              </span>
            </div>
          </div>
        </div>
      </div>

      <ChatSidebar
        conversations={conversations}
        convId={convId}
        selectedWorkspace={selectedWorkspace}
        pendingAction={pendingAction}
        onSelect={loadHistory}
        onDelete={deleteConversation}
        onExport={exportConversation}
        onNewChat={createNewChat}
        onClearAll={clearAllConversations}
      />

      <MobileDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        conversations={conversations}
        convId={convId}
        selectedWorkspace={selectedWorkspace}
        pendingAction={pendingAction}
        onSelect={loadHistory}
        onDelete={deleteConversation}
        onExport={exportConversation}
        onNewChat={createNewChat}
        onClearAll={clearAllConversations}
      />

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

