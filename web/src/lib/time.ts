// Dates and times in the user's zone (their profile; Sam's is Europe/London), one set of helpers for the whole app (22 Oct 2026, from the codebase
// review: about 30 local copies with five different "ago" formats). parse() fixes the one real pitfall: a server timestamp
// with no zone ("2026-10-22T14:05:00") is UTC, but `new Date()` would read it as local time.
// The zone and locale come from the profile at boot (configure(), main.tsx): until then the browser's own. Exported as live
// bindings, so `import { TZ }` always reads the current one.
export let TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
export let LOCALE = 'en-GB'

/** A Date from a server timestamp: no zone means UTC; a bare date (YYYY-MM-DD) is that day at noon UTC. */
export function parse(ts: string | number | Date): Date {
  if (ts instanceof Date || typeof ts === 'number') return new Date(ts)
  const s = ts.trim().replace(' ', 'T')
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(`${s}T12:00:00Z`)
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) || !s.includes('T') ? s : `${s}Z`)
}

const fmt = (o: Intl.DateTimeFormatOptions, locale = LOCALE) => new Intl.DateTimeFormat(locale, { timeZone: TZ, ...o })
const build = () => ({
  key: fmt({}, 'en-CA'),
  hm: fmt({ hour: '2-digit', minute: '2-digit' }),
  day: fmt({ day: 'numeric', month: 'short' }),
  dayYear: fmt({ day: 'numeric', month: 'short', year: 'numeric' }),
  weekday: fmt({ weekday: 'short', day: 'numeric', month: 'short' }),
  full: fmt({ weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }),
  parts: fmt({ year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }),
})
let F = build()

/** Use the profile's time zone and locale (at boot, before the first render). */
export function configure(timezone?: string | null, locale?: string | null) {
  if (timezone) TZ = timezone
  if (locale) LOCALE = locale
  F = build()
}

/** A Date from a wall-clock time in the user's zone ("2026-11-04T08:30", how the calendar and meetings come from the server). The
 *  browser runs on this Mac's zone, which is not London when Sam travels (Lisbon, 4 Nov 2026: `new Date()` put every meeting
 *  9 hours early against the current-time line). A time with a zone is read as it is. */
export function wall(s: string): Date {
  if (/[zZ]|[+-]\d\d:?\d\d$/.test(s)) return new Date(s)
  const [y, mo, d, h = 0, mi = 0, sec = 0] = s.split(/\D/).map(Number)
  const utc = Date.UTC(y, mo - 1, d, h, mi)
  const offset = (t: number) => { const p = Object.fromEntries(F.parts.formatToParts(t).map((x) => [x.type, +x.value])); return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - t }
  return new Date(utc - offset(utc - offset(utc)) + sec * 1000)   // twice: the first guess can sit across a clock change
}

/** YYYY-MM-DD in the user's zone. */
export const dayKey = (ts: string | number | Date) => F.key.format(parse(ts))
/** 14:05 */
export const hm = (ts: string | number | Date) => F.hm.format(parse(ts))
/** 22 Oct (with the year when it is not this year) */
export const day = (ts: string | number | Date) => { const d = parse(ts); return (d.getFullYear() === new Date().getFullYear() ? F.day : F.dayYear).format(d) }
/** 14:05 today, otherwise 22 Oct */
export const dayTime = (ts: string | number | Date) => (dayKey(ts) === dayKey(Date.now()) ? hm(ts) : day(ts))
/** Thu 22 Oct, 14:05 */
export const fullWhen = (ts: string | number | Date) => F.full.format(parse(ts))
/** Today / Yesterday / Thu 22 Oct, for a YYYY-MM-DD key */
export function dayLabel(key: string, today = dayKey(Date.now())) {
  if (key === today) return 'Today'
  if (key === new Date(Date.parse(today) - 86400000).toISOString().slice(0, 10)) return 'Yesterday'
  return F.weekday.format(new Date(`${key}T12:00:00Z`))
}
/** How long ago. short: "just now", "5 min ago", "3 h ago", "2 d ago", then the date. long: "5 minutes ago", "3 hours ago",
 *  "yesterday", "4 days ago", "2 weeks ago", then the date. */
export function ago(ts: string | number | Date | null | undefined, style: 'short' | 'long' = 'short') {
  if (ts == null || ts === '') return ''
  const s = (Date.now() - parse(ts).getTime()) / 1000
  if (isNaN(s)) return ''
  const m = Math.round(s / 60), h = Math.round(s / 3600), d = Math.round(s / 86400)
  if (style === 'short') return s < 60 ? 'just now' : m < 60 ? `${m} min ago` : h < 48 ? `${h} h ago` : d < 14 ? `${d} d ago` : day(ts)
  return s < 60 ? 'just now' : m < 60 ? `${m} minute${m === 1 ? '' : 's'} ago` : h < 24 ? `${h} hour${h === 1 ? '' : 's'} ago`
    : d < 2 ? 'yesterday' : d < 14 ? `${d} days ago` : d < 60 ? `${Math.round(d / 7)} weeks ago` : day(ts)
}
