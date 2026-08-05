'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, MessageSquare, FolderOpen, Database, Cpu, Wrench, Shield, Settings, HelpCircle, Sun, Moon, ChevronLeft, ChevronRight, Wifi, WifiOff, X, GitBranch, Menu, type LucideIcon } from 'lucide-react';
import { useTheme } from '@/components/ThemeProvider';
import { useSidebar } from '@/components/SidebarProvider';
import { fetchJSON } from '@/lib/api';

type NavItem = { href: string; label: string; icon: LucideIcon };

const navGroups: { label: string; items: NavItem[] }[] = [
  {
    label: 'Overview',
    items: [
      { href: '/', label: 'Dashboard', icon: Activity },
      { href: '/chat', label: 'Chat', icon: MessageSquare },
    ],
  },
  {
    label: 'Data',
    items: [
      { href: '/workspace', label: 'Workspace', icon: FolderOpen },
      { href: '/database', label: 'Database', icon: Database },
      { href: '/graph', label: 'Knowledge Graph', icon: GitBranch },
    ],
  },
  {
    label: 'System',
    items: [
      { href: '/models', label: 'Models', icon: Cpu },
      { href: '/tools', label: 'Tools', icon: Wrench },
      { href: '/admin', label: 'Admin', icon: Shield },
      { href: '/settings', label: 'Settings', icon: Settings },
    ],
  },
];

const footerItems = [
  { href: '/help', label: 'Help & Guide', icon: HelpCircle },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const { open: mobileOpen, setOpen: setMobileOpen } = useSidebar();
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    try { return localStorage.getItem('sidebar_collapsed') === 'true'; } catch { return false; }
  });
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    try { localStorage.setItem('sidebar_collapsed', String(collapsed)); } catch { /* ignore */ }
  }, [collapsed]);

  useEffect(() => {
    let mounted = true;
    async function check() {
      try {
        await fetchJSON('/v1/health', { timeout: 3000 });
        if (mounted) setOnline(true);
      } catch {
        if (mounted) setOnline(false);
      }
    }
    check();
    const interval = setInterval(check, 15000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  const sidebarContent = (
    <>
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2.5">
          {!collapsed ? (
            <>
              <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white text-sm font-bold shadow-lg shadow-accent/30 shrink-0">A</span>
              <div className="min-w-0">
                <h1 className="text-sm font-bold tracking-tight gradient-text truncate">Agentic LLM</h1>
                <p className="text-[10px] text-text-muted">Local · Fast · Private</p>
              </div>
            </>
          ) : (
            <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white text-sm font-bold shadow-lg shadow-accent/30 mx-auto">A</span>
          )}
        </div>
      </div>

      <nav id="sidebar" className="flex-1 px-2 py-3 overflow-y-auto scrollbar-thin">
        {navGroups.map(group => (
          <div key={group.label} className="mb-4 last:mb-0">
            {!collapsed && (
              <p className="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-text-muted">{group.label}</p>
            )}
            <div className="space-y-0.5">
              {group.items.map(item => {
                const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMobileOpen(false)}
                    className={`relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
                      isActive
                        ? 'text-accent bg-accent-soft border border-accent/20'
                        : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary border border-transparent'
                    }`}
                    title={collapsed ? item.label : undefined}
                  >
                    {isActive && !collapsed && (
                      <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-full bg-accent" />
                    )}
                    <Icon size={18} className={`shrink-0 ${isActive ? 'text-accent' : ''}`} />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="p-3 border-t border-border space-y-1">
        {footerItems.map(item => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
                isActive ? 'text-accent bg-accent-soft border border-accent/20' : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary border border-transparent'
              }`}
              title={collapsed ? item.label : undefined}
            >
              <Icon size={18} className={`shrink-0 ${isActive ? 'text-accent' : ''}`} />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
        <button
          onClick={toggle}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? <Sun size={18} className="shrink-0" /> : <Moon size={18} className="shrink-0" />}
          {!collapsed && <span>{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>}
        </button>
        <div className="flex items-center gap-2.5 text-xs text-text-muted px-3 pt-1">
          {online === true ? <Wifi size={14} className="text-success shrink-0" /> : <WifiOff size={14} className="text-danger shrink-0" />}
          {!collapsed && <span className="truncate">{online === true ? 'Backend connected' : online === false ? 'Backend offline' : 'Checking...'}</span>}
        </div>
        {!collapsed && (
          <p className="text-[10px] text-text-muted/70 px-3 pt-1 pb-0.5">Built by Rhasan</p>
        )}
      </div>
    </>
  );

  return (
    <>
      {/* Mobile menu trigger (only when the drawer is closed) */}
      {!mobileOpen && (
        <button
          onClick={() => setMobileOpen(true)}
          className="lg:hidden fixed top-3 left-3 z-30 p-2 rounded-lg bg-bg-secondary/80 backdrop-blur border border-border text-text-primary hover:text-text-accent transition-colors"
          aria-label="Open menu"
        >
          <Menu size={20} />
        </button>
      )}

      {/* Desktop sidebar */}
      <aside className={`hidden lg:flex relative bg-bg-secondary/70 backdrop-blur-lg border-r border-border flex-col transition-all duration-300 ${collapsed ? 'w-16' : 'w-64'}`}>
        {sidebarContent}
        <button
          onClick={() => setCollapsed(v => !v)}
          className="absolute -right-3 top-24 z-10 p-1.5 rounded-full bg-bg-secondary border border-border text-text-secondary hover:text-text-primary shadow-md hover:border-accent/30 transition-all"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </aside>

      {/* Mobile sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64 animate-slide-in">
            <div className="bg-bg-secondary border-r border-border h-full flex flex-col">
              {sidebarContent}
            </div>
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute top-4 right-4 p-2 rounded-lg bg-bg-secondary border border-border text-text-primary"
              aria-label="Close menu"
            >
              <X size={20} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
