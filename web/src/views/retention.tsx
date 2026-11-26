// Retention (Sales): revenue retention from Salesforce renewals, company and deal data only (assist/renewals.py).
// Two levels: the renewal book (ARR that came up for renewal, what was kept) and the company (all Salesforce-tracked ARR,
// bridged back to 1 January). Two tabs: this year so far, and next year's outlook weighted by each segment's share of the
// book. "As recorded" takes Salesforce as it is; "Excluding likely re-papers" treats a lost renewal replaced by a deal at
// the same account within 90 days as kept.
import { useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type RetAgg, type RetRenewal, type Retention as RetData } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { Card, Empty, Loading, Muted, PageTabs, Section, Tag, Tile } from '@/components/ui'
import { FilterBar, FilterRow, Opt, Segmented } from '@/components/FilterBar'
import { viewEntity } from '@/components/EntityPanel'
import { fmtDate, signed, usd } from './pipeline-closed'

type Basis = 'recorded' | 'adjusted'
type Tab = 'year' | 'next'
const pc = (x: number | null | undefined, d = 1) => (x == null ? '—' : `${(x * 100).toFixed(d)}%`)
const REGION_LABEL: Record<string, string> = { NAM: 'North America', EMEA: 'EMEA', Other: 'Japan, LatAm' }
const SOURCE_LABEL = { segment: 'own', region: 'region', all: 'all' }

// Stacked from the base: kept (grey), downsell (light hot), churn (hot); uplift (volt) sits on top. A 2px panel gap
// separates the segments.
const KEPT = 'bg-ink3/55', DOWN = 'bg-hot/45', CHURN = 'bg-hot', UP = 'bg-accent'
function Legend({ items }: { items: [string, string][] }) {
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink2">
      {items.map(([c, l]) => <span key={l} className="flex items-center gap-1.5"><span className={cn('inline-block h-2.5 w-2.5 border border-ink/40', c)} />{l}</span>)}
    </span>)
}

const tbl = 'w-full border-collapse text-[13px]'
const thead = 'text-left text-[12px] [&>th]:whitespace-nowrap [&>th]:border-b [&>th]:border-line [&>th]:px-2 [&>th]:py-2 [&>th]:font-semibold'
const tbody = '[&>tr>td]:border-b [&>tr>td]:border-line2 [&>tr>td]:px-2 [&>tr>td]:py-1.5 [&>tr>td]:align-top [&>tr>td]:tabular-nums'

export function Retention() {
  const q = useQuery({ queryKey: ['retention'], queryFn: api.retention })
  const [tab, setTab] = usePersisted<Tab>('assist-retention-tab', 'year')
  const [basis, setBasis] = usePersisted<Basis>('assist-retention-basis', 'recorded')
  const d = q.data
  return (
    <div>
      <PageTabs title="Retention" label="Retention views" active={tab} onSelect={setTab}
        tabs={[{ key: 'year', label: d ? `${d.year} so far` : 'This year' }, { key: 'next', label: d ? `${d.year + 1} outlook` : 'Next year' }]}
        right={<>
          {d?.pulled && <span className="text-ink3">Salesforce pulled {fmtDate(d.pulled)}</span>}
          <span title={`A lost renewal counts as a likely re-paper when the same account won a comparable deal within ${d?.repaper_days ?? 90} days: a duplicate renewal is dropped; a renewal replaced by an upsell, cross-sell or new contract counts as kept.`}>
            <Segmented value={basis} onChange={setBasis} options={[['recorded', 'As recorded'], ['adjusted', `Excluding likely re-papers${d ? ` · ${d.notes.repapers}` : ''}`]]} /></span>
        </>} />
      {!d ? <Loading /> : !d.closed.length && !d.upcoming.length ? <Empty>No renewals yet. Run /salesforce.</Empty>
        : tab === 'year' ? <ThisYear d={d} basis={basis} /> : <NextYear d={d} basis={basis} />}
      {d && <Method d={d} />}
    </div>
  )
}

// ---------- this year ----------

function ThisYear({ d, basis }: { d: RetData; basis: Basis }) {
  const b = d.bases[basis], other = d.bases[basis === 'recorded' ? 'adjusted' : 'recorded'], a = b.actual, c = b.company
  const lastQ = a.by_quarter[a.by_quarter.length - 1]?.key
  const toDate = (qq: string) => (qq === lastQ ? `${qq} to date` : qq)
  const regions = a.by_region.filter((r) => r.n >= 5)
  const max = Math.max(1, ...a.by_quarter.map((x) => x.prior + x.uplift))
  const fyRest = b.rest_of_year
  return (
    <div>
      <Section right={<span className="text-[12.5px] font-normal text-ink2">ARR that came up for renewal, by close date since {fmtDate(d.since)}</span>}>Renewal book</Section>
      <div className="mb-2 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile value={pc(a.grr)} label="gross renewal rate" note={<>{usd(a.kept)} kept of {usd(a.prior)} up for renewal · {basis === 'recorded' ? 'excluding re-papers' : 'as recorded'} {pc(other.actual.grr)}</>} />
        <Tile value={pc(a.nrr)} label="net renewal rate" note={<>uplift {signed(a.uplift)}, downsell {signed(-a.downsell)} · {usd(a.renewed)} renewed</>} />
        <Tile value={pc(a.logo_retention)} label="logo retention" note={<>{a.logos - a.logos_lost} of {a.logos} customers kept · {a.won} of {a.n} renewals won ({pc(a.renewal_rate, 0)})</>} />
        <Tile value={usd(a.lost_arr)} label="ARR lost" note={<>churn {usd(a.churn)} ({a.lost} renewals) · downsell {usd(a.downsell)}</>} />
      </div>

      <Section right={<span className="text-[12.5px] font-normal text-ink2">all Salesforce-tracked ARR · estimate</span>}>Company</Section>
      <div className="mb-2 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)]">
        <Tile value={pc(c.grr)} label={`gross revenue retention · ${d.year} to date`} note={<>{usd(a.lost_arr)} lost on {usd(c.base_start)} ARR at 1 Jan · full year projected <b className="text-ink">{pc(c.fy.grr)}</b></>} />
        <Tile value={pc(c.nrr)} label={`net revenue retention · ${d.year} to date`} note={<>expansion {signed(c.expansion)}, uplift {signed(a.uplift)} · full year projected <b className="text-ink">{pc(c.fy.nrr)}</b></>} />
        <Card className="px-4 py-3">
          <div className="mb-1.5 text-[13px] font-medium">ARR bridge since 1 January</div>
          <table className="w-full text-[12.5px] tabular-nums [&_td]:py-[2px]"><tbody>
            {([['1 January (estimate)', c.base_start, true], ['New logos', c.new_logo], ['Expansion (upsell, cross-sell)', c.expansion], ['Uplift on renewals', a.uplift],
              ['Downsell', -a.downsell], ['Churn', -a.churn], ['Today: open renewals', d.base_now.arr, true]] as [string, number, boolean?][]).map(([l, v, strong]) => (
              <tr key={l} className={cn(strong && 'font-semibold', l.startsWith('Today') && '[&>td]:border-t [&>td]:border-line')}>
                <td>{l}</td><td className={cn('text-right', !strong && v < 0 && 'text-hot')}>{strong ? usd(v) : signed(v)}</td></tr>))}
          </tbody></table>
          {c.expansion_taken_back > 0 && <div className="mt-1 text-[11.5px] text-ink3">Expansion excludes {usd(c.expansion_taken_back)} of old contract value carried into re-papered deals.</div>}
        </Card>
      </div>
      <Muted className="mb-5">Full year projected = to date, plus the {fyRest.n} renewals still due this year ({usd(fyRest.prior)}, overdue included) at this year's rates for their segment ({pc(fyRest.grr)} gross), plus expansion at this year's pace.</Muted>

      <Section right={<Legend items={[[KEPT, 'Kept'], [DOWN, 'Downsell'], [CHURN, 'Churn'], [UP, 'Uplift']]} />}>By quarter</Section>
      <div className={cn('mb-5 grid gap-3', regions.length > 1 ? 'lg:grid-cols-3' : 'lg:grid-cols-2')}>
        <Card className="px-4 py-3">
          <div className="flex items-baseline gap-2"><span className="text-[15px] font-semibold">All regions</span>
            <span className="ml-auto text-[12.5px] tabular-nums text-ink2">{pc(a.grr)} gross · {pc(a.nrr)} net</span></div>
          <QuarterBars rows={a.by_quarter.map((x) => ({ label: x.key, full: toDate(x.key), agg: x }))} max={max} />
        </Card>
        {regions.map((r) => {
          const rows = a.by_region_quarter.filter((x) => x.region === r.key)
          const rmax = Math.max(1, ...rows.map((x) => x.prior + x.uplift))
          return (
            <Card key={r.key} className="px-4 py-3">
              <div className="flex items-baseline gap-2"><span className="text-[15px] font-semibold">{REGION_LABEL[r.key] ?? r.key}</span>
                <span className="ml-auto text-[12.5px] tabular-nums text-ink2">{pc(r.grr)} gross · {pc(r.nrr)} net</span></div>
              <QuarterBars rows={rows.map((x) => ({ label: x.quarter, full: `${REGION_LABEL[r.key] ?? r.key} · ${toDate(x.quarter)}`, agg: x }))} max={rmax} />
            </Card>)
        })}
      </div>

      <div className="mb-5 grid gap-4 xl:grid-cols-2">
        <div>
          <Section>By contract size</Section>
          <Card className="overflow-x-auto px-3 py-1">
            <table className={tbl}>
              <thead><tr className={thead}><th>Prior ARR</th><th className="text-right">Renewals</th><th className="text-right">Up for renewal</th><th className="text-right">Gross</th><th className="text-right">Net</th><th className="text-right">Won</th></tr></thead>
              <tbody className={tbody}>{a.by_band.map((x) => (
                <tr key={x.key}><td className="whitespace-nowrap">{x.key}</td><td className="text-right">{x.n}</td><td className="text-right">{usd(x.prior)}</td>
                  <td className="text-right"><RateCell v={x.grr} /></td><td className="text-right">{pc(x.nrr)}</td><td className="text-right text-ink2">{pc(x.renewal_rate, 0)}</td></tr>))}
              </tbody>
            </table>
          </Card>
        </div>
        <div>
          <Section>Quarter by region</Section>
          <Card className="overflow-x-auto px-3 py-1">
            <table className={tbl}>
              <thead><tr className={thead}><th>Quarter</th><th>Region</th><th className="text-right">Up</th><th className="text-right">Churn</th><th className="text-right">Downsell</th><th className="text-right">Gross</th><th className="text-right">Net</th></tr></thead>
              <tbody className={tbody}>{[...a.by_quarter].reverse().flatMap((x) => [
                <tr key={x.key} className="font-semibold"><td className="whitespace-nowrap">{toDate(x.key)}</td><td>All</td><td className="text-right">{usd(x.prior)}</td><td className="text-right">{usd(x.churn)}</td><td className="text-right">{usd(x.downsell)}</td><td className="text-right">{pc(x.grr)}</td><td className="text-right">{pc(x.nrr)}</td></tr>,
                ...a.by_region_quarter.filter((y) => y.quarter === x.key).map((y) => (
                  <tr key={x.key + y.region}><td /><td className="whitespace-nowrap pl-5">{REGION_LABEL[y.region] ?? y.region}</td><td className="text-right">{usd(y.prior)}</td><td className="text-right">{usd(y.churn)}</td><td className="text-right">{usd(y.downsell)}</td><td className="text-right">{pc(y.grr)}</td><td className="text-right">{pc(y.nrr)}</td></tr>))])}
              </tbody>
            </table>
          </Card>
        </div>
      </div>

      <ClosedList d={d} basis={basis} />
      <Overdue d={d} basis={basis} />
    </div>
  )
}

function QuarterBars({ rows, max }: { rows: { label: string; full: string; agg: RetAgg }[]; max: number }) {
  const h = (v: number) => (v > 0 ? Math.max(2, (v / max) * 112) : 0)
  return (
    <>
      <div className="mt-3 flex h-[150px] items-end gap-2 border-b border-line">
        {rows.map(({ label, full, agg: x }) => (
          <div key={label} className="flex h-full flex-1 flex-col items-center justify-end"
            title={`${full}: ${usd(x.prior)} up for renewal in ${x.n} renewals\nKept ${usd(x.kept)} · downsell ${usd(x.downsell)} · churn ${usd(x.churn)} (${x.lost} lost)\nUplift ${usd(x.uplift)} · renewed ${usd(x.renewed)}\nGross ${pc(x.grr)} · net ${pc(x.nrr)}`}>
            <span className="mb-1 text-[11.5px] font-semibold tabular-nums">{pc(x.grr, 0)}</span>
            <span className="flex w-full max-w-10 flex-col-reverse gap-[2px]">
              {([[KEPT, x.kept], [DOWN, x.downsell], [CHURN, x.churn], [UP, x.uplift]] as [string, number][]).filter(([, v]) => v > 0).map(([cls, v]) => (
                <span key={cls} className={cls} style={{ height: `${h(v)}px` }} />))}
            </span>
          </div>))}
      </div>
      <div className="mt-1 flex gap-2">{rows.map((r) => <span key={r.label} className="flex-1 text-center text-[11.5px] text-ink3">{r.label.slice(0, 2)}</span>)}</div>
      <div className="mt-1 text-[11.5px] text-ink3">Figure above each bar: gross renewal rate</div>
    </>)
}

const RateCell = ({ v }: { v: number | null }) => (
  <span className="inline-flex items-center justify-end gap-2">
    <span aria-hidden className="hidden h-1.5 w-14 bg-panel2 sm:block"><span className="block h-full bg-ink3/55" style={{ width: `${Math.max(0, Math.min(1, v ?? 0)) * 100}%` }} /></span>
    {pc(v)}
  </span>)

function useOrgs() {
  const orgs = useQuery({ queryKey: ['orgs'], queryFn: api.orgs, staleTime: 300_000 })
  return useMemo(() => new Map((orgs.data ?? []).map((o) => [o.name, o.id] as [string, number])), [orgs.data])
}

function Account({ r, orgId }: { r: RetRenewal; orgId: Map<string, number> }) {
  const id = orgId.get(r.account)
  return <>{id ? <button onClick={() => viewEntity('org', id)} title="Open the account: deals, people, open items and every mail and meeting" className="text-left font-semibold underline decoration-accent decoration-2 underline-offset-2">{r.account}</button>
    : r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.account}</a> : <b>{r.account}</b>}
    {r.url && id && <a href={r.url} target="_blank" rel="noreferrer" className="ml-1.5 text-[12px]">SF ↗</a>}</>
}

function ClosedList({ d, basis }: { d: RetData; basis: Basis }) {
  const orgId = useOrgs()
  const [show, setShow] = useState<'lost' | 'down' | 'all'>('lost')
  const [region, setRegion] = useState('')
  const [search, setSearch] = useState('')
  const lostLogos = new Set(d.bases[basis].actual.lost_logo_accounts)
  const pick = (r: RetRenewal) => (show === 'lost' ? r.outcome === 'lost' : show === 'down' ? r.outcome === 'won' && r.change_usd < 0 : true)
  const scoped = d.closed.filter((r) => (!region || r.region === region))
  let list = scoped.filter(pick)
  if (search.trim()) { const re = new RegExp(search.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'); list = list.filter((r) => re.test(r.account)) }
  list = [...list].sort((x, y) => (show === 'all' ? y.close_date.localeCompare(x.close_date) : x.change_usd - y.change_usd))
  return (
    <>
      <Section>Churn and downsell · {d.year}</Section>
      <FilterBar search={search} onSearch={setSearch} placeholder="Search account…"
        tokens={region ? [{ label: REGION_LABEL[region] ?? region, onRemove: () => setRegion('') }] : []}
        right={<Segmented value={show} onChange={setShow} options={[['lost', `Lost · ${scoped.filter((r) => r.outcome === 'lost').length}`], ['down', `Downsold · ${scoped.filter((r) => r.outcome === 'won' && r.change_usd < 0).length}`], ['all', `All closed · ${scoped.length}`]]} />}>
        <FilterRow label="Region"><Opt on={!region} onClick={() => setRegion('')}>All</Opt>
          {['NAM', 'EMEA', 'Other'].filter((g) => d.closed.some((r) => r.region === g)).map((g) => <Opt key={g} on={region === g} onClick={() => setRegion(region === g ? '' : g)}>{REGION_LABEL[g]}</Opt>)}</FilterRow>
      </FilterBar>
      {list.length === 0 ? <Empty>Nothing here.</Empty> : (
        <Card className="mb-5 overflow-x-auto px-3 py-1">
          <table className={tbl}>
            <thead><tr className={thead}><th>Closed</th><th>Account</th><th className="max-md:hidden">Region</th><th className="text-right">Was</th><th className="text-right">Now</th><th className="text-right">Change</th><th className="max-md:hidden">Note</th></tr></thead>
            <tbody className={tbody}>
              {list.slice(0, 200).map((r) => (
                <tr key={r.id} className="hover:bg-panel2">
                  <td className="whitespace-nowrap">{fmtDate(r.close_date)}</td>
                  <td><Account r={r} orgId={orgId} /></td>
                  <td className="max-md:hidden">{r.region}</td>
                  <td className="whitespace-nowrap text-right">{usd(r.prior_usd)}</td>
                  <td className="whitespace-nowrap text-right">{r.outcome === 'lost' ? '—' : usd(r.value_usd)}</td>
                  <td className={cn('whitespace-nowrap text-right', r.change_usd < 0 && 'text-hot')}>{signed(r.change_usd)}</td>
                  <td className="max-md:hidden text-[12.5px]">
                    {r.replaced_by ? <span className="inline-flex flex-wrap items-center gap-1.5"><Tag tone="good">{basis === 'adjusted' ? (r.replaced_by.kind === 'Renewal' ? 'dropped as duplicate' : 'counted as kept') : 'likely re-paper'}</Tag>
                      <span className="text-ink2">{r.replaced_by.sale_type} {usd(r.replaced_by.value_usd)} won {fmtDate(r.replaced_by.close_date)}{r.replaced_by.url && <> · <a href={r.replaced_by.url} target="_blank" rel="noreferrer">SF ↗</a></>}</span></span>
                      : r.outcome === 'lost' && lostLogos.has(r.account) ? <Tag tone="pending">customer lost</Tag>
                      : r.outcome === 'lost' ? <span className="text-ink2">still a customer (other contract)</span> : null}
                  </td>
                </tr>))}
            </tbody>
          </table>
          {list.length > 200 && <Muted className="px-2 py-2">First 200 of {list.length}.</Muted>}
        </Card>)}
    </>)
}

function Overdue({ d, basis }: { d: RetData; basis: Basis }) {
  const orgId = useOrgs()
  const list = d.upcoming.filter((r) => r.overdue)
  if (!list.length) return null
  return (
    <>
      <Section right={<span className="text-[12.5px] font-normal text-ink2">close date passed, still open in Salesforce</span>}>Overdue renewals · {list.length} · {usd(list.reduce((s, r) => s + r.prior_usd, 0))}</Section>
      <Card className="mb-5 overflow-x-auto px-3 py-1">
        <RenewalTable list={list} orgId={orgId} basis={basis} />
      </Card>
    </>)
}

// ---------- next year ----------

function NextYear({ d, basis }: { d: RetData; basis: Basis }) {
  const orgId = useOrgs()
  const n = d.bases[basis].next_year, other = d.bases[basis === 'recorded' ? 'adjusted' : 'recorded'].next_year, ny = n.year
  const [scope, setScope] = useState<'next' | 'rest'>('next')
  const [region, setRegion] = useState('')
  const pool = d.upcoming.filter((r) => (scope === 'next' ? r.close_date.startsWith(String(ny)) : r.close_date <= `${d.year}-12-31`) && (!region || r.region === region))
  const qmax = Math.max(1, ...n.by_quarter.map((x) => x.prior))
  const views: [string, string, number | null, number | null, ReactNode][] = [
    ['History, weighted by segment share', `${d.year} rates for each region and contract size, weighted by its share of the ${ny} book`, n.grr, n.nrr, usd(n.expected_kept)],
    ['Salesforce stage probability', 'probability on each renewal (50% at Validate, 75% Create Quote, 90% Awaiting Order) × quoted value', n.stage.grr, n.stage.nrr, usd((n.stage.grr ?? 0) * n.prior)],
    ['Every renewal closes as quoted', 'no churn; downsells and uplifts already in the quotes', n.as_quoted.grr, n.as_quoted.nrr, usd((n.as_quoted.grr ?? 0) * n.prior)],
  ]
  return (
    <div>
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile value={usd(n.prior)} label={`up for renewal in ${ny}`} note={<>{n.n} renewals · {n.accounts} customers · {Math.round((n.prior / Math.max(1, d.base_now.arr)) * 100)}% of today's ARR</>} />
        <Tile value={pc(n.grr)} label="expected gross renewal rate" note={<>{usd(n.expected_lost)} at risk · {basis === 'recorded' ? 'excluding re-papers' : 'as recorded'} {pc(other.grr)}</>} />
        <Tile value={pc(n.nrr)} label="expected net renewal rate" note={<>{usd(n.expected_renewed)} renewed · quotes already carry {usd(n.downsell_quoted)} of downsell or churn</>} />
        <Tile value={`${pc(n.company_grr)} · ${pc(n.company_nrr)}`} label={`company GRR · NRR, ${ny}`} note={<>on {usd(n.base_start)} ARR at 1 Jan {ny} · expansion {signed(n.expansion)} at {d.year}'s pace</>} />
      </div>

      <div className="mb-5 grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div>
          <Section>Three ways to read the {ny} book</Section>
          <Card className="overflow-x-auto px-3 py-1">
            <table className={tbl}>
              <thead><tr className={thead}><th>View</th><th className="text-right">Gross</th><th className="text-right">Net</th><th className="text-right">ARR kept</th></tr></thead>
              <tbody className={tbody}>{views.map(([l, note, g, nn, kept], i) => (
                <tr key={l} className={cn(i === 0 && 'font-semibold')}><td><div>{l}{i === 0 && <span className="ml-1.5 font-normal"><Tag tone="good">headline</Tag></span>}</div><div className="text-[12px] font-normal text-ink3">{note}</div></td>
                  <td className="text-right">{pc(g)}</td><td className="text-right">{pc(nn)}</td><td className="whitespace-nowrap text-right">{kept}</td></tr>))}
              </tbody>
            </table>
          </Card>
          <Muted className="mt-1.5">Stage probability is a floor: almost every renewal sits at Validate (50%) until weeks before it closes, while {d.year}'s renewals kept {pc(d.bases[basis].actual.grr)} by value.</Muted>
        </div>
        <div>
          <Section right={<Legend items={[[KEPT, 'Expected kept'], [DOWN, 'At risk']]} />}>When it lands</Section>
          <Card className="px-4 py-3">
            <div className="flex h-[150px] items-end gap-3 border-b border-line">
              {n.by_quarter.map((x) => {
                const risk = x.prior - x.expected_kept, h = (v: number) => (v > 0 ? Math.max(2, (v / qmax) * 112) : 0)
                return (
                  <div key={x.quarter} className="flex h-full flex-1 flex-col items-center justify-end" title={`${x.quarter}: ${usd(x.prior)} due in ${x.n} renewals\nExpected kept ${usd(x.expected_kept)} · at risk ${usd(risk)}`}>
                    <span className="mb-1 text-[11.5px] font-semibold tabular-nums">{usd(x.prior)}</span>
                    <span className="flex w-full max-w-12 flex-col-reverse gap-[2px]">
                      <span className={KEPT} style={{ height: `${h(x.expected_kept)}px` }} />
                      {risk > 0 && <span className={DOWN} style={{ height: `${h(risk)}px` }} />}
                    </span>
                  </div>)
              })}
            </div>
            <div className="mt-1 flex gap-3">{n.by_quarter.map((x) => <span key={x.quarter} className="flex-1 text-center text-[11.5px] text-ink3">{x.quarter.slice(0, 2)} · {x.n}</span>)}</div>
          </Card>
        </div>
      </div>

      <Section>By segment: share of the {ny} book × {d.year} rate</Section>
      <Card className="overflow-x-auto px-3 py-1">
        <table className={tbl}>
          <thead><tr className={thead}><th>Region</th><th>Prior ARR</th><th className="text-right">Renewals</th><th className="text-right">Due {ny}</th><th className="text-right">Share</th>
            <th className="text-right">{d.year} gross</th><th className="text-right max-xl:hidden">{d.year} net</th><th className="max-xl:hidden" title="closed renewals the rate is based on">Rate from</th><th className="text-right">Expected kept</th><th className="text-right">At risk</th></tr></thead>
          <tbody className={tbody}>
            {n.segments.map((s, i) => (
              <tr key={s.region + s.band}>
                <td className="whitespace-nowrap">{i === 0 || n.segments[i - 1].region !== s.region ? (REGION_LABEL[s.region] ?? s.region) : ''}</td>
                <td className="whitespace-nowrap">{s.band}</td><td className="text-right">{s.n}</td><td className="text-right">{usd(s.prior)}</td>
                <td className="text-right"><span className="inline-flex items-center justify-end gap-2"><span aria-hidden className="hidden h-1.5 w-10 bg-panel2 sm:block"><span className="block h-full bg-accent" style={{ width: `${s.share * 100}%` }} /></span>{pc(s.share, 0)}</span></td>
                <td className="text-right">{pc(s.grr)}</td><td className="text-right max-xl:hidden">{pc(s.nrr)}</td>
                <td className="max-xl:hidden whitespace-nowrap text-[12.5px] text-ink2">{SOURCE_LABEL[s.source]} · {s.hist_n}</td>
                <td className="text-right">{usd(s.expected_kept)}</td><td className="text-right text-hot">{usd(s.prior - s.expected_kept)}</td>
              </tr>))}
          </tbody>
          <tfoot className="[&>tr>td]:border-t-2 [&>tr>td]:border-ink [&>tr>td]:px-2 [&>tr>td]:py-1.5 [&>tr>td]:font-semibold [&>tr>td]:tabular-nums">
            <tr><td colSpan={2}>All</td><td className="text-right">{n.n}</td><td className="text-right">{usd(n.prior)}</td><td className="text-right">100%</td>
              <td className="text-right">{pc(n.grr)}</td><td className="text-right max-xl:hidden">{pc(n.nrr)}</td><td className="max-xl:hidden" /><td className="text-right">{usd(n.expected_kept)}</td><td className="text-right text-hot">{usd(n.expected_lost)}</td></tr>
          </tfoot>
        </table>
      </Card>
      <Muted className="mb-5 mt-1.5">A segment needs {d.min_n} or more closed renewals this year for its own rate; otherwise its region's rate applies, then the rate across all renewals. Rate from shows which, and how many renewals it rests on.</Muted>

      <Section>Largest renewals</Section>
      <FilterBar tokens={region ? [{ label: REGION_LABEL[region] ?? region, onRemove: () => setRegion('') }] : []}
        right={<Segmented value={scope} onChange={setScope} options={[['next', `${ny} · ${d.upcoming.filter((r) => r.close_date.startsWith(String(ny))).length}`], ['rest', `Rest of ${d.year} · ${d.upcoming.filter((r) => r.close_date <= `${d.year}-12-31`).length}`]]} />}>
        <FilterRow label="Region"><Opt on={!region} onClick={() => setRegion('')}>All</Opt>
          {['NAM', 'EMEA', 'Other'].filter((g) => d.upcoming.some((r) => r.region === g)).map((g) => <Opt key={g} on={region === g} onClick={() => setRegion(region === g ? '' : g)}>{REGION_LABEL[g]}</Opt>)}</FilterRow>
      </FilterBar>
      {pool.length === 0 ? <Empty>No renewals due.</Empty> : (
        <Card className="mb-5 overflow-x-auto px-3 py-1">
          <RenewalTable list={pool.slice(0, 60)} orgId={orgId} basis={basis} />
          {pool.length > 60 && <Muted className="px-2 py-2">Largest 60 of {pool.length}.</Muted>}
        </Card>)}
    </div>
  )
}

function RenewalTable({ list, orgId, basis }: { list: RetRenewal[]; orgId: Map<string, number>; basis: Basis }) {
  return (
    <table className={tbl}>
      <thead><tr className={thead}><th>Due</th><th>Account</th><th className="max-md:hidden">Region</th><th className="text-right">Current ARR</th><th className="text-right">Quoted</th>
        <th className="text-right">Change</th><th className="max-md:hidden">Stage</th><th className="text-right max-xl:hidden" title="this year's gross renewal rate for the renewal's region and size">History says</th></tr></thead>
      <tbody className={tbody}>
        {list.map((r) => (
          <tr key={r.id} className="hover:bg-panel2">
            <td className="whitespace-nowrap">{fmtDate(r.close_date)}</td>
            <td><Account r={r} orgId={orgId} />
              {(r.overdue || r.change_usd < 0 || r.history) && <span className="mt-1 flex flex-wrap gap-1">
                {r.overdue && <Tag tone="pending">overdue</Tag>}
                {r.change_usd < 0 && <Tag tone="pending">{r.value_usd === 0 ? 'churn forecast' : 'downsell quoted'}</Tag>}
                {r.history && <Tag>{r.history} this year</Tag>}
              </span>}</td>
            <td className="max-md:hidden">{r.region}</td>
            <td className="whitespace-nowrap text-right font-semibold">{usd(r.prior_usd)}</td>
            <td className="whitespace-nowrap text-right">{usd(r.value_usd)}</td>
            <td className={cn('whitespace-nowrap text-right', r.change_usd < 0 && 'text-hot')}>{r.change_usd ? signed(r.change_usd) : '—'}</td>
            <td className="max-md:hidden whitespace-nowrap text-[12.5px]">{r.stage.replace(/^\d+ - /, '')}{r.probability != null && <span className="text-ink3"> · {r.probability}%</span>}</td>
            <td className="text-right max-xl:hidden">{pc(r.rate?.[basis], 0)}</td>
          </tr>))}
      </tbody>
    </table>)
}

// ---------- method ----------

function Method({ d }: { d: RetData }) {
  const lost = d.notes.lost_renewals
  return (
    <details className="mt-6 border border-line bg-panel px-4 py-3 text-[13px] leading-relaxed">
      <summary className="cursor-pointer font-semibold">How these figures are worked out</summary>
      <ul className="mt-2 list-disc space-y-1.5 pl-5 text-ink2">
        <li><b className="text-ink">Prior ARR</b> is the contract a renewal replaces: ACV minus Salesforce's net forecast for a won or open renewal, and the negative net forecast for a lost one. Values are approximate US dollars. Renewals worth under $100 ($1 and €1 placeholders) are left out.</li>
        <li><b className="text-ink">Gross renewal rate</b> = prior ARR less churn and downsell, over prior ARR; never above 100%. <b className="text-ink">Net renewal rate</b> = renewed value over prior ARR, uplifts included. <b className="text-ink">Logo retention</b>: a customer is lost when every renewal it had this year was lost and it has no other contract or won deal.</li>
        <li><b className="text-ink">Company GRR and NRR</b> use all Salesforce-tracked ARR: today it is the contract value of every open renewal ({usd(d.base_now.arr)} over {d.base_now.contracts} contracts at {d.base_now.accounts} customers), bridged back to 1 January through this year's new logos, expansion, uplift, downsell and churn. regional partner and white-label ARR has no Salesforce renewal, so this base is below finance's ARR.</li>
        <li><b className="text-ink">Next year</b>: each open renewal due next year sits in a segment (region × prior ARR band). Its segment's rate from this year's closed renewals applies, and segments count by their share of the book. Expansion is assumed to run at this year's pace; new logos are not in the base.</li>
        <li><b className="text-ink">Likely re-papers</b> ({d.notes.repapers}): a lost renewal where the same account won a deal worth at least half as much within {d.repaper_days} days. This is an inference from dates and values; Salesforce records no reason.</li>
        <li><b className="text-ink">Limits</b>: closed deals are pulled from {fmtDate(d.since)}, so there is no year-on-year comparison yet. {d.notes.loss_reasons} of {lost} lost renewals carry a loss or churn reason. Quarters here are by Salesforce close date; finance's ARR Bridge (QBRs, board pack) books churn by contract date and includes ARR adjustments, so quarter figures will not match it line for line.</li>
      </ul>
    </details>)
}
