'use client';

import { useEffect } from 'react';

export default function ErrorHandler() {
  useEffect(() => {
    const ignoredMessages = [
      'A listener indicated an asynchronous response by returning true',
    ];
    const handler = (event: ErrorEvent) => {
      if (event.message && ignoredMessages.some(m => event.message!.includes(m))) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener('error', handler);
    return () => {
      window.removeEventListener('error', handler);
    };
  }, []);

  return null;
}
