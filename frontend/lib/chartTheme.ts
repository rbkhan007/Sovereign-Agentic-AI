'use client';

import { useEffect, useState } from 'react';

export interface ChartTheme {
  grid: string;
  axis: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  colors: string[];
}

function readVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>({
    grid: 'rgba(255,255,255,0.04)',
    axis: '#64748b',
    tooltipBg: '#1e293b',
    tooltipBorder: '#334155',
    tooltipText: '#f1f5f9',
    colors: ['#7c3aed', '#10b981', '#eab308', '#ef4444', '#06b6d4', '#f97316'],
  });

  useEffect(() => {
    function read() {
      setTheme({
        grid: readVar('--chart-grid', 'rgba(255,255,255,0.04)'),
        axis: readVar('--chart-axis', '#64748b'),
        tooltipBg: readVar('--chart-tooltip-bg', '#1e293b'),
        tooltipBorder: readVar('--chart-tooltip-border', '#334155'),
        tooltipText: readVar('--chart-tooltip-text', '#f1f5f9'),
        colors: [
          readVar('--chart-1', '#7c3aed'),
          readVar('--chart-2', '#10b981'),
          readVar('--chart-3', '#eab308'),
          readVar('--chart-4', '#ef4444'),
          readVar('--chart-5', '#06b6d4'),
          readVar('--chart-6', '#f97316'),
        ],
      });
    }
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  return theme;
}

export function chartTooltipStyle(theme: ChartTheme) {
  return {
    backgroundColor: theme.tooltipBg,
    border: `1px solid ${theme.tooltipBorder}`,
    borderRadius: 8,
    color: theme.tooltipText,
  };
}
