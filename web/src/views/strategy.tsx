// Not routed since 29 Oct 2026 (Sam: "we don't need it"; /strategy redirects to Initiatives). Kept to bring back.
// Strategy: the strategy agent's memo (assist/strategy.py). Macro-level thoughts to think with in meetings and
// conversations, not actions: bets, risks, tensions, opportunities and open questions, each with its evidence, what it
// means, questions to bring and where to raise it. Written weekly by the refresh, or on demand. Nothing here sends.
import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Compass, Eye, Loader2, MessageCircleQuestion, Pin, RefreshCw, Scale, ShieldAlert, Sparkles, TrendingUp, X } from 'lucide-react'
import { api, type StrategyThought } from '@/lib/api'
import { useAgents } from '@/lib/agents'
import { cn } from '@/lib/util'
import { Loading } from '@/components/ui'
import { FilterBar, FilterRow, Opt } from '@/components/FilterBar'
import { TZ, LOCALE } from '@/lib/time'

const TYPE: Record<string, { label: string; icon: typeof Compass; cls: string }> = {
  bet: { label: 'Bet', icon: Compass, cls: 'border-ink' },
  risk: { label: 'Risk', icon: ShieldAlert, cls: 'border-hot text-hot' },
  tension: { label: 'Tension', icon: Scale, cls: 'border-ink' },
  opportunity: { label: 'Opportunity', icon: TrendingUp, cls: 'border-ink bg-accent text-onaccent' },
  question: { label: 'Question', icon: MessageCircleQuestion, cls: 'border-ink' },
}
const fmt = (s: string) => new Date(s).toLocaleString(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

function Thought({ t, i, mark, onMark }: { t: StrategyThought; i: number; mark?: string; onMark: (m: string) => void }) {
  const T = TYPE[t.type] ?? TYPE.question
  const [open, setOpen] = useState(i < 3 || mark === 'pinned')
  return (
    <article className={cn('border bg-panel', mark === 'pinned' ? 'border-ink shadow-[4px_4px_0_0_var(--ink)]' : 'border-line', mark === 'dismissed' && 'opacity-50')}>
      <header className="flex items-start gap-3 px-5 pt-4">
        <span className={cn('mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px] font-medium', T.cls)}><T.icon size={12} />{T.label}</span>
        <button onClick={() => setOpen(!open)} className="min-w-0 flex-1 text-left">
          <h2 className="text-[16.5px] font-semibold leading-snug">{t.title}</h2>
          <div className="mt-0.5 text-[12px] text-ink2">{t.horizon} · {t.confidence} confidence{mark === 'discussed' ? ' · discussed' : ''}</div>
        </button>
        <div className="flex shrink-0 items-center gap-1">
          <button onClick={() => onMark(mark === 'pinned' ? '' : 'pinned')} title={mark === 'pinned' ? 'Unpin' : 'Pin: keep this in view'} aria-label="Pin"
            className={cn('grid size-7 place-items-center border', mark === 'pinned' ? 'border-ink bg-accent text-onaccent' : 'border-line hover:border-ink')}><Pin size={13} /></button>
          <button onClick={() => onMark(mark === 'discussed' ? '' : 'discussed')} title="Mark as discussed" aria-label="Discussed"
            className={cn('grid size-7 place-items-center border', mark === 'discussed' ? 'border-ink bg-ink text-bg' : 'border-line hover:border-ink')}><Eye size={13} /></button>
          <button onClick={() => onMark(mark === 'dismissed' ? '' : 'dismissed')} title="Not useful: dismiss" aria-label="Dismiss"
            className={cn('grid size-7 place-items-center border', mark === 'dismissed' ? 'border-hot text-hot' : 'border-line hover:border-hot')}><X size={13} /></button>
        </div>
      </header>
      {open ? (
        <div className="px-5 pb-4 pt-2 text-[14px] leading-relaxed">
          <p>{t.thesis}</p>
          {t.implications && <p className="mt-2.5"><b className="font-semibold">What it means: </b>{t.implications}</p>}
          {t.questions?.length > 0 && (
            <div className="mt-3 border-l-2 border-accent bg-panel2 px-3 py-2">
              <div className="mb-1 text-[12.5px] font-semibold">Questions to bring</div>
              <ul className="list-disc space-y-0.5 pl-5 text-[13.5px]">{t.questions.map((q) => <li key={q}>{q}</li>)}</ul>
            </div>)}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px]">
            {t.raise_with?.length > 0 && <span><span className="text-ink2">Raise with </span>{t.raise_with.join(' · ')}</span>}
            {t.sources?.length > 0 && <span className="flex flex-wrap items-center gap-1.5"><span className="text-ink2">Evidence</span>
              {t.sources.map((s) => <a key={s.code} href={s.url} className="rounded-full border border-line px-2 py-px text-ink no-underline hover:border-ink">{s.label}</a>)}</span>}
          </div>
        </div>
      ) : <button onClick={() => setOpen(true)} className="block w-full px-5 pb-3 pt-1 text-left text-[13px] text-ink2 line-clamp-1">{t.thesis}</button>}
    </article>
  )
}

// head: what sits in place of the title (it was the Initiatives | Strategy switch, 23 to 29 Oct 2026)
export function Strategy({ head }: { head?: ReactNode } = {}) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['strategy'], queryFn: api.strategy })
  const agents = useAgents()
  const running = agents.data?.running.some((r) => r.key === 'strategy')
  const [pick, setPick] = useState(0)
  const [filter, setFilter] = useState('')
  const run = useMutation({ mutationFn: () => api.agentRun('strategy'), onSettled: () => qc.invalidateQueries({ queryKey: ['agents'] }) })
  const mark = useMutation({
    mutationFn: ({ id, index, m }: { id: number; index: number; m: string }) => api.strategyMark(id, index, m),
    onSettled: () => qc.invalidateQueries({ queryKey: ['strategy'] }),
  })
  // when the agent finishes, show the new memo
  const [wasRunning, setWasRunning] = useState(false)
  if (running && !wasRunning) setWasRunning(true)
  if (!running && wasRunning) { setWasRunning(false); qc.invalidateQueries({ queryKey: ['strategy'] }); setPick(0) }
  if (!q.data) return <Loading />
  const memos = q.data.memos
  const cur = memos[pick]
  const thoughts = (cur?.memo.thoughts ?? []).map((t, i) => ({ t, i, mark: cur.marks[String(i)] }))
  const order = (m?: string) => (m === 'pinned' ? 0 : m === 'dismissed' ? 3 : m === 'discussed' ? 2 : 1)
  const shown = thoughts.filter((x) => !filter || x.t.type === filter).sort((a, b) => order(a.mark) - order(b.mark) || a.i - b.i)
  const types = [...new Set(thoughts.map((x) => x.t.type))]

  return (
    <div className="max-w-[920px]">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        {head ? <><h1 className="sr-only">Strategy</h1>{head}</> : <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Strategy</h1>}
        {memos.length === 1 && cur && <span className="text-[13px] text-ink2">{fmt(cur.created_at)}</span>}
        {memos.length > 1 && <select value={pick} onChange={(e) => setPick(Number(e.target.value))} aria-label="Memo" className="border border-line bg-panel px-2 py-1 text-[12.5px] text-ink">
          {memos.map((m, k) => <option key={m.id} value={k}>{k === 0 ? 'Latest · ' : ''}{fmt(m.created_at)}</option>)}</select>}
        <button onClick={() => run.mutate()} disabled={running || run.isPending}
          className="ml-auto inline-flex items-center gap-1.5 border border-accent bg-accent px-3 py-1.5 text-[13px] font-medium text-onaccent hover:brightness-95 disabled:opacity-60">
          {running ? <Loader2 size={14} className="animate-spin" /> : cur ? <RefreshCw size={14} /> : <Sparkles size={14} />}{running ? 'Thinking… a few minutes' : cur ? 'Regenerate' : 'Write the first memo'}</button>
      </div>
      {run.isError && <p className="mb-3 text-[12.5px] text-hot">{String(run.error).replace(/^Error: /, '')}</p>}

      {!cur ? <div className="border border-dashed border-line px-5 py-8 text-center text-[13.5px] text-ink2">{running ? 'Writing the first memo…' : 'No memo yet.'}</div> : <>
        <section className="mb-5 border-l-4 border-accent bg-panel px-5 py-4">
          <div className="mb-1 text-[12px] font-semibold text-ink2">The picture this week</div>
          <p className="text-[16px] leading-relaxed">{cur.memo.headline}</p>
        </section>
        {types.length > 1 && <FilterBar tokens={filter ? [{ label: (TYPE[filter] ?? TYPE.question).label, onRemove: () => setFilter('') }] : []}
          right={<span>{shown.length === thoughts.length ? `${thoughts.length} thoughts` : `${shown.length} of ${thoughts.length}`}</span>}>
          <FilterRow label="Type">
            <Opt on={!filter} onClick={() => setFilter('')}>All</Opt>
            {types.map((k) => <Opt key={k} on={filter === k} onClick={() => setFilter(filter === k ? '' : k)} count={thoughts.filter((x) => x.t.type === k).length}>{(TYPE[k] ?? TYPE.question).label}</Opt>)}
          </FilterRow>
        </FilterBar>}
        <div className="space-y-3">{shown.map(({ t, i, mark: m }) => <Thought key={`${cur.id}-${i}`} t={t} i={i} mark={m} onMark={(v) => mark.mutate({ id: cur.id, index: i, m: v })} />)}</div>
        {cur.memo.watch?.length > 0 && (
          <section className="mt-6">
            <h2 className="mb-2 text-[15px] font-semibold">Signals to watch</h2>
            <ul className="space-y-1.5 border border-line bg-panel px-5 py-3 text-[13.5px]">{cur.memo.watch.map((w) => <li key={w} className="flex gap-2"><Eye size={14} className="mt-0.5 shrink-0 text-ink2" />{w}</li>)}</ul>
          </section>)}
      </>}
    </div>
  )
}
