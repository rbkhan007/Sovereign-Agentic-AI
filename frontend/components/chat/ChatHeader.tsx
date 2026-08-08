'use client';

import React from 'react';
import { MessageSquare, Plus, X, History, Trash2, Square, Check, Slash, SlidersHorizontal } from 'lucide-react';
import Select from '@/components/ui/Select';
import Button from '@/components/ui/Button';
import ModesPopover from '@/components/chat/ModesPopover';
import { type ModelItem, type Agent, type Skill, type Workspace } from '@/lib/api';

export default function ChatHeader({
  currentConvTitle,
  convId,
  selectedWorkspace,
  workspaces,
  selectedModel,
  models,
  modelLoading,
  modelLoaded,
  modelCtx,
  sessionTokens,
  sessionCost,
  activeModel,
  sending,
  streaming,
  autoStreaming,
  planning,
  agenticTools,
  codeAgent,
  pendingAction,
  selectedAgent,
  agents,
  selectedSkill,
  skills,
  modesOpen,
  onNewChat,
  onClearChat,
  onStopGeneration,
  onModelChange,
  onWorkspaceChange,
  onAgentChange,
  onSkillChange,
  onToggleMode,
  onToggleModesOpen,
  onRunPreset,
  onCancelPending,
}: {
  currentConvTitle: string;
  convId: string;
  selectedWorkspace: string;
  workspaces: Workspace[];
  selectedModel: string;
  models: ModelItem[];
  modelLoading: boolean;
  modelLoaded: boolean;
  modelCtx: string | null;
  sessionTokens: number;
  sessionCost: number;
  activeModel: ModelItem | undefined;
  sending: boolean;
  streaming: boolean;
  autoStreaming: boolean;
  planning: boolean;
  agenticTools: boolean;
  codeAgent: boolean;
  pendingAction: string | null;
  selectedAgent: string;
  agents: Agent[];
  selectedSkill: string;
  skills: Skill[];
  modesOpen: boolean;
  onNewChat: () => void;
  onClearChat: () => void;
  onStopGeneration: () => void;
  onModelChange: (value: string) => void;
  onWorkspaceChange: (value: string) => void;
  onAgentChange: (value: string) => void;
  onSkillChange: (value: string) => void;
  onToggleMode: (key: string, checked: boolean) => void;
  onToggleModesOpen: () => void;
  onRunPreset: (action: 'clear' | 'compact' | 'review' | 'test' | 'model' | 'help') => void;
  onCancelPending: () => void;
}) {
  const modes = [
    { key: 'stream', label: 'Stream', checked: streaming, description: 'Real-time token streaming' },
    { key: 'auto', label: 'Auto-stream', checked: autoStreaming, description: 'Automatic streaming decisions' },
    { key: 'agentic', label: 'Agentic Tools', checked: agenticTools, description: 'Enable computer agent tools' },
    { key: 'code', label: 'Code Agent', checked: codeAgent, description: 'Use code-focused agent protocol' },
    { key: 'planning', label: 'Planning', checked: planning, description: 'Multi-step planning mode' },
  ];

  return (
    <div className="px-4 py-3 border-b border-border bg-bg-secondary/40">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-xl bg-accent/20 flex items-center justify-center text-accent shrink-0">
            <MessageSquare size={18} />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold truncate">{currentConvTitle || 'New Conversation'}</h1>
            <div className="flex items-center gap-2 mt-0.5">
              {convId && <span className="text-[10px] font-mono text-text-muted">{convId.slice(0, 8)}...</span>}
              {selectedWorkspace && <span className="text-[10px] text-text-muted">Workspace: {selectedWorkspace}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {sending && (
            <Button variant="danger" size="sm" onClick={onStopGeneration} className="!py-1 !px-2 gap-1 text-xs">
              <Square size={12} /> Stop
            </Button>
          )}
          {pendingAction === 'clear' ? (
            <>
              <span className="text-xs text-text-secondary">Confirm?</span>
              <Button variant="danger" size="sm" onClick={onClearChat} className="!py-1 !px-2 gap-1 text-xs">Yes</Button>
              <Button variant="secondary" size="sm" onClick={onCancelPending} className="!py-1 !px-2 gap-1 text-xs">No</Button>
            </>
          ) : (
            <>
              <Button variant="secondary" size="sm" onClick={onNewChat} className="!py-1.5 !px-2.5 gap-1">
                <Plus size={14} />
                <span className="hidden sm:inline">New</span>
              </Button>
              <Button variant="secondary" size="sm" onClick={onClearChat} className="!py-1.5 !px-2.5 gap-1">
                <Trash2 size={14} />
                <span className="hidden sm:inline">Clear</span>
              </Button>
            </>
          )}
          <button className="p-1.5 rounded-xl text-text-secondary hover:text-accent hover:bg-accent/10 transition-all" title="History">
            <History size={18} />
          </button>
        </div>
      </div>
      <div className="flex items-center gap-2 relative">
        <Select label="" value={selectedModel} onChange={(e) => onModelChange(e.target.value)} options={models.map((m) => ({ value: m.id, label: `${m.id}${m.role ? ` (${m.role})` : ''}` }))} disabled={models.length === 0 || modelLoading} hint={modelLoading ? 'Loading...' : (models.length === 0 ? 'No models' : '')} className="!w-auto min-w-[160px]" />
        <Select label="" value={selectedWorkspace} onChange={(e) => onWorkspaceChange(e.target.value)} options={workspaces.map((w) => ({ value: w.id, label: w.name || w.id }))} disabled={workspaces.length === 0} className="!w-auto min-w-[140px]" />
        <Select label="" value={selectedAgent} onChange={(e) => onAgentChange(e.target.value)} options={agents.map((a) => ({ value: a.name, label: a.name }))} disabled={agents.length === 0} className="!w-auto min-w-[140px]" />
        <Select label="" value={selectedSkill} onChange={(e) => onSkillChange(e.target.value)} options={skills.map((s) => ({ value: s.name, label: s.name }))} disabled={skills.length === 0} className="!w-auto min-w-[140px]" />
        <div className="relative">
          <Button variant="secondary" size="sm" onClick={onToggleModesOpen} className="gap-1.5">
            <SlidersHorizontal size={14} />
            <span className="hidden sm:inline">Modes</span>
          </Button>
          <ModesPopover open={modesOpen} onClose={onToggleModesOpen} modes={modes} onToggle={onToggleMode} />
        </div>
      </div>
      <div className="flex items-center gap-2 mt-2.5">
        <button onClick={() => onRunPreset('clear')} className="px-2.5 py-1 rounded-lg text-xs text-text-secondary hover:text-accent hover:bg-accent/10 transition-all">/clear</button>
        <button onClick={() => onRunPreset('compact')} className="px-2.5 py-1 rounded-lg text-xs text-text-secondary hover:text-accent hover:bg-accent/10 transition-all">/compact</button>
        <button onClick={() => onRunPreset('review')} className="px-2.5 py-1 rounded-lg text-xs text-text-secondary hover:text-accent hover:bg-accent/10 transition-all">/review</button>
      </div>
    </div>
  );
}
