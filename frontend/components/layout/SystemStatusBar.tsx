'use client';

import React, { useEffect, useState } from 'react';
import { Activity, Cpu, HardDrive, MemoryStick, Zap, Wifi, WifiOff } from 'lucide-react';
import { fetchJSON, type HardwareInfo, type Metrics } from '@/lib/api';

interface StatusSnapshot {
  online: boolean;
  cpu: number;
  ramUsedMb: number;
  ramTotalMb: number;
  vramUsedMb: number;
  vramTotalMb: number;
  tokensPerSec: number;
  backend: string;
  gpuName: string;
}

const empty: StatusSnapshot = {
  online: false,
  cpu: 0,
  ramUsedMb: 0,
  ramTotalMb: 0,
  vramUsedMb: 0,
  vramTotalMb: 0,
  tokensPerSec: 0,
  backend: '',
  gpuName: '',
};

function pct(used: number, total: number): number {
  return total > 0 ? Math.round((used / total) * 100) : 0;
}

function tone(value: number): string {
  if (value > 85) return 'var(--danger)';
  if (value > 60) return 'var(--warning)';
  return 'var(--accent)';
}

function Meter({ value, tone: toneVar }: { value: number; tone: string }) {
  return (
    <span className="status-track">
      <span className="status-fill" style={{ width: `${Math.min(100, Math.max(0, value))}%`, background: toneVar }} />
    </span>
  );
}

function mb(used: number, total: number): string {
  if (!total) return '—';
  const gb = (mb: number) => mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
  return `${gb(used)} / ${gb(total)}`;
}

/** Thin global telemetry strip pinned above every page's content. */
export default function SystemStatusBar() {
  const [snap, setSnap] = useState<StatusSnapshot>(empty);

  useEffect(() => {
    let mounted = true;
    async function tick() {
      try {
        const [h, m, health] = await Promise.all([
          fetchJSON<HardwareInfo | null>('/v1/hardware').catch(() => null),
          fetchJSON<Metrics | null>('/v1/metrics').catch(() => null),
          fetchJSON<{ status?: string } | null>('/v1/health', { timeout: 3000 }).catch(() => null),
        ]);
        if (!mounted) return;
        const hw = (h || {}) as HardwareInfo;
        const met = (m || {}) as Record<string, unknown>;
        const ramUsed = Math.max(0, (hw.ram_total_mb || 0) - (hw.ram_available_mb || 0));
        const tps = typeof met.tokens_per_sec_window === 'number'
          ? met.tokens_per_sec_window as number
          : typeof met.tokens_per_sec === 'number'
            ? met.tokens_per_sec as number
            : 0;
        setSnap({
          online: !!health && health.status !== 'offline',
          cpu: hw.cpu_utilization || 0,
          ramUsedMb: ramUsed,
          ramTotalMb: hw.ram_total_mb || 0,
          vramUsedMb: hw.gpu_vram_used_mb || 0,
          vramTotalMb: hw.gpu_vram_mb || 0,
          tokensPerSec: tps,
          backend: hw.gpu_backend || '',
          gpuName: hw.gpu_name || '',
        });
      } catch {
        if (mounted) setSnap(s => ({ ...s, online: false }));
      }
    }
    tick();
    const id = setInterval(tick, 3000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  const cpuPct = pct(snap.cpu, 100);
  const ramPct = pct(snap.ramUsedMb, snap.ramTotalMb);
  const vramPct = pct(snap.vramUsedMb, snap.vramTotalMb);

  return (
    <div className="status-bar">
      <span className="inline-flex items-center gap-1.5 font-medium text-text-primary shrink-0">
        {snap.online
          ? <Wifi size={13} className="text-success" />
          : <WifiOff size={13} className="text-danger" />}
        <span className="hidden sm:inline">Local Engine</span>
      </span>

      <span className="h-3.5 w-px bg-border hidden sm:inline-block" />

      <span className="status-metric shrink-0" title={snap.backend || 'Backend'}>
        <Cpu size={13} className="text-accent-2" />
        <span className="hidden md:inline">CPU</span>
        <Meter value={cpuPct} tone={tone(cpuPct)} />
        <span className="tabular-nums w-9 text-text-primary">{cpuPct}%</span>
      </span>

      <span className="status-metric shrink-0" title="System RAM">
        <MemoryStick size={13} className="text-accent" />
        <span className="hidden md:inline">RAM</span>
        <Meter value={ramPct} tone={tone(ramPct)} />
        <span className="tabular-nums text-text-primary hidden lg:inline">{mb(snap.ramUsedMb, snap.ramTotalMb)}</span>
        <span className="tabular-nums text-text-primary lg:hidden">{ramPct}%</span>
      </span>

      <span className="status-metric shrink-0" title={snap.gpuName || 'GPU memory'}>
        <HardDrive size={13} className="text-accent-3" />
        <span className="hidden md:inline">VRAM</span>
        <Meter value={vramPct} tone={tone(vramPct)} />
        <span className="tabular-nums text-text-primary hidden lg:inline">{mb(snap.vramUsedMb, snap.vramTotalMb)}</span>
        <span className="tabular-nums text-text-primary lg:hidden">{vramPct}%</span>
      </span>

      <span className="flex-1" />

      <span className="status-metric shrink-0" title="Inference throughput (60s window)">
        <Zap size={13} className="text-warning" />
        <span className="tabular-nums text-text-primary">{snap.tokensPerSec > 0 ? `${snap.tokensPerSec.toFixed(1)}` : '—'} tok/s</span>
      </span>

      <span className="hidden sm:inline-flex items-center gap-1.5 text-text-muted">
        <Activity size={13} />
        {snap.backend ? snap.backend : 'Auto'}
      </span>
    </div>
  );
}
