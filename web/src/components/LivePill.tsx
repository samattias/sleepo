// The top bar's Live pill (Sam, 27 Oct 2026): while Granola records a call, scheduled or not (a Teams call someone rang),
// one click opens the Live page on it (views/live.tsx). The server looks at Granola every 20 seconds and only while the
// Granola app runs (assist/live_call.py recording); a note started in the last 20 minutes that has words counts at once, so the pill comes within
// half a minute of the first words; it goes two minutes after the last ones.
import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import { api } from '@/lib/api'

export function LivePill() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const q = useQuery({ queryKey: ['live-now'], queryFn: api.liveNow, refetchInterval: 20000, refetchIntervalInBackground: true, retry: false })
  const n = q.data?.note
  if (!n || path === '/live') return null
  return (
    <Link to="/live" search={{ note: n.id, event: q.data?.event ?? undefined }} title={`Granola is recording: ${n.title || 'a call'}. The transcript as it is said, the brief, and questions about it.`}
      className="inline-flex max-w-[260px] items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-[12.5px] font-semibold text-onaccent no-underline">
      <span aria-hidden className="size-1.5 shrink-0 animate-pulse rounded-full bg-onaccent" />
      <span className="truncate">Live{n.title && n.title !== 'New note' ? ` · ${n.title}` : ''}</span>
    </Link>
  )
}
