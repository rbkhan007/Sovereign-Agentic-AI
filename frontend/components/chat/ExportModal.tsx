'use client';

import React, { useState } from 'react';
import { X, FileJson, FileText, FileDown, Link2, Check } from 'lucide-react';
import { useToast } from '@/components/providers/ToastProvider';
import type { ChatMessage } from '@/lib/api';

interface ExportModalProps {
  open: boolean;
  title: string;
  messages: ChatMessage[];
  convId?: string;
  onClose: () => void;
}

function toMarkdown(title: string, messages: ChatMessage[], convId?: string): string {
  const lines: string[] = [`# ${title || 'Conversation'}`];
  if (convId) lines.push('', `> conversation_id: \`${convId}\``, '');
  for (const m of messages) {
    lines.push(`## ${m.role === 'user' ? '**User**' : '**Assistant**'}`, '', m.content, '');
  }
  return lines.join('\n');
}

function toJson(title: string, messages: ChatMessage[], convId?: string): string {
  return JSON.stringify(
    { title, conversation_id: convId || null, exported_at: new Date().toISOString(), messages },
    null,
    2,
  );
}

function exportPdf(title: string, messages: ChatMessage[], convId?: string) {
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title>
  <style>
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 20px; color: #111; line-height: 1.6; }
    h1 { font-size: 22px; } h2 { font-size: 15px; color: #555; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 24px; }
    pre { background: #f6f6f6; padding: 12px; border-radius: 6px; overflow:auto; }
    .meta { color: #888; font-size: 12px; }
    .user { color: #6d28d9; } .assistant { color: #047857; }
  </style></head><body>
  <h1>${title}</h1>
  <p class="meta">${convId ? `conversation_id: ${convId}` : 'Conversation'}</p>
  ${messages.map((m) => `<h2 class="${m.role}">${m.role === 'user' ? 'User' : 'Assistant'}</h2><div>${m.content.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</div>`).join('')}
  </body></html>`;
  const w = window.open('', '_blank');
  if (!w) return false;
  w.document.write(html);
  w.document.close();
  setTimeout(() => w.print(), 300);
  return true;
}

export default function ExportModal({ open, title, messages, convId, onClose }: ExportModalProps) {
  const { addToast } = useToast();
  const [copied, setCopied] = useState(false);

  if (!open) return null;

  const md = toMarkdown(title, messages, convId);
  const json = toJson(title, messages, convId);

  const download = (content: string, mime: string, ext: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(title || 'conversation').replace(/[^\w\- ]+/g, '').trim() || 'conversation'}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyLink = async () => {
    const link = `${window.location.origin}/chat?conv=${encodeURIComponent(convId || '')}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      addToast('Shareable link copied', 'success');
    } catch {
      addToast('Failed to copy link', 'error');
    }
  };

  const rows = [
    { icon: <FileJson size={16} />, label: 'JSON', desc: 'Structured data', action: () => { download(json, 'application/json', 'json'); addToast('Exported as JSON', 'success'); } },
    { icon: <FileText size={16} />, label: 'Markdown', desc: 'Plain .md file', action: () => { download(md, 'text/markdown', 'md'); addToast('Exported as Markdown', 'success'); } },
    { icon: <FileDown size={16} />, label: 'PDF', desc: 'Print-friendly', action: () => { if (!exportPdf(title, messages, convId)) addToast('Pop-up blocked — allow pop-ups', 'error'); } },
    { icon: copied ? <Check size={16} /> : <Link2 size={16} />, label: copied ? 'Copied!' : 'Share link', desc: 'Copy URL with conv id', action: copyLink },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in p-4" onClick={onClose}>
      <div className="glass-card w-full max-w-sm p-4 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold">Export conversation</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition-colors" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <p className="text-xs text-text-muted mb-3 truncate">{title || 'Untitled'} · {messages.length} messages</p>
        <div className="space-y-1.5">
          {rows.map((r) => (
            <button
              key={r.label}
              onClick={r.action}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl bg-bg-secondary/60 border border-border text-left hover:border-accent/40 hover:bg-bg-tertiary transition-all"
            >
              <span className="text-accent">{r.icon}</span>
              <span className="flex-1">
                <span className="block text-sm font-medium text-text-primary">{r.label}</span>
                <span className="block text-[11px] text-text-muted">{r.desc}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
