// Search across everything: one ranked list with snippets, filters by kind, and every result opens the exact thing.
// Query syntax: "exact phrase", type:email|meeting|transcript|doc|person|commitment|chat|attachment|event|library,
// from:gray, after:2026-09-01, before:2026-10-01. Acronyms expand from the glossary (PLT ↔ Agentic Platform).
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { BookOpen, CalendarDays, CircleCheck, FileText, Mail, MessageSquare, Mic, Monitor, Paperclip, Map as MapIcon, Search as SearchIcon, Target, User, Video, type LucideIcon } from 'lucide-react'
import { api, type SearchHit, type SearchResult } from '@/lib/api'
import { cn } from '@/lib/util'
import { Empty, Loading, Muted } from '@/components/ui'
import { Opt } from '@/components/FilterBar'
import { openDoc } from '@/components/DocChip'
import { isTextName, viewDoc } from '@/components/DocViewer'
import { TZ, LOCALE } from '@/lib/time'

export const KIND: Record<string, { label: string; icon: LucideIcon }> = {
  person: { label: 'People', icon: User }, initiative: { label: 'Initiatives', icon: Target },
  commitment: { label: 'Commitments', icon: CircleCheck }, meeting: { label: 'Meetings', icon: Video }, transcript: { label: 'Transcripts', icon: Mic }, screen: { label: 'On screen', icon: Monitor },
  email: { label: 'Emails', icon: Mail }, chat: { label: 'Chat', icon: MessageSquare }, attachment: { label: 'Attachments', icon: Paperclip },
  document: { label: 'Documents', icon: FileText }, library: { label: 'Library', icon: BookOpen }, event: { label: 'Calendar', icon: CalendarDays }, roadmap: { label: 'Roadmap', icon: MapIcon },
}
const ORDER = ['person', 'initiative', 'commitment', 'meeting', 'email', 'document', 'attachment', 'transcript', 'screen', 'chat', 'roadmap', 'library', 'event']
const date = (ts: string) => { try { return ts ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(ts.length === 10 ? ts : ts.replace(' ', 'T'))) : '' } catch { return '' } }

// snippets come back with \u0002…\u0003 around matched words
export function Hl({ text }: { text: string }) {
  const parts: ReactNode[] = []
  text.split('\u0002').forEach((chunk, i) => {
    if (i === 0) { parts.push(chunk); return }
    const [hit, rest = ''] = chunk.split('\u0003')
    parts.push(<mark key={i} style={{ background: 'var(--accent)', color: '#0a0a0a' }}>{hit}</mark>, rest)
  })
  return <>{parts}</>
}

export function useOpenHit() {
  const nav = useNavigate()
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.documents, staleTime: 300_000 })
  return (h: SearchHit, q?: string) => {
    if (h.url.startsWith('doc:')) { const d = docs.data?.find((x) => x.id === h.url.slice(4)); if (d) openDoc(d); return }
    if (h.url.startsWith('http') && isTextName(h.url)) { const d = docs.data?.find((x) => x.url === h.url); if (d) { viewDoc(d); return } }
    if (h.url.startsWith('http')) { window.open(h.url, '_blank', 'noopener'); return }
    if (h.kind === 'transcript' && q) { window.location.hash = `${h.url}?q=${encodeURIComponent(q.replace(/\b\w+:\S+/g, '').replace(/"/g, '').trim())}`; return }
    window.location.hash = h.url
    void nav
  }
}

export function SearchPage({ q }: { q: string }) {
  const nav = useNavigate()
  const [text, setText] = useState(q)
  const [kind, setKind] = useState('')
  const [cur, setCur] = useState(0)
  const open = useOpenHit()
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => { setText(q); setKind(''); setCur(0) }, [q])
  const s = useQuery({ queryKey: ['search2', q], queryFn: () => api.search(q, 200), enabled: q.trim().length >= 2 })
  const data: SearchResult | undefined = s.data
  const hits = useMemo(() => (data?.results ?? []).filter((h) => !kind || h.kind === kind), [data, kind])
  useEffect(() => { list.current?.querySelector(`[data-i="${cur}"]`)?.scrollIntoView({ block: 'nearest' }) }, [cur])
  const go = (e: React.FormEvent) => { e.preventDefault(); nav({ to: '/search', search: { q: text } }) }

  return (
    <div className="max-w-[1000px]" onKeyDown={(e) => {
      if ((e.target as HTMLElement).tagName === 'INPUT' && e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      if (e.key === 'ArrowDown') { e.preventDefault(); setCur((c) => Math.min(c + 1, hits.length - 1)) }
      if (e.key === 'ArrowUp') { e.preventDefault(); setCur((c) => Math.max(c - 1, 0)) }
      if (e.key === 'Enter' && hits[cur]) open(hits[cur], q)
    }}>
      <form onSubmit={go} className="relative mb-3">
        <SearchIcon size={18} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink2" />
        <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="Search people, meetings, emails, documents…"
          className="w-full rounded-full border border-line bg-panel py-2.5 pl-10 pr-4 text-[16px] text-ink outline-none placeholder:text-ink3 focus:border-ink focus:ring-2 focus:ring-accent" />
      </form>
      {q.trim().length < 2 ? <Tips /> : !data ? <Loading /> : <>
        <div className="mb-2 flex flex-wrap items-center gap-1">
          <Opt on={!kind} onClick={() => { setKind(''); setCur(0) }} count={data.total}>All</Opt>
          {ORDER.filter((k) => data.counts[k]).map((k) => <Opt key={k} on={kind === k} onClick={() => { setKind(kind === k ? '' : k); setCur(0) }} count={data.counts[k]}>{KIND[k].label}</Opt>)}
        </div>
        <Muted className="mb-3 text-[12.5px]">
          {data.total} result{data.total === 1 ? '' : 's'}{data.mode === 'some words' ? ' · showing items that match some of your words' : data.mode === 'partial match' ? ' · partial matches' : ''}
          {data.expanded.length > 0 && <> · also searched <b className="text-ink">{data.expanded.join(', ')}</b></>}
          {data.filters.types.length > 0 && <> · only {data.filters.types.map((t) => KIND[t]?.label ?? t).join(', ')}</>}
          {data.filters.from.length > 0 && <> · from {data.filters.from.join(', ')}</>}
          {(data.filters.after || data.filters.before) && <> · {data.filters.after ? `after ${data.filters.after}` : ''} {data.filters.before ? `before ${data.filters.before}` : ''}</>}
        </Muted>
        {hits.length === 0 ? <Empty>Nothing found.</Empty> : (
          <div ref={list} className="border border-line bg-panel">
            {hits.map((h, i) => <Row key={h.kind + h.ref} h={h} i={i} on={i === cur} onOpen={() => open(h, q)} onHover={() => setCur(i)} />)}
          </div>
        )}
        {data.total > hits.length && !kind && <Muted className="mt-2">Showing the best {hits.length}.</Muted>}
      </>}
    </div>
  )
}

function Row({ h, i, on, onOpen, onHover }: { h: SearchHit; i: number; on: boolean; onOpen: () => void; onHover: () => void }) {
  const K = KIND[h.kind] ?? { label: h.kind, icon: FileText }
  return (
    <button data-i={i} onClick={onOpen} onMouseMove={onHover} className={cn('flex w-full gap-3 border-b border-l-2 border-b-line2 px-4 py-3 text-left last:border-b-0', on ? 'border-l-accent bg-accentbg' : 'border-l-transparent')}>
      <K.icon size={17} className="mt-0.5 shrink-0" strokeWidth={1.75} />
      <span className="min-w-0 flex-1">
        <span className="block text-[14.5px] font-medium [overflow-wrap:anywhere]"><Hl text={h.title_hl || h.title} /></span>
        <span className="mt-0.5 block text-[12.5px] text-ink2">{K.label.replace(/s$/, '')}{h.sub ? ` · ${h.sub}` : ''}{h.ts ? ` · ${date(h.ts)}` : ''}{h.more ? (h.kind === 'email' ? ` · +${h.more} more in this thread` : ` · also in ${h.more} other place${h.more > 1 ? 's' : ''}`) : ''}</span>
        {h.snippet && <span className="mt-1 line-clamp-2 block text-[13px] leading-relaxed text-ink2"><Hl text={h.snippet} /></span>}
      </span>
    </button>
  )
}

function Tips() {
  return (
    <div className="text-[12.5px] leading-relaxed text-ink3">
      <code>"exact phrase"</code> · <code>type:email</code> · <code>from:gray</code> · <code>after:2026-09-01</code> · <code>before:…</code> · acronyms expand from the glossary
    </div>
  )
}
