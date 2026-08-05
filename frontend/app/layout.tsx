import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { ToastProvider } from '@/components/providers/ToastProvider';
import { SidebarProvider } from '@/components/SidebarProvider';
import Sidebar from '@/components/layout/Sidebar';
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
  title: 'Sovereign-Agentic-AI',
  description: 'Local agentic LLM dashboard',
};

const themeScript = `
(function() {
  try {
    var t = localStorage.getItem('theme');
    if (t === 'light') {
      document.documentElement.classList.add('light');
      document.documentElement.classList.remove('dark');
    }
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
        <meta name="theme-color" content="#0F172A" />
      </head>
      <body className={`${inter.variable} font-sans bg-bg-primary text-text-primary transition-colors duration-200`}>
        <ThemeProvider>
          <SidebarProvider>
            <OfflineBanner />
            <ErrorHandler />
            <ToastProvider>
               <div className="flex h-[100dvh] overflow-hidden">
                <Sidebar />
                <main className="flex-1 overflow-y-auto scrollbar-thin">
                  <ErrorBoundary>
                    <PageTransition>
                      {children}
                    </PageTransition>
                  </ErrorBoundary>
                </main>
              </div>
            </ToastProvider>
          </SidebarProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
