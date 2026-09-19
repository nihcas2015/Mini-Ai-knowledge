'use client';

import ReactMarkdown from 'react-markdown';
import { Citation } from '@/lib/api';
import CitationBadge from './CitationBadge';
import { Bot, User } from 'lucide-react';
import React from 'react';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
  provider?: string;
}

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  const components: Record<string, React.ComponentType<any>> = {
    p: ({ children, ...props }: any) => <p className="mb-4 last:mb-0 leading-relaxed" {...props}>{children}</p>,
    a: (props: any) => <a {...props} className="text-accent hover:underline" />,
  };

  const renderContent = () => {
    if (isUser) {
      return <div className="text-sm whitespace-pre-wrap">{message.content}</div>;
    }

    const citationRegex = /\[(\d+)\]/g;
    const parts = [];
    let lastIndex = 0;
    let match;

    while ((match = citationRegex.exec(message.content)) !== null) {
      if (match.index > lastIndex) {
        parts.push(
          <span key={`md-${lastIndex}`} className="prose prose-invert max-w-none text-sm inline">
            <ReactMarkdown components={components}>
              {message.content.slice(lastIndex, match.index)}
            </ReactMarkdown>
          </span>
        );
      }
      
      const citationId = parseInt(match[1], 10);
      const citation = message.citations?.find(c => c.marker === citationId);
      
      if (citation) {
        parts.push(<CitationBadge key={`cite-${match.index}`} citation={citation} />);
      } else {
        parts.push(<span key={`text-${match.index}`}>[{match[1]}]</span>);
      }
      
      lastIndex = citationRegex.lastIndex;
    }

    if (lastIndex < message.content.length) {
      parts.push(
        <span key={`md-${lastIndex}`} className="prose prose-invert max-w-none text-sm inline">
          <ReactMarkdown components={components}>
            {message.content.slice(lastIndex)}
          </ReactMarkdown>
        </span>
      );
    }

    return (
      <div className="flex-1 min-w-0">
        <div className="inline-block break-words w-full">
          {parts.length > 0 ? parts : (
            <div className="prose prose-invert max-w-none text-sm">
              <ReactMarkdown components={components}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
          {message.isStreaming && (
            <span className="inline-block w-2 h-4 ml-1 bg-slate-400 animate-pulse-slow align-middle" />
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={`flex w-full animate-slide-up ${isUser ? 'justify-end' : 'justify-start'} mb-6`}>
      <div className={`flex gap-4 max-w-[85%] ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center
          ${isUser ? 'bg-slate-700' : 'bg-gradient-to-br from-accent to-purple-600'}`}>
          {isUser ? <User className="w-4 h-4 text-slate-300" /> : <Bot className="w-4 h-4 text-white" />}
        </div>

        <div className={`flex flex-col gap-2 min-w-0
          ${isUser 
            ? 'bg-gradient-to-br from-indigo-600 to-purple-600 text-white rounded-2xl rounded-tr-sm px-5 py-3 shadow-lg shadow-indigo-900/20' 
            : 'bg-dark-800/60 backdrop-blur border border-dark-700/50 text-slate-200 rounded-2xl rounded-tl-sm px-5 py-4'
          }`}>
          {renderContent()}

          {!isUser && !message.isStreaming && (
            <div className="mt-2 pt-2 border-t border-dark-700/50 flex items-center justify-between">
              <span className="text-[10px] text-slate-500 font-medium">
                Mini AI Knowledge System • Built by Sachin
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
