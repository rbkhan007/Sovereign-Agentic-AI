'use client';

import React, { useEffect, useRef } from 'react';
import { Terminal, FileText, FilePen, CheckCircle2, XCircle, Clock, Loader2, Sparkles } from 'lucide-react';

export interface TraceAction {
  id: number;
  action: string;
  payload: string;
  status: 'running' | 'success' | 'failed';
  elapsed?: number;
  step?: number;
}

function actionIcon(action: string) {
  switch (action) {
    case 'BASH':
      return <Terminal size={13} className="shrink-0" />;
    case 'READ':
      return <FileText size={13} className="shrink-0" />;
    case 'WRITE':
      return <FilePen size={13} className="shrink-0" />;
    case 'DONE':
      return <CheckCircle2 size={13} className="shrink-0" />;
    default:
      return <Sparkles size={13} className="shrink-0" />;
  }
}

function actionColor(action: string): string {
  switch (action) {
    case 'BASH':
      return 'text-accent-2';
    case 'READ':
      return 'text-accent';
    case 'WRITE':
      return 'text-accent-3';
    case 'DONE':
      return 'text-success';
    default:
      return 'text-text-secondary';
  }
}

function formatElapsed(s?: number): string {
  if (s === undefined) return '';
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  return `${s.toFixed(1)}s`;
}

export default function AgentTrace({ actions, active }: { actions: TraceAction[]; active: boolean }) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [actions.length]);

  return (
    <div className="rounded-xl border border-border bg-bg-secondary/70 overflow-hidden animate-fade-in">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-bg-tertiary/40">
        <Sparkles size={14} className="text-accent shrink-0" />
        <span className="text-xs font-semibold text-text-primary">Code Agent</span>
        {active && <Loader2 size={13} className="text-accent animate-spin" />}
        <span className="text-[11px] text-text-muted ml-auto flex items-center gap-2">
          <span>{actions.length} step{actions.length === 1 ? '' : 's'}</span>
          {active && <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" /> working</span>}
        </span>
      </div>

      <div ref={listRef} className="max-h-56 overflow-y-auto scrollbar-thin p-1.5 space-y-0.5 font-mono text-[11px]">
        {actions.length === 0 && (
          <div className="px-2 py-2 text-text-muted">
            {active ? 'Initializing environment scan…' : 'No actions recorded yet.'}
          </div>
        )}
        {actions.map((a) => (
          <div key={a.id} className="flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-bg-tertiary/50 transition-colors">
            <span className={`mt-0.5 shrink-0 ${actionColor(a.action)}`}>{actionIcon(a.action)}</span>
            <span className="flex-1 min-w-0">
              <span className={`font-semibold shrink-0 ${actionColor(a.action)}`}>[{a.action}]</span>{' '}
              <span className="text-text-secondary break-words whitespace-pre-wrap">{a.payload}</span>
              {a.step !== undefined && <span className="text-text-muted"> · #{a.step}</span>}
            </span>
            <span className="flex items-center gap-1.5 shrink-0 mt-0.5">
              {a.status === 'running' ? (
                <Loader2 size={11} className="text-accent animate-spin" />
              ) : a.status === 'success' ? (
                <CheckCircle2 size={11} className="text-success" />
              ) : (
                <XCircle size={11} className="text-danger" />
              )}
              {a.elapsed !== undefined && (
                <span className="flex items-center gap-0.5 text-text-muted">
                  <Clock size={10} /> {formatElapsed(a.elapsed)}
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
