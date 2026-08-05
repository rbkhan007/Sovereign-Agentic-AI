'use client';

import React, { useEffect } from 'react';
import { X } from 'lucide-react';

interface ImagePreviewModalProps {
  url: string;
  name?: string;
  onClose: () => void;
}

export default function ImagePreviewModal({ url, name, onClose }: ImagePreviewModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-fade-in p-4"
      onClick={onClose}
    >
      <button
        className="absolute top-4 right-4 p-2 rounded-full bg-bg-tertiary/80 text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors"
        onClick={onClose}
        aria-label="Close preview"
      >
        <X size={20} />
      </button>
      <div className="flex flex-col items-center gap-3 max-w-[92vw] max-h-[92vh]" onClick={(e) => e.stopPropagation()}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={name || 'preview'}
          className="max-w-full max-h-[82vh] rounded-xl border border-border object-contain shadow-lg"
        />
        {name && <span className="text-xs text-text-muted truncate max-w-full">{name}</span>}
      </div>
    </div>
  );
}
