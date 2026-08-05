'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { fetchJSON, toArray, type GraphNode, type GraphStats } from '@/lib/api';
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
import { GitBranch, Search, Tag, FileText, RefreshCw, Sparkles, Loader2, Boxes, X } from 'lucide-react';

type Tab = 'nodes' | 'tags' | 'recent' | 'semantic';

export default function GraphPage() {
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [tags, setTags] = useState<{ tag: string; count: number }[]>([]);
  const [recent, setRecent] = useState<GraphNode[]>([]);
  const [query, setQuery] = useState('');
  const [semanticResults, setSemanticResults] = useState<{ node: GraphNode; score: number; neighbours?: GraphNode[] }[]>([]);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [previewNode, setPreviewNode] = useState<GraphNode | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [tab, setTab] = useState<Tab>('nodes');
  const [loading, setLoading] = useState(true);
  const { addToast } = useToast();

  async function openNodePreview(node: GraphNode) {
    setPreviewLoading(true);
    setPreviewNode(node);
    try {
      const data = await fetchJSON(`/v1/graph/nodes/${String(node.id)}`);
      setPreviewNode((data as { node?: GraphNode }).node || node);
    } catch {
      addToast('Failed to load node details', 'error');
      setPreviewNode(node);
    } finally {
      setPreviewLoading(false);
    }
  }

  const load = async () => {
    setLoading(true);
    try {
      const [s, n, tg, r] = await Promise.all([
        fetchJSON('/v1/graph/stats'),
        fetchJSON('/v1/graph/nodes?limit=100'),
        fetchJSON('/v1/graph/tags'),
        fetchJSON('/v1/graph/recent?limit=20'),
      ]);
      setStats(s as GraphStats);
      setNodes(toArray<GraphNode>(n));
      setTags(toArray<{ tag: string; count: number }>(tg));
      setRecent(toArray<GraphNode>(r));
    } catch {
      addToast('Failed to load graph data', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filteredNodes = useMemo(() => {
    if (!query.trim()) return nodes;
    const q = query.toLowerCase();
    return nodes.filter(n => n.title.toLowerCase().includes(q) || (n.node_type || '').toLowerCase().includes(q));
  }, [nodes, query]);

  async function runSemanticSearch() {
    if (!query.trim()) return;
    setSemanticLoading(true);
    try {
      const data = await fetchJSON(`/v1/graph/hybrid?q=${encodeURIComponent(query)}`);
      setSemanticResults(toArray(data));
    } catch {
      addToast('Semantic search failed', 'error');
    } finally {
      setSemanticLoading(false);
    }
  }

  const nodeCount = (stats as Record<string, unknown> | null)?.nodes as number | undefined;
  const edgeCount = (stats as Record<string, unknown> | null)?.edges as number | undefined;

  if (loading) {
    return (
      <div className="page-shell space-y-6">
        <Skeleton className="h-9 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: 'nodes', label: t('graph.nodes') || 'Nodes', icon: <FileText size={16} /> },
    { key: 'tags', label: t('graph.tags') || 'Tags', icon: <Tag size={16} /> },
    { key: 'recent', label: t('graph.recent') || 'Recent', icon: <RefreshCw size={16} /> },
    { key: 'semantic', label: t('graph.semantic') || 'Semantic', icon: <Sparkles size={16} /> },
  ];

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title={t('graph.title') || 'Knowledge Graph'}
        subtitle={t('graph.subtitle') || 'Explore concepts, documents, and connections'}
        icon={<Boxes size={20} />}
      >
        <Button onClick={load} variant="secondary" className="gap-2">
          <RefreshCw size={16} />
          {t('models.refresh')}
        </Button>
      </PageHeader>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard icon={<Boxes size={20} />} label="Nodes" value={String(nodeCount ?? nodes.length)} color="accent" />
        <StatCard icon={<GitBranch size={20} />} label="Edges" value={String(edgeCount ?? '—')} color="success" />
        <StatCard icon={<Tag size={20} />} label="Tags" value={String(tags.length)} color="warning" />
      </div>

      <div className="tabs">
        {tabs.map(tabItem => (
          <button
            key={tabItem.key}
            onClick={() => setTab(tabItem.key)}
            className={`tab ${tab === tabItem.key ? 'tab-active' : ''}`}
          >
            {tabItem.icon}
            {tabItem.label}
          </button>
        ))}
      </div>

      <div className="animate-fade-in">
        {tab === 'nodes' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
            <Card>
              <div className="flex items-center gap-2 mb-4">
                <Search size={16} className="text-text-muted shrink-0" />
                <Input
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder={t('graph.searchPlaceholder') || 'Search nodes by title or type...'}
                  className="flex-1"
                />
              </div>
              <div className="space-y-2">
                {filteredNodes.length === 0 && <EmptyState icon={<FileText size={22} />} title="No nodes found" description="Try a different search or load a workspace." />}
                {filteredNodes.map(n => (
                  <div key={n.id} className="flex items-center justify-between p-3 rounded-xl bg-bg-primary/40 border border-border hover:border-accent/50 hover:shadow-glow transition-all cursor-pointer" onClick={() => openNodePreview(n)}>
                    <div className="flex items-center gap-3 min-w-0">
                      <FileText size={14} className="text-text-muted shrink-0" />
                      <span className="text-sm font-medium truncate">{n.title}</span>
                      {n.node_type && <Badge variant="brand">{n.node_type}</Badge>}
                    </div>
                    <span className="text-xs text-text-muted font-mono shrink-0">{n.id}</span>
                  </div>
                ))}
              </div>
            </Card>

            {previewNode && (
              <Card className="lg:sticky lg:top-24">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-semibold flex items-center gap-2 min-w-0">
                    <FileText size={16} className="text-accent shrink-0" />
                    <span className="truncate">{previewNode.title}</span>
                    {previewNode.node_type && <Badge variant="brand">{previewNode.node_type}</Badge>}
                  </h3>
                  <button onClick={() => setPreviewNode(null)} className="text-text-muted hover:text-text-primary transition-colors p-1 rounded-md hover:bg-bg-tertiary" title="Close">
                    <X size={16} />
                  </button>
                </div>
                {previewLoading ? (
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-4 w-1/2" />
                  </div>
                ) : (
                  <p className="text-sm text-text-secondary whitespace-pre-wrap max-h-64 overflow-y-auto scrollbar-thin">{String(previewNode.content || 'No content')}</p>
                )}
                <div className="mt-3 text-[10px] text-text-muted font-mono border-t border-border pt-3">id: {previewNode.id}</div>
              </Card>
            )}
          </div>
        )}

        {tab === 'tags' && (
          <Card className="max-w-3xl">
            <div className="space-y-2">
              {tags.length === 0 && <EmptyState icon={<Tag size={22} />} title="No tags yet" description="Tags appear once files are uploaded to a workspace." />}
              {tags.map(ta => (
                <div key={ta.tag} className="flex items-center justify-between p-3 rounded-xl bg-bg-primary/40 border border-border">
                  <div className="flex items-center gap-2">
                    <Tag size={14} className="text-accent" />
                    <span className="text-sm font-medium">#{ta.tag}</span>
                  </div>
                  <Badge variant="default">{ta.count} {ta.count === 1 ? 'file' : 'files'}</Badge>
                </div>
              ))}
            </div>
          </Card>
        )}

        {tab === 'recent' && (
          <Card className="max-w-3xl">
            <div className="space-y-2">
              {recent.length === 0 && <EmptyState icon={<RefreshCw size={22} />} title="No recent nodes" description="Uploaded files will show up here." />}
              {recent.map(n => (
                <div key={n.id} className="flex items-center justify-between p-3 rounded-xl bg-bg-primary/40 border border-border hover:border-accent/50 hover:shadow-glow transition-all cursor-pointer" onClick={() => openNodePreview(n)}>
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-sm font-medium truncate">{n.title}</span>
                    {n.node_type && <Badge variant="brand">{n.node_type}</Badge>}
                  </div>
                  <span className="text-xs text-text-muted font-mono shrink-0">{n.id}</span>
                </div>
              ))}
            </div>
          </Card>
        )}

        {tab === 'semantic' && (
          <Card className="max-w-3xl">
            <div className="flex items-center gap-2 mb-4">
              <Search size={16} className="text-text-muted shrink-0" />
              <Input
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder={t('graph.semanticPlaceholder') || 'Semantic search over graph nodes...'}
                className="flex-1"
                onKeyDown={e => { if (e.key === 'Enter') runSemanticSearch(); }}
              />
              <Button onClick={runSemanticSearch} disabled={semanticLoading || !query.trim()} className="gap-2">
                {semanticLoading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                {semanticLoading ? t('common.searching') || 'Searching...' : t('common.search')}
              </Button>
            </div>
            <div className="space-y-2">
              {semanticResults.length === 0 && query && !semanticLoading && (
                <EmptyState icon={<Search size={22} />} title="No semantic matches" description="Try different wording for your query." />
              )}
              {semanticResults.map((r, i) => (
                <div key={i} className="p-3 rounded-xl bg-bg-primary/40 border border-border hover:border-accent/50 hover:shadow-glow transition-all cursor-pointer" onClick={() => openNodePreview(r.node)}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-sm font-medium truncate">{r.node.title}</span>
                      {r.node.node_type && <Badge variant="brand">{r.node.node_type}</Badge>}
                    </div>
                    <Badge variant="brand">{r.score.toFixed(2)}</Badge>
                  </div>
                  {r.neighbours && r.neighbours.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {r.neighbours.slice(0, 5).map(nb => (
                        <span key={String(nb.id)} className="text-[10px] px-2 py-0.5 rounded-full bg-bg-tertiary border border-border text-text-secondary">{nb.title}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
