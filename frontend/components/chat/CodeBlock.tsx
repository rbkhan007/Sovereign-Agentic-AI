'use client';

import React, { useState, useMemo } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { Copy, Check, List, ChevronsUpDown } from 'lucide-react';

const COLLAPSE_THRESHOLD = 30;
const COLLAPSE_PREVIEW = 14;

export default function CodeBlock({ code, language, fileName }: { code: string; language: string; fileName?: string }) {
  const [copied, setCopied] = useState(false);
  const [showLines, setShowLines] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const lines = useMemo(() => code.replace(/\n$/, '').split('\n'), [code]);
  const isLong = lines.length > COLLAPSE_THRESHOLD;
  const isDiff = language === 'diff' || language === 'patch';
  const displayCode = isLong && !expanded ? lines.slice(0, COLLAPSE_PREVIEW).join('\n') : code.replace(/\n$/, '');

  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="relative group my-2 rounded-xl overflow-hidden border border-border bg-bg-primary/60">
      <div className="flex items-center justify-between bg-bg-tertiary/80 px-3 py-1.5 text-xs text-text-muted border-b border-border">
        <span className="font-mono truncate">{fileName || language || 'code'}</span>
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            onClick={() => setShowLines((v) => !v)}
            title="Toggle line numbers"
            aria-label="Toggle line numbers"
            className={`p-1 rounded transition-colors hover:text-text-primary ${showLines ? 'text-accent' : ''}`}
          >
            <List size={13} />
          </button>
          <button
            onClick={copy}
            title="Copy code"
            aria-label="Copy code"
            className="p-1 rounded flex items-center gap-1 hover:text-text-primary transition-colors"
          >
            {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
            {copied && <span className="text-success">Copied</span>}
          </button>
        </div>
      </div>

      {isDiff ? (
        <pre className="!m-0 !rounded-none bg-bg-primary/80 text-sm p-3 overflow-x-auto scrollbar-thin leading-relaxed">
          {displayCode.split('\n').map((ln, i) => {
            const cls = ln.startsWith('+')
              ? 'text-success'
              : ln.startsWith('-')
                ? 'text-danger'
                : ln.startsWith('@@')
                  ? 'text-accent'
                  : 'text-text-secondary';
            return (
              <div key={i} className={cls}>
                {showLines && <span className="select-none text-text-muted/40 mr-3 inline-block w-8 text-right tabular-nums">{i + 1}</span>}
                {ln || ' '}
              </div>
            );
          })}
        </pre>
      ) : (
        <SyntaxHighlighter
          language={language || 'text'}
          PreTag="div"
          showLineNumbers={showLines}
          className="!m-0 !rounded-none !bg-bg-primary/80 !text-sm"
          customStyle={{ padding: '0.75rem', fontSize: '0.8125rem', lineHeight: 1.6 }}
          lineNumberStyle={{ color: 'rgba(127,127,140,0.4)', minWidth: '2.2rem', paddingRight: '0.75rem' }}
        >
          {displayCode}
        </SyntaxHighlighter>
      )}

      {isLong && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-center justify-center gap-1.5 text-xs py-1.5 bg-bg-tertiary/70 text-accent hover:bg-bg-tertiary transition-colors border-t border-border"
        >
          <ChevronsUpDown size={12} />
          {expanded ? 'Collapse code' : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}
