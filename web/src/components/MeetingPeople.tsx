// Who was in a recorded meeting. Granola records no attendees, so SleePO suggests them from the calendar (the matched or an
// overlapping invite), the title ("… with Marlow and Ellis") and names in the notes. Confident ones count straight away;
// the rest wait for a tick or a cross. Sam can add anyone. His decisions are final (assist/meeting_people.py).
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, Plus, X } from 'lucide-react'
import { api, type MeetingPerson } from '@/lib/api'
import { cn } from '@/lib/util'
import { Avatar, btnClass, inputClass } from './ui'

const SRC: Record<string, string> = { granola: 'Granola', speaker: 'spoke in the recording', event: 'calendar invite', overlap: 'overlapping invite', title: 'meeting title', notes: 'named in the notes', sam: 'added by you' }
const why = (p: MeetingPerson) => p.sources.map((s) => SRC[s] ?? s).join(', ') + (p.evidence && p.sources.some((s) => s === 'event' || s === 'overlap') ? ` (“${p.evidence}”)` : '')

export function MeetingPeople({ meetingId, compact }: { meetingId: string; compact?: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['meetingPeople', meetingId], queryFn: () => api.meetingPeople(meetingId) })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 300_000 })
  const [adding, setAdding] = useState(false)
  const [who, setWho] = useState('')
  const [err, setErr] = useState('')
  const set = useMutation({
    mutationFn: (b: { key?: string; status?: string; who?: string }) => api.meetingPeopleDecide(meetingId, b),
    onSuccess: (rows) => { qc.setQueryData(['meetingPeople', meetingId], rows); setErr(''); setWho(''); setAdding(false) },
    onError: (e) => setErr(String(e).replace(/^Error: /, '')),
    onSettled: () => { for (const k of ['meetings', 'calendar', 'people', 'entity']) qc.invalidateQueries({ queryKey: [k] }) },
  })
  if (!q.data) return <span className="text-[12.5px] text-ink2">Loading…</span>
  const person = (id: number | null) => (id ? people.data?.find((p) => p.id === `p-${id}`) : undefined)
  const inMeeting = q.data.filter((p) => p.accepted)
  const toCheck = q.data.filter((p) => p.status === 'suggested' && !p.accepted)
  const Tag = ({ p }: { p: MeetingPerson }) => { const pp = person(p.person_id); const label = <>{pp ? <Avatar p={pp} size={20} /> : null}<span>{p.name}</span></>
    return pp ? <Link to="/people/$id" params={{ id: pp.id }} className="inline-flex items-center gap-1.5 text-ink no-underline hover:underline">{label}</Link> : <span className="inline-flex items-center gap-1.5">{label}</span> }

  return (
    <div className={cn('space-y-2', compact && 'space-y-1.5')}>
      <div className="flex flex-wrap items-center gap-1.5">
        {inMeeting.length === 0 && <span className="text-[12.5px] text-ink2">Nobody confirmed yet.</span>}
        {inMeeting.map((p) => (
          <span key={p.key} title={p.status === 'confirmed' ? 'Confirmed by you' : `Suggested from ${why(p)}`}
            className={cn('group inline-flex items-center gap-1 rounded-full border py-px pl-px pr-2 text-[12.5px] focus-within:pr-1 hover:pr-1', p.status === 'confirmed' ? 'border-ink' : 'border-line')}>
            <Tag p={p} />
            {p.status !== 'confirmed' && <button onClick={() => set.mutate({ key: p.key, status: 'confirmed' })} aria-label={`Confirm ${p.name}`} title="Confirm"
              className="hidden size-5 place-items-center rounded-full text-ink2 hover:bg-accent hover:text-onaccent group-focus-within:grid group-hover:grid"><Check size={12} /></button>}
            <button onClick={() => set.mutate({ key: p.key, status: 'rejected' })} aria-label={`Remove ${p.name}`} title="Not in this meeting"
              className="hidden size-5 place-items-center rounded-full text-ink2 hover:bg-hot hover:text-white group-focus-within:grid group-hover:grid"><X size={12} /></button>
          </span>))}
        {!adding && <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1 rounded-full border border-dashed border-line px-2 py-0.5 text-[12.5px] text-ink2 hover:border-ink hover:text-ink"><Plus size={12} />Add</button>}
      </div>
      {toCheck.length > 0 && (
        <div>
          <div className="mb-1 text-[12px] text-ink2">Were they there?</div>
          <div className="flex flex-wrap gap-1.5">
            {toCheck.map((p) => (
              <span key={p.key} title={`Suggested from ${why(p)}`} className="inline-flex items-center gap-1 rounded-full border border-dashed border-ink3 py-px pl-px pr-1 text-[12.5px] text-ink">
                <Tag p={p} /><span className="text-[11px] text-ink2">{p.sources.includes('overlap') ? 'overlapping invite' : p.sources.includes('notes') ? 'in notes' : ''}</span>
                <button onClick={() => set.mutate({ key: p.key, status: 'confirmed' })} aria-label={`Yes, ${p.name} was there`} title="Yes, they were there"
                  className="grid size-5 place-items-center rounded-full border border-line hover:border-ink hover:bg-accent hover:text-onaccent"><Check size={12} /></button>
                <button onClick={() => set.mutate({ key: p.key, status: 'rejected' })} aria-label={`No, ${p.name} was not there`} title="No"
                  className="grid size-5 place-items-center rounded-full border border-line hover:border-hot hover:bg-hot hover:text-white"><X size={12} /></button>
              </span>))}
          </div>
        </div>)}
      {adding && (
        <form className="flex items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); if (who.trim()) set.mutate({ who: who.trim() }) }}>
          <input autoFocus list={`people-${meetingId}`} value={who} onChange={(e) => setWho(e.target.value)} placeholder="Full name or email"
            className={cn(inputClass, 'w-[220px]')} />
          <datalist id={`people-${meetingId}`}>{(people.data ?? []).filter((p) => p.status !== 'me').map((p) => <option key={p.id} value={p.name} />)}</datalist>
          <button type="submit" className={btnClass('primary')}>Add</button>
          <button type="button" onClick={() => { setAdding(false); setWho(''); setErr('') }} className={btnClass('ghost', 'sm', 'text-ink2')}>Cancel</button>
        </form>)}
      {err && <div className="text-[12px] text-hot">{err}</div>}
    </div>
  )
}
