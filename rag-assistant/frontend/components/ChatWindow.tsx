'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Send, Brain, Loader2 } from 'lucide-react';
import { SourceFilter, askQuestion, AskResult } from '@/lib/api';
import MessageBubble, { Message } from './MessageBubble';

interface ChatWindowProps {
  sessionId: string;
  sourceFilter: SourceFilter;
}

export default function ChatWindow({ sessionId, sourceFilter }: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isAsking, setIsAsking] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isAsking) return;

    const userMessage: Message = {
      id: Math.random().toString(36).substring(7),
      role: 'user',
      content: input.trim(),
    };

    const assistantMessageId = Math.random().toString(36).substring(7);
    const initialAssistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      isStreaming: true,
    };

    setMessages((prev) => [...prev, userMessage, initialAssistantMessage]);
    setInput('');
    setIsAsking(true);

    try {
      await askQuestion(
        sessionId,
        userMessage.content,
        sourceFilter,
        (token) => {
          setMessages((prev) => 
            prev.map((msg) => 
              msg.id === assistantMessageId 
                ? { ...msg, content: msg.content + token }
                : msg
            )
          );
        },
        (result: AskResult) => {
          setMessages((prev) => 
            prev.map((msg) => 
              msg.id === assistantMessageId 
                ? { 
                    ...msg, 
                    content: result.answer, 
                    citations: result.citations,
                    provider: result.provider_used,
                    isStreaming: false 
                  }
                : msg
            )
          );
          setIsAsking(false);
        },
        (error) => {
          console.error(error);
          setMessages((prev) => 
            prev.map((msg) => 
              msg.id === assistantMessageId 
                ? { ...msg, content: msg.content + '\n\n**Error:** ' + error.message, isStreaming: false }
                : msg
            )
          );
          setIsAsking(false);
        }
      );
    } catch (err: any) {
      setMessages((prev) => 
        prev.map((msg) => 
          msg.id === assistantMessageId 
            ? { ...msg, content: '**Error:** ' + err.message, isStreaming: false }
            : msg
        )
      );
      setIsAsking(false);
    }
  };

  return (
    <div className="flex flex-col h-full relative">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-6 scroll-smooth custom-scrollbar">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto animate-fade-in">
            <div className="w-16 h-16 rounded-2xl bg-dark-800/80 border border-dark-700/50 flex items-center justify-center mb-6 shadow-xl backdrop-blur">
              <Brain className="w-8 h-8 text-accent-light" />
            </div>
            <h2 className="text-xl font-bold text-slate-200 mb-2">How can I help you today?</h2>
            <p className="text-sm text-slate-400">
              Upload a document on the left and ask me anything about it. I'll provide answers with citations!
            </p>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto w-full">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="p-4 bg-dark-800/80 backdrop-blur border-t border-dark-700/50">
        <div className="max-w-3xl mx-auto">
          <form onSubmit={handleSubmit} className="relative flex items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question..."
              disabled={isAsking}
              className="w-full bg-dark-900/50 border border-dark-600 rounded-xl py-3 pl-4 pr-12 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || isAsking}
              className="absolute right-2 p-1.5 rounded-lg bg-accent text-white hover:bg-accent-light transition-colors disabled:opacity-50 disabled:hover:bg-accent flex items-center justify-center"
            >
              {isAsking ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </form>
          <div className="text-center mt-2">
            <span className="text-[10px] text-slate-500">AI can make mistakes. Verify information with the provided citations.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
