'use client';

import React, { useState } from 'react';
import { Copy, Check, Terminal } from 'lucide-react';

/**
 * Dracula-themed code window with a copy-to-clipboard button.
 * Hardcoded palette so it reads like a real terminal in both app themes.
 */
export default function CopyCode({ code, title = 'terminal', language = 'bash' }: { code: string; title?: string; language?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="overflow-hidden rounded-xl border border-[#44475a] shadow-lg" style={{ background: '#282a36' }}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#44475a]" style={{ background: '#21222c' }}>
        <span className="flex items-center gap-1.5">
          <span className="flex gap-1.5 mr-1">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#ff5555' }} />
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#f1fa8c' }} />
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#50fa7b' }} />
          </span>
          <Terminal size={12} style={{ color: '#bd93f9' }} />
          <span className="font-mono text-[11px] text-[#f8f8f2]">{title}</span>
          <span className="ml-1 px-1.5 py-px rounded text-[9px] uppercase tracking-wider font-mono" style={{ background: '#44475a', color: '#8be9fd' }}>{language}</span>
        </span>
        <button
          onClick={copy}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium transition-colors hover:bg-[#44475a]"
          style={{ color: copied ? '#50fa7b' : '#f8f8f2' }}
          aria-label="Copy code"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="m-0 px-4 py-3 overflow-x-auto text-[12.5px] leading-relaxed font-mono scrollbar-thin" style={{ color: '#f8f8f2' }}>
        <code>{code}</code>
      </pre>
    </div>
  );
}
