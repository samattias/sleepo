// Pipeline: open Salesforce opportunities (company and deal data only), focused on the current quarter, and a Closed
// deals tab (pipeline-closed.tsx) looking back at wins and losses since Q1 2026.
// Values are converted to approximate USD with the rates the data itself implies; owners and contacts are never stored.
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type PipelineRow } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { Card, Empty, Loading, Muted, PageTabs, Section, selectClass, Tag, Tile } from '@/components/ui'
import { viewEntity } from '@/components/EntityPanel'
import { FilterBar, FilterRow, Opt, Segmented } from '@/components/FilterBar'
import { ClosedDeals, fmtDate, local, NEW_BAR, RENEWAL_BAR, SplitLegend, usd } from './pipeline-closed'

const NEW_BIZ = new Set(['New Logo', 'Upsell', 'Cross Sell'])

function qOf(d: Date) { return `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}` }
function nextQ(d: Date) { const n = new Date(d.getFullYear(), d.getMonth() + 3, 1); return qOf(n) }

type Col = 'close' | 'account' | 'type' | 'stage' | 'prob' | 'acv' | 'weighted' | 'forecast' | 'region' | 'use'
const PROB = [[0, 'Any'], [25, '25%+'], [50, '50%+'], [75, '75%+'], [90, '90%+']] as const
const MINV = [[0, 'Any value'], [10000, '$10k+'], [50000, '$50k+'], [100000, '$100k+'], [250000, '$250k+']] as const
const sel = selectClass

export function Pipeline() {
  const [saved, setTab] = usePersisted<'open' | 'closed'>('assist-pipeline-tab', 'open')
  const [linked, setLinked] = useState(() => new URLSearchParams(location.hash.split('?')[1] ?? '').get('tab'))   // #/pipeline?tab=closed links straight to the history
  const tab = linked === 'closed' || linked === 'open' ? linked : saved
  return (
    <div>
      <PageTabs title="Pipeline" label="Pipeline views" active={tab} onSelect={(k) => { setLinked(null); setTab(k) }}
        tabs={[{ key: 'open', label: 'Open pipeline' }, { key: 'closed', label: 'Closed deals' }]} />
      {tab === 'open' ? <OpenPipeline /> : <ClosedDeals />}
    </div>
  )
}

function OpenPipeline() {
  const q = useQuery({ queryKey: ['pipeline'], queryFn: api.pipeline })
  const orgs = useQuery({ queryKey: ['orgs'], queryFn: api.orgs, staleTime: 300_000 })
  const orgId = useMemo(() => new Map((orgs.data ?? []).map((o) => [o.name, o.id] as [string, number])), [orgs.data])
  const thisQ = qOf(new Date()), nq = nextQ(new Date())
  const [f0, setF] = usePersisted('assist-pipeline', { period: 'this' as 'this' | 'next' | 'overdue' | 'all', type: '' as '' | 'new' | 'renewal', region: '', stage: '',
    probMin: 0, minValue: 0, forecast: '', saleType: '', useCase: '' })
  const f = Object.assign({ probMin: 0, minValue: 0, forecast: '', saleType: '', useCase: '' }, f0)   // older saved filters lack the new keys
  const [search, setSearch] = useState('')
  const [order, setOrder] = usePersisted<{ col: Col; desc: boolean }>('assist-pipeline-order', { col: 'close', desc: false })
  const sortBy = (col: Col) => setOrder(order.col === col ? { col, desc: !order.desc } : { col, desc: ['prob', 'acv', 'weighted', 'stage'].includes(col) })
  const rows = q.data?.opportunities ?? []
  const regions = useMemo(() => [...new Set(rows.map((r) => r.region).filter(Boolean))].sort(), [rows])

  const list = useMemo(() => {
    let l = rows
    if (f.period === 'this') l = l.filter((r) => r.quarter === thisQ)
    if (f.period === 'next') l = l.filter((r) => r.quarter === nq)
    if (f.period === 'overdue') l = l.filter((r) => r.overdue || r.odd_date)
    if (f.type === 'new') l = l.filter((r) => NEW_BIZ.has(r.sale_type))
    if (f.type === 'renewal') l = l.filter((r) => r.sale_type === 'Renewal')
    if (f.region) l = l.filter((r) => r.region === f.region)
    if (f.stage) l = l.filter((r) => r.stage === f.stage)
    if (f.probMin) l = l.filter((r) => (r.probability ?? 0) >= f.probMin)
    if (f.minValue) l = l.filter((r) => r.acv_usd >= f.minValue)
    if (f.forecast) l = l.filter((r) => (r.forecast_category || '—') === f.forecast)
    if (f.saleType) l = l.filter((r) => r.sale_type === f.saleType)
    if (f.useCase) l = l.filter((r) => (r.use_case || '—') === f.useCase)
    if (search.trim()) { const re = new RegExp(search.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'); l = l.filter((r) => re.test([r.account, r.name, r.use_case, r.stage].join(' '))) }
    const txt = (a: string, b: string) => (a || '~').localeCompare(b || '~')
    const by: Record<Col, (a: PipelineRow, b: PipelineRow) => number> = {
      close: (a, b) => (a.close_date || '9').localeCompare(b.close_date || '9'), account: (a, b) => txt(a.account, b.account),
      type: (a, b) => txt(a.sale_type, b.sale_type), stage: (a, b) => a.stage_rank - b.stage_rank, prob: (a, b) => (a.probability ?? -1) - (b.probability ?? -1),
      acv: (a, b) => a.acv_usd - b.acv_usd, weighted: (a, b) => a.weighted_usd - b.weighted_usd, forecast: (a, b) => txt(a.forecast_category, b.forecast_category),
      region: (a, b) => txt(a.region, b.region), use: (a, b) => txt(a.use_case, b.use_case),
    }
    const cmp = by[order.col] ?? by.close
    return [...l].sort((a, b) => (order.desc ? -cmp(a, b) : cmp(a, b)) || b.acv_usd - a.acv_usd)
  }, [rows, f0, search, order, thisQ, nq])

  if (!q.data) return <Loading />
  const total = list.reduce((a, r) => a + r.acv_usd, 0)
  const weighted = list.reduce((a, r) => a + r.weighted_usd, 0)
  const commit = list.filter((r) => /commit|best case/i.test(r.forecast_category)).reduce((a, r) => a + r.acv_usd, 0)
  const newBiz = list.filter((r) => NEW_BIZ.has(r.sale_type))
  const stages = [...new Set(list.map((r) => r.stage))].sort((a, b) => (list.find((r) => r.stage === a)!.stage_rank) - (list.find((r) => r.stage === b)!.stage_rank))
  const maxStage = Math.max(1, ...stages.map((s) => list.filter((r) => r.stage === s).reduce((a, r) => a + r.acv_usd, 0)))
  const flagged = rows.filter((r) => r.overdue || r.odd_date).length
  const periodLabel = f.period === 'this' ? thisQ : f.period === 'next' ? nq : f.period === 'overdue' ? 'needing a date fix' : 'all open'
  // region split ignores the region filter so the comparison stays visible while one region is selected
  const regionBase = rows.filter(inScope)
  function inScope(r: PipelineRow) {
    if (f.period === 'this' && r.quarter !== thisQ) return false
    if (f.period === 'next' && r.quarter !== nq) return false
    if (f.period === 'overdue' && !(r.overdue || r.odd_date)) return false
    if (f.type === 'new' && !NEW_BIZ.has(r.sale_type)) return false
    if (f.type === 'renewal' && r.sale_type !== 'Renewal') return false
    return !f.stage || r.stage === f.stage
  }

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile value={String(list.length)} label={`deals · ${periodLabel}`} note={`${newBiz.length} new business · ${list.length - newBiz.length} renewals`} />
        <Tile value={usd(total)} label="total value (ACV)" note={`${usd(newBiz.reduce((a, r) => a + r.acv_usd, 0))} new business`} />
        <Tile value={usd(weighted)} label="weighted by probability" note={total ? `${Math.round((weighted / total) * 100)}% of total` : ''} />
        <Tile value={usd(commit)} label="commit or best case" note={`${list.filter((r) => /commit|best case/i.test(r.forecast_category)).length} deals forecast`} />
      </div>

      <FilterBar search={search} onSearch={setSearch} placeholder="Search account, use case…"
        right={<Segmented value={f.period} onChange={(v) => setF({ ...f, period: v })} options={[['this', thisQ], ['next', nq], ['overdue', `Fix date · ${flagged}`], ['all', 'All open']]} />}
        tokens={[
          ...(f.type ? [{ label: f.type === 'new' ? 'New business' : 'Renewals', onRemove: () => setF({ ...f, type: '' }) }] : []),
          ...(f.saleType ? [{ label: f.saleType, onRemove: () => setF({ ...f, saleType: '' }) }] : []),
          ...(f.region ? [{ label: f.region, onRemove: () => setF({ ...f, region: '' }) }] : []),
          ...(f.stage ? [{ label: f.stage, onRemove: () => setF({ ...f, stage: '' }) }] : []),
          ...(f.probMin ? [{ label: `Probability ${f.probMin}%+`, onRemove: () => setF({ ...f, probMin: 0 }) }] : []),
          ...(f.forecast ? [{ label: f.forecast, onRemove: () => setF({ ...f, forecast: '' }) }] : []),
          ...(f.minValue ? [{ label: MINV.find(([v]) => v === f.minValue)?.[1] ?? '', onRemove: () => setF({ ...f, minValue: 0 }) }] : []),
          ...(f.useCase ? [{ label: f.useCase, onRemove: () => setF({ ...f, useCase: '' }) }] : []),
        ]}
        onClear={() => setF({ ...f, probMin: 0, minValue: 0, forecast: '', saleType: '', useCase: '', stage: '', region: '', type: '' })}>
        <FilterRow label="Business">{([['', 'All'], ['new', 'New business'], ['renewal', 'Renewals']] as const).map(([k, l]) => <Opt key={l} on={f.type === k} onClick={() => setF({ ...f, type: k })}>{l}</Opt>)}</FilterRow>
        <FilterRow label="Region"><Opt on={!f.region} onClick={() => setF({ ...f, region: '' })}>All</Opt>{regions.map((r) => <Opt key={r} on={f.region === r} onClick={() => setF({ ...f, region: f.region === r ? '' : r })}>{r}</Opt>)}</FilterRow>
        <FilterRow label="Probability">{PROB.map(([v, l]) => <Opt key={v} on={f.probMin === v} onClick={() => setF({ ...f, probMin: v })}>{l}</Opt>)}</FilterRow>
        <FilterRow label="Value">{MINV.map(([v, l]) => <Opt key={v} on={f.minValue === v} onClick={() => setF({ ...f, minValue: v })}>{l}</Opt>)}</FilterRow>
        <FilterRow label="More">
          <select aria-label="Forecast category" value={f.forecast} onChange={(e) => setF({ ...f, forecast: e.target.value })} className={sel}>
            <option value="">Any forecast</option>{[...new Set(rows.map((r) => r.forecast_category || '—'))].sort().map((x) => <option key={x} value={x}>{x}</option>)}</select>
          <select aria-label="Deal type" value={f.saleType} onChange={(e) => setF({ ...f, saleType: e.target.value })} className={sel}>
            <option value="">Any deal type</option>{[...new Set(rows.map((r) => r.sale_type).filter(Boolean))].sort().map((x) => <option key={x} value={x}>{x}</option>)}</select>
          <select aria-label="Stage" value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })} className={sel}>
            <option value="">Any stage</option>{[...new Set(rows.map((r) => r.stage))].sort((a, b) => (rows.find((r) => r.stage === a)!.stage_rank) - (rows.find((r) => r.stage === b)!.stage_rank)).map((x) => <option key={x} value={x}>{x}</option>)}</select>
          <select aria-label="Use case" value={f.useCase} onChange={(e) => setF({ ...f, useCase: e.target.value })} className={cn(sel, 'max-w-[200px]')}>
            <option value="">Any use case</option>{[...new Set(rows.map((r) => r.use_case || '—'))].sort().map((x) => <option key={x} value={x}>{x}</option>)}</select>
        </FilterRow>
      </FilterBar>

      {list.length > 0 && <div className="mb-5 grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div>
          <Section right={<SplitLegend />}>By stage</Section>
          <Card className="px-4 py-2">
            {stages.map((s) => {
              const ss = list.filter((r) => r.stage === s), nb = ss.filter((r) => NEW_BIZ.has(r.sale_type))   // as in the tiles: anything not new business counts as renewal
              const v = ss.reduce((a, r) => a + r.acv_usd, 0), nbV = nb.reduce((a, r) => a + r.acv_usd, 0), rnV = v - nbV
              const k = v ? Math.max(2, (v / maxStage) * 100) / v : 0   // % of track per dollar, keeping a sliver for tiny stages
              return (
              <button key={s} onClick={() => setF({ ...f, stage: f.stage === s ? '' : s })} className={cn('grid w-full grid-cols-[150px_1fr_110px] items-center gap-3 py-1.5 text-left text-[13px]', f.stage === s && 'font-semibold')}
                title={`${s || '—'}: ${usd(v)} from ${ss.length} deals\nNew business ${usd(nbV)} from ${nb.length} deals\nRenewals ${usd(rnV)} from ${ss.length - nb.length} deals`}>
                <span className="truncate">{s || '—'}</span>
                <span className="flex h-2.5 bg-panel2"><span className={cn('block h-full', NEW_BAR)} style={{ width: `${nbV * k}%` }} /><span className={cn('block h-full', RENEWAL_BAR)} style={{ width: `${rnV * k}%` }} /></span>
                <span className="text-right tabular-nums">{usd(v)} · {ss.length}</span>
              </button>) })}
            {f.stage && <div className="pt-1 text-[12px] text-ink2">Filtered to {f.stage}. <button onClick={() => setF({ ...f, stage: '' })} className="underline">Clear</button></div>}
          </Card>
        </div>
        <div>
          <Section>By type</Section>
          <Card className="px-4 py-2">
            {['New Logo', 'Upsell', 'Cross Sell', 'Renewal'].map((t) => { const tt = list.filter((r) => r.sale_type === t); if (!tt.length) return null; return (
              <div key={t} className="flex items-center gap-3 py-1.5 text-[13px]"><span className="flex-1">{t}</span><span className="tabular-nums text-ink2">{tt.length} deals</span><span className="w-20 text-right tabular-nums">{usd(tt.reduce((a, r) => a + r.acv_usd, 0))}</span></div>) })}
          </Card>
        </div>
        <div>
          <Section>By region</Section>
          <Card className="px-4 py-2">
            {[...new Set(regionBase.map((r) => r.region))].sort((a, b) => regionBase.filter((r) => r.region === b).reduce((x, r) => x + r.acv_usd, 0) - regionBase.filter((r) => r.region === a).reduce((x, r) => x + r.acv_usd, 0)).map((g) => {
              const gg = regionBase.filter((r) => r.region === g); return (
                <button key={g || '—'} onClick={() => setF({ ...f, region: f.region === g ? '' : g })} className={cn('flex w-full items-center gap-3 py-1.5 text-left text-[13px]', f.region === g && 'font-semibold')}>
                  <span className="flex-1">{g || '—'}</span><span className="whitespace-nowrap tabular-nums text-ink2">{gg.length} deals</span>
                  <span className="text-right tabular-nums" title="total value · weighted by probability">{usd(gg.reduce((a, r) => a + r.acv_usd, 0))}<span className="block text-[11.5px] text-ink3">{usd(gg.reduce((a, r) => a + r.weighted_usd, 0))} weighted</span></span></button>) })}
          </Card>
        </div>
      </div>}

      <Section right={<span className="text-[12.5px] text-ink2">Click a column to sort · again to reverse</span>}>Deals · {list.length}</Section>
      {list.length === 0 ? <Empty>No open deals match.</Empty> : (
        <Card className="overflow-x-auto px-3 py-1">
          <table className="w-full border-collapse text-[13px]">
            <thead><tr className="text-left text-[12px] text-ink2 [&>th]:border-b [&>th]:border-line [&>th]:px-2 [&>th]:py-2 [&>th]:font-semibold">
              {([['close', 'Close', ''], ['account', 'Account', ''], ['type', 'Type', 'max-md:hidden'], ['stage', 'Stage', ''], ['prob', 'Prob.', 'text-right'], ['acv', 'Value', 'text-right'],
                 ['weighted', 'Weighted', 'text-right max-md:hidden'], ['forecast', 'Forecast', 'max-lg:hidden'], ['region', 'Region', 'max-md:hidden'], ['use', 'Use case', 'max-lg:hidden']] as [Col, string, string][]).map(([k, l, c]) => (
                <th key={k} className={cn('cursor-pointer select-none whitespace-nowrap hover:text-ink', c, order.col === k && 'text-ink')} onClick={() => sortBy(k)} aria-sort={order.col === k ? (order.desc ? 'descending' : 'ascending') : 'none'}>
                  {l}{order.col === k ? (order.desc ? ' ↓' : ' ↑') : ''}</th>))}</tr></thead>
            <tbody className="[&>tr>td]:border-b [&>tr>td]:border-line2 [&>tr>td]:px-2 [&>tr>td]:py-2 [&>tr>td]:align-top">
              {list.slice(0, 400).map((r) => (
                <tr key={r.id} className="hover:bg-panel2">
                  <td className="whitespace-nowrap">{fmtDate(r.close_date)}{r.overdue && <div className="mt-0.5"><Tag tone="pending">date passed</Tag></div>}{r.odd_date && <div className="mt-0.5"><Tag tone="pending">check date</Tag></div>}</td>
                  <td>{orgId.get(r.account) ? <button onClick={() => viewEntity('org', orgId.get(r.account)!)} title="Open the account: deals, people, open items and every mail and meeting" className="text-left font-semibold underline decoration-accent decoration-2 underline-offset-2">{r.account}</button>
                    : r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.account}</a> : <b>{r.account}</b>}
                    {r.url && orgId.get(r.account) && <a href={r.url} target="_blank" rel="noreferrer" className="ml-1.5 text-[12px]">SF ↗</a>}</td>
                  <td className="max-md:hidden whitespace-nowrap">{r.sale_type}</td>
                  <td className="whitespace-nowrap">{r.stage}</td>
                  <td className="text-right tabular-nums">{r.probability != null ? `${r.probability}%` : '—'}</td>
                  <td className="whitespace-nowrap text-right tabular-nums"><b>{usd(r.acv_usd)}</b>{r.currency !== 'USD' && <div className="text-[12px] text-ink2">{local(r.acv, r.currency)}</div>}</td>
                  <td className="max-md:hidden whitespace-nowrap text-right tabular-nums text-ink2">{usd(r.weighted_usd)}</td>
                  <td className="max-lg:hidden whitespace-nowrap text-[12.5px]">{r.forecast_category || '—'}</td>
                  <td className="max-md:hidden">{r.region}</td>
                  <td className="max-lg:hidden text-[12.5px] text-ink2">{r.use_case || '—'}</td>
                </tr>))}
            </tbody>
          </table>
          {list.length > 400 && <Muted className="px-2 py-2">Showing the first 400 of {list.length}. Narrow the filters to see the rest.</Muted>}
        </Card>)}
    </div>
  )
}
