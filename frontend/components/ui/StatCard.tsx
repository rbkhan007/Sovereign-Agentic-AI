'use client';

import React from 'react';

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color?: 'accent' | 'success' | 'warning' | 'danger' | 'brand';
  subtitle?: string;
}

const colorMap = {
  accent: 'text-accent',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  brand: 'text-accent',
};

const iconBgMap = {
  accent: 'from-accent/20 to-accent/5 border-accent/20',
  success: 'from-success/20 to-success/5 border-success/20',
  warning: 'from-warning/20 to-warning/5 border-warning/20',
  danger: 'from-danger/20 to-danger/5 border-danger/20',
  brand: 'from-accent/20 to-accent/5 border-accent/20',
};

export default function StatCard({ icon, label, value, color = 'accent', subtitle }: StatCardProps) {
  return (
    <div className="glass-card stat-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md">
      <div className={`stat-card-icon bg-gradient-to-br border ${iconBgMap[color]}`}>
        {icon}
      </div>
      <div className="min-w-0">
        <p className="stat-card-label">{label}</p>
        <p className={`stat-card-value ${colorMap[color]}`}>{value}</p>
        {subtitle && <p className="stat-card-subtitle truncate">{subtitle}</p>}
      </div>
    </div>
  );
}
