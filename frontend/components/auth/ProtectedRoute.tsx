'use client';

import React from 'react';
import { useAuth } from '@/components/auth/AuthProvider';
import Link from 'next/link';

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center space-y-4">
          <p className="text-text-muted text-sm">Please sign in to continue.</p>
          <Link href="/login" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-accent to-accent-hover hover:from-accent-hover hover:to-accent text-white shadow-lg shadow-accent/25 transition-all">
            Go to Login
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
