'use client';

import React, { useState } from 'react';
import { BookOpen, ShieldCheck, KeyRound, Command, FileCode2, ArrowRight, Copy, Check } from 'lucide-react';
import {
  TerminalCodeIcon, LocalEngineIcon, HubDownloadIcon, SandboxShieldIcon, PulseLineIcon, MemoryMatrixIcon,
} from '@/components/icons';
import Card from '@/components/ui/Card';
import PageHeader from '@/components/ui/PageHeader';
import CopyCode from '@/components/ui/CopyCode';
import Link from 'next/link';

type TabKey = 'cli' | 'api' | 'security';

const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
  { key: 'cli', label: 'CLI Flags & Commands', icon: <TerminalCodeIcon size={15} /> },
  { key: 'api', label: 'REST API Documentation', icon: <FileCode2 size={15} /> },
  { key: 'security', label: 'Security Rules', icon: <ShieldCheck size={15} /> },
];

const CLI_GROUPS: [string, string][] = [
  ['System', '/help · /status · /new · /retry · /clear · /exit'],
  ['Models', '/model · /models · /preload · /unload · /vram'],
  ['Reasoning', '/plan · /think · /harness · /harness reset · /harness adjust · /arc [n]'],
  ['Agents', '/agent · /agents · /skill · /skills · /code · /computer · /lora'],
  ['Generation', '/parallel · /context · /temperature · /max · /timeout · /tokens'],
  ['Conversations', '/save · /load · /sessions'],
  ['Cloud & memory', '/openai · /cloud · /db · /prune · /exec'],
  ['MCP tools', '/mcp · /mcp call <tool> <input> · /mcp json'],
];

const QUICK_START = `# 1. Full mode — web UI + CLI + API on one port
python run.py

# 2. Terminal CLI only (what this guide documents)
python run.py cli
python run.py cli --no-auto-load   # instant boot, skip VRAM preload

# 3. API server only (power the page over HTTP)
python run.py api

# 4. Secure it (optional but recommended)
python run.py --api-token secret --admin-key secret
python run.py --sandbox           # force read-only: no DB writes`;

const HF_DOWNLOAD = `pip install "huggingface_hub[cli]"
huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF \\
  qwen2.5-3b-instruct-q4_k_m.gguf --local-dir models/

# Any GGUF dropped in models/ auto-registers; or register from anywhere:
python run.py --add-model PATH --add-model-name NAME --add-model-role Executor`;

interface ApiEndpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  path: string;
  desc: string;
  params: string[];
  example: string;
}

const METHOD_STYLES: Record<ApiEndpoint['method'], string> = {
  GET: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  POST: 'bg-sky-500/15 text-sky-400 border-sky-500/30',
  PUT: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  DELETE: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  PATCH: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
};

const API_ENDPOINTS: ApiEndpoint[] = [
  {
    method: 'POST',
    path: '/v1/terminal/exec',
    desc: 'Run a sandboxed shell command, returns stdout + exit code.',
    params: ['command'],
    example: `curl -X POST localhost:8070/v1/terminal/exec \\
  -H "Content-Type: application/json" \\
  -d '{"command":"ls"}'`,
  },
  {
    method: 'POST',
    path: '/v1/terminal/python',
    desc: 'Execute editor code as Python, returns stdout + exit code.',
    params: ['code'],
    example: `curl -X POST localhost:8070/v1/terminal/python \\
  -H "Content-Type: application/json" \\
  -d '{"code":"print(6 * 7)"}'`,
  },
  {
    method: 'GET',
    path: '/v1/terminal/fs/tree',
    desc: 'Project file tree, optionally depth-limited.',
    params: ['depth', 'max_nodes'],
    example: `curl -X GET "localhost:8070/v1/terminal/fs/tree?depth=2&max_nodes=200"`,
  },
  {
    method: 'POST',
    path: '/v1/terminal/fs/read',
    desc: 'Open a file, returns its content.',
    params: ['path', 'limit'],
    example: `curl -X POST localhost:8070/v1/terminal/fs/read \\
  -H "Content-Type: application/json" \\
  -d '{"path":"README.md","limit":2000}'`,
  },
  {
    method: 'POST',
    path: '/v1/terminal/fs/write',
    desc: 'Save a file, creating parent folders as needed.',
    params: ['path', 'content'],
    example: `curl -X POST localhost:8070/v1/terminal/fs/write \\
  -H "Content-Type: application/json" \\
  -d '{"path":"scratch.py","content":"print(\"hi\")"}'`,
  },
  {
    method: 'POST',
    path: '/v1/terminal/fs/mkdir',
    desc: 'Create a folder.',
    params: ['path'],
    example: `curl -X POST localhost:8070/v1/terminal/fs/mkdir \\
  -H "Content-Type: application/json" \\
  -d '{"path":"myproject/src"}'`,
  },
  {
    method: 'POST',
    path: '/v1/terminal/fs/delete',
    desc: 'Delete a file or folder (path-traversal proof).',
    params: ['path'],
    example: `curl -X POST localhost:8070/v1/terminal/fs/delete \\
  -H "Content-Type: application/json" \\
  -d '{"path":"scratch.py"}'`,
  },
];

const SECURITY_FLAGS = `# Enforce read-only: no DB writes, isolated conversations
python run.py --sandbox

# Require a Bearer token on /v1/* and /mcp
python run.py --api-token secret

# Require X-Admin-Key for control-plane mutations (config, load/unload)
python run.py --admin-key secret

# Optional hardening
python run.py --no-rate-exempt-local   # rate-limit even 127.0.0.1
python run.py --allow-gui              # enable mouse/keyboard tools (opt-in)`;

const SECURITY_PROTECTIONS: [string, string][] = [
  ['Dangerous shell patterns', 'rm -rf /, mkfs, dd, format … blocked → HTTP 400'],
  ['Path traversal', '.. escape, drive-absolute, UNC and absolute cd rejected'],
  ['File scoping', 'read / list / search are scoped to the project directory'],
  ['Sandbox is non-negotiable', '--sandbox cannot be downgraded by any caller'],
  ['GUI tools', 'mouse/keyboard are dangerous, opt-in only, sandbox-blocked'],
  ['Rate limiting', 'per-IP buckets on /v1/* and /mcp (light 120/min, heavy 10/min)'],
];

const MODELS = [
  { name: 'Hy-MT2 1.8B', quant: 'Q4_K_M', role: 'Planner', vram: '~1.1 GB' },
  { name: 'Gemma 4 E4B', quant: 'Q2_K_XL', role: 'Executor · Vision', vram: '~3 GB' },
  { name: 'Qwen2.5-Omni 3B', quant: 'Q4_K_M', role: 'Multimodal Executor', vram: '~2.5 GB' },
  { name: 'Mythos-nano', quant: 'Q5_K_M', role: 'Agent X core', vram: '~2.7 GB' },
];

export default function TerminalPage() {
  const [tab, setTab] = useState<TabKey>('cli');
  const [active, setActive] = useState<ApiEndpoint>(API_ENDPOINTS[0]);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  const copyEndpoint = (ep: ApiEndpoint) => {
    navigator.clipboard.writeText(ep.example);
    setCopiedPath(ep.path);
    setTimeout(() => setCopiedPath(null), 1500);
  };

  return (
    <div className="page-shell terminal-page">
      <PageHeader
        title="Agentic Terminal"
        subtitle="Setup & usage guideline — run the same engine from the CLI, or script it over HTTP."
        icon={<TerminalCodeIcon size={22} />}
      />

      {/* Tab navigation */}
      <div className="tabs" role="tablist" aria-label="Terminal guide sections">
        {TABS.map(t => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`tab ${tab === t.key ? 'tab-active' : ''}`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* ── CLI Flags & Commands ─────────────────────────────── */}
      {tab === 'cli' && (
        <div className="space-y-8">
          <section className="space-y-3">
            <h2 className="section-title">
              <Command size={20} className="text-accent" /> Quick start
            </h2>
            <CopyCode code={QUICK_START} title="run.py" language="bash" />
            <p className="text-sm text-text-muted prose-ch leading-relaxed">
              Everything below works in <code className="font-mono text-accent">python run.py cli</code> and is also exposed as
              HTTP endpoints for <code className="font-mono text-accent">python run.py api</code> / the web UI. Type{' '}
              <code className="font-mono text-accent">/help</code> inside the CLI for the same reference at runtime.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="section-title">
              <FileCode2 size={20} className="text-accent" /> Slash commands
            </h2>
            <Card className="code-block">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
                {CLI_GROUPS.map(([group, cmds]) => (
                  <div key={group} className="grid grid-cols-[6.5rem_1fr] gap-2 py-1.5 border-b border-border/60 last:border-0">
                    <span className="text-accent text-xs font-semibold truncate">{group}</span>
                    <span className="text-xs text-text-secondary font-mono leading-relaxed break-words">{cmds}</span>
                  </div>
                ))}
              </div>
            </Card>
            <Card className="code-block">
              <p className="text-[11px] uppercase tracking-widest text-text-muted font-semibold mb-2">Shortcuts</p>
              <div className="flex flex-wrap gap-2">
                <span className="chip inline-flex items-center gap-1.5"><Command size={12} /> <code className="font-mono">!cmd</code> — run a shell command</span>
                <span className="chip inline-flex items-center gap-1.5"><Command size={12} /> <code className="font-mono">!!</code> — retry last prompt</span>
                <span className="chip inline-flex items-center gap-1.5"><Command size={12} /> <code className="font-mono">{'\\'}</code> — continue on a new line</span>
                <span className="chip inline-flex items-center gap-1.5"><Command size={12} /> <code className="font-mono">Ctrl+C</code> — stop output</span>
                <span className="chip inline-flex items-center gap-1.5"><Command size={12} /> <code className="font-mono">Ctrl+V / Ctrl+X / Ctrl+K</code> — paste / cut / delete-to-end</span>
              </div>
            </Card>
          </section>

          <section className="space-y-3">
            <h2 className="section-title">
              <LocalEngineIcon size={20} className="text-accent" /> Bundled models & VRAM
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 stagger">
              {MODELS.map(m => (
                <Card key={m.name} className="model-card">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold text-sm truncate">{m.name}</p>
                    <span className="chip-active text-[10px] px-2 py-0.5 shrink-0">{m.quant}</span>
                  </div>
                  <p className="text-[11px] text-text-muted mt-0.5">{m.role}</p>
                  <p className="text-xs mt-2 inline-flex items-center gap-1.5 text-text-secondary">
                    <LocalEngineIcon size={13} /> <span className="tabular-nums">{m.vram}</span> VRAM
                  </p>
                </Card>
              ))}
            </div>
            <div className="space-y-2">
              <p className="text-[11px] uppercase tracking-widest text-text-muted font-semibold inline-flex items-center gap-1.5">
                <HubDownloadIcon size={13} /> Get more models from Hugging Face
              </p>
              <CopyCode code={HF_DOWNLOAD} title="huggingface-cli" language="bash" />
              <p className="text-xs text-text-muted">
                Models load one at a time and LRU-evict under the 6&nbsp;GB VRAM budget — pick quants that fit so several can coexist.
              </p>
            </div>
          </section>
        </div>
      )}

      {/* ── REST API Documentation ───────────────────────────── */}
      {tab === 'api' && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-6 items-start">
          <section className="space-y-3">
            <h2 className="section-title">
              <KeyRound size={20} className="text-accent" /> Endpoints
            </h2>
            <div className="space-y-2.5">
              {API_ENDPOINTS.map(ep => (
                <div
                  key={ep.path}
                  onClick={() => setActive(ep)}
                  className={`group cursor-pointer rounded-xl border p-3.5 transition-all ${
                    active.path === ep.path
                      ? 'border-accent/40 bg-accent-soft/40 shadow-md shadow-accent/5'
                      : 'border-border bg-bg-secondary/40 hover:border-accent/25 hover:bg-bg-secondary/60'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className={`shrink-0 w-16 text-center text-[10px] font-bold tracking-wider rounded-md border py-1 ${METHOD_STYLES[ep.method]}`}>
                      {ep.method}
                    </span>
                    <code className="flex-1 min-w-0 font-mono text-xs text-text-primary truncate">{ep.path}</code>
                    <button
                      onClick={(e) => { e.stopPropagation(); copyEndpoint(ep); }}
                      className="shrink-0 p-1.5 rounded-lg text-text-muted hover:text-accent hover:bg-accent/10 transition-colors"
                      title="Copy curl example"
                      aria-label={`Copy example for ${ep.path}`}
                    >
                      {copiedPath === ep.path ? <Check size={13} className="text-success" /> : <Copy size={13} />}
                    </button>
                  </div>
                  <p className="text-xs text-text-secondary mt-1.5">{ep.desc}</p>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {ep.params.map(p => (
                      <span key={p} className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-bg-tertiary border border-border text-text-muted">{p}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-3 lg:sticky lg:top-4">
            <h2 className="section-title">
              <FileCode2 size={20} className="text-accent" /> Example request
            </h2>
            <CopyCode code={active.example} title={`curl ${active.method.toLowerCase()} · ${active.path.split('/').filter(Boolean).pop()}`} language="bash" />
            <p className="text-xs text-text-muted">
              Click any endpoint on the left to load its example. All requests are JSON unless marked GET.
            </p>
          </section>
        </div>
      )}

      {/* ── Security Rules ───────────────────────────────────── */}
      {tab === 'security' && (
        <div className="space-y-8">
          <section className="space-y-3">
            <h2 className="section-title">
              <KeyRound size={20} className="text-accent" /> Hardening flags
            </h2>
            <CopyCode code={SECURITY_FLAGS} title="run.py --secure" language="bash" />
          </section>

          <section className="space-y-3">
            <h2 className="section-title">
              <SandboxShieldIcon size={20} className="text-accent" /> Built-in protections
            </h2>
            <Card className="code-block">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
                {SECURITY_PROTECTIONS.map(([rule, detail]) => (
                  <div key={rule} className="grid grid-cols-[9rem_1fr] gap-2 py-1.5 border-b border-border/60 last:border-0">
                    <span className="text-accent text-xs font-semibold">{rule}</span>
                    <span className="text-xs text-text-secondary leading-relaxed">{detail}</span>
                  </div>
                ))}
              </div>
            </Card>
            <div className="flex flex-wrap gap-2">
              <span className="chip inline-flex items-center gap-1.5"><ShieldCheck size={12} /> Dangerous patterns (<code className="font-mono">rm -rf /</code>, mkfs, dd, format…) blocked → HTTP 400</span>
              <span className="chip inline-flex items-center gap-1.5"><MemoryMatrixIcon size={12} /> File ops scoped to the project; path traversal rejected</span>
              <span className="chip inline-flex items-center gap-1.5"><SandboxShieldIcon size={12} /> <code className="font-mono">--sandbox</code> forces read-only + no DB writes (cannot be downgraded)</span>
              <span className="chip inline-flex items-center gap-1.5"><ShieldCheck size={12} /> GUI mouse/keyboard is opt-in (<code className="font-mono">--allow-gui</code>) and sandbox-blocked</span>
            </div>
          </section>
        </div>
      )}

      {/* Footer CTA */}
      <section className="glass-card p-6 sm:p-8 text-center mt-8">
        <h3 className="text-lg font-semibold inline-flex items-center gap-2">
          <PulseLineIcon size={18} className="text-accent" /> Ready to build?
        </h3>
        <p className="text-text-muted text-sm mt-1.5 max-w-xl mx-auto">
          Run <code className="font-mono text-accent">python run.py cli</code> for the interactive terminal, or jump straight into a conversation with Agent X.
        </p>
        <div className="mt-4 flex justify-center flex-wrap gap-3">
          <Link
            href="/chat?agent=agent_x"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25 transition-all"
          >
            <BookOpen size={16} /> Chat with Agent X
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium bg-bg-tertiary hover:bg-bg-hover text-text-primary border border-border transition-all"
          >
            Open Dashboard <ArrowRight size={14} />
          </Link>
        </div>
      </section>
    </div>
  );
}
