'use client';

import React, { useRef, useEffect } from 'react';
import ConversationsPanel, { type ConvoItem } from '@/components/chat/ConversationsPanel';
import { Download, Plus, Trash2, X, Check } from 'lucide-react';

export default function MobileDrawer({
  open,
  onClose,
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
  open: boolean;
  onClose: () => void;
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
  const touchStartX = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    function onTouchStart(e: TouchEvent) { touchStartX.current = e.touches[0].clientX; }
    function onTouchEnd(e: TouchEvent) {
      if (touchStartX.current !== null) {
        const dx = e.changedTouches[0].clientX - touchStartX.current;
        if (dx < -60) onClose();
      }
      touchStartX.current = null;
    }
    document.addEventListener('touchstart', onTouchStart);
    document.addEventListener('touchend', onTouchEnd);
    return () => {
      document.removeEventListener('touchstart', onTouchStart);
      document.removeEventListener('touchend', onTouchEnd);
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 xl:hidden">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="absolute inset-y-0 right-0 w-[85%] max-w-sm bg-bg-secondary border-l border-border shadow-2xl flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Conversations</h3>
          <button onClick={onClose} className="p-1.5 rounded-xl text-text-secondary hover:text-accent hover:bg-accent/10 transition-all">
            <X size={18} />
          </button>
        </div>
        <div className="flex items-center justify-between px-4 py-2 border-b border-border">
          <div className="flex gap-1">
            <button onClick={onExport} className="p-1.5 rounded-xl text-text-secondary hover:text-accent hover:bg-accent/10 transition-all" title="Export">
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
          onSelect={(id) => { onSelect(id); onClose(); }}
          onDelete={onDelete}
          onExport={onExport}
        />
      </div>
    </div>
  );
}
