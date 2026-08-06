'use client';

import React from 'react';
import { BookOpen, ShieldCheck, KeyRound, Command, FileCode2, ArrowRight } from 'lucide-react';
import {
  TerminalCodeIcon, LocalEngineIcon, HubDownloadIcon, SandboxShieldIcon, PulseLineIcon, MemoryMatrixIcon,
} from '@/components/icons';
import Card from '@/components/ui/Card';
import PageHeader from '@/components/ui/PageHeader';
import Link from 'next/link';

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

const API_ROUTES: [string, string][] = [
  ['POST /v1/terminal/exec', 'Run a sandboxed shell command → {stdout, exit_code}'],
  ['POST /v1/terminal/python', 'Execute editor code as Python → {stdout, exit_code}'],
  ['GET  /v1/terminal/fs/tree', 'Project file tree (depth, max_nodes)'],
  ['POST /v1/terminal/fs/read', 'Open a file ({path, limit}) → {content}'],
  ['POST /v1/terminal/fs/write', 'Save a file ({path, content})'],
  ['POST /v1/terminal/fs/mkdir', 'Create a folder ({path})'],
  ['POST /v1/terminal/fs/delete', 'Delete a file/folder ({path})'],
];

export default function TerminalPage() {
  return (
    <div className="page-container terminal-page">
      <PageHeader
        title="Agentic Terminal"
        subtitle="Setup & usage guideline — run the same engine from the CLI, or script it over HTTP."
        icon={<TerminalCodeIcon size={22} />}
      />

      {/* Quick start */}
      <section className="space-y-3">
        <h2 className="section-title">
          <Command size={20} className="text-accent" /> Quick start — CLI code version
        </h2>
        <Card className="code-block">
          <p className="text-[11px] uppercase tracking-widest text-text-muted font-semibold mb-2">One launcher, three surfaces</p>
          <pre className="terminal-pre"><code>{`# 1. Full mode — web UI + CLI + API on one port
python run.py

# 2. Terminal CLI only (what this guide documents)
python run.py cli
python run.py cli --no-auto-load   # instant boot, skip VRAM preload

# 3. API server only (power the page over HTTP)
python run.py api

# 4. Secure it (optional but recommended)
python run.py --api-token secret --admin-key secret
python run.py --sandbox           # force read-only: no DB writes`}</code></pre>
        </Card>
        <p className="text-sm text-text-muted prose-ch leading-relaxed">
          Everything below works in <code className="font-mono text-accent">python run.py cli</code> and is also exposed as
          HTTP endpoints for <code className="font-mono text-accent">python run.py api</code> / the web UI. Type{' '}
          <code className="font-mono text-accent">/help</code> inside the CLI for the same reference at runtime.
        </p>
      </section>

      {/* CLI slash commands */}
      <section className="space-y-3">
        <h2 className="section-title">
          <FileCode2 size={20} className="text-accent" /> CLI slash commands
        </h2>
        <Card className="code-block">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            {CLI_GROUPS.map(([group, cmds]) => (
              <div key={group} className="grid grid-cols-[6.5rem_1fr] gap-2 py-1.5 border-b border-border/60 last:border-0 md:odd:border-r-0">
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

      {/* HTTP API */}
      <section className="space-y-3">
        <h2 className="section-title">
          <KeyRound size={20} className="text-accent" /> HTTP API (this engine, scriptable)
        </h2>
        <Card className="code-block">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            {API_ROUTES.map(([route, desc]) => (
              <div key={route} className="grid grid-cols-[13rem_1fr] gap-2 py-1.5 border-b border-border/60 last:border-0">
                <code className="text-accent text-[11px] font-mono break-words">{route}</code>
                <span className="text-xs text-text-secondary leading-relaxed">{desc}</span>
              </div>
            ))}
          </div>
        </Card>
        <pre className="terminal-pre"><code>{`curl -X POST localhost:8070/v1/terminal/exec \\
  -H "Content-Type: application/json" \\
  -d '{"command":"ls"}'`}</code></pre>
      </section>

      {/* Models & VRAM */}
      <section className="space-y-3">
        <h2 className="section-title">
          <LocalEngineIcon size={20} className="text-accent" /> Bundled models & VRAM
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 stagger">
          {[
            { name: 'Hy-MT2 1.8B', quant: 'Q4_K_M', role: 'Planner', vram: '~1.1 GB' },
            { name: 'Gemma 4 E4B', quant: 'Q2_K_XL', role: 'Executor · Vision', vram: '~3 GB' },
            { name: 'Qwen2.5-Omni 3B', quant: 'Q4_K_M', role: 'Multimodal Executor', vram: '~2.5 GB' },
            { name: 'Mythos-nano', quant: 'Q5_K_M', role: 'Agent X core', vram: '~2.7 GB' },
          ].map(m => (
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
        <Card className="code-block">
          <p className="text-[11px] uppercase tracking-widest text-text-muted font-semibold inline-flex items-center gap-1.5 mb-2">
            <HubDownloadIcon size={13} /> Get more models from Hugging Face
          </p>
          <pre className="terminal-pre"><code>{`pip install "huggingface_hub[cli]"
huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF \\
  qwen2.5-3b-instruct-q4_k_m.gguf --local-dir models/

# Any GGUF dropped in models/ auto-registers; or register from anywhere:
python run.py --add-model PATH --add-model-name NAME --add-model-role Executor`}</code></pre>
          <p className="text-xs text-text-muted mt-2">
            Models load one at a time and LRU-evict under the 6&nbsp;GB VRAM budget — pick quants that fit so several can coexist.
          </p>
        </Card>
      </section>

      {/* Safety */}
      <section className="space-y-3">
        <h2 className="section-title">
          <SandboxShieldIcon size={20} className="text-accent" /> Safety & sandbox rules
        </h2>
        <Card className="code-block">
          <div className="flex flex-wrap gap-2">
            <span className="chip inline-flex items-center gap-1.5"><ShieldCheck size={12} /> Dangerous patterns (<code className="font-mono">rm -rf /</code>, mkfs, dd, format…) blocked → HTTP 400</span>
            <span className="chip inline-flex items-center gap-1.5"><MemoryMatrixIcon size={12} /> File ops scoped to the project; path traversal rejected</span>
            <span className="chip inline-flex items-center gap-1.5"><SandboxShieldIcon size={12} /> <code className="font-mono">--sandbox</code> forces read-only + no DB writes (cannot be downgraded)</span>
            <span className="chip inline-flex items-center gap-1.5"><ShieldCheck size={12} /> GUI mouse/keyboard is opt-in (<code className="font-mono">--allow-gui</code>) and sandbox-blocked</span>
          </div>
        </Card>
      </section>

      {/* Footer CTA */}
      <section className="glass-card p-6 sm:p-8 text-center">
        <h3 className="text-lg font-semibold inline-flex items-center gap-2">
          <PulseLineIcon size={18} className="text-accent" /> Ready to build?
        </h3>
        <p className="text-text-muted text-sm mt-1.5 max-w-xl mx-auto">
          Run <code className="font-mono text-accent">python run.py cli</code> for the interactive terminal, or jump straight into a conversation with Agent X.
        </p>
        <div className="mt-4 flex justify-center flex-wrap gap-3">
          <Link
            href="/chat?agent=agent_x"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25 transition-all"
          >
            <BookOpen size={16} /> Chat with Agent X
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-bg-tertiary hover:bg-bg-hover text-text-primary border border-border transition-all"
          >
            Open Dashboard <ArrowRight size={14} />
          </Link>
        </div>
      </section>
    </div>
  );
}
