// One "Join" button for online meetings, with the app's own icon (Teams, Zoom, Google Meet) so it is clear what opens.
// Neutral until the meeting is within 15 minutes or under way, then highlighted. Hidden once the meeting has ended.
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { cn } from '@/lib/util'
import { wall } from '@/lib/time'

export type JoinKind = 'teams' | 'zoom' | 'meet' | 'other'
export const joinKind = (url: string): JoinKind =>
  /teams\.microsoft\.com|teams\.live\.com/.test(url) ? 'teams' : /zoom\.us/.test(url) ? 'zoom' : /meet\.google\.com/.test(url) ? 'meet' : 'other'
const NAME: Record<JoinKind, string> = { teams: 'Microsoft Teams', zoom: 'Zoom', meet: 'Google Meet', other: 'the online meeting' }

const at = (s?: string) => (s ? wall(s).getTime() : NaN)

function ZoomIcon({ size }: { size: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden><rect width="24" height="24" rx="6" fill="#0B5CFF" />
    <path d="M5 8.6c0-.6.5-1.1 1.1-1.1h7.3c1.2 0 2.1.9 2.1 2.1v5.8c0 .6-.5 1.1-1.1 1.1H7.1C5.9 16.5 5 15.6 5 14.4V8.6Z" fill="#fff" />
    <path d="m16.4 10.6 2.4-1.8c.4-.3.9 0 .9.5v5.4c0 .5-.5.8-.9.5l-2.4-1.8v-2.8Z" fill="#fff" /></svg>
}
function MeetIcon({ size }: { size: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
    <path d="M3 8.5 6.5 5H14v4.5H3V8.5Z" fill="#EA4335" /><path d="M3 9.5h4.5v5H3z" fill="#4285F4" /><path d="M3 14.5h4.5V19H6.5L3 15.5v-1Z" fill="#1967D2" />
    <path d="M7.5 9.5H14v5H7.5z" fill="#fff" /><path d="M7.5 14.5H14V19H7.5z" fill="#34A853" /><path d="M14 5h1.5c.8 0 1.5.7 1.5 1.5V9.5h-3V5Z" fill="#FBBC04" />
    <path d="M14 9.5h3v5h-3z" fill="#188038" /><path d="M14 14.5h3v3c0 .8-.7 1.5-1.5 1.5H14v-4.5Z" fill="#137333" />
    <path d="m17 10.2 3.2-2.6c.3-.3.8 0 .8.4v8c0 .4-.5.7-.8.4L17 13.8v-3.6Z" fill="#00832D" /></svg>
}

export function JoinIcon({ url, size = 16 }: { url: string; size?: number }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const k = joinKind(url)
  if (k === 'teams' && meta.data?.logos?.teams) return <img src={meta.data.logos.teams} alt="" width={size} height={size} className="shrink-0 object-contain" />
  if (k === 'zoom') return <ZoomIcon size={size} />
  if (k === 'meet') return <MeetIcon size={size} />
  return <span aria-hidden className="inline-block shrink-0 rounded-full bg-ink" style={{ width: size * 0.6, height: size * 0.6 }} />
}

/** start/end: London "YYYY-MM-DDTHH:MM" or ISO. `always` shows the button even after the meeting ended. */
export function JoinButton({ url, start, end, size = 'md', always = false, className }: { url?: string | null; start?: string; end?: string; size?: 'sm' | 'md'; always?: boolean; className?: string }) {
  if (!url) return null
  const now = Date.now(), s = at(start), e = at(end)
  if (!always && !Number.isNaN(e) && e < now) return null
  const live = !Number.isNaN(s) && s - now <= 15 * 60_000 && (Number.isNaN(e) || e >= now)
  return (
    <a href={url} target="_blank" rel="noopener" onClick={(ev) => ev.stopPropagation()} title={`Join in ${NAME[joinKind(url)]}`} aria-label={`Join in ${NAME[joinKind(url)]}`}
      className={cn('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border font-semibold text-ink no-underline',
        size === 'sm' ? 'rounded-full px-2.5 py-0.5 text-[12px]' : 'px-3 py-1 text-[13px]',
        live ? 'border-accent bg-accent text-onaccent hover:brightness-95' : 'border-line bg-panel hover:border-ink', className)}>
      <JoinIcon url={url} size={size === 'sm' ? 14 : 16} />Join
    </a>)
}
