'use client';

import React, { useId } from 'react';

export default function Input({
  label,
  type = 'text',
  value,
  onChange,
  onKeyDown,
  placeholder,
  disabled = false,
  hint,
  className = '',
  step,
  min,
  max,
}: {
  label?: string;
  type?: string;
  value?: string | number;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  placeholder?: string;
  disabled?: boolean;
  hint?: string;
  className?: string;
  step?: string | number;
  min?: string | number;
  max?: string | number;
}) {
  const id = useId();
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && <label htmlFor={id} className="text-xs font-medium text-text-secondary uppercase tracking-wider">{label}</label>}
      <input
        id={id}
        type={type}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        step={step}
        min={min}
        max={max}
        className="input-base disabled:opacity-50 disabled:cursor-not-allowed"
      />
      {hint && <span className="text-xs text-text-muted">{hint}</span>}
    </div>
  );
}
