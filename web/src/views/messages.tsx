// Messages: Teams and Slack in one place, as conversations (DMs, group chats, channels) with their messages.
// Each row is a message as the pull stored it, verbatim (Sam, 22 Oct 2026: the raw messages, no summaries; rows from older
// pulls that hold only a one-line summary are left out).
// The list is laid out like the Inbox (Sam, 22 Oct 2026): a switch between All, Teams and Slack, a search pill and chips (All,
// Direct, Groups, Channels). The open conversation reads like a chat (Sam, 22 Oct 2026): bubbles, his own on the right, date
// chips that stay in view, and one conversation per person for direct messages however the pulls named them, across Teams and
// Slack together (Sam, 22 Oct 2026: Gray on both is one conversation; Both | Teams | Slack inside it). The list is just photo,
// name, the apps and the date. Read state stays in Teams and Slack: SleePO cannot sync it, so it shows none.
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, ChevronDown, ExternalLink, RefreshCw, FileText, Hash, Link2, MessageSquare, Paperclip, PenLine, Search as SearchIcon, Users as UsersIcon } from 'lucide-react'
import { api, type ChatFull, type MsgItem, type Person } from '@/lib/api'
import { cn, hue, usePersisted } from '@/lib/util'
import { Avatar, Empty, Loading, Markdown, AvatarStack, Segmented } from '@/components/ui'
import { AssistPill, type PillAction } from '@/components/AssistPill'
import { openChatThread } from '@/components/Chat'
import { Logo } from '@/components/Logo'
import { tidyChat as tidy } from '@/components/ChatMessage'
import { ListResizer } from '@/components/ListResizer'
import { TZ, ago, dayKey, hm as time, LOCALE } from '@/lib/time'
import { usePageTitle, useSearchSync } from '@/lib/nav'
import { isMe, mentionsMe } from '@/lib/profile'
import { PersonLink } from '@/components/PersonLink'

const fullWhen = (ts: string) => new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(ts))
const short = (ts: string, today: string) => /T00:00:00Z$/.test(ts) && ts.startsWith('2026-01-01') ? 'no date' : dayKey(ts) === today && time(ts) !== '00:00' && !/T00:00:00Z$/.test(ts) ? time(ts) : new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short' }).format(new Date(ts))
// Some imported rows carry only a date (midnight UTC); don't show a fake 00:00/01:00 time for those.
const dateOnly = (ts: string) => /T00:00:00Z$/.test(ts)
// Rows imported without a real date carry a 1 January placeholder.
const undated = (ts: string) => ts.startsWith('2026-01-01T00:00:00')
// The date chip: Today, Yesterday, else the weekday and date (with the year when it is not this year)
function dayChip(key: string, today: string) {
  if (key === 'undated') return 'Date not recorded'
  if (key === today) return 'Today'
  if (key === dayKey(new Date(Date.parse(today + 'T12:00:00Z') - 86_400_000).toISOString())) return 'Yesterday'
  return new Intl.DateTimeFormat(LOCALE, { weekday: 'long', day: 'numeric', month: 'long', ...(key.slice(0, 4) !== today.slice(0, 4) && { year: 'numeric' }), timeZone: 'UTC' }).format(new Date(key))
}
const isSam = (n: string | null) => mentionsMe(n)   // the user (lib/profile)

// A reviewed file's chip says so, and opens the conversation its review lives in (components/ChatReview.tsx). Reviews start
// from Review beside a message's bubble, which opens the message in Ask SleePO (Bubble).
function FullBody({ f, onReviewed }: { f: ChatFull; onReviewed?: (att: number) => void }) {
  const shown = new Set((f.body ?? '').match(/https?:\/\/[^)\s]+/g) ?? [])
  const extra = f.links.filter((l) => !shown.has(l.url))
  return (
    <div className="text-[13px] leading-snug [overflow-wrap:anywhere] [&_.md_p]:my-0.5 [&_.md>*:first-child]:mt-0 [&_.md>*:last-child]:mb-0">
      <div className="md"><Markdown>{tidy(f.body ?? '')}</Markdown></div>
      {(extra.length > 0 || f.attachments.length > 0) && <div className="mt-2 flex flex-wrap gap-1.5">
        {/* a file SleePO has read (the chat pull reads files shared in direct and group chats) carries a tick: the writer and tasks use it */}
        {f.attachments.map((a, k) => { const Icon = /image|pdf|word|sheet|presentation|text/.test(a.content_type || '') || /\.(pptx?|docx?|xlsx?|pdf)$/i.test(a.name || '') ? FileText : Paperclip; const inner = <><Icon size={13} aria-hidden />{a.name || 'attachment'}{a.size ? <span className="text-ink3"> · {Math.max(1, Math.round(a.size / 1024))} KB</span> : null}{a.read && <Check size={12} aria-label="SleePO has read it" className="text-ink3" />}</>
          const done = !!(a as typeof a & { review?: unknown }).review
          const review = onReviewed && done && <button key={'r' + k} onClick={() => onReviewed(a.id)} title="Open the review in Ask SleePO"
            className="-ml-1 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[12px] text-ink2 hover:bg-panel2 hover:text-ink"><span className="grid size-3.5 place-items-center overflow-hidden rounded-full"><Logo size={14} /></span>Reviewed</button>
          const chip = a.url ? <a key={k} href={a.url} target="_blank" rel="noopener" title={a.read ? 'Open the file · SleePO has read it, so replies and tasks can use it' : 'Open the file'} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-0.5 text-[12.5px] font-normal no-underline hover:border-ink">{inner}</a>
            : <span key={k} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-0.5 text-[12.5px]">{inner}</span>
          return review ? <Fragment key={k}>{chip}{review}</Fragment> : chip })}
        {extra.map((l, k) => <a key={'l' + k} href={l.url} target="_blank" rel="noopener" className="inline-flex max-w-[360px] items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-0.5 text-[12.5px] font-normal no-underline hover:border-ink"><Link2 size={13} aria-hidden /><span className="truncate">{l.title || l.url}</span></a>)}
      </div>}
    </div>)
}

type Kind = 'dm' | 'group' | 'channel'
type Source = '' | 'teams' | 'slack'
// Like Slack (Sam, 22 Oct 2026): direct messages with one person, and channels, which here also hold group chats. The list
// shows them as two sections; the chips under the search narrow it to one.
type Section = 'dm' | 'channel'
type Show = '' | Section
const sectionOf = (k: Kind): Section => (k === 'dm' ? 'dm' : 'channel')
const SECTION_LABEL: Record<Section, string> = { dm: 'Direct messages', channel: 'Channels' }
const SECTIONS: Section[] = ['dm', 'channel']
const SOURCES: [Source, string][] = [['', 'All'], ['teams', 'Teams'], ['slack', 'Slack']]
const SHOWS: [Show, string][] = [['', 'All'], ['dm', 'Direct messages'], ['channel', 'Channels']]
const KIND_LABEL: Record<Kind, string> = { dm: 'Direct message', group: 'Group chat', channel: 'Channel' }
// itemKind: the item's own kind from the pull ('channel' for channel posts) wins over the name, which can look like a DM
// ("Acme All channel", "Acme Development (Slack bridge)").
// convKind: the chat's type as the pull stored it (dm | group | channel | meeting), when there is one.
function kindOf(thread: string, itemKind?: string, convKind?: string | null): Kind {
  const t = thread.toLowerCase()
  if (convKind === 'channel' || itemKind === 'channel' || t.startsWith('#') || /\bchannel\b|slack bridge/.test(t)) return 'channel'
  // named as one person's chat ("1:1 chat Harper Brook", "DM Rowan", "Chat with Gray Selby (…)"): a DM, whatever the pull stored
  if (/\b1:1\b|^dm\b|^chat with [^,/+]+$|^chat with [^,/+(]+\(/.test(t) && !/\bgroup\b/.test(t)) return 'dm'
  if (convKind === 'group' || convKind === 'meeting' || /\bgroup\b|\bmeeting chat\b/.test(t) || /\S\s*\/\s*\S+\s*\/\s*\S/.test(t)) return 'group'   // "Gray / Tatum / Sam chat"
  if (convKind === 'dm') return 'dm'
  if (t.startsWith('group') || t.startsWith('meeting chat') || /\((group|meeting) chat\)\s*$/.test(t) || /,|\+\s*\d/.test(t)) return 'group'
  return 'dm'
}
// "DM Gray" and "DM Gray Selby" are the same conversation; key on a normalised name.
const convKey = (source: string, thread: string) => `${source}|${thread.trim().replace(/^DM\s+/i, 'DM ').toLowerCase().replace(/^(dm \S+)\s+\S+$/, '$1')}`
const convTitle = (thread: string) => thread.trim() === 'DM' ? 'Direct messages (person not recorded)' : thread.replace(/^DM\s+/i, '').replace(/^Group DM\s+/i, '').replace(/^group chat\s+/i, '').replace(/^meeting chat\s+/i, '').replace(/^channel\s+/i, '') || 'Direct message'
// The pulls name one DM many ways: "DM Gray", "DM: Finley Kirby", "DM with Rowan Lowell", "1:1 chat Ellis Ingram", "Chat with Gray
// Selby (naming prefix)", "Noel Osborne DM", "Ellis Ingram (DM)". The name, and a trailing "(…)" other than "DM" as its topic.
const DM_PREFIX = /^(?:dm\s*:?\s*(?:with\s+)?|1:1\s+chat\s+(?:with\s+)?|chat\s*:?\s*(?:with\s+)?|direct\s+message\s+(?:with\s+)?)/i
function splitDm(thread: string) {
  let t = thread.trim(), topic = ''
  const m = t.match(/\s*\(([^)]*)\)\s*$/)
  if (m) { t = t.slice(0, m.index).trim(); if (!/^dm$/i.test(m[1].trim())) topic = m[1].trim() }
  // "Harper Brook 1:1", "Gray Selby chat", "Chat: Sam, Jules Upton", "Sam / Ellis Ingram": the other person's DM
  const name = t.replace(DM_PREFIX, '').replace(/\s+(dm|1:1|chat)$/i, '').trim()
  const parts = name.split(/\s*[,/]\s*/).filter((x) => x && !isMe(x))
  return { name: parts.length === 1 ? parts[0] : name, topic }
}

type App = 'teams' | 'slack'
const APPS: App[] = ['teams', 'slack']
const APP_NAME: Record<App, string> = { teams: 'Teams', slack: 'Slack' }
type Conv = { key: string; sources: Set<App>; kind: Kind; title: string; person?: Person; items: MsgItem[]; topics: Map<number, string>; last: string }

function SourceLogo({ source, logos, size = 16 }: { source: string; logos: Record<string, string>; size?: number }) {
  const uri = logos[source]
  return uri ? <img src={uri} alt={source === 'teams' ? 'Teams' : 'Slack'} title={source === 'teams' ? 'Microsoft Teams' : 'Slack'} style={{ width: size, height: size }} className="shrink-0 object-contain" />
    : <span className="text-[11px] text-ink3">{source}</span>
}
const KindIcon = ({ kind, size = 13 }: { kind: Kind; size?: number }) => kind === 'channel' ? <Hash size={size} aria-hidden className="shrink-0 text-ink2" /> : kind === 'group' ? <UsersIcon size={size} aria-hidden className="shrink-0 text-ink2" /> : <MessageSquare size={size} aria-hidden className="shrink-0 text-ink2" />

// Refresh: pull Teams and Slack now (Sam, 22 Oct 2026). The server runs the same connector pull as the morning refresh, in
// the background (minutes); this polls it, then reloads the conversations. "pulled 2 h ago" says how fresh they are.
function ChatRefresh() {
  const qc = useQueryClient()
  const st = useQuery({ queryKey: ['msgRefresh'], queryFn: api.messagesRefreshStatus, refetchInterval: (q) => (q.state.data?.running ? 5000 : 60000) })
  const [err, setErr] = useState('')
  const was = useRef(false)
  const d = st.data
  useEffect(() => {   // a run just ended: reload what it brought in
    if (was.current && d && !d.running) for (const k of ['items', 'chat', 'today', 'loops']) qc.invalidateQueries({ queryKey: [k] })
    was.current = !!d?.running
  }, [d?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  const run = async () => {
    setErr('')
    try { qc.setQueryData(['msgRefresh'], await api.messagesRefresh()) } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
  }
  const note = err || (d?.running ? '' : d?.finished && d.note ? d.note : d?.last ? ago(d.last) : '')
  return (
    <>
      <span className={cn('ml-auto min-w-0 truncate text-[12px]', err || d?.ok === false ? 'text-hot' : 'text-ink3')} title={d?.note || (d?.last ? `Teams and Slack last pulled ${new Date(d.last).toLocaleString(LOCALE)}` : '')}>{note}</span>
      <button onClick={run} disabled={!!d?.running} title={d?.running ? 'Pulling Teams and Slack: usually under a minute' : 'Pull new Teams and Slack messages now (usually under a minute; read only)'}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2 disabled:opacity-60">
        <RefreshCw size={13} aria-hidden className={cn(d?.running && 'animate-spin')} />{d?.running ? 'Pulling…' : 'Refresh'}</button>
    </>
  )
}

export function Messages({ open }: { open?: number; review?: number } = {}) {   // review: an older link's ?review=, no longer used
  const teams = useQuery({ queryKey: ['items', 'teams'], queryFn: () => api.items('teams') })
  const slack = useQuery({ queryKey: ['items', 'slack'], queryFn: () => api.items('slack') })
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const full = useQuery({ queryKey: ['chat'], queryFn: api.chat })
  const [st, setSt] = usePersisted('assist-msgs-v4', { source: '' as Source, show: '' as Show, noise: false, folded: [] as Section[] })
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const [listW, setListW] = usePersisted<number>('assist-messages-list-width', 0)   // dragged like the Inbox's list; 0: the default

  const byName = useMemo(() => new Map((people.data ?? []).flatMap((p) => [[p.name.toLowerCase(), p], [p.name.split(' ')[0].toLowerCase(), p]] as const)), [people.data])
  const person = (n: string | null) => (n ? byName.get(n.toLowerCase()) ?? byName.get(n.split(' ')[0].toLowerCase()) : undefined)
  // for merging DMs only a sure match counts: the full name, or a first name nobody else has
  const surePerson = useMemo(() => {
    const ps = (people.data ?? []).filter((p) => p.status !== 'me' && !isSam(p.name))
    const full = new Map(ps.map((p) => [p.name.toLowerCase(), p]))
    const firsts = new Map<string, Person[]>()
    for (const p of ps) { const f = p.name.split(' ')[0].toLowerCase(); firsts.set(f, [...(firsts.get(f) ?? []), p]) }
    return (n: string) => { const k = n.toLowerCase(); const one = firsts.get(k); return full.get(k) ?? (!k.includes(' ') && one?.length === 1 ? one[0] : undefined) }
  }, [people.data])

  const grouped = useMemo(() => {
    const m = new Map<string, Conv>()
    for (const it of [...(teams.data ?? []), ...(slack.data ?? [])]) {
      if (!full.data?.[it.id]) continue   // only a summary is stored for it: not a message
      if (!st.noise && it.noise) continue
      const thread = it.thread || (it.source_id === 'slack' ? 'Slack' : 'Teams')
      const kind = kindOf(thread, it.kind, it.conv_kind)
      let k = convKey(it.source_id, thread), title = convTitle(thread), topic = '', p: Person | undefined
      // a direct message with a known person is one conversation across Teams and Slack
      if (kind === 'dm') { const d = splitDm(thread); p = d.name ? surePerson(d.name) : undefined; if (p) { k = `dm|${p.id}`; title = p.name; topic = d.topic } }
      // a group or meeting chat is one conversation by its id, under one title (the server's conv_title: its topic, else who
      // writes in it), however each pull named it (Sam, 17 Nov 2026: one chat had nine names, so nine rows; assist/chatsync.py)
      else if (kind === 'group' && it.conv_id && it.conv_title) { k = `${it.source_id}|chat|${it.conv_id}`; title = it.conv_title }
      let c = m.get(k)
      if (!c) { c = { key: k, sources: new Set(), kind, title, person: p, items: [], topics: new Map(), last: it.ts }; m.set(k, c) }
      c.sources.add(it.source_id as App)
      c.items.push(it)
      if (topic) c.topics.set(it.id, topic)
      if (it.ts > c.last) c.last = it.ts
      if (!c.person && kind === 'dm' && title.length > c.title.length) c.title = title
    }
    // Two pulls can store one message twice (Slack's own id and a made-up one): show it once. The same message is the same
    // sender in the same app at the same second, or with the same text (20+ characters) within five minutes. The copy kept is
    // the one that links back to the app; a link to the other opens it.
    const alias = new Map<number, number>()
    const bodyOf = (i: MsgItem) => (full.data?.[i.id]?.body ?? '').replace(/\s+/g, ' ').trim().toLowerCase()
    const better = (x: MsgItem, y: MsgItem) => Number(!!x.url) - Number(!!y.url)
    for (const c of m.values()) {
      c.items.sort((a, b) => a.ts.localeCompare(b.ts))
      const kept: MsgItem[] = []
      for (const i of c.items) {
        const t = Date.parse(i.ts), exact = !dateOnly(i.ts) && !i.ts.endsWith(':00Z'), b = bodyOf(i)
        let j = kept.length - 1
        for (; j >= 0 && t - Date.parse(kept[j].ts) <= 5 * 60_000; j--) {
          const k = kept[j]
          if (k.source_id === i.source_id && k.from_name === i.from_name && ((exact && k.ts === i.ts) || (b.length >= 20 && bodyOf(k) === b))) break
        }
        const twin = j >= 0 && t - Date.parse(kept[j].ts) <= 5 * 60_000 ? kept[j] : undefined
        if (!twin) kept.push(i)
        else if (better(i, twin) > 0) { kept[j] = i; alias.set(twin.id, i.id) }
        else alias.set(i.id, twin.id)
      }
      c.items = kept
    }
    return { list: [...m.values()].sort((a, b) => b.last.localeCompare(a.last)), alias }
  }, [teams.data, slack.data, st.noise, surePerson, full.data])
  const convs = grouped.list

  const re = q.trim() ? new RegExp(q.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
  const shown = convs.filter((c) => (!st.source || c.sources.has(st.source)) && (!st.show || sectionOf(c.kind) === st.show)
    && (!re || re.test(c.title) || c.items.some((i) => re.test([i.subject, i.text, i.from_name, full.data?.[i.id]?.body].join(' ')))))
  // nothing chosen: the first conversation as the list shows it (direct messages first, unless folded)
  const order = SECTIONS.filter((x) => !st.folded.includes(x)).flatMap((x) => shown.filter((c) => sectionOf(c.kind) === x))
  const cur = shown.find((c) => c.key === sel) ?? order[0] ?? shown[0]
  useEffect(() => { if (cur && cur.key !== sel) setSel(cur.key) }, [cur, sel])
  // inside a conversation on both apps: Both, Teams or Slack. It opens on the app chosen at the top, or Both.
  const [viewFor, setViewFor] = useState<{ key: string; v: Source } | null>(null)
  const view: Source = cur && viewFor?.key === cur.key ? viewFor.v : st.source
  // Review beside a bubble (Sam, 29 Oct 2026): the message, its files and their context open in Ask SleePO, which waits for
  // what he wants done (assist/message_chat.py); Reviewed on a file's chip reopens the conversation its review lives in
  const [reviewErr, setReviewErr] = useState('')
  const [opening, setOpening] = useState<number | null>(null)
  const inChat = async (f: () => Promise<{ thread: string }>) => {
    setReviewErr('')
    try { openChatThread((await f()).thread) } catch (e) { setReviewErr(e instanceof Error ? e.message : String(e)) }
  }
  const openMessage = async (item: number) => { setOpening(item); await inChat(() => api.messageChat(item)); setOpening(null) }
  const openReview = (att: number) => inChat(() => api.reviewChat(att))

  // Back returns here (lib/nav.ts, the header's Back button): the address keeps the open conversation as ?open=<its newest
  // message>, replacing the entry, and the page names it for the Back label.
  // Until a link in the address has opened its conversation, the address is left alone (the first conversation in the list
  // would otherwise overwrite it on load, and the two would fight).
  const opened = useRef<number | undefined>(undefined)
  const newest = cur ? cur.items[cur.items.length - 1]?.id ?? null : null
  useSearchSync('open', open && opened.current !== open ? open : newest)
  usePageTitle(cur?.title)
  // A link to one message (?open=<item id>, from the brief, open items, search, or Back): open its conversation and show it.
  // The address catching up with the conversation on screen is not a link. A conversation's newest message is where it
  // opens anyway, so only an earlier message is scrolled to and ringed.
  const [hitId, setHitId] = useState<number | null>(null)
  useEffect(() => {
    if (!open || opened.current === open || !teams.data || !slack.data || !full.data) return
    if (open === newest) { opened.current = open; return }
    const target = grouped.alias.get(open) ?? open
    const c = convs.find((x) => x.items.some((i) => i.id === target))
    if (!c) { if (!st.noise) setSt({ ...st, noise: true }); return }   // maybe filtered as noise: show noise, then try again
    opened.current = open
    if ((st.source && !c.sources.has(st.source)) || (st.show && st.show !== sectionOf(c.kind))) setSt({ ...st, source: '', show: '' })
    if (st.folded.includes(sectionOf(c.kind))) setSt({ ...st, folded: st.folded.filter((x) => x !== sectionOf(c.kind)) })   // unfold its section
    setQ(''); setSel(c.key); setViewFor({ key: c.key, v: '' })
    const last = c.items[c.items.length - 1]?.id === target
    setHitId(last ? null : target)
    if (!last) setTimeout(() => { pinned.current = false; document.getElementById(`msg-${target}`)?.scrollIntoView({ block: 'center' }) }, 80)
  }, [open, convs]) // eslint-disable-line react-hooks/exhaustive-deps

  // Open each conversation at the latest message, and stay pinned to the bottom while full bodies load in,
  // unless Sam has scrolled up to read.
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  useLayoutEffect(() => { pinned.current = true }, [cur?.key])
  useLayoutEffect(() => {
    const el = scroller.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [cur?.key, cur?.items.length, full.data, q, view])

  if (!teams.data || !slack.data || !meta.data || !full.data) return <Loading />
  const today = meta.data.built_iso
  const logos = meta.data.logos
  const hiddenNoise = st.noise ? 0 : [...teams.data, ...slack.data].filter((i) => i.noise && full.data?.[i.id] && (!st.source || i.source_id === st.source)).length
  const msgs = cur ? cur.items.filter((i) => (!view || i.source_id === view) && (!re || re.test([i.subject, i.text, i.from_name, full.data?.[i.id]?.body].join(' ')) || re.test(cur.title))) : []
  const dk = (ts: string) => (undated(ts) ? 'undated' : dayKey(ts))
  const days = [...new Set(msgs.map((i) => dk(i.ts)))]
  const srcs = cur ? APPS.filter((a) => cur.sources.has(a)) : []
  const both = srcs.length > 1
  const mixed = both && !view   // both apps on screen: each run says which one it is in
  const linkOf = (a: App) => cur && [...cur.items].reverse().find((i) => i.source_id === a && i.url)?.url
  const latest = cur ? [...cur.items].reverse().find((i) => !view || i.source_id === view) : undefined   // what the reply pill works on

  // Who is in a conversation: senders other than Sam, most active first (for the stacked avatars).
  const members = (c: Conv) => {
    const n = new Map<string, number>()
    for (const i of c.items) if (i.from_name && !isSam(i.from_name)) n.set(i.from_name, (n.get(i.from_name) ?? 0) + 1)
    // group chats are often named after their members ("Kai, Mark, Sam (group chat)"): include those who have not posted yet
    if (c.kind === 'group') for (const raw of c.title.replace(/\((group|meeting) chat\)\s*$/i, '').split(/,|\band\b/)) {
      const nm = raw.replace(/\+\s*\d+.*$/, '').trim()
      const p = nm && person(nm)
      if (p && !isSam(p.name) && ![...n.keys()].some((k) => k.split(' ')[0] === p.name.split(' ')[0])) n.set(p.name, 0)
    }
    return [...n.entries()].sort((x, y) => y[1] - x[1]).map(([name]) => name)
  }
  const chip = (on: boolean) => cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12.5px] font-medium transition-colors', on ? 'border-ink bg-ink text-bg' : 'border-line text-ink hover:border-ink')
  const curMembers = cur && cur.kind !== 'dm' ? members(cur) : []

  const row = (c: Conv) => {
    const p = c.person ?? (c.kind === 'dm' ? person(c.title) : undefined)
    const ms = !p && c.kind !== 'dm' ? members(c) : []
    const on = cur?.key === c.key
    const face = (n: string, cls: string) => <span className={cn('absolute rounded-full ring-2', on ? 'ring-accentbg' : 'ring-panel', cls)}><Avatar p={person(n) ?? { name: n, avatar: '' }} size={19} /></span>
    return (
      <button key={c.key} onClick={() => setSel(c.key)} aria-current={on ? 'true' : undefined} title={c.title}
        className={cn('flex w-full items-center gap-2.5 border-l-2 py-1.5 pl-3.5 pr-4 text-left transition-colors', on ? 'border-l-accent bg-accentbg' : 'border-l-transparent hover:bg-panel2')}>
        {p ? <Avatar p={p} size={28} />
          : ms.length > 1 ? <span className="relative size-7 shrink-0">{face(ms[0], 'left-0 top-0')}{face(ms[1], 'bottom-0 right-0')}</span>
          : <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-line bg-panel2"><KindIcon kind={c.kind} /></span>}
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{c.title}</span>
        <span className="flex shrink-0 items-center gap-1">{APPS.filter((x) => c.sources.has(x)).map((x) => <SourceLogo key={x} source={x} logos={logos} size={12} />)}</span>
        <span className="w-[44px] shrink-0 text-right text-[11.5px] tabular-nums text-ink3">{short(c.last, today)}</span>
      </button>)
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      {/* conversation list, with the Inbox's controls above it */}
      <aside aria-label="Conversations" style={listW ? ({ '--list-w': `${listW}px` } as CSSProperties) : undefined}
        className={cn('relative flex max-h-[45vh] min-h-0 w-full flex-col border-b border-line bg-panel md:max-h-none md:shrink-0 md:border-b-0 md:border-r', listW ? 'md:w-[min(var(--list-w),50vw)]' : 'md:w-[clamp(300px,30vw,400px)]')}>
        <ListResizer width={listW} onChange={setListW} label="Resize the conversation list" />
        <div className="border-b border-line px-4 pt-3">
          <h1 className="sr-only">Messages</h1>
          <div className="flex items-center gap-2">
          <Segmented size="md" label="Source" value={st.source} onChange={(k) => { setSel(null); setSt({ ...st, source: k }) }}
            options={SOURCES.map(([k, l]) => [k, <>{k && <SourceLogo source={k} logos={logos} size={14} />}{l}</>] as const)} />
          <ChatRefresh />
          </div>
          <label className="relative mt-2.5 block">
            <SearchIcon size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink3" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search messages, people" aria-label="Search messages"
              className="w-full rounded-full border border-line bg-bg py-1.5 pl-8 pr-3 text-[13px] text-ink outline-none transition-colors placeholder:text-ink3 focus:border-ink" />
          </label>
          <div role="radiogroup" aria-label="Show" className="flex flex-wrap gap-1.5 py-2.5">
            {SHOWS.map(([k, l]) => <button key={k || 'all'} role="radio" aria-checked={st.show === k} onClick={() => { setSel(null); setSt({ ...st, show: k }) }} className={chip(st.show === k)}>{l}</button>)}
          </div>
        </div>
        <nav className="min-h-0 flex-1 overflow-auto">
          {shown.length === 0 && <div className="p-4"><Empty>{q ? 'No conversations match.' : 'Nothing here.'}</Empty></div>}
          {SECTIONS.map((sec) => {
            const list = shown.filter((c) => sectionOf(c.kind) === sec)
            if (!list.length || (st.show && st.show !== sec)) return null
            const folded = st.folded.includes(sec)
            return (
              <section key={sec} aria-label={SECTION_LABEL[sec]}>
                <button onClick={() => setSt({ ...st, folded: folded ? st.folded.filter((x) => x !== sec) : [...st.folded, sec] })} aria-expanded={!folded}
                  className="sticky top-0 z-[1] flex w-full items-center gap-1.5 border-b border-line2 bg-panel px-3 py-1.5 text-left text-[12.5px] font-semibold text-ink hover:bg-panel2">
                  <ChevronDown size={14} aria-hidden className={cn('text-ink2 transition-transform', folded && '-rotate-90')} />
                  {sec === 'dm' ? <MessageSquare size={13} aria-hidden className="text-ink2" /> : <Hash size={13} aria-hidden className="text-ink2" />}
                  {SECTION_LABEL[sec]}<span className="font-normal tabular-nums text-ink3">{list.length}</span></button>
                {!folded && list.map(row)}
              </section>)
          })}
          {(hiddenNoise > 0 || st.noise) && <div className="px-4 py-4 text-[12.5px] text-ink2">
            {st.noise ? <>Showing bots, notifications and other noise. <button onClick={() => setSt({ ...st, noise: false })} className="font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Hide them</button></>
              : <>{hiddenNoise.toLocaleString()} bot and notification messages hidden. <button onClick={() => setSt({ ...st, noise: true })} className="font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Show them</button></>}
          </div>}
        </nav>
      </aside>

      {/* the conversation, as a chat */}
      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col bg-bg">
        {cur ? <>
          <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-panel px-5 py-2">
            {cur.person ? <Link to="/people/$id" params={{ id: cur.person.id }} aria-label={cur.person.name}><Avatar p={cur.person} size={36} /></Link>
              : curMembers.length > 1 ? <AvatarStack names={curMembers} person={person} size={28} max={3} linked />
              : <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-full border border-line bg-panel2"><KindIcon kind={cur.kind} size={16} /></span>}
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-[15.5px] font-semibold leading-tight">
                {cur.person ? <Link to="/people/$id" params={{ id: cur.person.id }} className="text-ink no-underline hover:underline">{cur.title}</Link> : cur.title}</h2>
              <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12px] text-ink2">
                {!both && srcs.map((a) => <SourceLogo key={a} source={a} logos={logos} size={12} />)}
                <span className="truncate">{cur.person?.title && `${cur.person.title} · `}{!both && `${srcs.map((a) => APP_NAME[a]).join(' and ')} · `}{KIND_LABEL[cur.kind]}{curMembers.length > 0 && <> · with {curMembers.slice(0, 4).map((n, k) => <span key={n}>{k > 0 && ', '}<PersonLink id={person(n)?.id}>{n.split(' ')[0]}</PersonLink></span>)}{curMembers.length > 4 && ` +${curMembers.length - 4}`}</>} · {msgs.length} message{msgs.length === 1 ? '' : 's'}</span>
              </div>
            </div>
            {both && <Segmented label="App" value={view} onChange={(k) => setViewFor({ key: cur.key, v: k })}
              options={(['', ...srcs] as Source[]).map((k) => [k, <>{k ? <><SourceLogo source={k} logos={logos} size={13} />{APP_NAME[k]}</> : 'Both'}
                <span className="text-[11px] tabular-nums text-ink3">{k ? cur.items.filter((i) => i.source_id === k).length : cur.items.length}</span></>] as const)} />}
            {(view ? [view as App] : srcs).map((a) => { const url = linkOf(a); return url && (
              <a key={a} href={url} target="_blank" rel="noopener" title={`Open this conversation in ${APP_NAME[a]}`}
                className="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-ink no-underline transition-colors hover:bg-panel2 active:bg-line">
                <SourceLogo source={a} logos={logos} size={13} /><ExternalLink size={12} aria-hidden /><span className="sr-only">Open in {APP_NAME[a]}</span></a>) })}
          </header>
          <div ref={scroller} onScroll={(e) => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }} className="flex-1 overflow-auto">
            <div className="mx-auto max-w-[820px] px-4 pb-4 md:px-6">
              {days.map((d) => {
                const day = msgs.filter((i) => dk(i.ts) === d)
                return (
                  <section key={d} aria-label={dayChip(d, today)}>
                    {/* the date stays in view while its messages scroll under it */}
                    <div className="sticky top-0 z-[1] flex justify-center pb-0.5 pt-2">
                      <span className="rounded-full border border-line bg-panel px-2.5 py-px text-[11px] font-medium text-ink2 shadow-sm">{dayChip(d, today)}</span>
                    </div>
                    {day.map((i, n) => {
                      const prev = n > 0 ? day[n - 1] : undefined
                      const topic = cur.topics.get(i.id) ?? ''
                      const newTopic = !!topic && topic !== (prev ? cur.topics.get(prev.id) ?? '' : '')
                      // a run: the same sender, within ten minutes, same topic; the name and avatar show once
                      const first = !prev || prev.from_name !== i.from_name || newTopic || Date.parse(i.ts) - Date.parse(prev.ts) > 10 * 60_000
                        || (mixed && prev.source_id !== i.source_id)   // a run stays in one app
                      return <Fragment key={i.id}>
                        {newTopic && <div className="mt-2 text-center text-[11px] text-ink3">{topic}</div>}
                        <Bubble i={i} f={full.data?.[i.id]} first={first} p={person(i.from_name)} hit={i.id === hitId} src={mixed ? <SourceLogo source={i.source_id} logos={logos} size={12} /> : undefined} onOpen={openMessage} opening={opening === i.id} onReviewed={openReview} />
                      </Fragment>
                    })}
                  </section>)
              })}
              {msgs.length === 0 && <div className="pt-6"><Empty>No messages match.</Empty></div>}
              {reviewErr && <p role="alert" className="mt-2 text-center text-[12.5px] text-hot">{reviewErr}</p>}
            </div>
          </div>
          {/* where a chat app has its message box: the assistant pill (Sam, 16 Nov 2026: "replace that with this pill, which would
              then send me to draft a reply, but open it in the assistant ... with quick actions"; components/AssistPill.tsx). The reply
              is written in Ask SleePO on this conversation (its chip) as a Teams or Slack card, copied from there; never sent. */}
          {srcs.length > 0 && <div className="border-t border-line bg-panel py-2.5 pl-4 pr-20">{/* clear of the floating Ask SleePO button */}
            {/* the context it passes (components/AssistContext.tsx): this conversation's latest message in the app on screen, so the
                chat holds the conversation, shows its chip (who, and the latest message) and writes the reply for that app */}
            <AssistPill key={cur.key} className="mx-auto max-w-[820px]" target={latest ? { kind: 'message', ref: String(latest.id) } : null}
              {...replyPill(cur.person?.name.split(' ')[0])} note="Opens in Ask SleePO · nothing is sent" />
          </div>}
        </> : <div className="grid h-full place-items-center p-6 text-[13.5px] text-ink2">Select a conversation.</div>}
      </section>
    </div>
  )
}

// The reply pill's actions: what to ask Ask SleePO about the conversation on screen. Each is a short question in Sam's words
// (it shows as his question in the chat); what he typed in the pill's field goes with it.
function replyPill(first?: string) {
  const to = first ? ` to ${first}` : ''
  const with_ = (q: string, d: string) => (d ? `${q} Also: ${d}` : q)
  const reply = (label: string, how: string): PillAction => ({ label, prompt: (d) => with_(`Draft my reply${to}: ${how}.`, d) })
  return {
    field: { placeholder: `What should your reply${to} say? Optional`, label: 'What the reply should say' },
    actions: [{ label: 'Draft a reply', icon: PenLine, prompt: (d: string) => d ? `Draft my reply${to}, in my voice. It should say: ${d}` : `Draft my reply to ${first ? `${first}'s` : 'the'} latest message, in my voice.` }],
    quick: [
      reply('Agree and confirm next steps', 'agree and confirm the next steps, with owners and dates where the conversation has them'),
      reply('Ask for more detail', 'ask for the details I still need, as specific questions'),
      reply('Propose a time to talk', 'propose two times to talk this week that suit my calendar'),
      reply('Push back', 'push back, with the reason in a line'),
      reply('Decline politely', 'decline politely, with the reason in a line'),
      { label: 'Summarise', prompt: (d: string) => with_('Summarise this conversation: what was asked, what was agreed, and what is still open on each side.', d) },
    ] as PillAction[],
  }
}

// One message as a chat bubble (Sam, 22 Oct 2026: more colour, no dotted edges): others on the left under their avatar and
// name, each person in a soft tint of their own colour (msg-them, index.css; the hue comes from the name), Sam's own on the
// right in pale volt (msg-mine). A message that is nothing but emoji shows large, without a bubble. The time is on the first
// of a run, and on hover.
const EMOJI_ONLY = /^(?:\p{Extended_Pictographic}|\p{Emoji_Component}|\uFE0F|\u200D|\s){1,16}$/u
function Bubble({ i, f, first, p, hit, src, onOpen, opening, onReviewed }: { i: MsgItem; f?: ChatFull; first: boolean; p?: Person; hit: boolean; src?: ReactNode
  onOpen?: (item: number) => void; opening?: boolean; onReviewed?: (att: number) => void }) {
  const mine = isSam(i.from_name)
  const app = i.source_id === 'slack' ? 'Slack' : 'Teams'
  const t = !dateOnly(i.ts) && !undated(i.ts) && time(i.ts) !== '00:00' ? time(i.ts) : ''
  const raw = (f?.body ?? '').trim()
  const emoji = !!f && !f.attachments.length && EMOJI_ONLY.test(raw) && /\p{Extended_Pictographic}/u.test(raw)
  const content = f && <FullBody f={f} onReviewed={onReviewed} />
  // on hover, beside the bubble: open the message in Ask SleePO, which waits for Sam to say what to do with it. Drawn as a
  // small copy of the assistant's own badge (Sam, 29 Oct 2026: "look like the assistant icon"): the volt circle with the
  // SleePO face, which snores while the conversation opens.
  const review = onOpen && <button onClick={() => onOpen(i.id)} disabled={opening} title="Review in Ask SleePO: opens this message, its files and context in the assistant, then you say what you want done"
    aria-label="Review in Ask SleePO"
    className={cn('mb-0.5 inline-flex shrink-0 items-center gap-1 rounded-full bg-accent py-0.5 pl-0.5 pr-2.5 text-[12px] font-semibold text-onaccent ring-1 ring-ink/20 shadow-[0_3px_10px_-4px_rgba(0,0,0,0.45)] transition-[opacity,transform] hover:scale-105 active:scale-95 focus:opacity-100 group-hover:opacity-100',
      opening ? 'opacity-100' : 'opacity-0')}>
    <span className="grid size-5 shrink-0 place-items-center overflow-hidden rounded-full"><Logo size={20} animate={opening} /></span>{opening ? 'Opening…' : 'Review'}</button>
  const open = i.url && <a href={i.url} target="_blank" rel="noopener" aria-label={`Open in ${app}`} title={`Open in ${app}`}
    className="mb-1 shrink-0 rounded-full p-1 text-ink2 opacity-0 transition-opacity hover:bg-panel2 hover:text-ink focus:opacity-100 group-hover:opacity-100"><ExternalLink size={12} aria-hidden /></a>
  const box = cn('min-w-0 rounded-2xl px-3 py-1.5 shadow-[0_1px_1px_rgb(0_0_0/0.04)]', hit && 'ring-2 ring-accent ring-offset-2 ring-offset-bg')
  const when = !undated(i.ts) ? fullWhen(i.ts) : undefined
  const bubble = (cls: string) => emoji ? <div title={when} className={cn('px-1 text-[32px] leading-tight', hit && 'rounded-2xl ring-2 ring-accent')}>{raw}</div>
    : <div title={when} className={cn(box, cls)}>{content}</div>
  if (mine) return (
    <div id={`msg-${i.id}`} className={cn('group flex justify-end', first ? 'mt-2' : 'mt-0.5', i.noise && 'opacity-55')}>
      <div className="flex min-w-0 max-w-[85%] flex-col items-end">
        {first && <div className="mb-0.5 flex items-center gap-1.5 px-1 text-[11px] text-ink3">{src}You{t && ` · ${t}`}</div>}
        <div className="flex items-end gap-1">{open}{review}{bubble(cn('msg-mine', first && 'rounded-tr-md'))}</div>
      </div>
    </div>)
  const name = i.from_name || 'Unknown'
  return (
    <div id={`msg-${i.id}`} style={{ '--h': hue(name) } as CSSProperties} className={cn('group flex gap-2', first ? 'mt-2' : 'mt-0.5', i.noise && 'opacity-55')}>
      <div className="w-7 shrink-0 pt-[18px]">{first && (p ? <Link to="/people/$id" params={{ id: p.id }} aria-label={p.name}><Avatar p={p} size={28} /></Link> : <Avatar p={{ name: name === 'Unknown' ? '?' : name, avatar: '' }} size={28} />)}</div>
      <div className="flex min-w-0 max-w-[85%] flex-col items-start">
        {first && <div className="mb-0.5 flex items-baseline gap-2 px-1">
          {p ? <Link to="/people/$id" params={{ id: p.id }} className="msg-name text-[12px] font-semibold no-underline hover:underline">{name}</Link> : <span className="msg-name text-[12px] font-semibold">{name}</span>}
          {t && <span className="text-[11.5px] tabular-nums text-ink3">{t}</span>}
          {src && <span className="self-center">{src}</span>}
        </div>}
        <div className="flex max-w-full items-end gap-1">{bubble(cn('msg-them', first && 'rounded-tl-md'))}{review}{open}</div>
      </div>
    </div>)
}
