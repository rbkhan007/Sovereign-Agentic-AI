'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { fetchJSON, toArray, toText, type Metrics } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import { useChartTheme, chartTooltipStyle } from '@/lib/chartTheme';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Input from '@/components/ui/Input';
import Textarea from '@/components/ui/Textarea';
import Badge from '@/components/ui/Badge';
import Skeleton, { CardSkeleton } from '@/components/ui/Skeleton';
import StatCard from '@/components/ui/StatCard';
import Field from '@/components/ui/Field';
import PageHeader from '@/components/ui/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import { t } from '@/lib/i18n';
import { Activity, FileText, GitBranch, Cpu, Loader2, ShieldCheck } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

type AdminTab = 'metrics' | 'logs' | 'threads' | 'loras' | 'skills' | 'agents' | 'mcp' | 'harness';

export default function AdminPage() {
  const [tab, setTab] = useState<AdminTab>('metrics');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [threads, setThreads] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const { addToast } = useToast();
  const chartTheme = useChartTheme();

  const loadCommon = async () => {
    setLoading(true);
    try {
      const [m, l, threadsData] = await Promise.all([
        fetchJSON('/v1/admin/metrics'),
        fetchJSON('/v1/admin/logs?lines=200'),
        fetchJSON('/v1/admin/threads'),
      ]);
      setMetrics(m as Metrics);
      setLogs(Array.isArray(l) ? l : ((l as { lines?: unknown[] } | null)?.lines as string[]) ?? []);
      setThreads((threadsData && typeof threadsData === 'object' && 'threads' in threadsData)
        ? (threadsData as { threads: unknown }).threads as Record<string, unknown>
        : threadsData as Record<string, unknown>);
    } catch {
      addToast('Failed to load admin data', 'error');
    } finally {
      setLoading(false);
    }
  };

  const perModelChartData = useMemo(() => {
    if (!metrics || typeof metrics !== 'object') return [];
    const m = metrics as Record<string, unknown>;
    const pm = m.per_model as Record<string, Record<string, unknown>> | undefined;
    if (!pm) return [];
    return Object.entries(pm).map(([name, d]) => ({
      name,
      requests: (d.requests as number) || 0,
      errors: (d.errors as number) || 0,
      avg_latency: ((d.avg_latency as number) || 0).toFixed(2),
    }));
  }, [metrics]);

  useEffect(() => { loadCommon(); }, []);

  const tabs: { key: AdminTab; label: string; icon: React.ReactNode }[] = [
    { key: 'metrics', label: t('admin.metrics'), icon: <Activity size={16} /> },
    { key: 'logs', label: t('admin.logs'), icon: <FileText size={16} /> },
    { key: 'threads', label: t('admin.threads'), icon: <Cpu size={16} /> },
    { key: 'loras', label: t('admin.loras'), icon: <Activity size={16} /> },
    { key: 'skills', label: t('admin.skills'), icon: <FileText size={16} /> },
    { key: 'agents', label: t('admin.agents'), icon: <Cpu size={16} /> },
    { key: 'mcp', label: t('admin.mcpTools'), icon: <GitBranch size={16} /> },
    { key: 'harness', label: 'Harness', icon: <Activity size={16} /> },
  ];

  const m = metrics as Record<string, unknown> | null;

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title={t('admin.title')}
        subtitle={t('admin.subtitle')}
        icon={<ShieldCheck size={20} />}
      >
        <Button onClick={loadCommon} variant="secondary" className="gap-2">
          <Activity size={16} />
          {t('models.refresh')}
        </Button>
      </PageHeader>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <CardSkeleton />
        </div>
      ) : (
        <>
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
            {tab === 'metrics' && (
              <div className="space-y-6">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <StatCard icon={<Activity size={20} />} label={t('admin.uptime')} value={typeof metrics?.uptime_s === 'number' ? `${Math.round(metrics.uptime_s / 60)} min` : '—'} color="accent" />
                  <StatCard icon={<Activity size={20} />} label={t('admin.requests')} value={(m?.requests)?.toString() || '0'} color="success" />
                  <StatCard icon={<Activity size={20} />} label={t('admin.errors')} value={(m?.errors)?.toString() || '0'} color="danger" />
                  <StatCard icon={<Activity size={20} />} label={t('admin.tokensPerSec')} value={(m?.tokens_per_sec)?.toString() || '0'} color="warning" />
                </div>
                <Card>
                  <h3 className="font-semibold mb-4">Requests by Model</h3>
                  {perModelChartData.length > 0 ? (
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={perModelChartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} />
                          <XAxis dataKey="name" stroke={chartTheme.axis} fontSize={12} tickLine={false} axisLine={false} />
                          <YAxis stroke={chartTheme.axis} fontSize={12} tickLine={false} axisLine={false} width={50} />
                          <Tooltip contentStyle={chartTooltipStyle(chartTheme)} />
                          <Legend />
                          <Bar dataKey="requests" fill={chartTheme.colors[0]} radius={[4, 4, 0, 0]} name="Requests" />
                          <Bar dataKey="errors" fill={chartTheme.colors[3]} radius={[4, 4, 0, 0]} name="Errors" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <EmptyState icon={<Activity size={22} />} title="No model metrics yet" description="Request volume appears here once models have served traffic." />
                  )}
                </Card>
                <Card>
                  <h3 className="font-semibold mb-3">Raw Metrics</h3>
                  <pre className="text-xs bg-bg-primary/50 p-4 rounded-xl overflow-x-auto whitespace-pre-wrap border border-border max-h-64 scrollbar-thin">
                    {JSON.stringify(metrics, null, 2)}
                  </pre>
                </Card>
              </div>
            )}
            {tab === 'logs' && (
              <Card>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold">{t('admin.systemLogs')}</h3>
                  <span className="text-xs text-text-muted">{logs.length} lines</span>
                </div>
                <div className="bg-bg-primary/80 p-4 rounded-xl max-h-[600px] overflow-y-auto scrollbar-thin font-mono text-xs">
                  {logs.length === 0 ? (
                    <EmptyState icon={<FileText size={22} />} title="No logs available" description="Server log lines will stream in here." />
                  ) : (
                    <div className="space-y-0.5">
                      {logs.map((line, i) => {
                        const isError = line.toLowerCase().includes('error') || line.toLowerCase().includes('failed');
                        const isWarn = line.toLowerCase().includes('warn');
                        return (
                          <div key={i} className={`py-0.5 ${isError ? 'text-danger' : isWarn ? 'text-warning' : 'text-text-secondary'}`}>
                            {line}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </Card>
            )}
            {tab === 'threads' && (
              <Card>
                <h3 className="font-semibold mb-4">{t('admin.threads')}</h3>
                <div className="bg-bg-primary/50 p-4 rounded-xl overflow-x-auto border border-border">
                  {Array.isArray(threads) ? (
                    <div className="space-y-2">
                      {threads.map((th, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
                          <span className="text-sm font-medium">{String((th as { name?: unknown })?.name ?? `thread-${i}`)}</span>
                          <span className="text-xs text-text-secondary font-mono">
                            {typeof th === 'object' ? JSON.stringify(th) : String(th)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : threads && typeof threads === 'object' ? (
                    <div className="space-y-2">
                      {Object.entries(threads).map(([key, val]) => (
                        <div key={key} className="flex items-center justify-between py-1.5 border-b border-border/50 last:border-0">
                          <span className="text-sm font-medium">{key}</span>
                          <span className="text-xs text-text-secondary font-mono">
                            {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(threads, null, 2)}</pre>
                  )}
                </div>
              </Card>
            )}
            {tab === 'loras' && <LoraTab onRefresh={loadCommon} />}
            {tab === 'skills' && <SkillsAdminTab />}
            {tab === 'agents' && <AgentsAdminTab />}
            {tab === 'mcp' && <McpTab />}
            {tab === 'harness' && <HarnessTab />}
          </div>
        </>
      )}
    </div>
  );
}

function StepDots({ step, total }: { step: number; total: number }) {
  return (
    <div className="flex items-center gap-2 mb-6">
      {Array.from({ length: total }).map((_, i) => (
        <React.Fragment key={i}>
          <div
            className={`flex items-center justify-center w-8 h-8 rounded-full text-xs font-medium ${
              step > i + 1 ? 'bg-success text-white' : step === i + 1 ? 'bg-accent text-white shadow-glow' : 'bg-bg-tertiary text-text-muted'
            }`}
          >
            {i + 1}
          </div>
          {i < total - 1 && <div className={`flex-1 h-0.5 rounded-full ${step > i + 1 ? 'bg-success' : 'bg-bg-tertiary'}`} />}
        </React.Fragment>
      ))}
    </div>
  );
}

function LoraTab({ onRefresh }: { onRefresh: () => void }) {
  const [step, setStep] = useState(1);
  const [datasets, setDatasets] = useState<{ name: string; lines?: number; size?: number }[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [selectedDataset, setSelectedDataset] = useState('');
  const [baseModel, setBaseModel] = useState('');
  const [epochs, setEpochs] = useState(3);
  const [outputName, setOutputName] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  useEffect(() => {
    setDatasetsLoading(true);
    fetchJSON('/v1/loras/datasets').then(d => setDatasets(toArray(d))).finally(() => setDatasetsLoading(false));
  }, []);

  const totalSteps = 3;

  async function submit() {
    if (!selectedDataset || !baseModel.trim()) { addToast(t('common.required'), 'error'); return; }
    setLoading(true);
    try {
      await fetchJSON('/v1/loras/train', { method: 'POST', body: JSON.stringify({ base_model: baseModel.trim(), dataset: selectedDataset, output_name: outputName.trim() || selectedDataset, epochs }) });
      addToast(t('admin.loraTrainingStarted'), 'success');
      setStep(1);
      setSelectedDataset('');
      setBaseModel('');
      setEpochs(3);
      setOutputName('');
      onRefresh();
    } catch (e) { addToast(toText(e), 'error'); } finally { setLoading(false); }
  }

  return (
    <Card className="max-w-3xl">
      <h3 className="font-semibold mb-4">{t('admin.loraAdapters')}</h3>

      <StepDots step={step} total={totalSteps} />

      {step === 1 && (
        <div className="space-y-4 animate-fade-in">
          <h4 className="text-sm font-medium">{t('common.step')} 1: {t('admin.name')}</h4>
          <div className="space-y-2 max-h-64 overflow-y-auto scrollbar-thin">
            {datasetsLoading ? (
              Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)
            ) : datasets.length === 0 ? (
              <EmptyState icon={<Activity size={22} />} title="No datasets uploaded" description="Use /v1/loras/upload_dataset first." />
            ) : (
              datasets.map(d => (
                <button
                  key={d.name}
                  onClick={() => setSelectedDataset(d.name)}
                  className={`w-full text-left p-3 rounded-xl border transition-all ${selectedDataset === d.name ? 'border-accent bg-accent-soft' : 'border-border hover:bg-bg-tertiary'}`}
                >
                  <p className="text-sm font-medium">{d.name}</p>
                  <p className="text-xs text-text-muted">{d.lines ?? '?'} lines · {d.size ? `${(d.size / 1024).toFixed(1)} KB` : '—'}</p>
                </button>
              ))
            )}
          </div>
          <div className="flex justify-end">
            <Button onClick={() => setStep(2)} disabled={!selectedDataset}>{t('common.next')}</Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4 animate-fade-in">
          <h4 className="text-sm font-medium">{t('common.step')} 2: Configure</h4>
          <div className="space-y-3">
            <Field label="Base Model">
              <Input value={baseModel} onChange={e => setBaseModel(e.target.value)} placeholder="e.g. meta-llama/Llama-2-7b-hf" />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Epochs">
                <Input type="number" min={1} max={10} value={String(epochs)} onChange={e => setEpochs(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))} />
              </Field>
              <Field label="Output Name (optional)">
                <Input value={outputName} onChange={e => setOutputName(e.target.value)} placeholder="my-lora-adapter" />
              </Field>
            </div>
          </div>
          <p className="text-xs text-text-secondary">Training requires peft/datasets/transformers installed.</p>
          <div className="flex justify-between">
            <Button variant="secondary" onClick={() => setStep(1)}>{t('common.back')}</Button>
            <Button onClick={() => setStep(3)} disabled={!baseModel.trim()}>{t('common.next')}</Button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4 animate-fade-in">
          <h4 className="text-sm font-medium">{t('common.step')} 3: Review</h4>
          <div className="p-4 rounded-xl bg-bg-primary/50 border border-border space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-text-secondary">Dataset</span><span className="font-medium">{selectedDataset}</span></div>
            <div className="flex justify-between"><span className="text-text-secondary">Base Model</span><span className="font-medium">{baseModel}</span></div>
            <div className="flex justify-between"><span className="text-text-secondary">Epochs</span><span className="font-medium">{epochs}</span></div>
            <div className="flex justify-between"><span className="text-text-secondary">Output</span><span className="font-medium">{outputName || selectedDataset}</span></div>
          </div>
          <div className="flex justify-between">
            <Button variant="secondary" onClick={() => setStep(2)}>{t('common.back')}</Button>
            <Button onClick={submit} disabled={loading} className="gap-2">{loading ? <Loader2 size={16} className="animate-spin" /> : null} {t('common.finish')}</Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function SkillsAdminTab() {
  const [skills, setSkills] = useState<{ name: string; description?: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newTemplate, setNewTemplate] = useState('');
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const { addToast } = useToast();

  useEffect(() => {
    setLoading(true);
    fetchJSON('/v1/skills').then(d => setSkills(toArray(d))).finally(() => setLoading(false));
  }, []);

  async function addSkill() {
    if (!newName.trim()) return;
    try {
      await fetchJSON('/v1/skills', { method: 'POST', body: JSON.stringify({ name: newName.trim(), description: newDesc.trim(), template: newTemplate.trim() || '{input}' }) });
      addToast(t('admin.skillAdded'), 'success');
      setNewName(''); setNewDesc(''); setNewTemplate('');
      fetchJSON('/v1/skills').then(d => setSkills(toArray(d)));
    } catch (e) { addToast(toText(e), 'error'); }
  }

  async function deleteSkill(name: string) {
    if (pendingDelete !== name) {
      setPendingDelete(name);
      return;
    }
    setPendingDelete(null);
    try {
      await fetchJSON(`/v1/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
      addToast(t('admin.skillDeleted'), 'success');
      fetchJSON('/v1/skills').then(d => setSkills(toArray(d)));
    } catch (e) { addToast(toText(e), 'error'); }
  }

  return (
    <Card className="max-w-3xl">
      <h3 className="font-semibold mb-4">{t('admin.skills')}</h3>
      <div className="space-y-3 mb-6">
        <Input value={newName} onChange={e => setNewName(e.target.value)} placeholder={t('admin.name')} />
        <Input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder={t('admin.description')} />
        <Textarea value={newTemplate} onChange={e => setNewTemplate(e.target.value)} placeholder={t('admin.template')} rows={3} />
        <Button onClick={addSkill}>{t('admin.addSkill')}</Button>
      </div>
      <div className="space-y-2">
        {loading ? (
          Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)
        ) : (
          skills.map(s => (
            <div key={s.name} className="flex items-center justify-between p-3 rounded-xl bg-bg-primary/40 border border-border">
              <div className="min-w-0">
                <p className="text-sm font-medium">{s.name}</p>
                {s.description && <p className="text-xs text-text-secondary truncate">{s.description}</p>}
              </div>
              {pendingDelete === s.name ? (
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-xs text-text-secondary">Confirm?</span>
                  <Button variant="danger" size="sm" onClick={() => deleteSkill(s.name)} className="!py-1 !px-2 text-xs">Yes</Button>
                  <Button variant="secondary" size="sm" onClick={() => setPendingDelete(null)} className="!py-1 !px-2 text-xs">No</Button>
                </div>
              ) : (
                <Button variant="danger" size="sm" onClick={() => deleteSkill(s.name)} className="!py-1 !px-2 text-xs shrink-0">{t('admin.delete')}</Button>
              )}
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

function AgentsAdminTab() {
  const [agents, setAgents] = useState<{ name: string; role?: string; description?: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState('');
  const [newRole, setNewRole] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const { addToast } = useToast();

  useEffect(() => {
    setLoading(true);
    fetchJSON('/v1/agents').then(d => setAgents(toArray(d))).finally(() => setLoading(false));
  }, []);

  async function addAgent() {
    if (!newName.trim()) return;
    try {
      await fetchJSON('/v1/agents', { method: 'POST', body: JSON.stringify({ name: newName.trim(), role: newRole.trim() || undefined, description: newDesc.trim() || undefined }) });
      addToast(t('admin.agentAdded'), 'success');
      setNewName(''); setNewRole(''); setNewDesc('');
      fetchJSON('/v1/agents').then(d => setAgents(toArray(d)));
    } catch (e) { addToast(toText(e), 'error'); }
  }

  async function deleteAgent(name: string) {
    if (pendingDelete !== name) {
      setPendingDelete(name);
      return;
    }
    setPendingDelete(null);
    try {
      await fetchJSON(`/v1/agents/${encodeURIComponent(name)}`, { method: 'DELETE' });
      addToast(t('admin.agentDeleted'), 'success');
      fetchJSON('/v1/agents').then(d => setAgents(toArray(d)));
    } catch (e) { addToast(toText(e), 'error'); }
  }

  return (
    <Card className="max-w-3xl">
      <h3 className="font-semibold mb-4">{t('admin.agents')}</h3>
      <div className="space-y-3 mb-6">
        <Input value={newName} onChange={e => setNewName(e.target.value)} placeholder={t('admin.name')} />
        <Input value={newRole} onChange={e => setNewRole(e.target.value)} placeholder={t('admin.role')} />
        <Input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder={t('admin.description')} />
        <Button onClick={addAgent}>{t('admin.addAgent')}</Button>
      </div>
      <div className="space-y-2">
        {loading ? (
          Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)
        ) : (
          agents.map(a => (
            <div key={a.name} className="flex items-center justify-between p-3 rounded-xl bg-bg-primary/40 border border-border">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium">{a.name}</p>
                  {a.role && <Badge variant="brand">{a.role}</Badge>}
                </div>
                {a.description && <p className="text-xs text-text-secondary truncate">{a.description}</p>}
              </div>
              {pendingDelete === a.name ? (
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-xs text-text-secondary">Confirm?</span>
                  <Button variant="danger" size="sm" onClick={() => deleteAgent(a.name)} className="!py-1 !px-2 text-xs">Yes</Button>
                  <Button variant="secondary" size="sm" onClick={() => setPendingDelete(null)} className="!py-1 !px-2 text-xs">No</Button>
                </div>
              ) : (
                <Button variant="danger" size="sm" onClick={() => deleteAgent(a.name)} className="!py-1 !px-2 text-xs shrink-0">{t('admin.delete')}</Button>
              )}
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

function McpTab() {
  const [tools, setTools] = useState<{ name: string; description: string; inputSchema?: Record<string, unknown> }[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTool, setSelectedTool] = useState('');
  const [toolInput, setToolInput] = useState('');
  const [toolResult, setToolResult] = useState('');
  const [calling, setCalling] = useState(false);
  const { addToast } = useToast();

  useEffect(() => {
    setLoading(true);
    fetchJSON('/mcp').then((d: unknown) => {
      const data = d as { tools?: { name: string; description: string; inputSchema?: Record<string, unknown> }[] };
      setTools(data.tools || []);
    }).catch(() => addToast('Failed to load MCP tools', 'error')).finally(() => setLoading(false));
  }, [addToast]);

  async function callTool() {
    if (!selectedTool || !toolInput.trim()) return;
    setCalling(true);
    setToolResult('');
    try {
      const data = await fetchJSON('/mcp', {
        method: 'POST',
        body: JSON.stringify({
          jsonrpc: '2.0',
          method: 'tools/call',
          params: { name: selectedTool, arguments: { input: toolInput.trim() } },
          id: 1,
        }),
      });
      const result = (data as { result?: { content?: { type: string; text: string }[] } }).result;
      const text = result?.content?.map((c: { type: string; text: string }) => c.text).join('\n') || 'No result';
      setToolResult(text);
      addToast('Tool called successfully', 'success');
    } catch (e) {
      setToolResult(`Error: ${toText(e)}`);
      addToast('Tool call failed', 'error');
    } finally {
      setCalling(false);
    }
  }

  return (
    <Card className="max-w-3xl">
      <h3 className="font-semibold mb-4">{t('admin.mcpTools')}</h3>
      <div className="space-y-2 mb-4">
        {loading ? (
          Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)
        ) : tools.length === 0 ? (
          <EmptyState icon={<GitBranch size={22} />} title="No MCP tools available" description="Agent personas and skills appear here automatically." />
        ) : (
          tools.map(tool => (
            <button
              key={tool.name}
              onClick={() => { setSelectedTool(tool.name); setToolResult(''); }}
              className={`w-full text-left p-3 rounded-xl border transition-all ${selectedTool === tool.name ? 'border-accent bg-accent-soft' : 'border-border hover:bg-bg-tertiary'}`}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{tool.name}</span>
                {tool.name === 'chat' && <Badge variant="brand">built-in</Badge>}
              </div>
              <p className="text-xs text-text-secondary mt-1">{tool.description}</p>
            </button>
          ))
        )}
      </div>

      {selectedTool && (
        <div className="space-y-3 p-4 rounded-xl bg-bg-secondary/30 border border-border animate-fade-in">
          <p className="text-sm font-medium">Call: {selectedTool}</p>
          <Textarea
            label="Input"
            value={toolInput}
            onChange={e => setToolInput(e.target.value)}
            placeholder="Enter input text for this tool..."
            rows={3}
          />
          <Button onClick={callTool} disabled={calling || !toolInput.trim()} className="gap-2">
            {calling ? <Loader2 size={16} className="animate-spin" /> : <GitBranch size={16} />}
            {calling ? 'Calling...' : 'Call Tool'}
          </Button>
        </div>
      )}

      {toolResult && (
        <div className="mt-4 p-4 bg-bg-primary/50 border border-border rounded-xl animate-fade-in">
          <p className="text-xs text-text-muted uppercase tracking-wider mb-2">Result</p>
          <pre className="text-sm whitespace-pre-wrap overflow-x-auto">{toolResult}</pre>
        </div>
      )}
    </Card>
  );
}

function HarnessTab() {
  const [stats, setStats] = useState<{ generation: number; epsilon: number; data: Record<string, { attempts: number; errors: number; avg_latency: number; tokens: number; score: number; recent: number }> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [adjustTask, setAdjustTask] = useState('');
  const [adjustModel, setAdjustModel] = useState('');
  const [adjustScore, setAdjustScore] = useState('50');
  const [confirmReset, setConfirmReset] = useState(false);
  const { addToast } = useToast();

  useEffect(() => {
    setLoading(true);
    fetchJSON('/v1/router/stats').then(data => {
      setStats(data as typeof stats);
    }).catch(() => addToast('Failed to load harness stats', 'error')).finally(() => setLoading(false));
  }, []);

  async function resetHarness() {
    if (!confirmReset) {
      setConfirmReset(true);
      return;
    }
    setConfirmReset(false);
    try {
      await fetchJSON('/v1/router/harness/reset', { method: 'POST' });
      addToast('Harness reset', 'success');
      const data = await fetchJSON('/v1/router/stats');
      setStats(data as typeof stats);
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  async function adjustScoreAction() {
    if (!adjustTask.trim() || !adjustModel.trim()) return;
    try {
      await fetchJSON('/v1/router/harness/adjust', {
        method: 'POST',
        body: JSON.stringify({ task: adjustTask.trim(), model: adjustModel.trim(), score: parseFloat(adjustScore) || 50 }),
      });
      addToast('Score adjusted', 'success');
      setAdjustTask('');
      setAdjustModel('');
      const data = await fetchJSON('/v1/router/stats');
      setStats(data as typeof stats);
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  const entries = stats ? Object.entries(stats.data).sort((a, b) => b[1].score - a[1].score) : [];

  return (
    <div className="space-y-6">
      <Card className="max-w-4xl">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h3 className="font-semibold">Adaptive Harness</h3>
          <div className="flex items-center gap-3 text-sm text-text-secondary">
            <span>Generation: <span className="font-mono">{stats?.generation ?? 0}</span></span>
            <span>Epsilon: <span className="font-mono">{stats?.epsilon ?? 0}</span></span>
            {confirmReset ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-secondary">Confirm reset?</span>
                <Button variant="danger" size="sm" onClick={resetHarness} className="!py-1 !px-2 text-xs">Yes</Button>
                <Button variant="secondary" size="sm" onClick={() => setConfirmReset(false)} className="!py-1 !px-2 text-xs">No</Button>
              </div>
            ) : (
              <Button variant="danger" size="sm" onClick={resetHarness} className="!py-1 !px-2 text-xs">Reset</Button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="table-wrap">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th>Task / Model</th>
                  <th className="!text-right">Score</th>
                  <th className="!text-right">Attempts</th>
                  <th className="!text-right">Errors</th>
                  <th className="!text-right">Avg Latency</th>
                  <th className="!text-right">Tokens</th>
                  <th className="!text-right">Recent</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i}>
                    <td><Skeleton className="h-4 w-32" /></td>
                    <td><Skeleton className="h-4 w-12 ml-auto" /></td>
                    <td><Skeleton className="h-4 w-8 ml-auto" /></td>
                    <td><Skeleton className="h-4 w-8 ml-auto" /></td>
                    <td><Skeleton className="h-4 w-12 ml-auto" /></td>
                    <td><Skeleton className="h-4 w-8 ml-auto" /></td>
                    <td><Skeleton className="h-4 w-12 ml-auto" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : entries.length > 0 ? (
          <div className="table-wrap">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th>Task / Model</th>
                  <th className="!text-right">Score</th>
                  <th className="!text-right">Attempts</th>
                  <th className="!text-right">Errors</th>
                  <th className="!text-right">Avg Latency</th>
                  <th className="!text-right">Tokens</th>
                  <th className="!text-right">Recent</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([key, d]) => (
                  <tr key={key}>
                    <td className="font-medium">{key}</td>
                    <td className="!text-right">
                      <span className={`font-mono ${d.score >= 70 ? 'text-success' : d.score >= 40 ? 'text-warning' : 'text-danger'}`}>
                        {d.score.toFixed(1)}
                      </span>
                    </td>
                    <td className="!text-right font-mono">{d.attempts}</td>
                    <td className="!text-right font-mono">{d.errors}</td>
                    <td className="!text-right font-mono">{d.avg_latency.toFixed(2)}s</td>
                    <td className="!text-right font-mono">{d.tokens}</td>
                    <td className="!text-right font-mono">{d.recent.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={<Activity size={22} />} title="No harness data yet" description="Generate some responses to populate scores." />
        )}
      </Card>

      <Card className="max-w-3xl">
        <h3 className="font-semibold mb-3">Manual Score Adjustment</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
          <Input label="Task" value={adjustTask} onChange={e => setAdjustTask(e.target.value)} placeholder="e.g. code" />
          <Input label="Model" value={adjustModel} onChange={e => setAdjustModel(e.target.value)} placeholder="e.g. hy-mt2" />
          <Input label="Score (0-100)" type="number" min="0" max="100" value={adjustScore} onChange={e => setAdjustScore(e.target.value)} />
        </div>
        <Button onClick={adjustScoreAction} disabled={!adjustTask.trim() || !adjustModel.trim()}>Set Score</Button>
      </Card>
    </div>
  );
}
