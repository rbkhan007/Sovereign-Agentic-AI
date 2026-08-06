'use client';

import React, { useEffect, useState } from 'react';
import { fetchJSON, toArray } from '@/lib/api';
import { ArrowRight, Sparkles, Bot, LayoutDashboard, Loader2 } from 'lucide-react';
import {
  OrchestratorIcon, TerminalCodeIcon, AgentXIcon, LocalEngineIcon, GraphWebIcon,
  WorkspacePaneIcon, VisionLensIcon, ArtForgeIcon, ReactLoopIcon, MemoryMatrixIcon,
  SandboxShieldIcon, DataLakeIcon, CloudBridgeIcon, HubDownloadIcon, PulseLineIcon,
} from '@/components/icons';
import Link from 'next/link';
import Card from '@/components/ui/Card';

const SOFTWARE: { icon: React.ReactNode; title: string; desc: string }[] = [
  { icon: <OrchestratorIcon size={18} />, title: 'Multi-Agent Orchestrator', desc: 'A planner + executor pipeline routes each task to the best-fit model with adaptive harness scoring and auto-summarizing context.' },
  { icon: <TerminalCodeIcon size={18} />, title: 'Agentic Terminal', desc: 'An IDE-like workspace: edit, run and let the agent build files and execute shell/Python safely inside a sandbox.' },
  { icon: <AgentXIcon size={18} />, title: 'Agent X (All-in-One)', desc: 'A universal, autonomous agent that follows your goal and the project index to deliver complete, production-ready results.' },
  { icon: <LocalEngineIcon size={18} />, title: 'Local LLM Engine', desc: 'Runs GGUF models on your GPU via Vulkan with VRAM budgeting, LRU eviction and per-model worker threads.' },
  { icon: <GraphWebIcon size={18} />, title: 'Knowledge Graph', desc: 'Obsidian-style wiki-links, tags and backlinks with pgvector hybrid + recursive shortest-path search.' },
  { icon: <WorkspacePaneIcon size={18} />, title: 'Workspaces', desc: 'Isolated chat areas with their own system prompt, file chunks and scoped memory — great for managing projects.' },
  { icon: <VisionLensIcon size={18} />, title: 'Computer Vision', desc: 'Local image understanding with Gemma 3 to describe screenshots and uploads for the agent.' },
  { icon: <ArtForgeIcon size={18} />, title: 'Image Generation', desc: 'On-device Stable Diffusion image synthesis, RAM-guarded and resolution-capped.' },
  { icon: <ReactLoopIcon size={18} />, title: 'Computer Agent', desc: 'ReAct shell, file I/O, web and process tools — sandboxed by default, with a dangerous-command guard.' },
  { icon: <MemoryMatrixIcon size={18} />, title: 'Memory & Vector Store', desc: 'PostgreSQL + pgvector persistence with auto-pruning, sessions and per-workspace memory scopes.' },
  { icon: <SandboxShieldIcon size={18} />, title: 'Security & Sandbox', desc: 'Dangerous-pattern blocking, path-traversal-safe file ops, API tokens and rate limiting on every endpoint.' },
  { icon: <CloudBridgeIcon size={18} />, title: 'Cloud Fallback', desc: 'Optional OpenAI-compatible fallback with sliding-window rate limiting when local models are unavailable.' },
];

const ARCH_STAGES: { icon: React.ReactNode; title: string; desc: string }[] = [
  { icon: <PulseLineIcon size={18} />, title: 'Your Prompt', desc: 'Any task, in plain language.' },
  { icon: <GraphWebIcon size={18} />, title: 'Selection Room', desc: 'classify_task buckets code / math / summarize / translate / tool / creative / general.' },
  { icon: <OrchestratorIcon size={18} />, title: 'Model Router', desc: 'Harness ranks executors by fitness = success·60 + speed·30 + recency·10.' },
  { icon: <ReactLoopIcon size={18} />, title: 'Planner (Hy-MT2)', desc: 'Generates 2 candidate plans, ranked by length for the shortest reliable path.' },
  { icon: <LocalEngineIcon size={18} />, title: 'Executors', desc: 'Gemma, Qwen2.5-Omni & Mythos-nano answer in parallel; the best wins.' },
  { icon: <MemoryMatrixIcon size={18} />, title: 'Judge + Harness', desc: 'Every answer scored 0–10; scores feed back into the router.' },
];

const CONTEXT_LAYER = [
  { icon: <MemoryMatrixIcon size={14} />, label: 'Memory & pgvector' },
  { icon: <GraphWebIcon size={14} />, label: 'Knowledge Graph' },
  { icon: <WorkspacePaneIcon size={14} />, label: 'Workspace context' },
  { icon: <VisionLensIcon size={14} />, label: 'Vision' },
  { icon: <CloudBridgeIcon size={14} />, label: 'Web search fallback' },
];

const MODELS = [
  { name: 'Hy-MT2 1.8B', quant: 'Q4_K_M', role: 'Planner', vram: '~1.1 GB', tags: ['multi-candidate planning', 'low VRAM'], hf: 'gguf-plan-1.8b' },
  { name: 'Gemma 4 E4B', quant: 'Q2_K_XL', role: 'Executor · Vision', vram: '~3 GB', tags: ['vision', 'instruction'], hf: 'gemma-4-e4b' },
  { name: 'Qwen2.5-Omni 3B', quant: 'Q4_K_M', role: 'Multimodal Executor', vram: '~2.5 GB', tags: ['multimodal', 'fast'], hf: 'qwen2.5-omni-3b' },
  { name: 'Mythos-nano', quant: 'Q5_K_M', role: 'Agent X core', vram: '~2.7 GB', tags: ['all-in-one', 'quality'], hf: 'mythos-nano' },
];

const DATASETS = [
  { icon: <DataLakeIcon size={18} />, title: 'ARC Grid Reasoning', desc: 'arc/training.json powers the /arc eval — measure grid-pattern accuracy per model.', meta: 'eval' },
  { icon: <DataLakeIcon size={18} />, title: 'LoRA Fine-tuning', desc: 'Drop prompt/output pairs in lora_datasets/ and train a lightweight adapter on CPU (peft).', meta: 'train' },
  { icon: <WorkspacePaneIcon size={18} />, title: 'Workspace Knowledge', desc: 'Upload docs to a workspace — chunked (600/120) and embedded for scoped retrieval.', meta: 'rag' },
  { icon: <VisionLensIcon size={18} />, title: 'Chat Uploads', desc: 'PDFs get preview text, images get a vision description inlined as context.', meta: 'files' },
  { icon: <GraphWebIcon size={18} />, title: 'Wiki Knowledge Base', desc: '[[wiki-links]], #tags and headings on markdown become graph nodes + backlinks.', meta: 'graph' },
  { icon: <MemoryMatrixIcon size={18} />, title: 'Sessions & Metrics', desc: 'Conversation history, persisted sessions and metrics snapshots for trend analysis.', meta: 'logs' },
];

type Pulse = { requests: number; models: number; vram: number; cpu: number; online: boolean };

function SystemPulse() {
  const [pulse, setPulse] = useState<Pulse>({ requests: 0, models: 0, vram: 0, cpu: 0, online: false });

  useEffect(() => {
    let mounted = true;
    async function tick() {
      try {
        const metrics = (await fetchJSON('/v1/metrics', { timeout: 4000 })) as { total_requests?: number; requests?: number } | null;
        const hardware = (await fetchJSON('/v1/hardware', { timeout: 4000 })) as { gpu_vram_used_mb?: number; cpu_percent?: number } | null;
        const models = (await fetchJSON('/v1/models', { timeout: 4000 })) as { data?: unknown[] } | unknown[] | null;
        const modelsData = Array.isArray(models) ? models : models?.data ?? [];
        const list = (modelsData as { id?: string; loaded?: boolean }[]).filter(m => m && m.loaded);
        if (!mounted) return;
        setPulse({
          requests: metrics?.total_requests ?? metrics?.requests ?? 0,
          models: list.length,
          vram: hardware?.gpu_vram_used_mb ?? 0,
          cpu: hardware?.cpu_percent ?? 0,
          online: true,
        });
      } catch {
        if (mounted) setPulse(p => ({ ...p, online: false }));
      }
    }
    tick();
    const interval = setInterval(tick, 15000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  const items = [
    { label: 'Total requests', value: pulse.online ? String(pulse.requests) : '—' },
    { label: 'Models loaded', value: pulse.online ? String(pulse.models) : '—' },
    { label: 'VRAM in use', value: pulse.online ? `${pulse.vram} MB` : '—' },
    { label: 'CPU load', value: pulse.online ? `${Math.round(pulse.cpu)}%` : '—' },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {items.map(item => (
        <div key={item.label} className="glass-card p-3 text-center">
          <p className="text-lg font-bold tabular-nums">{item.value}</p>
          <p className="text-[10px] uppercase tracking-widest text-text-muted mt-0.5">{item.label}</p>
        </div>
      ))}
    </div>
  );
}

export default function Landing() {
  const [agents, setAgents] = useState<{ name: string; role: string; description?: string; model?: string }[]>([]);

  useEffect(() => {
    fetchJSON('/v1/agents')
      .then(d => setAgents(toArray<{ name: string; role: string; description?: string; model?: string }>(d)))
      .catch(() => { /* agents optional on landing */ });
  }, []);

  return (
    <div className="page-shell space-y-10">
      <div className="brand-logo-wrap">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/static/ascii-logo.png" alt="Sovereign Agentic AI" className="brand-logo-img" />
      </div>

      {/* Hero */}
      <section className="landing-hero glass-card p-6 sm:p-8 lg:p-10">
        <div className="flex items-center gap-2 text-accent text-sm font-semibold uppercase tracking-widest mb-3">
          <Sparkles size={16} /> Sovereign-Agentic-AI
        </div>
        <h1 className="landing-title text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight leading-tight">
          Your personal <span className="gradient-text">multi-agent AI operating system</span>,<br className="hidden sm:block" />
          running 100% locally on your GPU.
        </h1>
        <p className="landing-lead prose-ch mt-4 text-text-secondary text-base sm:text-lg">
          Sovereign-Agentic-AI is a private, offline-first platform that turns local LLMs into a team of
          specialized agents — coding, debugging, research, and an autonomous <strong>Agent&nbsp;X</strong> that
          builds complete, production-ready software. It ships with an IDE-like Agentic Terminal, a knowledge
          graph, isolated workspaces, computer vision, image generation and a fully responsive WebUI.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25 transition-all"
          >
            <LayoutDashboard size={16} /> Enter Dashboard
          </Link>
          <Link
            href="/chat"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-bg-tertiary hover:bg-bg-hover text-text-primary border border-border transition-all"
          >
            Start Chatting <ArrowRight size={14} />
          </Link>
          <Link
            href="/terminal"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-bg-tertiary hover:bg-bg-hover text-text-primary border border-border transition-all"
          >
            <TerminalCodeIcon size={14} /> Agentic Terminal
          </Link>
        </div>
        <div className="mt-5 flex flex-wrap gap-2 text-xs text-text-muted">
          <span className="chip">Local &amp; Private</span>
          <span className="chip">GGUF + Vulkan GPU</span>
          <span className="chip">Sandboxed Computer Agent</span>
          <span className="chip">Cloud Fallback</span>
          <span className="chip">Responsive WebUI</span>
          <span className="chip">Production-Ready Agents</span>
          <span className="chip">Hugging Face Models</span>
          <span className="chip">ARC Eval</span>
        </div>
      </section>

      {/* Live system pulse */}
      <section className="space-y-3">
        <h2 className="section-title">
          <PulseLineIcon size={20} className="text-accent" /> Live system pulse
        </h2>
        <SystemPulse />
        <p className="text-xs text-text-muted prose-ch">Auto-refreshes every 15s — open the <Link href="/dashboard" className="text-accent hover:underline">Dashboard</Link> for full graphs, model tables and hardware telemetry.</p>
      </section>

      {/* Architecture */}
      <section className="space-y-4">
        <div>
          <h2 className="section-title">
            <OrchestratorIcon size={20} className="text-accent" /> Architecture
          </h2>
          <p className="text-sm text-text-muted prose-ch mt-1">One plan-then-execute pass per request: every task is classified, routed, planned, executed in parallel and judged — then the scores teach the router.</p>
        </div>
        <div className="flow-diagram">
          {ARCH_STAGES.map((stage, i) => (
            <div key={stage.title} className="flex flex-col sm:flex-row sm:items-center gap-2">
              <div className="flow-stage glass-card flex-1">
                <span className="icon-tile">{stage.icon}</span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold leading-tight">{stage.title}</p>
                  <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed">{stage.desc}</p>
                </div>
              </div>
              {i < ARCH_STAGES.length - 1 && <span className="flow-arrow" aria-hidden="true">→</span>}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2 glass-card p-3">
          <span className="text-[11px] uppercase tracking-widest text-text-muted font-semibold">Context layer</span>
          {CONTEXT_LAYER.map(c => (
            <span key={c.label} className="chip inline-flex items-center gap-1.5">
              {c.icon} {c.label}
            </span>
          ))}
        </div>
      </section>

      {/* Hardware-optimized models */}
      <section className="space-y-4">
        <div>
          <h2 className="section-title">
            <LocalEngineIcon size={20} className="text-accent" /> Hardware-optimized models
          </h2>
          <p className="text-sm text-text-muted prose-ch mt-1">Bundled GGUF models tuned for a 6&nbsp;GB AMD RX&nbsp;5600&nbsp;XT (Vulkan). Models load one at a time and LRU-evict under the VRAM budget — the router picks the best fit per task.</p>
        </div>
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
              <div className="mt-2 flex flex-wrap gap-1.5">
                {m.tags.map(t => <span key={t} className="chip text-[10px] px-2 py-0.5">{t}</span>)}
              </div>
              <p className="text-[10px] text-text-muted mt-2 break-all font-mono">hf: {m.hf}</p>
            </Card>
          ))}
        </div>
        <p className="text-xs text-text-muted">Drop any GGUF into <code className="font-mono text-accent">models/</code> and it auto-registers as an executor — or register one from anywhere with <code className="font-mono text-accent">python run.py --add-model PATH --add-model-name NAME --add-model-role Executor</code>.</p>
      </section>

      {/* Hugging Face download guide */}
      <section className="space-y-4">
        <div>
          <h2 className="section-title">
            <HubDownloadIcon size={20} className="text-accent" /> Download models from Hugging Face
          </h2>
          <p className="text-sm text-text-muted prose-ch mt-1">Fetch GGUF quantizations into <code className="font-mono text-accent">models/</code> — the engine discovers and registers them on next start.</p>
        </div>
        <Card className="code-block space-y-3">
          <p className="text-[11px] uppercase tracking-widest text-text-muted font-semibold">1 · CLI (recommended)</p>
          <pre className="terminal-pre"><code>{`pip install "huggingface_hub[cli]"
huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF \\
  qwen2.5-3b-instruct-q4_k_m.gguf --local-dir models/`}</code></pre>
          <p className="text-[11px] uppercase tracking-widest text-text-muted font-semibold pt-1">2 · Direct link (wget)</p>
          <pre className="terminal-pre"><code>{`wget -P models/ https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf`}</code></pre>
          <p className="text-[11px] uppercase tracking-widest text-text-muted font-semibold pt-1">3 · Tip</p>
          <ul className="text-sm text-text-secondary list-disc pl-5 space-y-1">
            <li>Pick a quant that fits your VRAM budget — the <span className="text-accent">Selection Room</span> routes tasks around what is loaded.</li>
            <li>Pick GGUF quant sizes under your budget so multiple models can live together in memory.</li>
            <li>No model installed yet? The <span className="text-accent">Cloud fallback</span> keeps the platform usable while you download.</li>
          </ul>
        </Card>
      </section>

      {/* Datasets */}
      <section className="space-y-4">
        <div>
          <h2 className="section-title">
            <DataLakeIcon size={20} className="text-accent" /> Bring your own datasets
          </h2>
          <p className="text-sm text-text-muted prose-ch mt-1">Everything is just files and folders on disk — feed the platform your own data for evals, training, retrieval and graphs.</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 stagger">
          {DATASETS.map(d => (
            <Card key={d.title} className="hover-lift transition-all">
              <div className="flex items-start gap-3">
                <span className="w-10 h-10 rounded-xl bg-accent-soft text-accent flex items-center justify-center shrink-0">{d.icon}</span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-sm leading-tight">{d.title}</h3>
                    <span className="chip text-[10px] px-1.5 py-0">{d.meta}</span>
                  </div>
                  <p className="text-text-muted text-xs mt-1 leading-relaxed">{d.desc}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* Software / capabilities */}
      <section className="space-y-4">
        <h2 className="section-title">
          <Sparkles size={20} className="text-accent" /> What's inside
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 stagger">
          {SOFTWARE.map(s => (
            <Card key={s.title} className="hover-lift transition-all">
              <div className="flex items-start gap-3">
                <span className="icon-tile shrink-0">{s.icon}</span>
                <div className="min-w-0">
                  <h3 className="font-semibold text-sm leading-tight">{s.title}</h3>
                  <p className="text-text-muted text-xs mt-1 leading-relaxed">{s.desc}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* Agents showcase */}
      <section className="space-y-4">
        <div className="flex items-end justify-between gap-3 flex-wrap">
          <h2 className="section-title mb-0">
            <Bot size={20} className="text-accent" /> Agent personas
          </h2>
          <Link href="/dashboard" className="text-sm text-accent hover:underline inline-flex items-center gap-1">
            Open Dashboard <ArrowRight size={14} />
          </Link>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 stagger">
          {agents.length === 0 ? (
            <p className="text-text-muted text-sm inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading agents…</p>
          ) : (
            agents.map(a => {
              const featured = a.name === 'agent_x';
              return (
                <Link
                  key={a.name}
                  href={`/chat?agent=${encodeURIComponent(a.name)}`}
                  className={`block rounded-2xl border p-4 transition-all hover-lift ${
                    featured ? 'border-accent/50 bg-accent-soft shadow-glow' : 'border-border bg-surface'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-sm truncate inline-flex items-center gap-2">
                      {featured ? <AgentXIcon size={16} className="text-accent" /> : <Bot size={16} className="text-text-muted" />}
                      {a.role}
                    </span>
                    {featured && <span className="chip-active text-[10px] px-2 py-0.5">Featured</span>}
                    {a.model && <span className="text-[10px] text-text-muted truncate">{a.model}</span>}
                  </div>
                  <p className="text-text-muted text-xs mt-1.5 leading-relaxed">
                    {a.description || 'Specialized assistant persona.'}
                  </p>
                </Link>
              );
            })
          )}
        </div>
      </section>

      {/* Footer CTA */}
      <section className="glass-card p-6 sm:p-8 text-center">
        <h3 className="text-lg font-semibold">Ready to put your local AI to work?</h3>
        <p className="text-text-muted text-sm mt-1.5 max-w-xl mx-auto">
          Launch the dashboard to watch models, hardware and throughput live — or jump straight into the Agentic Terminal and let Agent X build your next project.
        </p>
        <div className="mt-4 flex justify-center flex-wrap gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25 transition-all"
          >
            <LayoutDashboard size={16} /> Enter Dashboard
          </Link>
          <Link
            href="/terminal"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium bg-bg-tertiary hover:bg-bg-hover text-text-primary border border-border transition-all"
          >
            <TerminalCodeIcon size={14} /> Open Agentic Terminal
          </Link>
        </div>
        <p className="text-text-muted text-xs mt-6">Built by Rhasan (Rhasan_Indie_dev).</p>
      </section>
    </div>
  );
}
