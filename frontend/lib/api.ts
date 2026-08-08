export function getApiBase(): string {
  if (typeof window !== 'undefined') {
    const runtimeOverride = (window as unknown as Record<string, string | undefined>).NEXT_PUBLIC_API_BASE;
    if (runtimeOverride) return runtimeOverride.replace(/\/$/, '');
    const envBase = process.env.NEXT_PUBLIC_API_BASE;
    if (envBase) return envBase.replace(/\/$/, '');
    return window.location.origin;
  }
  return process.env.NEXT_PUBLIC_API_BASE || '';
}

import { loadAuth } from '@/lib/auth';

export async function api(path: string, options: RequestInit = {}, timeout = 60000, signal?: AbortSignal): Promise<Response> {
  const base = getApiBase();
  const url = `${base}${path.startsWith('/') ? path : `/${path}`}`;
  
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  
  let token = '';
  let adminKey = '';
  if (typeof window !== 'undefined') {
    const auth = loadAuth();
    token = auth.apiToken || (window as unknown as Record<string, string | undefined>).API_TOKEN || '';
    adminKey = auth.adminKey || (window as unknown as Record<string, string | undefined>).ADMIN_KEY || '';
  }
  
  if (signal) {
    const onAbort = () => controller.abort();
    signal.addEventListener('abort', onAbort, { once: true });
  }
  
  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(adminKey ? { 'X-Admin-Key': adminKey } : {}),
        ...options.headers,
      },
      signal: controller.signal,
    });
    
    if (res.status === 401 && typeof window !== 'undefined') {
      delete (window as unknown as Record<string, string | undefined>).API_TOKEN;
    }
    
    return res;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchJSON<T = unknown>(path: string, options?: RequestInit & { timeout?: number }): Promise<T> {
  const timeout = options?.timeout ?? 60000;
  const rest: RequestInit = { ...options };
  delete (rest as RequestInit & { timeout?: number }).timeout;
  const res = await api(path, rest, timeout);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function toText(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v == null) return '';
  try { return JSON.stringify(v); } catch { return typeof v === 'object' ? JSON.stringify(Object.prototype.toString.call(v)) : String(v); }
}

export function toArray<T>(v: unknown): T[] {
  if (Array.isArray(v)) return v as T[];
  if (v && typeof v === 'object') {
    const obj = v as Record<string, unknown>;
    for (const key of ['data', 'nodes', 'results', 'conversations', 'agents', 'skills', 'logs', 'datasets', 'models', 'messages', 'tags', 'workspaces', 'files', 'memories', 'edges']) {
      if (key in obj && Array.isArray((obj as Record<string, unknown>)[key])) {
        return (obj as Record<string, T[]>)[key];
      }
    }
  }
  return [];
}

export interface ModelItem {
  id: string;
  role?: string;
  loaded?: boolean;
  capabilities?: string[];
  [key: string]: unknown;
}

export interface InstalledModel {
  filename: string;
  path: string;
  size_mb: number;
  size_bytes: number;
}

export interface ChatMessage {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  model?: string;
}

/** Return the message with a stable id attached (memoized-safe, no-op if present). */
export function ensureMsgId<T extends ChatMessage>(msg: T): T {
  if (msg.id) return msg;
  return { ...msg, id: typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `m-${Date.now()}-${Math.random().toString(36).slice(2)}` };
}

export interface StreamEvent {
  type: 'start' | 'thinking' | 'response' | 'done' | 'error' | 'tool_call';
  content?: string;
  model?: string;
  tool?: string;
  args?: Record<string, unknown>;
  tokens?: number;
  elapsed?: number;
}

/** Yield parsed JSON payloads from an SSE body stream (handles multi-byte UTF-8 splits). */
export async function* readSSE<T = Record<string, unknown>>(res: Response): AsyncGenerator<T> {
  const reader = res.body?.getReader();
  if (!reader) throw new Error('No stream reader');
  const decoder = new TextDecoder();
  let buffer = '';
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
      let evt: T;
      try {
        evt = JSON.parse(payload) as T;
      } catch {
        continue;
      }
      yield evt;
    }
  }
}

export async function autoStreamChat(
  messages: ChatMessage[],
  model?: string,
  workspace_id?: string,
  planning?: boolean,
  onEvent?: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<string> {
  const res = await api('/v1/chat/auto-stream', {
    method: 'POST',
    body: JSON.stringify({
      model: model || '',
      messages,
      workspace_id: workspace_id || 'default',
      use_planning: planning !== undefined ? planning : true,
      stream: true,
    }),
  }, 300000, signal);

  if (!res.ok) {
    throw new Error(`Stream failed: ${res.status}`);
  }

  let assistantText = '';
  for await (const evt of readSSE<StreamEvent>(res)) {
    if (evt.type === 'response' && typeof evt.content === 'string') {
      assistantText += evt.content;
    }
    if (evt.type === 'error') {
      throw new Error(evt.content || 'Stream error');
    }
    if (onEvent) onEvent(evt);
  }
  return assistantText;
}

export interface ComputerToolEvent {
  type: 'thinking' | 'tool_call' | 'action' | 'complete' | 'error' | 'done';
  content?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  success?: boolean;
  step?: number;
  elapsed?: number;
  answer?: string;
  action?: string;
  payload?: string;
  protocol?: string;
}

export interface WorkflowEvent {
  type: 'plan' | 'trace' | 'complete' | 'error' | 'status';
  content?: string;
  action?: string;
  path?: string;
  result?: string;
  success?: boolean;
  error?: string;
  step?: number;
  elapsed_s?: number;
  message?: string;
}

export async function computerStream(
  goal: string,
  opts: { sandbox?: boolean; maxSteps?: number; protocol?: 'json' | 'actions' },
  onEvent?: (event: ComputerToolEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await api('/v1/computer/stream', {
    method: 'POST',
    body: JSON.stringify({
      goal,
      sandbox: opts.sandbox ?? false,
      max_steps: opts.maxSteps ?? 25,
      protocol: opts.protocol ?? 'json',
    }),
  }, 600000, signal);

  if (!res.ok) {
    throw new Error(`Computer stream failed: ${res.status}`);
  }

  for await (const evt of readSSE<ComputerToolEvent>(res)) {
    if (evt.type === 'error') {
      throw new Error(evt.content || 'Computer agent error');
    }
    if (onEvent) onEvent(evt);
  }
}

export async function workflowStream(
  goal: string,
  opts: { workspace?: string; maxSteps?: number; model?: string },
  onEvent?: (event: WorkflowEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await api('/v1/chat/auto-stream/workflow', {
    method: 'POST',
    body: JSON.stringify({
      messages: [{ role: 'user', content: goal }],
      model: opts.model || '',
      workspace_id: opts.workspace || 'default',
      max_tokens: opts.maxSteps ?? 25,
      stream: true,
    }),
  }, 600000, signal);

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Workflow stream failed: ${res.status}${text ? ' - ' + text.slice(0, 200) : ''}`);
  }

  for await (const evt of readSSE<WorkflowEvent>(res)) {
    if (evt.type === 'error') {
      throw new Error(evt.content || evt.message || 'Workflow error');
    }
    if (onEvent) onEvent(evt);
  }
}

export interface SystemInfo {
  [key: string]: unknown;
}

export interface Metrics {
  [key: string]: unknown;
}

export interface HardwareInfo {
  cpu_cores: number;
  cpu_name?: string;
  ram_total_mb: number;
  ram_available_mb: number;
  gpu_name?: string;
  gpu_vram_mb: number;
  gpu_vram_used_mb: number;
  gpu_backend: string;
  cpu_utilization: number;
  detected_at: number;
}

export interface RouterStats {
  [key: string]: unknown;
}

export interface Agent {
  name: string;
  role?: string;
  description?: string;
  [key: string]: unknown;
}

export interface Skill {
  name: string;
  description?: string;
  [key: string]: unknown;
}

export interface Workspace {
  id: string;
  name: string;
  description?: string;
  [key: string]: unknown;
}

export interface DbStats {
  [key: string]: unknown;
}

export interface GraphStats {
  [key: string]: unknown;
}

export interface GraphNode {
  id: string;
  title: string;
  node_type?: string;
  [key: string]: unknown;
}

export async function uploadChatFile(file: File): Promise<{ url: string; name: string; preview_text?: string | null }> {
  const formData = new FormData();
  formData.append('file', file);
  let token = '';
  let adminKey = '';
  if (typeof window !== 'undefined') {
    const auth = loadAuth();
    token = auth.apiToken || (window as unknown as Record<string, string | undefined>).API_TOKEN || '';
    adminKey = auth.adminKey || (window as unknown as Record<string, string | undefined>).ADMIN_KEY || '';
  }
  const res = await fetch(`${getApiBase()}/v1/chat/upload`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(adminKey ? { 'X-Admin-Key': adminKey } : {}),
    },
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`Upload failed: ${res.status} - ${text}`);
  }
  return res.json() as Promise<{ url: string; name: string }>;
}

export async function fetchInstalledModels(): Promise<InstalledModel[]> {
  const res = await api('/v1/models/installed');
  if (!res.ok) throw new Error('Failed to fetch installed models');
  const data = await res.json() as { models?: InstalledModel[] };
  return data.models || [];
}

export async function pullModel(url: string, filename?: string): Promise<ReadableStream<Uint8Array>> {
  const res = await api('/v1/models/pull', {
    method: 'POST',
    body: JSON.stringify({ url, filename: filename || '' }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Pull failed: ${res.status}${text ? ' - ' + text.slice(0, 200) : ''}`);
  }
  if (!res.body) throw new Error('No response body');
  return res.body;
}
