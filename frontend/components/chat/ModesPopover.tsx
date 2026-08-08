'use client';

import React, { useEffect, useRef } from 'react';
import { SlidersHorizontal } from 'lucide-react';

export default function ModesPopover({ open, onClose, modes, onToggle }: { open: boolean; onClose: () => void; modes: Array<{ key: string; label: string; checked: boolean; description: string }>; onToggle: (key: string, checked: boolean) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div ref={ref} className="absolute right-0 top-full mt-2 z-30 w-72 rounded-xl bg-bg-secondary border border-border shadow-xl p-3 animate-fade-in">
      <div className="flex items-center gap-2 mb-3">
        <SlidersHorizontal size={16} className="text-accent" />
        <span className="text-sm font-semibold">Generation Modes</span>
      </div>
      <div className="space-y-2">
        {modes.map((m) => (
          <label key={m.key} className="flex items-start gap-2.5 cursor-pointer group">
            <input
              type="checkbox"
              checked={m.checked}
              onChange={(e) => onToggle(m.key, e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-border bg-bg-primary accent-accent"
            />
            <div className="flex flex-col">
              <span className="text-sm font-medium group-hover:text-accent transition-colors">{m.label}</span>
              <span className="text-xs text-text-muted">{m.description}</span>
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}
