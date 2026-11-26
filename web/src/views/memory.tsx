// Memory: what SleePO keeps from what Sam tells it (assist/remember.py; Sam, 28 Oct 2026, option A of the mem0 review).
// Only his own words (Ask SleePO, "What should change?" under drafts, brief notes, task and document asks); every memory
// quotes them. The writers (replies, briefs, tasks, Ask SleePO) get the ones that apply. Sam edits, keeps, deletes (Undo)
// and adds them here; his edits are final. A document page: the page scrolls.
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Pencil, Plus, Sparkles, Trash2, X } from 'lucide-react'
import { api, type Memory, type MemoryKind } from '@/lib/api'
import { cn } from '@/lib/util'
import { Button, Loading, Segmented } from '@/components/ui'
import { LOCALE } from '@/lib/time'
import {  } from '@/lib/profile'

const KIND: Record<MemoryKind, string> = { preference: 'Preference', fact: 'Fact', correction: 'Correction' }
const SCOPES: [string, string][] = [['all', 'Everywhere'], ['drafts', 'Drafts'], ['briefs', 'Briefs'], ['tasks', 'Tasks'], ['chat', 'Ask SleePO']]
const SOURCE: Record<string, string> = { chat: 'Ask SleePO', revise: 'What should change?', reply: 'Draft request', notes: 'Brief notes', ask: 'Request', sam: 'Typed here' }
const day = (s: string | null) => (s ? new Date(s).toLocaleDateString(LOCALE, { day: 'numeric', month: 'short' }) : '')
const time = (s: string | null) => (s ? new Date(s).toLocaleString(LOCALE, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'never')

function ScopePicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const toggle = (k: string) => {
    if (k === 'all') return onChange(['all'])
    const rest = value.filter((x) => x !== 'all')
    const next = rest.includes(k) ? rest.filter((x) => x !== k) : [...rest, k]
    onChange(next.length ? next : ['all'])
  }
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label="Applies to">
      {SCOPES.map(([k, l]) => (
        <button key={k} type="button" onClick={() => toggle(k)} aria-pressed={value.includes(k)}
          className={cn('rounded-full px-2.5 py-0.5 text-[12px] transition-colors', value.includes(k) ? 'bg-ink text-bg' : 'bg-panel2 text-ink2 hover:text-ink')}>{l}</button>))}
    </div>
  )
}

function Row({ m, onDeleted }: { m: Memory; onDeleted: (m: Memory) => void }) {
  const qc = useQueryClient()
  const [edit, setEdit] = useState(false)
  const [text, setText] = useState(m.text)
  const [kind, setKind] = useState<MemoryKind>(m.kind)
  const [scope, setScope] = useState<string[]>(m.scope)
  const refresh = () => qc.invalidateQueries({ queryKey: ['memory'] })
  const save = useMutation({ mutationFn: () => api.memoryUpdate(m.id, { text, kind, scope }), onSuccess: () => { setEdit(false); refresh() } })
  const keep = useMutation({ mutationFn: () => api.memoryOp(m.id, 'keep'), onSuccess: refresh })
  const del = useMutation({ mutationFn: () => api.memoryOp(m.id, 'delete'), onSuccess: () => { onDeleted(m); refresh() } })
  const scopes = m.scope.includes('all') ? 'Everywhere' : m.scope.map((s) => SCOPES.find(([k]) => k === s)?.[1] ?? s).join(' · ')
  const soon = m.expires_at && new Date(m.expires_at).getTime() - Date.now() < 7 * 86400000
  return (
    <li className="group border-b border-line2 px-4 py-3 last:border-b-0">
      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11.5px]">
        <span className={cn('rounded-full px-2 py-px font-medium', m.kind === 'correction' ? 'bg-hot/15 text-hot' : m.kind === 'fact' ? 'bg-ink text-bg' : 'bg-accent text-onaccent')}>{KIND[m.kind]}</span>
        <span className="text-ink2">{scopes}</span>
        {m.people.map((p) => <span key={p} className="rounded-full bg-panel2 px-2 py-px text-ink">{p}</span>)}
        {!edit && (
          <span className="ml-auto flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <button onClick={() => setEdit(true)} title="Edit" aria-label="Edit" className="rounded-full p-1 text-ink2 hover:bg-panel2 hover:text-ink"><Pencil size={13} /></button>
            <button onClick={() => del.mutate()} title="Delete" aria-label="Delete" className="rounded-full p-1 text-ink2 hover:bg-panel2 hover:text-hot"><Trash2 size={13} /></button>
          </span>)}
      </div>
      {edit ? (
        <div className="space-y-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} autoFocus
            className="w-full resize-y rounded-xl border border-line bg-panel px-2.5 py-1.5 text-[14px] outline-none focus:border-ink" />
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={kind} onChange={setKind} options={[['preference', 'Preference'], ['fact', 'Fact'], ['correction', 'Correction']] as const} label="Kind" />
            <ScopePicker value={scope} onChange={setScope} />
            <span className="ml-auto flex gap-1">
              <Button onClick={() => { setEdit(false); setText(m.text); setKind(m.kind); setScope(m.scope) }}><X size={13} /> Cancel</Button>
              <Button variant="primary" disabled={!text.trim() || save.isPending} onClick={() => save.mutate()}><Check size={13} /> Save</Button>
            </span>
          </div>
        </div>
      ) : (
        <p className="text-[14.5px] leading-snug">{m.text}</p>
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-ink3">
        <span title={m.source_label ?? undefined}>{SOURCE[m.source ?? ''] ?? 'Said'} · {day(m.created_at)}</span>
        {m.quote && m.source !== 'sam' && <span className="min-w-0 truncate italic">“{m.quote}”</span>}
        <span className={cn('ml-auto shrink-0', soon && 'text-hot')}>
          {m.expires_at ? <>Kept until {day(m.expires_at)} <button onClick={() => keep.mutate()} className="ml-1 font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Keep</button></> : 'Kept until you delete it'}
        </span>
      </div>
    </li>
  )
}

function AddBox() {
  const qc = useQueryClient()
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const [text, setText] = useState('')
  const [kind, setKind] = useState<MemoryKind>('preference')
  const [scope, setScope] = useState<string[]>(['all'])
  const [about, setAbout] = useState<{ id: number; name: string }[]>([])
  const [who, setWho] = useState('')
  const add = useMutation({
    mutationFn: () => api.memoryAdd({ text, kind, scope, people: about.map((p) => p.id) }),
    onSuccess: () => { setText(''); setAbout([]); qc.invalidateQueries({ queryKey: ['memory'] }) },
  })
  const pick = (name: string) => {
    const p = (people.data ?? []).find((x) => x.name.toLowerCase() === name.trim().toLowerCase())
    if (p && !about.some((a) => a.name === p.name)) setAbout([...about, { id: Number(String(p.id).replace(/^p-/, '')), name: p.name }])
    setWho('')
  }
  return (
    <div className="mb-5 rounded-xl border border-line bg-panel p-3">
      <div className="flex items-start gap-2">
        <Plus size={16} className="mt-2 shrink-0 text-ink3" />
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} placeholder="Tell SleePO something to remember…" title="For example: never copy Jordan on partner pricing; Priya is back on 8 Nov"
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && text.trim()) { e.preventDefault(); add.mutate() } }}
          className="min-h-[36px] w-full resize-none bg-transparent py-1.5 text-[14px] outline-none placeholder:text-ink3" />
      </div>
      {text.trim() && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line2 pt-2">
          <Segmented value={kind} onChange={setKind} options={[['preference', 'Preference'], ['fact', 'Fact'], ['correction', 'Correction']] as const} label="Kind" />
          <ScopePicker value={scope} onChange={setScope} />
          <span className="flex flex-wrap items-center gap-1">
            {about.map((a) => <button key={a.id} onClick={() => setAbout(about.filter((x) => x.id !== a.id))} className="rounded-full bg-panel2 px-2 py-0.5 text-[12px]" title="Remove">{a.name} ×</button>)}
            <input list="memory-people" value={who} onChange={(e) => { setWho(e.target.value); if ((people.data ?? []).some((p) => p.name === e.target.value)) pick(e.target.value) }}
              placeholder="About someone?" className="w-[150px] rounded-full bg-panel2 px-2.5 py-0.5 text-[12px] outline-none placeholder:text-ink3" />
            <datalist id="memory-people">{(people.data ?? []).filter((p) => p.status !== 'me').map((p) => <option key={p.id} value={p.name} />)}</datalist>
          </span>
          <Button variant="primary" className="ml-auto" disabled={add.isPending} onClick={() => add.mutate()}>Remember</Button>
        </div>)}
    </div>
  )
}

export function MemoryPage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['memory'], queryFn: api.memory, refetchInterval: (x) => (x.state.data?.learning.running ? 3000 : false) })
  const [filter, setFilter] = useState<'all' | MemoryKind>('all')
  const [gone, setGone] = useState<Memory | null>(null)
  const learn = useMutation({ mutationFn: api.memoryLearn, onSettled: () => qc.invalidateQueries({ queryKey: ['memory'] }) })
  const restore = useMutation({ mutationFn: (id: number) => api.memoryOp(id, 'restore'), onSuccess: () => { setGone(null); qc.invalidateQueries({ queryKey: ['memory'] }) } })
  const list = useMemo(() => (q.data?.memories ?? []).filter((m) => m.status === 'active' && (filter === 'all' || m.kind === filter)), [q.data, filter])
  if (!q.data) return <Loading />
  const { learning, retention_days } = q.data
  const active = q.data.memories.filter((m) => m.status === 'active')
  const count = (k: MemoryKind) => active.filter((m) => m.kind === k).length
  return (
    <div className="max-w-[860px]">
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Memory</h1>
        <span className="ml-auto flex items-center gap-2 text-[12px] text-ink3">
          {learning.running ? <><Loader2 size={13} className="animate-spin" /> Reading what you said…</> : <>Last read {time(learning.last_run)}</>}
          <Button variant="outline" disabled={learning.running || learn.isPending} onClick={() => learn.mutate()}><Sparkles size={13} /> Learn now</Button>
        </span>
      </div>
      <p className="mb-4 max-w-[680px] text-[13px] text-ink2">
        What SleePO keeps from what you tell it: in Ask SleePO, under drafts (What should change?), in brief notes and in task or document requests.
        Only your own words, never mail or chat from others; each memory quotes you. Drafts, briefs, tasks and Ask SleePO follow the ones that apply.
        Memories about your own way of working stay until you delete them; memories about someone else go after {retention_days} days unless you keep them.
      </p>
      {learn.data && !learn.data.started && !learning.running && <p className="mb-3 text-[12.5px] text-ink3">Nothing new since the last read.</p>}
      <AddBox />
      <div className="mb-2 flex items-center gap-2">
        <Segmented value={filter} onChange={setFilter} label="Kind"
          options={[['all', `All ${active.length}`], ['preference', `Preferences ${count('preference')}`], ['fact', `Facts ${count('fact')}`], ['correction', `Corrections ${count('correction')}`]] as const} />
      </div>
      {gone && (
        <div className="mb-2 flex items-center gap-2 bg-panel2 px-3 py-2 text-[12.5px]">
          <span className="min-w-0 truncate">Deleted “{gone.text}”</span>
          <button onClick={() => restore.mutate(gone.id)} className="ml-auto shrink-0 font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Undo</button>
          <button onClick={() => setGone(null)} aria-label="Dismiss" className="shrink-0 text-ink3 hover:text-ink"><X size={13} /></button>
        </div>)}
      {list.length ? (
        <ul className="border border-line bg-panel">{list.map((m) => <Row key={`${m.id}-${m.updated_at}`} m={m} onDeleted={setGone} />)}</ul>
      ) : (
        <p className="border border-dashed border-line px-4 py-8 text-center text-[13px] text-ink3">
          {active.length ? 'None of this kind.' : 'Nothing remembered yet. Tell SleePO what to keep doing in Ask SleePO or under a draft, or type it above.'}
        </p>)}
    </div>
  )
}
