'use client';

import React, { useEffect, useState } from 'react';
import { fetchJSON, toArray, toText, type Workspace } from '@/lib/api';
import { useToast } from '@/components/providers/ToastProvider';
import Card from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Input from '@/components/ui/Input';
import Textarea from '@/components/ui/Textarea';
import Badge from '@/components/ui/Badge';
import Skeleton from '@/components/ui/Skeleton';
import Field from '@/components/ui/Field';
import PageHeader from '@/components/ui/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import { t } from '@/lib/i18n';
import { FolderOpen, Plus, Trash2, Upload, Search, Download, UploadCloud, Save, Eye, ShieldCheck } from 'lucide-react';

export default function WorkspacePage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [files, setFiles] = useState<{ name: string; chunks: number }[]>([]);
  const [searchResults, setSearchResults] = useState<{ file: string; score: number; preview: string }[]>([]);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editPrompt, setEditPrompt] = useState('');
  const [editing, setEditing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [importText, setImportText] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const { addToast } = useToast();

  const selectedWs = workspaces.find(w => w.id === selected);

  const loadWorkspaces = async () => {
    setLoading(true);
    try {
      const data = await fetchJSON('/v1/workspaces');
      const list = toArray<Workspace>(data);
      setWorkspaces(list);
      if (!selected && list.length) setSelected(list[0].id);
    } catch {
      addToast('Failed to load workspaces', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadWorkspaces(); }, []);

  useEffect(() => {
    if (!selected) return;
    let mounted = true;
    const wsId = selected;
    async function loadFiles() {
      try {
        const data = await fetchJSON(`/v1/workspaces/${encodeURIComponent(wsId)}/files`);
        if (!mounted) return;
        setFiles(toArray(data));
      } catch { /* ignore */ }
    }
    loadFiles();
    return () => { mounted = false; };
  }, [selected]);

  useEffect(() => {
    if (selectedWs) {
      setEditName(selectedWs.name);
      setEditDesc(selectedWs.description || '');
      setEditPrompt((selectedWs as unknown as Record<string, unknown>).system_prompt as string || '');
    }
  }, [selected, selectedWs]);

  async function createWorkspace() {
    if (!newName.trim()) return;
    try {
      await fetchJSON('/v1/workspaces', { method: 'POST', body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || undefined }) });
      addToast('Workspace created', 'success');
      setNewName('');
      setNewDesc('');
      loadWorkspaces();
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  async function deleteWorkspace(id: string) {
    if (id === 'default') {
      addToast('The default workspace cannot be deleted', 'error');
      return;
    }
    if (!window.confirm('Delete this workspace and all its files?')) return;
    try {
      await fetchJSON(`/v1/workspaces/${encodeURIComponent(id)}/delete`, { method: 'POST' });
      addToast('Workspace deleted', 'success');
      if (selected === id) setSelected(null);
      loadWorkspaces();
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  async function updateWorkspace() {
    if (!selected || !editName.trim()) return;
    setEditing(true);
    try {
      await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/update`, {
        method: 'POST',
        body: JSON.stringify({
          name: editName.trim(),
          description: editDesc.trim() || undefined,
          system_prompt: editPrompt.trim() || undefined,
        }),
      });
      addToast('Workspace updated', 'success');
      loadWorkspaces();
    } catch (e) {
      addToast(toText(e), 'error');
    } finally {
      setEditing(false);
    }
  }

  async function exportWorkspace() {
    if (!selected) return;
    try {
      const data = await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/export?format=json`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${selected}-export.json`;
      a.click();
      URL.revokeObjectURL(url);
      addToast('Workspace exported', 'success');
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  async function importWorkspace() {
    if (!selected || !importText.trim()) return;
    try {
      const body = JSON.parse(importText.trim());
      await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/import`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      addToast('Workspace imported', 'success');
      setImportText('');
      setShowImport(false);
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  async function uploadFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !selected) return;
    const content = await file.text();
    try {
      await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/files/upload`, {
        method: 'POST',
        body: JSON.stringify({ name: file.name, content }),
      });
      addToast('File uploaded', 'success');
      const data = await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/files`);
      setFiles(toArray(data));
    } catch (err) {
      addToast(toText(err), 'error');
    }
  }

  async function deleteFile(name: string) {
    if (!selected) return;
    if (!window.confirm(`Delete file "${name}"?`)) return;
    try {
      await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/files/delete?name=${encodeURIComponent(name)}`, { method: 'POST' });
      addToast('File deleted', 'success');
      const data = await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/files`);
      setFiles(toArray(data));
    } catch (err) {
      addToast(toText(err), 'error');
    }
  }

  async function openPreview(name: string) {
    if (!selected) return;
    setPreviewLoading(true);
    setPreviewFile(name);
    setPreviewContent('');
    try {
      const data = await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/files/${encodeURIComponent(name)}/content`) as { content?: string };
      setPreviewContent(data.content || '');
    } catch {
      setPreviewContent('Failed to load file content');
    } finally {
      setPreviewLoading(false);
    }
  }

  async function searchKnowledge() {
    if (!searchQuery.trim() || !selected) return;
    try {
      const data = await fetchJSON(`/v1/workspaces/${encodeURIComponent(selected)}/knowledge/search?q=${encodeURIComponent(searchQuery)}`);
      setSearchResults(toArray(data));
    } catch (e) {
      addToast(toText(e), 'error');
    }
  }

  if (loading) {
    return (
      <div className="page-shell space-y-6">
        <Skeleton className="h-9 w-48" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-64 lg:col-span-2" />
        </div>
      </div>
    );
  }

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title={t('workspace.title')}
        subtitle="Isolated chat areas backed by the knowledge store. Upload files and search them semantically."
        icon={<FolderOpen size={20} />}
      />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="space-y-4">
          <Card>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2"><FolderOpen size={16} className="text-accent" /> {t('workspace.workspaces')}</h3>
            <div className="space-y-2 mb-4">
              <Input value={newName} onChange={e => setNewName(e.target.value)} placeholder={t('workspace.newWorkspaceName')} />
              <Input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder={t('workspace.description')} />
              <Button onClick={createWorkspace} className="w-full gap-2" disabled={!newName.trim()}><Plus size={16} /> {t('workspace.create')}</Button>
            </div>
            <div className="space-y-1">
              {workspaces.map(ws => (
                <div key={ws.id} className={`flex items-center justify-between p-2.5 rounded-xl cursor-pointer transition-all ${selected === ws.id ? 'bg-accent-soft text-accent border border-accent/20' : 'hover:bg-bg-tertiary border border-transparent'}`} onClick={() => setSelected(ws.id)}>
                  <span className="text-sm font-medium flex items-center gap-2 min-w-0">
                    <FolderOpen size={14} className="shrink-0 opacity-60" />
                    <span className="truncate">{ws.name}</span>
                    {ws.id === 'default' && <Badge variant="brand" className="!text-[9px] !px-1.5 !py-0.5 shrink-0"><ShieldCheck size={9} /> Protected</Badge>}
                  </span>
                  <button onClick={(e) => { e.stopPropagation(); deleteWorkspace(ws.id); }} className={ws.id === 'default' ? 'invisible' : 'text-text-muted hover:text-danger shrink-0'} title={ws.id === 'default' ? 'Protected' : 'Delete'}><Trash2 size={14} /></button>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="lg:col-span-2 space-y-6">
          {selected ? (
            <>
              <Card>
                <h3 className="text-sm font-semibold mb-4 flex items-center gap-2"><FolderOpen size={15} className="text-accent" /> Workspace Settings</h3>
                <div className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <Field label="Name">
                      <Input value={editName} onChange={e => setEditName(e.target.value)} />
                    </Field>
                    <Field label="Description">
                      <Input value={editDesc} onChange={e => setEditDesc(e.target.value)} />
                    </Field>
                  </div>
                  <Field label="System Prompt">
                    <Textarea value={editPrompt} onChange={e => setEditPrompt(e.target.value)} rows={3} />
                  </Field>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Button onClick={updateWorkspace} disabled={editing || !editName.trim()} className="gap-2"><Save size={16} /> Save</Button>
                    <Button variant="secondary" onClick={exportWorkspace} className="gap-2"><Download size={16} /> Export</Button>
                    <Button variant="secondary" onClick={() => setShowImport(s => !s)} className="gap-2"><UploadCloud size={16} /> Import</Button>
                  </div>
                  {showImport && (
                    <div className="space-y-2 animate-fade-in">
                      <Textarea value={importText} onChange={e => setImportText(e.target.value)} rows={6} placeholder='Paste exported JSON here...' />
                      <Button onClick={importWorkspace} disabled={!importText.trim()}>Import</Button>
                    </div>
                  )}
                </div>
              </Card>

              <Card>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold flex items-center gap-2"><Upload size={15} className="text-accent" /> {t('workspace.files')}</h3>
                  <label className="cursor-pointer inline-flex items-center gap-2 text-sm text-accent hover:text-accent-hover px-3 py-1.5 rounded-lg border border-accent/25 bg-accent/10 transition-all hover:bg-accent/20">
                    <Upload size={16} />
                    <span>{t('workspace.upload')}</span>
                    <input type="file" className="hidden" onChange={uploadFile} />
                  </label>
                </div>
                <div className="space-y-2">
                  {files.length === 0 && (
                    <EmptyState
                      icon={<Upload size={22} />}
                      title={t('workspace.noFiles')}
                      description="Upload markdown or text files. They are chunked and embedded for semantic search."
                    />
                  )}
                  {files.map(f => (
                    <div key={f.name} className="flex items-center justify-between p-3 rounded-xl bg-bg-primary/30 border border-border hover:border-accent/30 transition-all">
                      <button onClick={() => openPreview(f.name)} className="text-sm text-left hover:text-accent transition-colors font-medium truncate min-w-0">{f.name}</button>
                      <div className="flex items-center gap-2.5 shrink-0">
                        <Badge variant="default">{f.chunks} {t('workspace.chunks')}</Badge>
                        <button onClick={() => openPreview(f.name)} className="p-1.5 text-text-muted hover:text-accent hover:bg-accent/10 rounded-lg transition-all" title="Preview"><Eye size={14} /></button>
                        <button onClick={() => deleteFile(f.name)} className="p-1.5 text-text-muted hover:text-danger hover:bg-danger/10 rounded-lg transition-all"><Trash2 size={14} /></button>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>

              {previewFile && (
                <Card>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold">Preview: {previewFile}</h3>
                    <Button variant="secondary" size="sm" onClick={() => setPreviewFile(null)}>Close</Button>
                  </div>
                  <pre className="text-xs bg-bg-primary/50 p-4 rounded-xl overflow-x-auto whitespace-pre-wrap border border-border max-h-96 scrollbar-thin">
                    {previewLoading ? 'Loading...' : previewContent || 'Empty file'}
                  </pre>
                </Card>
              )}

              <Card>
                <h3 className="text-sm font-semibold mb-4 flex items-center gap-2"><Search size={16} className="text-accent" /> {t('workspace.knowledgeSearch')}</h3>
                <div className="flex gap-2 mb-4">
                  <Input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder={t('workspace.searchPlaceholder')} className="flex-1" onKeyDown={e => { if (e.key === 'Enter') searchKnowledge(); }} />
                  <Button onClick={searchKnowledge}>{t('common.search')}</Button>
                </div>
                <div className="space-y-2">
                  {searchResults.length === 0 && searchQuery && <p className="text-text-muted text-sm py-2">{t('workspace.noResults')}</p>}
                  {searchResults.map((r, i) => (
                    <div key={i} className="p-3.5 rounded-xl bg-bg-primary/30 border border-border">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-sm font-medium">{r.file}</span>
                        <Badge variant="brand">{r.score.toFixed(2)}</Badge>
                      </div>
                      <p className="text-xs text-text-secondary leading-relaxed">{r.preview}</p>
                    </div>
                  ))}
                </div>
              </Card>
            </>
          ) : (
            <Card className="flex items-center justify-center h-64">
              <EmptyState
                icon={<FolderOpen size={24} />}
                title={t('workspace.selectOrCreate')}
                description="Create a new workspace or select an existing one from the sidebar."
              />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
