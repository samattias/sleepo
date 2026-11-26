// A briefing on an email: the situation around the thread, so Sam is up to speed before he answers it, meets these people or
// asks more (assist/briefing.py). A tool-free run reads the thread in full and everything SleePO knows around it (related
// mail and messages, meetings, documents, open items, the people, their deals and Sam's initiatives) and writes
// where it stands, how it got here, who wants what, what is open, what to read and what to watch. Every source is a link:
// emails open in the Inbox, meetings at their page, documents in the reader or where they live. "Ask about this in chat"
// continues in Ask SleePO: the briefing is the conversation's first answer and its material sits in the conversation's
// folder, so the chat goes deeper from there (components/Chat.tsx openChatThread). Nothing is sent.
// The Inbox shows it above the thread, written when Sam asks with the toolbar's Brief me (views/inbox/conversation.tsx),
// and hides and shows it from there.
import { Fragment, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarClock, CalendarDays, ChevronDown, CircleDot, ListChecks, Mail, MessageSquare, MessagesSquare, RefreshCw, ScrollText, Sparkles, type LucideIcon } from 'lucide-react'
import { api, type BriefingRecord, type BriefingRef, type Person } from '@/lib/api'
import { cn } from '@/lib/util'
import { ago, day as dayOf, TZ, LOCALE } from '@/lib/time'
import { useJob } from '@/lib/useJob'
import { Avatar } from '@/components/ui'
import { DocChip } from '@/components/DocChip'
import { openChatThread } from '@/components/Chat'
import { DictateButton } from './Dictate'
import { PersonLink } from '@/components/PersonLink'

const REF = /\[((?:[ECMKL]\d+)|(?:(?:sp|lf|kb|ma)-\d+))\]/g
const ICON: Record<BriefingRef['kind'], LucideIcon> = { email: Mail, chat: MessageSquare, meeting: CalendarDays, event: CalendarClock, item: CircleDot, doc: ScrollText }
const FOCUS = ['What has been agreed so far', 'What they expect from me', 'The history with this partner', 'Risks before I reply']
const h = 'mb-1.5 text-[13px] font-semibold'
const day = (iso: string) => { try { return dayOf(iso) } catch { return '' } }

// one source, as a small chip: an email, message, meeting or open item opens in SleePO; a document opens to read
function Src({ k, refs }: { k: string | null; refs: Record<string, BriefingRef> }) {
  const r = k ? refs[k] : undefined
  if (!k || !r) return null
  if (r.kind === 'doc') return <DocChip id={k}>{r.label}</DocChip>
  const Icon = ICON[r.kind] ?? CircleDot
  const tip = [r.title, r.label, r.thread ? 'in this thread' : ''].filter(Boolean).join(' · ')
  return (
    <a href={r.url ? `#${r.url}` : undefined} title={tip}
      className="mx-0.5 inline-flex max-w-[16rem] items-center gap-1 rounded-full border border-line bg-panel px-1.5 py-px align-baseline text-[11.5px] font-medium text-ink no-underline hover:border-ink hover:bg-accent hover:text-onaccent">
      <Icon size={11} className="shrink-0" aria-hidden /><span className="truncate">{r.label}</span></a>
  )
}

// prose with [E123] citations turned into chips
function Cited({ text, refs }: { text: string; refs: Record<string, BriefingRef> }) {
  const parts = text.split(REF)
  return <>{parts.map((p, i) => (i % 2 ? <Src key={i} k={p} refs={refs} /> : <Fragment key={i}>{p}</Fragment>))}</>
}

function Section({ title, icon: Icon, children }: { title: string; icon?: LucideIcon; children: ReactNode }) {
  return <section className="mt-4"><h4 className={cn(h, 'flex items-center gap-1.5')}>{Icon && <Icon size={14} aria-hidden />}{title}</h4>{children}</section>
}

// top: the Inbox shows it above the thread (Sam, 22 Oct 2026). Nothing shows there until he asks for one with the toolbar's
// Brief me or the b key (Sam, 18 Nov 2026: the standing row with Create briefing and Add focus was clutter): then the
// reading line, then the briefing, which the toolbar hides and shows (hidden / onHidden, kept per email by the Inbox).
// A focus is given with Brief me again, under an existing briefing. runSignal: the toolbar's click, which writes one.
export function Briefing({ mailId, who, askRef, top = false, runSignal = 0, hidden = false, onHidden }: { mailId: number; who: (name: string) => Person | undefined
  askRef?: RefObject<HTMLTextAreaElement | null>; top?: boolean; runSignal?: number; hidden?: boolean; onHidden?: (hidden: boolean) => void }) {
  const qc = useQueryClient()
  const latest = useQuery({ queryKey: ['briefing', mailId], queryFn: () => api.briefing(mailId) })
  const rec: BriefingRecord | null = latest.data?.briefing ?? null
  const [ask, setAsk] = useState('')
  const [starting, setStarting] = useState(false)
  const [err, setErr] = useState('')
  const [chatting, setChatting] = useState(false)
  const [again, setAgain] = useState(false)   // the focus box, shown again over an existing briefing

  // the run follows on: leaving the email stops the polling, and coming back picks a running job up (lib/useJob.ts); the
  // finished briefing is kept on the server, so nothing is lost either way
  const run = useJob(`assist-briefing-${mailId}`, api.briefingJob, {
    onDone: (j) => {
      if (!j.result) { setErr('No briefing came back'); return }
      qc.setQueryData(['briefing', mailId], { briefing: j.result })
      setAgain(false); onHidden?.(false)
    },
    onError: setErr,
  })
  const busy = starting || run.busy
  const create = async () => {
    if (busy) return
    setStarting(true); setErr('')
    try { run.follow((await api.briefingStart(mailId, ask)).job) } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    setStarting(false)
  }
  const signal = useRef(runSignal)   // only a click after this mounted writes one, never the mount itself
  useEffect(() => { if (runSignal !== signal.current) { signal.current = runSignal; void create() } }, [runSignal])   // eslint-disable-line react-hooks/exhaustive-deps
  const toChat = async (q?: string) => {
    setChatting(true); setErr('')
    try {
      const { thread } = await api.briefingChat(mailId)
      openChatThread(thread, q)
      qc.invalidateQueries({ queryKey: ['briefing', mailId] })
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    setChatting(false)
  }

  const form = (
    <div className="px-4 py-3">
      <label htmlFor={`brief-ask-${mailId}`} className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold"><Sparkles size={14} aria-hidden />Anything to focus on? <span className="font-normal text-ink2">Optional</span></label>
      <div className="relative" data-dictate>
      <textarea id={`brief-ask-${mailId}`} ref={askRef} value={ask} onChange={(e) => setAsk(e.target.value)} rows={2}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); create() } }}
        placeholder="e.g. What did we already promise them on pricing, and who else is involved?"
        className="w-full resize-y rounded-lg border border-line bg-bg p-2.5 pr-10 text-[13.5px] leading-relaxed text-ink outline-none focus:border-ink" />
        <span className="absolute bottom-2 right-2"><DictateButton /></span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {FOCUS.map((t) => <button key={t} onClick={() => setAsk(ask ? `${ask.trim()} ${t}.` : `${t}.`)} className="rounded-full border border-line px-2.5 py-0.5 text-[12.5px] text-ink2 hover:border-ink hover:text-ink">{t}</button>)}
        <button onClick={create} disabled={busy} title="Create the briefing (⌘↵)" className="ml-auto inline-flex items-center gap-2 rounded-full bg-accent px-3.5 py-1.5 text-[13px] font-semibold text-onaccent hover:brightness-95 disabled:opacity-60">
          {busy ? <RefreshCw size={15} className="animate-spin" aria-hidden /> : <ScrollText size={15} aria-hidden />}{busy ? 'Reading…' : rec ? 'Brief me again' : 'Create briefing'}</button>
      </div>
    </div>
  )

  if (top) {
    if (!busy && !err && (!rec || hidden)) return null
    return (
      <section aria-label="Briefing on this thread" className="mt-4 rounded-xl bg-panel2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
          <ScrollText size={15} aria-hidden className="shrink-0" />
          <div className="min-w-0 flex-1 text-[13px] leading-snug">
            <span className="font-semibold">Briefing</span>
            <span className="text-ink2"> · {busy ? 'reading the thread, related mail, meetings, documents and open items. Usually under a minute.'
              : rec ? <span title={new Date(rec.created_at).toLocaleString(LOCALE, { timeZone: TZ })}>written {ago(rec.created_at)}</span>
              : 'not written'}</span>
          </div>
          {busy ? <RefreshCw size={15} className="animate-spin text-ink2" aria-hidden />
            : rec && <button onClick={() => onHidden?.(true)} title="Hide the briefing (b)" className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12.5px] font-medium hover:bg-panel">
                Hide<ChevronDown size={13} aria-hidden className="rotate-180" /></button>}
        </div>
        {!busy && rec && again && <div className="border-t border-line/60">{form}</div>}
        {err && <div role="alert" className="px-4 pb-3 text-[12.5px] text-hot">{err}</div>}
        {rec && <div className="rounded-b-xl bg-panel"><View rec={rec} who={who} chatting={chatting} onChat={toChat} onAgain={() => setAgain(!again)} again={again} busy={busy} /></div>}
      </section>
    )
  }

  return (
    <div aria-label="Briefing on this email">
      <header className="flex items-start gap-2 border-b border-line px-4 py-2 text-[13px] text-ink2">
        <ScrollText size={15} className="mt-0.5 shrink-0 text-ink" aria-hidden />
        <span>Get up to speed: where this stands, how it got here, who wants what, what is open and what to read. Then keep asking in the chat.</span>
      </header>

      {latest.isLoading ? null : (!rec || again) && form}
      {busy && <div className="px-4 pb-3 text-[12.5px] text-ink2">Reading the whole thread, related mail and messages, meetings, documents and open items. Usually under a minute.</div>}
      {err && <div role="alert" className="px-4 pb-3 text-[12.5px] text-hot">{err}</div>}

      {rec && <View rec={rec} who={who} chatting={chatting} onChat={toChat} onAgain={() => setAgain(!again)} again={again} busy={busy} />}
    </div>
  )
}

function View({ rec, who, chatting, onChat, onAgain, again, busy }: { rec: BriefingRecord; who: (name: string) => Person | undefined; chatting: boolean
  onChat: (q?: string) => void; onAgain: () => void; again: boolean; busy: boolean }) {
  const b = rec.briefing, refs = rec.refs, s = rec.stats
  const n = (k: number, w: string) => `${k} ${w}${k === 1 ? '' : 's'}`
  const from = [s.thread && `${n(s.thread, 'email')} in the thread`, s.mail && n(s.mail, 'related email'), s.messages && n(s.messages, 'message'),
    s.meetings && n(s.meetings, 'meeting'), s.documents && n(s.documents, 'document'), s.open && n(s.open, 'open item')].filter(Boolean)
  return (
    <article className={cn('border-t border-line px-4 py-3', busy && 'opacity-60')}>
      {b.headline && <p className="text-[15px] font-semibold leading-snug"><Cited text={b.headline} refs={refs} /></p>}
      {b.situation && <p className="mt-2 text-[14px] leading-relaxed"><Cited text={b.situation} refs={refs} /></p>}
      {b.needs && <div className="mt-3 rounded-lg border-l-2 border-l-hot bg-panel2 px-3 py-2 text-[13.5px] leading-relaxed"><b>What it needs from you</b> · <Cited text={b.needs} refs={refs} /></div>}

      {b.timeline.length > 0 && <Section title="How we got here" icon={CalendarDays}>
        <ol className="border-l border-line">
          {b.timeline.map((x, i) => <li key={i} className="relative py-1 pl-4 text-[13.5px] leading-relaxed">
            <span aria-hidden className="absolute -left-[4px] top-[0.7em] size-[7px] rounded-full bg-ink" />
            <span className="mr-1.5 inline-block min-w-[3.4rem] font-semibold tabular-nums">{day(x.date)}</span><Cited text={x.what} refs={refs} /><Src k={x.ref} refs={refs} /></li>)}
        </ol>
      </Section>}

      {b.people.length > 0 && <Section title="Who is involved">
        <ul className="grid gap-2 md:grid-cols-2">
          {b.people.map((p) => {
            const per = who(p.name)
            const pid = p.id ?? per?.id
            const name = pid ? <PersonLink id={pid} className="font-semibold">{p.name}</PersonLink> : <span className="font-semibold">{p.name}</span>
            return <li key={p.name} className="flex items-start gap-2.5 rounded-lg border border-line bg-panel px-3 py-2">
              <PersonLink id={pid} photo><Avatar p={per ?? { name: p.name, avatar: '' }} size={30} /></PersonLink>
              <div className="min-w-0 text-[13px] leading-snug">
                <div>{name}{(p.title || per?.title) && <span className="text-ink2"> · {p.title || per?.title}</span>}</div>
                {p.part && <div className="mt-0.5 text-ink2"><Cited text={p.part} refs={refs} /><Src k={p.ref} refs={refs} /></div>}
              </div>
            </li>
          })}
        </ul>
      </Section>}

      {b.open.length > 0 && <Section title="Still open" icon={ListChecks}>
        <ul className="space-y-1">
          {b.open.map((x, i) => <li key={i} className="flex items-start gap-2 text-[13.5px] leading-relaxed">
            <CircleDot size={13} className="mt-1 shrink-0 text-ink2" aria-hidden />
            <span><Cited text={x.what} refs={refs} />{x.owner && <span className="text-ink2"> · {x.owner}</span>}{x.ref ? <Src k={x.ref} refs={refs} /> : <span className="text-[12px] text-ink3"> · no source</span>}</span></li>)}
        </ul>
      </Section>}

      {b.read.length > 0 && <Section title="Read first" icon={ScrollText}>
        <ul className="space-y-1.5">
          {b.read.map((x) => <li key={x.doc} className="text-[13.5px] leading-relaxed"><DocChip id={x.doc}>{refs[x.doc]?.label}</DocChip>{x.why && <span className="text-ink2"> {x.why}</span>}</li>)}
        </ul>
      </Section>}

      {b.watch.length > 0 && <Section title="Watch" icon={AlertTriangle}>
        <ul className="list-disc space-y-1 pl-5 text-[13.5px] leading-relaxed">{b.watch.map((x, i) => <li key={i}><Cited text={x} refs={refs} /></li>)}</ul>
      </Section>}

      <div className="mt-4 border-t border-line pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => onChat()} disabled={chatting} className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1.5 text-[13px] font-semibold text-onaccent hover:brightness-95 disabled:opacity-60">
            {chatting ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : <MessagesSquare size={14} aria-hidden />}Ask about this in chat</button>
          <button onClick={onAgain} disabled={busy} className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium hover:bg-panel2 disabled:opacity-60"><RefreshCw size={13} aria-hidden />{again ? 'Keep this briefing' : 'Brief me again'}</button>
          <span className="text-[12px] text-ink3" title={new Date(rec.created_at).toLocaleString(LOCALE, { timeZone: TZ })}>Written {ago(rec.created_at)}{from.length ? ` from ${from.join(', ')}` : ''}. Nothing is sent from here.</span>
        </div>
        {b.questions.length > 0 && <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[12.5px] font-semibold">Ask next</span>
          {b.questions.map((q) => <button key={q} onClick={() => onChat(q)} disabled={chatting} title="Opens the chat with this question ready to send"
            className="rounded-full border border-line px-2.5 py-0.5 text-left text-[12.5px] text-ink2 hover:border-ink hover:text-ink disabled:opacity-60">{q}</button>)}
        </div>}
      </div>
    </article>
  )
}
