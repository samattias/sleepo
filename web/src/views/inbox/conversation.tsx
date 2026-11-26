// The open email: the conversation as cards, Brief me, Open in Outlook, the ⋯ menu and the answer panel.
// Above the thread only what matters at a glance (Sam, 18 Nov 2026: "a lot of content that I guess I rarely use ... too much
// clutter"): the subject with its state (waiting on you, replied, sent; why on hover), the task the thread belongs to when
// it is surely on his list, and the briefing once he asks for one. Needs response, linking to a task (and SleePO's unsure
// matches), what it is linked to, related items and the original email are in the ⋯ menu. Every name and photo of a person
// SleePO knows opens their page (Sam, 18 Nov 2026: "every name is a hot link to the person's page").
import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ArrowLeft, Check, ChevronDown, ChevronsUpDown, FilePlus2, FileText, Link2, ListChecks, Forward, Image as ImageIcon, MessageSquarePlus, MoreHorizontal, Plus, RefreshCw, Reply, ReplyAll, ScrollText, Search as SearchIcon, X, type LucideIcon } from 'lucide-react'
import { OutlookLogo } from '@/components/OutlookLogo'
import { ItemLinks } from '@/components/ItemLinks'
import { PersonLink } from '@/components/PersonLink'
import { api, type MailFull, type Person, type ThreadItem } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { hasRemoteImages, splitThread } from '@/lib/emailhtml'
import { Avatar, Empty, Loading, RetentionDays, Tag, popoverClass } from '@/components/ui'
import { AttachmentChip, Body, EmailFrame } from '@/components/Email'
import { DocumentCreator } from '@/components/DocumentCreator'
import { TaskCreator } from '@/components/TaskCreator'
import { USE_DRAFT } from '@/components/Chat'
import { Briefing } from '@/components/Briefing'
import { PlainText } from '@/components/PlainText'
import { fullWhen as fullWhenOf } from '@/lib/time'
import { Composer } from './composer'
import { type Entry, type Mode, type Panel, type Who, isMe, nm, primaryBtn, toolBtn, typing } from './model'

// ---- the conversation: every message on its own card, oldest first, the selected one open; then the reply.
// It is the history quoted inside the selected email plus every other stored message of the thread (MailFull.thread,
// received and sent: Sam's own replies, other branches, later answers) that the quote does not already hold, in time order.
// raw: the date as the message gives it; load: a stored message the email does not quote, read when its card opens.
// who wrote the folded messages, in order, first names: "Gray, Rowan and you", "Gray, Rowan, Ellis and 2 others"
const folded = (xs: { from: string; me: boolean }[]) => {
  const names = [...new Set(xs.filter((x) => !x.me).map((x) => (x.from || '').replace(/\s*\(.*\)$/, '').split(/[\s,@]+/)[0]).filter(Boolean))]
  const all = [...names.slice(0, 3), ...(names.length > 3 ? [`${names.length - 3} other${names.length > 4 ? 's' : ''}`] : []), ...(xs.some((x) => x.me) ? ['you'] : [])]
  return all.length > 1 ? `${all.slice(0, -1).join(', ')} and ${all.at(-1)}` : all[0] ?? ''
}
type Msg = { key: string; from: string; address: string; date: string; raw: string; to: string; cc: string; snippet: string; latest: boolean; me: boolean; html?: string; text?: string; load?: number }
const fullWhen = fullWhenOf
// Quoted header dates come in the sender's language ("lundi, 12 octobre 2026 à 09:56", "Montag, 12. Oktober 2026 09:56"):
// drop the weekday, put the month in English, then show it like the rest of the app.
const MONTHS: Record<string, string> = { janvier: 'January', 'février': 'February', fevrier: 'February', mars: 'March', avril: 'April', mai: 'May', juin: 'June', juillet: 'July', 'août': 'August', aout: 'August',
  septembre: 'September', octobre: 'October', novembre: 'November', 'décembre': 'December', decembre: 'December', januar: 'January', februar: 'February', 'märz': 'March', juni: 'June', juli: 'July',
  oktober: 'October', dezember: 'December' }
const english = (d: string) => d.replace(/^\s*[\p{L}]+day,?\s*|^\s*(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag),?\s*/iu, '')
  .replace(/\p{L}+/gu, (w) => MONTHS[w.toLowerCase()] ?? w).replace(/\s(?:at|à|um)\s/g, ' ').replace(/(\d)\.\s/, '$1 ').replace(/(\d{1,2})h(\d{2})/, '$1:$2')
const whenOf = (d: string) => Date.parse(english(d))   // NaN when it cannot be read
const msgWhen = (d: string) => {
  const t = whenOf(d)
  if (Number.isNaN(t)) return english(d)
  return fullWhenOf(t)
}

const words = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
// "Selby, Harper" is "Harper Brook"; a quote that gives no name leaves it to the text and the time
function samePerson(a: string, aAddr: string, b: string, bAddr: string) {
  if (aAddr && bAddr && aAddr.toLowerCase() === bAddr.toLowerCase()) return true
  const x = new Set(words(a).split(' ').filter((w) => w.length > 1)), y = words(b).split(' ').filter((w) => w.length > 1)
  return !x.size || !y.length || y.filter((w) => x.has(w)).length >= Math.min(2, x.size, y.length)
}
// How sure a quoted message is a stored one: 2 for the same opening words, 1 for the same minute (give or take the
// writer's time zone, which quoted dates leave out), 0 when it is someone else's.
function likeness(q: Msg, s: ThreadItem) {
  if (q.me !== s.me || (!q.me && !samePerson(q.from, q.address, s.from_name, s.from_address))) return 0
  const a = words(q.snippet), b = words(s.snippet)
  const text = (a.length >= 12 && b.includes(a.slice(0, 30))) || (b.length >= 12 && a.includes(b.slice(0, 30)))
  const diff = Math.abs(whenOf(q.raw) - Date.parse(s.ts))
  const time = diff < 14 * 3600e3 && Math.min(diff % 1800e3, 1800e3 - (diff % 1800e3)) < 120e3
  return (text ? 2 : 0) + (time ? 1 : 0)
}
// chain: the selected email and the history it quotes, oldest first. A quoted message that is also stored takes the stored
// time; one that is not (older than the mailbox, or between other people) keeps its place in the chain.
function merge(chain: Msg[], thread: ThreadItem[], sel: { id: number; ts: string }): Msg[] {
  const rest = thread.filter((t) => t.id !== sel.id)
  const used = new Set<number>()
  const out = chain.map((q) => {
    if (q.latest) return { ...q, at: Date.parse(sel.ts) as number | null }
    let best: ThreadItem | null = null, score = 0
    for (const s of rest) { const k = used.has(s.id) ? 0 : likeness(q, s); if (k > score) { best = s; score = k } }
    if (!best) return { ...q, at: null as number | null }
    used.add(best.id)
    return { ...q, date: fullWhen(best.ts), at: Date.parse(best.ts) as number | null }
  })
  for (let i = out.length - 2; i >= 0; i--) {   // the last one is the selected email, always placed
    if (out[i].at != null) continue
    const hi = out[i + 1].at!, lo = out.slice(0, i).reverse().find((x) => x.at != null)?.at ?? -Infinity
    const t = whenOf(out[i].raw)
    out[i].at = t > lo && t < hi ? t : hi - 1
  }
  const stored = rest.filter((s) => !used.has(s.id)).map((s) => ({ key: `s${s.id}`, from: s.from_name || s.from_address, address: s.from_address, date: fullWhen(s.ts), raw: s.ts,
    to: s.to, cc: s.cc, snippet: s.snippet, latest: false, me: s.me, load: s.id, at: Date.parse(s.ts) as number | null }))
  return [...out, ...stored].sort((a, b) => a.at! - b.at!).map(({ at: _, ...x }) => x)
}
// toolbar buttons: soft, borderless pills that show on hover (Sam, 22 Oct 2026: the square bordered ones looked blocky);
// the main action of the toolbar (Reply, or Follow up on Sam's own mail) is the one filled button

export function Conversation({ m, who, onBack, onNeeds }: { m: Entry; who: Who; onBack: () => void; onNeeds?: () => void }) {
  const full = useQuery({ queryKey: ['mailOne', m.id], queryFn: () => api.mailOne(m.id) })
  const d = full.data
  const rich = d?.body_type === 'html' && !!d.body
  const conv = useQuery({ queryKey: ['mailConv', m.id], queryFn: () => api.mailConversation(m.id), enabled: !!d && d.full && !rich })
  // Sam's own email: follow up with the same people, or forward it; anything else: reply, reply all, forward
  const [mode, setMode] = useState<Mode>(m.sent ? 'followup' : 'reply')
  const [remote, setRemote] = useState(false)
  const [original, setOriginal] = useState(false)
  const [more, setMore] = useState(false)
  const ask = useRef<HTMLTextAreaElement>(null)
  const docAsk = useRef<HTMLTextAreaElement>(null)
  const briefAsk = useRef<HTMLTextAreaElement>(null)
  const [tab, setTab] = useState<Panel>('reply')   // the panel's tab: Draft response or Create document
  const [briefSignal, setBriefSignal] = useState(0)
  // a task proposed for this email in the background (the Tasks session's preplan): a dot on the Create task tab
  const proposal = useQuery({ queryKey: ['taskProposal', m.id], queryFn: () => api.taskProposal(m.id), enabled: !m.sent })   // the b key: open the briefing's focus box at the top
  const [opened, setOpened] = useState<Panel[]>(['reply'])   // a tab mounts the first time it is chosen, then keeps its plan or briefing
  const panel = useRef<HTMLDivElement>(null)
  // The subject stays in view (Sam, 22 Oct 2026): once the big title scrolls under the toolbar, a slim copy shows below it.
  // It hangs off the sticky bar (absolute), so showing it never moves the page and cannot flicker.
  const bar = useRef<HTMLDivElement>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const [titleGone, setTitleGone] = useState(false)
  useEffect(() => {
    const el = title.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => setTitleGone(!e.isIntersecting && e.boundingClientRect.top < (e.rootBounds?.top ?? 0)),
      { root: el.closest('section'), rootMargin: `-${bar.current?.offsetHeight ?? 44}px 0px 0px 0px` })   // the conversation pane scrolls, not the page
    io.observe(el); return () => io.disconnect()
  }, [])
  const focus = (el: RefObject<HTMLTextAreaElement | null>, scroll: boolean) => requestAnimationFrame(() => {
    if (scroll) panel.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    el.current?.focus({ preventScroll: true })
  })
  const startReply = (k: Mode, scroll = true) => { setTab('reply'); setMode(k); focus(ask, scroll) }
  const taskAsk = useRef<HTMLTextAreaElement>(null)
  const startTab = (t: 'doc' | 'task', scroll = true) => { setTab(t); setOpened((o) => (o.includes(t) ? o : [...o, t])); focus(t === 'doc' ? docAsk : taskAsk, scroll) }
  // Brief me (b): writes a briefing when there is none, else shows or hides the one there is (kept hidden by default)
  const briefQ = useQuery({ queryKey: ['briefing', m.id], queryFn: () => api.briefing(m.id), enabled: !!d?.full })
  const brief = briefQ.data?.briefing ?? null
  const [briefHidden, setBriefHidden] = usePersisted<boolean>(`assist-briefing-hidden-${m.id}`, true)
  const briefBox = useRef<HTMLDivElement>(null)
  const startBrief = () => {
    if (!briefQ.data) return   // not known yet whether one exists
    if (brief) setBriefHidden(!briefHidden); else setBriefSignal((n) => n + 1)
    requestAnimationFrame(() => briefBox.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  }
  const [showLinks, setShowLinks] = useState(false)   // "Linked to", opened from the ⋯ menu
  const [pickTask, setPickTask] = useState(false)   // the task picker, opened from the ⋯ menu
  const navigate = useNavigate()
  useEffect(() => {   // a draft from the chat: show it on the Draft response tab
    const on = (e: Event) => { if ((e as CustomEvent<{ mail: number }>).detail?.mail === m.id) startReply(mode) }
    window.addEventListener(USE_DRAFT, on); return () => window.removeEventListener(USE_DRAFT, on)
  })
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (typing(e)) return
      const keys: Record<string, Mode> = m.sent ? { r: 'followup', a: 'followup', f: 'forward' } : { r: 'reply', a: 'replyall', f: 'forward' }
      const mk = keys[e.key]
      if (mk && d?.full) { e.preventDefault(); startReply(mk) }
      if (e.key === 'c' && d?.full) { e.preventDefault(); startTab('doc') }
      if (e.key === 't' && d?.full) { e.preventDefault(); startTab('task') }
      if (e.key === 'b' && d?.full) { e.preventDefault(); startBrief() }
      if (e.key === 'e' && onNeeds) { e.preventDefault(); onNeeds() }
      if (e.key === 'Escape' && !matchMedia('(min-width: 768px)').matches) onBack()   // phone: back to the list
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  })

  const split = useMemo(() => (d && rich ? splitThread(d.body!, { from: nm(d.from), address: d.from.address, date: d.ts, to: d.to.map(nm).join(', '), cc: d.cc.map(nm).join(', '), subject: d.subject ?? '' }) : null), [d, rich])
  const msgs: Msg[] = useMemo(() => {
    const chain: Msg[] = split ? split.msgs.map((x, i) => ({ ...x, key: `h${i}`, raw: x.date, me: isMe(x.from + ' ' + x.address), date: x.latest ? fullWhen(x.date) : msgWhen(x.date) })).reverse()
      : (conv.data?.messages ?? []).map((x, i) => ({ key: `t${i}`, from: x.from, address: '', raw: x.latest ? m.ts : x.date, date: x.latest ? fullWhen(m.ts) : msgWhen(x.date),
          to: x.to, cc: x.cc, snippet: x.text.replace(/\s+/g, ' ').slice(0, 220), latest: x.latest, me: x.me, text: x.text }))
    return chain.length && d ? merge(chain, d.thread, d) : chain
  }, [split, conv.data, m.ts, d])
  const remoteImages = rich && hasRemoteImages(d!.body!)
  // fold the middle: keep the first message, the one before the selected email, it and everything after it
  const here = msgs.findIndex((x) => x.latest)
  const cut = Math.min(here - 1, msgs.length - 2)
  const fold = !more && cut > 2
  const shown = fold ? [msgs[0], null, ...msgs.slice(cut)] : msgs
  const newest = msgs.length - 1 > here ? msgs.at(-1) : undefined   // a later message (often Sam's own reply) opens too
  const files = d ? d.attachments.filter((a) => !a.is_inline || !(d.body ?? '').includes(`cid:${a.content_id}`)) : []
  const them = m.sent ? who(m.to[0] ?? '') : who(m.from_name)   // the person this email is with: sender, or the first recipient of Sam's own
  const actions: [Mode, string, typeof Reply, string][] = m.sent ? [['followup', 'Follow up', MessageSquarePlus, 'r'], ['forward', 'Forward', Forward, 'f']]
    : [['reply', 'Reply', Reply, 'r'], ['replyall', 'Reply all', ReplyAll, 'a'], ['forward', 'Forward', Forward, 'f']]

  return (
    <div className="flex min-h-full flex-col">
      <div ref={bar} className="sticky top-0 z-[2] flex flex-wrap items-center gap-1.5 border-b border-line bg-panel px-4 py-1.5">
        <button onClick={onBack} className={cn(toolBtn, 'md:hidden')}><ArrowLeft size={14} aria-hidden />Inbox</button>
        <button onClick={() => title.current?.closest('section')?.scrollTo({ top: 0, behavior: 'smooth' })} title="Back to the top" tabIndex={titleGone ? 0 : -1} aria-hidden={!titleGone}
          className={cn('absolute inset-x-0 top-full block w-full truncate border-b border-line bg-panel/95 px-5 py-1.5 text-left text-[13.5px] font-semibold text-ink backdrop-blur-sm transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none',
            titleGone ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1 opacity-0')}>{m.subject}</button>
        {d?.full !== false && actions.map(([k, l, Icon, key], i) => <button key={k} onClick={() => startReply(k)} title={`${l} (${key})`} className={i === 0 ? primaryBtn : toolBtn}><Icon size={14} aria-hidden />{l}</button>)}
        <span aria-hidden className="mx-1 h-5 w-px bg-line max-sm:hidden" />
        {d?.full && <button onClick={startBrief} aria-pressed={brief ? !briefHidden : undefined} className={cn(toolBtn, brief && !briefHidden && 'bg-panel2')}
          title={!brief ? 'Brief me on this thread: where it stands, how it got here, who wants what and what is open (b)' : briefHidden ? 'Show the briefing (b)' : 'Hide the briefing (b)'}>
          <ScrollText size={14} aria-hidden />{brief ? 'Briefing' : 'Brief me'}</button>}
        {d && <OpenInOutlook id={m.id} fallback={d.web_link} />}
        <EmailMenu items={[
          onNeeds ? { label: m.needs ? 'No response needed' : 'Add to Needs response', icon: m.needs ? X : Plus, kbd: 'e', onClick: onNeeds,
            note: !m.sent && !m.answered && m.why ? (m.needs ? `Waiting on you: ${m.why}` : `Not waiting on you: ${m.why}`) : undefined } : null,
          d?.full ? { label: 'Link to a task…', icon: ListChecks, onClick: () => setPickTask(true) } : null,
          { label: showLinks ? 'Hide what it is linked to' : 'What it is linked to', icon: Link2, onClick: () => setShowLinks(!showLinks), note: 'People, companies, bets and documents' },
          'sep',
          { label: 'Find related', icon: SearchIcon, onClick: () => navigate({ to: '/search', search: { q: m.subject.replace(/^((re|fw|fwd|aw|tr):\s*)+/i, '').slice(0, 60) } }) },
          d?.full ? { label: original ? 'Show as conversation' : 'View original', icon: FileText, onClick: () => setOriginal(!original) } : null,
        ]} />
      </div>

      <div className="mx-auto w-full max-w-[1040px] flex-1 px-4 pb-28 pt-5 md:px-8">
        {/* the subject and its state on one line; why it is or is not waiting on Sam is on hover and in the ⋯ menu */}
        <div className="text-[21px] font-semibold leading-snug tracking-[-0.01em]">
          <h2 ref={title} className="inline">{m.subject}</h2>
          {(m.sent || m.answered || m.needs || m.noise) && <span className="ml-2.5 inline-flex -translate-y-0.5 gap-1.5 align-middle" title={!m.sent && !m.answered && m.why ? `${m.needs ? 'Waiting on you' : 'Not waiting on you'}: ${m.why}` : undefined}>
            {m.sent ? <Tag>Sent</Tag> : m.answered ? <Tag tone="good">Replied</Tag> : m.needs ? <Tag tone="pending">Waiting on you</Tag> : null}
            {m.noise && <Tag>noise</Tag>}</span>}
        </div>
        <TaskLinks itemId={m.id} onCreate={d?.full ? () => startTab('task') : undefined} pick={pickTask} setPick={setPickTask} />
        {showLinks && <ItemLinks itemId={m.id} onClose={() => setShowLinks(false)} />}
        {original && <div className="mt-2 text-[12.5px] text-ink2">The original email, as it was sent · <button onClick={() => setOriginal(false)} className="font-medium text-ink underline decoration-line underline-offset-2 hover:decoration-ink">Show as conversation</button></div>}
        <div ref={briefBox} className="scroll-mt-24">
          {d?.full && <Briefing mailId={m.id} who={who} askRef={briefAsk} top runSignal={briefSignal} hidden={briefHidden} onHidden={setBriefHidden} />}
        </div>
        {/* blocked remote images: a quiet notice next to the message it concerns, not a toolbar button */}
        {remoteImages && !remote && !original && d?.full && <div className="mt-3 flex items-center gap-1.5 text-[12px] text-ink2">
          <ImageIcon size={13} aria-hidden />Images hidden to stop tracking.
          <button onClick={() => setRemote(true)} className="font-medium text-ink underline decoration-accent decoration-2 underline-offset-2 hover:decoration-ink">Show images</button></div>}

        {/* the thread as one white card: messages joined by hairlines, opening and folding with a height animation (Sam, 22 Oct 2026) */}
        <div className="mt-4 divide-y divide-line2 overflow-hidden rounded-xl border border-line bg-panel shadow-sm">
          {full.isError ? <div className="p-4"><Empty>Could not load this email.</Empty></div>
            : !d ? <div className="p-4"><Loading /></div>
            : !d.full ? <div className="border-l-2 border-l-hot px-4 py-3 text-[13.5px]">
                <p>Only a one-line summary of this email is stored (full text is kept for the last <RetentionDays /> days), so it cannot be shown or answered here.</p>
                {d.note && <p className="mt-2 text-[14px] leading-relaxed">{d.note}</p>}</div>
            : !rich && !conv.data ? <div className="p-4">{conv.isError ? <Body m={d} /> : <Loading />}</div>
            : original ? <div className="p-4">{d.body != null ? <Body m={d} /> : <p className="text-[13.5px] text-ink2">{m.preview}</p>}</div>
            : shown.map((x) => x === null
              ? <button key="more" onClick={() => setMore(true)} aria-label={`Show ${cut - 1} more messages`}
                  className="group/more relative flex w-full items-center gap-3 bg-panel2/40 px-4 py-2 text-left text-[13px] text-ink2 transition-colors hover:bg-panel2 hover:text-ink">
                  {/* stacked edges: the folded messages read as pages tucked under each other. No number in a circle:
                      in this column a circle reads as a person (Sam, 23 Oct 2026); the icon sits where the photos are */}
                  <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[3px] border-b border-line2" />
                  <span aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-[3px] border-t border-line2" />
                  <span aria-hidden className="flex w-9 shrink-0 justify-center text-ink3 transition-colors group-hover/more:text-ink"><ChevronsUpDown size={16} /></span>
                  <span className="min-w-0 flex-1 truncate"><span className="font-medium text-ink">{cut - 1} more message{cut - 1 > 1 ? 's' : ''}</span>
                    {folded(msgs.slice(1, cut)) && <span className="text-ink3"> · from {folded(msgs.slice(1, cut))}</span>}</span>
                  <span className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-ink2 group-hover/more:text-ink">Show all<ChevronDown size={14} aria-hidden className="transition-transform group-hover/more:translate-y-0.5" /></span></button>
              : <MsgCard key={x.key} x={x} person={who(x.from)} who={who} open={x.latest || x === newest}>
                  {x.load != null ? <StoredBody id={x.load} remote={remote} />
                    : <><MsgBody x={x} mailId={m.id} css={split?.css} remote={remote} attachments={d.attachments} />
                      {x.latest && files.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{files.map((a) => <AttachmentChip key={a.id} mail={d.id} a={a} webLink={d.web_link} />)}</div>}</>}
                </MsgCard>)}
        </div>

        <div ref={panel} className="scroll-mt-24">{/* clear the sticky bar and the subject under it */}
          {d?.full && (
            <section aria-label="Work on this email" className="@container mt-6 rounded-xl border border-line bg-panel shadow-sm">
              {/* narrow panel (a phone, or a small window with three columns): smaller tabs without icons, scrolling sideways if still too wide */}
              <div role="tablist" aria-label="Respond or create a document" className="flex gap-1 overflow-x-auto border-b border-line px-2 [scrollbar-width:none]">
                {([['reply', m.sent ? 'Draft follow-up' : 'Draft response', m.sent ? MessageSquarePlus : Reply, 'r', 'Draft an email in your voice'],
                   ['doc', 'Create document', FilePlus2, 'c', 'Plan a deck, document or workbook that answers this email; Claude builds it'],
                   ['task', 'Create task', ListChecks, 't', 'Turn this email into a task with steps, or add steps to a task you have']] as const).map(([k, l, Icon, key, tip]) =>
                  <button key={k} role="tab" id={`answer-${k}`} aria-selected={tab === k} aria-controls={`answer-${k}-panel`} title={`${tip} (${key})`}
                    onClick={() => (k === 'reply' ? startReply(mode, false) : startTab(k, false))}
                    className={cn('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 py-2.5 text-[14px] @max-lg:px-2 @max-lg:text-[13px]', tab === k ? 'font-semibold text-ink shadow-[inset_0_-2px_0_0_var(--accent)]' : 'text-ink2 hover:text-ink')}>
                    <Icon size={15} aria-hidden className="@max-lg:hidden" />{l}
                    {k === 'task' && proposal.data?.status === 'ok' && <span aria-label="a task is proposed" title={proposal.data.note ?? 'A task is proposed for this email'} className="size-1.5 rounded-full bg-accent ring-1 ring-ink/30" />}</button>)}
              </div>
              <div role="tabpanel" id="answer-reply-panel" aria-labelledby="answer-reply" hidden={tab !== 'reply'}>
                <Composer m={m} d={d} mode={mode} setMode={setMode} askRef={ask} />
              </div>
              {opened.includes('doc') && <div role="tabpanel" id="answer-doc-panel" aria-labelledby="answer-doc" hidden={tab !== 'doc'}>
                <DocumentCreator mailId={m.id} sendTo={them?.name ?? (m.sent ? m.to[0] ?? '' : m.from_name)} askRef={docAsk} />
              </div>}
              {opened.includes('task') && <div role="tabpanel" id="answer-task-panel" aria-labelledby="answer-task" hidden={tab !== 'task'}>
                <TaskCreator mailId={m.id} title={d.subject ?? m.subject ?? ''} askRef={taskAsk} pill />
              </div>}
            </section>)}
        </div>
      </div>
    </div>
  )
}

// The task this email's thread belongs to (Sam, 22 Oct 2026: "the 2027 Dev thread should be linked to the budgeting
// task"). Linked by SleePO when the thread is a source of the task, or matched by a tool-free run (assist/task_links.py).
// Under the subject only a sure link to a task on his list shows, as one quiet line (Sam, 18 Nov 2026: the task chips and
// "Part of …?" questions above every email were clutter he rarely used). The picker, opened from the ⋯ menu, holds the
// rest: SleePO's unsure matches (tick or cross), links to suggested tasks, any open task to link, and Create a task.
// Unlinking sticks.
function TaskLinks({ itemId, onCreate, pick, setPick }: { itemId: number; onCreate?: () => void; pick: boolean; setPick: (v: boolean) => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['itemTasks', itemId], queryFn: () => api.itemTasks(itemId) })
  const [find, setFind] = useState('')
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!pick) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setPick(false) }
    document.addEventListener('mousedown', away); return () => document.removeEventListener('mousedown', away)
  }, [pick, setPick])
  const set = async (tid: number, on: boolean, close = true) => {
    const r = await api.itemTaskLink(itemId, tid, on)
    qc.setQueryData(['itemTasks', itemId], (o: Awaited<ReturnType<typeof api.itemTasks>> | undefined) => (o ? { ...o, linked: r.linked } : o))
    qc.invalidateQueries({ queryKey: ['mail'] })
    if (close) { setPick(false); setFind('') }
  }
  if (!q.data) return null
  const linked = q.data.linked
  const sure = linked.filter((t) => !t.suggested && t.status !== 'suggested')
  const asks = linked.filter((t) => t.suggested || t.status === 'suggested')
  if (!sure.length && !pick) return null
  const choices = q.data.open.filter((t) => !linked.some((l) => l.task_id === t.id) && (!find.trim() || t.title.toLowerCase().includes(find.trim().toLowerCase())))
  const tiny = 'grid size-6 shrink-0 place-items-center rounded-full text-ink2 hover:bg-panel2 hover:text-ink'
  return (
    <div ref={box} className={cn('relative flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]', sure.length > 0 && 'mt-1.5')}>
      {sure.map((t) => (
        <span key={t.task_id} className="group inline-flex min-w-0 max-w-full items-center gap-1.5 text-ink2" title={`${t.why ?? ''}${t.done_when ? ` · done when: ${t.done_when}` : ''}`}>
          <ListChecks size={13} aria-hidden className="shrink-0" />
          <a href={t.url} className="min-w-0 truncate text-ink no-underline hover:underline">{t.title}</a>
          <button onClick={() => set(t.task_id, false)} aria-label="Unlink from this task" title="Not part of this task: unlink"
            className="rounded-full p-0.5 text-ink3 opacity-0 transition-opacity hover:bg-panel2 hover:text-ink focus:opacity-100 group-hover:opacity-100"><X size={12} aria-hidden /></button>
        </span>))}
      {pick && (
        <div className={cn(popoverClass, 'absolute left-0 top-full z-20 mt-1 w-[min(440px,90vw)]')}>
          {asks.length > 0 && <div className="border-b border-line py-1">
            <p className="px-3 pb-0.5 pt-1 text-[11.5px] text-ink3">SleePO thinks it may belong to</p>
            {asks.map((t) => (
              <div key={t.task_id} className="flex items-center gap-1 px-3 py-1 text-[13px]" title={t.why ?? ''}>
                <a href={t.url} className="min-w-0 flex-1 truncate text-ink no-underline hover:underline">{t.title}</a>
                {t.status === 'suggested' && <span className="shrink-0 text-[11.5px] text-ink3">suggested</span>}
                {t.suggested && <button onClick={() => set(t.task_id, true, false)} aria-label={`Yes, part of ${t.title}`} title="Yes, link it" className={tiny}><Check size={13} aria-hidden /></button>}
                <button onClick={() => set(t.task_id, false, false)} aria-label={`Not part of ${t.title}`} title="No, it is not part of this task" className={tiny}><X size={13} aria-hidden /></button>
              </div>))}
          </div>}
          <input autoFocus value={find} onChange={(e) => setFind(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && setPick(false)} placeholder="Find a task to link"
            className="w-full border-b border-line bg-transparent px-3 py-2 text-[13px] text-ink outline-none placeholder:text-ink3" />
          <div className="max-h-[260px] overflow-auto py-1">
            {choices.map((t) => <button key={t.id} onClick={() => set(t.id, true)} className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-panel2">
              <span className="min-w-0 flex-1 truncate">{t.title}</span>
              <span className="shrink-0 text-[11.5px] text-ink3">{t.status === 'suggested' ? 'suggested' : t.initiative ?? t.area ?? ''}</span></button>)}
            {choices.length === 0 && <div className="px-3 py-2 text-[12.5px] text-ink3">No open task matches.</div>}
          </div>
          {onCreate && <button onClick={() => { setPick(false); onCreate() }} className="flex w-full items-center gap-1.5 border-t border-line px-3 py-2 text-left text-[13px] font-medium hover:bg-panel2">
            <Plus size={13} aria-hidden />Create a task from this email</button>}
        </div>)}
    </div>
  )
}

// The ⋯ at the end of the toolbar: what the email view uses less often (Sam, 18 Nov 2026). Each item may carry a second
// line (why SleePO counts the email as waiting on him or not, beside the switch that overrides it) and its key.
type MenuItem = { label: string; icon: LucideIcon; onClick: () => void; note?: string; kbd?: string }
function EmailMenu({ items }: { items: (MenuItem | 'sep' | null)[] }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  const shown = items.filter((x): x is MenuItem | 'sep' => x !== null)
  const rows = shown.filter((x, i) => x !== 'sep' || (i > 0 && shown[i - 1] !== 'sep' && i < shown.length - 1))   // no separator first, last or twice
  return (
    <div ref={box} className="relative ml-auto">
      <button onClick={() => setOpen(!open)} aria-label="More" aria-haspopup="menu" aria-expanded={open} title="More"
        className={cn(toolBtn, 'px-2', open && 'bg-panel2')}><MoreHorizontal size={16} aria-hidden /></button>
      {open && (
        <div role="menu" className={cn(popoverClass, 'absolute right-0 top-[calc(100%+6px)] z-30 w-[300px] py-1')}>
          {rows.map((x, i) => x === 'sep' ? <div key={`s${i}`} role="separator" className="my-1 border-t border-line" />
            : <button key={x.label} role="menuitem" title={x.note} onClick={() => { setOpen(false); x.onClick() }} className="flex w-full items-start gap-2.5 px-3 py-1.5 text-left text-[13px] text-ink hover:bg-panel2">
                <x.icon size={15} aria-hidden className="mt-0.5 shrink-0 text-ink3" />
                <span className="min-w-0 flex-1"><span className="block">{x.label}</span>{x.note && <span className="line-clamp-2 text-[11.5px] leading-snug text-ink3">{x.note}</span>}</span>
                {x.kbd && <kbd className="mt-0.5 shrink-0 rounded border border-line px-1 font-sans text-[11px] text-ink3">{x.kbd}</kbd>}
              </button>)}
        </div>)}
    </div>
  )
}

// Open the email itself in Outlook (Sam, 22 Oct 2026: Outlook is his mail client; Apple Mail only syncs). SleePO holds
// Apple Mail's ids, so the Outlook link is looked up by Message-ID on the click (assist/outlook_drafts.py link). Until he
// has signed in for Outlook, or if it is not found, the email opens in Mail instead and the reason shows on the button.
function OpenInOutlook({ id, fallback }: { id: number; fallback: string | null }) {
  const [state, setState] = useState<'' | 'busy'>('')
  const [why, setWhy] = useState('')
  const go = async () => {
    setState('busy'); setWhy('')
    const w = window.open('', '_blank')
    try { const { web_link } = await api.mailOutlookLink(id); if (w) w.location.href = web_link }
    catch (e) {
      const msg = String(e instanceof Error ? e.message : e)
      if (fallback && w) w.location.href = fallback; else w?.close()
      setWhy(msg)
    }
    setState('')
  }
  return <button onClick={go} disabled={state === 'busy'} title={why ? `${why}${fallback ? ' Opened in Mail instead.' : ''}` : 'Open this email in Outlook'}
    className={cn(toolBtn, 'disabled:opacity-60')}>{state === 'busy' ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : <OutlookLogo size={14} />}Open in Outlook
    {why && <span aria-label={why} className="size-1.5 rounded-full bg-hot" />}</button>
}

// One message of the thread, a section of the thread card. The body mounts the first time it opens (a stored message is
// read then), stays mounted, and slides open or shut (grid rows 0fr <-> 1fr; no animation with reduced motion).
// "Sam Doe, Selby, Harper, Rowan Lowell": each name once, a "Last, First" pair joined when that is someone SleePO knows
function namesIn(s: string, who: Who) {
  const parts = s.split(/\s*[,;]\s*/).filter(Boolean)
  const out: { text: string; p?: Person }[] = []
  for (let i = 0; i < parts.length; i++) {
    const a = parts[i], b = parts[i + 1]
    const pair = b && !who(a) ? who(`${a}, ${b}`) : undefined
    if (pair) { out.push({ text: `${a}, ${b}`, p: pair }); i++ } else out.push({ text: a, p: isMe(a) ? undefined : who(a) })
  }
  return out
}
// names, each a link to the person's page when SleePO knows them
function Names({ s, who }: { s: string; who: Who }) {
  return <>{namesIn(s, who).map((n, i) => <span key={i}>{i > 0 && ', '}{n.p ? <PersonLink id={n.p.id} className="pointer-events-auto">{n.text}</PersonLink> : n.text}</span>)}</>
}

// The header opens and folds the message; the sender's photo and name and the recipients are links to their pages (Sam,
// 18 Nov 2026), so the fold is a button laid under the row and the text lets clicks through to it, except on the links.
function MsgCard({ x, person, who, open: start, children }: { x: Msg; person?: Person; who: Who; open: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(start)
  const [mounted, setMounted] = useState(start)
  const toggle = () => { setMounted(true); setOpen(!open) }
  const linked = x.me ? undefined : person
  return (
    <article className={cn('transition-colors', !open && 'hover:bg-panel2/60')}>
      <div className="relative flex w-full items-start gap-3 px-4 py-3 text-left">
        <button onClick={toggle} aria-expanded={open} aria-label={`${open ? 'Fold' : 'Open'} the message from ${x.me ? 'you' : x.from || 'an unknown sender'}, ${x.date}`}
          className="absolute inset-0 size-full cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ink" />
        <PersonLink id={linked?.id} photo className="relative" title={linked ? `${linked.name}'s page` : undefined}>
          <Avatar p={person ?? { name: x.from || '?', avatar: '' }} size={36} className={linked ? undefined : 'pointer-events-none relative'} /></PersonLink>
        <span className="pointer-events-none relative min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="max-w-[70%] shrink-0 truncate text-[14px] font-semibold">{x.me ? 'You'
              : <PersonLink id={linked?.id} className="pointer-events-auto" title={linked ? `${linked.name}'s page` : undefined}>{x.from || 'Unknown sender'}</PersonLink>}</span>
            {open && x.address && !x.me && <span className="min-w-0 truncate text-[12.5px] text-ink3 max-sm:hidden">&lt;{x.address}&gt;</span>}
            <span className="ml-auto shrink-0 text-[12.5px] tabular-nums text-ink2">{x.date}</span>
          </span>
          {open ? (x.to || x.cc) && <span title={`To: ${x.to}${x.cc ? `\nCc: ${x.cc}` : ''}`} className="block truncate text-[12.5px] text-ink2">to <Names s={x.to} who={who} />{x.cc && <> · cc <Names s={x.cc} who={who} /></>}</span>
            : <span className="block truncate text-[13px] text-ink2">{x.snippet}</span>}
        </span>
      </div>
      <div className={cn('grid transition-[grid-template-rows,opacity] duration-300 ease-out motion-reduce:transition-none', open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0')}>
        <div className="min-h-0 overflow-hidden">
          {mounted && <div className="px-4 pb-4 md:pl-[64px]">{children}</div>}
        </div>
      </div>
    </article>
  )
}

function MsgBody({ x, mailId, css, remote, attachments }: { x: Pick<Msg, 'html' | 'text'>; mailId: number; css?: string; remote: boolean; attachments?: MailFull['attachments'] }) {
  return x.html != null
    ? <div className="mailpaper"><EmailFrame mailId={mailId} html={x.html} css={css} remote={remote} attachments={attachments} /></div>
    : <PlainText text={x.text ?? ''} />
}

// A stored message of the thread that the selected email does not quote (often Sam's own reply, or another branch of the
// thread), read when its card opens: its own words, without the history it quotes, and its attachments.
function StoredBody({ id, remote }: { id: number; remote: boolean }) {
  const q = useQuery({ queryKey: ['mailOne', id], queryFn: () => api.mailOne(id) })
  const d = q.data
  const view = useMemo(() => {
    if (!d) return null
    const head = { from: nm(d.from), address: d.from.address, date: d.ts, to: '', cc: '', subject: d.subject ?? '' }
    const split = d.body_type === 'html' && d.body ? splitThread(d.body, head) : null
    const text = split ? undefined : (d.body ?? d.note ?? '').split(/\n(?:From|De|Von)\s*:/)[0].trim()
    return { html: split?.msgs[0]?.html, text, css: split?.css }
  }, [d])
  if (q.isError) return <p className="text-[13.5px] text-ink2">Could not load this email.</p>
  if (!d || !view) return <Loading />
  const files = d.attachments.filter((a) => !a.is_inline || !(d.body ?? '').includes(`cid:${a.content_id}`))
  return <>
    <MsgBody x={view} mailId={id} css={view.css} remote={remote} attachments={d.attachments} />
    {files.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{files.map((a) => <AttachmentChip key={a.id} mail={id} a={a} webLink={d.web_link} />)}</div>}
  </>
}
