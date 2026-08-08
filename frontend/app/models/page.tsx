'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { fetchJSON, toArray, toText, fetchInstalledModels, pullModel, type ModelItem, type InstalledModel } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Badge from '@/components/ui/Badge';
import Skeleton, { CardSkeleton } from '@/components/ui/Skeleton';
import PageHeader from '@/components/ui/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import { t } from '@/lib/i18n';
import { Cpu, Loader2, PowerOff, Play, SlidersHorizontal, RefreshCw, Boxes, Download, HardDrive } from 'lucide-react';

type ModelConfig = {
  name: string;
  role?: string;
  n_ctx?: number;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
};

export default function ModelsPage() {
  const [models, setModels] = useState<ModelItem[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [configs, setConfigs] = useState<Record<string, ModelConfig>>({});
  const [health, setHealth] = useState<ModelItem[]>([]);
  const [installed, setInstalled] = useState<InstalledModel[]>([]);
  const [pullUrl, setPullUrl] = useState('');
  const [pullFilename, setPullFilename] = useState('');
  const [pullProgress, setPullProgress] = useState<{ percent: number; downloaded_mb: number; total_mb: number } | null>(null);
  const [pullError, setPullError] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const { addToast } = useToast();

  const load = async () => {
    setLoading(true);
    try {
      const [m, s, c, h, inst] = await Promise.all([
        fetchJSON('/v1/models'),
        fetchJSON('/v1/models/stats'),
        fetchJSON('/v1/config'),
        fetchJSON('/v1/models/health'),
        fetchInstalledModels().then((r) => r).catch(() => []),
      ]);
      setModels(toArray<ModelItem>(m));
      setStats(s as Record<string, unknown>);
      const configModels = (c as { models?: ModelConfig[] }).models || [];
      const map: Record<string, ModelConfig> = {};
      for (const cfg of configModels) map[cfg.name] = cfg;
      setConfigs(map);
      setHealth((h as { models?: ModelItem[] }).models || []);
      setInstalled(inst);
    } catch {
      addToast('Failed to load models', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  async function toggleModel(id: string, loaded: boolean) {
    if (loaded && !window.confirm(`Unload model "${id}"?`)) return;
    setActionLoading(id);
    try {
      const endpoint = loaded ? '/v1/models/unload' : '/v1/models/load';
      await fetchJSON(`${endpoint}?name=${encodeURIComponent(id)}`, { method: 'POST' });
      addToast(`${loaded ? 'Unloaded' : 'Loaded'} ${id}`, 'success');
      load();
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setActionLoading(null);
    }
  }

  async function handlePull() {
    if (!pullUrl.trim()) {
      addToast('Enter a model URL', 'error');
      return;
    }
    setPullError(null);
    setPullProgress(null);
    try {
      const stream = await pullModel(pullUrl.trim(), pullFilename.trim() || undefined);
      const reader = stream.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith('data:')) continue;
          const payload = trimmed.slice(5).trim();
          if (payload === '[DONE]') continue;
          try {
            const evt = JSON.parse(payload);
            if (evt.type === 'progress') {
              setPullProgress({ percent: evt.percent, downloaded_mb: evt.downloaded_mb, total_mb: evt.total_mb });
            } else if (evt.type === 'complete') {
              addToast(`Pulled ${evt.filename} (${evt.size_mb} MB)`, 'success');
              setPullProgress(null);
              setPullUrl('');
              setPullFilename('');
              load();
            } else if (evt.type === 'error') {
              throw new Error(evt.content || 'Download failed');
            }
          } catch {
            // ignore parse errors for partial frames
          }
        }
      }
    } catch (e) {
      setPullError(toText(e));
      addToast(toText(e), 'error');
    }
  }

  const vramMap = useMemo(() => {
    const out: Record<string, number> = {};
    if (health && health.length > 0) {
      for (const h of health) {
        const mb = typeof h.vram_mb === 'number' ? h.vram_mb : 0;
        if (h.loaded && mb > 0) out[h.id] = mb;
      }
    }
    if (!stats) return out;
    const perModel = (stats as Record<string, unknown>).per_model as Record<string, { vram_mb?: number }> | undefined;
    if (perModel) {
      for (const [k, v] of Object.entries(perModel)) {
        if (v?.vram_mb) out[k] = v.vram_mb;
      }
    }
    return out;
  }, [stats, health]);

  const filteredModels = useMemo(() => {
    if (roleFilter === 'all') return models;
    return models.filter(m => (m.role || '').toLowerCase() === roleFilter.toLowerCase());
  }, [models, roleFilter]);

  const roles = useMemo(() => {
    const set = new Set<string>();
    for (const m of models) if (m.role) set.add(m.role);
    return Array.from(set);
  }, [models]);

  if (loading) {
    return (
      <div className="page-shell space-y-6">
        <Skeleton className="h-9 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
      </div>
    );
  }

  const loadedCount = models.filter(m => m.loaded).length;

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title={t('models.title')}
        subtitle={t('models.subtitle')}
        icon={<Boxes size={20} />}
      >
        <Button onClick={load} variant="secondary" className="gap-2">
          <RefreshCw size={16} />
          {t('models.refresh')}
        </Button>
      </PageHeader>

      <div className="flex items-center gap-2 flex-wrap">
        <SlidersHorizontal size={14} className="text-text-muted" />
        <button
          onClick={() => setRoleFilter('all')}
          className={`chip ${roleFilter === 'all' ? 'chip-active' : ''}`}
        >
          All
          <span className="opacity-70">({models.length})</span>
        </button>
        {roles.map(r => (
          <button
            key={r}
            onClick={() => setRoleFilter(r)}
            className={`chip capitalize ${roleFilter === r ? 'chip-active' : ''}`}
          >
            {r}
          </button>
        ))}
        <span className="ml-auto text-xs text-text-muted hidden sm:inline">
          {loadedCount} of {models.length} loaded
        </span>
      </div>

      <div className="flex flex-wrap gap-4">
        {filteredModels.length === 0 && (
          <div className="w-full">
            <EmptyState
              icon={<Cpu size={24} />}
              title={t('models.noModels')}
              description="Drop .gguf files into the models/ folder to auto-register them."
            />
          </div>
        )}
        {filteredModels.map(m => {
          const cfg = configs[m.id];
          return (
            <Card key={m.id} hover className="flex-1 min-w-[300px] max-w-full flex flex-col gap-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-9 h-9 rounded-xl bg-accent-soft flex items-center justify-center text-accent shrink-0">
                    <Cpu size={18} />
                  </div>
                  <span className="font-semibold text-sm truncate">{m.id}</span>
                </div>
                <Badge variant={m.loaded ? 'success' : 'default'}>
                  <span className={`w-1.5 h-1.5 rounded-full ${m.loaded ? 'bg-success' : 'bg-text-muted'}`} />
                  {m.loaded ? t('models.loaded') : t('models.unloaded')}
                </Badge>
              </div>
              <div className="flex items-center gap-2 -mt-1">
                {m.role && <Badge variant="brand" className="capitalize">{m.role}</Badge>}
                {vramMap[m.id] ? <Badge variant="warning">{`~${vramMap[m.id]} MB VRAM`}</Badge> : null}
              </div>
              {Array.isArray(m.capabilities) && m.capabilities.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {m.capabilities.map((cap: string) => (
                    <Badge key={cap} variant="default" className="text-[10px] capitalize">{cap}</Badge>
                  ))}
                </div>
              )}
              <div className="grid grid-cols-2 gap-2 text-xs text-text-secondary">
                {cfg?.n_ctx ? (
                  <div className="p-2.5 rounded-xl bg-bg-primary/40 border border-border">
                    <p className="text-text-muted text-[10px] uppercase tracking-wider mb-0.5">Context</p>
                    <p className="font-medium text-text-primary">{cfg.n_ctx.toLocaleString()} tokens</p>
                  </div>
                ) : null}
                {cfg?.temperature !== undefined ? (
                  <div className="p-2.5 rounded-xl bg-bg-primary/40 border border-border">
                    <p className="text-text-muted text-[10px] uppercase tracking-wider mb-0.5">Temperature</p>
                    <p className="font-medium text-text-primary">{cfg.temperature}</p>
                  </div>
                ) : null}
                {cfg?.max_tokens ? (
                  <div className="p-2.5 rounded-xl bg-bg-primary/40 border border-border">
                    <p className="text-text-muted text-[10px] uppercase tracking-wider mb-0.5">Max tokens</p>
                    <p className="font-medium text-text-primary">{cfg.max_tokens.toLocaleString()}</p>
                  </div>
                ) : null}
                {cfg?.top_p !== undefined ? (
                  <div className="p-2.5 rounded-xl bg-bg-primary/40 border border-border">
                    <p className="text-text-muted text-[10px] uppercase tracking-wider mb-0.5">Top P</p>
                    <p className="font-medium text-text-primary">{cfg.top_p}</p>
                  </div>
                ) : null}
              </div>
              <Button
                onClick={() => toggleModel(m.id, !!m.loaded)}
                disabled={actionLoading === m.id}
                variant={m.loaded ? 'danger' : 'primary'}
                className="w-full mt-auto"
              >
                {actionLoading === m.id ? <Loader2 size={16} className="animate-spin" /> : m.loaded ? <PowerOff size={16} /> : <Play size={16} />}
                {m.loaded ? t('models.unload') : t('models.load')}
              </Button>
            </Card>
          );
        })}
      </div>

      <Card>
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Download size={18} />
          Pull Model
        </h3>
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            value={pullUrl}
            onChange={(e) => setPullUrl(e.target.value)}
            placeholder="https://huggingface.co/.../resolve/main/model.gguf"
            className="flex-1 px-3 py-2 rounded-xl border border-border bg-bg-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent/50"
          />
          <input
            type="text"
            value={pullFilename}
            onChange={(e) => setPullFilename(e.target.value)}
            placeholder="filename.gguf (optional)"
            className="w-full sm:w-64 px-3 py-2 rounded-xl border border-border bg-bg-primary text-sm focus:outline-none focus:ring-2 focus:ring-accent/50"
          />
          <Button onClick={handlePull} disabled={pullProgress !== null} className="gap-2">
            {pullProgress ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
            {pullProgress ? 'Downloading...' : 'Pull'}
          </Button>
        </div>
        {pullProgress && (
          <div className="mt-3">
            <div className="h-2 rounded-full bg-bg-tertiary overflow-hidden">
              <div className="h-full bg-accent transition-all duration-300" style={{ width: `${pullProgress.percent}%` }} />
            </div>
            <p className="text-xs text-text-muted mt-1">
              {pullProgress.downloaded_mb} MB / {pullProgress.total_mb} MB ({pullProgress.percent}%)
            </p>
          </div>
        )}
        {pullError && <p className="text-xs text-danger mt-2">{pullError}</p>}
      </Card>

      <Card>
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <HardDrive size={18} />
          Installed Models
        </h3>
        {installed.length === 0 ? (
          <EmptyState
            icon={<HardDrive size={24} />}
            title="No models installed"
            description="Pull a model using the form above or drop .gguf files into the models/ folder."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-text-muted text-xs uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-4">Filename</th>
                  <th className="pb-2 pr-4">Size</th>
                  <th className="pb-2">Path</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {installed.map((m) => (
                  <tr key={m.filename}>
                    <td className="py-2 pr-4 font-medium">{m.filename}</td>
                    <td className="py-2 pr-4 text-text-secondary">{m.size_mb} MB</td>
                    <td className="py-2 text-text-muted font-mono text-xs truncate max-w-[200px]">{m.path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {stats && (
        <Card>
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            {t('models.performanceStats')}
            <span className="text-xs font-normal text-text-muted bg-bg-tertiary px-2 py-0.5 rounded-full">raw JSON</span>
          </h3>
          <pre className="text-xs text-text-secondary overflow-x-auto whitespace-pre-wrap bg-bg-primary/50 p-4 rounded-xl border border-border max-h-80 scrollbar-thin">
            {JSON.stringify(stats, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
