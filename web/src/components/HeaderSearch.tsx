// Header search with instant results: the best few matches across everything as you type (↑ ↓ Enter),
// or Enter on the box for the full results page.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { FileText, Search } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/util'
import { popoverClass } from './ui'
import { Hl, KIND, useOpenHit } from '@/views/search'

export function HeaderSearch() {
  const nav = useNavigate()
  const open = useOpenHit()
  const [q, setQ] = useState('')
  const [deb, setDeb] = useState('')
  const [show, setShow] = useState(false)
  const [cur, setCur] = useState(-1)
  const box = useRef<HTMLFormElement>(null)
  useEffect(() => { const t = setTimeout(() => setDeb(q.trim()), 140); return () => clearTimeout(t) }, [q])
  const s = useQuery({ queryKey: ['suggest', deb], queryFn: () => api.suggest(deb), enabled: deb.length >= 2, staleTime: 30_000 })
  const hits = deb.length >= 2 ? s.data?.results ?? [] : []
  useEffect(() => { setCur(-1) }, [deb])
  useEffect(() => {
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setShow(false) }
    document.addEventListener('mousedown', away); return () => document.removeEventListener('mousedown', away)
  }, [])
  const full = () => { setShow(false); nav({ to: '/search', search: { q } }) }

  return (
    <form ref={box} role="search" className="relative mx-auto w-full min-w-0 max-w-[560px]" onSubmit={(e) => { e.preventDefault(); if (cur >= 0 && hits[cur]) { setShow(false); open(hits[cur], q) } else full() }}>
      <Search size={15} aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink3/60" />
      {/* Always white, in both themes, so the text colours are fixed rather than theme tokens. */}
      <input id="globalsearch" aria-label="Search everything" autoComplete="off" value={q}
        onChange={(e) => { setQ(e.target.value); setShow(true) }} onFocus={() => setShow(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setShow(true); setCur((c) => Math.min(c + 1, hits.length)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setCur((c) => Math.max(c - 1, -1)) }
          if (e.key === 'Escape') { setShow(false); (e.target as HTMLInputElement).blur() }
        }}
        placeholder="Search" className="w-full rounded-full border border-line bg-panel py-1.5 pl-9 pr-4 text-[13.5px] text-ink outline-none placeholder:text-ink3/45 focus:border-ink focus:ring-2 focus:ring-accent" />
      {show && deb.length >= 2 && (
        <div className={cn(popoverClass, 'absolute left-0 right-0 top-[calc(100%+6px)] z-50')}>
          {s.isFetching && !hits.length && <div className="px-3 py-2.5 text-[13px] text-ink2">Searching…</div>}
          {!s.isFetching && !hits.length && <div className="px-3 py-2.5 text-[13px] text-ink2">No matches. Press Enter for the full search.</div>}
          {hits.map((h, i) => { const K = KIND[h.kind] ?? { label: h.kind, icon: FileText }; return (
            <button type="button" key={h.kind + h.ref} onMouseEnter={() => setCur(i)} onClick={() => { setShow(false); open(h, q) }}
              className={cn('flex w-full items-start gap-2.5 border-l-2 px-3 py-2 text-left', i === cur ? 'border-l-accent bg-accentbg' : 'border-l-transparent')}>
              <K.icon size={15} className="mt-0.5 shrink-0" strokeWidth={1.75} />
              <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium"><Hl text={h.title_hl || h.title} /></span>
                <span className="block truncate text-[12px] text-ink2">{K.label.replace(/s$/, '')}{h.sub ? ` · ${h.sub}` : ''}</span></span>
            </button>) })}
          {hits.length > 0 && <button type="button" onClick={full} onMouseEnter={() => setCur(hits.length)}
            className={cn('block w-full border-t border-line px-3 py-2 text-left text-[12.5px] font-medium', cur === hits.length ? 'bg-accentbg' : 'hover:bg-panel2')}>
            See all {s.data?.total ?? ''} results for “{q.trim()}” →</button>}
        </div>
      )}
    </form>
  )
}
