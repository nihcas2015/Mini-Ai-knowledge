'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Citation } from '@/lib/api';
import CitationBadge from './CitationBadge';
import { Bot, User } from 'lucide-react';

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

  const processedContent = React.useMemo(() => {
    if (isUser) return message.content;
    // Map [1], [2] to [1](#cite-1) so markdown tables, lists, and blocks stay 100% syntactically valid
    return message.content.replace(/\[(\d+)\]/g, '[$1](#cite-$1)');
  }, [message.content, isUser]);

  const components: Record<string, React.ComponentType<any>> = {
    p: ({ children, ...props }: any) => (
      <p className="mb-3 last:mb-0 leading-relaxed text-sm" {...props}>{children}</p>
    ),
    a: ({ href, children, ...props }: any) => {
      if (href && href.startsWith('#cite-')) {
        const marker = parseInt(href.replace('#cite-', ''), 10);
        const citation = message.citations?.find(c => c.marker === marker);
        if (citation) {
          return <CitationBadge citation={citation} />;
        }
        return (
          <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-slate-700 text-[10px] font-medium text-slate-300 mx-0.5 align-middle">
            {children}
          </span>
        );
      }
      return (
        <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline" {...props}>
          {children}
        </a>
      );
    },
    table: ({ children }: any) => (
      <div className="overflow-x-auto my-3 rounded-lg border border-dark-700">
        <table className="min-w-full divide-y divide-dark-700 text-xs text-left">
          {children}
        </table>
      </div>
    ),
    thead: ({ children }: any) => (
      <thead className="bg-dark-800/80 text-slate-200 font-semibold">{children}</thead>
    ),
    tbody: ({ children }: any) => (
      <tbody className="divide-y divide-dark-700/50 bg-dark-900/30">{children}</tbody>
    ),
    th: ({ children }: any) => (
      <th className="px-3 py-2 text-slate-300 font-semibold border-b border-dark-700">{children}</th>
    ),
    td: ({ children }: any) => (
      <td className="px-3 py-2 text-slate-300 border-b border-dark-700/50 align-top">{children}</td>
    ),
    code: ({ children, className, ...props }: any) => (
      <code className="bg-dark-900/90 text-indigo-300 px-1.5 py-0.5 rounded text-xs font-mono border border-dark-700/40" {...props}>
        {children}
      </code>
    ),
  };

  const renderContent = () => {
    if (isUser) {
      return <div className="text-sm whitespace-pre-wrap">{message.content}</div>;
    }

    return (
      <div className="flex-1 min-w-0">
        <div className="inline-block break-words w-full prose prose-invert max-w-none text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {processedContent}
          </ReactMarkdown>
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
            <div className="mt-2 pt-2 border-t border-dark-700/50 flex items-center justify-between gap-3">
              <span className="text-[10px] text-slate-500 font-medium">
                Mini AI Knowledge System • Built by Sachin
              </span>
              {(!message.citations || message.citations.length === 0) ? (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400/90 border border-amber-500/20 tracking-wide">
                  LLM Reply
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-500/10 text-indigo-300/90 border border-indigo-500/20 tracking-wide">
                  Grounded • {message.citations.length} {message.citations.length === 1 ? 'source' : 'sources'}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
