declare module 'react-syntax-highlighter' {
  import React from 'react';
  export interface PrismProps {
    language: string;
    style?: Record<string, React.CSSProperties> | React.CSSProperties;
    children: string;
    showLineNumbers?: boolean;
    wrapLines?: boolean;
    customStyle?: React.CSSProperties;
    PreTag?: string | React.FC;
    [key: string]: unknown;
  }
  export const Prism: React.FC<PrismProps>;
}
