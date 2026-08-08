'use client';

import React from 'react';
import ConversationsPanel, { type ConvoItem } from '@/components/chat/ConversationsPanel';
import { Download, Plus, Trash2, Check } from 'lucide-react';

export default function ChatSidebar({
  conversations,
  convId,
  selectedWorkspace,
  pendingAction,
  onSelect,
  onDelete,
  onExport,
  onNewChat,
  onClearAll,
}: {
  conversations: ConvoItem[];
  convId: string;
  selectedWorkspace: string;
  pendingAction: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onExport: () => void;
  onNewChat: () => void;
  onClearAll: () => void;
}) {
  return (
    <div className="w-72 border-l border-border bg-bg-secondary/40 p-4 hidden xl:flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-3 px-0.5">
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Conversations</h3>
        <div className="flex gap-1">
          <button onClick={onExport} className="p-1.5 rounded-xl text-text-secondary hover:text-accent hover:bg-accent/10 transition-all" title="Export current conversation">
            <Download size={15} />
          </button>
          <button onClick={onNewChat} className="p-1.5 rounded-xl text-text-secondary hover:text-accent hover:bg-accent/10 transition-all" title="New chat">
            <Plus size={16} />
          </button>
          {conversations.length > 0 && (
            <button onClick={onClearAll} className="p-1.5 rounded-xl text-text-secondary hover:text-danger hover:bg-danger/10 transition-all" title="Clear all">
              {pendingAction === 'clear-all' ? <Check size={14} /> : <Trash2 size={14} />}
            </button>
          )}
        </div>
      </div>
      <ConversationsPanel
        conversations={conversations}
        convId={convId}
        selectedWorkspace={selectedWorkspace}
        onSelect={onSelect}
        onDelete={onDelete}
        onExport={onExport}
      />
    </div>
  );
}
