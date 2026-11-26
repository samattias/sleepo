// Roadmap: Rowan Lowell's Roadmap Workbook workbook (the single source of truth for the product roadmap), navigable.
// Timeline (quarters, grouped by strategic theme, roadmap group or owner), Board (by horizon) and List views; filters for
// status, theme, owner, committed and audience; click an initiative for everything the workbook says about it.
// The workbook is authoritative: SleePO keeps a snapshot, refreshed when the file changes (assist/roadmap.py), and on
// Refresh (Sam, 30 Oct 2026), which reads Rowan's workbook again now.
import { useSearchSync } from '@/lib/nav'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLink, Flag, RefreshCw, X } from 'lucide-react'
import { api, type RoadmapItem } from '@/lib/api'
import { ago, LOCALE } from '@/lib/time'
import { cn, usePersisted } from '@/lib/util'
import { btnClass, Loading, selectClass } from '@/components/ui'
import { FilterBar, FilterRow, Opt, Segmented } from '@/components/FilterBar'
import { org } from '@/lib/profile'
import { AssistPill } from '@/components/AssistPill'
import { roadmapPill } from '@/lib/assistPills'

const STATUS: Record<string, { label: string; bar: string; dot: string }> = {
  shipped: { label: 'Shipped', bar: 'bg-ink text-bg border-ink', dot: 'bg-ink' },
  inflight: { label: 'In flight', bar: 'bg-accent text-onaccent border-ink/30', dot: 'bg-accent ring-1 ring-ink/30' },
  planned: { label: 'Planned', bar: 'bg-panel text-ink border-ink', dot: 'border border-ink' },
  paused: { label: 'Paused', bar: 'bg-panel text-hot border-hot border-dashed', dot: 'border border-dashed border-hot' },
}
const THEMES = ['Big Bets', 'Strengthening the Core', 'Working Smarter']
const HORIZONS = ['Shipped', '0-6 mo', '6-12 mo', '12-24 mo', '24 mo+ / TBD']
const qIndex = (q: string) => { const m = /Q([1-4])\s+(\d{4})/.exec(q || ''); return m ? Number(m[2]) * 4 + Number(m[1]) - 1 : null }
const qLabel = (i: number) => `Q${(i % 4) + 1} ${Math.floor(i / 4)}`
const nowQ = (() => { const d = new Date(); return d.getFullYear() * 4 + Math.floor(d.getMonth() / 3) })()
const sel = selectClass
const AUD = { public: 'Public', nda: 'Under NDA', internal: 'Internal' } as const

export function Roadmap({ item }: { item?: string }) {
  const q = useQuery({ queryKey: ['roadmap'], queryFn: api.roadmap })
  const [f, setF] = usePersisted('assist-roadmap', { view: 'timeline' as 'timeline' | 'board' | 'list', group: 'theme' as 'theme' | 'grp' | 'owner',
    status: [] as string[], theme: '', owner: '', committed: false, audience: '' as '' | 'public' | 'nda' | 'internal', q: '' })
  const [open, setOpen] = useState<string | null>(item ?? null)
  useEffect(() => { if (item) setOpen(item) }, [item])
  useSearchSync('item', open)   // the open initiative stays in the address: Back returns to it (lib/nav.ts)
  const all = q.data?.items ?? []
  const owners = useMemo(() => [...new Set(all.flatMap((i) => i.owners))].sort(), [all])
  const list = useMemo(() => {
    const re = f.q.trim() ? new RegExp(f.q.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
    return all.filter((i) => (!f.status.length || f.status.includes(i.status)) && (!f.theme || i.theme === f.theme) && (!f.owner || i.owners.includes(f.owner))
      && (!f.committed || i.committed) && (!f.audience || (f.audience === 'public' ? i.show_public : f.audience === 'nda' ? i.show_nda : i.show_internal))
      && (!re || re.test([i.id, i.name_internal, i.name_external, i.value, i.detail, i.customers, i.grp, i.owners.join(' ')].join(' '))))
  }, [all, f])
  if (!q.data) return <Loading />
  const meta = q.data.meta
  const cur = all.find((i) => i.id === open)
  const toggleStatus = (s: string) => setF({ ...f, status: f.status.includes(s) ? f.status.filter((x) => x !== s) : [...f.status, s] })

  return (
    <div className="max-w-[1400px]">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Roadmap</h1>
        <span className="text-[13px] text-ink2">{list.length === all.length ? `${all.length} initiatives` : `${list.length} of ${all.length}`}{meta?.modified ? ` · last changed ${new Date(meta.modified).toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' })}` : ''}</span>
        <RoadmapRefresh />
        {meta && <a href={meta.url} target="_blank" rel="noopener" className={btnClass('outline')}>
          <ExternalLink size={13} />Open the workbook</a>}
      </div>

      <FilterBar search={f.q} onSearch={(v) => setF({ ...f, q: v })} placeholder="Search initiatives, customers…"
        tokens={[
          ...f.status.map((k) => ({ label: STATUS[k]?.label ?? k, onRemove: () => toggleStatus(k) })),
          ...(f.committed ? [{ label: 'Committed', onRemove: () => setF({ ...f, committed: false }) }] : []),
          ...(f.theme ? [{ label: f.theme, onRemove: () => setF({ ...f, theme: '' }) }] : []),
          ...(f.owner ? [{ label: f.owner, onRemove: () => setF({ ...f, owner: '' }) }] : []),
          ...(f.audience ? [{ label: AUD[f.audience], onRemove: () => setF({ ...f, audience: '' }) }] : []),
        ]}
        onClear={() => setF({ ...f, status: [], theme: '', owner: '', committed: false, audience: '', q: '' })}
        right={<>
          {f.view === 'timeline' && <select aria-label="Group by" value={f.group} onChange={(e) => setF({ ...f, group: e.target.value as typeof f.group })} className={sel}>
            <option value="theme">By theme</option><option value="grp">By roadmap group</option><option value="owner">By owner</option></select>}
          <Segmented value={f.view} onChange={(v) => setF({ ...f, view: v })} options={[['timeline', 'Timeline'], ['board', 'By horizon'], ['list', 'List']]} />
        </>}>
        <FilterRow label="Status">
          {Object.entries(STATUS).map(([k, s]) => <Opt key={k} on={f.status.includes(k)} onClick={() => toggleStatus(k)} count={all.filter((i) => i.status === k).length}>{s.label}</Opt>)}
          <Opt on={f.committed} onClick={() => setF({ ...f, committed: !f.committed })} count={all.filter((i) => i.committed).length}>Committed</Opt>
        </FilterRow>
        <FilterRow label="Theme">
          <Opt on={!f.theme} onClick={() => setF({ ...f, theme: '' })}>All</Opt>
          {THEMES.map((t) => <Opt key={t} on={f.theme === t} onClick={() => setF({ ...f, theme: f.theme === t ? '' : t })} count={all.filter((i) => i.theme === t).length}>{t}</Opt>)}
        </FilterRow>
        <FilterRow label="Owner">
          <select aria-label="Owner" value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} className={sel}><option value="">All owners</option>{owners.map((o) => <option key={o}>{o}</option>)}</select>
        </FilterRow>
        <FilterRow label="Audience">
          <Opt on={!f.audience} onClick={() => setF({ ...f, audience: '' })}>Any</Opt>
          {(Object.keys(AUD) as (keyof typeof AUD)[]).map((a) => <Opt key={a} on={f.audience === a} onClick={() => setF({ ...f, audience: f.audience === a ? '' : a })}>{AUD[a]}</Opt>)}
        </FilterRow>
      </FilterBar>

      {list.length === 0 ? <p className="text-[13px] text-ink2">No initiatives match.</p>
        : f.view === 'timeline' ? <Timeline items={list} group={f.group} onOpen={setOpen} />
        : f.view === 'board' ? <Board items={list} onOpen={setOpen} />
        : <List items={list} onOpen={setOpen} />}
      {cur && <Detail it={cur} url={meta?.url} onClose={() => setOpen(null)} />}
    </div>
  )
}

// Refresh: read the latest Initiatives sheet of Rowan's workbook now (a short connector run on the server, a minute or two;
// read only). The server loads it only when it differs, and says what changed by initiative ID; the page reloads after.
function RoadmapRefresh() {
  const qc = useQueryClient()
  const st = useQuery({ queryKey: ['roadmapRefresh'], queryFn: api.roadmapRefreshState, refetchInterval: (q) => (q.state.data?.running ? 4000 : false) })
  const [err, setErr] = useState('')
  const was = useRef(false)
  const d = st.data
  useEffect(() => {   // a run just ended: reload the roadmap
    if (was.current && d && !d.running) qc.invalidateQueries({ queryKey: ['roadmap'] })
    was.current = !!d?.running
  }, [d?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  const run = async () => {
    setErr('')
    try { qc.setQueryData(['roadmapRefresh'], await api.roadmapRefresh()) } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
  }
  const owner = org().roadmap_owner ? `${org().roadmap_owner.split(' ')[0]}'s ` : 'the '   // the org pack's roadmap owner
  const note = err || (d?.running ? `Reading ${owner}workbook: a minute or two` : d?.finished && d.note ? `${d.note} · ${ago(d.finished)}` : '')
  return (
    <>
      <span className={cn('ml-auto min-w-0 truncate text-[12px]', err || d?.ok === false ? 'text-hot' : 'text-ink3')} title={d?.note || ''}>{note}</span>
      <button onClick={run} disabled={!!d?.running} title={d?.running ? `Reading ${owner}workbook` : `Read the latest version of ${owner}roadmap workbook now (read only)`}
        className={btnClass('outline', 'sm', 'shrink-0')}>
        <RefreshCw size={13} aria-hidden className={cn(d?.running && 'animate-spin')} />{d?.running ? 'Refreshing…' : 'Refresh'}</button>
    </>
  )
}

function Timeline({ items, group, onOpen }: { items: RoadmapItem[]; group: 'theme' | 'grp' | 'owner'; onOpen: (id: string) => void }) {
  const idx = items.flatMap((i) => [qIndex(i.start_q), qIndex(i.end_q)]).filter((x): x is number => x != null)
  const lo = Math.min(nowQ - 2, ...idx), hi = Math.max(nowQ + 4, ...idx)
  const qs = Array.from({ length: hi - lo + 1 }, (_, k) => lo + k)
  const cols = `minmax(220px,300px) repeat(${qs.length}, minmax(64px,1fr)) 64px`
  const key = (i: RoadmapItem) => group === 'theme' ? i.theme : group === 'grp' ? i.grp : (i.owners[0] ?? 'No owner')
  const groups = [...new Set(items.map(key))].sort((a, b) => group === 'theme' ? THEMES.indexOf(a) - THEMES.indexOf(b) : a.localeCompare(b))
  return (
    <div className="overflow-x-auto border border-line bg-panel">
      <div className="min-w-[900px]">
        <div className="sticky top-0 z-[1] grid border-b border-line bg-panel2 text-[12px] font-semibold" style={{ gridTemplateColumns: cols }}>
          <div className="px-3 py-1.5">Initiative</div>
          {qs.map((qq) => <div key={qq} className={cn('border-l border-line px-1.5 py-1.5 text-center', qq === nowQ && 'bg-accentbg')}>{qLabel(qq)}{qq === nowQ ? ' · now' : ''}</div>)}
          <div className="border-l border-line px-1.5 py-1.5 text-center">TBD</div>
        </div>
        {groups.map((g) => (
          <div key={g}>
            <div className="border-b border-line bg-panel px-3 py-1.5 text-[13px] font-semibold">{g} <span className="font-normal text-ink2">· {items.filter((i) => key(i) === g).length}</span></div>
            {items.filter((i) => key(i) === g).sort((a, b) => (qIndex(a.start_q) ?? 9e9) - (qIndex(b.start_q) ?? 9e9)).map((i) => {
              const s = qIndex(i.start_q), e = qIndex(i.end_q) ?? s
              const st = STATUS[i.status] ?? STATUS.planned
              return (
                <div key={i.id} className="grid border-b border-line2 text-[12.5px] hover:bg-panel2" style={{ gridTemplateColumns: cols }}>
                  <button onClick={() => onOpen(i.id)} style={{ gridRow: 1, gridColumn: 1 }} className="truncate px-3 py-1.5 text-left" title={i.name_internal}>
                    <span className="mr-1.5 font-mono text-[11px] text-ink2">{i.id}</span>{i.name_internal}</button>
                  {qs.map((qq, k) => <div key={qq} style={{ gridRow: 1, gridColumn: k + 2 }} className={cn('border-l border-line2', qq === nowQ && 'bg-accentbg/60')} />)}
                  <div style={{ gridRow: 1, gridColumn: qs.length + 2 }} className="border-l border-line2" />
                  {/* the bar spans its quarters (or sits in TBD) */}
                  <button onClick={() => onOpen(i.id)} title={`${i.name_internal} · ${st.label} · ${i.start_q}–${i.end_q}`}
                    className={cn('z-0 my-1 flex items-center gap-1 overflow-hidden whitespace-nowrap border px-1.5 text-[11px] font-medium', st.bar)}
                    style={{ gridRow: 1, gridColumn: s == null ? `${qs.length + 2} / span 1` : `${s - lo + 2} / ${(e ?? s) - lo + 3}` }}>
                    {i.committed && <Flag size={10} className="shrink-0" />}{i.size ? `${i.size} · ` : ''}{i.name_external || i.name_internal}</button>
                </div>)
            })}
          </div>))}
      </div>
    </div>
  )
}

function Board({ items, onOpen }: { items: RoadmapItem[]; onOpen: (id: string) => void }) {
  return (
    <div className="grid gap-3 overflow-x-auto md:grid-cols-5">
      {HORIZONS.map((h) => { const col = items.filter((i) => i.horizon === h); return (
        <div key={h} className="min-w-[200px]">
          <div className="mb-1.5 flex items-baseline gap-2 border-b-2 border-ink pb-1 text-[13px] font-semibold">{h}<span className="font-normal text-ink2">{col.length}</span></div>
          <div className="space-y-2">{col.map((i) => { const st = STATUS[i.status] ?? STATUS.planned; return (
            <button key={i.id} onClick={() => onOpen(i.id)} className="block w-full border border-line bg-panel p-2.5 text-left hover:border-ink">
              <div className="flex items-center gap-1.5 text-[11px] text-ink2"><span className={cn('size-2 rounded-full', st.dot)} /><span className="font-mono">{i.id}</span>{i.committed && <Flag size={10} />}<span className="ml-auto">{i.size}</span></div>
              <div className="mt-1 text-[13px] font-medium leading-snug">{i.name_internal}</div>
              <div className="mt-1 text-[11.5px] text-ink2">{i.start_q}{i.end_q && i.end_q !== i.start_q ? `–${i.end_q}` : ''}{i.owners.length ? ` · ${i.owners.join(', ')}` : ''}</div>
            </button>) })}</div>
        </div>) })}
    </div>
  )
}

function List({ items, onOpen }: { items: RoadmapItem[]; onOpen: (id: string) => void }) {
  const [sort, setSort] = useState<{ k: keyof RoadmapItem; desc: boolean }>({ k: 'start_q', desc: false })
  const val = (i: RoadmapItem, k: keyof RoadmapItem) => k === 'start_q' || k === 'end_q' ? (qIndex(String(i[k])) ?? 9e9) : String(i[k] ?? '')
  const rows = [...items].sort((a, b) => { const x = val(a, sort.k), y = val(b, sort.k); const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y)); return sort.desc ? -c : c })
  const Th = ({ k, children }: { k: keyof RoadmapItem; children: string }) => <th className="cursor-pointer select-none whitespace-nowrap px-2 py-2 hover:text-ink" onClick={() => setSort({ k, desc: sort.k === k ? !sort.desc : false })}>{children}{sort.k === k ? (sort.desc ? ' ↓' : ' ↑') : ''}</th>
  return (
    <div className="overflow-x-auto border border-line bg-panel">
      <table className="w-full border-collapse text-[13px]">
        <thead><tr className="border-b border-line text-left text-[12px] text-ink2"><Th k="id">ID</Th><Th k="name_internal">Initiative</Th><Th k="theme">Theme</Th><Th k="status">Status</Th><Th k="start_q">Start</Th><Th k="end_q">End</Th><Th k="size">Size</Th><Th k="confidence">Confidence</Th><th className="px-2 py-2">Owners</th><Th k="customers">Customers</Th></tr></thead>
        <tbody>{rows.map((i) => { const st = STATUS[i.status] ?? STATUS.planned; return (
          <tr key={i.id} onClick={() => onOpen(i.id)} className="cursor-pointer border-b border-line2 hover:bg-panel2 [&>td]:px-2 [&>td]:py-1.5 [&>td]:align-top">
            <td className="whitespace-nowrap font-mono text-[11.5px] text-ink2">{i.id}</td>
            <td className="font-medium">{i.name_internal}{i.committed && <Flag size={11} className="ml-1 inline" />}</td>
            <td className="whitespace-nowrap text-ink2">{i.theme}</td>
            <td className="whitespace-nowrap"><span className="inline-flex items-center gap-1.5"><span className={cn('size-2 rounded-full', st.dot)} />{st.label}</span></td>
            <td className="whitespace-nowrap">{i.start_q}</td><td className="whitespace-nowrap">{i.end_q}</td><td>{i.size}</td><td>{i.confidence}</td>
            <td className="text-ink2">{i.owners.join(', ')}</td><td className="max-w-[220px] truncate text-ink2">{i.customers}</td>
          </tr>) })}</tbody>
      </table>
    </div>
  )
}

function Detail({ it, url, onClose }: { it: RoadmapItem; url?: string; onClose: () => void }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); addEventListener('keydown', k); return () => removeEventListener('keydown', k) }, [onClose])
  const st = STATUS[it.status] ?? STATUS.planned
  const aud = [it.show_public && 'public', it.show_nda && 'NDA', it.show_investor && 'investors', it.show_internal && 'internal'].filter(Boolean).join(', ')
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} />
      <aside role="dialog" aria-label={it.name_internal} className="fixed bottom-0 right-0 top-0 z-50 flex w-[min(560px,100vw)] flex-col border-l border-line bg-panel shadow-2xl">
        <header className="border-b border-line px-5 pb-3 pt-3.5">
          <div className="flex items-center gap-2 text-[12.5px] text-ink2">
            <span className={cn('size-2 rounded-full', st.dot)} /><span className="font-medium text-ink">{st.label}</span>{it.committed && <><span>·</span><span className="inline-flex items-center gap-1 font-medium text-ink"><Flag size={11} />committed</span></>}
            <span>·</span><span className="font-mono">{it.id}</span>
            <button onClick={onClose} aria-label="Close (Esc)" className="-mr-1.5 ml-auto p-1 text-ink hover:bg-panel2"><X size={17} /></button>
          </div>
          <h2 className="mt-1 text-[18px] font-semibold leading-snug">{it.name_internal}</h2>
          {it.name_external && it.name_external !== it.name_internal && <div className="text-[13px] text-ink2">Externally: {it.name_external}</div>}
        </header>
        <div className="flex-1 overflow-auto px-5 py-4 text-[13.5px]">
          <dl className="grid grid-cols-[92px_1fr] gap-x-3 gap-y-1.5 text-[13px]">
            <dt className="text-ink2">When</dt><dd>{it.start_q}{it.end_q && it.end_q !== it.start_q ? ` to ${it.end_q}` : ''} · {it.horizon}</dd>
            <dt className="text-ink2">Theme</dt><dd>{it.theme} › {it.grp}{it.platform_theme ? ` · ${it.platform_theme}` : ''}</dd>
            <dt className="text-ink2">Owners</dt><dd>{it.owners.length ? it.owners.map((o, k) => <span key={o}>{k ? ', ' : ''}{it.owner_ids[o] ? <Link to="/people/$id" params={{ id: it.owner_ids[o] }}>{o}</Link> : o}</span>) : <span className="text-hot">no owner yet</span>}</dd>
            <dt className="text-ink2">Size</dt><dd>{it.size || <span className="text-hot">not sized</span>}{it.confidence ? ` · ${it.confidence} confidence` : ''}</dd>
            {it.customers && <><dt className="text-ink2">Customers</dt><dd>{it.customers}</dd></>}
            <dt className="text-ink2">Audience</dt><dd>{aud || 'none'}</dd>
          </dl>
          {it.value && <section className="mt-4"><h3 className="mb-1 text-[13px] font-semibold">Value</h3><p className="leading-relaxed">{it.value}</p></section>}
          {it.detail && <section className="mt-4"><h3 className="mb-1 text-[13px] font-semibold">Detail</h3><p className="leading-relaxed text-ink2">{it.detail}</p></section>}
          {it.gap && <section className="mt-4 border-l-2 border-hot pl-3"><h3 className="mb-1 text-[13px] font-semibold">Gap</h3><p className="leading-relaxed">{it.gap}</p></section>}
          {it.notes && <section className="mt-4"><h3 className="mb-1 text-[13px] font-semibold">Notes (internal)</h3><p className="whitespace-pre-line leading-relaxed text-ink2">{it.notes.split(' | ').join('\n')}</p></section>}
          {url && <a href={url} target="_blank" rel="noopener" className="mt-5 inline-flex items-center gap-1.5 text-[13px]"><ExternalLink size={13} />Source: Roadmap Workbook workbook ({it.src})</a>}
        </div>
        {/* the assistant pill (Sam, 16 Nov 2026): where it stands, its money story, an update, with the item's chip (the entry and
            what was said about it lately); clear of the floating Ask SleePO button */}
        <div className="border-t border-line bg-panel py-2.5 pl-5 pr-20"><AssistPill key={it.id} target={{ kind: 'roadmap', ref: it.id }} {...roadmapPill()} /></div>
      </aside>
    </>
  )
}
