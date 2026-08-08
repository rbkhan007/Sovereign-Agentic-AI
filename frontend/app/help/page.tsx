'use client';

import React, { useState } from 'react';
import Card from '@/components/ui/Card';
import PageHeader from '@/components/ui/PageHeader';
import { t } from '@/lib/i18n';
import { Cpu, MessageSquare, Database, FolderOpen, BookOpen, Zap, ChevronDown, ChevronRight, HelpCircle } from 'lucide-react';

function CollapsibleSection({ title, icon, children, defaultOpen = false }: { title: string; icon: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card className="p-6">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="w-full flex items-center gap-3 mb-0 hover:opacity-80 transition-opacity text-left">
        <div className="w-10 h-10 rounded-xl bg-accent-soft flex items-center justify-center text-accent shrink-0">
          {icon}
        </div>
        <h2 className="text-lg font-semibold flex-1">{title}</h2>
        {open ? <ChevronDown size={18} className="text-text-muted" /> : <ChevronRight size={18} className="text-text-muted" />}
      </button>
      {open && <div className="mt-4 pt-4 border-t border-border">{children}</div>}
    </Card>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="bg-bg-primary/80 border border-border rounded-xl p-3 text-xs font-mono overflow-x-auto text-text-primary mt-2 mb-2">
      <code>{children}</code>
    </pre>
  );
}

export default function HelpPage() {
  return (
    <div className="page-shell max-w-5xl space-y-6">
      <PageHeader
        title={t('help.title')}
        subtitle={t('help.subtitle')}
        icon={<HelpCircle size={20} />}
      />

      <Card className="p-6">
        <h2 className="text-lg font-semibold mb-3">{t('help.quickStart')}</h2>
        <ol className="list-decimal list-inside space-y-2 text-sm text-text-secondary">
          <li>Start the server: <code className="px-1.5 py-0.5 rounded bg-bg-tertiary border border-border text-xs">python run.py web</code></li>
          <li>Open <strong>Dashboard</strong> and confirm GPU is detected and <em>Backend connected</em> is green.</li>
          <li>Go to <strong>Models</strong> and click <em>Load</em> on your preferred Executor.</li>
          <li>Open <strong>Chat</strong>, verify the loaded model is selected, and start chatting.</li>
          <li>Monitor <strong>Dashboard</strong> graphs to watch RAM, VRAM, and CPU in real time.</li>
          <li>(Optional) Enable PostgreSQL with <code className="px-1.5 py-0.5 rounded bg-bg-tertiary border border-border text-xs">--db</code> for persistent memory.</li>
        </ol>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <CollapsibleSection title={t('help.models')} icon={<Cpu size={20} />}>
          <div className="space-y-3 text-sm text-text-secondary">
            <p><strong className="text-text-primary">{t('help.whatAreModels')}</strong> {t('help.modelDesc')}</p>
            <p><strong className="text-text-primary">{t('help.howToLoad')}</strong> {t('help.loadDesc')}</p>
            <p><strong className="text-text-primary">{t('help.chatSelection')}</strong> {t('help.chatSelectDesc')}</p>
            <p><strong className="text-text-primary">{t('help.vramBudget')}</strong> {t('help.vramDesc')}</p>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title={t('help.chat')} icon={<MessageSquare size={20} />}>
          <div className="space-y-3 text-sm text-text-secondary">
            <p><strong className="text-text-primary">{t('help.sendMessages')}</strong> {t('help.sendDesc')}</p>
            <p><strong className="text-text-primary">{t('help.streaming')}</strong> {t('help.streamDesc')}</p>
            <p><strong className="text-text-primary">{t('help.planning')}</strong> {t('help.planDesc')}</p>
            <p><strong className="text-text-primary">{t('help.conversations')}</strong> {t('help.convDesc')}</p>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title={t('help.workspace')} icon={<FolderOpen size={20} />}>
          <div className="space-y-3 text-sm text-text-secondary">
            <p><strong className="text-text-primary">{t('help.isolatedContexts')}</strong> {t('help.isoDesc')}</p>
            <p><strong className="text-text-primary">{t('help.fileUpload')}</strong> {t('help.fileDesc')}</p>
            <p><strong className="text-text-primary">{t('help.knowledgeGraph')}</strong> {t('help.kgDesc')}</p>
            <p><strong className="text-text-primary">{t('help.exportImport')}</strong> {t('help.expDesc')}</p>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title={t('help.performanceTips')} icon={<Zap size={20} />}>
          <div className="space-y-3 text-sm text-text-secondary">
            <p><strong className="text-text-primary">{t('help.vramTip')}</strong> {t('help.vramTipDesc')}</p>
            <p><strong className="text-text-primary">{t('help.threadsTip')}</strong> {t('help.threadsTipDesc')}</p>
            <p><strong className="text-text-primary">{t('help.parallelTip')}</strong> {t('help.parallelTipDesc')}</p>
            <p><strong className="text-text-primary">{t('help.contextTip')}</strong> {t('help.contextTipDesc')}</p>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title={t('help.shortcuts')} icon={<BookOpen size={20} />}>
          <div className="space-y-3 text-sm text-text-secondary">
            <p><strong className="text-text-primary">{t('help.dashboardGraphs')}</strong> {t('help.dashDesc')}</p>
            <p><strong className="text-text-primary">{t('help.modelLoadingTip')}</strong> {t('help.modelLoadDesc')}</p>
            <p><strong className="text-text-primary">{t('help.agentsSkills')}</strong> {t('help.agentDesc')}</p>
            <p><strong className="text-text-primary">{t('help.cliMode')}</strong> {t('help.cliDesc')}</p>
          </div>
        </CollapsibleSection>
      </div>

      {/* PostgreSQL + pgvector Setup Guide */}
      <CollapsibleSection title="PostgreSQL + pgvector Setup" icon={<Database size={20} />} defaultOpen={false}>
        <div className="space-y-4 text-sm text-text-secondary">
          <p className="text-text-primary font-medium">Required for: persistent memory, semantic search, knowledge graphs, workspace file embeddings.</p>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">1. Install PostgreSQL 15+</h4>
            <p className="mb-2">Download from <a href="https://www.postgresql.org/download/" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">postgresql.org</a> or use your package manager:</p>
            <CodeBlock>{`# Windows: download installer from postgresql.org
# Linux (Ubuntu/Debian):
sudo apt install postgresql postgresql-contrib

# macOS:
brew install postgresql@16`}</CodeBlock>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">2. Enable pgvector Extension</h4>
            <p className="mb-2">Install the pgvector extension for vector similarity search:</p>
            <CodeBlock>{`# Linux:
sudo apt install postgresql-16-pgvector

# macOS:
brew install pgvector

# Or build from source:
git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git
cd pgvector && make && sudo make install`}</CodeBlock>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">3. Create Database and Enable Extension</h4>
            <CodeBlock>{`# Connect to PostgreSQL
psql -U postgres

# Create the database
CREATE DATABASE rhasan_indie_agentic_llm;

# Connect to it
\\c rhasan_indie_agentic_llm

# Enable the vector extension
CREATE EXTENSION IF NOT EXISTS vector;

# Verify
\\dx vector`}</CodeBlock>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">4. Create User (Recommended)</h4>
            <CodeBlock>{`CREATE USER llm_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE rhasan_indie_agentic_llm TO llm_user;
ALTER USER llm_user CREATEDB;
\\c rhasan_indie_agentic_llm
GRANT ALL ON SCHEMA public TO llm_user;`}</CodeBlock>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">5. Start the App with DB</h4>
            <CodeBlock>{`# Basic (uses defaults: localhost:5432, postgres user)
python run.py --db

# Custom connection
python run.py --db --db-name rhasan_indie_agentic_llm --db-user llm_user --db-password your_secure_password

python run.py --db --db-password postgres`}</CodeBlock>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">6. Environment Variables (Alternative)</h4>
            <p className="mb-2">Instead of CLI flags, set these environment variables:</p>
            <CodeBlock>{`export PGHOST=localhost
export PGPORT=5432
export PGUSER=llm_user
export PGPASSWORD=your_secure_password
export PGDATABASE=rhasan_indie_agentic_llm
export LLM_DB=on

python run.py`}</CodeBlock>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">7. Auto-Database Creation</h4>
            <p className="mb-2">The app automatically creates the database if it doesn't exist (requires superuser or CREATEDB privilege). On first startup with <code className="px-1.5 py-0.5 rounded bg-bg-tertiary border border-border text-xs">--db</code>, it will:</p>
            <ol className="list-decimal list-inside space-y-1 ml-2">
              <li>Attempt to connect to the target database</li>
              <li>If it doesn't exist, connect to <code className="px-1 py-0.5 rounded bg-bg-tertiary border border-border text-xs">postgres</code> and run <code className="px-1 py-0.5 rounded bg-bg-tertiary border border-border text-xs">CREATE DATABASE</code></li>
              <li>Create all required tables: agent_memory, workspaces, workspace_files, nodes, edges, tags</li>
              <li>Enable the pgvector extension and create IVFFlat indexes (after 2,000+ rows)</li>
              <li>Optionally register the connection in pgAdmin 4</li>
            </ol>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">8. pgAdmin 4 Connection Setup</h4>
            <p className="mb-2">The app auto-registers the database in pgAdmin 4 when it starts. If auto-registration doesn't work:</p>
            <CodeBlock>{`# Method 1: Import servers.json
# The app generates a servers.json at:
#   Windows: %APPDATA%\\pgAdmin\\servers.json
#   Linux:   ~/.pgadmin/servers.json

# Method 2: Manual setup in pgAdmin 4
# 1. Open pgAdmin 4
# 2. Right-click "Servers" â†’ Register â†’ Server
# 3. General tab:
#    - Name: Agentic LLM (rhasan_indie_agentic_llm)
#    - Group: Agentic LLM
# 4. Connection tab:
#    - Host: localhost
#    - Port: 5432
#    - Database: rhasan_indie_agentic_llm
#    - Username: postgres (or llm_user)
#    - Password: your password
# 5. Click "Save"`}</CodeBlock>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">9. Verify Connection</h4>
            <p className="mb-2">After starting, check the <strong>Database</strong> page in the UI. You should see:</p>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li><span className="text-success font-medium">Connected</span> status badge</li>
              <li>Memory count and token statistics</li>
              <li>Vector dimension: <code className="px-1 py-0.5 rounded bg-bg-tertiary border border-border text-xs">384</code> (all-MiniLM-L6-v2)</li>
              <li>IVFFlat index status: <span className="text-success">created</span> (auto-created after 2,000+ rows)</li>
              <li>Connection pool: active/min/max connections</li>
              <li>Auto-prune: running with interval and max age</li>
            </ul>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">Troubleshooting</h4>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li><strong>Connection refused:</strong> Check PostgreSQL is running: <code className="px-1 py-0.5 rounded bg-bg-tertiary border border-border text-xs">pg_isready</code></li>
              <li><strong>Authentication failed:</strong> Check pg_hba.conf allows password auth for your user</li>
              <li><strong>Database does not exist:</strong> The app will auto-create it if your user has CREATEDB privilege</li>
              <li><strong>Vector extension not found:</strong> Ensure pgvector is installed and the extension is created</li>
              <li><strong>App falls back to in-memory:</strong> DB connection failed; app still works but data is not persistent</li>
              <li><strong>pgAdmin can't connect:</strong> Verify pg_hba.conf allows connections from 127.0.0.1</li>
            </ul>
          </div>
        </div>
      </CollapsibleSection>

      {/* Hardware Monitoring */}
      <CollapsibleSection title="Real-Time Hardware Monitoring" icon={<Cpu size={20} />} defaultOpen={false}>
        <div className="space-y-4 text-sm text-text-secondary">
          <p className="text-text-primary font-medium">The dashboard displays live hardware metrics polled every 2 seconds.</p>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">What is Monitored</h4>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li><strong>RAM Usage:</strong> Used vs total system memory (MB + percentage)</li>
              <li><strong>VRAM Usage:</strong> GPU video memory used vs total (for Vulkan/CUDA)</li>
              <li><strong>CPU Utilization:</strong> Overall CPU usage percentage</li>
              <li><strong>Token Throughput:</strong> Tokens generated per second</li>
              <li><strong>Request Count:</strong> Total API requests served</li>
            </ul>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">Dashboard Charts</h4>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li><strong>Memory Usage:</strong> Area chart showing RAM and VRAM over time</li>
              <li><strong>CPU &amp; Throughput:</strong> Line chart showing CPU % and tokens/sec over time</li>
              <li>Click the <strong>Refresh</strong> button to pause/resume live updates</li>
              <li>Data is kept for the last 30 polling cycles (~60 seconds)</li>
            </ul>
          </div>

          <div>
            <h4 className="text-text-primary font-semibold mb-2">API Endpoints</h4>
            <CodeBlock>{`GET /v1/hardware    # RAM, VRAM, CPU cores, GPU info
GET /v1/system      # Full system info + version
GET /v1/metrics     # Per-model and per-task metrics
GET /v1/metrics     # Request counts, latency, tokens/sec`}</CodeBlock>
          </div>
        </div>
      </CollapsibleSection>
    </div>
  );
}

