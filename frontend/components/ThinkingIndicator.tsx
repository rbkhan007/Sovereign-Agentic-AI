'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Brain, ChevronDown, ChevronUp, Timer } from 'lucide-react';

interface ThinkingIndicatorProps {
  isThinking: boolean;
  thoughtText?: string;
  onToggle?: (expanded: boolean) => void;
}

function formatSeconds(sec: number): string {
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

export default function ThinkingIndicator({ isThinking, thoughtText, onToggle }: ThinkingIndicatorProps) {
  const [expanded, setExpanded] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);
  const lastTextRef = useRef<string>('');

  useEffect(() => {
    if (isThinking && startRef.current === null) {
      startRef.current = Date.now();
      setElapsed(0);
    }
  }, [isThinking]);

  useEffect(() => {
    if (!isThinking) {
      startRef.current = null;
      return;
    }
    const tick = () => {
      if (startRef.current !== null) {
        setElapsed((Date.now() - startRef.current) / 1000);
      }
    };
    const id = setInterval(tick, 100);
    return () => clearInterval(id);
  }, [isThinking]);

  useEffect(() => {
    if (isThinking && thoughtText) {
      lastTextRef.current = thoughtText;
      setExpanded(true);
    }
  }, [isThinking, thoughtText]);

  const handleToggle = () => {
    const next = !expanded;
    setExpanded(next);
    onToggle?.(next);
  };

  if (!isThinking && !thoughtText) return null;

  const label = isThinking ? 'Reasoning' : 'Thought';

  return (
    <div className="flex flex-col gap-2 animate-fade-in min-w-[180px]">
      <div className="flex items-center gap-2">
        <div className="relative">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white shrink-0 shadow-md">
            <Brain size={16} />
          </div>
          {isThinking && (
            <span className="absolute inset-0 rounded-xl ring-2 ring-accent/60 animate-ping" />
          )}
        </div>
        <div className="flex-1 flex items-center gap-2 min-w-0">
          <span className="text-xs text-text-muted shrink-0">
            {isThinking ? 'Thinking' : 'Thought'}
            {isThinking ? '…' : ''}
          </span>
          {isThinking ? (
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 bg-accent rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 bg-accent-2 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 bg-accent-3 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          ) : (
            <span className="flex items-center gap-1 text-[11px] text-text-muted font-mono">
              <Timer size={11} />
              {formatSeconds(elapsed)}
            </span>
          )}
        </div>
        {thoughtText && (
          <button
            onClick={handleToggle}
            className="text-text-muted hover:text-accent transition-colors"
            aria-expanded={expanded}
            aria-label="Toggle thinking"
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        )}
      </div>
      {expanded && thoughtText && (
        <div className="bg-bg-tertiary/80 rounded-xl px-4 py-3 text-xs text-text-muted border border-border max-h-48 overflow-y-auto whitespace-pre-wrap break-words animate-fade-in scrollbar-thin">
          <div className="text-[10px] uppercase tracking-wider text-text-muted/70 mb-1">{label} trace</div>
          {thoughtText}
        </div>
      )}
    </div>
  );
}
