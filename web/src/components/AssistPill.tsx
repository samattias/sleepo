// The assistant's call to action (Sam, 16 Nov 2026: "I like this pill because it's a call to action to use the assistant to do
// stuff. I want to use it throughout the UI"). One lime pill with the SleePO mark and its actions; where a page wants it, a field
// inside the pill for details ("I could add context directly into the pill"), and quick actions under it. Clicking an action
// opens Ask SleePO on a new chat about the thing the page names (target, or the nearest AssistScope, or what the address has
// open: the context framework in components/AssistContext.tsx) and asks it at once, with the details typed in the field: the
// floating button's hover menu, made prominent on the page. The chat shows the thing's chip above the question (for a
// conversation: who and its latest message), so what it read is visible, and the page stays beside the panel. Nothing is sent.
// Pages with a richer start of their own pass onAction: an initiative's or topic's work bar (components/InitiativeWork.tsx)
// opens a conversation seeded with its pack and the items picked there. An action with `run` does its page's own work in place
// instead: the Inbox's answer panel, one pill per tab in place of its request box (Sam, 17 Nov 2026: Draft response, Create
// document, Create task; "this pill should be part of the draft response at the bottom").
// First use: the Messages page's reply box (views/messages.tsx).
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { RefreshCw, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/util'
import { useAskAssistant, type AssistTarget } from './AssistContext'
import { DictateButton } from './Dictate'
import { Logo } from './Logo'

/** prompt: the question asked, given what Sam typed in the field ('' when nothing). run: the page's own work instead of a
 *  question to the chat. busy: that work is running (its own spinner). needsText: only with words in the field. meta: what
 *  ⌘Enter does (Enter does the first action). */
export type PillAction = { label: string; icon?: LucideIcon; tip?: string; prompt: (details: string) => string
  run?: (details: string) => void; busy?: boolean; disabled?: boolean; needsText?: boolean; meta?: boolean }

const btn = 'inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-semibold text-onaccent transition-colors hover:bg-black/10 focus-visible:bg-black/10 disabled:opacity-60'

export function AssistPill({ target, actions, quick = [], field, onAction, busy, note, inputRef, className }: {
  target?: AssistTarget | null                           // what it works on (AssistContext.tsx); else the scope, else the address
  actions: PillAction[]                                  // in the pill; with a field, the first is what Enter does
  quick?: PillAction[]                                   // one-click asks under the pill
  field?: { placeholder: string; label: string }         // details, sent with whichever action is clicked
  onAction?: (a: PillAction, details: string) => void    // a page's own start (default: a new chat with the page's chip)
  busy?: string | null                                   // with onAction: the label of the action starting
  note?: ReactNode                                       // a quiet line beside the pill (or at the end of the quick asks)
  inputRef?: RefObject<HTMLTextAreaElement | null>       // the field, for the page's keys to focus
  className?: string
}) {
  const assistant = useAskAssistant(target)
  const [details, setDetails] = useState('')
  const [starting, setStarting] = useState<string | null>(null)
  const mine = useRef<HTMLTextAreaElement>(null)
  const box = inputRef ?? mine
  useEffect(() => {   // the field grows with its text (to four lines) and shrinks back once an action takes it
    const el = box.current
    if (!el) return
    el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 96)}px`
  }, [details, box])
  const working = onAction ? busy ?? null : starting
  const blocked = working !== null || (!onAction && assistant.busy)
  const off = (a: PillAction) => !!a.disabled || (!!a.needsText && !details.trim()) || (a.run ? !!a.busy : blocked)
  const go = async (a: PillAction) => {
    if (off(a)) return
    const d = details.trim()
    if (a.run) { a.run(d); setDetails(''); return }
    if (onAction) { onAction(a, d); setDetails(''); return }
    setStarting(a.label)
    if (await assistant.ask(a.prompt(d))) setDetails('')
    setStarting(null)
  }
  const tipOf = (a: PillAction) => !a.run && assistant.busy && !onAction ? 'SleePO is still answering in the chat' : a.tip ?? `Ask SleePO: ${a.prompt(details.trim())}`
  const spins = (a: PillAction) => a.busy ?? working === a.label
  const Icon = ({ a }: { a: PillAction }) => spins(a) ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : a.icon ? <a.icon size={14} aria-hidden /> : null
  const meta = actions.find((a) => a.meta)
  const noteEl = note && <span className="text-[12px] text-ink3 max-sm:hidden">{note}</span>
  return (
    <div className={className}>
      <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5', field && 'flex-nowrap')}>
        <div role="group" aria-label="Ask SleePO" data-dictate={field ? true : undefined}
          className={cn('inline-flex items-center gap-0.5 rounded-[22px] bg-accent p-1 pl-1.5 text-onaccent shadow-[0_2px_10px_-6px_rgba(0,0,0,0.35)]', field ? 'min-w-0 flex-1' : 'flex-wrap')}>
          <Logo size={24} animate={working !== null || actions.some((a) => a.busy)} className="mr-1 shrink-0 rounded-full" />
          {field && <div className="mr-0.5 flex min-w-0 flex-1 items-center rounded-[18px] bg-bg pr-1">
            <textarea ref={box} rows={1} value={details} aria-label={field.label} placeholder={field.placeholder}
              onChange={(e) => setDetails(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void go((e.metaKey || e.ctrlKey) && meta ? meta : actions[0]) } }}
              className="min-w-0 flex-1 resize-none bg-transparent py-1.5 pl-3.5 text-[13.5px] leading-snug text-ink outline-none placeholder:text-ink3 placeholder-shown:overflow-hidden placeholder-shown:text-ellipsis placeholder-shown:whitespace-nowrap" />
            <DictateButton target={box} size={14} />
          </div>}
          {actions.map((a) => <button key={a.label} onClick={() => void go(a)} disabled={off(a)} title={tipOf(a)} className={btn}><Icon a={a} />{a.label}</button>)}
        </div>
        {!quick.length && noteEl && <span className="ml-auto">{noteEl}</span>}
      </div>
      {quick.length > 0 && <div className="mt-1.5 flex flex-wrap items-center gap-1 pl-1">
        {quick.map((a) => <button key={a.label} onClick={() => void go(a)} disabled={off(a)} title={tipOf(a)}
          className="inline-flex items-center gap-1 rounded-full bg-panel2 px-2.5 py-0.5 text-[12px] text-ink2 transition-colors hover:bg-line hover:text-ink disabled:opacity-50">
          {spins(a) && <RefreshCw size={11} className="animate-spin" aria-hidden />}{a.label}</button>)}
        {noteEl && <span className="ml-auto pl-2">{noteEl}</span>}
      </div>}
    </div>
  )
}
