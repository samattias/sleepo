// Working on an initiative or a top-of-mind topic from its page (Sam, 29 Oct 2026: "click into the initiative and see all the
// recent content and be able to take actions and decisions related to that initiative, for example, generate documents, send
// emails"). The bar under the page's header: Write an email, Create a document, Decide, Ask in chat. Each opens a conversation
// in Ask SleePO (Sam, 29 Oct 2026: "open this in the assistant interface ... with all the context of the situation ... I want
// to stop creating separate UXs"): it starts from the subject's status or summary, with its context (assist/initiative_work.py:
// status, tasks, top of mind, everything behind it, people, documents) and the items Sam picked ("Working from") in the
// conversation's folder. Nothing is asked for him (Sam, 30 Oct 2026: "don't immediately kick it off in chat ... wait for
// additional input context from me"): the chat asks who the email is for and what it should say (or what the document is,
// or which decision), the box says so, and one suggestion leaves it to SleePO. The bar is one lime pill with the SleePO mark
// (Sam, 30 Oct 2026: "a little pill section with the assistant icon ... highlight these in green as these are the kind of
// call to action buttons on the page"). The email comes back as an email card, the document as a
// plan and then the file, the decision laid out with options; Sam's call is recorded by its card as a decide step in Tasks.
// Nothing is sent. A top-of-mind topic's page (views/topic.tsx) works the same way: the subject is a WorkSubject, whose `base`
// says where the work goes (api.workBase), and ItemRow reads one item in place on either page.
import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, ExternalLink, FileText, Mail, MessageSquare, Paperclip, Pin, Scale, Sparkles, Video, X } from 'lucide-react'
import { api, type IniWork } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { openChatThread } from '@/components/Chat'
import { FileIcon } from '@/components/FileIcon'
import { AssistPill } from '@/components/AssistPill'
import { TZ, LOCALE } from '@/lib/time'

export type Pin = { key: string; ref_type: string; ref_id: number; type: string; title: string }
/** What a button asks the conversation for; '' is Ask in chat (Sam asks himself). */
export type Intent = '' | 'email' | 'document' | 'decide'
/** What a page works on: an initiative or a topic. base: where its work goes (api.workBase); key: its name in this browser's
 *  storage (the picked items). */
export type WorkSubject = { kind: 'initiative' | 'topic'; base: string; key: string; name: string; work?: IniWork }
/** One item a page lists (an initiative's Latest, a topic's sources), to read in place and work from. */
export type WorkItem = { key: string; ref_type: string; ref_id: number; type: string; title: string; who: string; ts: string | null; app: string; url?: string
  gist?: string; reason?: string; verdict?: 'confirmed' | 'rejected' | null }

const msg = (e: unknown) => String(e instanceof Error ? e.message : e)

/** A page's working state: the items Sam picked (kept per subject) and the conversation being started. */
export function useWork(subj: Pick<WorkSubject, 'base' | 'key'>) {
  const [pins, setPins] = usePersisted<Pin[]>(`assist-${subj.key}-pins`, [])
  const [busy, setBusy] = useState<Intent | null>(null)
  const [err, setErr] = useState('')
  const pin = (l: WorkItem): Pin => ({ key: l.key, ref_type: l.ref_type, ref_id: l.ref_id, type: l.type, title: l.title })
  const togglePin = (l: WorkItem) => setPins(pins.some((p) => p.key === l.key) ? pins.filter((p) => p.key !== l.key) : [...pins, pin(l)].slice(-8))
  // a conversation in Ask SleePO with the subject's context and the picked items; it waits for Sam to say what he wants
  const start = async (intent: Intent, focus = pins) => {
    if (busy !== null) return
    setBusy(intent); setErr('')
    try { const { thread, hint } = await api.workChat(subj.base, focus.map((p) => p.key), intent); openChatThread(thread, undefined, { hint }) }
    catch (e) { setErr(msg(e)) }
    setBusy(null)
  }
  // an action from one item: work from it, with what was picked already
  const actFrom = (l: WorkItem, intent: Intent) => {
    const next = pins.some((x) => x.key === l.key) ? pins : [...pins, pin(l)].slice(-8)
    setPins(next); void start(intent, next)
  }
  return { pins, setPins, togglePin, start, actFrom, busy, err }
}
export type Work = ReturnType<typeof useWork>

const ICON: Record<string, typeof Mail> = { meeting: Video, mail: Mail, chat: MessageSquare, doc: FileText }
const BUTTONS: [Intent, string, typeof Mail, string][] = [
  ['email', 'Write an email', Mail, 'Opens Ask SleePO with everything behind this; say who it is for and what it should say, and SleePO writes it'],
  ['document', 'Create a document', FileText, 'Opens Ask SleePO with everything behind this; say what the document is, and SleePO proposes it, then makes it (a deck through Claude)'],
  ['decide', 'Decide', Scale, 'Opens Ask SleePO with everything behind this; say which decision, and SleePO lays out the options and a recommendation; your call is kept as a decide step in Tasks'],
  ['', 'Ask in chat', MessageSquare, 'Ask SleePO about this, with everything behind it'],
]

export function WorkBar({ subj, w }: { subj: WorkSubject; w: Work }) {
  const { pins, setPins, start, busy, err } = w
  const work = subj.work ?? { drafts: [], decisions: [] }
  const chats = work.chats ?? []
  const open = work.decisions.filter((d) => d.status !== 'done')
  const chip = 'inline-flex max-w-[280px] items-center gap-1 rounded-full bg-panel2 px-2 py-0.5 font-normal text-ink no-underline hover:bg-line'
  return (
    <section id="ini-work" aria-label={`Work on this ${subj.kind}`} className="mb-4 scroll-mt-4">
      {/* the assistant pill (components/AssistPill.tsx), starting this page's own conversations */}
      <AssistPill actions={BUTTONS.map(([intent, label, icon, tip]) => ({ label, icon, tip, prompt: () => intent }))}
        onAction={(a) => void start(BUTTONS.find((b) => b[1] === a.label)![0])}
        busy={busy === null ? null : BUTTONS.find((b) => b[0] === busy)?.[1] ?? null} note="Opens in Ask SleePO · nothing is sent" />
      {pins.length > 0 && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12.5px]">
        <span className="inline-flex items-center gap-1 text-ink3"><Pin size={12} aria-hidden />Working from</span>
        {pins.map((p) => { const I = ICON[p.type] ?? FileText
          return <span key={p.key} className="inline-flex max-w-[280px] items-center gap-1 rounded-full border border-line bg-panel py-0.5 pl-2 pr-1">
            {p.type === 'doc' ? <FileIcon name={p.title} size={12} /> : <I size={12} aria-hidden className="shrink-0 text-ink3" />}<span className="truncate">{p.title}</span>
            <button onClick={() => setPins(pins.filter((q) => q.key !== p.key))} aria-label={`Stop working from ${p.title}`} className="rounded-full p-0.5 text-ink3 hover:bg-panel2 hover:text-ink"><X size={12} aria-hidden /></button></span> })}
        {pins.length > 1 && <button onClick={() => setPins([])} className="px-1 text-ink3 hover:text-ink">Clear</button>}
      </div>}
      {(chats.length > 0 || work.drafts.length > 0 || open.length > 0) && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12.5px]">
        <span className="text-ink3">In progress</span>
        {chats.map((c) => <button key={c.id} onClick={() => openChatThread(c.id)} title="Open the conversation" className={chip}>
          <MessageSquare size={12} aria-hidden className="shrink-0" /><span className="truncate">{c.title}</span></button>)}
        {work.drafts.map((d) => <a key={d.key} href={`#/inbox?draft=${d.key}`} title={d.ask || d.subject} className={chip}><Mail size={12} aria-hidden className="shrink-0" />
          <span className="truncate">{d.subject || (d.has_text ? 'Email' : 'New email')}</span>{!d.has_text && <span className="text-ink3">· not written</span>}</a>)}
        {open.map((d) => <a key={d.id} href={`#/tasks?open=${d.task_id}`} title={`A decide step on “${d.task}”`} className={chip}>
          <Scale size={12} aria-hidden className="shrink-0" /><span className="truncate">{d.title}</span></a>)}
      </div>}
      {err && <p role="alert" className="mt-2 text-[12.5px] text-hot">{err}</p>}
    </section>
  )
}

// ---------------------------------------------------------------- one item, read in place
const day = (iso?: string | null) => iso ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short' }).format(new Date(iso.length === 10 ? iso + 'T12:00:00Z' : iso)) : ''
const KIND_LABEL: Record<string, string> = { meeting: 'Meeting', mail: 'Email', chat: 'Chat', doc: 'Document', ask: 'You asked SleePO' }
const act = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2'

/** An item on an initiative's or topic's page: one line; opened, it reads in place (the email with its thread, the message with
 *  the ones before it, the meeting's notes, the document's card) under who said what in it (a topic's meetings), with what Sam
 *  can do from it. onVerdict: a tick or a cross on hover (an initiative's full list; it teaches the linker). below: under the
 *  line (a topic's sources: what it said and the files it shares). */
export function ItemRow({ base, x, open, onToggle, pinned, onPin, onUse, onVerdict, said, aside, below }: {
  base: string; x: WorkItem; open: boolean; onToggle: () => void; pinned: boolean; onPin: () => void; onUse: (p: Intent) => void
  onVerdict?: (v: 'confirmed' | 'rejected' | null) => void; said?: { who: string; text: string; clock?: string; app?: string }[]; aside?: ReactNode; below?: ReactNode
}) {
  const I = x.type === 'ask' ? Sparkles : ICON[x.type] ?? FileText
  const readable = x.ref_type !== 'ask' && !!x.ref_id
  const q = useQuery({ queryKey: ['iniRead', x.key], queryFn: () => api.workRead(base, x.ref_type, x.ref_id), enabled: open && readable, staleTime: 300_000, retry: false })
  const [more, setMore] = useState(false)
  const [earlier, setEarlier] = useState(false)
  const r = q.data
  const href = r?.open || x.app || x.url
  const long = (r?.text?.length ?? 0) > 1400
  return (
    <div id={`ini-${x.key}`} className={cn('group border-b border-line2 last:border-0', open && 'bg-panel2/40')}>
      <div className="flex items-center gap-2.5 px-3 py-2 hover:bg-panel2">
        <button onClick={onToggle} aria-expanded={open} title={x.reason || x.gist || x.title} className="flex min-w-0 flex-1 items-center gap-2.5 text-left">
          <ChevronRight size={13} aria-hidden className={cn('shrink-0 text-ink3 transition-transform', open && 'rotate-90')} />
          {x.type === 'doc' ? <FileIcon name={x.title} /> : <I size={14} aria-label={KIND_LABEL[x.type] ?? 'Item'} className="shrink-0 text-ink3" />}
          <span className="min-w-0 flex-1 truncate text-[13.5px]">{x.title}{x.who && <span className="text-ink3"> · {x.who}</span>}</span>
        </button>
        {aside}
        {pinned && <Pin size={12} aria-label="Working from this" className="shrink-0 text-ink" />}
        {onVerdict && x.verdict !== 'confirmed' && <span className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100">
          <button onClick={() => onVerdict('confirmed')} title="Belongs here" aria-label="Confirm link" className="p-1 text-ink3 hover:text-ink"><Check size={13} /></button>
          <button onClick={() => onVerdict('rejected')} title="Not about this initiative" aria-label="Remove link" className="p-1 text-ink3 hover:text-hot"><X size={13} /></button></span>}
        <span className="w-[52px] shrink-0 text-right text-[12px] tabular-nums text-ink3">{day(x.ts)}</span>
      </div>
      {below}
      {open && <div className="px-4 pb-3 md:pl-[52px]">
        {said && said.length > 0 && <ul className="mb-2 space-y-1 border-l-2 border-ink/70 pl-3">{said.map((s, i) => <li key={i} className="text-[13px] leading-snug">
          <span className="font-semibold">{s.who === 'you' ? 'You' : s.who}</span>
          {s.clock && (s.app ? <a href={s.app} className="ml-1 text-[12px] font-normal text-ink3 no-underline hover:underline">at {s.clock}</a> : <span className="ml-1 text-[12px] text-ink3">at {s.clock}</span>)}
          <span className="text-ink2">: {s.text}</span></li>)}</ul>}
        {readable && q.isLoading && <p className="py-1 text-[12.5px] text-ink3">Reading…</p>}
        {readable && q.isError && <p className="py-1 text-[12.5px] text-ink2">{x.gist || 'Not available here.'}{' '}<span className="text-ink3">(only a summary is kept after 30 days, and private items are not shown)</span></p>}
        {r && <>
          <div className="text-[12px] text-ink3">{[r.who && (r.to ? `${r.who} → ${r.to}` : r.who), r.ts && day(r.ts), r.note].filter(Boolean).join(' · ')}</div>
          {r.earlier.length > 0 && <div className="mt-1.5">
            <button onClick={() => setEarlier(!earlier)} aria-expanded={earlier} className="inline-flex items-center gap-1 text-[12px] text-ink2 hover:text-ink">
              {earlier ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}{r.kind === 'chat' ? 'Messages before' : 'Earlier in the thread'} · {r.earlier.length}</button>
            {earlier && <div className="mt-1 space-y-1.5 border-l-2 border-line pl-3">{r.earlier.map((e, i) => <div key={i} className="text-[12.5px]"><span className="font-medium">{e.who}</span>
              <span className="text-ink3"> · {day(e.ts)}</span><div className="whitespace-pre-wrap text-ink2">{e.text}</div></div>)}</div>}
          </div>}
          <div className={cn('mt-1.5 whitespace-pre-wrap text-[13.5px] leading-relaxed', !more && long && 'max-h-[260px] overflow-hidden [mask-image:linear-gradient(to_bottom,black_75%,transparent)]')}>{r.text || x.gist}</div>
          {long && <button onClick={() => setMore(!more)} className="mt-1 text-[12.5px] font-medium text-ink2 hover:text-ink">{more ? 'Show less' : 'Show all'}</button>}
          {r.attachments.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1.5 text-[12px] text-ink2">{r.attachments.map((a) => <span key={a} className="inline-flex max-w-[260px] items-center gap-1 rounded-full border border-line px-2 py-px"><Paperclip size={11} aria-hidden className="shrink-0" /><span className="truncate">{a}</span></span>)}</div>}
        </>}
        <div className="mt-2 flex flex-wrap items-center gap-1">
          {readable && <>
            <button onClick={onPin} aria-pressed={pinned} title="Pick it for the email, document, decision or question above" className={cn(act, pinned && 'bg-panel2')}>
              <Pin size={13} aria-hidden />{pinned ? 'Working from this' : 'Work from this'}</button>
            <button onClick={() => onUse('email')} title="Write an email about it in Ask SleePO" className={act}><Mail size={13} aria-hidden />Email about it</button>
            <button onClick={() => onUse('document')} title="Create a document from it in Ask SleePO" className={act}><FileText size={13} aria-hidden />Document from it</button>
            <button onClick={() => onUse('decide')} title="Decide on it in Ask SleePO" className={act}><Scale size={13} aria-hidden />Decide on it</button>
          </>}
          {href && <a href={href} target={href.startsWith('http') ? '_blank' : undefined} rel="noopener" className={cn(act, 'ml-auto font-normal no-underline')}>
            <ExternalLink size={13} aria-hidden />{x.type === 'mail' ? 'Open in Inbox' : x.type === 'meeting' ? 'Open meeting' : x.type === 'chat' ? 'Open in Messages' : x.type === 'ask' ? 'Open the chat' : 'Open'}</a>}
        </div>
      </div>}
    </div>
  )
}
