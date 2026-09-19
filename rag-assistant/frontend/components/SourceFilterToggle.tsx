'use client';

type FilterType = 'base' | 'user' | 'both';

export default function SourceFilterToggle({ 
  value, 
  onChange 
}: { 
  value: FilterType; 
  onChange: (val: FilterType) => void;
}) {
  return (
    <div className="flex p-1 bg-slate-200/60 rounded-lg w-full">
      {(['base', 'both', 'user'] as FilterType[]).map((type) => (
        <button
          key={type}
          onClick={() => onChange(type)}
          className={`flex-1 text-xs font-medium py-1.5 px-2 rounded-md capitalize transition-all
            ${value === type 
              ? 'bg-white text-slate-900 shadow-sm' 
              : 'text-slate-500 hover:text-slate-700'
            }`}
        >
          {type}
        </button>
      ))}
    </div>
  );
}
