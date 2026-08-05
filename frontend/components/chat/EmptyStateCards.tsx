'use client';

import React from 'react';
import { Code2, Database, TestTube, BookOpen, Sparkles, Search, PenLine, Wand2 } from 'lucide-react';

export interface WorkflowCard {
  title: string;
  description: string;
  icon: React.ReactNode;
  prompt: string;
  modelId?: string;
  agentName?: string;
  accentClass?: string;
}

const defaultCards: WorkflowCard[] = [
  {
    title: 'Refactor Code',
    description: 'Clean up structure, naming & performance',
    icon: <Code2 size={18} />,
    prompt: 'Refactor the following code for clarity, better structure, and performance. Explain the key changes:\n',
    accentClass: 'text-accent',
  },
  {
    title: 'Generate Unit Tests',
    description: 'Cover edge cases with assertions',
    icon: <TestTube size={18} />,
    prompt: 'Write comprehensive unit tests for the code below, covering happy paths and edge cases:\n',
    accentClass: 'text-accent-3',
  },
  {
    title: 'Analyze Vector DB',
    description: 'Inspect schema, indexes & recall',
    icon: <Database size={18} />,
    prompt: 'Analyze this vector database setup (schema, indexes, embedding dimension, and recall strategy) and suggest improvements:\n',
    agentName: '',
    accentClass: 'text-accent-2',
  },
  {
    title: 'Explain & Summarize',
    description: 'Plain-language breakdown',
    icon: <BookOpen size={18} />,
    prompt: 'Explain the following concept in simple terms and summarize the key takeaways:\n',
    accentClass: 'text-blue-400',
  },
  {
    title: 'Deep Research',
    description: 'Multi-step reasoning with planning',
    icon: <Search size={18} />,
    prompt: 'Research this topic thoroughly and give me a structured answer with sources and trade-offs:\n',
    agentName: '',
    accentClass: 'text-yellow-400',
  },
  {
    title: 'Creative Draft',
    description: 'Brainstorm & write with flair',
    icon: <PenLine size={18} />,
    prompt: 'Help me draft a creative piece on the following idea. Make it engaging:\n',
    accentClass: 'text-fuchsia-400',
  },
];

interface EmptyStateCardsProps {
  cards?: WorkflowCard[];
  onSelect: (card: WorkflowCard) => void;
}

export default function EmptyStateCards({ cards = defaultCards, onSelect }: EmptyStateCardsProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center animate-fade-in px-4">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center text-white mb-5 shadow-lg shadow-accent/30">
        <Sparkles size={30} />
      </div>
      <h2 className="text-xl font-semibold mb-1.5 gradient-text">How can I help you?</h2>
      <p className="text-text-secondary text-sm mb-7 max-w-md">
        Pick a workflow to start, or just type below. Use <span className="font-mono text-accent">/</span> for commands and{' '}
        <span className="font-mono text-accent">@</span> to attach workspace context.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 max-w-3xl w-full">
        {cards.map((card) => (
          <button
            key={card.title}
            onClick={() => onSelect(card)}
            className="group text-left bg-bg-secondary/60 border border-border rounded-xl p-4 hover:border-accent/40 hover:-translate-y-0.5 transition-all hover:shadow-md flex flex-col gap-2"
          >
            <div className={`w-9 h-9 rounded-lg bg-bg-tertiary flex items-center justify-center ${card.accentClass || 'text-accent'}`}>
              {card.icon}
            </div>
            <div>
              <div className="text-sm font-semibold text-text-primary flex items-center gap-1.5">
                {card.title}
                <Wand2 size={12} className="opacity-0 group-hover:opacity-100 text-accent transition-opacity" />
              </div>
              <div className="text-xs text-text-muted">{card.description}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
