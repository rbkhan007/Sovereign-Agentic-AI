import React, { type ReactNode } from 'react';
import { FileImage, FileText, FileCode } from 'lucide-react';

export function getFileIcon(file: File): ReactNode {
  if (file.type.startsWith('image/')) return <><FileImage size={16} className="text-accent-2" /></>;
  if (file.type === 'text/markdown' || file.name.endsWith('.md')) return <><FileText size={16} className="text-blue-400" /></>;
  if (file.type.includes('code') || /\.(py|js|ts|tsx|jsx|go|rs|java|c|cpp|sh|json)$/i.test(file.name)) return <><FileCode size={16} className="text-yellow-400" /></>;
  return <><FileText size={16} className="text-text-muted" /></>;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

export function stripMarkdown(md: string): string {
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

export function getTrigger(value: string, caret: number): { type: 'slash' | 'mention'; query: string } | null {
  const before = value.slice(0, caret);
  const m = /(^|\s)([/@])(\S*)$/.exec(before);
  if (!m) return null;
  return { type: m[2] === '/' ? 'slash' : 'mention', query: m[3] };
}

export interface SlashCommand {
  id: string;
  label: string;
  description: string;
  hint?: string;
  action: 'clear' | 'compact' | 'review' | 'test' | 'model' | 'help';
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { id: '/clear', label: '/clear', description: 'Clear the current conversation', hint: '⌫', action: 'clear' },
  { id: '/compact', label: '/compact', description: 'Compress conversation context', action: 'compact' },
  { id: '/review', label: '/review', description: 'Review code & show a diff', action: 'review' },
  { id: '/test', label: '/test', description: 'Generate unit tests', action: 'test' },
  { id: '/model', label: '/model', description: 'Switch the active model', action: 'model' },
  { id: '/help', label: '/help', description: 'Show available commands', hint: '?', action: 'help' },
];

export interface ContextChip {
  id: string;
  label: string;
  kind: 'file' | 'agent' | 'skill' | 'web';
}

export const MAX_TOKENS = 4096;
