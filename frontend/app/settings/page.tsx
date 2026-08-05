'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { fetchJSON, toText } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import Input from '@/components/ui/Input';
import Button from '@/components/ui/Button';
import Section from '@/components/ui/Section';
import Field from '@/components/ui/Field';
import Switch from '@/components/ui/Switch';
import Skeleton, { CardSkeleton } from '@/components/ui/Skeleton';
import Badge from '@/components/ui/Badge';
import PageHeader from '@/components/ui/PageHeader';
import { t } from '@/lib/i18n';
import { RefreshCw, Server, Cpu, Gauge, Key, Shield, Eye, EyeOff, RotateCcw, Settings2 } from 'lucide-react';

interface CloudPreset {
  label: string;
  base_url: string;
  chat_model: string;
}

interface CloudConfig {
  provider: string;
  base_url: string;
  chat_model: string;
  presets: Record<string, CloudPreset>;
}

interface OpenAIConfig {
  enabled: boolean;
  base_url: string;
  rate_limit_per_min?: number;
  backoff_max_s?: number;
}

export default function SettingsPage() {
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const { addToast } = useToast();

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchJSON('/v1/config');
      setConfig(data as Record<string, unknown>);
      setApiKey('');
    } catch {
      addToast('Failed to load config', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const KEY_MAP: Record<string, string> = {
    vram_budget_mb: 'vram.budget_mb',
    parallel_max: 'parallel.max',
    prune_interval_hours: 'prune.interval_hours',
    prune_max_age_days: 'prune.max_age_days',
    gen_timeout_s: 'gen.timeout_s',
  };

  const update = useCallback(async (key: string, value: unknown) => {
    const backendKey = key.startsWith('models.')
      ? `model.${key.slice('models.'.length)}`
      : (KEY_MAP[key] || key);
    setSaving(true);
    try {
      await fetchJSON('/v1/config', {
        method: 'POST',
        body: JSON.stringify({ key: backendKey, value }),
      });
      addToast('Config updated', 'success');
      load();
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setSaving(false);
    }
  }, [addToast]);

  const cloud = config.cloud as CloudConfig | undefined;
  const openai = config.openai as OpenAIConfig | undefined;
  const presets = cloud?.presets ?? {};
  const currentProvider = cloud?.provider || '';

  const handleProviderChange = async (provider: string) => {
    if (!provider) {
      await update('cloud.provider', 'none');
      return;
    }
    await update('cloud.provider', provider);
  };

  const handleApiKeySubmit = async () => {
    if (!apiKey.trim()) {
      addToast('Please enter an API key', 'error');
      return;
    }
    setSaving(true);
    try {
      await fetchJSON('/v1/config', {
        method: 'POST',
        body: JSON.stringify({ key: 'openai.api_key', value: apiKey.trim() }),
      });
      await fetchJSON('/v1/config', {
        method: 'POST',
        body: JSON.stringify({ key: 'openai.enabled', value: true }),
      });
      addToast('API key saved', 'success');
      setApiKey('');
      load();
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="page-shell space-y-6">
        <Skeleton className="h-9 w-48" />
        {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)}
      </div>
    );
  }

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title={t('settings.title')}
        subtitle={t('settings.subtitle')}
        icon={<Settings2 size={20} />}
      >
        <Button onClick={load} variant="secondary" className="gap-2">
          <RefreshCw size={16} />
          {t('settings.reload')}
        </Button>
      </PageHeader>

      {/* API Keys Section */}
      <Section
        title="API Keys"
        icon={<Key size={20} />}
        description="Configure cloud AI providers and API keys"
      >
        <div className="space-y-6">
          {/* Provider Selection */}
          <div className="space-y-3">
            <p className="text-sm font-medium text-text-primary">Cloud Provider</p>
            <p className="text-xs text-text-muted">Select a provider to auto-fill the base URL and model name</p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {Object.entries(presets).map(([key, preset]) => (
                <button
                  key={key}
                  onClick={() => handleProviderChange(key)}
                  className={`p-4 rounded-xl border-2 transition-all duration-200 text-left ${
                    currentProvider === key
                      ? 'border-accent bg-accent-soft shadow-glow'
                      : 'border-border bg-bg-secondary/50 hover:border-accent/30 hover:bg-bg-secondary'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-sm">{preset.label}</span>
                    {currentProvider === key && openai?.enabled && (
                      <Badge variant="success" className="text-[10px]">Active</Badge>
                    )}
                  </div>
                  <p className="text-xs text-text-muted truncate">{preset.chat_model}</p>
                </button>
              ))}
              <button
                onClick={() => handleProviderChange('')}
                className={`p-4 rounded-xl border-2 transition-all duration-200 text-left ${
                  !currentProvider
                    ? 'border-border bg-bg-secondary/50'
                    : 'border-border bg-bg-secondary/50 hover:border-accent/30 hover:bg-bg-secondary'
                }`}
              >
                <span className="font-semibold text-sm text-text-secondary">None (Local Only)</span>
                <p className="text-xs text-text-muted mt-1">Use local models only</p>
              </button>
            </div>
          </div>

          {/* API Key Input */}
          {currentProvider && (
            <div className="p-4 rounded-xl bg-bg-secondary/30 border border-border space-y-4">
              <div className="flex items-center gap-2 mb-2">
                <Shield size={16} className="text-accent" />
                <span className="text-sm font-medium">API Key for {presets[currentProvider]?.label || currentProvider}</span>
                {openai?.enabled && (
                  <Badge variant="success" className="text-[10px]">Configured</Badge>
                )}
              </div>

              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Input
                    type={showApiKey ? 'text' : 'password'}
                    value={apiKey}
                    onChange={e => setApiKey(e.target.value)}
                    placeholder={`Enter your ${presets[currentProvider]?.label || currentProvider} API key`}
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
                  >
                    {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                <Button
                  onClick={handleApiKeySubmit}
                  disabled={saving || !apiKey.trim()}
                  className="gap-2"
                >
                  {saving ? 'Saving...' : 'Save Key'}
                </Button>
              </div>

              <p className="text-xs text-text-muted">
                Your API key is stored locally and never sent to our servers.
              </p>
            </div>
          )}

          {/* Base URL & Model */}
          {currentProvider && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="Base URL">
                <Input
                  value={cloud?.base_url || ''}
                  onChange={e => update('openai.base_url', e.target.value)}
                  placeholder="https://api.openai.com/v1"
                />
              </Field>
              <Field label="Model">
                <Input
                  value={cloud?.chat_model || ''}
                  onChange={e => update('openai.chat_model', e.target.value)}
                  placeholder="gpt-4o-mini"
                />
              </Field>
            </div>
          )}

          {/* Enable/Disable Toggle */}
          {currentProvider && (
            <Switch
              label="Enable Cloud Provider"
              checked={openai?.enabled ?? false}
              onChange={v => update('openai.enabled', v)}
              hint="When enabled, the system will use this cloud provider as a fallback"
            />
          )}

          {/* Rate Limiting */}
          {currentProvider && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
              <Field label="Rate Limit (calls/min)">
                <Input
                  type="number"
                  min="1"
                  max="120"
                  value={String(openai?.rate_limit_per_min ?? 10)}
                  onChange={e => update('openai.rate_limit_per_min', parseInt(e.target.value) || 10)}
                />
              </Field>
              <Field label="Backoff Max (seconds)">
                <Input
                  type="number"
                  min="1"
                  max="300"
                  value={String(openai?.backoff_max_s ?? 60)}
                  onChange={e => update('openai.backoff_max_s', parseFloat(e.target.value) || 60)}
                />
              </Field>
              <div className="md:col-span-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    update('openai.rate_limit_per_min', 10);
                    update('openai.backoff_max_s', 60);
                    addToast('Rate limit settings reset to defaults', 'success');
                  }}
                >
                  <RotateCcw size={14} /> Reset to Defaults
                </Button>
              </div>
            </div>
          )}
        </div>
      </Section>

      {/* Server Section */}
      <Section title={t('settings.server')} icon={<Server size={20} />} description="Backend connection settings (host/port require a restart to change)">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label={t('settings.host')}>
            <Input value={String(config.host || 'localhost')} disabled hint="Set at startup via run.py --host" />
          </Field>
          <Field label={t('settings.port')}>
            <Input type="number" value={String(config.port || 8070)} disabled hint="Set at startup via run.py --port" />
          </Field>
        </div>
      </Section>

      {/* Security Section */}
      <Section title="Security" icon={<Shield size={20} />} description="Admin key and per-IP rate limiting">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label="Admin Key" hint="Required via X-Admin-Key for control-plane mutations (config, model load, agent/skill/LoRA writes)">
            <Input
              value={String(config.admin_key ? 'set' : '')}
              disabled
              placeholder="Set at startup via run.py --admin-key or LLM_ADMIN_KEY"
            />
          </Field>
          <Field label="Rate Limit (light/min)">
            <Input type="number" min="1" value={String((config.rate_limit as Record<string, unknown> | undefined)?.light_per_min ?? 120)} onChange={e => update('rate_limit.light_per_min', parseInt(e.target.value))} />
          </Field>
          <Field label="Rate Limit (heavy/min)">
            <Input type="number" min="1" value={String((config.rate_limit as Record<string, unknown> | undefined)?.heavy_per_min ?? 10)} onChange={e => update('rate_limit.heavy_per_min', parseInt(e.target.value))} />
          </Field>
        </div>
        <div className="mt-4 space-y-3">
          <Switch
            label="Per-IP Rate Limiting"
            checked={Boolean((config.rate_limit as Record<string, unknown> | undefined)?.enabled)}
            onChange={v => update('rate_limit.enabled', v)}
            hint="Throttle /v1/* and /mcp by client IP (heavy endpoints: chat, generate, batch, vision, images, tools)"
          />
          <Switch
            label="Exempt Localhost from Rate Limits"
            checked={Boolean((config.rate_limit as Record<string, unknown> | undefined)?.exempt_localhost ?? true)}
            onChange={v => update('rate_limit.exempt_localhost', v)}
            hint="Skip rate limiting for 127.0.0.1 / ::1 clients"
          />
        </div>
      </Section>

      {/* Model Tuning Section */}
      <Section title={t('settings.modelTuning')} icon={<Cpu size={20} />} description="Per-model generation parameters">
        <div className="space-y-4">
          {(config.models as Array<Record<string, unknown>> || []).map((params, idx) => {
            const name = String(params.name || `model-${idx}`);
            const role = typeof params.role === 'string' ? params.role : '';
            return (
              <div key={name} className="space-y-3 p-4 rounded-xl bg-bg-secondary/30 border border-border">
                <div className="flex items-center gap-2">
                  <Cpu size={14} className="text-accent" />
                  <p className="text-sm font-semibold text-accent">{name}</p>
                  {role && <Badge variant="brand" className="text-[10px]">{role}</Badge>}
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Field label={t('settings.temperature')}>
                    <Input
                      type="number"
                      step="0.1"
                      min="0"
                      max="2"
                      value={String(params.temperature ?? 0.7)}
                      onChange={e => update(`models.${name}.temperature`, parseFloat(e.target.value))}
                    />
                  </Field>
                  <Field label={t('settings.maxTokens')}>
                    <Input
                      type="number"
                      min="16"
                      value={String(params.max_tokens ?? 512)}
                      onChange={e => update(`models.${name}.max_tokens`, parseInt(e.target.value))}
                    />
                  </Field>
                  <Field label={t('settings.context')}>
                    <Input
                      type="number"
                      min="256"
                      value={String(params.n_ctx ?? 2048)}
                      onChange={e => update(`models.${name}.n_ctx`, parseInt(e.target.value))}
                    />
                  </Field>
                  <Field label={t('settings.topP')}>
                    <Input
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      value={String(params.top_p ?? 0.9)}
                      onChange={e => update(`models.${name}.top_p`, parseFloat(e.target.value))}
                    />
                  </Field>
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {/* Performance Section */}
      <Section title={t('settings.performance')} icon={<Gauge size={20} />} description="Harness, parallel, VRAM, prune, and cloud settings">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <Field label={t('settings.threads')}>
            <Input type="number" min="1" value={String(config.threads ?? 4)} onChange={e => update('threads', parseInt(e.target.value))} />
          </Field>
          <Field label={t('settings.vramBudget')}>
            <Input type="number" min="256" value={String((config.vram as Record<string, unknown> | undefined)?.budget_mb ?? 4096)} onChange={e => update('vram_budget_mb', parseInt(e.target.value))} />
          </Field>
          <Field label={t('settings.parallelMax')}>
            <Input type="number" min="1" value={String((config.parallel as Record<string, unknown> | undefined)?.max ?? 2)} onChange={e => update('parallel_max', parseInt(e.target.value))} />
          </Field>
          <Field label={t('settings.pruneInterval')}>
            <Input type="number" min="1" value={String((config.prune as Record<string, unknown> | undefined)?.interval_hours ?? 6)} onChange={e => update('prune_interval_hours', parseInt(e.target.value))} />
          </Field>
          <Field label={t('settings.pruneMaxAge')}>
            <Input type="number" min="1" value={String((config.prune as Record<string, unknown> | undefined)?.max_age_days ?? 30)} onChange={e => update('prune_max_age_days', parseInt(e.target.value))} />
          </Field>
          <Field label={t('settings.genTimeout')}>
            <Input type="number" min="5" value={String((config.gen as Record<string, unknown> | undefined)?.timeout_s ?? 240)} onChange={e => update('gen_timeout_s', parseFloat(e.target.value))} />
          </Field>
        </div>

        <div className="mt-4 space-y-3">
          <Switch
            label="Parallel Generation"
            checked={Boolean((config as Record<string, unknown>).parallel && typeof (config as Record<string, unknown>).parallel === 'object' && !!(config as Record<string, unknown>).parallel && (config as { parallel?: { enabled?: boolean } }).parallel?.enabled)}
            onChange={v => update('parallel.enabled', v)}
            hint="Generate responses from multiple models simultaneously"
          />
          <Switch
            label="Auto-load Models"
            checked={Boolean((config as Record<string, unknown>).vram && typeof (config as Record<string, unknown>).vram === 'object' && (config as { vram?: { auto_load?: boolean } }).vram?.auto_load)}
            onChange={v => update('vram.auto_load', v)}
            hint="Automatically load models based on VRAM budget"
          />
          <Switch
            label="Auto-tune Hardware"
            checked={Boolean((config as Record<string, unknown>).vram && typeof (config as Record<string, unknown>).vram === 'object' && (config as { vram?: { auto_tune?: boolean } }).vram?.auto_tune)}
            onChange={v => update('vram.auto_tune', v)}
            hint="Automatically detect hardware and optimize settings"
          />
        </div>
      </Section>
    </div>
  );
}
