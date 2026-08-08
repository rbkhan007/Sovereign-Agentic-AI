'use client';

import React from 'react';

export default function RangeSlider({
  label,
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.1,
  disabled = false,
  hint,
  formatValue,
  className = '',
}: {
  label?: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  hint?: string;
  formatValue?: (value: number) => string;
  className?: string;
}) {
  const percentage = ((value - min) / (max - min)) * 100;

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && <label className="text-xs font-medium text-text-secondary uppercase tracking-wider">{label}</label>}
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={e => onChange(parseFloat(e.target.value))}
          className="flex-1 h-2 rounded-full appearance-none cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${percentage}%, var(--bg-tertiary) ${percentage}%, var(--bg-tertiary) 100%)`,
          }}
        />
        <span className="text-xs font-mono text-text-secondary w-10 text-right tabular-nums">
          {formatValue ? formatValue(value) : value.toFixed(1)}
        </span>
      </div>
      {hint && <span className="text-xs text-text-muted">{hint}</span>}
    </div>
  );
}
