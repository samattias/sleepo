// Sources (System › Sources) and each source's page. Sam, 28 Oct 2026, review: the list led with columns that meant
// nothing ("3107 windows"), every gap ever recorded sat under it as one wall of red cards (120, most about 7 Oct problems
// fixed long ago), and a source's page drew one table per pull plus every pull window (Outlook: 211,000 px tall). Now: what
// needs attention first, one row per source, all the same height (status with its age, items), searchable and
// filtered by state and type like a list (Sam, 28 Oct 2026), the gaps reported in the last few days with the
// older ones folded (assist/gaps.py), and nothing else. A source's page: one list of its items,
// newest first, and its recent pulls with the quiet checks counted rather than listed.
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { CalendarDays, ChevronRight } from 'lucide-react'
import { api, type System, type SourcePull } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { SourceDot, SourceStatusPill, sourceWhen } from '@/components/SourceStatus'
import { ConnectionIssues } from '@/components/ConnectionAlert'
import { FilterBar, FilterRow, Opt, Segmented } from '@/components/FilterBar'
import { btnClass, Card, Empty, H1, Links, Loading, Muted, Section, SystemIcon, Table, Tag } from '@/components/ui'
import { TZ, LOCALE } from '@/lib/time'

const when = (iso?: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso.slice(0, 16) : d.toLocaleString(LOCALE, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ })
}
const day = (iso?: string | null) => {
  const d = iso ? new Date(iso) : null
  return d && !isNaN(d.getTime()) ? d.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short', timeZone: TZ }) : 'undated'
}

// what kind of material a source brings, for the list's Type filter
const TYPE: Record<string, string> = { outlook: 'Mail & chat', teams: 'Mail & chat', slack: 'Mail & chat', granola: 'Meetings', calendar: 'Meetings',
  'acme-kb': 'Documents', 'public-docs': 'Documents', sharepoint: 'Documents', local: 'Documents', salesforce: 'Sales' }
const typeOf = (s: System) => TYPE[s.id] ?? 'Other'
const fresh = (s: System) => !s.status || s.status.state === 'fresh'

export function Sources() {
  const q = useQuery({ queryKey: ['sources'], queryFn: api.sources })
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const nav = useNavigate()
  const [f, setF] = usePersisted<{ q: string; state: string; type: string }>('assist-v2-sources', { q: '', state: 'all', type: '' })
  if (!q.data || !meta.data) return <Loading />
  const { systems, stream_counts, gaps } = q.data
  const count = (s: System) => s.streams.reduce((a, st) => a + (st.source === 'meetings' ? meta.data!.counts.meetings : st.source === 'calendar' ? meta.data!.counts.calendar : stream_counts[st.id] ?? 0), 0)
  const current = gaps.filter((g) => g.current), older = gaps.filter((g) => !g.current)
  const re = f.q ? new RegExp(f.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
  const types = [...new Set(systems.map(typeOf))]
  const byType = systems.filter((s) => !f.type || typeOf(s) === f.type).filter((s) => !re || re.test([s.name, s.vendor, s.kind, s.status?.via, staleNote(s)].join(' ')))
  const shown = byType.filter((s) => f.state === 'all' || (f.state === 'attention' ? !fresh(s) : fresh(s)))
  return (
    <div>
      <H1>Sources</H1>
      {/* what SleePO cannot reach, with the way to fix it (assist/connections.py; 17 Nov 2026) */}
      <ConnectionIssues className="mb-4 border border-line border-l-2 border-l-hot bg-panel px-4 py-3" />
      <FilterBar search={f.q} onSearch={(v) => setF({ ...f, q: v })} placeholder="Search sources…"
        tokens={f.type ? [{ label: f.type, onRemove: () => setF({ ...f, type: '' }) }] : []}
        right={<Segmented value={f.state} onChange={(v) => setF({ ...f, state: v })} options={[
          ['all', `All · ${byType.length}`], ['fresh', `Up to date · ${byType.filter(fresh).length}`], ['attention', `Needs attention · ${byType.filter((s) => !fresh(s)).length}`]]} />}>
        <FilterRow label="Type">{types.map((t) => <Opt key={t} on={f.type === t} onClick={() => setF({ ...f, type: f.type === t ? '' : t })} count={systems.filter((s) => typeOf(s) === t).length}>{t}</Opt>)}</FilterRow>
      </FilterBar>
      {shown.length ? <Card className="divide-y divide-line2 p-0">
        {shown.map((s) => { const n = count(s); const note = !fresh(s) ? staleNote(s) : ''; return (
          // every row is the same height: two single lines, the second the stale reason when there is one
          <button key={s.id} onClick={() => nav({ to: '/sources/$id', params: { id: s.id } })}
            className="group flex h-[64px] w-full items-center gap-3 px-4 text-left transition-colors hover:bg-panel2 max-sm:px-3">
            <SystemIcon sys={s} logos={meta.data!.logos} size={32} />
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold text-ink">{s.name}</div>
              <div className={cn('truncate text-[12.5px]', note ? 'text-ink2' : 'text-ink3')} title={note || s.kind}>
                {note || <>{s.kind}{s.status?.via && <> · via {s.status.via}</>}</>}</div>
            </div>
            <div className="w-28 shrink-0 text-right text-[13px] tabular-nums max-sm:hidden"
              title={s.streams.length > 1 ? s.streams.map((st) => `${st.name} ${(stream_counts[st.id] ?? 0).toLocaleString()}`).join(' · ') : undefined}>
              {n ? <><b>{n.toLocaleString()}</b> <span className="text-ink3">items</span></> : <span className="text-ink3">none yet</span>}</div>
            <div className="flex w-48 shrink-0 justify-end max-sm:hidden"><SourceStatusPill status={s.status} /></div>
            {/* on a phone: the dot and the age only, so the name keeps its room */}
            <span title={s.status?.label} className={cn('inline-flex shrink-0 items-center gap-1.5 text-[12px] tabular-nums sm:hidden', fresh(s) ? 'text-ink2' : 'font-medium text-hot')}>
              <SourceDot state={s.status?.state} />{sourceWhen(s.status)}</span>
            <ChevronRight size={16} aria-hidden className="shrink-0 text-ink3 group-hover:text-ink max-sm:hidden" />
          </button>) })}
      </Card> : <Empty>No source matches.</Empty>}

      <Section right={<span className="text-[12.5px] font-normal normal-case tracking-normal text-ink3">reported by a pull in the last 3 days</span>}>Known gaps</Section>
      {current.length ? <Card className="divide-y divide-line2 px-4 py-0">{current.map((g, i) => (
        <div key={i} className="flex items-start gap-3 py-2.5 text-[13.5px]"><SourceDot state="stale" className="mt-1.5" /><span className="flex-1">{g.text}</span><span className="shrink-0 text-[12px] tabular-nums text-ink3">{when(g.seen)}</span></div>))}</Card>
        : <Empty>None. The latest pulls read everything they were meant to.</Empty>}
      {older.length > 0 && <details className="mt-2 text-[13px]">
        <summary className="cursor-pointer select-none text-ink2 hover:text-ink">Older notes from earlier pulls · {older.length}</summary>
        <div className="mt-2 divide-y divide-line2 border-l-2 border-line pl-3">{older.map((g, i) => (
          <div key={i} className="flex gap-3 py-1.5 text-ink2"><span className="flex-1">{g.text}</span><span className="shrink-0 text-[12px] tabular-nums text-ink3">{day(g.seen)}</span></div>))}</div>
      </details>}

    </div>
  )
}

// the note of the streams that are not up to date (a system's note joins every stream's)
const staleNote = (s: System) => (s.status?.streams ?? []).filter((x) => x.state !== 'fresh').map((x) => x.note).filter(Boolean).join(' · ')

// a pull that brought something in: when, which stream, how many items it stored of how many it listed
function PullRow({ r }: { r: SourcePull }) {
  return (
    <div className="flex items-start gap-3 py-2.5 text-[13.5px]">
      <span className="w-24 shrink-0 tabular-nums text-ink3">{when(r.at)}</span>
      <div className="min-w-0 flex-1">
        <span className="font-medium">{r.stream}</span> <span className="text-ink2">· {r.pulled.toLocaleString()} stored{r.available != null && r.available !== r.pulled ? ` of ${r.available.toLocaleString()} listed` : ''}</span>
        {!r.complete && <Tag className="ml-1.5">partial</Tag>}
        {r.note && <div className="truncate text-[12px] text-ink3" title={r.note}>{r.note}</div>}
      </div>
    </div>
  )
}

export function SourcePage({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['sources'], queryFn: api.sources })
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const [f, setF] = usePersisted<Record<string, { stream: string; q: string; limit: number }>>('assist-v2-sf', {})
  const sys = q.data?.systems.find((s) => s.id === id)
  const cur = f[id] ?? { stream: sys?.streams[0]?.id ?? '', q: '', limit: 150 }
  const st = sys?.streams.find((s) => s.id === cur.stream) ?? sys?.streams[0]
  const set = (p: Partial<typeof cur>) => setF({ ...f, [id]: { ...cur, ...p } })
  if (!q.data || !meta.data) return <Loading />
  if (!sys) return <Empty>Unknown source.</Empty>
  const via = sys.status?.via
  const pulls = q.data.pulls[id]
  const count = (s: typeof st) => !s ? 0 : s.source === 'meetings' ? meta.data!.counts.meetings : s.source === 'calendar' ? meta.data!.counts.calendar : q.data!.stream_counts[s.id] ?? 0
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3"><SystemIcon sys={sys} logos={meta.data.logos} size={44} />
        <div className="min-w-0 flex-1"><h1 className="text-2xl font-semibold">{sys.name}</h1><div className="text-ink2">{sys.vendor} · {sys.kind}{via && <> · pulled via <b className="font-medium text-ink">{via}</b></>}</div></div>
        <div className="text-right max-sm:text-left"><SourceStatusPill status={sys.status} />
          {sys.status && sys.status.streams.length > 1 && <Muted className="mt-1">{sys.status.streams.map((x) => `${x.name.split(' · ').pop()} ${sourceWhen(x)}`).join(' · ')}</Muted>}</div></div>
      {sys.status && sys.status.state !== 'fresh' && staleNote(sys) && <div className="mb-4 border-l-2 border-hot bg-panel px-3 py-2 text-[13px] text-ink2">{staleNote(sys)}</div>}
      {sys.streams.length > 0 && <FilterBar search={cur.q} onSearch={(v) => set({ q: v, limit: 150 })} placeholder={`Search ${sys.name}…`}
        right={sys.streams.length > 1 ? <Segmented value={st?.id ?? ''} onChange={(v) => set({ stream: v, limit: 150 })} options={sys.streams.map((s) => [s.id, `${s.name} · ${count(s).toLocaleString()}`] as [string, string])} /> : `${count(st).toLocaleString()} items`} />}
      {st && <StreamItems source={st.source} sid={st.id} q={cur.q} limit={cur.limit} more={() => set({ limit: cur.limit + 300 })} />}
      <Section right={pulls && <span className="text-[12.5px] font-normal normal-case tracking-normal text-ink3">{pulls.total.toLocaleString()} pulls in all{pulls.quiet_week ? ` · ${pulls.quiet_week.toLocaleString()} checks this week found nothing new` : ''}</span>}>Latest pulls</Section>
      {pulls?.recent.length ? <Card className="divide-y divide-line2 px-4 py-0">{pulls.recent.map((r, i) => <PullRow key={i} r={r} />)}</Card> : <Empty>Nothing pulled yet.</Empty>}
      <Section>How it is pulled</Section>
      <Card><p className="text-[13.5px] text-ink2">{sys.how}</p><Muted className="mt-2"><b>Auth:</b> {sys.auth} · <b>Status:</b> {sys.connect}</Muted></Card>
    </div>
  )
}

function StreamItems({ source, sid, q, limit, more }: { source: string; sid: string; q: string; limit: number; more: () => void }) {
  const re = q ? new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
  const meetings = useQuery({ queryKey: ['meetings'], queryFn: api.meetings, enabled: source === 'meetings' })
  const cal = useQuery({ queryKey: ['calendar'], queryFn: api.calendar, enabled: source === 'calendar' })
  const stream = useQuery({ queryKey: ['stream', sid], queryFn: () => api.stream(sid), enabled: source.startsWith('snap:') })
  const More = ({ total }: { total: number }) => total > limit ? <div className="py-2.5"><button onClick={more} className={btnClass('outline', 'md', 'font-normal')}>Show more ({(total - limit).toLocaleString()} left)</button></div> : null
  if (source === 'meetings') {
    if (!meetings.data) return <Loading />
    const l = meetings.data.filter((m) => !re || re.test([m.title, m.calendar, ...m.with].join(' ')))
    return <><Table head={<><th>Date</th><th>Meeting</th><th>With</th><th>Status</th><th></th></>}>{l.slice(0, limit).map((m) => <tr key={m.id}><td className="whitespace-nowrap text-ink3">{day(m.date)}</td><td><Link to="/explore/library/$" params={{ _splat: m.id }} className="font-semibold text-ink no-underline">{m.title}</Link>{m.calendar && <div className="flex items-center gap-1 text-[12.5px] text-ink3"><CalendarDays size={12} aria-hidden className="shrink-0" />{m.calendar}</div>}</td><td className="text-[12.5px]">{m.with.join(', ')}</td><td><Tag tone={m.status === 'analysed' ? 'good' : 'pending'}>{m.status}</Tag></td><td><a href={m.granola} target="_blank" rel="noopener" className="text-[12.5px]">Granola ↗</a></td></tr>)}</Table><More total={l.length} /></>
  }
  if (source === 'calendar') {
    if (!cal.data) return <Loading />
    const l = cal.data.events.filter((e) => !re || re.test([e.subject, e.organizer, ...e.attendees].join(' ')))
    return <><Table head={<><th>Date</th><th>Time</th><th>Event</th><th>Attendees</th><th>Granola</th><th></th></>}>{l.slice(0, limit).map((e) => <tr key={e.id}><td className="whitespace-nowrap text-ink3">{day(e.date)}</td><td className="whitespace-nowrap text-ink3">{e.time}</td><td><b>{e.subject}</b>{e.cancelled && <Tag className="ml-1">cancelled</Tag>}</td><td className="text-[12.5px]">{e.attendees.slice(0, 5).join(', ')}</td><td>{e.recorded ? <Tag tone="good">recorded</Tag> : e.unrecorded ? <Tag tone="pending">not recorded</Tag> : null}</td><td>{e.webLink && <a href={e.webLink} target="_blank" rel="noopener" className="text-[12.5px]">Outlook ↗</a>}</td></tr>)}</Table><More total={l.length} /></>
  }
  if (source.startsWith('snap:')) {
    if (!stream.data) return <Loading />
    // one list across the pulls (they come newest pull first); columns: When, From, Subject, Gist, Where, Noise
    const rows = stream.data.flatMap((t) => t.rows).filter((r) => !re || re.test(r.c.join(' ')))
    const shown = rows.slice(0, limit)
    const opaque = /^(\d+|[\w+/=-]{24,})$/   // thread ids (a number, an Exchange conversation id) say nothing
    const has = (k: number, skip?: RegExp) => shown.some((r) => r.c[k]?.trim() && !(skip && skip.test(r.c[k])))
    const subject = has(2), where = has(4, opaque)
    const gist = shown.filter((r) => r.c[3]?.trim()).length >= shown.length / 5   // mail mostly has no text here
    if (!rows.length) return <Empty>{q ? 'Nothing matches.' : 'Not pulled yet.'}</Empty>
    return <><Table head={<><th>When</th><th>From</th>{subject && <th>Subject</th>}{gist && <th>Text</th>}{where && <th>Where</th>}<th></th></>}>
      {shown.map((r, j) => { const noise = !!r.c[5]; return (
        <tr key={j} className={cn(noise && '[&>td]:text-ink3')}>
          <td className="whitespace-nowrap text-[12.5px] tabular-nums text-ink3">{r.c[0]}</td>
          <td className="whitespace-nowrap text-[12.5px]">{r.c[1]}</td>
          {subject && <td className="min-w-[220px] text-[13px]">{r.c[2]}{noise && <Tag className="ml-1.5">noise</Tag>}</td>}
          {gist && <td className="min-w-[260px] text-[12.5px] text-ink2"><span className="line-clamp-2">{r.c[3]}</span>{noise && !subject && <Tag className="ml-1.5">noise</Tag>}</td>}
          {where && <td className="text-[12.5px] text-ink3">{opaque.test(r.c[4]) ? '' : r.c[4]}</td>}
          <td className="whitespace-nowrap"><Links links={r.l} /></td>
        </tr>) })}
    </Table><More total={rows.length} /></>
  }
  return <Empty>Not pulled yet.</Empty>
}
