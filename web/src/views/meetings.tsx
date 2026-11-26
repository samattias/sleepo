// Meetings: the calendar and the Granola recordings as one thing. A recording that matches (or overlaps) a calendar event
// is shown once, combined; a recording with no event is overlaid on the calendar; an event nobody recorded stays an event.
// Two views of the same set: the calendar grid and a list.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { CircleDashed, Mic, Radio, RefreshCw, Search as SearchIcon } from 'lucide-react'
import { Link, useNavigate } from '@tanstack/react-router'
import { api, type Meeting } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { JoinButton } from '@/components/JoinButton'
import { Empty, GroupRow, Loading, Table, Tag } from '@/components/ui'
import { usePageTitle, useSearchSync } from '@/lib/nav'
import { CalendarGrid, MeetingPanel, REPLY_LABEL, ViewSwitch, calViewKey, toolBtn, unconfirmed, useSlots, type Slot } from '@/views/calendar'

const ymd = (d: Date) => format(d, 'yyyy-MM-dd')
const STATUS: Record<string, { label: string; tone: 'good' | 'pending' | 'plain' }> = {
  recorded: { label: 'Recorded', tone: 'good' }, 'granola-only': { label: 'Granola only', tone: 'good' }, missed: { label: 'Not recorded', tone: 'pending' },
  upcoming: { label: 'Upcoming', tone: 'plain' }, meeting: { label: 'No recording', tone: 'plain' }, block: { label: 'Time block', tone: 'plain' },
}
const RANGES: [string, string][] = [['week', 'This week'], ['upcoming', 'Next 14 days'], ['past', 'Past 30 days'], ['all', 'All']]

// The Meetings page under its heading (meetings-hub.tsx): the calendar grid or the list, one toolbar each, Refresh at its end.
// Sam, 22 Oct 2026: same shapes as the Inbox, and less on the page (no review banner, no counts line, the colour key folded).
export function MeetingsPage({ event, open: openParam }: { event?: string; open?: string } = {}) {
  const { slots, meetings, pulled } = useSlots()
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const prep = useQuery({ queryKey: ['prep'], queryFn: api.prep })
  const fu = useQuery({ queryKey: ['followups'], queryFn: api.followups, refetchInterval: (q) => (q.state.data?.running.length ? 5000 : false) })
  const [f, setF] = usePersisted('assist-meetings', { mode: 'calendar', range: 'week', q: '' })
  const [open, setOpen] = useState<Slot | null>(null)
  const qc = useQueryClient()
  const [opened, setOpened] = useState(false)
  const navigate = useNavigate()
  useEffect(() => {   // /prep?event=<id>, or /meetings?open=<slot> (Back from a page the panel led to): open that panel once loaded
    const want = event ?? openParam
    if (!want || opened || !slots) return
    // a recording (m-<id>, an Ask SleePO chip: components/ContextChip.tsx) opens the panel of the event it was matched to; one
    // the calendar does not show (older than its range) opens its own page
    const s = slots.find((x) => x.id === want || x.event?.id === want || x.meetingId === want)
    if (s) setOpen(s)
    else if (/^m-\d+$/.test(want)) void navigate({ to: '/meetings/$id', params: { id: want }, replace: true })
    setOpened(true)
  }, [event, openParam, slots, opened]) // eslint-disable-line react-hooks/exhaustive-deps
  // a link to another meeting while this page is open (a chip clicked in the chat beside it) opens that one too; the address
  // catching up with the panel already open is not a new link
  useEffect(() => { if (openParam && openParam !== open?.id && openParam !== open?.meetingId) setOpened(false) }, [openParam]) // eslint-disable-line react-hooks/exhaustive-deps
  // the open meeting is kept in the address, so Back from a person, transcript or task returns to its panel (lib/nav.ts)
  useSearchSync('open', event ? null : open?.id ?? null)
  usePageTitle(open?.title)
  // the calendar from Calendar.app now (the refresh reads it every 30 minutes): moved meetings, declined ones, your replies;
  // and Granola's new meeting notes (23 Oct 2026)
  // It runs in the background on the server (assist/calrefresh.py): a run started before this page opened, or one this page
  // started before you left it, is picked up and followed, and the page reloads its data when it ends.
  const reload = () => { for (const k of ['calendar', 'meetings', 'prep', 'today', 'followups', 'transcript']) qc.invalidateQueries({ queryKey: [k] }) }
  const refresh = useMutation({ mutationFn: api.calendarRefresh, onSuccess: (st) => { qc.setQueryData(['calendar-refresh'], st); reload() },   // the run it followed is the latest state
    onError: () => qc.invalidateQueries({ queryKey: ['calendar-refresh'] }) })
  const calJob = useQuery({ queryKey: ['calendar-refresh'], queryFn: api.calendarRefreshState, retry: true, retryDelay: 2000,   // a check during a server restart is retried
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false) })
  const wasRunning = useRef(false)
  useEffect(() => {
    const running = !!calJob.data?.running
    if (wasRunning.current && !running && !refresh.isPending) reload()
    wasRunning.current = running
  }, [calJob.data?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  const now = new Date()
  const byMeeting = useMemo(() => new Map(meetings.map((m) => [m.id, m])), [meetings])
  const briefs = useMemo(() => new Map((prep.data ?? []).filter((e) => e.brief).map((e) => [e.event_id, e])), [prep.data])

  if (!slots) return <Loading />
  const status = (s: Slot) => (s.kind === 'meeting' && s.start > now ? 'upcoming' : s.kind)
  // Live: a call in progress, with its brief (the meeting on now) or, with none, the newest Granola note (26 Oct 2026)
  const onNow = slots.find((s) => s.event && !s.allDay && s.kind !== 'block' && s.start.getTime() - 10 * 60000 <= now.getTime() && now <= s.end)
  const liveBtn = <Link to="/live" search={{ event: onNow?.event?.id }} className={toolBtn} title={onNow ? `Live: ${onNow.title}` : 'Live: follow a call Granola is recording'}><Radio size={13} aria-hidden />Live</Link>
  const refreshBtn = <>{liveBtn}<CalRefresh pulled={pulled} busy={refresh.isPending || !!calJob.data?.running} error={refresh.isError ? String(refresh.error).replace(/^Error: /, '') : ''} onRun={() => refresh.mutate()} /></>

  // list
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() + 6) % 7))
  const day = 86400000
  const ranges: Record<string, [Date, Date, boolean]> = {
    week: [monday, new Date(monday.getTime() + 7 * day), false],
    upcoming: [now, new Date(today.getTime() + 15 * day), false],
    past: [new Date(today.getTime() - 30 * day), now, true],
    all: [new Date(0), new Date(8.64e15), true],
  }
  const [from, to, desc] = ranges[f.range] ?? ranges.week
  const re = f.q.trim() ? new RegExp(f.q.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
  const names = (s: Slot) => (s.event?.attendees.length ? s.event.attendees : s.meetingId ? byMeeting.get(s.meetingId)?.with ?? [] : [])
  let list = slots.filter((s) => s.start >= from && s.start < to && !s.allDay && s.kind !== 'block')
  if (re) list = list.filter((s) => re.test([s.title, s.meetingId ? byMeeting.get(s.meetingId)?.title : '', ...names(s)].join(' ')))
  list = [...list].sort((a, b) => (desc ? b.start.getTime() - a.start.getTime() : a.start.getTime() - b.start.getTime()))
  const days = [...new Set(list.map((s) => ymd(s.start)))]

  return (
    <div className="flex min-h-0 flex-1 flex-col">{/* fills the fixed canvas (Layout): the calendar, or the list's own scroll pane */}
      {open && <MeetingPanel slot={open} meetings={meetings} people={people.data ?? []} onClose={() => setOpen(null)} />}

      {f.mode !== 'list' ? <CalendarGrid slots={slots} onOpen={setOpen} onList={() => setF({ ...f, mode: 'list' })} right={refreshBtn} /> : <>
        <div className="mb-3 flex shrink-0 flex-wrap items-center gap-1.5">
          <h2 className="min-w-0 flex-1 text-[18px] font-semibold tracking-[-0.01em]">{list.length} meeting{list.length === 1 ? '' : 's'}</h2>
          <ViewSwitch value="list" onChange={(v) => { if (v !== 'list') { try { localStorage.setItem(calViewKey(), JSON.stringify({ view: v })) } catch { /* ignore */ } setF({ ...f, mode: 'calendar' }) } }} />
          {refreshBtn}
        </div>
        {/* search and range chips, as in the Inbox */}
        <div className="mb-3 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2">
          <label className="relative block w-full sm:w-64">
            <SearchIcon size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink3" />
            <input value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="Search title, attendee" aria-label="Search meetings"
              className="w-full rounded-full border border-line bg-panel py-1.5 pl-8 pr-3 text-[13px] text-ink outline-none transition-colors placeholder:text-ink3 focus:border-ink" />
          </label>
          <div role="radiogroup" aria-label="When" className="flex flex-wrap gap-1.5">
            {RANGES.map(([k, l]) => { const on = (ranges[f.range] ? f.range : 'week') === k; return (
              <button key={k} role="radio" aria-checked={on} onClick={() => setF({ ...f, range: k })}
                className={cn('inline-flex items-center rounded-full border px-2.5 py-0.5 text-[12.5px] font-medium transition-colors', on ? 'border-ink bg-ink text-bg' : 'border-line text-ink hover:border-ink')}>{l}</button>) })}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">{/* the list scrolls in its own pane; the page stays put */}
        <Table head={<><th>Time</th><th>Meeting</th><th>Status</th><th className="max-md:hidden"><span className="sr-only">Join</span></th></>}>
          {days.length === 0 && <tr><td colSpan={4}><Empty>Nothing in this range.</Empty></td></tr>}
          {days.map((d) => [
            <GroupRow key={d} cols={4}>{format(new Date(d + 'T00:00:00'), 'EEEE d MMMM')}{d === ymd(now) && ' · today'}</GroupRow>,
            ...list.filter((s) => ymd(s.start) === d).map((s) => <Row key={s.id} s={s} m={s.meetingId ? byMeeting.get(s.meetingId) : undefined} st={status(s)} names={names(s)} brief={!!(s.event && briefs.has(s.event.id))}
              actions={s.meetingId && s.end < now ? fu.data?.items[s.meetingId]?.actions : undefined} onOpen={() => setOpen(s)} />),
          ])}
        </Table>
        </div>
      </>}
    </div>
  )
}

// One meeting in the list. Links (Outlook, Granola, transcript) and initiatives live in the panel the row opens.
function Row({ s, m, st, names, brief, actions, onOpen }: { s: Slot; m?: Meeting; st: string; names: string[]; brief: boolean; actions?: number; onOpen: () => void }) {
  const title = m && s.event && m.title !== s.title ? m.title : s.title
  return (
    <tr className="cursor-pointer hover:[&>td]:bg-panel2" onClick={onOpen}>
      <td className="whitespace-nowrap tabular-nums text-ink2">{format(s.start, 'HH:mm')}–{format(s.end, 'HH:mm')}</td>
      <td>
        <div className="flex items-start gap-1.5">{m && <Mic size={13} className="mt-1 shrink-0" aria-label="recorded" />}<b>{title}</b></div>
        {names.length > 0 && <div className="text-[12.5px] text-ink2">with {names.slice(0, 6).join(', ')}{names.length > 6 ? ` +${names.length - 6}` : ''}</div>}
      </td>
      <td className="whitespace-nowrap">
        <Tag tone={STATUS[st]?.tone ?? 'plain'}>{STATUS[st]?.label ?? st}</Tag>
        {unconfirmed(s.event) && <div className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-ink2"><CircleDashed size={11} aria-hidden />{REPLY_LABEL[s.event!.reply!]}</div>}
        {brief && s.event && s.end > new Date() && <div className="mt-1 text-[12px] font-medium">Brief ready</div>}
        {actions !== undefined && <div className="mt-1 text-[12px] font-medium">{actions ? `${actions} action${actions > 1 ? 's' : ''} to take` : 'Nothing to do'}</div>}
      </td>
      <td className="whitespace-nowrap max-md:hidden" onClick={(e) => e.stopPropagation()}>
        <JoinButton url={s.event?.join_url} start={s.event?.start} end={s.event?.end} size="sm" />
      </td>
    </tr>
  )
}

// Refresh as in the Inbox: when the calendar was last read, then a soft pill that reads Calendar.app now (moved meetings,
// declined ones, your replies; about 4 seconds). Its state lives in the page, so the calendar's toolbar can remount freely.
function CalRefresh({ pulled, busy, error, onRun }: { pulled: string; busy: boolean; error: string; onRun: () => void }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 30000); return () => clearInterval(t) }, [])
  const last = pulled ? new Date(pulled.replace(' ', 'T')) : null
  return (
    <span className="flex shrink-0 items-center gap-1">
      <span className="text-[12px] text-ink3 max-sm:hidden" title={last ? `Last read from Calendar.app ${format(last, 'EEE d MMM, HH:mm')}` : undefined}>
        {busy ? 'Reading the calendar and Granola…' : last ? ago(last) : ''}</span>
      <button onClick={onRun} disabled={busy} title="Read the calendar from Calendar.app (moved meetings, declined ones, your replies) and Granola's new meeting notes now. Takes about half a minute."
        className={cn(toolBtn, 'px-2.5 disabled:opacity-60')}>
        <RefreshCw size={13} aria-hidden className={cn(busy && 'animate-spin')} />Refresh</button>
      {error && <span role="alert" className="text-[12px] text-hot">{error}</span>}
    </span>
  )
}
function ago(d: Date) {
  const s = (Date.now() - d.getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  return ymd(d) === ymd(new Date()) ? `at ${format(d, 'HH:mm')}` : format(d, 'd MMM, HH:mm')
}
