'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Loader2 } from 'lucide-react';
import MessageBubble from './MessageBubble';
import { askQuestion } from '@/lib/api';

interface Citation {
  marker: string;
  filename: string;
  page_number: number;
  source_type: string;
  snippet: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  provider_used?: string;
  isStreaming?: boolean;
}

export default function ChatWindow({ 
  sessionId, 
  sourceFilter 
}: { 
  sessionId: string;
  sourceFilter: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    const assistantId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: assistantId, role: 'assistant', content: '', isStreaming: true }]);
    
    await askQuestion(
      sessionId,
      userMessage.content,
      (token) => {
        setMessages(prev => prev.map(msg => 
          msg.id === assistantId ? { ...msg, content: msg.content + token } : msg
        ));
      },
      (finalData) => {
        setMessages(prev => prev.map(msg => 
          msg.id === assistantId ? { 
            ...msg, 
            content: finalData.answer || msg.content, 
            citations: finalData.citations, 
            provider_used: finalData.provider_used,
            isStreaming: false 
          } : msg
        ));
        setIsLoading(false);
      },
      (error) => {
        setMessages(prev => prev.map(msg => 
          msg.id === assistantId ? { ...msg, content: 'Error: Failed to get response. ' + error.message, isStreaming: false } : msg
        ));
        setIsLoading(false);
      }
    );
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 relative overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 scrollbar-hide">
        {messages.length === 0 ? (
          <div className="text-center text-slate-400 mt-20">
            <h2 className="text-2xl font-semibold mb-2 text-slate-600">How can I help you today?</h2>
            <p>Upload documents and ask questions based on them.</p>
          </div>
        ) : (
          messages.map(msg => (
            <MessageBubble key={msg.id} message={msg} />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      
      <div className="p-4 bg-white border-t border-slate-200 sticky bottom-0">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto relative flex items-center">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question..."
            disabled={isLoading}
            className="w-full px-4 py-3 pr-12 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="absolute right-2 p-2 rounded-lg bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
          </button>
        </form>
      </div>
    </div>
  );
}
