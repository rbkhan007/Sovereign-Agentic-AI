'use client';

import React from 'react';
import { FileImage, FileText, FileCode, X } from 'lucide-react';
import { formatBytes, getFileIcon } from '@/lib/chatUtils';

export default function FileChips({ files, previewUrls, onRemove, onPreviewImage }: { files: File[]; previewUrls: string[]; onRemove: (index: number) => void; onPreviewImage: (url: string, name: string) => void }) {
  if (files.length === 0) return null;
  return (
    <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin">
      {files.map((f, i) => (
        <div key={i} className="group relative flex items-center gap-2 px-3 py-2 rounded-xl bg-bg-secondary/60 border border-border shrink-0">
          {previewUrls[i] ? (
            <img src={previewUrls[i]} alt={f.name} className="w-8 h-8 rounded object-cover cursor-pointer" onClick={() => onPreviewImage(previewUrls[i], f.name)} />
          ) : (
            <span className="flex items-center">{getFileIcon(f)}</span>
          )}
          <div className="min-w-0">
            <p className="text-xs font-medium truncate max-w-[120px]">{f.name}</p>
            <p className="text-[10px] text-text-muted">{formatBytes(f.size)}</p>
          </div>
          <button onClick={() => onRemove(i)} className="absolute -top-1.5 -right-1.5 p-0.5 rounded-full bg-bg-tertiary border border-border text-text-muted hover:text-danger transition-colors">
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}
