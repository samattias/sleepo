// Graph: people in the middle, everything else around the people it involves.
// Sam sits at the centre; people sit in rows around him, nearest first by days in touch with him in the last 90, each in
// their team's direction. Rings outside, inside out: the bets and day-to-day areas the work is filed under, what is top of
// mind and the tasks on Sam's list, the companies (with their logos), then meetings and documents; each thing at the angle
// of the people on it, so a person's work fans out behind them. Sam, 29 Oct 2026: the ontology follows the app (bet or area
// → task → step; Companies; Top of mind), not the open-items register.
// The layout is computed once (d3-force) and pinned, drawn on canvas with react-force-graph-2d; click a node to light up
// its neighbourhood. assist/graph.py builds the data: every edge has a person at one end except ties between two things.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods, type NodeObject } from 'react-force-graph-2d'
import { forceCollide, forceRadial, forceSimulation, forceX, forceY } from 'd3-force'
import { useQuery } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { api, type GEdge, type GNode } from '@/lib/api'
import { cn } from '@/lib/util'
import { btnClass, Empty, inputClass, Loading, popoverClass, selectClass } from '@/components/ui'
import { FilterBar, FilterRow, Opt } from '@/components/FilterBar'

// suggested tasks (still waiting on Sam's yes) are shown and hidden on their own
type T = GNode['type'] | 'suggested'
const TYPES: { key: T; label: string; plural: string }[] = [
  { key: 'person', label: 'Person', plural: 'People' },
  { key: 'partner', label: 'Outside person', plural: 'Outside people' },
  { key: 'initiative', label: 'Bet', plural: 'Bets' },
  { key: 'area', label: 'Day-to-day area', plural: 'Areas' },
  { key: 'topic', label: 'Top of mind', plural: 'Top of mind' },
  { key: 'task', label: 'Task', plural: 'Tasks' },
  { key: 'suggested', label: 'Suggested task', plural: 'Suggested tasks' },
  { key: 'org', label: 'Company', plural: 'Companies' },
  { key: 'meeting', label: 'Meeting', plural: 'Meetings' },
  { key: 'document', label: 'Document', plural: 'Documents' },
]
const TYPE_LABEL = Object.fromEntries(TYPES.map((t) => [t.key, t.label])) as Record<T, string>
const kindOf = (n: GNode): T => (n.type === 'task' && n.status === 'suggested' ? 'suggested' : n.type)
const PEOPLE = new Set<T>(['person', 'partner'])
const EVEN = new Set<T>(['initiative', 'area'])   // spaced evenly round their ring, bets first
// the rings around the people, inside out: what the work is for, what is live now, who it is with, then the record
const RINGS: { types: T[]; label: string }[] = [
  { types: ['initiative', 'area'], label: 'Bets & areas' },
  { types: ['topic', 'task', 'suggested'], label: 'Top of mind & tasks' },
  { types: ['org'], label: 'Companies' },
  { types: ['meeting'], label: 'Meetings' },
  { types: ['document'], label: 'Documents' },
]
const CLOSEST = 10   // the people nearest Sam keep their names at any zoom
// teams round the circle: building the product, then the customer side, then the company; other teams and outside
// organisations follow, largest first
const TEAM_ORDER = ['Product Management', 'R&D', 'Professional Services', 'Customer Success', 'Sales', 'Marketing', 'G&A']
const ROW = 50, SEAT = 60   // distance between rows of people, and the room each person (and name) gets in a row

type FNode = GNode & { x?: number; y?: number; fx?: number; fy?: number }
// person–person, person–thing; thing–thing and Sam's own ties are drawn only when one end is selected
type Kind = 'pp' | 'pt' | 'tt' | 'me'
type FLink = { source: string; target: string; rel: string; w: number; kind: Kind }
type Ring = { label: string; types: T[]; r0: number; r1: number }
type Size = 'activity' | 'uniform'

// canvas cannot read CSS variables, so resolve the theme tokens and repaint when the theme flips
function useThemeColors() {
  const read = () => {
    const cs = getComputedStyle(document.documentElement)
    const v = (k: string) => cs.getPropertyValue(k).trim()
    return {
      bg: v('--panel'), ink: v('--ink'), ink2: v('--ink2'), ink3: v('--ink3'), line: v('--line'), accent: v('--accent'),
      type: Object.fromEntries(TYPES.map((t) => [t.key, v(`--g-${t.key === 'suggested' ? 'task' : t.key}`)])) as Record<T, string>,
    }
  }
  const [c, setC] = useState(read)
  useEffect(() => {
    const mo = new MutationObserver(() => setC(read()))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const mq = matchMedia('(prefers-color-scheme: dark)'); const f = () => setC(read())
    mq.addEventListener('change', f)
    return () => { mo.disconnect(); mq.removeEventListener('change', f) }
  }, [])
  return c
}

// deterministic PRNG so the picture is the same on every load
function rng(seed: number) { return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296 } }

// people by how much they are in touch with Sam, bets by weight, topics by rank, companies and the rest by connections
const radius = (n: GNode, deg: number, uniform = false) => n.me ? 18
  : PEOPLE.has(n.type) ? Math.max(n.avatar ? 7 : 0, uniform ? 8 : Math.min(15, 6 + Math.sqrt(n.contact ?? 0)))
  : n.type === 'initiative' ? 9 + (n.weight ?? 3) * 1.6
  : n.type === 'area' ? 9
  : n.type === 'org' ? (uniform ? 10 : Math.min(15, 9 + Math.sqrt(deg)))
  : n.type === 'topic' ? (uniform ? 7 : 6 + (11 - Math.min(n.rank ?? 10, 10)) * 0.55)
  : n.type === 'task' ? (n.status === 'suggested' ? 4.5 : 6)
  : uniform ? 4 : Math.min(10, 3.5 + deg * 0.45)

// Sam fixed in the middle, people in rows around him, then each ring of things at the mean angle of its people
function layout(nodes: FNode[], edges: GEdge[]): { rings: Ring[]; rp: number } {
  const rand = rng(7)
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const deg = new Map<string, number>()
  for (const e of edges) { deg.set(e.source, (deg.get(e.source) ?? 0) + 1); deg.set(e.target, (deg.get(e.target) ?? 0) + 1) }
  for (const n of nodes) if (n.me) { n.x = n.fx = 0; n.y = n.fy = 0 }

  const people = nodes.filter((n) => PEOPLE.has(n.type) && !n.me)
  const byContact = [...people].sort((a, b) => (b.contact ?? 0) - (a.contact ?? 0) || a.label.localeCompare(b.label))
  // each team gets a sector in proportion to its size; its middle is the direction its people face
  const size = new Map<string, number>()
  for (const n of people) size.set(n.group ?? '', (size.get(n.group ?? '') ?? 0) + 1)
  const rank = (g: string) => { const i = TEAM_ORDER.indexOf(g); return i < 0 ? TEAM_ORDER.length : i }
  const teams = [...size.entries()].sort((a, b) => rank(a[0]) - rank(b[0]) || b[1] - a[1] || a[0].localeCompare(b[0]))
  const facing = new Map<string, number>()
  let done = 0
  for (const [g, k] of teams) { facing.set(g, -Math.PI / 2 + ((done + k / 2) / Math.max(people.length, 1)) * Math.PI * 2); done += k }
  // rows filled nearest first; in a row, people are evenly spaced (so names never pile up) in the order of their teams,
  // turned so that everyone sits as close as possible to their team's direction
  const R0 = 70, angle = new Map<string, number>()
  let row = 0
  for (let left = byContact; left.length; row++) {
    const rr = R0 + row * ROW, seats = Math.max(6, Math.floor((2 * Math.PI * rr) / SEAT))
    const members = left.slice(0, seats).map((n) => ({ n, want: facing.get(n.group ?? '')! })).sort((a, b) => a.want - b.want || a.n.label.localeCompare(b.n.label))
    left = left.slice(seats)
    const step = (Math.PI * 2) / members.length
    let sx = 0, sy = 0
    members.forEach((m, i) => { sx += Math.cos(m.want - i * step); sy += Math.sin(m.want - i * step) })
    const turn = Math.atan2(sy, sx)
    members.forEach((m, i) => { const th = turn + i * step; m.n.x = m.n.fx = Math.round(Math.cos(th) * rr); m.n.y = m.n.fy = Math.round(Math.sin(th) * rr); angle.set(m.n.id, th) })
  }
  const RP = R0 + Math.max(row - 1, 0) * ROW + 24

  // each thing points at the mean angle of its people (ties between things do not count: they would drag everything to the bets)
  const pull = new Map<string, [number, number]>()
  for (const e of edges) for (const [a, b] of [[e.source, e.target], [e.target, e.source]]) {
    const th = angle.get(a)
    if (th === undefined || PEOPLE.has(byId.get(b)?.type as T)) continue
    const s = pull.get(b) ?? [0, 0]; s[0] += Math.cos(th); s[1] += Math.sin(th); pull.set(b, s)
  }
  type O = { id: string; r: number; mid: number; tx: number; ty: number; x: number; y: number; fx?: number; fy?: number }
  const os: O[] = [], rings: Ring[] = []
  let r = RP + 60
  for (const ring of RINGS) {
    const members = nodes.filter((n) => ring.types.includes(kindOf(n)))
    if (!members.length) continue
    const area = members.reduce((s, n) => s + (2 * radius(n, deg.get(n.id) ?? 0) + 4) ** 2, 0)
    const thick = Math.max(30, area / (2 * Math.PI * (r + 20) * 0.4))
    const mid = r + thick / 2
    const theta = (n: FNode) => { const s = pull.get(n.id); return s && (s[0] || s[1]) ? Math.atan2(s[1], s[0]) : rand() * Math.PI * 2 }
    // bets round the ring at the angle of their people, then the areas after them
    const bets = [...members.filter((n) => n.type === 'initiative').map((n) => ({ n, th: theta(n) })).sort((a, b) => a.th - b.th),
      ...members.filter((n) => n.type === 'area').map((n) => ({ n, th: 0 }))]
    const step = (Math.PI * 2) / Math.max(bets.length, 1), first = bets.length ? Math.round((bets[0].th + Math.PI / 2 - step / 2) / step) : 0
    bets.forEach(({ n }, i) => { const th = -Math.PI / 2 + step / 2 + (first + i) * step, x = Math.cos(th) * mid, y = Math.sin(th) * mid
      os.push({ id: n.id, r: radius(n, 0), mid, tx: x, ty: y, x, y, fx: x, fy: y }) })
    const clear = 90 / r   // the top of each ring stays clear for its name
    for (const n of members) {
      if (EVEN.has(n.type)) continue
      let th = theta(n)
      const off = Math.atan2(Math.sin(th + Math.PI / 2), Math.cos(th + Math.PI / 2))
      if (Math.abs(off) < clear) th = -Math.PI / 2 + (off < 0 ? -clear : clear)
      const j = mid + (rand() - 0.5) * thick * 0.6
      os.push({ id: n.id, r: radius(n, deg.get(n.id) ?? 0) * (n.type === 'org' || n.type === 'topic' ? 1.2 : 1), mid, tx: Math.cos(th) * mid, ty: Math.sin(th) * mid, x: Math.cos(th) * j, y: Math.sin(th) * j })
    }
    rings.push({ label: ring.label, types: ring.types, r0: r, r1: r + thick })
    r += thick + 44
  }
  forceSimulation(os).randomSource(rand)
    .force('x', forceX<O>((d) => d.tx).strength(0.03)).force('y', forceY<O>((d) => d.ty).strength(0.03))
    .force('radial', forceRadial<O>((d) => d.mid).strength(0.6))
    .force('collide', forceCollide<O>((d) => d.r + 1.5).strength(0.9))
    .stop().tick(Math.min(500, Math.max(240, os.length)))
  for (const o of os) { const n = byId.get(o.id)!; n.x = n.fx = Math.round(o.x); n.y = n.fy = Math.round(o.y) }
  return { rings, rp: RP }
}

// long bet names on two lines, so the ring of bets keeps its labels apart
function wrapLabel(s: string, max = 18): string[] {
  if (s.length <= max) return [s]
  const lines: string[] = ['']
  for (const w of s.split(' ')) {
    const cur = lines[lines.length - 1]
    if (cur && (cur + ' ' + w).length > max && lines.length < 2) lines.push(w)
    else lines[lines.length - 1] = cur ? cur + ' ' + w : w
  }
  return lines.map((l) => (l.length > max + 6 ? l.slice(0, max + 5) + '…' : l))
}

// the outline of each kind: people, bets, areas, meetings and documents are discs; a topic is a diamond; a task a square;
// a company a tile that holds its logo
function trace(ctx: CanvasRenderingContext2D, n: FNode, r: number) {
  const x = n.x!, y = n.y!
  ctx.beginPath()
  if (n.type === 'topic') { const d = r * 1.2; ctx.moveTo(x, y - d); ctx.lineTo(x + d, y); ctx.lineTo(x, y + d); ctx.lineTo(x - d, y); ctx.closePath() }
  else if (n.type === 'task') { const s = r * 0.85; ctx.roundRect(x - s, y - s, 2 * s, 2 * s, r * 0.25) }
  else if (n.type === 'org') { const s = r * 0.95; ctx.roundRect(x - s, y - s, 2 * s, 2 * s, r * 0.3) }
  else ctx.arc(x, y, r, 0, 2 * Math.PI)
}
const ok = (img?: HTMLImageElement) => !!img && img.complete && img.naturalWidth > 0
// a logo kept whole inside a box of side s, centred on x, y
function contain(ctx: CanvasRenderingContext2D, img: HTMLImageElement, x: number, y: number, s: number) {
  const k = s / Math.max(img.naturalWidth, img.naturalHeight)
  ctx.drawImage(img, x - (img.naturalWidth * k) / 2, y - (img.naturalHeight * k) / 2, img.naturalWidth * k, img.naturalHeight * k)
}
const initials = (s: string) => s.replace(/\b(the|of|and)\b/gi, '').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
const usd = (v?: number) => !v ? '' : v >= 1e6 ? `$${(v / 1e6).toFixed(1).replace(/\.0$/, '')}M` : `$${Math.round(v / 1e3)}k`

export function Graph({ focus }: { focus?: string } = {}) {
  const q = useQuery({ queryKey: ['graph'], queryFn: api.graph })
  if (q.isError) return <Empty>Could not load the graph.</Empty>
  if (!q.data) return <Loading />
  return <GraphCanvas data={q.data} focus={focus} />
}

function GraphCanvas({ data, focus }: { data: { nodes: GNode[]; edges: GEdge[]; unlinked?: Partial<Record<GNode['type'], number>> }; focus?: string }) {
  const c = useThemeColors()
  const wrap = useRef<HTMLDivElement>(null)
  const fg = useRef<ForceGraphMethods<FNode, FLink> | undefined>(undefined)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [hidden, setHidden] = useState<Set<T>>(new Set(['suggested']))   // suggestions are not on Sam's list until he says yes
  const [sel, setSel] = useState<string | null>(null)
  const [find, setFind] = useState('')
  const [sizeBy, setSizeBy] = useState<Size>('activity')
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const el = wrap.current; if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el); return () => ro.disconnect()
  }, [])

  // positions are computed once for the full graph; filters only hide, so nothing jumps
  const { all, rings, rp } = useMemo(() => { const ns: FNode[] = data.nodes.map((n) => ({ ...n })); return { all: ns, ...layout(ns, data.edges) } }, [data])
  const byId = useMemo(() => new Map(all.map((n) => [n.id, n])), [all])
  const closest = useMemo(() => new Set(all.filter((n) => PEOPLE.has(n.type) && !n.me).sort((a, b) => (b.contact ?? 0) - (a.contact ?? 0)).slice(0, CLOSEST).map((n) => n.id)), [all])
  // a document id from the library (m-12, p-7, i-3) → its graph node
  useEffect(() => {
    if (!focus) return
    setSel(byId.has(focus) ? focus : all.find((n) => n.href.endsWith('/' + focus))?.id ?? null)
  }, [focus, byId, all])
  const graphData = useMemo(() => {
    const nodes = all.filter((n) => !hidden.has(kindOf(n)))
    const ids = new Set(nodes.map((n) => n.id))
    const isP = (id: string) => PEOPLE.has(byId.get(id)!.type), isMe = (id: string) => !!byId.get(id)!.me
    const kind = (e: GEdge): Kind => isMe(e.source) || isMe(e.target) ? 'me' : isP(e.source) && isP(e.target) ? 'pp' : isP(e.source) || isP(e.target) ? 'pt' : 'tt'
    return { nodes, links: data.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ ...e, w: e.w ?? 1, kind: kind(e) })) as FLink[] }
  }, [all, byId, data.edges, hidden])
  const maxW = useMemo(() => Math.max(1, ...graphData.links.filter((l) => l.kind === 'pp').map((l) => l.w)), [graphData])

  const adj = useMemo(() => {
    const a = new Map<string, { id: string; rel: string; out: boolean }[]>()
    for (const n of graphData.nodes) a.set(n.id, [])
    for (const e of graphData.links) { a.get(e.source)?.push({ id: e.target, rel: e.rel, out: true }); a.get(e.target)?.push({ id: e.source, rel: e.rel, out: false }) }
    return a
  }, [graphData])
  const rad = useCallback((n: FNode) => radius(n, adj.get(n.id)?.length ?? 0, sizeBy === 'uniform'), [adj, sizeBy])
  const focusSet = useMemo(() => sel ? new Set([sel, ...(adj.get(sel) ?? []).map((x) => x.id)]) : null, [sel, adj])

  // the home view: the people disc and the first rings, so names are readable; Fit shows everything
  const home = useCallback((ms = 0) => {
    const f = fg.current; if (!f || !size.w) return
    const reach = rp + 110
    f.zoom(Math.max(0.2, Math.min(size.w, size.h) / (2 * reach)), ms); f.centerAt(0, 0, ms)
  }, [rp, size.w, size.h])

  useEffect(() => { const f = fg.current; if (f) { f.d3Force('link', null); f.d3Force('charge', null); f.d3Force('center', null) } }, [graphData])
  useEffect(() => { // first view, then reveal
    if (!size.w) return
    const t = setTimeout(() => { home(0); setReady(true) }, 120)
    return () => clearTimeout(t)
  }, [size.w > 0]) // eslint-disable-line react-hooks/exhaustive-deps

  // frame the selection and its neighbours, leaving room for the panel on the right
  useEffect(() => {
    const f = fg.current; if (!f || !ready) return
    if (!sel || !focusSet) { home(500); return }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const id of focusSet) { const n = byId.get(id); if (!n) continue; x0 = Math.min(x0, n.x!); x1 = Math.max(x1, n.x!); y0 = Math.min(y0, n.y!); y1 = Math.max(y1, n.y!) }
    const panel = size.w > 900 ? 340 : 0
    const z = Math.max(0.3, Math.min(2.4, (size.w - panel - 160) / Math.max(x1 - x0, 1), (size.h - 160) / Math.max(y1 - y0, 1)))
    f.zoom(z, 500); f.centerAt((x0 + x1) / 2 + panel / 2 / z, (y0 + y1) / 2, 500)
  }, [sel, ready]) // eslint-disable-line react-hooks/exhaustive-deps

  const matches = useMemo(() => {
    if (find.trim().length < 2) return []
    const re = new RegExp(find.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i')
    // people first: they are what you are most likely looking for
    return graphData.nodes.filter((n) => re.test(n.label)).sort((a, b) => Number(PEOPLE.has(b.type)) - Number(PEOPLE.has(a.type))).slice(0, 8)
  }, [find, graphData.nodes])

  const counts = useMemo(() => { const m = new Map<T, number>(); for (const n of all) m.set(kindOf(n), (m.get(kindOf(n)) ?? 0) + 1); return m }, [all])
  const toggle = (t: T) => { const h = new Set(hidden); if (h.has(t)) h.delete(t); else h.add(t); setHidden(h); if (sel && byId.get(sel) && kindOf(byId.get(sel)!) === t) setSel(null) }
  const selNode = sel ? byId.get(sel) : null
  const gaps = TYPES.filter((t) => data.unlinked?.[t.key as GNode['type']]).map((t) => { const k = data.unlinked![t.key as GNode['type']]!; return `${k} ${(k === 1 ? t.label : t.plural).toLowerCase()}` })

  // photos and logos, one image per address; repaint once a batch has loaded
  const images = useMemo(() => {
    const m = new Map<string, HTMLImageElement>()
    let t: ReturnType<typeof setTimeout> | undefined
    for (const n of all) for (const src of [n.avatar, n.logo, n.org_logo]) if (src && !m.has(src)) {
      const img = new Image()
      img.onload = () => { clearTimeout(t); t = setTimeout(() => { const f = fg.current; if (f) f.zoom(f.zoom()) }, 60) }
      img.src = src; m.set(src, img)
    }
    return m
  }, [all])

  const touchesSel = (l: FLink) => !!sel && (idOf(l.source) === sel || idOf(l.target) === sel)
  const shortName = (s: string) => { const w = s.split(' '); return w.length > 1 ? `${w[0]} ${w[w.length - 1][0]}.` : s }
  // how many top-of-mind topics each bet has, whatever is filtered: those bets carry a ring in the topics' colour
  const minded = useMemo(() => { const m = new Map<string, number>(); for (const e of data.edges) if (e.rel === 'about' && e.source.startsWith('topic-')) m.set(e.target, (m.get(e.target) ?? 0) + 1); return m }, [data.edges])
  const topicsOf = (id: string) => minded.get(id) ?? 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <FilterBar
        tokens={TYPES.filter((t) => hidden.has(t.key)).map((t) => ({ label: `Hide ${t.plural.toLowerCase()}`, onRemove: () => toggle(t.key) }))}
        onClear={() => setHidden(new Set())}
        right={
          <div className="relative w-full md:w-56">
            <input placeholder="Find a person or thing…" aria-label="Find a node" value={find} onChange={(e) => setFind(e.target.value)}
              className={cn(inputClass, 'w-full')} />
            {matches.length > 0 && (
              <div className={cn(popoverClass, 'absolute right-0 top-full z-20 mt-1 w-full py-1')}>
                {matches.map((n) => <button key={n.id} onClick={() => { setSel(n.id); setFind('') }} className="flex w-full items-center gap-2 truncate px-3 py-1.5 text-left text-[13px] text-ink hover:bg-panel2"><Glyph t={kindOf(n)} color={c.type[kindOf(n)]} /><span className="truncate">{n.label}</span></button>)}
              </div>
            )}
          </div>}>
        {/* people are the centre of the picture and always shown; everything else can be hidden */}
        <FilterRow label="Around them">
          {TYPES.filter((t) => t.key !== 'person' && counts.get(t.key)).map((t) => (
            <Opt key={t.key} on={!hidden.has(t.key)} onClick={() => toggle(t.key)} count={counts.get(t.key)}>
              <span className="mr-1.5 inline-flex align-middle"><Glyph t={t.key} color={c.type[t.key]} /></span>{t.plural}
            </Opt>
          ))}
        </FilterRow>
      </FilterBar>

      <div ref={wrap} className="relative min-h-[360px] flex-1 overflow-hidden border border-line bg-panel">
        <div style={{ visibility: ready ? 'visible' : 'hidden' }}>
          {size.w > 0 && (
            <ForceGraph2D<FNode, FLink>
              ref={fg}
              width={size.w} height={size.h}
              graphData={graphData}
              backgroundColor={c.bg}
              cooldownTicks={0} warmupTicks={0} enableNodeDrag={false}
              nodeRelSize={1}
              nodeVal={(n) => rad(n) ** 2}
              nodeLabel={(n) => `<b>${esc(n.label)}</b><span>${n.me ? 'You' : TYPE_LABEL[kindOf(n)]}${n.sub && !n.me ? ' · ' + esc(n.sub) : ''}`
                + (PEOPLE.has(n.type) && !n.me ? ` · in touch on ${n.contact ?? 0} of the last 90 days${n.tasks ? ` · ${n.tasks} task${n.tasks === 1 ? '' : 's'}` : ''}`
                  : n.type === 'initiative' ? ` · weight ${n.weight ?? '–'}${topicsOf(n.id) ? ` · ${topicsOf(n.id)} on your mind` : ''}`
                  : ` · ${adj.get(n.id)?.length ?? 0} links`) + '</span>'}
              onNodeClick={(n) => setSel(String(n.id))}
              onBackgroundClick={() => setSel(null)}
              linkVisibility={(l) => (l.kind !== 'tt' && l.kind !== 'me') || touchesSel(l)}
              linkCurvature={(l) => (l.kind === 'pp' ? 0.2 : 0)}
              linkColor={(l) => {
                if (focusSet) return touchesSel(l) ? c.ink : hexA(c.ink3, 0.04)
                return hexA(c.ink3, l.kind === 'pp' ? 0.12 + 0.3 * Math.sqrt(l.w / maxW) : 0.07)
              }}
              linkWidth={(l) => (focusSet ? (touchesSel(l) ? 1.4 : 0.5) : l.kind === 'pp' ? 0.5 + 1.5 * Math.sqrt(l.w / maxW) : 0.5)}
              nodeCanvasObject={(node: NodeObject<FNode>, ctx, k) => {
                const n = node as FNode; const r = rad(n); const isSel = n.id === sel; const person = PEOPLE.has(n.type); const kind = kindOf(n)
                const logo = n.logo ? images.get(n.logo) : undefined, hasLogo = ok(logo)
                ctx.globalAlpha = focusSet && !focusSet.has(n.id) ? 0.12 : 1
                trace(ctx, n, r)
                if (n.type === 'org') { // a white tile, as most logos are drawn for white; initials when there is no logo
                  ctx.fillStyle = hasLogo ? '#ffffff' : c.type.org; ctx.fill()
                  if (hasLogo) { ctx.save(); trace(ctx, n, r); ctx.clip(); contain(ctx, logo!, n.x!, n.y!, r * 1.45); ctx.restore() }
                  else { ctx.fillStyle = c.bg; ctx.font = `600 ${r * 0.8}px Inter, -apple-system, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(initials(n.label), n.x!, n.y! + r * 0.05) }
                  trace(ctx, n, r)
                } else if (kind === 'suggested' || n.type === 'area') { // not yet on the list, or a grouping: outlined only
                  ctx.fillStyle = c.bg; ctx.fill()
                } else {
                  ctx.fillStyle = c.type[kind]; ctx.fill()
                  const img = n.avatar ? images.get(n.avatar) : undefined
                  if (ok(img)) { // centre-cropped photo inside the dot
                    const s = Math.min(img!.naturalWidth, img!.naturalHeight)
                    ctx.save(); trace(ctx, n, r); ctx.clip()
                    ctx.drawImage(img!, (img!.naturalWidth - s) / 2, (img!.naturalHeight - s) / 2, s, s, n.x! - r, n.y! - r, 2 * r, 2 * r)
                    ctx.restore(); trace(ctx, n, r)
                  }
                }
                const strong = n.type === 'initiative' || n.me || isSel
                if (kind === 'suggested' || n.type === 'area') {
                  ctx.setLineDash([2.5 / Math.min(k, 2), 2 / Math.min(k, 2)]); ctx.lineWidth = 1.4 / Math.min(k, 2)
                  ctx.strokeStyle = kind === 'suggested' ? c.type.task : c.ink2; ctx.stroke(); ctx.setLineDash([])
                } else {
                  ctx.lineWidth = (strong ? 1.6 : 1) / Math.min(k, 2); ctx.strokeStyle = strong ? c.ink : n.type === 'org' ? c.line : c.bg; ctx.stroke()
                }
                if (EVEN.has(n.type) && topicsOf(n.id) && !isSel) { // discussed lately
                  ctx.beginPath(); ctx.arc(n.x!, n.y!, r + 3.5 / k, 0, 2 * Math.PI); ctx.strokeStyle = c.type.topic; ctx.lineWidth = Math.min(1.2 + topicsOf(n.id) * 0.6, 3) / k; ctx.stroke()
                }
                if (isSel || n.me) { ctx.beginPath(); ctx.arc(n.x!, n.y!, r * (n.type === 'topic' ? 1.2 : 1) + 4 / k, 0, 2 * Math.PI); ctx.strokeStyle = c.accent; ctx.lineWidth = 3 / k; ctx.stroke() }
                // an outside person carries their company's logo
                const badge = n.org_logo ? images.get(n.org_logo) : undefined
                if (person && ok(badge) && k > 0.45) {
                  const br = Math.max(r * 0.42, 3.5), bx = n.x! + r * 0.72, by = n.y! + r * 0.72
                  ctx.beginPath(); ctx.arc(bx, by, br, 0, 2 * Math.PI); ctx.fillStyle = '#ffffff'; ctx.fill()
                  ctx.save(); ctx.clip(); contain(ctx, badge!, bx, by, br * 1.5); ctx.restore()
                  ctx.beginPath(); ctx.arc(bx, by, br, 0, 2 * Math.PI); ctx.lineWidth = 1 / Math.min(k, 2); ctx.strokeStyle = c.line; ctx.stroke()
                }
                // always: you, the bets and areas, your closest people, companies without a logo (a logo names its company); all
                // people and the topics once zoomed in a little, companies with a logo further in; the rest on focus or close up
                const label = n.me || EVEN.has(n.type) || isSel || (person && (k > 0.6 || closest.has(n.id)))
                  || (n.type === 'org' && (k > 1.7 || !hasLogo)) || (n.type === 'topic' && k > 0.75)
                  || (focusSet?.has(n.id) && k > 1.1) || k > 2.2
                if (label) {
                  const fs = (n.me ? 13 : n.type === 'initiative' ? 12.5 : person || n.type === 'area' ? 11.5 : 11) / k
                  ctx.font = `${strong || person ? 600 : 500} ${fs}px Inter, -apple-system, sans-serif`
                  ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.lineJoin = 'round'
                  const most = n.type === 'topic' && k < 1.6 && !isSel ? 26 : 34   // topics sit close together: shorter until zoomed in
                  const lines = n.me ? ['You'] : person ? [k > 1.3 || isSel ? n.label : shortName(n.label)] : EVEN.has(n.type) ? wrapLabel(n.label)
                    : [n.label.length > most ? n.label.slice(0, most - 1).trimEnd() + '…' : n.label]
                  const below = n.type === 'topic' ? r * 1.2 : r
                  lines.forEach((t, i) => { const y = n.y! + below + 3 / k + i * fs * 1.15
                    ctx.lineWidth = 3.5 / k; ctx.strokeStyle = c.bg; ctx.strokeText(t, n.x!, y)
                    ctx.fillStyle = n.type === 'area' ? c.ink2 : c.ink; ctx.fillText(t, n.x!, y) })
                }
                ctx.globalAlpha = 1
              }}
              nodePointerAreaPaint={(node, color, ctx, k) => { const n = node as FNode; ctx.fillStyle = color; ctx.beginPath(); ctx.arc(n.x!, n.y!, Math.max(rad(n) * (n.type === 'topic' ? 1.2 : 1) + 2, 7 / k), 0, 2 * Math.PI); ctx.fill() }}
              onRenderFramePre={(ctx, k) => { // a faint guide circle inside each ring
                ctx.save(); ctx.setLineDash([4 / k, 5 / k]); ctx.lineWidth = 1 / k; ctx.strokeStyle = c.line; ctx.globalAlpha = focusSet ? 0.4 : 1
                for (const g of rings) if (g.types.some((t) => !hidden.has(t))) { ctx.beginPath(); ctx.arc(0, 0, g.r0 - 22, 0, 2 * Math.PI); ctx.stroke() }
                ctx.restore()
              }}
              onRenderFramePost={(ctx, k) => { // each ring's name on its guide circle, at the top
                ctx.font = `600 ${12.5 / k}px Inter, -apple-system, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
                ctx.globalAlpha = focusSet ? 0.35 : 1
                for (const g of rings) {
                  if (!g.types.some((t) => !hidden.has(t))) continue
                  const w = ctx.measureText(g.label).width + 12 / k, h = 19 / k, y = -(g.r0 - 22)
                  ctx.fillStyle = c.bg; ctx.fillRect(-w / 2, y - h / 2, w, h); ctx.strokeStyle = c.line; ctx.lineWidth = 1 / k; ctx.strokeRect(-w / 2, y - h / 2, w, h)
                  ctx.fillStyle = c.ink2; ctx.fillText(g.label, 0, y)
                }
                ctx.globalAlpha = 1
              }}
            />
          )}
        </div>
        {!ready && <div className="absolute inset-0 grid place-items-center text-[13px] text-ink2">Laying out {data.nodes.length} nodes…</div>}
        {ready && !selNode && <div className="pointer-events-none absolute left-3 top-3 max-w-[340px] bg-panel/85 px-1.5 py-1 text-[12.5px] leading-snug text-ink2">You are in the middle. The closer someone sits, the more days you were in touch over the last 90. Everything else sits behind the people on it.</div>}

        <div className="absolute bottom-3 left-3 right-16 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] [&>span]:bg-panel/85 [&>span]:px-1">
          <select value={sizeBy} onChange={(e) => setSizeBy(e.target.value as Size)} className={selectClass} aria-label="Size nodes by">
            <option value="activity">Size: contact and links</option><option value="uniform">Size: uniform</option>
          </select>
          <span className="text-ink2">{graphData.nodes.length} nodes · {graphData.links.length} links</span>
          {gaps.length > 0 && <span className="text-ink2" title="Every task, company, meeting and document should be reachable through a person. These have no one but you linked yet, so they are not in the picture.">Not linked to anyone yet: {gaps.join(' · ')}</span>}
        </div>
        <div className="absolute bottom-3 right-3 flex flex-col overflow-hidden rounded-full border border-line bg-panel shadow-sm">
          {[{ l: 'Back to the people', f: () => { setSel(null); home(400) }, i: '◎' }, { l: 'Fit everything', f: () => fg.current?.zoomToFit(400, 40), i: '⤢' },
            { l: 'Zoom in', f: () => fg.current?.zoom(fg.current.zoom() * 1.3, 180), i: '+' }, { l: 'Zoom out', f: () => fg.current?.zoom(fg.current.zoom() / 1.3, 180), i: '−' }].map((b) => (
            <button key={b.l} title={b.l} aria-label={b.l} onClick={b.f} className="grid size-8 place-items-center border-b border-line2 text-[15px] text-ink last:border-0 hover:bg-panel2">{b.i}</button>
          ))}
        </div>

        {selNode && <Panel n={selNode} adj={adj.get(selNode.id) ?? []} byId={byId} all={all} colors={c.type} minded={topicsOf(selNode.id)} onPick={setSel} onClose={() => setSel(null)} />}
      </div>
    </div>
  )
}

// the legend mark of each kind, matching its shape on the canvas
function Glyph({ t, color }: { t: T; color: string }) {
  const shape = t === 'topic' ? 'rotate-45 scale-90' : t === 'task' || t === 'suggested' ? 'rounded-[2px]' : t === 'org' ? 'rounded-[2px] border border-line bg-white' : 'rounded-full'
  const outlined = t === 'suggested' || t === 'area'
  return <span aria-hidden className={cn('inline-block size-2.5 shrink-0', shape, outlined ? 'border border-dashed' : t !== 'org' && 'ring-1 ring-ink/20')}
    style={outlined ? { borderColor: t === 'area' ? 'var(--ink2)' : color } : t === 'org' ? undefined : { background: color }} />
}

function Mark({ m, colors, size }: { m: FNode; colors: Record<T, string>; size: number }) {
  const [broken, setBroken] = useState(false)
  if (m.avatar && !broken) return <img src={m.avatar} alt="" onError={() => setBroken(true)} style={{ width: size, height: size }} className="shrink-0 rounded-full object-cover" />
  if (m.logo && !broken) return <span style={{ width: size, height: size }} className="grid shrink-0 place-items-center rounded-[3px] border border-line bg-white">
    <img src={m.logo} alt="" onError={() => setBroken(true)} style={{ width: size * 0.78, height: size * 0.78 }} className="object-contain" /></span>
  return <span style={{ width: size, height: size }} className="grid shrink-0 place-items-center"><Glyph t={kindOf(m)} color={colors[kindOf(m)]} /></span>
}

const OPEN_LABEL: Partial<Record<T, string>> = { initiative: 'Open bet', area: 'Open tasks', task: 'Open task', suggested: 'Open suggestion', meeting: 'Open meeting', document: 'Open document', org: 'Open company page' }

function Panel({ n, adj, byId, all, colors, minded, onPick, onClose }: { n: FNode; adj: { id: string; rel: string; out: boolean }[]; byId: Map<string, FNode>; all: FNode[]; colors: Record<T, string>; minded: number; onPick: (id: string) => void; onClose: () => void }) {
  const person = PEOPLE.has(n.type), kind = kindOf(n)
  const groups = TYPES.map((t) => ({ t, items: adj.filter((a) => { const m = byId.get(a.id); return m && kindOf(m) === t.key }) })).filter((g) => g.items.length)
  // for Sam: the people he is most in touch with, nearest first (his ties are not drawn as edges)
  const nearest = n.me ? all.filter((m) => PEOPLE.has(m.type) && !m.me && m.contact).sort((a, b) => (b.contact ?? 0) - (a.contact ?? 0)).slice(0, 25) : []
  const open = n.me ? 'Open your page' : person ? 'Open person page' : n.type === 'topic' ? (n.href.startsWith('/initiatives/') ? 'Open its bet' : 'Open Initiatives')
    : OPEN_LABEL[kind] ?? `Open ${TYPE_LABEL[kind].toLowerCase()}`
  return (
    <aside className={cn(popoverClass, 'absolute inset-y-3 right-3 flex w-[min(320px,calc(100%-24px))] flex-col')}>
      <div className="border-b border-line p-4">
        <div className="mb-1 flex items-center gap-2 text-[12.5px] text-ink2"><Glyph t={kind} color={colors[kind]} />{n.me ? 'You' : TYPE_LABEL[kind]}
          {n.private && <span className="inline-flex items-center gap-1"><Lock size={11} aria-hidden />people/HR, private</span>}
          <button onClick={onClose} aria-label="Close" className={btnClass('ghost', 'icon', 'ml-auto -my-1 text-[16px] leading-none')}>×</button></div>
        <div className="flex items-center gap-3">{(n.avatar || n.logo) && <Mark m={n} colors={colors} size={44} />}<div className="text-[16px] font-semibold leading-snug">{n.label}</div></div>
        {n.sub && !n.me && <div className="mt-0.5 text-[13px] text-ink2">{n.sub}{n.type === 'org' && n.open_usd ? ` · ${usd(n.open_usd)} open` : ''}{n.type === 'initiative' && minded ? ` · ${minded} on your mind` : ''}</div>}
        {person && !n.me && <div className="mt-1 text-[13px]">In touch on {n.contact ?? 0} of the last 90 days{n.tasks ? ` · ${n.tasks} task${n.tasks === 1 ? '' : 's'}` : ''}</div>}
        {n.detail && <p className="mt-2 text-[13px] leading-snug">{n.detail}</p>}
        {n.ask && <p className="mt-1.5 text-[13px] leading-snug"><b>On you:</b> {n.ask}</p>}
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
          {n.href && <a href={'#' + n.href}>{open} →</a>}
          {person && !n.me && <a href={`#/explore/library/${n.id}`}>Profile in library →</a>}
        </div>
      </div>
      <div className="flex-1 overflow-auto p-4 pt-2">
        {nearest.length > 0 && (
          <div className="mt-2.5">
            <div className="mb-1 text-[12.5px] font-semibold">Most in touch, last 90 days</div>
            {nearest.map((m) => <Row key={m.id} m={m} colors={colors} note={`${m.contact} days${m.tasks ? ` · ${m.tasks} task${m.tasks === 1 ? '' : 's'}` : ''}${m.sub ? ' · ' + m.sub : ''}`} onPick={onPick} />)}
          </div>
        )}
        {groups.length === 0 && !nearest.length && <div className="text-[13px] text-ink2">No connections in the current filter.</div>}
        {groups.map(({ t, items }) => (
          <div key={t.key} className="mt-2.5">
            <div className="mb-1 text-[12.5px] font-semibold">{t.plural} · {items.length}</div>
            {items.slice(0, 40).map((a) => { const m = byId.get(a.id)!; const rel = a.out ? a.rel : inverse(a.rel)
              return <Row key={a.id + a.rel} m={m} colors={colors} note={[rel === 'with' ? '' : rel, m.sub].filter(Boolean).join(' · ')} onPick={onPick} /> })}
            {items.length > 40 && <div className="px-2 py-1 text-[12px] text-ink2">+ {items.length - 40} more</div>}
          </div>
        ))}
      </div>
    </aside>
  )
}

function Row({ m, colors, note, onPick }: { m: FNode; colors: Record<T, string>; note: string; onPick: (id: string) => void }) {
  return (
    <button onClick={() => onPick(m.id)} className={cn('flex w-full items-start gap-2 border-l-2 border-transparent px-2 py-1 text-left text-[13px] hover:border-accent hover:bg-panel2')}>
      <span className="mt-0.5"><Mark m={m} colors={colors} size={20} /></span>
      <span className="min-w-0 flex-1"><span className="line-clamp-2">{m.label}</span>{note && <span className="block text-[11.5px] text-ink2">{note}</span>}</span>
    </button>
  )
}

// edges read "source rel target"; seen from the target they read the other way
const INVERSE: Record<string, string> = { 'reports to': 'manages', 'works at': 'employs', drives: 'driven by', 'works on': 'worked on by', attended: 'attended by',
  'named in': 'names', owns: 'owned by', shared: 'shared by', about: '', 'deals with': 'dealt with by', raised: 'raised by', discussed: 'discussed by',
  owes: 'waiting on', 'came up in': 'brought up', involves: 'named in', involved: 'involves' }
const inverse = (r: string) => INVERSE[r] ?? r
const idOf = (e: unknown) => (e && typeof e === 'object' && 'id' in e ? String((e as { id: unknown }).id) : String(e))
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
function hexA(hex: string, a: number) {
  const m = hex.replace('#', ''); if (m.length !== 6) return hex
  return `rgba(${parseInt(m.slice(0, 2), 16)},${parseInt(m.slice(2, 4), 16)},${parseInt(m.slice(4, 6), 16)},${a})`
}
