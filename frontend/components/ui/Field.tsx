'use client';

import React from 'react';

export default function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-text-secondary uppercase tracking-wider">{label}</label>
      <div className="w-full">{children}</div>
      {hint && <span className="text-xs text-text-muted">{hint}</span>}
    </div>
  );
}
