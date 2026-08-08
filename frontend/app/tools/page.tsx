'use client';

import React, { useEffect, useState } from 'react';
import { fetchJSON, toArray, toText, type Agent, type Skill } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Textarea from '@/components/ui/Textarea';
import Input from '@/components/ui/Input';
import Badge from '@/components/ui/Badge';
import Skeleton, { CardSkeleton } from '@/components/ui/Skeleton';
import PageHeader from '@/components/ui/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import Select from '@/components/ui/Select';
import { t } from '@/lib/i18n';
import { FileText, MessageSquare, Image as ImageIcon, Bot, Wrench, Copy, Check, Wand2, Eye, Upload, Database, Cpu, Loader2 } from 'lucide-react';

type ToolTab = 'summarize' | 'analyze' | 'translate' | 'image' | 'vision' | 'datascience' | 'agents' | 'skills';

export default function ToolsPage() {
  const [tab, setTab] = useState<ToolTab>('summarize');
  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const { addToast } = useToast();

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const [a, s] = await Promise.all([fetchJSON('/v1/agents'), fetchJSON('/v1/skills')]);
        if (!mounted) return;
        setAgents(toArray<Agent>(a));
        setSkills(toArray<Skill>(s));
      } catch {
        addToast('Failed to load tools data', 'error');
      } finally {
        setLoading(false);
      }
    }
    load();
    return () => { mounted = false; };
  }, [addToast]);

  const tabs: { key: ToolTab; label: string; icon: React.ReactNode }[] = [
    { key: 'summarize', label: t('tools.summarize'), icon: <FileText size={16} /> },
    { key: 'analyze', label: t('tools.analyze'), icon: <FileText size={16} /> },
    { key: 'translate', label: t('tools.translate'), icon: <MessageSquare size={16} /> },
    { key: 'image', label: t('tools.image'), icon: <ImageIcon size={16} /> },
    { key: 'vision', label: t('tools.vision'), icon: <Eye size={16} /> },
    { key: 'datascience', label: 'Data Science', icon: <Database size={16} /> },
    { key: 'agents', label: t('tools.agents'), icon: <Bot size={16} /> },
    { key: 'skills', label: t('tools.skills'), icon: <Wrench size={16} /> },
  ];

  return (
    <div className="page-shell">
      <PageHeader
        title={t('tools.title')}
        subtitle={t('tools.subtitle')}
        icon={<Wand2 size={20} />}
      />

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
            {tab === 'summarize' && <TextToolTab endpoint="/v1/tools/summarize" title={t('tools.summarize')} description={t('tools.summarize') + ' text'} />}
            {tab === 'analyze' && <TextToolTab endpoint="/v1/tools/analyze" title={t('tools.analyze')} description={t('tools.analyze') + ' text content'} />}
            {tab === 'translate' && <TextToolTab endpoint="/v1/tools/translate" title={t('tools.translate')} description={t('tools.translate') + ' text'} />}
            {tab === 'image' && <ImageTab />}
            {tab === 'vision' && <VisionTab />}
            {tab === 'datascience' && <DataScienceTab />}
            {tab === 'agents' && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {agents.map(a => <AgentCard key={a.name} agent={a} />)}
                {agents.length === 0 && <EmptyState icon={<Bot size={24} />} title={t('tools.noAgents')} description={t('tools.agentsDescription')} className="col-span-full" />}
              </div>
            )}
            {tab === 'skills' && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {skills.map(s => <SkillCard key={s.name} skill={s} />)}
                {skills.length === 0 && <EmptyState icon={<Wrench size={24} />} title={t('tools.noSkills')} description={t('tools.skillsDescription')} className="col-span-full" />}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="flex items-center gap-1 text-xs text-text-secondary hover:text-accent transition-colors"
      title="Copy to clipboard"
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function TextToolTab({ endpoint, title, description }: { endpoint: string; title: string; description: string }) {
  const [text, setText] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  async function run() {
    if (!text.trim()) return;
    setLoading(true);
    try {
      const data = await fetchJSON(endpoint, { method: 'POST', body: JSON.stringify({ text }) });
      const res = (data as { summary?: string; analysis?: string; translation?: string; result?: string }).summary
        || (data as { summary?: string; analysis?: string; translation?: string; result?: string }).analysis
        || (data as { summary?: string; analysis?: string; translation?: string; result?: string }).translation
        || (data as { summary?: string; analysis?: string; translation?: string; result?: string }).result
        || toText(data);
      setResult(res);
      addToast(`${title} complete`, 'success');
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <div className="mb-4">
          <h3 className="font-semibold">{title}</h3>
          <p className="text-xs text-text-secondary">{description}</p>
        </div>
        <Textarea label={t('tools.inputText')} value={text} onChange={e => setText(e.target.value)} rows={12} />
        <Button onClick={run} disabled={loading} className="mt-4 gap-2">{loading ? t('common.loading') : `${t('common.run')} ${title}`}</Button>
      </Card>
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold">{t('tools.result')}</h3>
            <p className="text-xs text-text-secondary">Output appears here</p>
          </div>
          {result && <CopyButton text={result} />}
        </div>
        <div className={`bg-bg-primary/50 border border-border rounded-xl p-4 min-h-[300px] ${result ? '' : 'flex items-center justify-center'}`}>
          {result ? (
            <p className="text-sm whitespace-pre-wrap leading-relaxed">{result}</p>
          ) : (
            <p className="text-xs text-text-muted">Run the tool to see results here</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function ImageTab() {
  const [prompt, setPrompt] = useState('');
  const [width, setWidth] = useState(512);
  const [height, setHeight] = useState(512);
  const [steps, setSteps] = useState(20);
  const [imageUrl, setImageUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  async function generate() {
    if (!prompt.trim()) return;
    setLoading(true);
    try {
      const data = await fetchJSON('/v1/images/generate', { method: 'POST', body: JSON.stringify({ prompt, width, height, steps }) });
      const url = (data as { url?: string }).url || (data as { filename?: string }).filename;
      if (url) setImageUrl(url);
      addToast(t('tools.result'), 'success');
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <h3 className="font-semibold mb-4">{t('tools.image')}</h3>
        <div className="space-y-3">
          <Input label={t('tools.prompt')} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="A futuristic city at sunset..." />
          <div className="grid grid-cols-3 gap-3">
            <Input label={t('tools.width')} type="number" value={String(width)} onChange={e => setWidth(parseInt(e.target.value) || 512)} />
            <Input label={t('tools.height')} type="number" value={String(height)} onChange={e => setHeight(parseInt(e.target.value) || 512)} />
            <Input label={t('tools.steps')} type="number" value={String(steps)} onChange={e => setSteps(parseInt(e.target.value) || 20)} />
          </div>
          <Button onClick={generate} disabled={loading} className="gap-2">{loading ? t('tools.generating') : t('tools.generate')}</Button>
        </div>
      </Card>
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold">{t('tools.result')}</h3>
            <p className="text-xs text-text-secondary">Generated image preview</p>
          </div>
        </div>
        <div className={`bg-bg-primary/50 border border-border rounded-xl p-4 min-h-[300px] flex items-center justify-center ${imageUrl ? '' : ''}`}>
          {imageUrl ? (
            <img src={imageUrl} alt="Generated" className="rounded-xl border border-border max-h-[400px] w-full object-cover" /* eslint-disable-line @next/next/no-img-element */ />
          ) : (
            <p className="text-xs text-text-muted">Generated image will appear here</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function VisionTab() {
  const [enabled, setEnabled] = useState(false);
  const [model, setModel] = useState('');
  const [imageData, setImageData] = useState('');
  const [imageName, setImageName] = useState('');
  const [prompt, setPrompt] = useState('Describe this image in detail.');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  useEffect(() => {
    let mounted = true;
    fetchJSON('/v1/vision/config').then((data: unknown) => {
      if (!mounted) return;
      const cfg = data as { enabled?: boolean; model?: string };
      setEnabled(Boolean(cfg.enabled));
      setModel(cfg.model || '');
    }).catch(() => { /* config optional */ });
    return () => { mounted = false; };
  }, []);

  function onFile(file: File | undefined) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setImageData(String(reader.result || ''));
      setImageName(file.name);
    };
    reader.readAsDataURL(file);
  }

  async function analyze() {
    if (!imageData) return;
    setLoading(true);
    try {
      const data = await fetchJSON('/v1/vision/analyze', {
        method: 'POST',
        body: JSON.stringify({ image: imageData, prompt: prompt || 'Describe this image in detail.' }),
      });
      setResult(toText(data));
      addToast(t('tools.result'), 'success');
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <div className="flex items-center gap-2 mb-1">
          <h3 className="font-semibold">{t('tools.vision')}</h3>
          <Badge variant={enabled ? 'success' : 'danger'}>{enabled ? 'enabled' : 'disabled'}</Badge>
        </div>
        {model && <p className="text-xs text-text-secondary mb-4">{t('tools.visionHint')} ({model})</p>}
        {!enabled && <p className="text-xs text-text-secondary mb-4">{t('tools.visionDisabled')}</p>}
        <div className="space-y-3">
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <span className="flex items-center gap-2 text-text-secondary">
              <Upload size={16} />
              {imageName || 'Upload an image'}
            </span>
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={e => onFile(e.target.files?.[0])}
              aria-label="Upload image"
            />
          </label>
          {imageData && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imageData} alt="Preview" className="rounded-xl border border-border max-h-[280px] object-contain w-full bg-bg-primary/50" />
          )}
          <Textarea label={t('tools.prompt')} value={prompt} onChange={e => setPrompt(e.target.value)} rows={2} />
          <Button onClick={analyze} disabled={loading || !imageData} className="gap-2">{loading ? t('tools.analyzing') : t('tools.run')}</Button>
        </div>
      </Card>
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold">{t('tools.result')}</h3>
            <p className="text-xs text-text-secondary">Image analysis output</p>
          </div>
          {result && <CopyButton text={result} />}
        </div>
        <div className={`bg-bg-primary/50 border border-border rounded-xl p-4 min-h-[300px] ${result ? '' : 'flex items-center justify-center'}`}>
          {result ? (
            <p className="text-sm whitespace-pre-wrap leading-relaxed">{result}</p>
          ) : (
            <p className="text-xs text-text-muted">Analysis results will appear here</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function DataScienceTab() {
  const [csvText, setCsvText] = useState('');
  const [targetCol, setTargetCol] = useState('');
  const [taskType, setTaskType] = useState('classification');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  async function runAutoML() {
    if (!csvText.trim() || !targetCol.trim()) return;
    setLoading(true);
    setResult('');
    try {
      const data = await fetchJSON('/v1/datascience/train', {
        method: 'POST',
        body: JSON.stringify({
          csv_text: csvText.trim(),
          target_column: targetCol.trim(),
          task_type: taskType,
          time_limit: 60,
        }),
      });
      setResult(JSON.stringify(data, null, 2));
      addToast('AutoML finished successfully', 'success');
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <h3 className="font-semibold mb-4 flex items-center gap-2">
          <Cpu size={18} className="text-accent" />
          Auto-Sklearn Data Scientist
        </h3>
        <p className="text-xs text-text-secondary mb-3">
          AutoML via auto-sklearn. This feature is Linux-only (auto-sklearn is not
          available on Windows); it requires free RAM &gt;= 3 GB and the
          <code className="mx-1 px-1 py-0.5 bg-bg-tertiary rounded">--automl</code>
          flag (or env <code>LLM_AUTOML=on</code>).
        </p>
        <div className="space-y-3">
          <Textarea
            label="CSV Data"
            value={csvText}
            onChange={e => setCsvText(e.target.value)}
            placeholder="column1,column2,target&#10;1,10,0&#10;2,20,1&#10;3,30,0"
            rows={10}
          />
          <Input
            label="Target Column Name"
            value={targetCol}
            onChange={e => setTargetCol(e.target.value)}
            placeholder="target"
          />
          <Select
            label="Task Type"
            value={taskType}
            onChange={e => setTaskType(e.target.value)}
            options={[
              { value: 'classification', label: 'Classification' },
              { value: 'regression', label: 'Regression' },
            ]}
          />
          <Button onClick={runAutoML} disabled={loading} className="gap-2">
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Database size={16} />}
            {loading ? 'Training...' : 'Train AutoML Model'}
          </Button>
        </div>
      </Card>
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold">{t('tools.result')}</h3>
            <p className="text-xs text-text-secondary">AutoML training output</p>
          </div>
          {result && <CopyButton text={result} />}
        </div>
        <div className={`bg-bg-primary/50 border border-border rounded-xl p-4 min-h-[300px] ${result ? '' : 'flex items-center justify-center'}`}>
          {result ? (
            <pre className="text-sm whitespace-pre-wrap overflow-x-auto font-mono">{result}</pre>
          ) : (
            <p className="text-xs text-text-muted">Training results will appear here</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function AgentCard({ agent }: { agent: Agent }) {
  const [form, setForm] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  async function run() {
    if (!form.trim()) return;
    setLoading(true);
    try {
      const data = await fetchJSON(`/v1/agents/${encodeURIComponent(agent.name)}/run`, { method: 'POST', body: JSON.stringify({ message: form }) });
      setResult(toText(data));
      addToast('Agent ran successfully', 'success');
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center gap-2.5">
        <div className="w-9 h-9 rounded-xl bg-accent-soft flex items-center justify-center text-accent shrink-0">
          <Bot size={18} />
        </div>
        <div className="min-w-0">
          <h3 className="font-semibold truncate">{agent.name}</h3>
          {agent.role && <Badge variant="brand" className="!text-[10px] mt-0.5">{agent.role}</Badge>}
        </div>
      </div>
      {agent.description && <p className="text-xs text-text-secondary leading-relaxed">{agent.description}</p>}
      <Textarea label={t('tools.message')} value={form} onChange={e => setForm(e.target.value)} rows={3} />
      <Button onClick={run} disabled={loading} className="w-full">{t('tools.run')}</Button>
      {result && (
        <div className="text-xs animate-fade-in">
          <div className="flex items-center justify-between mb-1">
            <span className="text-text-muted uppercase tracking-wider">{t('tools.result')}</span>
            <CopyButton text={result} />
          </div>
          <pre className="bg-bg-primary/50 p-3 rounded-xl overflow-x-auto border border-border">{result}</pre>
        </div>
      )}
    </Card>
  );
}

function SkillCard({ skill }: { skill: Skill }) {
  const [form, setForm] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  async function run() {
    if (!form.trim()) return;
    setLoading(true);
    try {
      const data = await fetchJSON(`/v1/skills/${encodeURIComponent(skill.name)}/run`, { method: 'POST', body: JSON.stringify({ input: form }) });
      setResult(toText(data));
      addToast('Skill ran successfully', 'success');
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center gap-2.5">
        <div className="w-9 h-9 rounded-xl bg-accent-soft flex items-center justify-center text-accent shrink-0">
          <Wrench size={18} />
        </div>
        <h3 className="font-semibold truncate">{skill.name}</h3>
      </div>
      {skill.description && <p className="text-xs text-text-secondary leading-relaxed">{skill.description}</p>}
      <Textarea label={t('tools.input')} value={form} onChange={e => setForm(e.target.value)} rows={3} />
      <Button onClick={run} disabled={loading} className="w-full">{t('tools.run')}</Button>
      {result && (
        <div className="text-xs animate-fade-in">
          <div className="flex items-center justify-between mb-1">
            <span className="text-text-muted uppercase tracking-wider">{t('tools.result')}</span>
            <CopyButton text={result} />
          </div>
          <pre className="bg-bg-primary/50 p-3 rounded-xl overflow-x-auto border border-border">{result}</pre>
        </div>
      )}
    </Card>
  );
}
