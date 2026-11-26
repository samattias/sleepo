// Check links: a sample of the links between items and people / organisations for Sam to tick or cross, and how good the
// linker is on his verdicts so far (assist/evals.py eval_links). Ticks and crosses here are the same verdicts as on the
// person timelines: a crossed link is hidden for good, and crossed first-name matches stop that first name being used.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Check, RefreshCw, X } from 'lucide-react'
import { api, type LinkSample } from '@/lib/api'
import { cn } from '@/lib/util'
import { btnClass, H1, Loading, Table } from '@/components/ui'
import { TZ, LOCALE } from '@/lib/time'

const ROLE: Record<string, string> = { from: 'sent it', author: 'wrote it', speaker: 'spoke in it', dm: 'in the DM', organizer: 'organised it', to: 'to', cc: 'cc',
  attendee: 'attended', invitee: 'invited', account: 'account', member: 'in the chat', domain: 'by mail domain', mentioned: 'mentioned', shared: 'shared it', owner: 'owner', discussed: 'discussed' }
const pct = (x: number | null | undefined) => (x == null ? '–' : `${Math.round(x * 100)}%`)
const day = (iso: string) => new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short' }).format(new Date(iso))

export function LinksPage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['links-review'], queryFn: () => api.linksReview(20) })
  const [done, setDone] = useState<Record<string, 'confirmed' | 'rejected'>>({})
  if (!q.data) return <Loading />
  const { sample, quality } = q.data
  const key = (s: LinkSample) => `${s.item_id}-${s.entity_type}-${s.entity_id}`
  const judge = async (s: LinkSample, v: 'confirmed' | 'rejected') => {
    setDone((d) => ({ ...d, [key(s)]: v }))
    await api.linkVerdict(s.item_id, s.entity_type, s.entity_id, v)
    qc.invalidateQueries({ queryKey: ['entity'] })
  }
  const roles = Object.entries(quality.precision).filter(([k]) => k !== 'all').sort((a, b) => b[1].reviewed - a[1].reviewed)
  const kinds = Object.entries(quality.coverage).sort((a, b) => b[1].items - a[1].items)
  return (
    <div className="max-w-[1000px]">
      <H1>Check links</H1>
      <p className="-mt-2 mb-4 max-w-[720px] text-[13.5px] text-ink2">Is each email, message and meeting linked to the right people and organisations? Tick the ones that are right and cross the wrong ones. Your answers measure the linker and teach it; a crossed link disappears everywhere.</p>
      <div className="mb-5 grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
        {[['Precision', pct(quality.precision.all?.precision), `${quality.precision.all?.reviewed ?? 0} links reviewed`],
          ['Recall', pct(quality.recall.recall), `${quality.recall.confirmed} confirmed links`],
          ['Found but hidden', String(quality.recall.hidden_right), 'right, below the threshold'],
          ['Email with a person', pct(quality.coverage.mail?.person), `${quality.coverage.mail?.items ?? 0} emails`]].map(([l, v, sub]) => (
          <div key={l} className="bg-panel px-4 py-3"><div className="text-[12px] text-ink2">{l}</div><div className="text-[24px] font-semibold tabular-nums">{v}</div><div className="text-[12px] text-ink2">{sub}</div></div>))}
      </div>
      <div className="mb-2 flex items-center gap-3">
        <h2 className="text-[15px] font-semibold">To check · {sample.length}</h2>
        <button onClick={() => { setDone({}); qc.invalidateQueries({ queryKey: ['links-review'] }) }} className={btnClass('outline', 'sm', 'ml-auto font-normal')}><RefreshCw size={13} />Next batch</button>
      </div>
      <div className="mb-6 border border-line bg-panel">
        {sample.map((s) => { const v = done[key(s)]; return (
          <div key={key(s)} className={cn('flex gap-3 border-b border-line2 px-3 py-2.5 last:border-b-0', v === 'rejected' && 'opacity-50')}>
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px]"><b>{s.name}</b> <span className="text-ink2">· {ROLE[s.role ?? ''] ?? s.role} · {s.label} {day(s.ts)}{s.from ? ` · ${s.from}` : ''}</span></div>
              <a href={s.url || undefined} target={s.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className="line-clamp-1 text-[13.5px] font-medium">{s.title || s.snippet || '(untitled)'}</a>
              {s.reason && <div className="line-clamp-2 text-[12px] italic text-ink2">{s.reason}</div>}
            </div>
            <div className="flex shrink-0 items-start gap-1">
              <button onClick={() => judge(s, 'confirmed')} aria-label="Right" title="Right" className={cn('border p-1', v === 'confirmed' ? 'border-ink bg-ink text-bg' : 'border-line hover:border-ink')}><Check size={14} /></button>
              <button onClick={() => judge(s, 'rejected')} aria-label="Wrong" title="Wrong" className={cn('border p-1', v === 'rejected' ? 'border-ink bg-ink text-bg' : 'border-line hover:border-ink')}><X size={14} /></button>
            </div>
          </div>) })}
        {sample.length === 0 && <div className="px-3 py-4 text-[13px] text-ink2">Nothing left to check from the last 90 days.</div>}
      </div>
      {roles.length > 0 && <section className="mb-6">
        <h2 className="mb-2 text-[15px] font-semibold">Precision by kind of link</h2>
        <Table head={<><th>Link</th><th className="text-right">Reviewed</th><th className="text-right">Right</th></>}>
          {roles.map(([k, r]) => <tr key={k}><td>{k.replace('person:', 'Person · ').replace('org:', 'Organisation · ')}</td><td className="text-right tabular-nums">{r.reviewed}</td><td className="text-right tabular-nums">{pct(r.precision)}</td></tr>)}
        </Table>
      </section>}
      <section>
        <h2 className="mb-2 text-[15px] font-semibold">Coverage: items with at least one link</h2>
        <Table head={<><th>Kind</th><th className="text-right">Items</th><th className="text-right">Person</th><th className="text-right">Organisation</th><th className="text-right">Initiative</th></>}>
          {kinds.map(([k, c]) => <tr key={k}><td>{k}</td><td className="text-right tabular-nums">{c.items}</td><td className="text-right tabular-nums">{pct(c.person)}</td><td className="text-right tabular-nums">{pct(c.org)}</td><td className="text-right tabular-nums">{pct(c.initiative)}</td></tr>)}
        </Table>
      </section>
    </div>
  )
}
