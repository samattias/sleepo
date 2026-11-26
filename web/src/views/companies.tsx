// People › Companies (Sam, 23 Oct 2026): the companies Sam deals with, next to the people, behind one switch. Acme itself
// (it replaced the Company page), partners, customers, prospects, investors and the rest folded under Other, each with a page:
// who it is to Acme (Sam can change it), its people, its Salesforce deals (company and deal data only), its latest activity
// and the initiatives it touches. One company recorded twice is merged here ("Same company as…"). assist/companies.py.
// Each shows its real logo (assist/logos.py, fetched by web domain and cached), else its initials.
import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Check, ChevronDown, ChevronRight, ExternalLink, Pencil, Search as SearchIcon, X } from 'lucide-react'
import { api, type CompanyDeal, type CompanyPage as Page, type CompanyRelation, type CompanyRow } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { ago, day } from '@/lib/time'
import { Avatar, Empty, inputClass, Loading, Markdown, PageTabs } from '@/components/ui'
import { org } from '@/lib/profile'
import { AssistPill } from '@/components/AssistPill'
import { companyPill } from '@/lib/assistPills'

const SECTIONS: CompanyRelation[] = ['ours', 'partner', 'customer', 'prospect', 'investor', 'vendor', 'other']
const LABEL: Record<CompanyRelation, string> = { ours: 'Our company', partner: 'Partners', customer: 'Customers', prospect: 'Prospects', investor: 'Investors & board', vendor: 'Vendors', other: 'Other', hidden: 'Hidden' }
const ONE: Record<CompanyRelation, string> = { ours: 'Our company', partner: 'Partner', customer: 'Customer', prospect: 'Prospect', investor: 'Investor', vendor: 'Vendor', other: 'Other', hidden: 'Hidden' }
const FOLDED: CompanyRelation[] = ['other', 'vendor']   // shown on request
const money = (n: number): string => (n < 0 ? `−${money(-n)}` : n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `$${Math.round(n / 1000)}k` : n ? `$${Math.round(n)}` : '')   // a net reduction shows as −$72k

// Relationships › People | Companies, at the top of both pages: the page tabs every page uses (UI review, 30 Oct 2026)
export function RelationshipsHeader({ on, right }: { on: 'people' | 'companies'; right?: ReactNode }) {
  return <PageTabs title="Relationships" label="Relationships" active={on} right={right}
    tabs={[{ key: 'people', label: 'People', to: '/people' }, { key: 'companies', label: 'Companies', to: '/companies' }]} />
}

// /company (the old Company page) opens Acme's company page
export function OursRedirect() {
  const q = useQuery({ queryKey: ['companies'], queryFn: api.companies })
  const nav = useNavigate()
  const ours = q.data?.companies.find((c) => c.relation === 'ours')
  useEffect(() => { if (ours) nav({ to: '/companies/$id', params: { id: String(ours.id) }, replace: true }) }, [ours]) // eslint-disable-line react-hooks/exhaustive-deps
  return q.isError ? <Empty>Could not load the companies.</Empty> : <Loading />
}

// a company's mark: its logo (Acme's from the app, the others from assist/logos.py on a white tile, as most are drawn for
// white), otherwise its initials on a soft square. A small site icon stays at its own size so it does not blur.
function Mark({ name, ours, id, logo: v, px, size = 32 }: { name: string; ours?: boolean; id?: number; logo?: string | null; px?: number | null; size?: number }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, enabled: !!ours })
  const [broken, setBroken] = useState(false)
  const logo = ours ? meta.data?.logos?.acme : undefined
  const ini = name.replace(/\(.*?\)/g, '').split(/[\s.-]+/).filter((w) => /^[A-Za-z0-9]/.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
  const inner = size - 6, own = px && px < inner ? Math.max(16, px) : inner
  if (!logo && v && id && !broken) return (
    <span style={{ width: size, height: size }} className="inline-flex shrink-0 items-center justify-center overflow-hidden rounded-[7px] border border-line bg-white">
      <img src={`/api/companies/${id}/logo?v=${v}`} alt="" loading="lazy" onError={() => setBroken(true)} style={{ width: own, height: own }} className="object-contain" />
    </span>)
  return logo ? <img src={logo} alt="" style={{ width: size, height: size }} className="shrink-0 object-contain" />
    : <span style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }} className="inline-flex shrink-0 items-center justify-center rounded-[7px] border border-line bg-panel2 font-semibold text-ink2">{ini || '?'}</span>
}

// ---------------------------------------------------------------- the list
export function Companies() {
  const q = useQuery({ queryKey: ['companies'], queryFn: api.companies })
  const nav = useNavigate()
  const [f, setF] = usePersisted('assist-companies', { q: '', open: [] as string[] })
  if (!q.data) return <Loading />
  const re = f.q.trim() ? new RegExp(f.q.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
  const list = q.data.companies.filter((c) => !re || re.test([c.name, ...c.merged, c.region ?? ''].join(' ')))
  const toggle = (k: string) => setF({ ...f, open: f.open.includes(k) ? f.open.filter((x) => x !== k) : [...f.open, k] })
  return (
    <div className="max-w-[1080px]">
      <RelationshipsHeader on="companies" right={
        <label className="relative block w-full sm:w-64">
          <SearchIcon size={13} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink3" />
          <input value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="Search companies" aria-label="Search companies"
            className={cn(inputClass, 'w-full pl-7')} />
        </label>} />
      {list.length === 0 && <Empty>No company matches.</Empty>}
      {SECTIONS.map((k) => {
        const rows = list.filter((c) => c.relation === k)
        if (!rows.length) return null
        const folded = FOLDED.includes(k) && !re && !f.open.includes(k)
        const many = rows.length > 12 && !re && !f.open.includes(`all-${k}`)
        return (
          <section key={k} className="mb-5">
            <button onClick={() => toggle(FOLDED.includes(k) ? k : `all-${k}`)} className="mb-1.5 flex items-baseline gap-2 text-left">
              <h2 className="text-[15px] font-semibold">{LABEL[k]}</h2><span className="text-[12.5px] text-ink3">{rows.length}</span>
              {FOLDED.includes(k) && (folded ? <ChevronRight size={14} className="self-center text-ink3" /> : <ChevronDown size={14} className="self-center text-ink3" />)}
            </button>
            {!folded && <div className="border border-line bg-panel">
              {(many ? rows.slice(0, 12) : rows).map((c) => <Row key={c.id} c={c} onOpen={() => nav({ to: '/companies/$id', params: { id: String(c.id) } })} />)}
            </div>}
            {!folded && rows.length > 12 && !re && <button onClick={() => toggle(`all-${k}`)} className="mt-1.5 inline-flex items-center gap-1 px-1 text-[12.5px] font-medium text-ink2 hover:text-ink">
              {many ? <ChevronRight size={13} /> : <ChevronDown size={13} />}{many ? `Show all ${rows.length}` : 'Show fewer'}</button>}
          </section>)
      })}
    </div>
  )
}

function Row({ c, onOpen }: { c: CompanyRow; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="flex w-full items-center gap-3 border-b border-line2 px-3 py-2 text-left last:border-0 hover:bg-panel2">
      <Mark name={c.name} ours={c.relation === 'ours'} id={c.id} logo={c.logo} px={c.logo_px} size={28} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-medium">{c.name}{c.relation_by === 'you' && c.relation !== 'ours' && <span className="ml-1.5 text-[11px] font-normal text-ink3">set by you</span>}</span>
        {(c.merged.length > 0 || c.region) && <span className="block truncate text-[12px] text-ink3">{[c.region, c.merged.length ? `also ${c.merged.join(', ')}` : ''].filter(Boolean).join(' · ')}</span>}
      </span>
      <span className="w-[120px] shrink-0 text-right text-[12.5px] text-ink2 max-md:hidden">{c.deals_open ? `${c.deals_open} open${c.open_usd ? ` · ${money(c.open_usd)}` : ''}` : ''}</span>
      <span className="w-[70px] shrink-0 text-right text-[12.5px] text-ink3 max-sm:hidden">{c.people ? `${c.people} ${c.people === 1 ? 'person' : 'people'}` : ''}</span>
      <span className="w-[80px] shrink-0 text-right text-[12px] tabular-nums text-ink3">{c.last ? ago(c.last) : ''}</span>
    </button>
  )
}

// ---------------------------------------------------------------- one company
export function CompanyPage({ id }: { id: number }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['company', id], queryFn: () => api.company(id) })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const reload = () => { qc.invalidateQueries({ queryKey: ['company'] }); qc.invalidateQueries({ queryKey: ['companies'] }) }
  const rel = useMutation({ mutationFn: (r: string | null) => api.companyRelation(id, r), onSettled: reload })
  const moved = q.data && q.data.id !== id ? q.data.id : null   // a merged record opens the company it belongs to
  useEffect(() => { if (moved) nav({ to: '/companies/$id', params: { id: String(moved) }, replace: true }) }, [moved]) // eslint-disable-line react-hooks/exhaustive-deps
  if (q.isError) return <Empty>No such company.</Empty>
  if (!q.data || moved) return <Loading />
  const x = q.data, ours = x.relation === 'ours'
  const face = (name: string) => people.data?.find((p) => p.name === name) ?? { name, avatar: '' }
  return (
    <div className="max-w-[920px]">
      <header className="mb-5 flex items-start gap-4">
        <Mark name={x.name} ours={ours} id={x.id} logo={x.logo} px={x.logo_px} size={52} />
        <div className="min-w-0 flex-1">
          <Name x={x} onSaved={reload} />
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink2">
            {ours ? <span>Our company</span> : <RelationPicker value={x.relation} by={x.relation_by} onChange={(r) => rel.mutate(r)} busy={rel.isPending} />}
            {x.region && <span>· {x.region}</span>}
            {x.domains.length > 0 && <span>· {x.domains.slice(0, 3).join(', ')}</span>}
          </div>
        </div>
        <Link to="/companies" className="mt-1.5 shrink-0 text-[12.5px]">All companies</Link>
      </header>
      {/* the assistant pill (Sam, 16 Nov 2026): where we stand, an email, prep, with the company's chip (not on our own) */}
      {!ours && <AssistPill className="-mt-1 mb-5 max-w-[860px]" target={{ kind: 'company', ref: String(x.id) }} {...companyPill(x.name)} />}

      {ours && <Overview />}

      <section className="mb-5">
        <h2 className="mb-2 text-[15px] font-semibold">{ours ? 'Our people' : `People at ${x.name}`}{x.people_total > 0 && <span className="ml-2 text-[12.5px] font-normal text-ink3">{x.people_total}</span>}</h2>
        {x.people.length === 0 ? <p className="text-[13px] text-ink2">No one from {x.name} in SleePO yet: people show here once their email address is known.</p>
          : <People list={x.people} face={face} />}
        {ours && x.people_total > x.people.length && <Link to="/people" className="mt-1.5 inline-block text-[12.5px]">All {x.people_total} in People</Link>}
        {x.our_people.length > 0 && <>
          <h3 className="mb-1.5 mt-3 text-[13px] font-semibold text-ink2">From {org().name || "your company"}, most involved</h3>
          <People list={x.our_people} face={face} />
        </>}
      </section>

      {x.deals.length > 0 && <Deals deals={x.deals} />}
      {!(ours && !x.activity.length) && <Activity items={x.activity} />}   {/* nothing is linked to Acme itself: no empty section there */}
      {x.initiatives.length > 0 && <section className="mb-5">
        <h2 className="mb-2 text-[15px] font-semibold">Initiatives</h2>
        <div className="flex flex-wrap gap-1.5">{x.initiatives.map((i) => <Link key={i.id} to="/initiatives/$slug" params={{ slug: i.slug }}
          className="rounded-full border border-line px-2.5 py-0.5 text-[12.5px] font-normal text-ink no-underline hover:border-ink">{i.name}</Link>)}</div>
      </section>}
      {!ours && <Records x={x} onChange={reload} />}
    </div>
  )
}

// What the company is to Acme: SleePO's reading, or Sam's call (which he can hand back)
function RelationPicker({ value, by, onChange, busy }: { value: CompanyRelation; by: 'you' | 'sleepo'; onChange: (r: string | null) => void; busy: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <select value={value} disabled={busy} onChange={(e) => onChange(e.target.value)} aria-label={`What this company is to ${org().name || "your company"}`}
        className="cursor-pointer rounded-full border border-line bg-panel px-2.5 py-0.5 text-[12.5px] font-medium text-ink outline-none hover:border-ink">
        {(['partner', 'customer', 'prospect', 'investor', 'vendor', 'other', 'hidden'] as CompanyRelation[]).map((r) => <option key={r} value={r}>{ONE[r]}</option>)}
      </select>
      {by === 'you' ? <button onClick={() => onChange(null)} className="text-[12px] text-ink3 underline decoration-line underline-offset-2 hover:text-ink" title="Let SleePO work it out from Salesforce and the records">set by you · reset</button>
        : <span className="text-[12px] text-ink3" title="From Salesforce deals and the records kept by hand; choose another to set it yourself">from SleePO</span>}
    </span>
  )
}

function People({ list, face }: { list: { id: string; name: string; title: string }[]; face: (n: string) => { name: string; avatar: string } }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {list.map((p) => <Link key={p.id} to="/people/$id" params={{ id: p.id }} title={p.title || p.name}
        className="inline-flex items-center gap-1.5 rounded-full border border-line py-px pl-px pr-2.5 text-[12.5px] font-normal text-ink no-underline hover:border-ink">
        <Avatar p={face(p.name)} size={22} />{p.name}</Link>)}
    </div>
  )
}

// Salesforce deals: open first, the rest folded (company and deal data only)
function Deals({ deals }: { deals: CompanyDeal[] }) {
  const [all, setAll] = useState(false)
  const open = deals.filter((d) => d.is_open), closed = deals.filter((d) => !d.is_open)
  const shown = all ? deals : open.length ? open : closed.slice(0, 3)
  const usd = (d: CompanyDeal) => money(Number((d.currency ?? 'USD') === 'USD' ? d.acv : d.net_forecast_usd ?? d.acv) || 0)
  return (
    <section className="mb-5">
      <h2 className="mb-2 flex items-baseline gap-2 text-[15px] font-semibold">Deals<span className="text-[12.5px] font-normal text-ink3">{open.length} open · {closed.length} closed</span>
        <Link to="/pipeline" className="ml-auto text-[12.5px] font-normal">Pipeline</Link></h2>
      <div className="border border-line bg-panel">
        {shown.map((d, i) => (
          <div key={i} className="flex items-center gap-3 border-b border-line2 px-3 py-2 text-[13px] last:border-0">
            <span className="min-w-0 flex-1 truncate">{d.name}</span>
            <span className={cn('shrink-0 text-[12.5px]', d.stage === 'Closed Won' ? 'text-ink' : d.stage === 'Closed Lost' ? 'text-ink3' : 'text-ink2')}>{d.stage}</span>
            <span className="w-[90px] shrink-0 text-right text-[12px] text-ink3 max-sm:hidden">{d.sale_type}</span>
            <span className="w-[64px] shrink-0 text-right text-[12px] tabular-nums text-ink3">{d.close_date ? day(d.close_date) : ''}</span>
            <span className="w-[64px] shrink-0 text-right tabular-nums">{usd(d)}</span>
          </div>))}
      </div>
      {deals.length > shown.length && <button onClick={() => setAll(true)} className="mt-1.5 inline-flex items-center gap-1 px-1 text-[12.5px] font-medium text-ink2 hover:text-ink"><ChevronRight size={13} />Show all {deals.length}</button>}
    </section>
  )
}

// The latest of what is linked to the company, one line each; Show all for the rest
function Activity({ items }: { items: Page['activity'] }) {
  const [all, setAll] = useState(false)
  const list = all ? items : items.slice(0, 6)
  return (
    <section className="mb-5">
      <h2 className="mb-2 text-[15px] font-semibold">Recent activity</h2>
      {items.length === 0 ? <p className="text-[13px] text-ink2">Nothing linked yet.</p> : <div className="border border-line bg-panel">
        {list.map((a) => (
          <a key={a.id} href={a.url || undefined} target={a.url?.startsWith('http') ? '_blank' : undefined} rel="noopener"
            className="flex items-center gap-2.5 border-b border-line2 px-3 py-2 text-[13.5px] font-normal text-ink no-underline last:border-0 hover:bg-panel2">
            <span className="w-[64px] shrink-0 text-[11.5px] text-ink3">{a.label}</span>
            <span className="min-w-0 flex-1 truncate">{a.title || a.where || '(untitled)'}{a.from && !a.mine && <span className="text-ink3"> · {a.from}</span>}</span>
            {a.url?.startsWith('http') && <ExternalLink size={12} className="shrink-0 text-ink3" />}
            <span className="w-[52px] shrink-0 text-right text-[12px] tabular-nums text-ink3">{day(a.ts)}</span>
          </a>))}
      </div>}
      {items.length > 6 && <button onClick={() => setAll(!all)} className="mt-1.5 inline-flex items-center gap-1 px-1 text-[12.5px] font-medium text-ink2 hover:text-ink">
        {all ? <ChevronDown size={13} /> : <ChevronRight size={13} />}{all ? 'Show less' : `Show all ${items.length}`}</button>}
    </section>
  )
}

// The company's name; one SleePO made from a mail domain ("Fabrikam") can be renamed. A Salesforce account keeps
// Salesforce's name, which its deals are matched by.
function Name({ x, onSaved }: { x: Page; onSaved: () => void }) {
  const [edit, setEdit] = useState<string | null>(null)
  const save = useMutation({ mutationFn: (n: string) => api.companyName(x.id, n), onSuccess: () => { setEdit(null); onSaved() } })
  const can = x.kind !== 'account' && x.relation !== 'ours'
  if (edit !== null) return (
    <form onSubmit={(e) => { e.preventDefault(); if (edit.trim()) save.mutate(edit.trim()) }} className="flex items-center gap-1.5">
      <input autoFocus value={edit} onChange={(e) => setEdit(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && setEdit(null)} aria-label="Company name"
        className="min-w-0 flex-1 border-b border-ink bg-transparent text-[26px] font-semibold leading-tight tracking-[-0.02em] text-ink outline-none" />
      <button type="submit" aria-label="Save the name" disabled={save.isPending} className="rounded-full p-1.5 text-ink hover:bg-panel2"><Check size={16} /></button>
      <button type="button" aria-label="Cancel" onClick={() => setEdit(null)} className="rounded-full p-1.5 text-ink2 hover:bg-panel2"><X size={16} /></button>
      {save.isError && <span role="alert" className="text-[12px] text-hot">{(save.error as Error).message}</span>}
    </form>)
  return (
    <h1 className="group flex items-center gap-1.5 text-[26px] font-semibold leading-tight tracking-[-0.02em]">{x.name}
      {can && <button onClick={() => setEdit(x.name)} aria-label="Rename" title="Rename" className="rounded-full p-1 text-ink3 opacity-0 transition-opacity hover:bg-panel2 hover:text-ink focus:opacity-100 group-hover:opacity-100"><Pencil size={14} /></button>}
    </h1>)
}

// Acme: the company overview (memory/context/company.md), as the Company page showed it
function Overview() {
  const docs = useQuery({ queryKey: ['docs'], queryFn: api.docs })
  const cur = docs.data?.find((d) => d.path?.endsWith('context/company.md'))
  const doc = useQuery({ queryKey: ['doc', cur?.id], queryFn: () => api.doc(cur!.id), enabled: !!cur })
  const [open, setOpen] = usePersisted('assist-company-overview', false)   // folded: the tagline and facts say enough at a glance
  if (!cur) return null
  const facts = (cur.meta?.facts ?? '').split(' · ').filter(Boolean)
  return (
    <section className="mb-5">
      {(cur.meta?.tagline || facts.length > 0) && <div className="mb-3">
        {cur.meta?.tagline && <p className="text-[14px] text-ink2">{cur.meta.tagline}</p>}
        {facts.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{facts.map((f) => <span key={f} className="rounded-full bg-panel2 px-2.5 py-0.5 text-[12px] text-ink">{f}</span>)}</div>}
      </div>}
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="mb-2 inline-flex items-center gap-1 text-[15px] font-semibold">
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}Overview</button>
      {open && (doc.data ? <div className="border border-line bg-panel p-4 text-[13.5px]"><Markdown>{(doc.data.md ?? '').replace(/^# .*\n+/, '')}</Markdown></div> : <Loading />)}
    </section>
  )
}

// The records this company is made of, and "Same company as…" to merge a duplicate (a Salesforce account and a mail domain,
// two records of one partner). Each record can be split off again.
function Records({ x, onChange }: { x: Page; onChange: () => void }) {
  const nav = useNavigate()
  const [find, setFind] = useState('')
  const [open, setOpen] = useState(false)
  const s = useQuery({ queryKey: ['companySearch', find], queryFn: () => api.companySearch(find), enabled: open && find.trim().length >= 2 })
  const merge = async (into: number) => { await api.companyMerge(x.id, into); onChange(); nav({ to: '/companies/$id', params: { id: String(into) } }) }
  const split = async (rid: number) => { await api.companyMerge(rid, null); onChange() }
  const KIND: Record<string, string> = { account: 'Salesforce account', external: 'mail domain', partner: 'kept by hand', investor: 'kept by hand', internal: org().name || 'internal' }
  return (
    <section className="mb-5 border-t border-line pt-3 text-[12.5px] text-ink2">
      {x.records.length > 1 && <div className="mb-2">Recorded as {x.records.map((r, i) => <span key={r.id}>{i > 0 && ' · '}<b className="font-medium text-ink">{r.name}</b>
        <span className="text-ink3"> ({KIND[r.kind ?? ''] ?? r.kind})</span>{r.id !== x.id && <button onClick={() => split(r.id)} title="Not the same company: show it separately"
          className="ml-1 text-ink3 underline decoration-line underline-offset-2 hover:text-ink">separate</button>}</span>)}</div>}
      {!open ? <button onClick={() => setOpen(true)} className="font-medium text-ink2 underline decoration-line underline-offset-2 hover:text-ink">Same company as…</button> : (
        <div className="max-w-[420px]">
          <div className="flex items-center gap-2">
            <input autoFocus value={find} onChange={(e) => setFind(e.target.value)} placeholder="Name of the other record" aria-label="Find the other record"
              className="min-w-0 flex-1 rounded-full border border-line bg-panel px-3 py-1 text-[12.5px] text-ink outline-none focus:border-ink" />
            <button onClick={() => { setOpen(false); setFind('') }} aria-label="Cancel" className="grid size-6 place-items-center rounded-full hover:bg-panel2"><X size={13} /></button>
          </div>
          <div className="mt-1.5 space-y-0.5">{(s.data ?? []).filter((r) => !x.records.some((m) => m.id === r.id)).map((r) => (
            <button key={r.id} onClick={() => merge(r.id)} className="block w-full rounded-lg px-2 py-1 text-left hover:bg-panel2">
              <span className="text-ink">{r.name}</span><span className="text-ink3"> · {KIND[r.kind ?? ''] ?? r.kind}{r.company !== r.name ? ` · part of ${r.company}` : ''}</span></button>))}</div>
          <p className="mt-1.5 text-[11.5px] text-ink3">{x.name} will show under the record you pick, with both records' people, deals and activity.</p>
        </div>)}
    </section>
  )
}
