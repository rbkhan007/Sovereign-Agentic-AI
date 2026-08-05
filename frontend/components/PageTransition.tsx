'use client';

import React, { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';

export default function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [displayChildren, setDisplayChildren] = useState(children);
  const [transitionStage, setTransitionStage] = useState('page-enter');
  const firstUpdate = useRef(true);

  useEffect(() => {
    if (firstUpdate.current) {
      firstUpdate.current = false;
      setTransitionStage('page-enter-active');
      return;
    }
    setTransitionStage('page-enter');
    const raf = requestAnimationFrame(() => {
      setDisplayChildren(children);
      setTransitionStage('page-enter-active');
    });
    return () => cancelAnimationFrame(raf);
  }, [pathname, children]);

  return (
    <div className={`${transitionStage} min-h-full`}>
      {displayChildren}
    </div>
  );
}
