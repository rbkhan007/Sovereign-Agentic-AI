'use client';

import React from 'react';

type Size = 'sm' | 'md' | 'lg';

const sizeStyles: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-2.5 text-base',
};

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'success' | 'accent';

const variantStyles: Record<Variant, string> = {
  primary: 'bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25 hover:shadow-accent/30',
  accent: 'bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25 hover:shadow-accent/30',
  secondary: 'bg-bg-tertiary hover:bg-bg-hover text-text-primary border border-border',
  danger: 'bg-danger/10 hover:bg-danger/20 text-danger border border-danger/20',
  success: 'bg-success/10 hover:bg-success/20 text-success border border-success/20',
  ghost: 'bg-transparent hover:bg-bg-tertiary text-text-secondary',
};

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  className = '',
  onClick,
  type = 'button',
  title,
}: {
  children: React.ReactNode;
  variant?: Variant;
  size?: Size;
  disabled?: boolean;
  className?: string;
  onClick?: () => void;
  type?: 'button' | 'submit' | 'reset';
  title?: string;
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      title={title}
      className={`inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed active:scale-95 whitespace-nowrap focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-bg-primary ${sizeStyles[size]} ${variantStyles[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
