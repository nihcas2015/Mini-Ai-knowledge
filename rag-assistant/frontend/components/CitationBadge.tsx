'use client';

import { useState } from 'react';
import { FileText } from 'lucide-react';

interface Citation {
  filename: string;
  page_number: number;
  source_type: string;
  snippet: string;
}
import { Citation } from '@/lib/api';

export default function CitationBadge({ citation, marker }: { citation: Citation; marker: string }) {
  const [showPopover, setShowPopover] = useState(false);

  return (
    <span className="relative inline-block mx-1">
      <button
        onMouseEnter={() => setShowPopover(true)}
        onMouseLeave={() => setShowPopover(false)}
        className="inline-flex items-center justify-center w-5 h-5 text-xs font-semibold bg-blue-100 text-blue-700 rounded-full hover:bg-blue-200 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400"
      >
        {marker.replace(/[\[\]]/g, '')}
      </button>

      {showPopover && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 bg-slate-800 text-white text-sm rounded-lg shadow-xl z-50 animate-in fade-in zoom-in duration-200">
          <div className="flex items-start gap-2 mb-2 border-b border-slate-600 pb-2">
            <FileText className="w-4 h-4 text-slate-300 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate" title={citation.filename}>
                {citation.filename}
              </div>
              <div className="text-xs text-slate-400 flex justify-between">
                <span>Page {citation.page_number}</span>
                <span className="capitalize">{citation.source_type}</span>
              </div>
            </div>
          </div>
          <div className="text-slate-300 text-xs italic line-clamp-4">
            "{citation.snippet}"
          </div>
          <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-slate-800 rotate-45" />
        </div>
      )}
    </span>
  );
}
