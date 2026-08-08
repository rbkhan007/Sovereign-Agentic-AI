'use client';

import React, { useEffect } from 'react';
import { useAuth } from '@/components/auth/AuthProvider';
import { usePathname } from 'next/navigation';

export default function RouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated } = useAuth();

  useEffect(() => {
    if (!isAuthenticated && pathname !== '/login') {
      window.location.href = '/login';
    }
  }, [isAuthenticated, pathname]);

  return <>{children}</>;
}
