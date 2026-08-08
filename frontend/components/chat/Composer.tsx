'use client';

import React, { useRef } from 'react';
import { Paperclip, Mic, Globe, Brain, Send, Square, Keyboard, FileImage, FileText, FileCode, X } from 'lucide-react';
import AutocompletePopover, { type AutocompleteItem } from '@/components/chat/AutocompletePopover';
import ContextChips from '@/components/chat/ContextChips';
import Button from '@/components/ui/Button';
import { MAX_TOKENS, estimateTokens, SLASH_COMMANDS, type SlashCommand, type ContextChip } from '@/lib/chatUtils';
import { getFileIcon } from '@/lib/chatUtils';

export default function Composer({
  input,
  onInputChange,
  onInputKeyDown,
  onSend,
  sending,
  uploading,
  files,
  previewUrls,
  listening,
  planning,
  contextChips,
  slashOpen,
  mentionOpen,
  slashFiltered,
  mentionFiltered,
  slashIndex,
  mentionIndex,
  onSlashIndexChange,
  onMentionIndexChange,
  tokenEstimate,
  composerFocused,
  onFileSelect,
  onRemoveFile,
  onStartVoice,
  onStopVoice,
  onToggleWebSearch,
  onTogglePlanning,
  onSelectSlash,
  onApplyMention,
  onCloseMenus,
  inputRef,
}: {
  input: string;
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onInputKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  sending: boolean;
  uploading: boolean;
  files: File[];
  previewUrls: string[];
  listening: boolean;
  planning: boolean;
  contextChips: ContextChip[];
  slashOpen: boolean;
  mentionOpen: boolean;
  slashFiltered: SlashCommand[];
  mentionFiltered: AutocompleteItem[];
  slashIndex: number;
  mentionIndex: number;
  onSlashIndexChange: (idx: number) => void;
  onMentionIndexChange: (idx: number) => void;
  tokenEstimate: number;
  composerFocused: boolean;
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onRemoveFile: (index: number) => void;
  onStartVoice: () => void;
  onStopVoice: () => void;
  onToggleWebSearch: () => void;
  onTogglePlanning: () => void;
  onSelectSlash: (cmd: SlashCommand) => void;
  onApplyMention: (item: AutocompleteItem, caret: number) => void;
  onCloseMenus: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="px-5 py-4 border-t border-border bg-bg-secondary/30">
      <div className="relative">
        {(slashOpen || mentionOpen) && inputRef.current && (
          <AutocompletePopover
            items={slashOpen ? slashFiltered as AutocompleteItem[] : mentionFiltered}
            activeIndex={slashOpen ? slashIndex : mentionIndex}
            onSelect={(item) => {
              if (slashOpen && 'action' in item) {
                onSelectSlash(item as SlashCommand);
              } else if (!slashOpen && 'id' in item) {
                const caret = inputRef.current?.selectionStart ?? input.length;
                onApplyMention(item as AutocompleteItem, caret);
              }
            }}
            onHover={(idx) => { if (slashOpen) onSlashIndexChange(idx); else onMentionIndexChange(idx); }}
            emptyLabel="No matches"
          />
        )}
        <ContextChips chips={contextChips} onRemove={(id) => {
          const idx = contextChips.findIndex((c) => c.id === id);
          if (idx >= 0) onRemoveFile(idx);
        }} />
        <div className="flex items-end gap-2 mt-2">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef as React.RefObject<HTMLTextAreaElement>}
              value={input}
              onChange={onInputChange}
              onKeyDown={onInputKeyDown}
              placeholder="Type a message... (/ for commands, @ for mentions)"
              rows={1}
              className="w-full bg-bg-primary border border-border rounded-2xl px-4 py-3 pr-20 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 resize-none transition-all"
              style={{ minHeight: '44px', maxHeight: '200px' }}
            />
            <div className="absolute right-2 bottom-2 flex items-center gap-1">
              <input ref={fileRef} type="file" multiple className="hidden" onChange={onFileSelect} />
              <button type="button" onClick={() => fileRef.current?.click()} className="p-1.5 rounded-lg text-text-muted hover:text-accent hover:bg-accent/10 transition-all" title="Attach files">
                <Paperclip size={18} />
              </button>
              {!listening ? (
                <button type="button" onClick={onStartVoice} className="p-1.5 rounded-lg text-text-muted hover:text-accent hover:bg-accent/10 transition-all" title="Voice input">
                  <Mic size={18} />
                </button>
              ) : (
                <button type="button" onClick={onStopVoice} className="p-1.5 rounded-lg text-danger hover:bg-danger/10 transition-all" title="Stop voice">
                  <Square size={18} />
                </button>
              )}
              <button type="button" onClick={onToggleWebSearch} className={`p-1.5 rounded-lg transition-all ${contextChips.some((c) => c.kind === 'web') ? 'text-accent bg-accent/10' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`} title="Web search">
                <Globe size={18} />
              </button>
              <button type="button" onClick={onTogglePlanning} className={`p-1.5 rounded-lg transition-all ${planning ? 'text-accent bg-accent/10' : 'text-text-muted hover:text-accent hover:bg-accent/10'}`} title="Planning mode">
                <Brain size={18} />
              </button>
              <button type="button" onClick={onSend} disabled={sending || uploading || !input.trim()} className="p-1.5 rounded-lg bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-all" title="Send">
                <Send size={18} />
              </button>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between mt-2 text-[10px] text-text-muted">
          <div className="flex items-center gap-3">
            <span>Shift+Enter for new line</span>
            <span>@ to mention files/agents/skills</span>
          </div>
          <span className={tokenEstimate > MAX_TOKENS ? 'text-danger' : ''}>{tokenEstimate} / {MAX_TOKENS} tokens</span>
        </div>
      </div>
    </div>
  );
}
