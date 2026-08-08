'use client';

import React from 'react';
import { ArrowDown } from 'lucide-react';

export default function ScrollToBottomButton({ visible, onClick, newMessageCount }: { visible: boolean; onClick: () => void; newMessageCount: number }) {
  if (!visible) return null;
  return (
    <button
      onClick={onClick}
      className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-accent text-white text-xs font-medium shadow-lg hover:bg-accent-hover transition-all animate-fade-in"
    >
      <ArrowDown size={14} />
      {newMessageCount > 0 && <span>{newMessageCount} new</span>}
    </button>
  );
}
