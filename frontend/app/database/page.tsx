'use client';

import React, { useEffect, useState } from 'react';
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
import { t } from '@/lib/i18n';
import { Database, HardDrive, Trash2, Activity, Search, RefreshCw, Server, Layers, Cpu, BarChart3, Clock, Boxes, SearchX } from 'lucide-react';

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

export default function DatabasePage() {
  const [stats, setStats] = useState<ExtendedDbStats | null>(null);
  const [memories, setMemories] = useState<{ id: string; content: string; agent?: string }[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<{ content: string; score: number; agent?: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const { addToast } = useToast();

  const load = async () => {
    setLoading(true);
    try {
      const [db, mem] = await Promise.all([
        fetchJSON('/v1/db/stats') as Promise<ExtendedDbStats>,
        fetchJSON('/v1/memory/recent?limit=30')
      ]);
      setStats(db);
      const memData = mem as { results?: { id: string; content: string; agent?: string }[] };
      setMemories(memData.results || toArray<{ id: string; content: string; agent?: string }>(mem));
    } catch {
      addToast('Failed to load database stats', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  async function searchMemory() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const data = await fetchJSON('/v1/memory/search', { method: 'POST', body: JSON.stringify({ query: searchQuery, limit: 10 }) });
      setSearchResults(toArray<{ content: string; score: number; agent?: string }>(data));
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
  const agentEntries = stats?.agents ? Object.entries(stats.agents) : [];
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
            {CONFIG_DB_NAME(stats)}
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

      {isConnected && agentEntries.length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold mb-3">Memory by Agent</h3>
          <div className="flex flex-wrap gap-2">
            {agentEntries.map(([agent, count]) => (
              <div key={agent} className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-bg-tertiary/50 border border-border text-sm">
                <span className="font-medium">{agent}</span>
                <Badge variant="brand">{count}</Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <h3 className="font-semibold mb-4 flex items-center gap-2"><Search size={18} className="text-accent" /> {t('database.searchMemory')}</h3>
          <div className="flex gap-2 mb-4">
            <Input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') searchMemory(); }}
              placeholder={t('database.searchPlaceholder')}
              className="flex-1"
            />
            <Button onClick={searchMemory} disabled={searching}>
              {searching ? t('common.loading') : t('common.search')}
            </Button>
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
          <h3 className="font-semibold mb-4">Actions & Recent</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
            <Button onClick={pruneMemory} variant="secondary" className="gap-2 justify-start">
              <Trash2 size={16} /> {t('database.pruneOldMemories')} (&gt;{stats?.prune_max_age_days ?? 30}d)
            </Button>
            <Button onClick={clearMemory} variant="danger" className="gap-2 justify-start">
              <Trash2 size={16} /> {t('database.clearAllMemories')}
            </Button>
          </div>
          <h4 className="text-sm font-semibold mb-3 text-text-secondary">Recent Memories</h4>
          <div className="space-y-2 max-h-64 overflow-y-auto scrollbar-thin">
            {memories.length === 0 && <p className="text-text-muted text-sm">{t('database.noMemories')}</p>}
            {memories.slice(0, 20).map(m => (
              <div key={m.id} className="p-2.5 rounded-xl bg-bg-primary/30 border border-border text-xs">
                <p className="truncate leading-relaxed">{m.content}</p>
                {m.agent && <span className="text-text-muted mt-1 inline-block text-[10px] uppercase tracking-wider">{m.agent}</span>}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function CONFIG_DB_NAME(stats: ExtendedDbStats): string {
  return (stats as Record<string, unknown>).database as string || 'database';
}

function formatNumber(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}
