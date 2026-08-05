'use client';

import React from 'react';

export default function Card({ children, className = '', hover = false }: { children: React.ReactNode; className?: string; hover?: boolean }) {
  return (
    <div className={`glass-card p-5 transition-all duration-200 ${hover ? 'hover:-translate-y-0.5 hover:shadow-lg hover:shadow-accent/5' : ''} ${className}`}>
      {children}
    </div>
  );
}
