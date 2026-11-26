// One compact filter control for every list page. By default it is a single quiet row: a search box (optional), a
// "Filters" button showing how many filters are on, and the active filters as small tokens you can remove. The filter
// options themselves (chips, selects) only appear when the button is clicked. A right-hand slot holds a count or a
// view switch. Use this instead of rows of chips. Rounded like every control (UI review, 30 Oct 2026: components/ui.tsx).
import { useState, type ReactNode } from 'react'
import { ChevronDown, Search, SlidersHorizontal, X } from 'lucide-react'
import { cn } from '@/lib/util'
import { Segmented as PillSwitch, inputClass } from './ui'

export type FilterToken = { label: string; onRemove: () => void }

export function FilterBar({ search, onSearch, placeholder = 'Search', tokens = [], onClear, right, children, className }: {
  search?: string; onSearch?: (v: string) => void; placeholder?: string; tokens?: FilterToken[]; onClear?: () => void
  right?: ReactNode; children?: ReactNode; className?: string
}) {
  const [open, setOpen] = useState(false)
  const n = tokens.length
  return (
    <div className={cn('mb-3', className)}>
      <div className="flex flex-wrap items-center gap-2">
        {onSearch && (
          <label className="relative block w-full sm:w-56">
            <Search size={13} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink3" />
            <input value={search ?? ''} onChange={(e) => onSearch(e.target.value)} placeholder={placeholder} aria-label={placeholder}
              className={cn(inputClass, 'w-full pl-7')} />
          </label>)}
        {children && (
          <button onClick={() => setOpen(!open)} aria-expanded={open}
            className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] font-medium', open || n ? 'border-ink text-ink' : 'border-line text-ink2 hover:border-ink hover:text-ink')}>
            <SlidersHorizontal size={13} aria-hidden />Filters{n > 0 && <span className="grid size-4 place-items-center rounded-full bg-accent text-[10.5px] font-semibold text-onaccent">{n}</span>}
            <ChevronDown size={12} aria-hidden className={cn('transition-transform', open && 'rotate-180')} />
          </button>)}
        {tokens.map((t) => (
          <span key={t.label} className="inline-flex items-center gap-1 rounded-full border border-line py-px pl-2 pr-1 text-[12px]">
            {t.label}<button onClick={t.onRemove} aria-label={`Remove ${t.label}`} className="grid size-4 place-items-center rounded-full text-ink2 hover:bg-panel2 hover:text-ink"><X size={11} /></button>
          </span>))}
        {n > 1 && onClear && <button onClick={onClear} className="text-[12px] text-ink2 underline-offset-2 hover:text-ink hover:underline">Clear</button>}
        {right && <div className="ml-auto flex items-center gap-2 text-[12.5px] text-ink2">{right}</div>}
      </div>
      {open && children && <div className="mt-2 space-y-2 border border-line bg-panel px-3 py-2.5">{children}</div>}
    </div>
  )
}

// A labelled row inside the filter panel.
export function FilterRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-[84px] shrink-0 text-[12px] text-ink2">{label}</span>
      {children}
    </div>
  )
}

// A small option button for the filter panel (lighter than Chip).
export function Opt({ on, onClick, children, count }: { on?: boolean; onClick: () => void; children: ReactNode; count?: number }) {
  return (
    <button onClick={onClick} className={cn('rounded-full border px-2 py-px text-[12px]', on ? 'border-ink bg-ink text-bg' : 'border-line text-ink hover:border-ink')}>
      {children}{count != null && <span className={cn('ml-1', on ? 'opacity-70' : 'text-ink3')}>{count}</span>}
    </button>
  )
}

// A compact segmented switch for views (Timeline / List…): always visible, it is not a filter. The same pill switch as
// everywhere else (components/ui.tsx Segmented); kept here so the pages that import it from FilterBar need no change.
export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return <PillSwitch value={value} onChange={onChange} options={options} />
}
