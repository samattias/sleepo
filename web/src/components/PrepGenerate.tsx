// Generate / Regenerate a meeting brief, optionally with Sam's own notes to steer it (topics, angle, documents, outcome).
// The meeting follow-up (actions after the meeting) uses it too, with its own labels.
import { useState } from 'react'
import { ChevronDown, RefreshCw, Sparkles } from 'lucide-react'
import { cn } from '@/lib/util'
import { DictateButton } from './Dictate'

export type GenerateLabels = { make: string; busy: string; heading: string; placeholder: string; hint: string; makeWith: string; redoWith: string }
const BRIEF: GenerateLabels = { make: 'Prepare brief', busy: 'Writing…', heading: 'Add context for this brief',
  placeholder: 'e.g. I want Jordan to commit to the team headcount by Friday. Focus on the budget, skip the roadmap. Read the org proposal deck. Priya may push back on the timeline.',
  hint: 'Topics, the outcome you want, people, documents to read, what to skip.', makeWith: 'Prepare with notes', redoWith: 'Regenerate with notes' }

export function PrepGenerate({ hasBrief, busy, onRun, lastNotes, labels = BRIEF }: { hasBrief: boolean; busy: boolean; onRun: (notes: string) => void; lastNotes?: string; labels?: GenerateLabels }) {
  const [open, setOpen] = useState(false)
  const [notes, setNotes] = useState(lastNotes ?? '')
  const label = busy ? labels.busy : hasBrief ? 'Regenerate' : labels.make
  const run = (n: string) => { onRun(n.trim()); setOpen(false) }
  // pills as in the Inbox (Sam, 22 Oct 2026): lime to make the first one, a soft grey pill to regenerate
  const half = hasBrief ? 'bg-panel2 text-ink hover:bg-line' : 'bg-accent text-onaccent hover:brightness-95'
  return (
    <div className="relative">
      <div className="flex">
        <button onClick={() => run('')} disabled={busy}
          className={cn('inline-flex items-center gap-1.5 rounded-l-full py-1 pl-3 pr-2.5 text-[12.5px] font-semibold transition-colors disabled:opacity-60', half)}>
          {busy ? <RefreshCw size={13} className="animate-spin" /> : <Sparkles size={13} />}{label}</button>
        <button onClick={() => setOpen(!open)} disabled={busy} aria-label={labels.heading} title={labels.heading}
          className={cn('ml-px rounded-r-full pl-1.5 pr-2.5 transition-colors disabled:opacity-60', half, open && hasBrief && 'bg-line')}>
          <ChevronDown size={14} className={cn('transition-transform', open && 'rotate-180')} /></button>
      </div>
      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-30 w-[min(440px,90vw)] rounded-xl border border-line bg-panel p-3 shadow-lg">
          <label htmlFor="prep-notes" className="mb-1.5 block text-[13px] font-semibold">{labels.heading}</label>
          <div className="relative" data-dictate>
          <textarea id="prep-notes" autoFocus value={notes} onChange={(e) => setNotes(e.target.value)} rows={5}
            placeholder={labels.placeholder}
            className="w-full resize-y rounded-lg border border-line bg-bg p-2.5 pr-10 text-[13px] leading-relaxed text-ink outline-none focus:border-ink" />
            <span className="absolute bottom-2 right-2"><DictateButton /></span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[12px] text-ink2">{labels.hint}</span>
            <button onClick={() => run(notes)} disabled={!notes.trim()} className="ml-auto inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full bg-accent px-3.5 py-1 text-[12.5px] font-semibold text-onaccent hover:brightness-95 disabled:opacity-50">
              <Sparkles size={14} />{hasBrief ? labels.redoWith : labels.makeWith}</button>
          </div>
        </div>
      )}
    </div>
  )
}
