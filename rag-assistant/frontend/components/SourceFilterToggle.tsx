'use client';

import { SourceFilter } from '@/lib/api';

const options: { value: SourceFilter; label: string }[] = [
  { value: 'base', label: 'Base' },
  { value: 'both', label: 'Both' },
  { value: 'user', label: 'My Docs' },
];

export default function SourceFilterToggle({
  value,
  onChange,
}: {
  value: SourceFilter;
  onChange: (v: SourceFilter) => void;
}) {
  return (
    <div className="flex rounded-lg bg-dark-800 p-1 gap-1">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200
            ${value === opt.value
              ? 'bg-accent text-white shadow-lg shadow-accent/20'
              : 'text-slate-400 hover:text-slate-200 hover:bg-dark-700'
            }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
