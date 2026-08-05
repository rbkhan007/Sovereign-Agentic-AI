'use client';

import React from 'react';

export default function PageHeader({
  title,
  subtitle,
  icon,
  children,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <div className="flex items-start gap-3 min-w-0">
        {icon && (
          <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white shadow-lg shadow-accent/25 shrink-0">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="page-header-title">{title}</h1>
          {subtitle && <p className="page-header-subtitle">{subtitle}</p>}
        </div>
      </div>
      {children && <div className="page-header-actions">{children}</div>}
    </div>
  );
}
