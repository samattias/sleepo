// How fresh a source is: one component for the Today widget, the Sources page and each source's page. The state itself is
// computed once on the server (assist/source_status.py) and comes with each system from /api/sources.
import type { SourceStatus, SourceState } from '@/lib/api'
import { cn } from '@/lib/util'

export const sourceAge = (h: number | null | undefined) =>
  h == null ? 'never' : h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 36 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} d ago`

// what to show instead of an age when there is no usable pull
export const sourceWhen = (s?: Pick<SourceStatus, 'state' | 'age_hours' | 'issue' | 'label'> | null) =>
  !s || s.state === 'unknown' ? 'not pulled yet' : s.issue ? s.label.toLowerCase() : s.state === 'off' ? 'not connected' : sourceAge(s.age_hours)

export function SourceDot({ state, className }: { state?: SourceState; className?: string }) {
  return <span aria-label={state ?? 'unknown'} className={cn('inline-block size-2 shrink-0 rounded-full',
    state === 'fresh' ? 'bg-accent ring-1 ring-ink/25' : state === 'stale' ? 'bg-hot' : state === 'capped' ? 'bg-serious' : 'border border-ink3', className)} />
}

// dot + label + age, e.g. "● Stale · 5 d ago"; a source a connection problem stopped: "● Sign-in needed · 11 d ago", the age
// of what last came in full (assist/connections.py)
export function SourceStatusPill({ status, age = true }: { status?: SourceStatus | null; age?: boolean }) {
  const issue = !!status?.issue
  return (
    <span title={status?.note || undefined} className={cn('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[12px]', issue ? 'border-hot text-hot' : 'border-line text-ink')}>
      <SourceDot state={issue ? 'stale' : status?.state} />{status?.label ?? 'Not pulled yet'}
      {age && status && (issue ? status.age_hours != null : status.state !== 'unknown' && status.state !== 'off') &&
        <span className={cn('tabular-nums', issue || status.state === 'stale' ? 'font-medium text-hot' : 'text-ink2')}>· {sourceAge(status.age_hours)}</span>}
    </span>
  )
}
