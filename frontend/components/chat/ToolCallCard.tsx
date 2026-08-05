'use client';

import React, { useState } from 'react';
import { Terminal, CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';

export interface ToolCall {
  id: number;
  tool: string;
  args?: Record<string, unknown>;
  status: 'running' | 'success' | 'failed';
  output?: string;
  elapsed?: number;
  step?: number;
}

function formatArgs(args?: Record<string, unknown>): string {
  if (!args) return '';
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

function formatElapsed(s?: number): string {
  if (s === undefined) return '';
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  return `${s.toFixed(1)}s`;
}

export default function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const isRunning = call.status === 'running';

  return (
    <div className="rounded-xl border border-border bg-bg-primary/70 overflow-hidden text-xs font-mono animate-fade-in">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-bg-tertiary/60 transition-colors text-left"
      >
        {isRunning ? (
          <Loader2 size={14} className="text-accent animate-spin shrink-0" />
        ) : call.status === 'success' ? (
          <CheckCircle2 size={14} className="text-success shrink-0" />
        ) : (
          <XCircle size={14} className="text-danger shrink-0" />
        )}
        <Terminal size={13} className="text-text-muted shrink-0" />
        <span className="font-semibold text-text-primary truncate">{call.tool}</span>
        {call.step !== undefined && (
          <span className="text-text-muted shrink-0">#{call.step}</span>
        )}
        <span
          className={`ml-auto flex items-center gap-1 shrink-0 ${
            call.status === 'success' ? 'text-success' : call.status === 'failed' ? 'text-danger' : 'text-text-muted'
          }`}
        >
          {call.status === 'running' ? 'Running…' : call.status === 'success' ? 'Success ✓' : 'Failed ✕'}
          {call.elapsed !== undefined && (
            <span className="flex items-center gap-0.5 text-text-muted">
              <Clock size={11} /> {formatElapsed(call.elapsed)}
            </span>
          )}
        </span>
        <span className="text-text-muted shrink-0">
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>
      </button>

      {open && (
        <div className="border-t border-border px-3 py-2 space-y-2 bg-bg-primary/40">
          {call.args && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">Command / Args</div>
              <pre className="text-accent whitespace-pre-wrap break-words text-[11px] leading-relaxed">{formatArgs(call.args)}</pre>
            </div>
          )}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">Output</div>
            <pre className={`whitespace-pre-wrap break-words text-[11px] leading-relaxed ${
              call.status === 'failed' ? 'text-danger' : 'text-text-secondary'
            }`}>{call.output || (isRunning ? 'Executing…' : '(no output)')}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
