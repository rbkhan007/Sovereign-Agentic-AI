'use client';

import React, { useState } from 'react';
import { useAuth } from '@/components/auth/AuthProvider';
import { ShieldCheck, KeyRound, Lock, Unlock, Terminal, AlertTriangle } from 'lucide-react';
import Link from 'next/link';

export default function LoginPage() {
  const { login } = useAuth();
  const [apiToken, setApiToken] = useState('');
  const [adminKey, setAdminKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    const ok = await login(apiToken.trim(), adminKey.trim());
    setLoading(false);
    if (!ok) {
      setError('Invalid token. The backend rejected the credentials.');
    }
  };

  return (
    <div className="flex items-center justify-center min-h-[100dvh] p-4">
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-accent-soft border border-accent/20 mb-4 shadow-lg shadow-accent/10">
            <Terminal size={28} className="text-accent" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Sovereign AI</h1>
          <p className="text-text-muted text-sm mt-1">Local · Private · Agentic</p>
        </div>

        {/* Login card */}
        <div className="glass-card p-6 sm:p-8 space-y-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <ShieldCheck size={18} className="text-accent" />
            Connect to backend
          </div>
          <p className="text-xs text-text-muted leading-relaxed">
            Enter the API token configured on the server. If you started the server with
            <code className="font-mono text-accent mx-1">--api-token secret</code>, use that value here.
            Leave blank to connect without a token (only works if the server allows unauthenticated access).
          </p>

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-danger/10 border border-danger/20 text-xs text-danger">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
                <KeyRound size={13} /> API Token
              </label>
              <input
                type="text"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
                placeholder="secret"
                className="input-base w-full"
                autoFocus
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
                <Lock size={13} /> Admin Key <span className="text-text-muted">(optional)</span>
              </label>
              <input
                type="password"
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
                placeholder="admin secret"
                className="input-base w-full"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white font-semibold py-2.5 shadow-lg shadow-accent/25 transition-all disabled:opacity-60 active:scale-95"
            >
              {loading ? (
                <>Connecting…</>
              ) : (
                <>
                  <Unlock size={16} /> Connect
                </>
              )}
            </button>
          </form>

          <div className="pt-2 border-t border-border/60 space-y-2">
            <p className="text-[11px] text-text-muted leading-relaxed">
              Tokens are stored locally in your browser. The backend verifies them on every request.
              If you don’t have a token, leave it blank — the server may still allow public access.
            </p>
            <div className="flex items-center gap-3 text-xs">
              <Link href="/" className="text-accent hover:underline">Back to home</Link>
              <span className="text-text-muted">·</span>
              <span className="text-text-muted">v1.0 · Sovereign AI</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
