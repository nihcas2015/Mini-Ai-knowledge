'use client';

import { useState, useRef } from 'react';
import { UploadCloud, File, Trash2, CheckCircle2, AlertCircle } from 'lucide-react';
import { uploadDocument, clearDocuments } from '@/lib/api';

interface UploadedFile {
  name: string;
  status: 'uploading' | 'success' | 'error';
  pages?: number;
  error?: string;
}

export default function UploadPanel({ sessionId }: { sessionId: string }) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (file.type !== 'application/pdf') {
      alert('Only PDF files are accepted');
      return;
    }
    
    if (file.size > 50 * 1024 * 1024) { 
      alert('File too large. Maximum size is 50MB.');
      return;
    }

    const fileState: UploadedFile = { name: file.name, status: 'uploading' };
    setFiles(prev => [...prev, fileState]);

    try {
      const res = await uploadDocument(sessionId, file);
      setFiles(prev => prev.map(f => 
        f.name === file.name 
          ? { ...f, status: res.status === 'success' ? 'success' : 'error', pages: res.pages_processed, error: res.reason }
          : f
      ));
    } catch (err: any) {
      setFiles(prev => prev.map(f =>
        f.name === file.name ? { ...f, status: 'error', error: err.message || 'Upload failed' } : f
      ));
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) handleFile(droppedFile);
  };

  const handleClear = async () => {
    if (!confirm('Are you sure you want to clear all your documents?')) return;
    try {
      await clearDocuments(sessionId);
      setFiles([]);
    } catch (err) {
      alert('Failed to clear documents');
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 p-4 rounded-xl border border-slate-200">
      <div 
        className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors cursor-pointer
          ${isDragging ? 'border-blue-500 bg-blue-50' : 'border-slate-300 hover:border-slate-400 bg-white'}`}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <input 
          type="file" 
          ref={fileInputRef} 
          className="hidden" 
          accept="application/pdf"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
            e.target.value = '';
          }}
        />
        <UploadCloud className="w-8 h-8 text-slate-400 mx-auto mb-2" />
        <p className="text-sm text-slate-600 font-medium">Click to upload or drag and drop</p>
        <p className="text-xs text-slate-400 mt-1">PDF only (max. 50MB)</p>
      </div>

      <div className="mt-4 flex-1 overflow-y-auto space-y-2">
        {files.map((file, i) => (
          <div key={i} className="flex items-center p-3 bg-white rounded-lg border border-slate-100 shadow-sm text-sm">
            <File className="w-4 h-4 text-slate-400 mr-3 shrink-0" />
            <div className="flex-1 truncate">
              <span className="font-medium text-slate-700 block truncate">{file.name}</span>
              {file.status === 'success' && <span className="text-xs text-slate-500">{file.pages} pages</span>}
              {file.status === 'error' && <span className="text-xs text-red-500">{file.error || 'Failed'}</span>}
            </div>
            {file.status === 'uploading' && <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin ml-2"></div>}
            {file.status === 'success' && <CheckCircle2 className="w-4 h-4 text-green-500 ml-2" />}
            {file.status === 'error' && <AlertCircle className="w-4 h-4 text-red-500 ml-2" />}
          </div>
        ))}
      </div>

      {files.length > 0 && (
        <button 
          onClick={handleClear}
          className="mt-4 w-full flex items-center justify-center gap-2 py-2 text-sm text-red-600 hover:bg-red-50 rounded-lg transition-colors border border-red-200 bg-white"
        >
          <Trash2 className="w-4 h-4" />
          Clear All
        </button>
      )}
    </div>
  );
}
