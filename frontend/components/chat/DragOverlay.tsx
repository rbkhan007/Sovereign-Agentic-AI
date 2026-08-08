'use client';

import React from 'react';
import { Paperclip } from 'lucide-react';

export default function DragOverlay({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-accent/10 backdrop-blur-sm border-2 border-dashed border-accent/30 rounded-2xl m-4">
      <div className="flex flex-col items-center gap-2 text-accent">
        <Paperclip size={32} className="rotate-45" />
        <span className="text-sm font-medium">Drop files to attach</span>
      </div>
    </div>
  );
}
