// Everything between Sam and one person, by day: email they sent, received or were copied on, both sides of DMs, group chats
// they are in, meetings they spoke in or attended, invites, and items that only mention them (assist/entities.py links them,
// with a role and the evidence). Each day shows one row per conversation (a chat, an email thread) that opens to its
// messages; a meeting or a lone email is its own row. The last 30 days first; "Show older" reaches back further.
// A tick or cross on a message is Sam's verdict on that link: a crossed link disappears and is never re-added; crossed
// first-name matches teach the linker. compact: the person page's "Recent conversations" (14 days, Sam or them involved).
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Check, ChevronRight, Mail, MessageSquare, NotebookPen, X, type LucideIcon } from 'lucide-react'
import { api, type TimelineItem } from '@/lib/api'
import { cn } from '@/lib/util'
import { Segmented } from './FilterBar'
import { Loading } from './ui'
import { TZ, LOCALE } from '@/lib/time'

const KINDS: Record<string, { group: 'email' | 'messages' | 'meetings'; icon: LucideIcon }> = {
  mail: { group: 'email', icon: Mail }, sent: { group: 'email', icon: Mail },
  chat: { group: 'messages', icon: MessageSquare }, channel: { group: 'messages', icon: MessageSquare }, teams: { group: 'messages', icon: MessageSquare },
  note: { group: 'meetings', icon: NotebookPen }, event: { group: 'meetings', icon: CalendarDays },
}
const WINDOWS = [30, 90, 180, 365]
const dayKey = (iso: string) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(new Date(iso))
const time = (iso: string) => new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(new Date(iso))
function dayLabel(key: string) {
  const today = dayKey(new Date().toISOString())
  const y = new Date(); y.setDate(y.getDate() - 1)
  if (key === today) return 'Today'
  if (key === dayKey(y.toISOString())) return 'Yesterday'
  const d = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(key + 'T12:00:00Z'))
  return key > today ? `Coming up · ${d}` : d
}

// Who and how, in a few words: "From Noel", "You → Noel", "Gray · Noel cc'd", "You · DM", "Noel · group chat Gray, Noel"
const PASSIVE = new Set(['mentioned', 'keyword', 'actor'])   // linked by what the item says, not by taking part in it
function who(t: TimelineItem, first: string) {
  const r = t.link?.role
  if (r === 'mentioned') return `Mentions ${first}`
  if (t.kind === 'note') return r === 'speaker' ? `${first} spoke · ${(t.link?.reason ?? '').replace(/^spoke /, '').replace(/ \(.*\)$/, '')} of the talk` : r === 'attendee' ? `${first} attended` : r === 'invitee' ? `${first} invited` : 'Meeting notes'
  if (t.kind === 'event') return r === 'organizer' ? `Invite · ${first} organised` : 'Invite'
  if (t.where !== undefined) return `${t.mine ? 'You' : t.from || 'Someone'} · ${t.dm ? 'DM' : t.where}`
  if (KINDS[t.kind]?.group === 'messages') return `${t.source === 'slack' ? 'Slack' : 'Teams'} conversation summary`   // older pulls kept a gist, not the messages
  if (t.role === 'from') return `From ${first}`
  if (t.mine) return t.role === 'cc' ? `You · ${first} cc'd` : `You → ${first}`
  return t.role === 'cc' ? `${t.from || 'Someone'} · ${first} cc'd` : `${t.from || 'Someone'} → ${first}`
}

// one conversation on one day: a chat (DM, group or channel) or an email thread by subject; anything else stands alone
const subjectKey = (s: string) => s.toLowerCase().replace(/^\s*((re|fw|fwd|aw|wg|tr)\s*:\s*)+/i, '').replace(/\s+/g, ' ').trim()
// a DM with them is one conversation per app, whatever name the pull gave it (Teams stores the same chat as "DM Gray", "Chat with Gray"…)
const convKey = (t: TimelineItem) => t.where !== undefined ? (t.dm && !PASSIVE.has(t.link?.role ?? '') ? `c:dm:${t.source}` : `c:${t.where}`)
  : KINDS[t.kind]?.group === 'email' && t.title ? `m:${subjectKey(t.title)}` : `i:${t.id}`
// chat gists already start with the speaker ("Gray: …"); add one only when they do not
export const withSpeaker = (who: string, text: string) => /^[A-Z][\w'’.-]*( [A-Z][\w'’.-]*)?:\s/.test(text) ? text : `${who}: ${text}`
type Conv = { key: string; rows: TimelineItem[] }
function convHead(c: Conv, first: string) {
  const t = c.rows[0], n = c.rows.length, mine = c.rows.filter((r) => r.mine).length
  const theirs = c.rows.filter((r) => r.role === 'from' || (!r.mine && r.from && r.from.split(' ')[0] === first)).length
  const parts = [t.where !== undefined ? (t.dm ? 'Teams DM' : t.where) : 'Email thread', `${n} ${t.where !== undefined ? 'messages' : 'emails'}`]
  if (theirs) parts.push(`${theirs} from ${first}`)
  if (mine) parts.push(`${mine} from you`)
  return parts.join(' · ')
}

export function PersonActivity({ id, name, compact, onMore, limit = 8 }: { id: number; name: string; compact?: boolean; onMore?: () => void; limit?: number }) {
  const first = name.split(' ')[0]
  const [days, setDays] = useState(30)
  const [show, setShow] = useState<'all' | 'email' | 'messages' | 'meetings'>('all')
  const [how, setHow] = useState<'all' | 'involved' | 'mentioned'>(compact ? 'involved' : 'all')
  const [open, setOpen] = useState<Set<string>>(new Set())
  const qc = useQueryClient()
  const judge = async (t: TimelineItem, v: 'confirmed' | 'rejected' | null) => { await api.linkVerdict(t.id, 'person', id, v); qc.invalidateQueries({ queryKey: ['entity'] }) }
  const q = useQuery({ queryKey: ['entity', 'person', id, days], queryFn: () => api.entity('person', id, days), placeholderData: (prev) => prev })
  const cutoff = compact ? dayKey(new Date(Date.now() - 13 * 864e5).toISOString()) : ''
  // history only: what is coming up is listed on the page itself. compact also leaves out invites and channel posts
  const items = (q.data?.timeline ?? []).filter((t) => Date.parse(t.ts) <= Date.now() && (!compact || (dayKey(t.ts) >= cutoff && t.kind !== 'channel' && t.kind !== 'event')))
  const count = (g: string) => items.filter((t) => KINDS[t.kind]?.group === g).length
  const days_ = useMemo(() => {
    const out: { key: string; convs: Conv[] }[] = []
    const passive = (t: TimelineItem) => PASSIVE.has(t.link?.role ?? '')
    for (const t of items.filter((t) => (show === 'all' || KINDS[t.kind]?.group === show) && (how === 'all' || (how === 'mentioned') === passive(t)))) {
      const k = dayKey(t.ts)
      if (out.at(-1)?.key !== k) out.push({ key: k, convs: [] })
      const day = out.at(-1)!, ck = convKey(t)
      const c = day.convs.find((x) => x.key === ck)
      if (c) { if (!c.rows.some((r) => r.title === t.title && r.mine === t.mine && Math.abs(Date.parse(r.ts) - Date.parse(t.ts)) < 120e3)) c.rows.push(t) }   // the same message pulled twice
      else day.convs.push({ key: ck, rows: [t] })
    }
    return out
  }, [items, show, how])
  const total = days_.reduce((n, d) => n + d.convs.length, 0)
  const shown = useMemo(() => {   // compact: the newest conversations (limit, eight unless the page says)
    if (!compact) return days_
    const out: typeof days_ = []
    let left = limit
    for (const d of days_) { if (left <= 0) break; out.push({ key: d.key, convs: d.convs.slice(0, left) }); left -= d.convs.length }
    return out
  }, [days_, compact, limit])
  const more = WINDOWS.find((w) => w > days)
  const toggle = (k: string) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const Row = ({ t, inner }: { t: TimelineItem; inner?: boolean }) => { const I = KINDS[t.kind]?.icon ?? Mail; const ext = t.url.startsWith('http'); return (
    <li className="group relative border-b border-line2 last:border-b-0">
      <a href={t.url || undefined} target={ext ? '_blank' : undefined} rel="noopener" className={cn('flex gap-3 px-3 py-2 pr-20 font-normal text-ink no-underline hover:bg-panel2', inner && 'pl-9')}>
        <I size={14} aria-hidden className="mt-[3px] shrink-0 text-ink2" />
        <span className="min-w-0 flex-1">
          <span className="block text-[12px] text-ink2">{who(t, first)}</span>
          <span className="line-clamp-2 text-[13.5px] leading-snug [overflow-wrap:anywhere]">{t.title || t.snippet || '(no subject)'}</span>
          {PASSIVE.has(t.link?.role ?? '') && t.link?.reason && <span className="mt-0.5 block line-clamp-1 text-[12px] italic text-ink2">{t.link.reason}</span>}
        </span>
        <span className="shrink-0 pt-px text-[12px] tabular-nums text-ink2">{time(t.ts)}</span>
      </a>
      <Verdict v={t.link?.verdict ?? null} onSet={(v) => judge(t, v)} />
    </li>) }
  return (
    <section className={compact ? '' : 'mb-6'}>
      {!compact && <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-[15px] font-semibold">Activity with {first} <span className="font-normal text-ink2">· last {days} days · {total} conversation{total === 1 ? '' : 's'}</span></h2>
        <div className="ml-auto flex flex-wrap gap-2"><Segmented value={how} onChange={setHow} options={[['all', 'Any link'], ['involved', `${first} involved`], ['mentioned', 'Mentioned only']]} />
          <Segmented value={show} onChange={setShow}
          options={[['all', `All · ${items.length}`], ['email', `Email · ${count('email')}`], ['messages', `Messages · ${count('messages')}`], ['meetings', `Meetings · ${count('meetings')}`]]} /></div>
      </div>}
      {!q.data ? <Loading /> : shown.length === 0 ? <p className="text-[13px] text-ink2">Nothing with {first} in the last {compact ? 14 : days} days.</p> : (
        <div className="border border-line bg-panel">
          {shown.map((d) => (
            <div key={d.key}>
              <div className={cn('z-[1] border-b border-line2 bg-panel2 px-3 py-1 text-[12px] font-semibold', !compact && 'sticky top-[86px]')}>{dayLabel(d.key)}</div>
              <ol>{d.convs.map((c) => { const k = d.key + c.key; if (c.rows.length === 1) return <Row key={k} t={c.rows[0]} />
                const t = c.rows[0], on = open.has(k), I = KINDS[t.kind]?.icon ?? Mail, last = c.rows[c.rows.length - 1]; return (
                <li key={k} className="border-b border-line2 last:border-b-0">
                  <button onClick={() => toggle(k)} aria-expanded={on} className="flex w-full gap-3 px-3 py-2 text-left hover:bg-panel2">
                    <I size={14} aria-hidden className="mt-[3px] shrink-0 text-ink2" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12px] text-ink2">{convHead(c, first)}</span>
                      <span className="line-clamp-2 text-[13.5px] leading-snug [overflow-wrap:anywhere]">{t.where !== undefined ? withSpeaker(t.mine ? 'You' : (t.from || first).split(' ')[0], t.title || t.snippet) : t.title || t.snippet || '(no subject)'}</span>
                    </span>
                    <span className="flex shrink-0 items-start gap-1.5 pt-px text-[12px] tabular-nums text-ink2">{time(last.ts)}–{time(t.ts)}<ChevronRight size={14} className={cn('transition-transform', on && 'rotate-90')} /></span>
                  </button>
                  {on && <ol className="border-t border-line2 bg-bg/40">{c.rows.map((r) => <Row key={r.id} t={r} inner />)}</ol>}
                </li>) })}</ol>
            </div>))}
        </div>)}
      {compact ? (total > limit && onMore && <button onClick={onMore} className="mt-2 text-[13px] font-medium underline decoration-accent decoration-2 underline-offset-2">{total - limit} more in the last 14 days</button>)
        : more && q.data && <button onClick={() => setDays(more)} disabled={q.isFetching} className="mt-2 text-[13px] font-medium underline decoration-accent decoration-2 underline-offset-2 disabled:opacity-50">
        {q.isFetching ? 'Loading…' : `Show older (last ${more} days)`}</button>}
    </section>
  )
}

// Tick: the link is right (kept whatever the linker later thinks). Cross: wrong, hide it for good. Shown on hover.
export function Verdict({ v, onSet }: { v: 'confirmed' | 'rejected' | null; onSet: (v: 'confirmed' | 'rejected' | null) => void }) {
  return (
    <span className={cn('absolute right-2 top-2 flex gap-0.5', v ? '' : 'opacity-0 focus-within:opacity-100 group-hover:opacity-100')}>
      <button onClick={() => onSet(v === 'confirmed' ? null : 'confirmed')} aria-label="Link is right" title={v === 'confirmed' ? 'Confirmed: click to undo' : 'This link is right'}
        className={cn('rounded-full border p-0.5', v === 'confirmed' ? 'border-ink bg-ink text-bg' : 'border-line bg-panel hover:border-ink')}><Check size={12} /></button>
      {v !== 'confirmed' && <button onClick={() => onSet('rejected')} aria-label="Wrong link" title="Not about this person: hide it"
        className="rounded-full border border-line bg-panel p-0.5 hover:border-ink"><X size={12} /></button>}
    </span>
  )
}
