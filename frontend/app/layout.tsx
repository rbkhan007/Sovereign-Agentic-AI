import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { ToastProvider } from '@/components/providers/ToastProvider';
import { SidebarProvider } from '@/components/SidebarProvider';
import Sidebar from '@/components/layout/Sidebar';
import SystemStatusBar from '@/components/layout/SystemStatusBar';
import OfflineBanner from '@/components/OfflineBanner';
import PageTransition from '@/components/PageTransition';
import { ThemeProvider } from '@/components/ThemeProvider';
import ErrorBoundary from '@/components/ErrorBoundary';
import ErrorHandler from '@/components/ErrorHandler';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export const metadata: Metadata = {
  title: {
    default: 'Sovereign-Agentic-AI',
    template: '%s · Sovereign-Agentic-AI',
  },
  description:
    'A private, offline-first multi-agent AI operating system — runs GGUF models 100% locally on your GPU with an Agentic Terminal, knowledge graph, workspaces, computer vision and image generation.',
  keywords: [
    'local LLM', 'multi-agent', 'GGUF', 'Vulkan', 'pgvector', 'knowledge graph',
    'Agentic Terminal', 'AI workspace', 'offline AI', 'RAG', 'Agent X',
  ],
  authors: [{ name: 'Rakibul Hasan', url: 'https://github.com/rbkhan007' }],
  applicationName: 'Sovereign-Agentic-AI',
};

const themeScript = `
(function() {
  try {
    var t = localStorage.getItem('theme');
    if (t !== 'light' && t !== 'dark') {
      t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    var el = document.documentElement;
    el.classList.remove('light', 'dark');
    el.classList.add(t);
    if (t === 'dark') { localStorage.setItem('theme', 'dark'); }
  } catch(e) {}
})()
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" sizes="any" />
        <link rel="apple-touch-icon" href="/favicon.svg" />
        <meta name="theme-color" content="#C9122B" />
      </head>
      <body className={`${inter.variable} font-sans bg-bg-primary text-text-primary transition-colors duration-200`}>
        <ThemeProvider>
          <SidebarProvider>
            <OfflineBanner />
            <ErrorHandler />
            <ToastProvider>
               <div className="app-viewport-wrapper">
                <Sidebar />
                <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
                  <SystemStatusBar />
                  <div className="main-content-canvas">
                    <ErrorBoundary>
                      <PageTransition>
                        {children}
                      </PageTransition>
                    </ErrorBoundary>
                  </div>
                </main>
              </div>
            </ToastProvider>
          </SidebarProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
