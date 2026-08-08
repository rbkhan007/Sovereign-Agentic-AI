'use client';

import React from 'react';
import { Bot, User } from 'lucide-react';
import MessageToolbar from '@/components/chat/MessageToolbar';
import ToolCallCard, { type ToolCall } from '@/components/chat/ToolCallCard';
import MarkdownContent from '@/components/chat/MarkdownContent';
import { stripMarkdown } from '@/lib/chatUtils';
import { type ChatMessage } from '@/lib/api';

export default function MessageBubble({
  message,
  index,
  isLast,
  isStreaming,
  agenticActive,
  liveToolCalls,
  editingId,
  editText,
  feedback,
  onStartEdit,
  onSaveEdit,
  onDeleteMessage,
  onRegenerate,
  onReadAloud,
  onSetFeedback,
  onCopyRaw,
  onCopyClean,
  onBranch,
}: {
  message: ChatMessage;
  index: number;
  isLast: boolean;
  isStreaming: boolean;
  agenticActive: boolean;
  liveToolCalls: ToolCall[];
  editingId: string | null;
  editText: string;
  feedback: Record<string, 'up' | 'down'>;
  onStartEdit: (index: number) => void;
  onSaveEdit: () => void;
  onDeleteMessage: (index: number) => void;
  onRegenerate: (index: number) => void;
  onReadAloud: (content: string) => void;
  onSetFeedback: (id: string, kind: 'up' | 'down') => void;
  onCopyRaw: (content: string) => void;
  onCopyClean: (content: string) => void;
  onBranch: () => void;
}) {
  const isUser = message.role === 'user';
  const msgId = message.id || '';
  const isEditing = editingId === msgId;

  return (
    <div className={`group flex gap-3 ${isUser ? 'flex-row-reverse' : ''} animate-fade-in`}>
      <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${isUser ? 'bg-accent-2/20 text-accent-2' : 'bg-accent/20 text-accent'}`}>
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>
      <div className={`flex-1 min-w-0 ${isUser ? 'text-right' : ''}`}>
        <div className={`flex items-center gap-2 mb-1 ${isUser ? 'justify-end' : ''}`}>
          <span className="text-xs font-medium text-text-secondary">{isUser ? 'You' : message.model || 'Assistant'}</span>
          {message.model && !isUser && <span className="text-[10px] font-mono text-text-muted bg-bg-tertiary px-1.5 py-0.5 rounded">{message.model}</span>}
        </div>
        <div className={`rounded-2xl px-4 py-3 border ${isUser ? 'bg-accent/10 border-accent/20 rounded-br-md' : 'bg-bg-secondary/50 border-border rounded-bl-md'}`}>
          {isEditing ? (
            <div className="space-y-2">
              <textarea
                value={editText}
                onChange={(e) => {}}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSaveEdit(); }
                  if (e.key === 'Escape') { onDeleteMessage(index); }
                }}
                className="w-full bg-bg-primary border border-accent/40 rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none resize-y"
                rows={3}
              />
              <div className="flex gap-2 justify-end">
                <button onClick={onSaveEdit} className="text-xs px-2 py-1 rounded bg-accent text-white">Save</button>
                <button onClick={() => onDeleteMessage(index)} className="text-xs px-2 py-1 rounded bg-bg-tertiary text-text-secondary">Cancel</button>
              </div>
            </div>
          ) : (
            <div className="text-sm"><MarkdownContent content={message.content} /></div>
          )}
          {!isUser && agenticActive && liveToolCalls.length > 0 && isLast && (
            <div className="mt-3 space-y-2">
              {liveToolCalls.map((tc) => (
                <ToolCallCard key={tc.id} call={tc} />
              ))}
            </div>
          )}
        </div>
        <MessageToolbar
          role={message.role === 'user' ? 'user' : 'assistant'}
          content={message.content}
          feedback={feedback[msgId] || null}
          onEdit={isUser ? () => onStartEdit(index) : undefined}
          onDelete={() => onDeleteMessage(index)}
          onBranch={isUser ? onBranch : undefined}
          onRegenerate={!isUser ? () => onRegenerate(index) : undefined}
          onReadAloud={!isUser ? () => onReadAloud(message.content) : undefined}
          onFeedback={!isUser ? (k) => onSetFeedback(msgId, k) : undefined}
          onCopyRaw={() => { navigator.clipboard.writeText(message.content); }}
          onCopyClean={() => { navigator.clipboard.writeText(stripMarkdown(message.content)); }}
        />
      </div>
    </div>
  );
}
