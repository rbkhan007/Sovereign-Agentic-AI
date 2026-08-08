'use client';

import React, { useEffect, useState, useRef, useCallback } from 'react';
import { fetchJSON, toArray, toText } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Input from '@/components/ui/Input';
import Badge from '@/components/ui/Badge';
import Skeleton, { CardSkeleton } from '@/components/ui/Skeleton';
import StatCard from '@/components/ui/StatCard';
import PageHeader from '@/components/ui/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import CopyCode from '@/components/ui/CopyCode';
import { t } from '@/lib/i18n';
import { Database, HardDrive, Trash2, Activity, Search, RefreshCw, Server, Layers, Cpu, BarChart3, Clock, Boxes, SearchX, Terminal } from 'lucide-react';

interface ExtendedDbStats {
  connected?: boolean;
  enabled?: boolean;
  count?: number;
  total_tokens?: number;
  vector_dim?: number;
  host?: string;
  port?: number | string;
  database?: string;
  ivfflat?: boolean;
  hnsw?: boolean;
  table_bytes?: number;
  cache_entries?: number;
  pool?: { min: number; max: number; active: number };
  auto_prune?: boolean;
  prune_interval_hours?: number;
  prune_max_age_days?: number;
  agents?: Record<string, number>;
  pgversion?: string;
}

interface MemoryRow {
  id: string;
  content: string;
  agent?: string;
  created_at?: number | string;
}

export default function DatabasePage() {
  const [stats, setStats] = useState<ExtendedDbStats | null>(null);
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<{ content: string; score: number; agent?: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const logEndRef = useRef<HTMLDivElement>(null);
  const { addToast } = useToast();

  const load = async () => {
    setLoading(true);
    try {
      const [db, mem] = await Promise.all([
        fetchJSON('/v1/db/stats') as Promise<ExtendedDbStats>,
        fetchJSON('/v1/memory/recent?limit=50')
      ]);
      setStats(db);
      const memData = mem as { results?: { id: string; thought: string; agent?: string; created_at?: number }[] };
      const memArr = memData.results || toArray<{ id: string; thought: string; agent?: string }>(mem);
      setMemories(memArr.map(m => ({ id: String(m.id), content: m.thought ?? '', agent: m.agent, created_at: (m as Record<string, unknown>).created_at as number | string | undefined })));
    } catch {
      addToast('Failed to load database stats', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!autoScroll || !logEndRef.current) return;
    logEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [logs, autoScroll]);

  useEffect(() => {
    let mounted = true;
    async function tick() {
      try {
        const data = await fetchJSON('/v1/admin/logs?lines=80').catch(() => null);
        if (!mounted) return;
        const arr = (data as { logs?: string[] } | null)?.logs || toArray<string>(data || []);
        setLogs(arr.slice(-120));
      } catch { /* ignore */ }
    }
    tick();
    const id = setInterval(tick, 3000);
    return () => { mounted = false; clearInterval(id); };
  }, [autoScroll]);

  async function searchMemory() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const data = await fetchJSON('/v1/memory/search', { method: 'POST', body: JSON.stringify({ query: searchQuery, limit: 10 }) }) as { results?: unknown[] };
      setSearchResults((data.results || toArray<unknown>(data)).map(r => {
        if (typeof r === 'string') return { content: r, score: 0, agent: undefined };
        const o = r as Record<string, unknown>;
        return { content: (o.thought ?? o.content ?? '') as string, score: Number(o.similarity ?? 0), agent: (o.agent ?? o.agent_name) as string | undefined };
      }));
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setSearching(false);
    }
  }

  async function pruneMemory() {
    if (!window.confirm('Prune old memories beyond the configured age?')) return;
    try {
      await fetchJSON('/v1/memory/prune', { method: 'POST' });
      addToast('Memory pruned', 'success');
      load();
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  async function clearMemory() {
    if (!window.confirm('Clear ALL memories? This cannot be undone.')) return;
    try {
      await fetchJSON('/v1/memory/clear', { method: 'POST' });
      addToast('Memory cleared', 'success');
      load();
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  if (loading) {
    return (
      <div className="page-shell space-y-6">
        <Skeleton className="h-9 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const isConnected = stats?.connected;
  const tableMB = stats?.table_bytes ? (stats.table_bytes / 1024 / 1024).toFixed(2) : '0';

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title={t('database.title')}
        subtitle={t('database.subtitle')}
        icon={<Database size={20} />}
      >
        <Button onClick={load} variant="secondary" className="gap-2">
          <RefreshCw size={16} />
          {t('models.refresh')}
        </Button>
      </PageHeader>

      <div className="flex items-center gap-2.5 flex-wrap">
        <Badge variant={isConnected ? 'success' : 'danger'}>
          <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-success' : 'bg-danger'}`} />
          {isConnected ? t('database.connected') : t('database.disconnected')}
        </Badge>
        {!!stats?.host && (
          <span className="text-sm text-text-secondary flex items-center gap-1.5">
            <Server size={14} />
            {String(stats.host)}:{String(stats.port)}
          </span>
        )}
        {!!stats?.enabled && (
          <span className="text-sm text-text-secondary flex items-center gap-1.5">
            <Database size={14} />
            {stats.database || 'database'}
          </span>
        )}
        {!isConnected && (
          <span className="text-sm text-text-muted">Running in-memory mode — start with <code className="text-xs px-1.5 py-0.5 rounded bg-bg-tertiary border border-border">--db</code> for persistence.</span>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={<Boxes size={20} />} label={t('database.memories')} value={String(stats?.count ?? '0')} color="accent" />
        <StatCard icon={<Activity size={20} />} label={t('database.totalTokens')} value={formatNumber(stats?.total_tokens ?? 0)} color="success" />
        <StatCard icon={<Layers size={20} />} label={t('database.vectorDim')} value={`${String(stats?.vector_dim ?? 384)}d`} color="warning" subtitle={stats?.ivfflat ? 'IVFFlat indexed' : stats?.hnsw ? 'HNSW indexed' : 'No index'} />
        <StatCard icon={<HardDrive size={20} />} label="Table Size" value={stats?.table_bytes ? `${tableMB} MB` : '—'} color="accent" subtitle={stats?.cache_entries ? `${stats.cache_entries} cached` : undefined} />
      </div>

      {isConnected && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          <Card>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2"><Cpu size={16} className="text-accent" /> Connection Pool</h3>
            <div className="space-y-2.5 text-sm">
              <div className="flex justify-between"><span className="text-text-secondary">Active</span><span className="font-mono font-medium">{stats?.pool?.active ?? 0}</span></div>
              <div className="flex justify-between"><span className="text-text-secondary">Min / Max</span><span className="font-mono">{stats?.pool?.min ?? 1} / {stats?.pool?.max ?? 4}</span></div>
              <div className="w-full bg-bg-tertiary rounded-full h-2 mt-1 overflow-hidden">
                <div className="bg-gradient-to-r from-accent to-accent-2 h-2 rounded-full transition-all duration-500" style={{ width: `${Math.min(100, ((stats?.pool?.active ?? 0) / (stats?.pool?.max ?? 4)) * 100)}%` }} />
              </div>
            </div>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2"><BarChart3 size={16} className="text-success" /> Index Status</h3>
            <div className="space-y-2.5 text-sm">
              <div className="flex justify-between">
                <span className="text-text-secondary">Vector Index</span>
                <Badge variant={(stats?.ivfflat || stats?.hnsw) ? 'success' : 'default'}>{stats?.ivfflat ? 'IVFFlat' : stats?.hnsw ? 'HNSW' : 'Deferred'}</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Vector Dimension</span>
                <span className="font-mono">{stats?.vector_dim ?? 384}d</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Index Thresholds</span>
                <span className="font-mono">HNSW ≥100 · IVFFlat &gt;2,000</span>
              </div>
            </div>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2"><Clock size={16} className="text-warning" /> Auto-Prune</h3>
            <div className="space-y-2.5 text-sm">
              <div className="flex justify-between">
                <span className="text-text-secondary">Status</span>
                <Badge variant={stats?.auto_prune ? 'success' : 'default'}>{stats?.auto_prune ? 'Running' : 'Stopped'}</Badge>
              </div>
              <div className="flex justify-between"><span className="text-text-secondary">Interval</span><span className="font-mono">{stats?.prune_interval_hours ?? 6}h</span></div>
              <div className="flex justify-between"><span className="text-text-secondary">Max Age</span><span className="font-mono">{stats?.prune_max_age_days ?? 30}d</span></div>
            </div>
          </Card>
        </div>
      )}

      {/* Memory Data Explorer */}
      <Card>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2"><Database size={16} className="text-accent" /> Memory Data Explorer</h3>
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left text-[10px] uppercase tracking-wider text-text-muted font-medium pb-2 pr-3">ID</th>
                <th className="text-left text-[10px] uppercase tracking-wider text-text-muted font-medium pb-2 pr-3">Agent</th>
                <th className="text-left text-[10px] uppercase tracking-wider text-text-muted font-medium pb-2 pr-3">Thought</th>
                <th className="text-left text-[10px] uppercase tracking-wider text-text-muted font-medium pb-2">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {memories.length === 0 && (
                <tr><td colSpan={4} className="py-6 text-center text-text-muted text-xs">{t('database.noMemories')}</td></tr>
              )}
              {memories.slice(0, 30).map(m => (
                <tr key={m.id} className="hover:bg-bg-tertiary/40 transition-colors">
                  <td className="py-2 pr-3 font-mono text-[11px] text-text-muted">{m.id.slice(0, 8)}</td>
                  <td className="py-2 pr-3"><Badge variant="brand" className="!text-[10px] !px-1.5 !py-0.5">{m.agent || '—'}</Badge></td>
                  <td className="py-2 pr-3 text-xs text-text-secondary truncate max-w-[320px]">{m.content}</td>
                  <td className="py-2 text-[11px] text-text-muted tabular-nums">{m.created_at ? new Date(m.created_at as number).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h3 className="font-semibold mb-4 flex items-center gap-2"><Search size={18} className="text-accent" /> {t('database.searchMemory')}</h3>
          <div className="flex gap-2 mb-4">
            <Input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') searchMemory(); }} placeholder={t('database.searchPlaceholder')} className="flex-1" />
            <Button onClick={searchMemory} disabled={searching}>{searching ? t('common.loading') : t('common.search')}</Button>
          </div>
          <div className="space-y-2 max-h-80 overflow-y-auto scrollbar-thin">
            {searchResults.length === 0 && searchQuery && !searching && (
              <EmptyState icon={<SearchX size={22} />} title={t('database.noResults')} description="Try different keywords or a broader query." />
            )}
            {searchResults.map((r, i) => (
              <div key={i} className="p-3.5 rounded-xl bg-bg-primary/30 border border-border">
                <div className="flex items-center justify-between mb-1.5">
                  <Badge variant="brand">{r.score.toFixed(3)}</Badge>
                  {r.agent && <span className="text-xs text-text-muted">{r.agent}</span>}
                </div>
                <p className="text-sm leading-relaxed">{r.content}</p>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold flex items-center gap-2"><Terminal size={18} className="text-accent" /> Live Query Log</h3>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-text-muted cursor-pointer">
                <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} className="accent-accent" />
                Auto-scroll
              </label>
              <Button variant="secondary" size="sm" onClick={load} className="gap-1.5"><RefreshCw size={12} /> Refresh</Button>
            </div>
          </div>
          <div className="rounded-xl border border-border overflow-hidden" style={{ background: '#282a36' }}>
            <div className="flex items-center gap-1.5 px-3 py-2 border-b border-[#44475a]" style={{ background: '#21222c' }}>
              <span className="w-2 h-2 rounded-full" style={{ background: '#ff5555' }} />
              <span className="w-2 h-2 rounded-full" style={{ background: '#f1fa8c' }} />
              <span className="w-2 h-2 rounded-full" style={{ background: '#50fa7b' }} />
              <span className="ml-2 text-[11px] font-mono" style={{ color: '#bd93f9' }}>query-log</span>
            </div>
            <div className="p-3 h-64 overflow-y-auto scrollbar-thin font-mono text-[11px] leading-relaxed" style={{ color: '#f8f8f2' }}>
              {logs.length === 0 && <span style={{ color: '#6272a4' }}>Waiting for log entries…</span>}
              {logs.map((line, i) => {
                const isErr = /ERROR|error|Traceback|exception/i.test(line);
                const isWarn = /WARN|warning/i.test(line);
                return (
                  <div key={i} style={{ color: isErr ? '#ff5555' : isWarn ? '#f1fa8c' : '#f8f8f2' }}>
                    {line}
                  </div>
                );
              })}
              <div ref={logEndRef} />
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}
