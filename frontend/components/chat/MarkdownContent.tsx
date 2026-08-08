'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import { useTheme } from '@/components/ThemeProvider';
import CodeBlock from '@/components/chat/CodeBlock';

export default function MarkdownContent({ content }: { content: string }) {
  const { theme } = useTheme();
  return (
    <div className={`prose max-w-none prose-sm ${theme === 'dark' ? 'prose-invert' : ''}`}>
      <ReactMarkdown
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            const codeString = String(children).replace(/\n$/, '');
            const isInline = !match && !codeString.includes('\n');
            if (isInline) {
              return <code className="bg-bg-tertiary px-1.5 py-0.5 rounded text-accent text-xs font-mono" {...props}>{children}</code>;
            }
            return <CodeBlock code={codeString} language={match?.[1] || 'text'} />;
          },
          p({ children }) {
            return <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>;
          },
          ul({ children }) {
            return <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>;
          },
          a({ href, children }) {
            return <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-hover underline underline-offset-2">{children}</a>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
