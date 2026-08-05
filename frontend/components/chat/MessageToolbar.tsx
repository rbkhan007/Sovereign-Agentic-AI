'use client';

import React from 'react';
import {
  Pencil,
  Trash2,
  GitBranch,
  Copy,
  WrapText,
  RefreshCw,
  Volume2,
  ThumbsUp,
  ThumbsDown,
  Check,
} from 'lucide-react';

export interface MessageToolbarProps {
  role: 'user' | 'assistant';
  content: string;
  feedback?: 'up' | 'down' | null;
  onEdit?: () => void;
  onDelete: () => void;
  onBranch?: () => void;
  onRegenerate?: () => void;
  onReadAloud?: () => void;
  onFeedback?: (kind: 'up' | 'down') => void;
  onCopyRaw: () => void;
  onCopyClean: () => void;
}

const btnBase =
  'p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-bg-tertiary transition-colors';

export default function MessageToolbar({
  role,
  feedback = null,
  onEdit,
  onDelete,
  onBranch,
  onRegenerate,
  onReadAloud,
  onFeedback,
  onCopyRaw,
  onCopyClean,
}: MessageToolbarProps) {
  return (
    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
      {role === 'user' ? (
        <>
          {onEdit && (
            <button className={btnBase} onClick={onEdit} title="Edit prompt" aria-label="Edit prompt">
              <Pencil size={13} />
            </button>
          )}
          {onBranch && (
            <button className={btnBase} onClick={onBranch} title="Branch conversation" aria-label="Branch conversation">
              <GitBranch size={13} />
            </button>
          )}
          <button className={btnBase} onClick={onDelete} title="Delete message" aria-label="Delete message">
            <Trash2 size={13} />
          </button>
        </>
      ) : (
        <>
          <button className={btnBase} onClick={onCopyRaw} title="Copy raw markdown" aria-label="Copy raw markdown">
            <Copy size={13} />
          </button>
          <button className={btnBase} onClick={onCopyClean} title="Copy clean text" aria-label="Copy clean text">
            <WrapText size={13} />
          </button>
          {onRegenerate && (
            <button className={btnBase} onClick={onRegenerate} title="Regenerate response" aria-label="Regenerate response">
              <RefreshCw size={13} />
            </button>
          )}
          {onReadAloud && (
            <button className={btnBase} onClick={onReadAloud} title="Read aloud" aria-label="Read aloud">
              <Volume2 size={13} />
            </button>
          )}
          {onFeedback && (
            <>
              <button
                className={`${btnBase} ${feedback === 'up' ? 'text-success' : ''}`}
                onClick={() => onFeedback('up')}
                title="Good response"
                aria-label="Good response"
              >
                <ThumbsUp size={13} />
              </button>
              <button
                className={`${btnBase} ${feedback === 'down' ? 'text-danger' : ''}`}
                onClick={() => onFeedback('down')}
                title="Bad response"
                aria-label="Bad response"
              >
                <ThumbsDown size={13} />
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}

export function CopyCheck({ copied }: { copied: boolean }) {
  return copied ? <Check size={12} className="text-success" /> : <Copy size={12} />;
}
