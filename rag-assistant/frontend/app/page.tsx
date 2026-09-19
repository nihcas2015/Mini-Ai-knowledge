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
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  const initSession = async () => {
    try {
      setError(null);
      setRetrying(true);
      const id = await createSession();
      setSessionId(id);
    } catch (err: any) {
      console.error('Failed to create session', err);
      setError(err?.message || 'Could not connect to the backend server.');
    } finally {
      setRetrying(false);
    }
  };

  useEffect(() => {
    initSession();

    return () => {
      if (sessionId) {
        endSession(sessionId).catch(() => {});
      }
    };
  }, []);

  if (!sessionId) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-dark-950 p-4">
        <ParticleBackground />
        <div className="relative z-10 flex flex-col items-center gap-4 max-w-md text-center">
          {error ? (
            <div className="bg-dark-900/90 border border-red-500/30 rounded-2xl p-6 backdrop-blur shadow-2xl flex flex-col items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-red-500/10 text-red-400 flex items-center justify-center text-xl font-bold">
                !
              </div>
              <div>
                <h2 className="text-white font-semibold mb-1">Connection Failed</h2>
                <p className="text-slate-400 text-xs leading-relaxed">{error}</p>
              </div>
              <button
                onClick={initSession}
                disabled={retrying}
                className="px-5 py-2 bg-accent hover:bg-accent-dark text-white rounded-xl text-xs font-semibold transition-all shadow-lg shadow-accent/25 disabled:opacity-50"
              >
                {retrying ? 'Retrying...' : 'Retry Connection'}
              </button>
            </div>
          ) : (
            <>
              <div className="w-12 h-12 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              <p className="text-slate-400 text-sm">Initializing session...</p>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-dark-950">
      <ParticleBackground />

      <aside className="relative z-10 w-80 flex-shrink-0 border-r border-dark-700/50 bg-dark-900/80 backdrop-blur-xl flex flex-col">
        <div className="p-6 border-b border-dark-700/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-purple-600 flex items-center justify-center">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">Mini AI Knowledge</h1>
              <p className="text-xs text-slate-500">Built by Sachin</p>
            </div>
          </div>
        </div>

        <div className="p-4 border-b border-dark-700/50">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Source</p>
          <SourceFilterToggle value={sourceFilter} onChange={setSourceFilter} />
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Documents</p>
          <UploadPanel sessionId={sessionId} />
        </div>
      </aside>

      <main className="relative z-10 flex-1 flex flex-col h-screen">
        <ChatWindow sessionId={sessionId} sourceFilter={sourceFilter} />
      </main>
    </div>
  );
}
