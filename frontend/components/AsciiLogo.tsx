'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import asciiArt from '@/public/ascii-art.txt?raw';
import { useTheme } from '@/components/ThemeProvider';

const BASE_FONT_PX = 10;
const MAX_WIDTH_PX = 1233;
const MAX_HEIGHT_PX = 840;

/* Density-tier palettes. Light theme gets a colourful gradient so the ASCII
 * art reads as a rich visual; dark theme stays a single subtle accent tint. */
const LIGHT_TIER_COLORS = [
  '#cdd1e4', // faint background dots
  '#a5b4fc', // indigo-300
  '#7c3aed', // violet (accent)
  '#0ea5e9', // sky-500
  '#06b6d4', // cyan-500
  '#f43f5e', // rose-500
];

/* Character → density tier (higher = more ink). Falls back to tier 2. */
const TIER_MAP: Record<string, number> = {
  '.': 0, ',': 0, "'": 0, '`': 0, ' ': 0,
  ':': 1, ';': 1, '-': 1, '_': 1, '~': 1, '"': 1,
  'i': 2, 'l': 2, 'I': 2, '1': 2, 't': 2, '!': 2, '|': 2, ']': 2, '[': 2, ')': 2, '(': 2,
  '+': 3, '=': 3, '>': 3, '<': 3, '*': 3, '/': 3, '\\': 3, '&': 3, '#': 3, '%': 3,
  '×': 4, '÷': 4, '±': 4, '≈': 4, '≠': 4, '≤': 4, '≥': 4, '°': 4, '•': 4, '◦': 4, '∏': 4, '·': 4,
  '∑': 5, '√': 5, '∫': 5, '∂': 5, '∇': 5, '⋆': 5, 'π': 5, '⊙': 5,
};

function tierOf(ch: string): number {
  return TIER_MAP[ch] ?? 2;
}

/* Render the ASCII art as colored runs. Consecutive same-tier characters are
 * grouped into a single span so the DOM stays small (~a few hundred nodes). */
function renderColoredArt(art: string, light: boolean): React.ReactNode[] {
  const lines = art.split('\n');
  return lines.map((line, li) => {
    const runs: { text: string; tier: number }[] = [];
    for (const ch of line) {
      const tier = tierOf(ch);
      const last = runs[runs.length - 1];
      if (last && last.tier === tier) {
        last.text += ch;
      } else {
        runs.push({ text: ch, tier });
      }
    }
    return (
      <span key={li} className="block">
        {runs.map((run, ri) => (
          <span
            key={ri}
            style={light ? { color: LIGHT_TIER_COLORS[run.tier % LIGHT_TIER_COLORS.length] } : undefined}
            className={light ? undefined : 'text-accent/70'}
          >
            {run.text}
          </span>
        ))}
      </span>
    );
  });
}

export default function AsciiLogo() {
  const boxRef = useRef<HTMLDivElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const [scale, setScale] = useState(1);
  const { theme } = useTheme();
  const light = theme === 'light';

  const colored = useMemo(() => renderColoredArt(asciiArt, light), [light]);

  useEffect(() => {
    const box = boxRef.current;
    const pre = preRef.current;
    if (!box || !pre) return;

    const fit = () => {
      const w = box.clientWidth;
      const h = box.clientHeight;
      const nw = pre.scrollWidth;
      const nh = pre.scrollHeight;
      if (w > 0 && h > 0 && nw > 0 && nh > 0) {
        setScale(Math.min(w / nw, h / nh));
      }
    };

    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(box);
    return () => ro.disconnect();
  }, []);

  return (
    <div
      ref={boxRef}
      className="ascii-logo relative w-full overflow-hidden select-none"
      style={{ maxWidth: MAX_WIDTH_PX, aspectRatio: `${MAX_WIDTH_PX} / ${MAX_HEIGHT_PX}` }}
      aria-label="Agentic LLM ASCII logo"
    >
      <pre
        ref={preRef}
        className="absolute left-1/2 top-1/2 m-0 font-mono leading-none whitespace-pre"
        style={{ fontSize: BASE_FONT_PX, transform: `translate(-50%, -50%) scale(${scale})` }}
      >
        {colored}
      </pre>
    </div>
  );
}
