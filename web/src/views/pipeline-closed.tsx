// Closed deals: Salesforce Closed Won / Closed Lost since Q1 2026 (company and deal data only), by quarter and region.
// Owners are never stored (org policy), so "who closed what" is answered by sales territory, not by rep.
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type ClosedDeal } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { Card, Empty, Loading, Muted, Section, Tile } from '@/components/ui'
import { FilterBar, FilterRow, Opt, Segmented } from '@/components/FilterBar'
import { viewEntity } from '@/components/EntityPanel'
import { LOCALE } from '@/lib/time'

export const usd = (n: number) => { const s = n < 0 ? '−' : ''; const a = Math.abs(n); return s + (a >= 1e6 ? `$${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `$${Math.round(a / 1e3)}K` : `$${Math.round(a)}`) }
export const signed = (n: number) => (n > 0 ? '+' : '') + usd(n)
export const local = (n: number, cur: string) => `${cur} ${n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'K' : Math.round(n)}`
export const fmtDate = (d: string) => (d ? new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short', year: '2-digit', timeZone: 'UTC' }).format(new Date(d)) : '—')
const qKey = (q: string) => { const m = /^Q(\d) (\d{4})$/.exec(q); return m ? +m[2] * 10 + +m[1] : 0 }
const REGION_ORDER = ['NAM', 'EMEA', 'JPN', 'LATAM']
const REGION_LABEL: Record<string, string> = { NAM: 'North America', EMEA: 'EMEA', JPN: 'Japan', LATAM: 'Latin America' }
const sum = (l: ClosedDeal[], f: (d: ClosedDeal) => number) => l.reduce((a, d) => a + f(d), 0)
const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : '—')

// Bars are stacked new business (volt, at the base so it compares across bars) then renewals (grey); services are not ARR and stay out.
export const NEW_BAR = 'bg-accent', RENEWAL_BAR = 'bg-ink3/55'
export function SplitLegend({ note }: { note?: string }) {
  const sw = (c: string) => <span className={cn('inline-block h-2.5 w-2.5 border border-ink/40', c)} />
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink2">
      <span className="flex items-center gap-1.5">{sw(NEW_BAR)}New business</span>
      <span className="flex items-center gap-1.5">{sw(RENEWAL_BAR)}Renewals</span>
      {note && <span className="text-ink3">{note}</span>}
    </span>)
}
const wonSplit = (l: ClosedDeal[]) => {
  const nb = l.filter((d) => d.won && d.kind === 'New business'), rn = l.filter((d) => d.won && d.kind === 'Renewal')
  return { nb, rn, nbV: sum(nb, (d) => d.value_usd), rnV: sum(rn, (d) => d.value_usd) }
}

function stats(l: ClosedDeal[]) {
  const won = l.filter((d) => d.won), nb = l.filter((d) => d.kind === 'New business'), nbWon = nb.filter((d) => d.won)
  return {
    won: won.length, lost: l.length - won.length, wonValue: sum(won, (d) => d.value_usd),
    nbWon: nbWon.length, nbValue: sum(nbWon, (d) => d.value_usd), newLogos: nbWon.filter((d) => d.sale_type === 'New Logo').length,
    nbLost: nb.length - nbWon.length, nbLostValue: sum(nb.filter((d) => !d.won), (d) => d.value_usd),
    renewals: won.filter((d) => d.kind === 'Renewal'), services: won.filter((d) => d.kind === 'Services'),
    netArr: sum(won.filter((d) => d.kind !== 'Services'), (d) => d.net_usd),
    winRate: pct(nbWon.length, nb.length), winRateValue: pct(sum(nbWon, (d) => d.value_usd), sum(nb, (d) => d.value_usd)),
  }
}

type Sort = 'date' | 'value' | 'net'

export function ClosedDeals() {
  const q = useQuery({ queryKey: ['pipeline-closed'], queryFn: api.pipelineClosed })
  const orgs = useQuery({ queryKey: ['orgs'], queryFn: api.orgs, staleTime: 300_000 })
  const orgId = useMemo(() => new Map((orgs.data ?? []).map((o) => [o.name, o.id] as [string, number])), [orgs.data])
  const [f, setF] = usePersisted('assist-closed', { period: 'ytd', region: '', kind: '', outcome: 'won' as 'won' | 'lost' })
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<Sort>('value')
  const deals = q.data?.deals ?? []
  const quarters = useMemo(() => [...new Set(deals.map((d) => d.quarter).filter(Boolean))].sort((a, b) => qKey(a) - qKey(b)), [deals])
  const regions = useMemo(() => {
    const seen = [...new Set(deals.map((d) => d.region).filter(Boolean))]
    return seen.sort((a, b) => (REGION_ORDER.indexOf(a) + 1 || 99) - (REGION_ORDER.indexOf(b) + 1 || 99))
  }, [deals])
  const inPeriod = useMemo(() => (f.period === 'ytd' ? deals : deals.filter((d) => d.quarter === f.period)), [deals, f.period])
  const scoped = useMemo(() => (f.region ? inPeriod.filter((d) => d.region === f.region) : inPeriod), [inPeriod, f.region])
  const list = useMemo(() => {
    let l = scoped.filter((d) => d.won === (f.outcome === 'won'))
    if (f.kind) l = l.filter((d) => d.kind === f.kind)
    if (search.trim()) { const re = new RegExp(search.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'); l = l.filter((d) => re.test([d.account, d.name, d.use_case, d.sale_type].join(' '))) }
    const by: Record<Sort, (a: ClosedDeal, b: ClosedDeal) => number> = {
      date: (a, b) => b.close_date.localeCompare(a.close_date) || b.value_usd - a.value_usd,
      value: (a, b) => b.value_usd - a.value_usd, net: (a, b) => b.net_usd - a.net_usd,
    }
    return [...l].sort(by[sort])
  }, [scoped, f.outcome, f.kind, search, sort])

  if (!q.data) return <Loading />
  if (!deals.length) return <Empty>No closed deals yet. Run /salesforce.</Empty>

  const s = stats(scoped)
  const lastQ = quarters[quarters.length - 1]
  const toDate = (qq: string) => (qq === lastQ && q.data.today < quarterEnd(qq) ? `${qq} to date` : qq)
  const periodLabel = f.period === 'ytd' ? `since ${quarters[0]}` : toDate(f.period)
  const cell = (qq: string, r: string) => deals.filter((d) => d.quarter === qq && d.region === r)
  const chartMax = Math.max(1, ...quarters.flatMap((qq) => regions.map((r) => { const sp = wonSplit(cell(qq, r)); return sp.nbV + sp.rnV })))
  const chartRegions = regions.filter((r) => deals.some((d) => d.region === r && d.won && d.kind !== 'Services'))
  const barH = (v: number) => (v ? Math.max(3, (v / chartMax) * 100) : 0)

  return (
    <div>
      <FilterBar tokens={f.region ? [{ label: REGION_LABEL[f.region] ?? f.region, onRemove: () => setF({ ...f, region: '' }) }] : []}
        right={<>{q.data.pulled && <span className="text-ink3">pulled {q.data.pulled}</span>}
          <Segmented value={f.period} onChange={(v) => setF({ ...f, period: v })} options={[['ytd', 'Year to date'], ...quarters.map((qq) => [qq, toDate(qq)] as [string, string])]} /></>}>
        <FilterRow label="Region">
          <Opt on={!f.region} onClick={() => setF({ ...f, region: '' })}>All</Opt>
          {regions.map((r) => <Opt key={r} on={f.region === r} onClick={() => setF({ ...f, region: f.region === r ? '' : r })} count={inPeriod.filter((d) => d.region === r).length}>{REGION_LABEL[r] ?? r}</Opt>)}
        </FilterRow>
      </FilterBar>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile value={usd(s.wonValue)} label={`won · ${periodLabel}`} note={`${s.won} deals: ${s.nbWon} new business · ${s.renewals.length} renewals · ${s.services.length} services`} />
        <Tile value={usd(s.nbValue)} label="new business won (ACV)" note={`${s.newLogos} new logos · ${s.nbWon - s.newLogos} upsell or cross-sell`} />
        <Tile value={signed(s.netArr)} label="net ARR added" note={`renewals ${signed(sum(s.renewals, (d) => d.net_usd))} on ${usd(sum(s.renewals, (d) => d.value_usd))} renewed`} />
        <div title="Lost deals include pipeline clean-ups, so this is a floor"><Tile value={s.winRate} label="new business win rate" note={`${s.nbWon} won, ${s.nbLost} lost · ${s.winRateValue} by value`} /></div>
      </div>

      <Section right={<SplitLegend note="won ACV per quarter · services excluded" />}>By region</Section>
      <div className={cn('mb-5 grid gap-3', chartRegions.length > 2 ? 'sm:grid-cols-2 xl:grid-cols-4' : 'sm:grid-cols-2')}>
        {chartRegions.map((r) => {
          const rs = stats(f.period === 'ytd' ? deals.filter((d) => d.region === r) : deals.filter((d) => d.region === r && d.quarter === f.period))
          const rnValue = sum(rs.renewals, (d) => d.value_usd)
          return (
            <Card key={r} className={cn('px-4 py-3', f.region === r && 'border-ink')}>
              <button onClick={() => setF({ ...f, region: f.region === r ? '' : r })} className="flex w-full items-baseline gap-2 text-left">
                <span className="text-[15px] font-semibold">{REGION_LABEL[r] ?? r}</span>
                <span className="ml-auto text-[13px] tabular-nums" title="new business plus renewals won">{usd(rs.nbValue + rnValue)}</span>
              </button>
              <div className="mt-3 flex h-[132px] items-end gap-2 border-b border-line">
                {quarters.map((qq) => {
                  const sp = wonSplit(cell(qq, r)), v = sp.nbV + sp.rnV
                  const on = f.period === 'ytd' || f.period === qq
                  return (
                    <button key={qq} onClick={() => setF({ ...f, period: f.period === qq ? 'ytd' : qq, region: r })}
                      title={`${REGION_LABEL[r] ?? r} · ${toDate(qq)}: ${usd(v)} won\nNew business ${usd(sp.nbV)} from ${sp.nb.length} deals (${pct(sp.nbV, v)})\nRenewals ${usd(sp.rnV)} from ${sp.rn.length} deals (${pct(sp.rnV, v)})`}
                      className="group flex h-full flex-1 flex-col items-center justify-end">
                      <span className="mb-1 text-[11.5px] tabular-nums text-ink">{v ? usd(v) : '—'}</span>
                      {v > 0 && <span className={cn('flex w-full max-w-10 flex-col-reverse border border-ink/40 group-hover:border-ink', !on && 'opacity-30')}>
                        <span className={NEW_BAR} style={{ height: `${barH(sp.nbV)}px` }} />
                        <span className={RENEWAL_BAR} style={{ height: `${barH(sp.rnV)}px` }} />
                      </span>}
                    </button>)
                })}
              </div>
              <div className="mt-1 flex gap-2">{quarters.map((qq) => <span key={qq} className="flex-1 text-center text-[11.5px] text-ink3">{qq.slice(0, 2)}</span>)}</div>
              <div className="mt-2 text-[12px] text-ink3">New business {usd(rs.nbValue)} ({rs.nbWon}) · renewals {usd(rnValue)} ({rs.renewals.length}) · win rate {rs.winRate}</div>
            </Card>)
        })}
      </div>

      <Section>Quarter by region</Section>
      <Card className="mb-5 overflow-x-auto px-3 py-1">
        <table className="w-full border-collapse text-[13px]">
          <thead><tr className="text-left text-[12px] [&>th]:whitespace-nowrap [&>th]:border-b [&>th]:border-line [&>th]:px-2 [&>th]:py-2 [&>th]:font-semibold">
            <th>Quarter</th><th>Region</th><th className="text-right">Won</th><th className="text-right">New business</th><th className="text-right max-md:hidden">New logos</th>
            <th className="text-right">Renewals</th><th className="text-right max-md:hidden">Services</th><th className="text-right">Net ARR</th><th className="text-right">Win rate</th></tr></thead>
          <tbody className="[&>tr>td]:border-b [&>tr>td]:border-line2 [&>tr>td]:px-2 [&>tr>td]:py-1.5 [&>tr>td]:tabular-nums">
            {[...quarters].reverse().flatMap((qq) => {
              const rows = (f.region ? [f.region] : regions).filter((r) => cell(qq, r).length)
              const line = (key: string, label: string, l: ClosedDeal[], total = false) => { const x = stats(l); return (
                <tr key={key} className={cn(total && 'font-semibold', (f.period === qq) && 'bg-panel2')}>
                  <td className="whitespace-nowrap">{total || rows.length === 1 ? toDate(qq) : ''}</td><td className={cn(!total && rows.length > 1 && 'pl-5')}>{label}</td>
                  <td className="text-right">{x.won}</td><td className="text-right">{usd(x.nbValue)}</td><td className="text-right max-md:hidden">{x.newLogos}</td>
                  <td className="text-right">{usd(sum(x.renewals, (d) => d.value_usd))}</td><td className="text-right max-md:hidden">{usd(sum(x.services, (d) => d.value_usd))}</td>
                  <td className="text-right">{signed(x.netArr)}</td><td className="text-right">{x.winRate}</td></tr>) }
              if (rows.length === 1) return [line(qq + rows[0], REGION_LABEL[rows[0]] ?? rows[0], cell(qq, rows[0]))]
              return [line(qq + 'all', 'All regions', deals.filter((d) => d.quarter === qq), true), ...rows.map((r) => line(qq + r, REGION_LABEL[r] ?? r, cell(qq, r)))]
            })}
          </tbody>
          {/* Totals across every quarter shown: overall, then per region (only the selected region when filtered) */}
          <tfoot className="[&>tr>td]:px-2 [&>tr>td]:py-1.5 [&>tr>td]:tabular-nums">
            {(() => {
              const rs = (f.region ? [f.region] : regions).filter((r) => deals.some((d) => d.region === r))
              const all = f.region ? deals.filter((d) => d.region === f.region) : deals
              const line = (key: string, first: string, label: string, l: ClosedDeal[], strong: boolean) => { const x = stats(l); return (
                <tr key={key} className={cn(strong ? 'font-semibold [&>td]:border-t-2 [&>td]:border-ink' : '[&>td]:border-t [&>td]:border-line2')}>
                  <td className="whitespace-nowrap">{first}</td><td className={cn(!strong && 'pl-5')}>{label}</td>
                  <td className="text-right">{x.won}</td><td className="text-right">{usd(x.nbValue)}</td><td className="text-right max-md:hidden">{x.newLogos}</td>
                  <td className="text-right">{usd(sum(x.renewals, (d) => d.value_usd))}</td><td className="text-right max-md:hidden">{usd(sum(x.services, (d) => d.value_usd))}</td>
                  <td className="text-right">{signed(x.netArr)}</td><td className="text-right">{x.winRate}</td></tr>) }
              const span = quarters.length > 1 ? `${quarters[0]} – ${toDate(lastQ).replace(' to date', '')}` : quarters[0]
              return [line('total', `Total · ${span}`, f.region ? REGION_LABEL[f.region] ?? f.region : 'All regions', all, true),
                ...(rs.length > 1 ? rs.map((r) => line('total' + r, '', REGION_LABEL[r] ?? r, deals.filter((d) => d.region === r), false)) : [])]
            })()}
          </tfoot>
        </table>
      </Card>

      <Section>Deals</Section>
      <FilterBar search={search} onSearch={setSearch} placeholder="Search account, use case…"
        tokens={f.kind ? [{ label: f.kind, onRemove: () => setF({ ...f, kind: '' }) }] : []}
        right={<Segmented value={f.outcome} onChange={(v) => setF({ ...f, outcome: v })}
          options={(['won', 'lost'] as const).map((k) => [k, `${k === 'won' ? 'Won' : 'Lost'} · ${scoped.filter((d) => d.won === (k === 'won')).length}`] as ['won' | 'lost', string])} />}>
        <FilterRow label="Type">{(['', 'New business', 'Renewal', 'Services'] as const).map((k) => <Opt key={k || 'all'} on={f.kind === k} onClick={() => setF({ ...f, kind: k })}>{k || 'All'}</Opt>)}</FilterRow>
        <FilterRow label="Sort">{(['value', 'date', 'net'] as Sort[]).map((k) => <Opt key={k} on={sort === k} onClick={() => setSort(k)}>{k === 'date' ? 'Close date' : k === 'value' ? 'Value' : 'Net ARR'}</Opt>)}</FilterRow>
      </FilterBar>
      {list.length === 0 ? <Empty>No deals match.</Empty> : (
        <Card className="overflow-x-auto px-3 py-1">
          <table className="w-full border-collapse text-[13px]">
            <thead><tr className="text-left text-[12px] [&>th]:border-b [&>th]:border-line [&>th]:px-2 [&>th]:py-2 [&>th]:font-semibold">
              <th>Closed</th><th>Account</th><th className="max-md:hidden">Type</th><th>Region</th><th className="text-right">Value</th><th className="text-right">Net ARR</th><th className="text-right max-md:hidden">Cycle</th><th className="max-md:hidden">Use case</th></tr></thead>
            <tbody className="[&>tr>td]:border-b [&>tr>td]:border-line2 [&>tr>td]:px-2 [&>tr>td]:py-2 [&>tr>td]:align-top">
              {list.slice(0, 300).map((d) => (
                <tr key={d.id} className="hover:bg-panel2">
                  <td className="whitespace-nowrap">{fmtDate(d.close_date)}</td>
                  <td>{orgId.get(d.account) ? <button onClick={() => viewEntity('org', orgId.get(d.account)!)} title="Open the account: deals, people, open items and every mail and meeting" className="text-left font-semibold underline decoration-accent decoration-2 underline-offset-2">{d.account}</button>
                    : d.url ? <a href={d.url} target="_blank" rel="noreferrer">{d.account}</a> : <b>{d.account}</b>}
                    {d.url && orgId.get(d.account) && <a href={d.url} target="_blank" rel="noreferrer" className="ml-1.5 text-[12px]">SF ↗</a>}</td>
                  <td className="max-md:hidden whitespace-nowrap">{d.sale_type}{d.kind === 'Services' && <span className="text-ink3"> · services</span>}</td>
                  <td>{d.region}</td>
                  <td className="whitespace-nowrap text-right tabular-nums"><b>{usd(d.value_usd)}</b>{d.currency !== 'USD' && <div className="text-[12px] text-ink3">{local(d.acv, d.currency)}</div>}</td>
                  <td className="whitespace-nowrap text-right tabular-nums">{d.won ? signed(d.net_usd) : '—'}</td>
                  <td className="max-md:hidden whitespace-nowrap text-right tabular-nums text-ink2">{d.cycle_days != null && d.cycle_days >= 0 ? `${d.cycle_days} d` : '—'}</td>
                  <td className="max-md:hidden text-[12.5px] text-ink2">{d.use_case || '—'}</td>
                </tr>))}
            </tbody>
          </table>
          {list.length > 300 && <Muted className="px-2 py-2">First 300 of {list.length}.</Muted>}
        </Card>)}

    </div>
  )
}

function quarterEnd(q: string) {
  const m = /^Q(\d) (\d{4})$/.exec(q)
  if (!m) return ''
  return new Date(Date.UTC(+m[2], +m[1] * 3, 0)).toISOString().slice(0, 10)
}
