'use client';

import { useEffect, useState } from 'react';
import ChatWindow from '@/components/ChatWindow';
import UploadPanel from '@/components/UploadPanel';
import SourceFilterToggle from '@/components/SourceFilterToggle';
import ParticleBackground from '@/components/ParticleBackground';
import { createSession, endSession, SourceFilter } from '@/lib/api';
import { Brain } from 'lucide-react';

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('both');

  useEffect(() => {
    let activeSession: string | null = null;
    const initSession = async () => {
      try {
        const id = await createSession();
        setSessionId(id);
        activeSession = id;
      } catch (err) {
        console.error('Failed to create session', err);
      }
    };
    initSession();

    return () => {
      if (activeSession) {
        endSession(activeSession).catch(() => {});
      }
    };
  }, []);

  if (!sessionId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-dark-950">
        <ParticleBackground />
        <div className="relative z-10 flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          <p className="text-slate-400 text-sm">Initializing session...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-dark-950">
      <ParticleBackground />

      {/* Sidebar */}
      <aside className="relative z-10 w-80 flex-shrink-0 border-r border-dark-700/50 bg-dark-900/80 backdrop-blur-xl flex flex-col">
        {/* Logo */}
        <div className="p-6 border-b border-dark-700/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-purple-600 flex items-center justify-center">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">AI Knowledge</h1>
              <p className="text-xs text-slate-500">Document-powered Q&A</p>
            </div>
          </div>
        </div>

        {/* Source Filter */}
        <div className="p-4 border-b border-dark-700/50">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Source</p>
          <SourceFilterToggle value={sourceFilter} onChange={setSourceFilter} />
        </div>

        {/* Upload Panel */}
        <div className="flex-1 overflow-y-auto p-4">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Documents</p>
          <UploadPanel sessionId={sessionId} />
        </div>
      </aside>

      {/* Main Chat */}
      <main className="relative z-10 flex-1 flex flex-col h-screen">
        <ChatWindow sessionId={sessionId} sourceFilter={sourceFilter} />
      </main>
    </div>
  );
}
