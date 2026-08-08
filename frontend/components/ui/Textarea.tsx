'use client';

import React, { useId } from 'react';

export default function Textarea({
  label,
  value,
  onChange,
  placeholder,
  rows = 4,
  disabled = false,
  hint,
  className = '',
}: {
  label?: string;
  value?: string;
  onChange?: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  hint?: string;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && <label htmlFor={id} className="text-xs font-medium text-text-secondary uppercase tracking-wider">{label}</label>}
      <textarea
        id={id}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        rows={rows}
        disabled={disabled}
        className="input-base disabled:opacity-50 resize-y"
      />
      {hint && <span className="text-xs text-text-muted">{hint}</span>}
    </div>
  );
}
