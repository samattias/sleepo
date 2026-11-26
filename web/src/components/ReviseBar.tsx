// Changing a draft email (Sam, 28 Oct 2026: "I click revise this draft and then it doesn't really change anything"). A box
// under the draft card, outside its dashed edge (the card holds only the email; Sam, 28 Oct: inside it was too cluttered): say what should change
// (or click a quick ask, which revises at once). Two equal buttons at the end of the box (Sam, 16 Nov 2026: "Write a new one"
// was a faint link under the box; "submit, which is to write an edit to the existing draft, and write a new one which starts
// one from scratch ... make these two options equivalent"): Revise changes the text on screen (Enter; needs a request), Write
// new starts again from the thread, with the words in the box if any (⌘Enter). After a revision, RevisedStrip says what
// changed, with Draft / Changes and Undo. Used by the Inbox reply composer and the Drafts editor (assist/revise.py on the server).
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowUp, MessageSquare, RefreshCw, RotateCcw, Sparkles } from 'lucide-react'
import { cn } from '@/lib/util'
import { btnClass } from '@/components/ui'
import { DictateButton } from '@/components/Dictate'

export const QUICK_EDITS = ['Shorter', 'Warmer', 'More direct', 'More formal', 'Add a clear next step']

export function ReviseBar({ busy, onRevise, onFresh, onChat, chatting, extra, focus, className, placeholder = 'What should change? e.g. warmer, and say we need it by Friday' }: {
  busy: boolean; onRevise: (ask: string) => void; onFresh?: (ask: string) => void; onChat?: () => void; chatting?: boolean; extra?: ReactNode; focus?: boolean; className?: string; placeholder?: string }) {
  const [ask, setAsk] = useState('')
  const [running, setRunning] = useState<'revise' | 'fresh' | null>(null)   // which of the two is working, for its spinner
  const box = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { if (focus) setTimeout(() => box.current?.focus(), 50) }, [focus])
  useEffect(() => { if (!busy) setRunning(null) }, [busy])
  const go = (text: string) => { const t = text.trim(); if (!t || busy) return; setRunning('revise'); onRevise(t); setAsk('') }
  const fresh = () => { if (busy || !onFresh) return; setRunning('fresh'); onFresh(ask.trim()); setAsk('') }
  const spin = <RefreshCw size={14} className="animate-spin" aria-hidden />
  // the two actions look the same: same pill, same size, side by side; each one's edge darkens when it can run
  const pair = (ready: boolean) => btnClass('outline', 'sm', cn('h-7 shrink-0 bg-bg px-2.5 disabled:opacity-50', ready && 'border-ink'))
  return (
    <div className={cn('mt-3', className)}>
      <div className="flex items-end gap-2">
      <div data-dictate className={cn('flex min-w-0 flex-1 items-end gap-2 rounded-xl border bg-bg py-1.5 pl-3 pr-1.5 transition-colors focus-within:border-ink', busy ? 'border-line opacity-70' : 'border-line')}>
        <Sparkles size={14} aria-hidden className="mb-1.5 shrink-0 text-ink3" />
        <textarea ref={box} rows={1} value={ask} disabled={busy} aria-label="What should change in this draft?"
          onChange={(e) => { setAsk(e.target.value); e.currentTarget.style.height = 'auto'; e.currentTarget.style.height = `${e.currentTarget.scrollHeight}px` }}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || e.shiftKey) return
            e.preventDefault()
            if ((e.metaKey || e.ctrlKey) && onFresh) fresh(); else go(ask)
          }}
          placeholder={busy ? (running === 'fresh' ? 'Writing a new one… usually 20 to 40 seconds' : 'Revising… usually about 10 seconds') : placeholder}
          className="mb-0.5 max-h-32 min-h-[22px] flex-1 resize-none bg-transparent py-1 text-[13.5px] leading-relaxed text-ink outline-none placeholder:text-ink3" />
        <DictateButton target={box} size={14} />
        <button onClick={() => go(ask)} disabled={busy || !ask.trim()} title="Revise: change this draft as you asked (Enter)"
          className={pair(!!ask.trim() && !busy)}>
          {running === 'revise' ? spin : <ArrowUp size={14} aria-hidden />}Revise</button>
        {onFresh && <button onClick={fresh} disabled={busy}
          title={ask.trim() ? 'Write new: start again from the thread, with what you typed (⌘Enter)' : 'Write new: start again from the thread (⌘Enter with a request)'}
          className={pair(!busy)}>
          {running === 'fresh' ? spin : <RotateCcw size={13} aria-hidden />}Write new</button>}
      </div>
      {/* the handoff: take the draft into Ask SleePO for a longer back and forth (Sam, 28 Oct 2026) */}
      {onChat && <button onClick={onChat} disabled={chatting} title="Continue in chat: ask questions about this draft and change it with Ask SleePO"
        className="inline-flex h-[40px] shrink-0 items-center gap-1.5 rounded-xl border border-line bg-bg px-3 text-[12.5px] font-medium text-ink2 transition-colors hover:border-ink hover:text-ink disabled:opacity-60">
        {chatting ? spin : <MessageSquare size={14} aria-hidden />}<span className="max-sm:hidden">Continue in chat</span></button>}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        {QUICK_EDITS.map((t) => <button key={t} disabled={busy} onClick={() => go(t)} title={`Revise: ${t.toLowerCase()}`}
          className="rounded-full bg-panel2 px-2 py-0.5 text-[12px] text-ink2 transition-colors hover:bg-line hover:text-ink disabled:opacity-50">{t}</button>)}
        {extra}
      </div>
    </div>
  )
}

// what the last revision did: its note, Draft / Changes, and Undo (back to the text before it)
export function RevisedStrip({ note, unchanged, showChanges, setShowChanges, onUndo, className }: {
  note: string; unchanged?: boolean; showChanges: boolean; setShowChanges: (v: boolean) => void; onUndo: () => void; className?: string }) {
  return (
    <div className={cn('mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-panel2 px-3 py-1.5 text-[12.5px]', className)}>
      <span className={cn('min-w-0 flex-1', unchanged ? 'text-hot' : 'text-ink2')}>
        {unchanged ? 'SleePO found little to change. Say more precisely what you want different.' : <><span className="font-medium text-ink">Revised.</span> {note}</>}</span>
      <div role="radiogroup" aria-label="Show" className="inline-flex shrink-0 rounded-full bg-panel p-0.5">
        {([[false, 'Draft'], [true, 'Changes']] as const).map(([k, l]) => <button key={l} role="radio" aria-checked={showChanges === k} onClick={() => setShowChanges(k)}
          className={cn('rounded-full px-2 py-0.5 text-[12px] transition-colors', showChanges === k ? 'bg-panel2 font-medium text-ink' : 'text-ink2 hover:text-ink')}>{l}</button>)}
      </div>
      <button onClick={onUndo} title="Back to the text before this revision" className="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium text-ink2 hover:bg-panel hover:text-ink">
        <RotateCcw size={12} aria-hidden />Undo</button>
    </div>
  )
}
