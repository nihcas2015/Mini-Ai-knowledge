'use client';

import React, { useState, useRef } from 'react';
import { UploadCloud, File as FileIcon, Trash2, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { uploadDocument, clearDocuments } from '@/lib/api';

interface UploadPanelProps {
  sessionId: string;
}

type FileStatus = 'uploading' | 'processing' | 'done' | 'error';

interface UploadedFile {
  id: string;
  name: string;
  status: FileStatus;
  error?: string;
}

export default function UploadPanel({ sessionId }: UploadPanelProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files));
    }
  };

  const handleFiles = async (selectedFiles: File[]) => {
    const pdfFiles = selectedFiles.filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    
    if (pdfFiles.length === 0) return;

    for (const file of pdfFiles) {
      const id = Math.random().toString(36).substring(7);
      
      setFiles((prev) => [...prev, { id, name: file.name, status: 'uploading' }]);

      try {
        setFiles((prev) => prev.map((f) => f.id === id ? { ...f, status: 'processing' } : f));
        await uploadDocument(sessionId, file);
        setFiles((prev) => prev.map((f) => f.id === id ? { ...f, status: 'done' } : f));
      } catch (err: any) {
        setFiles((prev) => prev.map((f) => f.id === id ? { ...f, status: 'error', error: err.message || 'Upload failed' } : f));
      }
    }
    
    if (fileInputRef.current) {
        fileInputRef.current.value = '';
    }
  };

  const handleClearAll = async () => {
    try {
      await clearDocuments(sessionId);
      setFiles([]);
    } catch (err) {
      console.error('Failed to clear documents', err);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div
        className={`relative border-2 border-dashed rounded-xl p-6 flex flex-col items-center justify-center text-center cursor-pointer transition-all duration-200
          ${isDragging ? 'border-accent bg-accent/10 shadow-[0_0_15px_rgba(99,102,241,0.2)]' : 'border-dark-600 hover:border-dark-500 hover:bg-dark-800/50'}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <UploadCloud className={`w-8 h-8 mb-3 ${isDragging ? 'text-accent' : 'text-slate-400'}`} />
        <p className="text-sm text-slate-300 font-medium mb-1">Click or drag PDF here</p>
        <p className="text-xs text-slate-500">PDFs only, up to 10MB</p>
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          accept="application/pdf"
          multiple
          onChange={handleFileInput}
        />
      </div>

      {files.length > 0 && (
        <div className="flex flex-col gap-3 mt-2">
          <div className="flex justify-between items-center">
            <span className="text-xs font-medium text-slate-500 uppercase">Uploaded Files</span>
            <button
              onClick={handleClearAll}
              className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1 transition-colors"
            >
              <Trash2 className="w-3 h-3" /> Clear All
            </button>
          </div>
          
          <div className="flex flex-col gap-2 max-h-[300px] overflow-y-auto pr-1">
            {files.map((file) => (
              <div key={file.id} className="bg-dark-800 rounded-lg p-3 border border-dark-700">
                <div className="flex items-center gap-3">
                  <FileIcon className="w-5 h-5 text-accent-light shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-300 truncate" title={file.name}>{file.name}</p>
                    
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1 flex-1 bg-dark-900 rounded-full overflow-hidden">
                        {(file.status === 'uploading' || file.status === 'processing') && (
                          <div className="h-full bg-accent shimmer w-full" />
                        )}
                        {file.status === 'done' && (
                          <div className="h-full bg-emerald-500 w-full" />
                        )}
                        {file.status === 'error' && (
                          <div className="h-full bg-red-500 w-full" />
                        )}
                      </div>
                      <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">
                        {file.status}
                      </span>
                    </div>
                    {file.status === 'error' && file.error && (
                        <p className="text-xs text-red-400 mt-1 truncate" title={file.error}>{file.error}</p>
                    )}
                  </div>
                  
                  <div className="shrink-0">
                    {file.status === 'uploading' || file.status === 'processing' ? (
                      <Loader2 className="w-4 h-4 text-accent animate-spin" />
                    ) : file.status === 'done' ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-red-500" />
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
