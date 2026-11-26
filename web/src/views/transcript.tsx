// Transcript view for one meeting: the conversation as turns, with talk-time, search, a speaker filter and the summary.
// Granola records two channels: Sam's microphone and everyone else on the call. Granola names the speakers on the second
// channel from the call's display names (Teams, Zoom, Meet); unnamed lines fall back to the 1:1 name from the calendar
// (marked as inferred) or "Others".
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronDown, ChevronUp, ExternalLink, FileText, MessageSquareText, Search, Users, Video } from 'lucide-react'
import { api, type Shot, type Turn } from '@/lib/api'
import { cn } from '@/lib/util'
import { Avatar, btnClass, Empty, Input, Loading, Markdown, selectClass } from '@/components/ui'
import { Segmented } from '@/components/FilterBar'
import { ItemLinks } from '@/components/ItemLinks'
import { ShotRow, ShotViewer } from '@/components/MeetingShots'
import { TZ, LOCALE } from '@/lib/time'
import { AssistPill } from '@/components/AssistPill'
import { useAssistChip } from '@/components/AssistContext'
import { meetingPill } from '@/lib/assistPills'
import { PersonLink } from '@/components/PersonLink'

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
const when = (iso: string) => new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(iso.endsWith('Z') ? iso : iso + 'Z'))
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function highlight(text: string, re: RegExp | null, base: number, current: number) {
  if (!re) return text
  const out: ReactNode[] = []
  let last = 0, i = 0
  for (const m of text.matchAll(re)) {
    out.push(text.slice(last, m.index))
    const n = base + i++
    out.push(<mark key={m.index} data-hit={n} className={cn(n === current && 'outline outline-2 outline-ink')}>{m[0]}</mark>)
    last = (m.index ?? 0) + m[0].length
  }
  out.push(text.slice(last))
  return out
}

export function TranscriptPage({ id, q: initial, at }: { id: string; q?: string; at?: number }) {
  const q = useQuery({ queryKey: ['transcript', id], queryFn: () => api.transcript(id) })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const [tab, setTab] = useState<'transcript' | 'speakers' | 'summary'>('transcript')
  const [mark, setMark] = useState<number | undefined>(at)   // a moment to show: from a link (?t=) or a point in Who said what
  const [who, setWho] = useState<string>('all')   // all | me | others | a speaker's name
  const [term, setTerm] = useState(initial ?? '')
  const [cur, setCur] = useState(0)
  const box = useRef<HTMLDivElement>(null)
  const target = /^m-\d+$/.test(id) ? { kind: 'meeting', ref: id.slice(2) } : null   // what the assistant pill passes
  const chip = useAssistChip(target)

  const t = q.data
  const re = term.trim().length >= 2 ? new RegExp(esc(term.trim()), 'gi') : null
  const turns = useMemo(() => (t?.turns ?? []).filter((x) => who === 'all' || (who === 'me' ? x.me : who === 'others' ? !x.me : x.speaker === who)), [t, who])
  // hit offsets per turn, so every <mark> gets a global index for next / previous
  const { offsets, total } = useMemo(() => {
    const offs: number[] = []; let n = 0
    for (const x of turns) { offs.push(n); if (re) n += (x.lines.join(' ').match(re) ?? []).length }
    return { offsets: offs, total: n }
  }, [turns, re?.source]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setCur(0) }, [term, who])
  useEffect(() => { box.current?.querySelector(`[data-hit="${cur}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, [cur, total])
  const step = (d: number) => total && setCur((c) => (c + d + total) % total)
  // the turn holding the marked moment: the last one starting at or before it
  const markedT = mark == null ? undefined : (t?.turns ?? []).reduce<number | undefined>((best, x) => (x.t <= mark + 5 ? x.t : best), undefined)
  useEffect(() => {
    if (markedT == null || tab !== 'transcript') return
    const go = () => box.current?.querySelector(`[data-t="${markedT}"]`)?.scrollIntoView({ block: 'center' })
    const h = setTimeout(go, 50); return () => clearTimeout(h)
  }, [markedT, tab, t])
  const jump = (sec: number) => { setWho('all'); setTerm(''); setMark(sec); setTab('transcript') }
  const [shot, setShot] = useState<number | null>(null)   // the screenshot open full size
  const shots = useMemo(() => (t?.shots ?? []).filter((s) => s.t != null), [t])
  // screenshots go after the last turn that started at or before their moment (those before the first turn go first)
  const shotsAt = useMemo(() => {
    const at = new Map<number, Shot[]>()
    for (const s of shots) {
      const i = turns.reduce((best, x, k) => (x.t <= s.t! ? k : best), -1)
      at.set(i, [...(at.get(i) ?? []), s])
    }
    return at
  }, [shots, turns])

  if (q.isError) return <Empty>This meeting has no transcript to show.</Empty>
  if (!t) return <Loading />
  const me = people.data?.find((p) => p.status === 'me')
  const other = people.data?.find((p) => p.name === t.other_label)
  const words = t.words ?? { me: 0, others: 0 }
  const share = words.me + words.others ? Math.round((100 * words.me) / (words.me + words.others)) : 0
  const otherName = t.other_inferred ? t.other_label : 'Others'
  const speakers = (t.speakers ?? []).filter((s) => s.words >= 40)
  const all = words.me + words.others
  const pct = (w: number) => (all ? Math.round((100 * w) / all) : 0)
  const unnamed = words.others - (t.speakers ?? []).reduce((a, s) => a + s.words, 0)
  const nameOf = (x: Turn) => x.me ? 'You' : x.speaker ?? otherName
  const avatarOf = (x: Turn) => x.me ? me : x.speaker ? people.data?.find((p) => p.name === x.speaker) : other

  return (
    <div className="max-w-[980px]">
      <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">{t.title}</h1>
      {t.calendar_title && t.calendar_title !== t.title && <div className="mt-0.5 text-[13.5px] text-ink2">Calendar: {t.calendar_title}</div>}
      <div className="mt-1 text-[13.5px] text-ink2">{when(t.starts_at)}{t.duration ? ` · ${Math.max(1, Math.round(t.duration / 60))} min` : ''}{t.segments ? ` · ${t.segments} turns` : ''}{shots.length ? ` · ${shots.length} screenshot${shots.length === 1 ? '' : 's'}` : ''}</div>
      {t.speakers_split && <div className="mt-1.5 max-w-[680px] rounded-lg bg-panel2 px-3 py-1.5 text-[12.5px] text-ink2">Recorded on your microphone only (a phone call), so Granola put every line under you. SleePO split the speakers from what was said; a few short replies are best guesses.</div>}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {t.attendees.map((n) => { const p = people.data?.find((x) => x.name === n); return p
          ? <Link key={n} to="/people/$id" params={{ id: p.id }} className="inline-flex items-center gap-1.5 rounded-full border border-line py-0.5 pl-0.5 pr-2.5 text-[13px] font-normal text-ink no-underline hover:border-ink"><Avatar p={p} size={20} />{n}</Link>
          : <span key={n} className="inline-flex items-center rounded-full border border-line px-2.5 py-0.5 text-[13px]">{n}</span> })}
        <span className="ml-auto flex flex-wrap gap-2">
          {t.granola && <a href={t.granola} target="_blank" rel="noopener" className={btnClass('outline', 'sm', 'font-normal text-ink')}><Video size={14} />Granola</a>}
          {t.outlook && <a href={t.outlook} target="_blank" rel="noopener" className={btnClass('outline', 'sm', 'font-normal text-ink')}><ExternalLink size={14} />Outlook</a>}
          <Link to="/explore/library/$" params={{ _splat: t.id }} className={btnClass('outline', 'sm', 'font-normal text-ink')}><FileText size={14} />Notes in library</Link>
        </span>
      </div>
      {/* the assistant pill (Sam, 16 Nov 2026): what was agreed, what I owe, the follow-up email, with the meeting's chip */}
      {target && chip && <AssistPill className="mt-3 max-w-[860px]" target={target} {...meetingPill(false)} />}

      {t.item_id && <ItemLinks itemId={t.item_id} />}
      {t.turns.length > 0 && (
        <div className="mt-4">
          {speakers.length ? (
            <div className="mb-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px]"><span><b>You</b> {share}%</span>
              {speakers.map((s) => <span key={s.name}><b>{s.name}</b> {pct(s.words)}%</span>)}
              {pct(unnamed) > 0 && <span className="text-ink2">unnamed {pct(unnamed)}%</span>}</div>
          ) : (
            <div className="mb-1 flex justify-between text-[12.5px]"><span><b>You</b> {share}%</span><span><b>{otherName}</b>{t.other_inferred && <span className="text-ink2"> (inferred)</span>} {100 - share}%</span></div>
          )}
          <div className="flex h-2 border border-line"><div className="bg-accent" style={{ width: `${share}%` }} /><div className="flex-1 bg-ink" /></div>
        </div>
      )}

      <div className="sticky top-12 z-10 mt-4 flex flex-wrap items-center gap-2 border-b border-line bg-bg py-2">
        <div role="tablist" className="inline-flex rounded-full bg-panel2 p-0.5">
          {([['transcript', 'Transcript', MessageSquareText], ...(t.by_speaker?.some((s) => s.points.length) ? [['speakers', 'Who said what', Users] as const] : []), ['summary', 'Summary', FileText]] as const).map(([k, l, I]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={cn('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] transition-colors', tab === k ? 'bg-panel font-semibold text-ink shadow-sm' : 'text-ink2 hover:text-ink')}><I size={14} />{l}</button>
          ))}
        </div>
        {tab === 'transcript' && t.turns.length > 0 && <>
          {speakers.length > 1
            ? <select aria-label="Speaker" value={who} onChange={(e) => setWho(e.target.value)} className={selectClass}>
                <option value="all">Everyone</option><option value="me">You</option><option value="others">Everyone but you</option>
                {speakers.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
              </select>
            : <Segmented value={who} onChange={setWho} options={[['all', 'Everyone'], ['me', 'You'], ['others', speakers[0]?.name ?? otherName]]} />}
          <div className="relative ml-auto flex items-center gap-1">
            <Search size={14} className="pointer-events-none absolute left-2.5 text-ink2" />
            <Input placeholder="find in transcript" value={term} onChange={(e) => setTerm(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && step(e.shiftKey ? -1 : 1)} className="w-56 pl-8" />
            {re && <span className="w-14 text-center text-[12.5px] tabular-nums text-ink2">{total ? `${cur + 1}/${total}` : '0'}</span>}
            {re && <><button aria-label="Previous match" onClick={() => step(-1)} className={btnClass('outline', 'icon')}><ChevronUp size={15} /></button>
              <button aria-label="Next match" onClick={() => step(1)} className={btnClass('outline', 'icon')}><ChevronDown size={15} /></button></>}
          </div>
        </>}
      </div>

      {tab === 'speakers' ? (
        <div className="space-y-5 py-4">
          <p className="text-[12.5px] text-ink2">Each speaker's main points, written by the assistant from the transcript. Every point opens the moment they said it; speaker names come from Granola (call display names) and can be wrong for a line or two.</p>
          {(t.by_speaker ?? []).filter((s) => s.points.length).map((s) => { const p = s.is_me ? me : people.data?.find((x) => x.name === s.name); return (
            <section key={s.name}>
              <div className="mb-1.5 flex items-center gap-2">
                <PersonLink id={p && !s.is_me ? p.id : undefined} photo><Avatar p={p ?? { name: s.name, avatar: '' }} size={24} /></PersonLink>
                {p && !s.is_me ? <Link to="/people/$id" params={{ id: p.id }} className="text-[14px] font-semibold text-ink">{s.name}</Link> : <span className="text-[14px] font-semibold">{s.is_me ? 'You' : s.name}</span>}
                <span className="text-[12.5px] text-ink2">{Math.round(s.share * 100)}% of the talk</span>
              </div>
              <ul className="space-y-1 border-l border-line pl-4">{s.points.map((x, i) => (
                <li key={i} className="flex gap-2 text-[14px] leading-snug">
                  <button onClick={() => jump(x.t)} className="shrink-0 pt-px text-[12px] tabular-nums text-ink2 underline decoration-line underline-offset-2 hover:text-ink" title="Show this moment in the transcript">{mmss(x.t)}</button>
                  <span>{x.text}</span>
                </li>))}</ul>
            </section>) })}
        </div>
      ) : tab === 'summary' ? (
        <div className="py-4">{t.summary_md ? <Markdown>{t.summary_md}</Markdown> : <Empty>No summary in this note.</Empty>}</div>
      ) : !t.available ? (
        <Empty>No transcript file found.</Empty>
      ) : (
        <div ref={box} className="py-3">
          {turns.length === 0 && <Empty>Nothing said by this speaker.</Empty>}
          {shotsAt.get(-1) && <ShotRow shots={shotsAt.get(-1)!} all={shots} onOpen={setShot} />}
          {turns.map((x, i) => <div key={x.t + '-' + i}><TurnRow x={x} name={nameOf(x)} avatar={avatarOf(x)} marked={x.t === markedT}
            body={highlight(x.lines.join(' '), re, offsets[i], cur)} />
            {shotsAt.get(i) && <ShotRow shots={shotsAt.get(i)!} all={shots} onOpen={setShot} />}</div>)}
        </div>
      )}
      {shot != null && <ShotViewer shots={shots} index={shot} onClose={() => setShot(null)} onJump={jump} />}
    </div>
  )
}

function TurnRow({ x, name, avatar, body, marked }: { x: Turn; name: string; avatar?: { name: string; avatar: string; id?: string }; body: ReturnType<typeof highlight>; marked?: boolean }) {
  const pid = x.me ? undefined : avatar?.id
  return (
    <div data-t={x.t} className={cn('group grid grid-cols-[52px_minmax(0,1fr)] gap-3 border-l-2 py-2 pl-3', x.me ? 'border-l-accent' : 'border-l-transparent', marked && 'bg-panel2 outline outline-2 outline-ink')}>
      <div className="pt-0.5 text-right text-[12px] tabular-nums text-ink2" title={`at ${x.clock}`}>{mmss(x.t)}</div>
      <div className="flex min-w-0 gap-2.5">
        <PersonLink id={pid} photo className="mt-0.5 self-start"><Avatar p={avatar ?? { name, avatar: '' }} size={26} className={pid ? undefined : 'mt-0.5'} /></PersonLink>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold"><PersonLink id={pid}>{name}</PersonLink></div>
          <p className="text-[14.5px] leading-relaxed [overflow-wrap:anywhere]">{body}</p>
        </div>
      </div>
    </div>
  )
}
