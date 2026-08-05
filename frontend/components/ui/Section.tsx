'use client';

import React from 'react';

export default function Section({
  title,
  icon,
  description,
  children,
  actions,
  className = '',
}: {
  title: string;
  icon?: React.ReactNode;
  description?: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`glass-card p-6 space-y-5 ${className}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          {icon && (
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent/20 to-accent/5 border border-accent/20 flex items-center justify-center text-accent shrink-0">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-text-primary tracking-tight">{title}</h2>
            {description && <p className="text-sm text-text-secondary mt-0.5">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      {children}
    </div>
  );
}
