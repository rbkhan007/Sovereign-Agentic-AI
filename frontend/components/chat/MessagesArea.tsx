'use client';

import React from 'react';
import DragOverlay from '@/components/chat/DragOverlay';
import FileChips from '@/components/chat/FileChips';
import EmptyStateCards from '@/components/chat/EmptyStateCards';
import MessageBubble from '@/components/chat/MessageBubble';
import AgentTrace from '@/components/chat/AgentTrace';
import ThinkingIndicator from '@/components/ThinkingIndicator';
import ScrollToBottomButton from '@/components/chat/ScrollToBottomButton';
import ToolCallCard, { type ToolCall } from '@/components/chat/ToolCallCard';
import { type ChatMessage } from '@/lib/api';
import { type WorkflowCard } from '@/components/chat/EmptyStateCards';

export default function MessagesArea({
  messages,
  isDragging,
  files,
  previewUrls,
  thinking,
  thinkingText,
  streaming,
  autoStreaming,
  sending,
  agenticActive,
  liveToolCalls,
  liveActions,
  codeAgent,
  editingId,
  editText,
  feedback,
  atBottom,
  newMessageCount,
  onScroll,
  onDragEnter,
  onDragOver,
  onDragLeave,
  onDrop,
  onRemoveFile,
  onPreviewImage,
  onStartEdit,
  onSaveEdit,
  onDeleteMessage,
  onRegenerate,
  onReadAloud,
  onSetFeedback,
  onCopyRaw,
  onCopyClean,
  onBranch,
  onScrollToBottom,
  onSelectEmptyCard,
  messagesRef,
  chatEndRef,
}: {
  messages: ChatMessage[];
  isDragging: boolean;
  files: File[];
  previewUrls: string[];
  thinking: boolean;
  thinkingText: string;
  streaming: boolean;
  autoStreaming: boolean;
  sending: boolean;
  agenticActive: boolean;
  liveToolCalls: ToolCall[];
  liveActions: any[];
  codeAgent: boolean;
  editingId: string | null;
  editText: string;
  feedback: Record<string, 'up' | 'down'>;
  atBottom: boolean;
  newMessageCount: number;
  onScroll: () => void;
  onDragEnter: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onRemoveFile: (index: number) => void;
  onPreviewImage: (url: string, name: string) => void;
  onStartEdit: (index: number) => void;
  onSaveEdit: () => void;
  onDeleteMessage: (index: number) => void;
  onRegenerate: (index: number) => void;
  onReadAloud: (content: string) => void;
  onSetFeedback: (id: string, kind: 'up' | 'down') => void;
  onCopyRaw: (content: string) => void;
  onCopyClean: (content: string) => void;
  onBranch: () => void;
  onScrollToBottom: () => void;
  onSelectEmptyCard: (card: WorkflowCard) => void;
  messagesRef: React.Ref<HTMLDivElement>;
  chatEndRef: React.Ref<HTMLDivElement>;
}) {
  return (
    <div ref={messagesRef} onScroll={onScroll} className="flex-1 overflow-y-auto scrollbar-thin relative">
      <DragOverlay visible={isDragging} />
      <div onDragEnter={onDragEnter} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop} className="p-4 space-y-4">
        <FileChips files={files} previewUrls={previewUrls} onRemove={onRemoveFile} onPreviewImage={onPreviewImage} />
        {messages.length === 0 && !thinking && (
          <EmptyStateCards onSelect={onSelectEmptyCard} />
        )}
        {messages.map((m, i) => (
          <MessageBubble
            key={m.id ?? i}
            message={m}
            index={i}
            isLast={i === messages.length - 1}
            isStreaming={streaming || autoStreaming}
            agenticActive={agenticActive}
            liveToolCalls={liveToolCalls}
            editingId={editingId}
            editText={editText}
            feedback={feedback}
            onStartEdit={onStartEdit}
            onSaveEdit={onSaveEdit}
            onDeleteMessage={onDeleteMessage}
            onRegenerate={onRegenerate}
            onReadAloud={onReadAloud}
            onSetFeedback={onSetFeedback}
            onCopyRaw={onCopyRaw}
            onCopyClean={onCopyClean}
            onBranch={onBranch}
          />
        ))}
        {agenticActive && liveActions.length > 0 && <AgentTrace actions={liveActions} active={agenticActive} />}
        {(thinking || sending) && <ThinkingIndicator isThinking={thinking} thoughtText={thinkingText || undefined} />}
        <div ref={chatEndRef} />
      </div>
      <ScrollToBottomButton visible={!atBottom} onClick={onScrollToBottom} newMessageCount={newMessageCount} />
    </div>
  );
}
