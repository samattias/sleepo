// Ask SleePO's chips, alive (Sam, 17 Nov 2026: "Improve the context chips that you pass into the assistant so that I can click
// on them and go back to the context or I can hover over them and see a snapshot of the context ... I really like these chips").
// Every chip (the one in the message box before asking, and the one kept above each question) opens the thing it names when
// clicked: its href, built by the server (assist/page_context.py href, the inverse of the address the floating button reads it
// from). Hovering it, or reaching it with the keyboard, shows a card with that thing as it is now (GET /api/chat/context/preview,
// assist/chip_preview.py): a conversation's last messages, an email thread and the draft reply, a bet's status, a topic, a
// task's steps, a person's latest exchanges and next meeting, a meeting's notes or brief, a company's open deals, a document's
// summary with a way to the real file, a roadmap entry. The card says what SleePO read. Reads only.
//
// Chat.tsx draws the chips (ChipMark, the label and its line) and decides what opening means (from the Assistant page the
// conversation moves to the panel beside the page it opens); this file is the hover card and its timing.
import { Fragment, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Check, ExternalLink } from 'lucide-react'
import { api, type ChipLine, type ChipPreview, type PageCtx } from '@/lib/api'
import { cn } from '@/lib/util'
import { day, dayTime, hm } from '@/lib/time'
import { Markdown, btnClass, popoverClass } from './ui'

const NOUN: Record<string, string> = { message: 'conversation', email: 'email', initiative: 'initiative', topic: 'topic', task: 'task', person: 'profile',
  meeting: 'meeting', event: 'meeting', company: 'company', document: 'document', roadmap: 'roadmap item' }
/** "Open the email": what clicking the chip does, for its label and the card's button. */
export const openLabel = (ctx: PageCtx) => `Open the ${NOUN[ctx.kind] ?? 'page'}`

const key = (ctx: PageCtx) => ['chip-preview', ctx.kind, ctx.ref]
const fetchPreview = (ctx: PageCtx) => api.chatContextPreview(ctx.kind, ctx.ref).then((r) => r.preview)
const when = (s: string) => (/^\d{4}-\d{2}-\d{2}$/.test(s) ? day(s) : dayTime(s))

const W = 344, GAP = 8, EDGE = 12, OPEN_MS = 280, CLOSE_MS = 160

/** A chip with its snapshot card. Hovering it (or focusing it with the keyboard) opens the card after a short pause; the pointer
 *  can move onto the card and use its buttons; leaving both, Escape, scrolling or a click closes it. mark: the chip's picture a
 *  size up, for the card's header. asked: the chip kept above a question (the card says what SleePO read, not what it will). */
export function ChipHover({ ctx, mark, onOpen, asked, className, children }: {
  ctx: PageCtx; mark: ReactNode; onOpen: (href?: string) => void; asked?: boolean; className?: string; children: ReactNode
}) {
  const qc = useQueryClient()
  const anchor = useRef<HTMLSpanElement>(null)
  const card = useRef<HTMLDivElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const [pos, setPos] = useState<CSSProperties | null>(null)
  const clear = () => window.clearTimeout(timer.current)
  const place = () => {
    const r = anchor.current?.getBoundingClientRect()
    if (!r) return
    const w = Math.min(W, innerWidth - 2 * EDGE)
    const above = r.top > innerHeight - r.bottom   // the side with more room
    const x = r.left + r.width / 2 > innerWidth / 2 ? Math.max(EDGE, r.right - w) : Math.min(r.left, innerWidth - EDGE - w)
    setPos({ position: 'fixed', left: x, width: w, ...(above ? { bottom: innerHeight - r.top + GAP, maxHeight: r.top - GAP - EDGE }
      : { top: r.bottom + GAP, maxHeight: innerHeight - r.bottom - GAP - EDGE }) })
  }
  const show = (ms: number) => {
    clear()
    void qc.prefetchQuery({ queryKey: key(ctx), queryFn: () => fetchPreview(ctx), staleTime: 30_000 })
    timer.current = window.setTimeout(place, ms)
  }
  const hide = (ms = CLOSE_MS) => { clear(); timer.current = window.setTimeout(() => setPos(null), ms) }
  useEffect(() => clear, [])
  useEffect(() => {
    if (!pos) return
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setPos(null) }
    const away = (e: Event) => { if (!(e.target instanceof Node && card.current?.contains(e.target))) setPos(null) }
    addEventListener('keydown', esc); addEventListener('scroll', away, true); addEventListener('resize', away)
    return () => { removeEventListener('keydown', esc); removeEventListener('scroll', away, true); removeEventListener('resize', away) }
  }, [pos])
  const open = (href?: string) => { clear(); setPos(null); onOpen(href) }
  return (
    <span ref={anchor} className={className}
      onPointerEnter={(e) => { if (e.pointerType === 'mouse') show(OPEN_MS) }} onPointerLeave={() => hide()}
      onFocus={(e) => { if (e.target.matches(':focus-visible')) show(0) }}
      // a press on the card moves focus off the chip; Safari gives no relatedTarget then, so the pointer being on the card counts
      onBlur={(e) => { if (!card.current?.contains(e.relatedTarget as Node | null) && !card.current?.matches(':hover')) hide(0) }}
      // a click on the chip closes the card; never a click inside it: React runs this capture handler and commits the close
      // before the card's own buttons get the click, so Open the … and The file would have been unmounted and done nothing
      onClickCapture={(e) => { if (card.current?.contains(e.target as Node)) return; clear(); setPos(null) }}>
      {children}
      {pos && createPortal(
        <div ref={card} role="dialog" aria-label={ctx.label} style={pos} onPointerEnter={clear} onPointerLeave={() => hide()}
          onBlur={(e) => { if (!card.current?.contains(e.relatedTarget as Node | null) && !anchor.current?.contains(e.relatedTarget as Node | null)) hide(0) }}
          className={cn(popoverClass, 'chip-card z-[70] flex flex-col rounded-2xl shadow-[0_18px_44px_-16px_rgba(0,0,0,0.35)]')}>
          <Snapshot ctx={ctx} mark={mark} asked={asked} onOpen={open} />
        </div>, document.body)}
    </span>
  )
}

// The card: the thing's name and what it is, then as much of it as fits in a glance, then the way to it.
function Snapshot({ ctx, mark, asked, onOpen }: { ctx: PageCtx; mark: ReactNode; asked?: boolean; onOpen: (href?: string) => void }) {
  const q = useQuery({ queryKey: key(ctx), queryFn: () => fetchPreview(ctx), staleTime: 30_000 })
  const p = q.data
  // no way to the page you are on (the chip in the message box names it): the button would do nothing
  const here = location.hash.replace(/^#/, '').split('?nolive')[0]
  const href = (p?.href || ctx.href) === here ? '' : p?.href || ctx.href
  const gone = ctx.gone || (q.isSuccess && !p)
  const reads = p?.reads || ctx.detail   // what the chat reads with the question (a person's chip detail is their role)
  const kicker = p ? p.kicker + (p.at ? ` · ${p.end ? `${day(p.at)}, ${hm(p.at)}–${hm(p.end)}` : when(p.at)}` : '') : ctx.sub || ''
  return <>
    <div className="flex items-start gap-2.5 px-3.5 pb-2 pt-3">
      {mark}
      <div className="min-w-0 flex-1 leading-tight">
        <div className="line-clamp-2 text-[13.5px] font-medium text-ink">{p?.label || ctx.label}</div>
        {kicker && <div className="mt-0.5 truncate text-[11.5px] text-ink3">{kicker}</div>}
      </div>
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto px-3.5 pb-3">
      {q.isLoading ? <div className="flex items-center gap-2 py-1 text-[12px] text-ink3"><Dots />Reading</div>
        : gone ? <p className="text-[12.5px] text-ink2">SleePO no longer holds this, so there is nothing to show or open.</p>
        : q.isError ? <p className="text-[12.5px] text-ink2">Could not read it just now.</p>
        : p && <Body p={p} />}
    </div>
    {!gone && (href || p?.url) && (
      <div className="flex items-center gap-1 border-t border-line2 px-2 py-1.5">
        {href && <button type="button" onClick={() => onOpen(href)} className={btnClass('ghost', 'sm', 'text-ink')}>{openLabel(ctx)}<ArrowUpRight size={14} aria-hidden /></button>}
        {p?.url && <a href={p.url} target="_blank" rel="noopener" className={btnClass('ghost', 'sm', 'text-ink2')}><ExternalLink size={13} aria-hidden />The file</a>}
      </div>)}
    {reads && !gone && <div className="border-t border-line2 px-3.5 py-2 text-[11.5px] leading-snug text-ink3">
      {asked ? 'SleePO read' : 'SleePO reads, with your first question'}: {reads.replace(/^\d{4}-\d{2}-\d{2} · (\w)/, (_, c: string) => c.toUpperCase())}</div>}
  </>
}

function Body({ p }: { p: ChipPreview }) {
  return (
    <div className="flex flex-col gap-2.5">
      {p.text && <p className="line-clamp-4 text-[12.5px] leading-snug text-ink2">{p.text}</p>}
      {p.facts.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px] leading-snug">
          {p.facts.map(([k, v, at]) => <Fragment key={k}>
            <dt className="whitespace-nowrap text-ink3">{k}</dt>
            <dd className="line-clamp-2 min-w-0 text-ink">{v}{at ? <span className="text-ink3"> · {when(at)}</span> : null}</dd>
          </Fragment>)}
        </dl>)}
      {p.md && <div className="chip-md max-h-[168px] overflow-hidden text-[12.5px] leading-snug [mask-image:linear-gradient(to_bottom,black_70%,transparent)]">
        <Markdown>{p.md}</Markdown></div>}
      {p.lines.length > 0 && (
        <div>
          {p.lines_label && <div className="mb-1 text-[11.5px] font-medium text-ink3">{p.lines_label}</div>}
          <ul className="flex flex-col gap-1.5">{p.lines.map((l, i) => <Line key={i} l={l} />)}</ul>
        </div>)}
      {p.draft_text && (
        <div className="rounded-lg border border-dashed border-line px-2.5 py-1.5">
          <div className="text-[11px] font-medium text-ink3">Your draft reply</div>
          <p className="mt-0.5 line-clamp-4 whitespace-pre-line text-[12.5px] leading-snug text-ink">{p.draft_text}</p>
        </div>)}
    </div>
  )
}

// One line: a message (who, when, what), a step (done or not, owner, due), a deal (amount, close date), a fact.
function Line({ l }: { l: ChipLine }) {
  const step = typeof l.done === 'boolean'
  const meta = l.who || l.when || l.when_text
  return (
    <li className="flex gap-2 text-[12.5px] leading-snug">
      {step && <span className={cn('mt-[3px] grid size-[13px] shrink-0 place-items-center rounded-full border', l.done ? 'border-ink bg-ink text-bg' : 'border-ink3')}>
        {l.done && <Check size={9} strokeWidth={3} aria-label="done" />}</span>}
      <div className="min-w-0 flex-1">
        {meta && !step && <div className="flex items-baseline gap-1.5 text-[11.5px]">
          {l.who && <span className="font-medium text-ink">{l.who}</span>}
          {(l.when || l.when_text) && <span className="truncate text-ink3">{l.when ? when(l.when) : l.when_text}</span>}
        </div>}
        <div className={cn('line-clamp-2 [overflow-wrap:anywhere]', l.done ? 'text-ink3 line-through' : step || !meta ? 'text-ink' : 'text-ink2')}>{l.text}</div>
        {step && meta && <div className="text-[11.5px] text-ink3">{[l.who, l.when ? when(l.when) : ''].filter(Boolean).join(' · ')}</div>}
      </div>
    </li>
  )
}

const Dots = () => <span aria-hidden className="inline-flex items-center gap-[3px]">{[0, 1, 2].map((i) =>
  <span key={i} className="size-[5px] animate-bounce rounded-full bg-ink3" style={{ animationDelay: `${i * 0.15}s`, animationDuration: '1s' }} />)}</span>
