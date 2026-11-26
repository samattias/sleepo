// What came in since a record was written, and what SleePO made of it (graph memory: assist/graph_memory.py, assist/graph_refresh.py,
// DESIGN-GRAPH-MEMORY.md; Sam, 17 Nov 2026: "for every input we receive ... update the record for that specific topic ... and
// traverse also the graph to look at related elements"). The server walks the graph when items are linked: each new item marks
// the records it touches, one hop through its sure links and a second along chosen edges (a task's or topic's bet, the brief of
// a meeting someone in it attends). After the syncs SleePO reads that material and rewrites only what changed.
// Two folded lines: "Updated 14:32 from new material" (each change, how sure, and the item it came from) when SleePO rewrote
// the record from it, and "3 new since this status" (each item where it lives), with "checked 14:32, nothing that changes it"
// once SleePO has read them and found nothing.
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { api, type GraphChanges, type GraphKind } from '@/lib/api'
import { dayTime } from '@/lib/time'
import { cn } from '@/lib/util'

export const useGraphChanges = (kind: GraphKind, id: number) =>
  useQuery({ queryKey: ['graph-changes', kind, id], queryFn: () => api.graphChanges(kind, id), staleTime: 60_000, enabled: id > 0 })

const Chevron = ({ open }: { open: boolean }) => open ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />

export function NewSince({ kind, id, what, className, data }: { kind: GraphKind; id: number; what: string; className?: string; data?: GraphChanges }) {
  const q = useGraphChanges(kind, id)
  const d = data ?? q.data
  const [open, setOpen] = useState(false)
  const [why, setWhy] = useState(false)
  if (!d) return null
  const r = d.review?.current ? d.review : null
  const updated = !!r && !!r.applied && r.facts.length > 0
  if (!d.count && !updated) return null
  const names = [...new Set(d.items.map((i) => i.who).filter(Boolean))].slice(0, 3)
  const note = d.count > 0 && d.unreviewed === 0 && r?.verdict === 'no change' ? `checked ${dayTime(r.at)}, nothing that changes it`
    : d.unreviewed > 0 && d.refreshing ? 'SleePO is reading it now' : ''
  return (
    <div className={cn('space-y-1 text-[12px] text-ink3', className)}>
      {updated && <div>
        <button onClick={() => setWhy(!why)} aria-expanded={why} className="inline-flex max-w-full items-center gap-1 text-left hover:text-ink">
          <Chevron open={why} />
          <span className="shrink-0 font-medium text-ink2">Updated {dayTime(r!.at)} from new material</span>
          {!why && <span className="truncate">· {r!.facts[0].text}</span>}
        </button>
        {why && <ul className="mt-1.5 space-y-1.5 border-l-2 border-line pl-3">
          {r!.facts.map((f, i) => (
            <li key={i} className="leading-snug">
              <span className="text-ink">{f.text}</span><span className="text-[11.5px]"> · {f.certainty}</span>
              {f.items.map((it) => <a key={it.item_id} href={it.app || undefined} className="block text-[11.5px] font-normal text-ink2 no-underline hover:underline">
                {it.who || it.label} · {it.label.toLowerCase()}{it.title ? ` · ${it.title}` : ''}{it.ts ? ` · ${dayTime(it.ts)}` : ''}</a>)}
            </li>))}
        </ul>}
      </div>}
      {d.count > 0 && <div>
        <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex max-w-full items-center gap-1 text-left hover:text-ink">
          <Chevron open={open} />
          <span className="shrink-0 font-medium text-ink2">{d.count} new since {what}</span>
          {note ? <span className="truncate">· {note}</span>
            : !open && names.length > 0 && <span className="truncate">· {names.join(', ')}{d.count > names.length ? '…' : ''}</span>}
        </button>
        {open && <ul className="mt-1.5 space-y-1 border-l-2 border-line pl-3">
          {d.items.map((i) => (
            <li key={i.item_id} className="leading-snug">
              <a href={i.app || undefined} className="font-normal text-ink no-underline hover:underline">{i.who ? <span className="font-medium">{i.who}</span> : i.label}
                {i.title && <> · {i.title}</>}</a>
              <span className="tabular-nums"> · {i.label.toLowerCase()} · {i.ts ? dayTime(i.ts) : ''}</span>
              {i.via && <span className="block text-[11.5px]">{i.via}</span>}
            </li>))}
          {d.count > d.items.length && <li className="text-[11.5px]">and {d.count - d.items.length} more</li>}
        </ul>}
      </div>}
    </div>
  )
}
