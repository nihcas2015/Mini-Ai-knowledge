'use client';

import { useEffect, useState } from 'react';
import ChatWindow from '@/components/ChatWindow';
import UploadPanel from '@/components/UploadPanel';
import SourceFilterToggle from '@/components/SourceFilterToggle';
import { createSession, endSession, SourceFilter } from '@/lib/api';

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('both');

  useEffect(() => {
    let activeSession: string | null = null;
    
    async function initSession() {
      try {
        const id = await createSession();
        setSessionId(id);
        activeSession = id;
      } catch (err) {
        console.error("Failed to create session", err);
      }
    }
    initSession();

    return () => {
      if (activeSession) {
        endSession(activeSession).catch(console.error);
      }
    };
  }, []);

  if (!sessionId) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg text-slate-500 animate-pulse">Initializing session...</div>
      </div>
    );
  }

  return (
    <main className="flex min-h-screen flex-col md:flex-row bg-slate-50">
      <div className="w-full md:w-80 border-r border-slate-200 bg-white p-4 flex flex-col gap-6">
        <div>
          <h2 className="text-xl font-bold mb-4 text-slate-800">RAG Assistant</h2>
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-2">Sources</h3>
            <SourceFilterToggle value={sourceFilter} onChange={setSourceFilter} />
          </div>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-2">Documents</h3>
          <UploadPanel sessionId={sessionId} />
        </div>
      </div>

      <div className="flex-1 flex flex-col h-screen">
        <ChatWindow sessionId={sessionId} sourceFilter={sourceFilter} />
      </div>
    </main>
  );
}
