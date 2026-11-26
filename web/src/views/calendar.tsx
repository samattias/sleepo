import { cloneElement, isValidElement, useEffect, useMemo, useState, type ReactElement, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PrepGenerate } from '@/components/PrepGenerate'
import { MeetingFollowup } from '@/components/MeetingFollowup'
import { MeetingShots } from '@/components/MeetingShots'
import { BriefBody } from './prep'
import { Link } from '@tanstack/react-router'
import { Calendar as BigCalendar, dateFnsLocalizer, Views, type View, type ToolbarProps } from 'react-big-calendar'
import { addDays, addMonths, format, getDay, isSameDay, isSameMonth, parse, startOfDay, startOfMonth, startOfWeek } from 'date-fns'
import { enGB } from 'date-fns/locale'
import { CalendarDays, CalendarRange, ChevronDown, ChevronLeft, ChevronRight, CircleDashed, Columns3, ExternalLink, FileText, List, Mic, Radio, Video, X } from 'lucide-react'
import 'react-big-calendar/lib/css/react-big-calendar.css'
import { api, type CalEvent, type Meeting, type Person } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { wall, LOCALE } from '@/lib/time'
import { JoinButton } from '@/components/JoinButton'
import { ListResizer } from '@/components/ListResizer'
import { MeetingPeople } from '@/components/MeetingPeople'
import { Avatar, btnClass, Loading, Markdown } from '@/components/ui'
import { mentionsMe, profile } from '@/lib/profile'
import { AssistPill } from '@/components/AssistPill'
import { useAssistChip } from '@/components/AssistContext'
import { meetingPill } from '@/lib/assistPills'

// Two clocks in the time column (Sam, 22 Oct 2026): this Mac's time, which the calendar runs on (UK at home, Lisbon when
// travelling, 4 Nov 2026), and Portland, where much of the US team sits, side by side like Google Calendar's second time
// zone, in 12-hour time ("2 pm", "6 am"). The offset follows both sides' clock changes (UK 25 Oct, US 1 Nov): Portland's
// time comes from its time zone. The library only
// formats a string, so the gutter's hour label is swapped for a two-column one in the slot wrapper (only gutter slots
// carry a label; the day columns' slots are passed through untouched).
// The second clock is the profile's (Sam's: America/Los_Angeles, "PT"); none, no second column.
let second: { tz: string; fmt: Intl.DateTimeFormat; label: string } | null | undefined
const secondClock = () => {
  if (second === undefined) {
    const p = profile()
    try { second = p.second_timezone ? { tz: p.second_timezone, fmt: new Intl.DateTimeFormat(LOCALE, { timeZone: p.second_timezone, hour: 'numeric', hour12: true }), label: p.second_timezone_label || p.second_timezone.split('/').pop()!.replace(/_/g, ' ') } : null }
    catch { second = null }
  }
  return second
}
const ampm = (s: string) => s.replace(/\s*([ap])\.?m\.?$/i, (_, x: string) => ` ${x.toLowerCase()}m`)
const HERE_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone
const HERE = HERE_TZ === 'Europe/London' ? 'UK' : HERE_TZ.split('/').pop()!.replace(/_/g, ' ')   // "Lisbon"
const hereTime = (d: Date) => format(d, 'h aaa')
function GutterHeader() {
  const s = secondClock()
  return <div className="two-clock flex h-full items-end pb-1 text-[10.5px] font-semibold" title={`${HERE} time (this Mac's)` + (s ? `, and ${s.label} time (${s.tz})` : '')}>
    <span className="text-ink2">{HERE}</span>{s && <span className="text-ink3">{s.label}</span>}</div>
}
function SlotWrapper({ value, children }: { value: Date; children?: ReactNode }) {
  const el = children as ReactElement<{ children?: ReactNode }> | undefined
  if (!isValidElement(el) || !el.props.children) return <>{children}</>
  return cloneElement(el, {}, <span className="rbc-label two-clock"><span className="text-ink2">{hereTime(value)}</span>{secondClock() && <span className="text-ink3">{ampm(secondClock()!.fmt.format(value))}</span>}</span>)
}
const localizer = dateFnsLocalizer({ format, parse, startOfWeek: (d: Date) => startOfWeek(d, { weekStartsOn: 1 }), getDay, locales: { 'en-GB': enGB } })

// One shape for the grid: an Outlook event (maybe recorded) or a Granola recording with no calendar match.
export type Slot = {
  id: string; title: string; start: Date; end: Date; allDay: boolean
  kind: 'recorded' | 'missed' | 'meeting' | 'block' | 'granola-only'
  event?: CalEvent; meetingId?: string
}

// Sam has not accepted it: a tentative reply, or no reply yet (Outlook draws both hatched). Calendar.app gives the reply;
// an event only the Outlook pull has seen says just "tentative".
export const unconfirmed = (e?: CalEvent) => e?.reply === 'tentative' || e?.reply === 'not answered'
export const REPLY_LABEL: Record<string, string> = { tentative: 'Tentative', 'not answered': 'Not answered', accepted: 'Accepted', organizer: 'You organise it', declined: 'Declined' }

// The server sends London wall-clock times; the grid runs on this Mac's clock, so a timed event becomes the real moment
// (14:00 London is 23:00 in Lisbon). An all-day event stays on its date wherever Sam is.
const at = (s: string, allDay = false) => (allDay ? new Date(s.length === 16 ? s + ':00' : s) : wall(s))

export function toSlots(events: CalEvent[], meetings: Meeting[], todayIso: string): Slot[] {
  const out: Slot[] = []
  for (const e of events) {
    if (e.cancelled || !e.start) continue
    const kind: Slot['kind'] = e.meeting_id ? 'recorded' : e.unrecorded ? 'missed' : e.attendees.length ? 'meeting' : 'block'
    out.push({ id: e.id, title: e.subject, start: at(e.start, e.all_day), end: at(e.end, e.all_day), allDay: e.all_day, kind, event: e, meetingId: e.meeting_id || undefined })
  }
  // Granola notes the server did not pair with an event are overlaid on the grid as Granola-only, from their start to their
  // last transcript line. The server's matcher (scripts/reconcile_calendar.py) is the only one: this page used to join them
  // to an overlapping event by time, which put a quick call with Gray (15:41 to 15:51) in the 16:00 UX review, and calls
  // in PTO entries and holds (Sam, 26 Oct 2026).
  for (const m of meetings) {
    if (m.event_item_id || !m.start || m.status === 'personal') continue
    const s = at(m.start), end = m.end ? at(m.end) : new Date(s.getTime() + Math.max(30, Math.round(m.segments / 6)) * 60000)
    out.push({ id: m.id, title: m.title, start: s, end, allDay: false, kind: 'granola-only', meetingId: m.id })
  }
  void todayIso
  return out
}

const KIND_LABEL: Record<Slot['kind'], string> = { recorded: 'Recorded in Granola', missed: 'Not recorded', meeting: 'Meeting', block: 'Time block', 'granola-only': 'Granola recording, no calendar match' }

function SlotEvent({ event }: { event: Slot }) {
  return (
    <span className="flex min-w-0 items-start gap-1">
      {(event.kind === 'recorded' || event.kind === 'granola-only') && <Mic size={11} aria-label="recorded" className="mt-[2px] shrink-0" />}
      {unconfirmed(event.event) && <CircleDashed size={11} aria-label={REPLY_LABEL[event.event!.reply!]} className="mt-[2px] shrink-0" />}
      <span className="break-words" style={{ display: '-webkit-box', WebkitBoxOrient: 'vertical', overflow: 'hidden', WebkitLineClamp: Math.max(1, Math.floor(((event.end.getTime() - event.start.getTime()) / 60000 - 6) / 15)) }}>{event.title}</span>
    </span>
  )
}

// ---- view switcher shared by the calendar toolbar and the list view: Month · Week · Day · List
export type CalView = 'month' | 'week' | 'day' | 'list'
export const isNarrow = () => typeof matchMedia !== 'undefined' && matchMedia('(max-width: 767px)').matches
export const calViewKey = () => (isNarrow() ? 'assist-cal-view-phone' : 'assist-cal-view')
const VIEW_OPTS: { k: CalView; label: string; icon: typeof List; key: string }[] = [
  { k: 'month', label: 'Month', icon: CalendarDays, key: 'M' }, { k: 'week', label: 'Week', icon: Columns3, key: 'W' },
  { k: 'day', label: 'Day', icon: CalendarRange, key: 'D' }, { k: 'list', label: 'List', icon: List, key: 'L' }]

// the same rounded switch as the Inbox's Inbox | Sent (Sam, 22 Oct 2026), icons only (23 Oct): the name shows on hover
export function ViewSwitch({ value, onChange }: { value: CalView; onChange: (v: CalView) => void }) {
  const opts = VIEW_OPTS.filter((o) => !isNarrow() || o.k === 'day' || o.k === 'list')
  return (
    <div role="tablist" aria-label="Calendar view" className="inline-flex shrink-0 rounded-full bg-panel2 p-0.5">
      {opts.map(({ k, label, icon: I, key }) => (
        <button key={k} role="tab" aria-selected={value === k} aria-label={label} title={`${label} (${key})`} onClick={() => onChange(k)}
          className={cn('inline-flex items-center rounded-full px-2.5 py-1.5 transition-colors', value === k ? 'bg-panel text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>
          <I size={15} aria-hidden /></button>))}
    </div>
  )
}

// buttons as in the Inbox (Sam, 22 Oct 2026): soft borderless pills with a background on hover; the main action is the one
// filled lime pill
export const toolBtn = btnClass('ghost', 'sm', 'shrink-0 no-underline')   // components/ui.tsx: the shared button styles
export const primaryBtn = btnClass('primary', 'sm', 'shrink-0 no-underline')
const navBtn = 'grid size-8 place-items-center rounded-full text-ink transition-colors hover:bg-panel2 active:bg-line'

function Toolbar({ label, view, date, onNavigate, onView, onList, right }: ToolbarProps<Slot> & { onList?: () => void; right?: ReactNode }) {
  const isToday = view === 'month' ? isSameMonth(date, new Date()) : view === 'day' ? isSameDay(date, new Date()) : Math.abs(startOfWeek(date, { weekStartsOn: 1 }).getTime() - startOfWeek(new Date(), { weekStartsOn: 1 }).getTime()) < 86_400_000
  // keyboard: T today, ← → previous/next, M W D L views (ignored while typing)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.metaKey || e.ctrlKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable) return
      const map: Record<string, () => void> = { t: () => onNavigate('TODAY'), arrowleft: () => onNavigate('PREV'), arrowright: () => onNavigate('NEXT'),
        m: () => onView('month'), w: () => onView('week'), d: () => onView('day'), l: () => onList?.() }
      const f = map[e.key.toLowerCase()]
      if (f) { e.preventDefault(); f() }
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [onNavigate, onView, onList])
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5">
      <button onClick={() => onNavigate('TODAY')} disabled={isToday} title="Today (T)" className={cn(toolBtn, 'disabled:cursor-default disabled:text-ink3 disabled:hover:bg-transparent')}>Today</button>
      <div className="inline-flex">
        <button onClick={() => onNavigate('PREV')} aria-label="Previous" title="Previous (←)" className={navBtn}><ChevronLeft size={16} aria-hidden /></button>
        <button onClick={() => onNavigate('NEXT')} aria-label="Next" title="Next (→)" className={navBtn}><ChevronRight size={16} aria-hidden /></button>
      </div>
      <h2 className="ml-1 min-w-0 flex-1 truncate text-[18px] font-semibold tracking-[-0.01em]" aria-live="polite">{label}</h2>
      <ViewSwitch value={view as CalView} onChange={(v) => (v === 'list' ? onList?.() : onView(v))} />
      {right}
    </div>
  )
}

// Week/day column header: weekday small, date number large, today's number on a lime dot.
// Saturday and Sunday are greyed in every view (Sam, 22 Oct 2026): rbc-weekend on the day cells, cal-weekend in the header
const weekend = (d: Date) => d.getDay() === 0 || d.getDay() === 6
function DayHeader({ date }: { date: Date }) {
  const today = isSameDay(date, new Date())
  return <span className={cn('flex flex-col items-center leading-tight', weekend(date) && 'cal-weekend')}><span className="text-[11px] font-medium uppercase tracking-wide text-ink3">{format(date, 'EEE')}</span>
    <span className={cn('mt-0.5 inline-flex size-7 items-center justify-center rounded-full text-[15px] tabular-nums', today ? 'bg-accent font-semibold text-onaccent' : 'text-ink')}>{format(date, 'd')}</span></span>
}
function MonthDate({ date, label }: { date: Date; label: string }) {
  const today = isSameDay(date, new Date())
  return <span className={cn('inline-flex size-6 items-center justify-center rounded-full text-[12.5px] tabular-nums', today && 'bg-accent font-semibold text-onaccent')}>{label}</span>
}

// right: what sits at the end of the toolbar (the Refresh button)
export function CalendarGrid({ slots, onOpen, onList, right }: { slots: Slot[]; onOpen: (s: Slot) => void; onList?: () => void; right?: ReactNode }) {
  const narrow = isNarrow()
  const [pref, setPref] = usePersisted(calViewKey(), { view: (narrow ? Views.DAY : Views.WEEK) as View })
  const [date, setDate] = useState(() => new Date())
  const view = pref.view === Views.AGENDA ? (narrow ? Views.DAY : Views.WEEK) : pref.view
  const busy = useMemo(() => new Set(slots.filter((s) => !s.allDay && s.kind !== 'block').map((s) => format(s.start, 'yyyy-MM-dd'))), [slots])
  return (
    <div className="flex min-h-0 flex-1 gap-6">{/* fills the fixed canvas: the grid scrolls inside itself, the page does not */}
    <div className="assist-cal flex min-h-[420px] min-w-0 flex-1 flex-col">
      <div className="min-h-0 flex-1">
      <BigCalendar<Slot>
        localizer={localizer}
        culture="en-GB"
        events={slots}
        view={view}
        onView={(v) => setPref({ view: v })}
        views={narrow ? [Views.DAY] : [Views.MONTH, Views.WEEK, Views.DAY]}
        date={date}
        onNavigate={setDate}
        onSelectEvent={onOpen}
        selectable={false}
        popup
        scrollToTime={new Date(1970, 0, 1, 7, 40)}  /* a little before 08:00 so that hour's label, which sits on its line, is not clipped */
        step={30}
        timeslots={2}
        dayLayoutAlgorithm="no-overlap"
        components={{ timeGutterHeader: GutterHeader, timeSlotWrapper: SlotWrapper as never, event: SlotEvent, toolbar: (p) => <Toolbar {...p} onList={onList} right={right} />, week: { header: DayHeader }, day: { header: DayHeader }, month: { dateHeader: MonthDate } }}
        dayPropGetter={(d) => (weekend(d) ? { className: 'rbc-weekend' } : {})}
        eventPropGetter={(e) => ({ className: cn(`ev-${e.kind}`, unconfirmed(e.event) && 'ev-tentative'), title: [e.title, KIND_LABEL[e.kind], unconfirmed(e.event) && REPLY_LABEL[e.event!.reply!]].filter(Boolean).join(' · ') })}
        formats={{ timeGutterFormat: 'HH:mm', eventTimeRangeFormat: ({ start, end }) => `${format(start, 'HH:mm')}–${format(end, 'HH:mm')}`, agendaTimeRangeFormat: ({ start, end }) => `${format(start, 'HH:mm')}–${format(end, 'HH:mm')}`, dayFormat: 'EEE d', weekdayFormat: 'EEE',
          monthHeaderFormat: 'MMMM yyyy', dayHeaderFormat: 'EEEE d MMMM yyyy',
          dayRangeHeaderFormat: ({ start, end }) => isSameMonth(start, end) ? `${format(start, 'd')} – ${format(end, 'd MMMM yyyy')}` : `${format(start, 'd MMM')} – ${format(end, 'd MMM yyyy')}` }}
        messages={{ agenda: 'List', showMore: (n) => `+${n} more` }}
        length={7}
      />
      </div>
      {/* the colour key, folded away (each event also says what it is on hover) */}
      <details className="group mt-1.5 text-[11.5px] text-ink3">
        <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-full px-2 py-0.5 font-medium text-ink2 transition-colors hover:bg-panel2 hover:text-ink [&::-webkit-details-marker]:hidden">
          <ChevronRight size={12} aria-hidden className="transition-transform group-open:rotate-90" />Colour key</summary>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 px-2">
          {(['recorded', 'granola-only', 'missed', 'meeting', 'block'] as Slot['kind'][]).map((k) => <span key={k} className="inline-flex items-center gap-1.5"><span className={cn('legend-sw', `ev-${k}`)} />{KIND_LABEL[k]}</span>)}
          <span className="inline-flex items-center gap-1.5"><span className="legend-sw ev-meeting ev-tentative" />Tentative or not answered</span>
        </div>
      </details>
    </div>
    {/* the mini month, in the space a wide window leaves beside the grid */}
    <aside aria-label="Month at a glance" className="hidden min-h-0 w-[236px] shrink-0 flex-col min-[1500px]:flex">
      <MiniMonth date={date} view={view} busy={busy} onPick={setDate} />
      <UpNext slots={slots} onOpen={onOpen} />
    </aside>
    </div>
  )
}

// Up next, under the mini month (Sam, 22 Oct 2026): the next meetings to join, today first, then the coming days (up to six,
// a week ahead), each with its Join button, which turns volt from 15 minutes before; a click on one opens its panel. Real
// meetings only, as the Meetings badge counts them: people invited, not cancelled, all-day or personal; tentative and
// unanswered ones show, marked.
function UpNext({ slots, onOpen }: { slots: Slot[]; onOpen: (s: Slot) => void }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(t) }, [])
  const until = startOfDay(addDays(new Date(now), 8)).getTime()
  const next = slots.filter((s) => s.event && !s.allDay && s.kind !== 'block' && s.event.attendees.length > 0 && s.end.getTime() > now
    && s.start.getTime() < until && !/personal/i.test(s.event.skip || '')).sort((a, b) => a.start.getTime() - b.start.getTime()).slice(0, 6)
  const today = new Date(now)
  const dayName = (d: Date) => isSameDay(d, today) ? 'Today' : isSameDay(d, addDays(today, 1)) ? 'Tomorrow' : format(d, 'EEEE d MMM')
  const soon = (s: Slot) => { const m = Math.round((s.start.getTime() - now) / 60_000); return s.start.getTime() <= now ? 'Now' : m < 60 ? `in ${m} min` : '' }
  const days = [...new Set(next.map((s) => format(s.start, 'yyyy-MM-dd')))]
  return (
    <section aria-label="Up next" className="mt-4 flex min-h-0 flex-1 flex-col border-t border-line pt-3">
      <h3 className="mb-1 px-1 text-[13px] font-semibold">Up next</h3>
      <div className="min-h-0 flex-1 overflow-auto">
        {next.length === 0 && <p className="px-1 py-2 text-[12.5px] text-ink2">No meetings in the next week.</p>}
        {days.map((d) => (
          <div key={d}>
            <div className="px-1 pb-0.5 pt-2 text-[11px] font-semibold text-ink3">{dayName(new Date(d + 'T12:00:00'))}</div>
            {next.filter((s) => format(s.start, 'yyyy-MM-dd') === d).map((s) => {
              const e = s.event!, label = soon(s), live = label === 'Now'
              const who = e.attendees.filter((n) => !mentionsMe(n)).map((n) => n.split(' ')[0])
              return (
                <div key={s.id} role="button" tabIndex={0} onClick={() => onOpen(s)} onKeyDown={(k) => { if (k.key === 'Enter') onOpen(s) }}
                  className={cn('group cursor-pointer rounded-lg border-l-2 px-2 py-1.5 transition-colors hover:bg-panel2', live ? 'border-l-accent bg-accentbg' : 'border-l-transparent')}>
                  <div className="flex items-center gap-1.5 text-[11.5px] tabular-nums text-ink2">
                    <span>{format(s.start, 'HH:mm')}–{format(s.end, 'HH:mm')}</span>
                    {label && <span className={cn('rounded-full px-1.5 text-[10.5px] font-semibold leading-[16px]', live ? 'bg-accent text-onaccent' : 'bg-panel2 text-ink')}>{label}</span>}
                    {unconfirmed(e) && <CircleDashed size={11} aria-label={REPLY_LABEL[e.reply!]} className="shrink-0" />}
                  </div>
                  <div className="mt-0.5 flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="line-clamp-2 text-[12.5px] font-medium leading-snug">{s.title}</div>
                      {who.length > 0 && <div className="truncate text-[11.5px] text-ink3">with {who.slice(0, 3).join(', ')}{who.length > 3 ? ` +${who.length - 3}` : ''}</div>}
                    </div>
                    <JoinButton url={e.join_url} start={e.start} end={e.end} size="sm" className="mt-0.5" />
                  </div>
                </div>)
            })}
          </div>))}
      </div>
    </section>
  )
}

// The mini month beside the grid (Sam, 22 Oct 2026, like Outlook's): the whole month at a glance, today in volt, the week
// (or day) the grid shows as a band, a dot on days with meetings, weekends and past days greyed. ‹ › page through months
// without moving the grid; a click on a day moves the grid there, in the same view.
const MINI_DAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
function MiniMonth({ date, view, busy, onPick }: { date: Date; view: View; busy: Set<string>; onPick: (d: Date) => void }) {
  const [month, setMonth] = useState(() => startOfMonth(date))
  useEffect(() => { setMonth(startOfMonth(date)) }, [date.getFullYear(), date.getMonth()]) // eslint-disable-line react-hooks/exhaustive-deps
  const first = startOfWeek(month, { weekStartsOn: 1 })
  const rows = Array.from({ length: 6 }, (_, w) => Array.from({ length: 7 }, (_, d) => addDays(first, w * 7 + d))).filter((wk, i) => i < 5 || isSameMonth(wk[0], month))
  const today = new Date(), dayStart = startOfDay(today)
  const weekOf = startOfWeek(date, { weekStartsOn: 1 })
  const nav = 'grid size-7 place-items-center rounded-full text-ink2 transition-colors hover:bg-panel2 hover:text-ink'
  return (
    <div className="select-none">
      <div className="mb-1 flex items-center">
        <button onClick={() => setMonth(addMonths(month, -1))} aria-label="Previous month" title="Previous month" className={nav}><ChevronLeft size={15} aria-hidden /></button>
        <div className="flex-1 text-center text-[13.5px] font-semibold" aria-live="polite">{format(month, 'MMMM yyyy')}</div>
        <button onClick={() => setMonth(addMonths(month, 1))} aria-label="Next month" title="Next month" className={nav}><ChevronRight size={15} aria-hidden /></button>
      </div>
      <div className="grid grid-cols-7 text-center text-[11px] font-semibold">
        {MINI_DAYS.map((l, i) => <span key={i} className={cn('py-1', i >= 5 ? 'text-ink3' : 'text-ink2')}>{l}</span>)}
      </div>
      {rows.map((wk) => {
        const band = view === Views.WEEK && isSameDay(wk[0], weekOf)
        return (
          <div key={wk[0].toISOString()} className={cn('grid grid-cols-7 rounded-full', band && 'mini-band')}>
            {wk.map((d) => {
              const key = format(d, 'yyyy-MM-dd'), isToday = isSameDay(d, today), out = !isSameMonth(d, month)
              const picked = view === Views.DAY && isSameDay(d, date)
              return (
                <button key={key} onClick={() => onPick(d)} aria-label={format(d, 'EEEE d MMMM yyyy')} aria-current={isToday ? 'date' : undefined}
                  className={cn('relative mx-auto my-px grid size-8 place-items-center rounded-full text-[12.5px] tabular-nums transition-colors',
                    isToday ? 'bg-accent font-semibold text-onaccent' : 'hover:bg-panel2',
                    !isToday && (out ? 'text-ink3 opacity-50' : weekend(d) || d < dayStart ? 'text-ink3' : 'text-ink'),
                    picked && !isToday && 'ring-1 ring-ink')}>
                  {format(d, 'd')}
                  {busy.has(key) && <span aria-hidden className={cn('absolute bottom-[3px] size-[3px] rounded-full', isToday ? 'bg-onaccent' : 'bg-ink3')} />}
                </button>)
            })}
          </div>)
      })}
    </div>
  )
}

// Strip the header lines the server puts on every meeting document; the panel shows them as fields.
function digestBody(md: string) {
  return md.split(/\n\n/).filter((p, i) => !(i === 0 && p.startsWith('# ')) && !/^\*\*\w{3} \d{2} \w{3} \d{4}/.test(p) && !p.startsWith('**Calendar:**')).join('\n\n')
}

// A collapsible section of the side panel: a quiet heading row that toggles, then the content. Open by default.
function Section({ title, meta, right, children, defaultOpen = true }: { title: string; meta?: ReactNode; right?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border-t border-line">
      <div className="flex items-center gap-2 py-2.5">
        <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-w-0 items-center gap-1.5 text-left">
          <ChevronDown size={15} aria-hidden className={cn('shrink-0 text-ink2 transition-transform', !open && '-rotate-90')} />
          <h3 className="text-[14px] font-semibold">{title}</h3>
          {meta && <span className="truncate text-[12px] text-ink2">{meta}</span>}
        </button>
        {right && <span className="ml-auto flex shrink-0 items-center gap-2">{right}</span>}
      </div>
      {open && <div className="pb-4">{children}</div>}
    </section>
  )
}

// The meeting brief written by /prep (Meeting prep), shown for upcoming meetings and for any meeting that has one.
function PanelBrief({ e, upcoming }: { e: CalEvent; upcoming: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['prep', 30], queryFn: () => api.prepWindow(30), refetchInterval: (s) => (s.state.data?.some((x) => x.event_id === e.id && x.job?.running) ? 4000 : false) })
  const it = q.data?.find((x) => x.event_id === e.id)
  const past = useQuery({ queryKey: ['prepBrief', e.id], queryFn: () => api.prepBrief(e.id), enabled: !upcoming })   // the window lists upcoming meetings only
  const brief = it?.brief ?? past.data?.brief ?? null
  const doc = useQuery({ queryKey: ['doc', brief?.doc_id, brief?.updated_at], queryFn: () => api.doc(brief!.doc_id), enabled: !!brief })
  const run = useMutation({ mutationFn: (notes: string) => api.prepRun(e.id, notes), onSettled: () => { qc.invalidateQueries({ queryKey: ['prep'] }) } })
  if (!brief && (!upcoming || e.attendees.length === 0)) return null
  const busy = !!it?.job?.running || run.isPending
  return (
    <Section title={upcoming ? 'Briefing' : 'Your brief'} defaultOpen={upcoming} meta={brief ? `${upcoming ? 'updated' : 'written'} ${format(new Date(brief.updated_at), 'EEE d MMM, HH:mm')}` : undefined}
      right={upcoming && <PrepGenerate key={e.id} hasBrief={!!brief} busy={busy} onRun={(notes) => run.mutate(notes)} lastNotes={it?.job?.notes} />}>
      <div className="panel-md">
        {brief ? (doc.data ? <BriefBody md={doc.data.md ?? ''} label={e.subject} eventId={e.id} /> : <Loading />)
          : busy ? <p className="text-[13px] text-ink2">Preparing… usually 1–3 minutes.</p>
          : <p className="text-[13px] text-ink2">No brief yet.</p>}
      </div>
      {it?.job?.notes && !busy && brief && <p className="mt-2 text-[12px] text-ink2">Written with your notes: “{it.job.notes.length > 140 ? it.job.notes.slice(0, 140) + '…' : it.job.notes}”</p>}
      {run.isError && <p className="mt-2 text-[12.5px] text-hot">{String(run.error).replace(/^Error: /, '')}</p>}
      {it?.job?.ok === false && !busy && <p className="mt-2 text-[12.5px] text-hot">The last attempt failed{it.job.error ? `: ${it.job.error.slice(-160)}` : '.'}</p>}
    </Section>)
}

const STATUS_DOT: Record<Slot['kind'], string> = { recorded: 'bg-accent ring-1 ring-ink/25', 'granola-only': 'bg-accent ring-1 ring-ink/25', missed: 'bg-hot', meeting: 'border border-ink2', block: 'border border-ink2' }

// Where the meeting is: an online meeting shows its service with the join link; anything else is the room or address as written.
function Where({ location, join }: { location: string; join?: string | null }) {
  const svc = join ? (/teams\.microsoft|teams\.live/i.test(join) ? 'Microsoft Teams' : /zoom\./i.test(join) ? 'Zoom' : /meet\.google/i.test(join) ? 'Google Meet' : /webex/i.test(join) ? 'Webex' : 'Online meeting') : ''
  const room = location && !/^(microsoft teams meeting|teams|zoom|google meet|online)$/i.test(location.trim()) ? location : ''
  return <span className="inline-flex flex-wrap items-center gap-x-2">
    {svc && <a href={join!} target="_blank" rel="noopener" className="inline-flex items-center gap-1.5 font-medium"><Video size={13} aria-hidden />{svc} ↗</a>}
    {room && <span>{svc ? `and ${room}` : room}</span>}
    {!svc && !room && <span>{location}</span>}
  </span>
}

function Linkified({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s<>()]+)/g)
  return <>{parts.map((t, i) => i % 2 ? <a key={i} href={t} target="_blank" rel="noopener">{t.length > 60 ? t.slice(0, 57) + '…' : t}</a> : t)}</>
}

function People({ names, person }: { names: string[]; person: (n: string) => Person | undefined }) {
  const [all, setAll] = useState(false)
  const shown = all ? names : names.slice(0, 8)
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {shown.map((n) => { const p = person(n); return p
        ? <Link key={n} to="/people/$id" params={{ id: p.id }} className="inline-flex items-center gap-1.5 rounded-full border border-line py-px pl-px pr-2.5 text-[12.5px] font-normal text-ink no-underline hover:border-ink"><Avatar p={p} size={20} />{n}</Link>
        : <span key={n} className="inline-flex items-center rounded-full border border-line px-2.5 py-0.5 text-[12.5px] text-ink">{n}</span> })}
      {names.length > 8 && <button onClick={() => setAll(!all)} className="text-[12.5px] font-medium underline decoration-accent decoration-2 underline-offset-2">{all ? 'fewer' : `+${names.length - 8} more`}</button>}
    </div>
  )
}

const PANEL_DEFAULT = 680
export function MeetingPanel({ slot, meetings, people, onClose }: { slot: Slot; meetings: Meeting[]; people: Person[]; onClose: () => void }) {
  const [panelW, setPanelW] = usePersisted<number>('assist-meeting-panel-width', 0)   // 0: the default
  const m = slot.meetingId ? meetings.find((x) => x.id === slot.meetingId) : undefined
  const doc = useQuery({ queryKey: ['doc', slot.meetingId], queryFn: () => api.doc(slot.meetingId!), enabled: !!slot.meetingId })
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); addEventListener('keydown', k); return () => removeEventListener('keydown', k) }, [onClose])
  const e = slot.event
  // what the pill passes: the recording when there is one, else the calendar event (its brief); a block with nobody invited none
  const target = m && m.status !== 'personal' ? { kind: 'meeting', ref: m.id.replace(/^m-/, '') } : e && slot.kind !== 'block' ? { kind: 'event', ref: e.id } : null
  const chip = useAssistChip(target)
  const names = e?.attendees.length ? e.attendees : m?.with ?? []
  const person = (n: string) => people.find((p) => p.name.toLowerCase() === n.toLowerCase())
  const time = slot.allDay ? 'All day' : `${format(slot.start, 'HH:mm')}–${format(slot.end, 'HH:mm')}`
  const mins = e && e.minutes > 0 && !slot.allDay ? ` · ${e.minutes} min` : ''
  const title = m && slot.kind === 'recorded' && m.title !== slot.title ? m.title : slot.title
  const upcoming = slot.end.getTime() > Date.now()
  const inCall = !slot.allDay && Date.now() >= slot.start.getTime() - 10 * 60000 && Date.now() <= slot.end.getTime() + 30 * 60000   // Live: the brief and the transcript as it is said
  const mine = e?.reply === 'organizer'   // Sam organises it: no organiser line
  const invite = e?.agenda && <Section title="Invite" defaultOpen={false} meta={e.organizer && !mine ? `from ${e.organizer}` : undefined}>
    <p className="whitespace-pre-wrap text-[13px] leading-relaxed [overflow-wrap:anywhere]"><Linkified text={e.agenda} /></p>
  </Section>
  const summary = m && <Section title="Summary" meta={m.segments ? `from ${m.segments} transcript turns` : undefined}>
    <div className="panel-md">{doc.data?.md ? <Markdown>{digestBody(doc.data.md)}</Markdown> : <Loading />}</div>
  </Section>
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} />
      {/* wider by default, and Sam can drag its left edge (Sam, 22 Oct 2026); the width is remembered like the lists' */}
      <aside role="dialog" aria-label={slot.title} style={{ width: `min(${panelW || PANEL_DEFAULT}px, 100vw)` }} className="fixed bottom-0 right-0 top-0 z-50 flex flex-col border-l border-line bg-panel shadow-2xl">
        <ListResizer side="left" width={panelW} onChange={setPanelW} label="Resize the meeting panel" min={440} max={1100} share={0.8} />
        <header className="border-b border-line px-5 pb-3 pt-3.5">
          <div className="flex items-center gap-2 text-[12.5px] text-ink2">
            <span aria-hidden className={cn('size-2 shrink-0 rounded-full', STATUS_DOT[slot.kind])} />
            <span className="font-medium text-ink">{KIND_LABEL[slot.kind]}</span>
            {unconfirmed(e) && <><span>·</span><span title={upcoming ? 'Answer it in Outlook' : undefined} className="inline-flex items-center gap-1 font-medium text-ink"><CircleDashed size={12} aria-hidden />{REPLY_LABEL[e!.reply!]}</span></>}
            <span>·</span><span>{format(slot.start, 'EEE d MMM yyyy')}, {time}{mins}</span>
            <button onClick={onClose} aria-label="Close (Esc)" title="Close (Esc)" className="-mr-1.5 ml-auto grid size-7 place-items-center rounded-full text-ink transition-colors hover:bg-panel2"><X size={17} aria-hidden /></button>
          </div>
          <h2 className="mt-1 text-[18px] font-semibold leading-snug">{title}</h2>
          {title !== slot.title && <div className="text-[12.5px] text-ink2">Calendar: {slot.title}</div>}
          {/* before the meeting Join leads; after it the transcript is the one filled button */}
          <div className="-ml-1 mt-2 flex flex-wrap items-center gap-1">
            {upcoming && <JoinButton url={e?.join_url} start={e?.start} end={e?.end} size="sm" className="mr-1" />}
            {inCall && e && <Link to="/live" search={{ event: e.id }} className={primaryBtn} title="The brief beside the transcript as it is said, and questions about the call"><Radio size={13} aria-hidden />Live</Link>}
            {m && m.status !== 'personal' && <Link to="/meetings/$id" params={{ id: m.id }} className={upcoming ? toolBtn : primaryBtn}><FileText size={13} aria-hidden />Transcript{m.segments ? ` · ${m.segments}` : ''}</Link>}
            {m?.granola && <a href={m.granola} target="_blank" rel="noopener" className={toolBtn}><Video size={13} aria-hidden />Granola</a>}
            {e?.webLink && <a href={e.webLink} target="_blank" rel="noopener" className={toolBtn}><ExternalLink size={13} aria-hidden />Outlook</a>}
          </div>
        </header>
        <div className="flex-1 overflow-auto px-5">
          <dl className="grid grid-cols-[84px_1fr] gap-x-3 gap-y-2 py-3.5 text-[13px]">
            <dt className="pt-0.5 text-ink2">People</dt><dd>{m ? <MeetingPeople meetingId={m.id} /> : names.length > 0 ? <People names={names} person={person} /> : <span className="text-ink2">Only you</span>}</dd>
            {e?.organizer && !mine && <><dt className="text-ink2">Organiser</dt><dd>{e.organizer}</dd></>}
            {(e?.location || e?.join_url) && <><dt className="text-ink2">Where</dt><dd className="[overflow-wrap:anywhere]"><Where location={e?.location ?? ''} join={e?.join_url} /></dd></>}
            {m && m.initiatives.length > 0 && <><dt className="text-ink2">Initiatives</dt><dd>{m.initiatives.join(' · ')}</dd></>}
          </dl>
          {/* before the meeting: the brief and its actions; after it: the actions from what was said, the summary, then the brief
              folded away. The invite text (mostly signatures) is folded at the end either way. */}
          {!upcoming && m && <MeetingFollowup meetingId={m.id} label={title} Section={Section} />}
          {!upcoming && summary}
          {!upcoming && m && m.status !== 'personal' && <MeetingShots meetingId={m.id} Section={Section} />}
          {e && <PanelBrief e={e} upcoming={upcoming} />}
          {upcoming && summary}
          {invite}
          {!m && slot.kind === 'missed' && <p className="border-t border-line py-3 text-[13px]"><b className="text-hot">Not recorded.</b> This meeting had attendees but no Granola recording was matched to it. If it was recorded, the note may have started more than 12 minutes off the calendar time.</p>}
          {!m && slot.kind === 'meeting' && slot.event?.skip && <p className="border-t border-line py-3 text-[13px] text-ink2">Not counted as a missed recording: {slot.event.skip}.</p>}
          {!m && slot.kind === 'meeting' && !slot.event?.skip && !upcoming && <p className="border-t border-line py-3 text-[13px] text-ink2">Notes appear here once Granola records it and the next sync runs.</p>}
        </div>
        {/* the assistant pill (Sam, 16 Nov 2026): before the meeting prep and an agenda, after it what was agreed and the
            follow-up, with the meeting's chip; only when SleePO holds it (never a personal meeting); clear of the floating button */}
        {target && chip && <div className="border-t border-line bg-panel py-2.5 pl-5 pr-20"><AssistPill target={target} {...meetingPill(upcoming)} /></div>}
      </aside>
    </>
  )
}

export function useSlots() {
  const cal = useQuery({ queryKey: ['calendar'], queryFn: api.calendar })
  const meetings = useQuery({ queryKey: ['meetings'], queryFn: api.meetings })
  const slots = useMemo(() => cal.data && meetings.data ? toSlots(cal.data.events, meetings.data, '') : null, [cal.data, meetings.data])
  return { slots, meetings: meetings.data ?? [], ready: !!slots, pulled: cal.data?.pulled ?? '' }
}
export { Loading }
