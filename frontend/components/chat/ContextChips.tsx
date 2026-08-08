'use client';

import React from 'react';
import { Globe, Bot, Sparkles, AtSign, X, FileText } from 'lucide-react';
import { type ContextChip } from '@/lib/chatUtils';

const KIND_ICON: Record<ContextChip['kind'], React.ReactNode> = {
  file: <FileText size={14} />,
  agent: <Bot size={14} />,
  skill: <Sparkles size={14} />,
  web: <Globe size={14} />,
};

export default function ContextChips({ chips, onRemove }: { chips: ContextChip[]; onRemove: (id: string) => void }) {
  if (chips.length === 0) return null;
  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
      {chips.map((c) => (
        <span key={c.id} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-accent-soft text-accent text-xs font-medium border border-accent/20 shrink-0">
          <span className="flex items-center">{KIND_ICON[c.kind]}</span>
          <AtSign size={12} />
          {c.label}
          <button onClick={() => onRemove(c.id)} className="ml-0.5 hover:text-danger transition-colors">
            <X size={12} />
          </button>
        </span>
      ))}
    </div>
  );
}
