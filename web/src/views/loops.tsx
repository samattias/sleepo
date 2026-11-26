// Open items: one register of everything still open between Sam and other people (assist/loops.py), shared by the
// brief, the Actions list and meeting prep. Replies owed, decisions pending, what Sam owes, what is owed to him, each
// with the date it really started, who it is with, and its source. Items the assistant closed from evidence show the
// evidence and can be reopened; nothing is ever dropped automatically.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, Building2, Check, Copy, RotateCcw, Trash2, User, MessageSquareQuote } from 'lucide-react'
import { api, type Loop } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { btnClass, Empty, Loading, popoverClass } from '@/components/ui'
import { FilterBar, FilterRow, Opt, Segmented } from '@/components/FilterBar'
import { viewEntity } from '@/components/EntityPanel'
import { TZ, LOCALE } from '@/lib/time'

const KINDS: { key: Loop['kind']; label: string; note?: string }[] = [
  { key: 'reply', label: 'Replies owed', note: 'asked you something you have not answered' },
  { key: 'decision', label: 'Decisions', note: 'pending with you' },
  { key: 'promise', label: 'You owe', note: 'what you said you would do' },
  { key: 'waiting', label: 'Owed to you', note: 'candidates to chase' },
]
const day = (iso?: string | null) => { try { return iso ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short' }).format(new Date(iso.length === 10 ? iso + 'T12:00:00Z' : iso)) : '' } catch { return '' } }
// snooze = "keep it, not now": back on the list at 08:00 on the chosen day
function snoozeTimes() {
  const at = (days: number) => { const d = new Date(); d.setDate(d.getDate() + days); d.setHours(8, 0, 0, 0); return d.toISOString().replace(/\.\d+Z$/, 'Z') }
  const toMonday = (8 - new Date().getDay()) % 7 || 7
  return [{ label: 'Tomorrow 08:00', at: at(1) }, { label: 'Monday 08:00', at: at(toMonday) }, { label: 'In 2 weeks', at: at(14) }]
}
const BY: Record<string, string> = { sam: 'you', source: 'in its source list', 'auto:sent': 'you replied', 'auto:thread': 'newer message in the thread', 'auto:review': 'found in the evidence', 'auto:filter': 'not from someone you work with', 'auto:fyi': 'not a question to you' }

export function Loops({ open: focus }: { open?: number } = {}) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['loops'], queryFn: api.loops, refetchInterval: 60_000 })
  const [view, setView] = usePersisted('assist-loops-view', { kind: '' as '' | Loop['kind'], flag: false, dup: false, show: 'open' as 'open' | 'snoozed' | 'closed' })
  const [text, setText] = useState('')
  const set = useMutation({
    mutationFn: ({ id, status, until }: { id: number; status: string; until?: string }) => api.loopSet(id, status, until),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['loops'] }); qc.invalidateQueries({ queryKey: ['entity'] }); qc.invalidateQueries({ queryKey: ['todo'] }) },
  })
  const distinct = useMutation({ mutationFn: (id: number) => api.loopDistinct(id), onSettled: () => qc.invalidateQueries({ queryKey: ['loops'] }) })
  const items = q.data?.items ?? []
  const open = items.filter((l) => l.status === 'open')
  const snoozed = items.filter((l) => l.status === 'snoozed')
  const closed = items.filter((l) => l.status === 'done' || l.status === 'dropped')
  const autoClosed = closed.filter((l) => (l.closed_by ?? '').startsWith('auto:') && l.closed_by !== 'auto:filter')
  const shown = useMemo(() => {
    const t = text.trim().toLowerCase()
    return (view.show === 'open' ? open : view.show === 'snoozed' ? snoozed : closed).filter((l) => (!view.kind || l.kind === view.kind)
      && (view.show !== 'open' || ((!view.flag || l.suggestion === 'decide_or_drop') && (!view.dup || l.suggestion === 'duplicate')))
      && (!t || `${l.title} ${l.person ?? ''} ${l.counterpart ?? ''} ${l.org ?? ''} ${l.initiatives.join(' ')}`.toLowerCase().includes(t)))
  }, [items, view, text])
  // A link to one item (?open=<id>, from the brief or a person page): show its list, clear the filters, scroll to it.
  const focused = useRef<number | undefined>(undefined)
  useEffect(() => {
    const l = focus && focused.current !== focus ? items.find((x) => x.id === focus) : undefined
    if (!l) return
    focused.current = focus
    setText('')
    setView({ ...view, kind: '', flag: false, dup: false, show: l.status === 'open' ? 'open' : l.status === 'snoozed' ? 'snoozed' : 'closed' })
    setTimeout(() => document.getElementById(`loop-${focus}`)?.scrollIntoView({ block: 'center' }), 80)
  }, [focus, items]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!q.data) return <Loading />
  const flagged = open.filter((l) => l.suggestion === 'decide_or_drop').length
  const dups = open.filter((l) => l.suggestion === 'duplicate').length
  const listed = view.show === 'open' ? open : view.show === 'snoozed' ? snoozed : closed

  return (
    <div className="max-w-[1000px]">
      <div className="mb-4 flex flex-wrap items-baseline gap-3">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Open items</h1>
        <span className="text-[13px] text-ink2">{open.length} open · {flagged} to decide or drop{dups ? ` · ${dups} possible duplicates` : ''}{q.data.reviewed_at ? ` · checked against evidence ${day(q.data.reviewed_at)}` : ''}</span>
      </div>
      {autoClosed.length > 0 && view.show === 'open' && (
        <div className="mb-3 text-[13px] text-ink2">
          {autoClosed.length} closed for you this week. <button onClick={() => setView({ ...view, show: 'closed' })} className="text-ink underline decoration-accent decoration-2 underline-offset-2">Check them</button>
        </div>
      )}
      <FilterBar search={text} onSearch={setText} placeholder="Search person, topic…"
        tokens={[
          ...(view.kind ? [{ label: KINDS.find((k) => k.key === view.kind)?.label ?? view.kind, onRemove: () => setView({ ...view, kind: '' }) }] : []),
          ...(view.flag && view.show === 'open' ? [{ label: 'Decide or drop', onRemove: () => setView({ ...view, flag: false }) }] : []),
          ...(view.dup && view.show === 'open' ? [{ label: 'Possible duplicates', onRemove: () => setView({ ...view, dup: false }) }] : []),
        ]}
        onClear={() => setView({ ...view, kind: '', flag: false, dup: false })}
        right={<Segmented value={view.show} onChange={(v) => setView({ ...view, show: v })}
          options={[['open', `Open · ${open.length}`], ['snoozed', `Snoozed · ${snoozed.length}`], ['closed', `Closed this week · ${closed.length}`]]} />}>
        <FilterRow label="Kind">
          <Opt on={!view.kind} onClick={() => setView({ ...view, kind: '' })}>All</Opt>
          {KINDS.map((k) => <Opt key={k.key} on={view.kind === k.key} onClick={() => setView({ ...view, kind: view.kind === k.key ? '' : k.key })}
            count={listed.filter((l) => l.kind === k.key).length}>{k.label}</Opt>)}
        </FilterRow>
        {view.show === 'open' && <FilterRow label="Flag">
          <Opt on={view.flag} onClick={() => setView({ ...view, flag: !view.flag, dup: false })} count={flagged}>Decide or drop</Opt>
          <Opt on={view.dup} onClick={() => setView({ ...view, dup: !view.dup, flag: false })} count={dups}>Possible duplicates</Opt>
        </FilterRow>}
      </FilterBar>

      {shown.length === 0 ? <Empty>{view.show === 'open' ? 'Nothing open here.' : view.show === 'snoozed' ? 'Nothing snoozed.' : 'Nothing closed this week.'}</Empty> :
        KINDS.filter((k) => shown.some((l) => l.kind === k.key)).map((k) => (
          <section key={k.key} className="mb-5">
            <h2 className="mb-1.5 flex items-baseline gap-2 text-[15px] font-semibold">{k.label}<span className="text-[12.5px] font-normal text-ink2">{shown.filter((l) => l.kind === k.key).length}</span></h2>
            <div className="border border-line bg-panel">
              {shown.filter((l) => l.kind === k.key).map((l) => <Row key={l.id} l={l} focus={l.id === focus}
                act={(status, until) => set.mutate({ id: l.id, status, until })} notSame={() => distinct.mutate(l.id)} />)}
            </div>
          </section>))}
    </div>
  )
}

function Row({ l, act, notSame, focus }: { l: Loop; act: (status: string, until?: string) => void; notSame: () => void; focus?: boolean }) {
  const closed = l.status === 'done' || l.status === 'dropped'
  const asleep = l.status === 'snoozed'
  const due = l.due && l.due < new Date().toISOString().slice(0, 10)
  const [menu, setMenu] = useState(false)
  return (
    <div id={`loop-${l.id}`} className={cn('group flex gap-3 border-b border-line2 px-4 py-3 last:border-b-0', focus && 'bg-accentbg shadow-[inset_2px_0_0_0_var(--accent)]', (l.suggestion === 'decide_or_drop' || l.suggestion === 'duplicate') && !closed && !asleep && 'border-l-2 border-l-hot')}>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-medium leading-snug">{l.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-ink2">
          {l.person_id ? <button onClick={() => viewEntity('person', l.person_id!)} className="inline-flex items-center gap-1 text-ink hover:underline"><User size={12} />{l.person}</button>
            : l.counterpart && <span>{l.counterpart}</span>}
          {l.org_id && <button onClick={() => viewEntity('org', l.org_id!)} className="inline-flex items-center gap-1 text-ink hover:underline"><Building2 size={12} />{l.org}</button>}
          <span title={l.origin_basis === 'source' ? 'from its source' : l.origin_basis === 'text' ? 'date written in the item' : 'first seen by the assistant; the real start may be earlier'}>
            since {day(l.origin_at)}{l.origin_basis !== 'source' ? ' (approx.)' : ''}{l.age_days != null ? ` · ${l.age_days}d` : ''}</span>
          {l.due && <span className={cn(due && 'font-medium text-hot')}>due {day(l.due)}</span>}
          {l.initiatives.map((i) => <span key={i} className="rounded-full border border-line px-1.5 text-[11.5px]">{i}</span>)}
          {l.links.slice(0, 2).map((x, i) => <a key={i} href={x.url} target={x.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className="max-w-[260px] truncate">{x.label} ↗</a>)}
        </div>
        {l.said && <a href={`#/meetings/m-${l.said.meeting_id}?t=${l.said.t}`} title={l.said.quote} className="mt-1 block max-w-[720px] truncate text-[12.5px] text-ink2 no-underline hover:text-ink">
          <MessageSquareQuote size={12} className="-mt-0.5 mr-1 inline" aria-hidden />Said by <b className="font-medium text-ink">{l.said.me ? 'you' : l.said.name}</b> at {l.said.clock}: “{l.said.quote}”</a>}
        {l.suggestion === 'decide_or_drop' && !closed && !asleep && <div className="mt-1 text-[12.5px]"><b className="text-hot">Decide or drop.</b> {l.suggestion_note}</div>}
        {l.suggestion === 'duplicate' && !closed && !asleep && <div className="mt-1 text-[12.5px]"><b className="text-hot"><Copy size={12} className="-mt-0.5 mr-1 inline" aria-hidden />Possible duplicate.</b> {l.suggestion_note}{' '}
          <button onClick={notSame} className="text-ink underline decoration-line decoration-1 underline-offset-2 hover:decoration-ink">Not the same</button></div>}
        {asleep && <div className="mt-1 text-[12.5px] text-ink2"><b className="text-ink">Snoozed</b> until {day(l.snooze_until)}{l.suggestion_note && !l.suggestion ? ` · ${l.suggestion_note}` : ''}</div>}
        {closed && <div className="mt-1 text-[12.5px]"><b>{l.status === 'done' ? 'Closed' : 'Dropped'}</b> {day(l.closed_at)} · {BY[l.closed_by ?? ''] ?? l.closed_by}{l.close_reason ? `: ${l.close_reason}` : ''}
          {l.close_ref && <> · <a href={l.close_ref.url} target={l.close_ref.url.startsWith('http') ? '_blank' : undefined} rel="noopener">{l.close_ref.label} ↗</a></>}</div>}
      </div>
      <div className="flex shrink-0 items-start gap-1">
        {closed || asleep ? <button onClick={() => act('open')} title={asleep ? 'Back on the list now' : 'Reopen'} className={btnClass('outline', 'sm', 'font-normal')}><RotateCcw size={13} />{asleep ? 'Wake' : 'Reopen'}</button> : <div className="relative flex gap-1">
          <button onClick={() => act('done')} title="Done" aria-label={`Done: ${l.title}`} className={btnClass('outline', 'icon', 'hover:bg-accent hover:text-onaccent')}><Check size={14} /></button>
          <button onClick={() => setMenu(!menu)} title="Keep it, not now" aria-label="Snooze" aria-expanded={menu} className={btnClass('outline', 'icon')}><AlarmClock size={14} /></button>
          <button onClick={() => act('dropped')} title="Drop: no longer needed" aria-label="Drop" className={btnClass('outline', 'icon')}><Trash2 size={14} /></button>
          {menu && <div className={cn(popoverClass, 'absolute right-0 top-8 z-20 w-40 py-1')}>
            {snoozeTimes().map((s) => <button key={s.label} onClick={() => { setMenu(false); act('snoozed', s.at) }} className="block w-full px-3 py-1.5 text-left text-[13px] hover:bg-panel2">{s.label}</button>)}
          </div>}
        </div>}
      </div>
    </div>
  )
}
