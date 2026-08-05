'use client';

import React from 'react';

export interface AutocompleteItem {
  id: string;
  label: string;
  description?: string;
  hint?: string;
  icon?: React.ReactNode;
  trailing?: React.ReactNode;
}

interface AutocompletePopoverProps {
  items: AutocompleteItem[];
  activeIndex: number;
  onSelect: (item: AutocompleteItem) => void;
  onHover: (index: number) => void;
  emptyLabel?: string;
}

export default function AutocompletePopover({
  items,
  activeIndex,
  onSelect,
  onHover,
  emptyLabel = 'No matches',
}: AutocompletePopoverProps) {
  return (
    <div className="absolute bottom-full left-0 mb-2 w-full max-w-md z-30 animate-fade-in">
      <div className="glass-card p-1.5 max-h-72 overflow-y-auto scrollbar-thin shadow-lg shadow-accent/10 border border-accent/20">
        {items.length === 0 ? (
          <div className="px-3 py-2.5 text-xs text-text-muted">{emptyLabel}</div>
        ) : (
          items.map((item, i) => (
            <button
              key={item.id}
              type="button"
              onMouseEnter={() => onHover(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                onSelect(item);
              }}
              className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-colors ${
                i === activeIndex
                  ? 'bg-accent-soft text-text-primary'
                  : 'text-text-secondary hover:bg-bg-tertiary'
              }`}
            >
              {item.icon && (
                <span className={`shrink-0 ${i === activeIndex ? 'text-accent' : 'text-text-muted'}`}>
                  {item.icon}
                </span>
              )}
              <span className="flex-1 min-w-0">
                <span className="block text-sm font-medium truncate">{item.label}</span>
                {item.description && (
                  <span className="block text-[11px] text-text-muted truncate">{item.description}</span>
                )}
              </span>
              {item.trailing ?? (item.hint && (
                <kbd className="shrink-0 text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-tertiary text-text-muted border border-border">
                  {item.hint}
                </kbd>
              ))}
            </button>
          ))
        )}
      </div>
    </div>
  );
}
