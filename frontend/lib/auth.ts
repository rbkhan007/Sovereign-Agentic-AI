/** Client-side auth state: API token + admin key + login/logout. */

export interface AuthState {
  apiToken: string;
  adminKey: string;
  isAuthenticated: boolean;
}

export const AUTH_KEY = 'sovereign_auth';
export const ADMIN_KEY_KEY = 'sovereign_admin_key';

export function loadAuth(): AuthState {
  if (typeof window === 'undefined') return { apiToken: '', adminKey: '', isAuthenticated: false };
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    if (raw) {
      const data = JSON.parse(raw) as AuthState;
      if (data.apiToken) return data;
    }
  } catch { /* ignore */ }
  return { apiToken: '', adminKey: '', isAuthenticated: false };
}

export function saveAuth(state: AuthState): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(AUTH_KEY, JSON.stringify(state));
  } catch { /* ignore */ }
}

export function clearAuth(): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(AUTH_KEY);
  } catch { /* ignore */ }
}
