'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { fetchJSON, toArray, toText, type ModelItem, type SystemInfo, type Metrics, type HardwareInfo } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import { useChartTheme, chartTooltipStyle } from '@/lib/chartTheme';
import StatCard from '@/components/ui/StatCard';
import Card from '@/components/ui/Card';
import Skeleton, { CardSkeleton } from '@/components/ui/Skeleton';
import Button from '@/components/ui/Button';
import PageHeader from '@/components/ui/PageHeader';
import { t } from '@/lib/i18n';
import { Activity, Cpu, HardDrive, Zap, ArrowRight, RefreshCw, Loader2, LayoutDashboard } from 'lucide-react';
import Link from 'next/link';
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const MAX_HISTORY = 30;

export default function Dashboard() {
  const [models, setModels] = useState<ModelItem[]>([]);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [hardware, setHardware] = useState<HardwareInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(true);
  const [loadingModel, setLoadingModel] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const { addToast } = useToast();
  const chartTheme = useChartTheme();

  const [history, setHistory] = useState<{ time: string; ram_used_mb: number; vram_used_mb: number; cpu: number; requests: number; tokens_per_sec: number }[]>([]);

  const loadInitial = async () => {
    try {
      const [m, s, met, h, health] = await Promise.all([
        fetchJSON('/v1/models'),
        fetchJSON('/v1/system'),
        fetchJSON('/v1/metrics'),
        fetchJSON('/v1/hardware'),
        fetchJSON('/v1/health').catch(() => ({ status: 'offline' })),
      ]);
      setModels(toArray<ModelItem>(m));
      setSystem(s as SystemInfo);
      setMetrics(met as Metrics);
      setHardware(h as HardwareInfo);
      setBackendOnline((health as Record<string, unknown>).status === 'ok' || (health as Record<string, unknown>).status === 'healthy');
    } catch {
      addToast('Failed to load dashboard data', 'error');
      setBackendOnline(false);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInitial();
  }, []);

  useEffect(() => {
    if (!polling) return;
    const id = setInterval(async () => {
      try {
        const [met, h] = await Promise.all([
          fetchJSON('/v1/metrics'),
          fetchJSON('/v1/hardware'),
        ]);
        setMetrics(met as Metrics);
        setHardware(h as HardwareInfo);

        const now = new Date();
        const time = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

        const m = (met as Record<string, unknown>) || {};
        const hw = (h as HardwareInfo) || ({} as HardwareInfo);
        const ramUsed = Math.max(0, (hw.ram_total_mb || 0) - (hw.ram_available_mb || 0));

        setHistory(prev => {
          const next = [...prev, {
            time,
            ram_used_mb: ramUsed,
            vram_used_mb: hw.gpu_vram_used_mb || 0,
            cpu: hw.cpu_utilization || 0,
            requests: typeof m.requests === 'number' ? m.requests : (prev[prev.length - 1]?.requests || 0),
            tokens_per_sec: typeof m.tokens_per_sec_window === 'number' ? m.tokens_per_sec_window : (typeof m.tokens_per_sec === 'number' ? m.tokens_per_sec : (prev[prev.length - 1]?.tokens_per_sec || 0)),
          }];
          return next.length > MAX_HISTORY ? next.slice(-MAX_HISTORY) : next;
        });
      } catch { /* ignore poll errors */ }
    }, 2000);
    return () => clearInterval(id);
  }, [polling]);

  const loadedCount = useMemo(() => models.filter(m => m.loaded).length, [models]);
  const totalRequests = useMemo(() => {
    if (!metrics) return '—';
    const req = (metrics as Record<string, unknown>).requests;
    if (typeof req === 'number') return req.toLocaleString();
    return '—';
  }, [metrics]);

  async function loadDefaultModel() {
    const executor = models.find(m => (m.role || '').toLowerCase().includes('executor')) || models[0];
    if (!executor) return;
    setLoadingModel(true);
    try {
      await fetchJSON(`/v1/models/load?name=${encodeURIComponent(executor.id)}`, { method: 'POST' });
      addToast(`Loading ${executor.id}...`, 'success');
      setTimeout(loadInitial, 2000);
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setLoadingModel(false);
    }
  }

  if (loading) {
    return (
      <div className="page-shell space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-9 w-48" />
          <Skeleton className="h-10 w-36" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
      </div>
    );
  }

  const cpuLabel = (hardware as Record<string, unknown> | null)?.cpu_name as string || '—';
  const ramUsed = hardware ? Math.max(0, (hardware.ram_total_mb || 0) - (hardware.ram_available_mb || 0)) : 0;
  const ramPct = hardware ? Math.round((ramUsed / (hardware.ram_total_mb || 1)) * 100) : 0;
  const vramPct = hardware ? Math.round(((hardware.gpu_vram_used_mb || 0) / (hardware.gpu_vram_mb || 1)) * 100) : 0;

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title={t('dashboard.title')}
        subtitle={t('dashboard.subtitle')}
        icon={<LayoutDashboard size={20} />}
      >
        <button
          onClick={() => setPolling(p => !p)}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-all bg-bg-tertiary hover:bg-bg-hover border border-border text-text-primary"
          title={polling ? 'Pause live updates' : 'Resume live updates'}
        >
          <RefreshCw size={14} className={polling ? 'animate-spin' : ''} />
          {polling ? t('dashboard.live') : t('dashboard.paused')}
        </button>
        {loadedCount === 0 && (
          <Button onClick={loadDefaultModel} disabled={loadingModel} className="gap-2">
            {loadingModel ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
            Load Model
          </Button>
        )}
        <QuickAction href="/chat" label={t('dashboard.startChatting')} />
        <QuickAction href="/workspace" label={t('dashboard.workspace')} variant="secondary" />
        <QuickAction href="/database" label={t('dashboard.database')} variant="secondary" />
      </PageHeader>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={<Zap size={20} />} label={t('dashboard.totalRequests')} value={totalRequests} color="accent" />
        <StatCard icon={<Cpu size={20} />} label={t('dashboard.modelsLoaded')} value={`${loadedCount} / ${models.length}`} color="success" subtitle="executors active" />
        <StatCard icon={<HardDrive size={20} />} label={t('dashboard.vram')} value={typeof hardware?.gpu_vram_mb === 'number' ? `${hardware.gpu_vram_mb} MB` : '—'} color="warning" subtitle={vramPct > 0 ? `${vramPct}% used` : undefined} />
        <StatCard icon={<Activity size={20} />} label={t('dashboard.backend')} value={backendOnline ? t('dashboard.online') : t('dashboard.offline')} color={backendOnline ? 'success' : 'danger'} subtitle={system?.version ? `v${system.version}` : undefined} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            {t('dashboard.modelsPreview')}
            <span className="text-xs font-normal text-text-muted bg-bg-tertiary px-2 py-0.5 rounded-full">{models.length} total</span>
          </h3>
          <div className="space-y-2">
            {models.length === 0 ? (
              <p className="text-text-muted text-sm py-6 text-center">{t('dashboard.noModelsLoaded')}</p>
            ) : (
              models.slice(0, 6).map(m => (
                <div key={m.id} className="flex items-center justify-between p-3 rounded-xl bg-bg-secondary/40 border border-border transition-all hover:border-accent/30 hover:bg-bg-secondary/60">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`relative flex w-2.5 h-2.5 shrink-0 ${m.loaded ? '' : ''}`}>
                      <span className={`absolute inline-flex h-full w-full rounded-full ${m.loaded ? 'bg-success animate-ping opacity-40' : ''}`} />
                      <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${m.loaded ? 'bg-success' : 'bg-text-muted'}`} />
                    </span>
                    <span className="font-medium text-sm truncate">{m.id}</span>
                    {m.role && <span className="text-xs text-text-muted bg-bg-tertiary px-2 py-0.5 rounded-full capitalize">{m.role}</span>}
                  </div>
                  <span className={`text-xs font-medium shrink-0 ${m.loaded ? 'text-success' : 'text-text-muted'}`}>
                    {m.loaded ? t('dashboard.loaded') : t('dashboard.unloaded')}
                  </span>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card>
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Cpu size={16} className="text-accent" />
            {t('dashboard.hardware')}
          </h3>
          <div className="space-y-3.5">
            {hardware && typeof hardware === 'object' ? (
              <>
                <div className="flex justify-between text-sm gap-3">
                  <span className="text-text-secondary shrink-0">{t('dashboard.cpu')}</span>
                  <span className="font-medium text-right truncate">{cpuLabel || '—'}</span>
                </div>
                <div className="flex justify-between text-sm gap-3">
                  <span className="text-text-secondary shrink-0">{t('dashboard.cores')}</span>
                  <span className="font-medium">{hardware.cpu_cores || '—'}</span>
                </div>
                <div className="flex justify-between text-sm gap-3">
                  <span className="text-text-secondary shrink-0">{t('dashboard.gpu')}</span>
                  <span className="font-medium text-right truncate">{hardware.gpu_name || '—'}</span>
                </div>
                <div className="flex justify-between text-sm gap-3">
                  <span className="text-text-secondary shrink-0">{t('dashboard.backendLabel')}</span>
                  <span className="font-medium">{hardware.gpu_backend || '—'}</span>
                </div>
                <div>
                  <div className="flex justify-between text-sm gap-3 mb-1.5">
                    <span className="text-text-secondary shrink-0">{t('dashboard.ram')}</span>
                    <span className="font-medium">{ramUsed} / {hardware.ram_total_mb || 0} MB ({ramPct}%)</span>
                  </div>
                  <div className="w-full bg-bg-tertiary rounded-full h-1.5 overflow-hidden">
                    <div className={`h-1.5 rounded-full transition-all duration-500 ${ramPct > 85 ? 'bg-danger' : ramPct > 60 ? 'bg-warning' : 'bg-accent'}`} style={{ width: `${Math.min(100, ramPct)}%` }} />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between text-sm gap-3 mb-1.5">
                    <span className="text-text-secondary shrink-0">{t('dashboard.vram')}</span>
                    <span className="font-medium">{hardware.gpu_vram_used_mb || 0} / {hardware.gpu_vram_mb || 0} MB ({vramPct}%)</span>
                  </div>
                  <div className="w-full bg-bg-tertiary rounded-full h-1.5 overflow-hidden">
                    <div className="h-1.5 rounded-full bg-gradient-to-r from-success to-emerald-400 transition-all duration-500" style={{ width: `${Math.min(100, vramPct)}%` }} />
                  </div>
                </div>
                <div className="flex justify-between text-sm gap-3">
                  <span className="text-text-secondary shrink-0">{t('dashboard.cpuUtil')}</span>
                  <span className="font-medium">{(hardware as HardwareInfo).cpu_utilization ?? 0}%</span>
                </div>
              </>
            ) : (
              <p className="text-text-muted text-sm">{t('dashboard.noHardwareInfo')}</p>
            )}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card>
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Activity size={16} className="text-accent" />
            {t('dashboard.memoryUsage')}
          </h3>
          {history.length > 1 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history}>
                  <defs>
                    <linearGradient id="ramGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={chartTheme.colors[0]} stopOpacity={0.35} />
                      <stop offset="95%" stopColor={chartTheme.colors[0]} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="vramGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={chartTheme.colors[1]} stopOpacity={0.35} />
                      <stop offset="95%" stopColor={chartTheme.colors[1]} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} vertical={false} />
                  <XAxis dataKey="time" stroke={chartTheme.axis} fontSize={11} tickLine={false} axisLine={false} minTickGap={40} />
                  <YAxis stroke={chartTheme.axis} fontSize={11} tickLine={false} axisLine={false} width={52} />
                  <Tooltip contentStyle={chartTooltipStyle(chartTheme)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" dataKey="ram_used_mb" stroke={chartTheme.colors[0]} strokeWidth={2} fillOpacity={1} fill="url(#ramGrad)" name="RAM Used (MB)" />
                  <Area type="monotone" dataKey="vram_used_mb" stroke={chartTheme.colors[1]} strokeWidth={2} fillOpacity={1} fill="url(#vramGrad)" name="VRAM Used (MB)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-text-muted text-sm py-10 text-center">{t('dashboard.collectingData')}</p>
          )}
        </Card>

        <Card>
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Zap size={16} className="text-warning" />
            {t('dashboard.cpuThroughput')}
          </h3>
          {history.length > 1 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history}>
                  <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} vertical={false} />
                  <XAxis dataKey="time" stroke={chartTheme.axis} fontSize={11} tickLine={false} axisLine={false} minTickGap={40} />
                  <YAxis yAxisId="left" stroke={chartTheme.axis} fontSize={11} tickLine={false} axisLine={false} width={42} domain={[0, 100]} unit="%" />
                  <YAxis yAxisId="right" orientation="right" stroke={chartTheme.axis} fontSize={11} tickLine={false} axisLine={false} width={44} />
                  <Tooltip contentStyle={chartTooltipStyle(chartTheme)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line yAxisId="left" type="monotone" dataKey="cpu" stroke={chartTheme.colors[2]} strokeWidth={2} dot={false} name="CPU %" />
                  <Line yAxisId="right" type="monotone" dataKey="tokens_per_sec" stroke={chartTheme.colors[3]} strokeWidth={2} dot={false} name="Tokens / sec (60s window)" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-text-muted text-sm py-10 text-center">{t('dashboard.collectingData')}</p>
          )}
        </Card>
      </div>
    </div>
  );
}

function QuickAction({ href, label, variant = 'primary' }: { href: string; label: string; variant?: 'primary' | 'secondary' }) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
        variant === 'primary'
          ? 'bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25'
          : 'bg-bg-tertiary hover:bg-bg-hover text-text-primary border border-border'
      }`}
    >
      {label}
      <ArrowRight size={14} />
    </Link>
  );
}
