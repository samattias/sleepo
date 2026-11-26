// Action types: every kind of action Sam takes at work, and how he actually takes it (assist/action_profile.py), measured
// from his own mail, chat, calendar, meetings, documents and promises. The Actions list uses this to suggest the action
// types and channels he really uses, with the people he uses them with.
import { useState } from 'react'
import { AgentTabs } from '@/components/AgentTabs'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { api, type ActionType } from '@/lib/api'
import { cn } from '@/lib/util'
import { Loading } from '@/components/ui'
import { Segmented } from '@/components/FilterBar'

const HELP: Record<string, string> = { email: 'Drafts emails', teams: 'Drafts Teams messages', slack: 'Drafts Slack messages', create: 'Hands off to Claude', edit: 'Hands off to Claude', draft: 'Thinks it through in Claude', prep: 'Writes meeting briefs' }
const CATS = ['Communicate', 'Meet', 'Create', 'Decide', 'Delegate', 'Admin']
const hour = (h: number) => `${String(h).padStart(2, '0')}:00`
const ago = (s: string | null) => { if (!s) return '—'; const d = Math.round((Date.now() - new Date(s).getTime()) / 86400000); return d <= 0 ? 'today' : d === 1 ? 'yesterday' : `${d} d ago` }

function Spark({ weeks }: { weeks: number[] }) {
  const max = Math.max(1, ...weeks)
  return <span className="inline-flex h-5 items-end gap-[2px]" title={`Last 8 weeks: ${weeks.join(', ')}`}>{weeks.map((w, i) => <span key={i} className={cn('w-[5px]', i === weeks.length - 1 ? 'bg-accent ring-1 ring-ink/20' : 'bg-ink/70')} style={{ height: `${Math.max(2, (w / max) * 20)}px` }} />)}</span>
}

function Row({ t, max }: { t: ActionType; max: number }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-b border-line2 last:border-b-0">
      <button onClick={() => setOpen(!open)} className={cn('grid w-full grid-cols-[minmax(0,1fr)_120px_70px_90px_20px] items-center gap-3 px-4 py-2.5 text-left hover:bg-panel2 max-md:grid-cols-[minmax(0,1fr)_70px_20px]', !t.measured && 'text-ink2')}>
        <span className="min-w-0">
          <span className="block truncate text-[14px] font-medium">{t.name}</span>
          {t.sleepo && <span className="block truncate text-[11.5px] text-ink2">SleePO {HELP[t.sleepo]?.toLowerCase() ?? 'helps'}</span>}
          <span className="mt-1 block h-1 bg-panel2" style={{ width: 120 }}><span className="block h-full bg-accent" style={{ width: `${(t.count / max) * 100}%` }} /></span>
        </span>
        <span className="max-md:hidden"><Spark weeks={t.weeks} /></span>
        <span className="text-right tabular-nums"><b className="text-[15px]">{t.measured ? t.count : '—'}</b></span>
        <span className="text-right text-[12.5px] tabular-nums text-ink2 max-md:hidden">{t.measured ? `${t.per_week}/week` : 'not measured'}{t.trend != null && <span className={cn('ml-1', t.trend > 0 ? 'text-ink' : 'text-hot')}>{t.trend > 0 ? '↑' : '↓'}{Math.abs(t.trend)}%</span>}</span>
        <ChevronDown size={14} className={cn('text-ink3 transition-transform', !open && '-rotate-90')} />
      </button>
      {open && (
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 bg-panel2 px-4 py-2.5 text-[12.5px]">
          <dt className="text-ink2">Measured from</dt><dd>{t.how}</dd>
          {t.measured && <><dt className="text-ink2">Last</dt><dd>{ago(t.last)}</dd></>}
          {t.peak_days.length > 0 && <><dt className="text-ink2">Usually</dt><dd>{t.peak_days.join(', ')}{t.peak_hours.length ? ` · around ${t.peak_hours.map(hour).join(', ')}` : ''}</dd></>}
          {t.median_words != null && <><dt className="text-ink2">Length</dt><dd>about {t.median_words} words</dd></>}
          {t.people.length > 0 && <><dt className="text-ink2">Mostly with</dt><dd>{t.people.map((p) => `${p.name} (${p.count})`).join(', ')}</dd></>}
          {t.suggested != null && <><dt className="text-ink2">SleePO suggested</dt><dd>{t.suggested} in the same period</dd></>}
        </dl>)}
    </div>
  )
}

export function ActionTypes() {
  const [days, setDays] = useState<'30' | '60' | '90'>('30')
  const q = useQuery({ queryKey: ['actionProfile', days], queryFn: () => api.actionProfile(Number(days)) })
  if (!q.data) return <Loading />
  const { types, by_person } = q.data
  const max = Math.max(1, ...types.map((t) => t.count))
  const total = types.filter((t) => t.measured).reduce((a, t) => a + t.count, 0)
  return (
    <div className="max-w-[1000px]">
      <AgentTabs active="action-types" />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-ink2">{types.length} types · {total} actions in {days} days</span>
        <span className="ml-auto"><Segmented value={days} onChange={setDays} options={[['30', '30 days'], ['60', '60 days'], ['90', '90 days']]} /></span>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-4">
          {CATS.map((c) => { const rows = types.filter((t) => t.category === c); if (!rows.length) return null; return (
            <section key={c}>
              <h2 className="mb-1.5 text-[15px] font-semibold">{c} <span className="font-normal text-ink2">· {rows.reduce((a, t) => a + t.count, 0)}</span></h2>
              <div className="border border-line bg-panel">{rows.map((t) => <Row key={t.key} t={t} max={max} />)}</div>
            </section>) })}
        </div>
        <aside>
          <h2 className="mb-1.5 text-[15px] font-semibold">How you reach people</h2>
          <div className="border border-line bg-panel">
            {by_person.map((p) => { const tot = p.total; return (
              <div key={p.name} className="border-b border-line2 px-3 py-2 last:border-b-0">
                <div className="flex items-baseline gap-2 text-[13px]"><span className="min-w-0 flex-1 truncate font-medium">{p.name}</span><span className="text-[12px] text-ink2">{p.preferred}</span></div>
                <div className="mt-1 flex h-1.5 overflow-hidden bg-panel2">
                  {Object.entries(p.channels).map(([ch, n]) => <span key={ch} title={`${ch}: ${n}`} className={cn('h-full', ch === 'Email' ? 'bg-ink' : ch === 'Teams' ? 'bg-accent' : 'bg-ink/40')} style={{ width: `${(n / tot) * 100}%` }} />)}
                </div>
                <div className="mt-0.5 text-[11.5px] text-ink2">{Object.entries(p.channels).map(([ch, n]) => `${ch} ${n}`).join(' · ')}</div>
              </div>) })}
          </div>
          <div className="mt-1.5 flex gap-3 text-[11.5px] text-ink2"><span className="inline-flex items-center gap-1"><span className="size-2 bg-ink" />Email</span><span className="inline-flex items-center gap-1"><span className="size-2 bg-accent" />Teams</span><span className="inline-flex items-center gap-1"><span className="size-2 bg-ink/40" />Slack</span></div>
        </aside>
      </div>
    </div>
  )
}
