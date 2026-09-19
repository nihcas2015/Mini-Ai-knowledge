'use client';

import { Citation } from '@/lib/api';
import { FileText, Database } from 'lucide-react';

interface CitationBadgeProps {
  citation: Citation;
}

export default function CitationBadge({ citation }: CitationBadgeProps) {
  return (
    <span className="relative group inline-flex items-center align-middle mx-0.5">
      <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-accent text-[10px] font-bold text-white cursor-pointer hover:bg-accent-light transition-colors shadow-sm">
        {citation.marker}
      </span>

      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 rounded-lg bg-dark-800/95 backdrop-blur border border-dark-600 shadow-xl opacity-0 group-hover:opacity-100 pointer-events-none group-hover:pointer-events-auto transition-all duration-200 z-50 origin-bottom scale-95 group-hover:scale-100">
        <div className="flex items-center justify-between mb-2 pb-2 border-b border-dark-700/50">
          <div className="flex items-center gap-1.5 min-w-0">
            <FileText className="w-3 h-3 text-slate-400 shrink-0" />
            <span className="text-xs font-medium text-slate-200 truncate" title={citation.filename}>
              {citation.filename}
            </span>
          </div>
          {citation.source_type === 'base' ? (
            <span className="flex items-center gap-1 text-[10px] uppercase font-bold text-slate-400 shrink-0 bg-dark-900 px-1.5 py-0.5 rounded">
              <Database className="w-3 h-3" /> Base
            </span>
          ) : (
            <span className="flex items-center gap-1 text-[10px] uppercase font-bold text-accent shrink-0 bg-accent/10 px-1.5 py-0.5 rounded">
              <FileText className="w-3 h-3" /> User
            </span>
          )}
        </div>
        <div className="text-xs text-slate-300 leading-relaxed max-h-32 overflow-y-auto custom-scrollbar">
          &ldquo;{citation.snippet}&rdquo;
        </div>
        {citation.page_number && (
          <div className="mt-2 text-[10px] text-slate-500 text-right">
            Page {citation.page_number}
          </div>
        )}
        
        <span className="absolute top-full left-1/2 -translate-x-1/2 -mt-[1px] border-4 border-transparent border-t-dark-600" />
      </span>
    </span>
  );
}
