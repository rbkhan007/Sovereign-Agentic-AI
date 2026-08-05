'use client';

import React from 'react';

export default function Switch({
  label,
  checked,
  onChange,
  disabled = false,
  hint,
  className = '',
}: {
  label?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={`flex items-center justify-between gap-4 ${className}`}>
      <div className="flex flex-col gap-0.5">
        {label && <span className="text-sm font-medium text-text-primary">{label}</span>}
        {hint && <span className="text-xs text-text-muted">{hint}</span>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent/50 focus:ring-offset-2 focus:ring-offset-bg-primary disabled:cursor-not-allowed disabled:opacity-50 ${
          checked ? 'bg-accent shadow-inner' : 'bg-bg-tertiary border-border'
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full shadow-md ring-0 transition-transform duration-200 ease-in-out bg-[var(--switch-knob)] ${
            checked ? 'translate-x-5' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  );
}
