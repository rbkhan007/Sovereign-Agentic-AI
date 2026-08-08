'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { loadAuth, saveAuth, clearAuth, type AuthState } from '@/lib/auth';
import { fetchJSON } from '@/lib/api';

type AuthContextValue = {
  auth: AuthState;
  login: (apiToken: string, adminKey?: string) => Promise<boolean>;
  logout: () => void;
  isAuthenticated: boolean;
};

const AuthContext = createContext<AuthContextValue>({
  auth: { apiToken: '', adminKey: '', isAuthenticated: false },
  login: async () => false,
  logout: () => {},
  isAuthenticated: false,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(loadAuth);

  useEffect(() => {
    const handler = () => setAuth(loadAuth());
    window.addEventListener('storage', handler);
    return () => window.removeEventListener('storage', handler);
  }, []);

  const login = useCallback(async (apiToken: string, adminKey = ''): Promise<boolean> => {
    try {
      const res = await fetchJSON('/v1/health', {
        headers: {
          'Content-Type': 'application/json',
          ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
          ...(adminKey ? { 'X-Admin-Key': adminKey } : {}),
        },
        timeout: 8000,
      });
      if ((res as Record<string, unknown>).status === 'healthy' || (res as Record<string, unknown>).status === 'ok') {
        const next = { apiToken, adminKey, isAuthenticated: true };
        saveAuth(next);
        if (typeof window !== 'undefined') {
          (window as unknown as Record<string, string | undefined>).API_TOKEN = apiToken;
          (window as unknown as Record<string, string | undefined>).ADMIN_KEY = adminKey;
        }
        setAuth(next);
        return true;
      }
    } catch { /* ignore */ }
    return false;
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    if (typeof window !== 'undefined') {
      delete (window as unknown as Record<string, string | undefined>).API_TOKEN;
      delete (window as unknown as Record<string, string | undefined>).ADMIN_KEY;
    }
    setAuth({ apiToken: '', adminKey: '', isAuthenticated: false });
  }, []);

  return (
    <AuthContext.Provider value={{ auth, login, logout, isAuthenticated: auth.isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
