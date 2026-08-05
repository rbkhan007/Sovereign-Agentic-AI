'use client';

import React from 'react';

type Variant = 'default' | 'success' | 'warning' | 'danger' | 'brand';

const styles: Record<Variant, string> = {
  default: 'bg-bg-tertiary text-text-secondary',
  success: 'badge-success',
  warning: 'badge-warning',
  danger: 'badge-danger',
  brand: 'bg-accent/10 text-accent border border-accent/25',
};

export default function Badge({ children, variant = 'default', className = '' }: { children: React.ReactNode; variant?: Variant; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${styles[variant]} ${className}`}>
      {children}
    </span>
  );
}
