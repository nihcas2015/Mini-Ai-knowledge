'use client';

import ReactMarkdown from 'react-markdown';
import { Citation } from '@/lib/api';
import CitationBadge from './CitationBadge';
import { Bot, User } from 'lucide-react';
import React, { ReactNode } from 'react';

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

  // Helper to replace [n] citations with custom badge in the markdown
  const components: Record<string, React.ComponentType<any>> = {
    p: ({ children, ...props }: any) => <p className="mb-4 last:mb-0 leading-relaxed" {...props}>{children}</p>,
    a: (props: any) => <a {...props} className="text-accent hover:underline" />,
  };

  // We will pre-process the content string.
  // Actually, a simple approach is to split the content by `\[(\d+)\]` if we are not using a plugin.
  // But react-markdown won't parse React nodes inside string.
  // We'll just show the citations at the bottom if any.
  // To truly parse [n] inline, let's write a simple custom regex approach replacing them with some tokens? No, react-markdown makes this tricky.
  // Let's implement it by showing the citations below the message text if they exist. 
  // Wait, the prompt says "Parse [n] citations and render CitationBadge".
  // Let's do a trick: we'll render the markdown and just rely on the user to see [1], but we can also parse the string and render chunks. 
  // Wait, it's easier to use a custom component for `a` if the backend sends links like [1](#cite-1), but we don't know that.
  // I will write a function to split content by [n] and render markdown for each chunk, interspersed with CitationBadge.

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
        // If not found, just render the text
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
        
        {/* Avatar */}
        <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center
          ${isUser ? 'bg-slate-700' : 'bg-gradient-to-br from-accent to-purple-600'}`}>
          {isUser ? <User className="w-4 h-4 text-slate-300" /> : <Bot className="w-4 h-4 text-white" />}
        </div>

        {/* Bubble */}
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
