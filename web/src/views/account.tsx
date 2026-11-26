// Account (16 Nov 2026; the account menu, top right): who this SleePO belongs to, how they are signed in, and where their
// data lives. One person per Mac today, always signed in locally; sign-in with company accounts comes later.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Download, ExternalLink, Laptop, Loader2, LogOut, Play, Power, RotateCcw, RotateCw, SlidersHorizontal, Upload } from 'lucide-react'
import { api } from '@/lib/api'
import { useProfile } from '@/lib/profile'
import { Avatar, Button, btnClass, Loading } from '@/components/ui'

const Panel = ({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) => (
  <section className="mb-5 border border-line bg-panel">
    <header className="flex items-center gap-3 border-b border-line2 px-4 py-3"><h2 className="text-[14px] font-semibold">{title}</h2>{right && <span className="ml-auto">{right}</span>}</header>
    <div className="px-4 py-3">{children}</div>
  </section>
)
const Fact = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="min-w-0"><dt className="text-[12px] text-ink3">{label}</dt><dd className="truncate text-[13px]">{children || '—'}</dd></div>
)

export function AccountPage() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['account'], queryFn: api.account, staleTime: 300_000 })
  const p = useProfile()
  const file = useRef<HTMLInputElement>(null)
  const [note, setNote] = useState('')
  const [imported, setImported] = useState(false)
  const imp = useMutation({
    mutationFn: async (f: File) => api.profileImport(JSON.parse(await f.text())),
    onSuccess: (d) => {
      qc.setQueryData(['profile'], d); qc.invalidateQueries({ queryKey: ['account'] }); qc.invalidateQueries({ queryKey: ['meta'] })
      setImported(true); setNote(d.wrote_seed ? 'Imported, with your initiatives.' : 'Imported.')
    },
    onError: (e: Error) => setNote(`Import failed: ${e.message}`),
  })
  const apply = useMutation({ mutationFn: api.profileApply, onSuccess: (r) => { if (r.restarting) { setNote('Restarting SleePO…'); setTimeout(() => window.location.reload(), 6000) } else setNote(r.reason ?? '') } })
  if (!q.data) return <Loading />
  const { user: u, data } = q.data

  return (
    <div className="max-w-[860px]">
      <h1 className="mb-4 text-[28px] font-semibold leading-tight tracking-[-0.02em]">Account</h1>

      <section className="mb-5 flex flex-wrap items-center gap-4 border border-line bg-panel p-5">
        <Avatar p={{ name: u.name || '?', avatar: u.avatar }} size={64} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[20px] font-semibold leading-tight">{u.name || 'Not set up yet'}</p>
          {(u.role || u.company) && <p className="mt-0.5 text-[13.5px] text-ink2">{[u.role, u.company].filter(Boolean).join(' at ')}</p>}
          {u.email && <p className="mt-0.5 truncate text-[12.5px] text-ink3" title={u.emails.join(', ')}>{u.email}{u.emails.length > 1 ? ` and ${u.emails.length - 1} more` : ''}</p>}
        </div>
        <span className="flex flex-wrap gap-2">
          {u.person_id && <Link to="/people/$id" params={{ id: `p-${u.person_id}` }} className={btnClass('outline')}>Person page</Link>}
          <Link to="/welcome" search={{ step: 'connect' }} className={btnClass('outline')}>Run setup again</Link>
          <Link to="/settings" className={btnClass('primary')}><SlidersHorizontal size={13} /> Edit profile</Link>
        </span>
      </section>

      <Panel title="Sign-in" right={<button disabled={!q.data.accounts} title={q.data.accounts ? undefined : q.data.note} className={btnClass('outline')}><LogOut size={13} /> Log out</button>}>
        <p className="flex items-center gap-2 text-[13px]"><Laptop size={15} className="shrink-0 text-ink3" />
          {q.data.signed_in ? <span>Signed in as <b>{u.name}</b> on this Mac.</span> : <span>Not set up yet: fill in your profile.</span>}</p>
        <p className="mt-1 pl-[23px] text-[12.5px] text-ink3">{q.data.note}</p>
      </Panel>

      <Panel title="At a glance" right={<Link to="/settings" className="text-[12.5px] text-ink2 underline decoration-accent decoration-2 underline-offset-2 hover:text-ink">Change</Link>}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
          <Fact label="Time zone">{p.timezone}{p.second_timezone ? ` · ${p.second_timezone_label || p.second_timezone}` : ''}</Fact>
          <Fact label="Date format">{p.locale} · {p.spelling}</Fact>
          <Fact label="Sign-off">{p.signoff}</Fact>
          <Fact label="Manager">{p.manager}</Fact>
          <Fact label="Plan">{p.plan_title}</Fact>
          <Fact label="Organisation">{u.company}</Fact>
        </dl>
      </Panel>

      <Panel title="Your data">
        <dl className="space-y-2 text-[13px]">
          <div><dt className="text-[12px] text-ink3">SleePO folder</dt><dd className="break-all font-mono text-[12px]">{data.folder}</dd></div>
          <div><dt className="text-[12px] text-ink3">Database</dt><dd className="break-all font-mono text-[12px]">{data.database}</dd></div>
          {data.code !== data.folder && <div><dt className="text-[12px] text-ink3">App</dt><dd className="break-all font-mono text-[12px]">{data.code}</dd></div>}
        </dl>
        <p className="mt-3 text-[12.5px] text-ink3">Everything stays on this Mac. A profile export holds your profile, settings and initiatives; not your mail, meetings or memories. Use it to keep a copy or move to another Mac.</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <a href="/api/profile/export" download className={btnClass('outline')}><Download size={13} /> Export profile</a>
          <Button variant="outline" onClick={() => file.current?.click()} disabled={imp.isPending}><Upload size={13} /> Import profile…</Button>
          <input ref={file} type="file" accept="application/json,.json" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) imp.mutate(f); e.target.value = '' }} />
          {note && <span className="text-[12.5px] text-ink2">{note}</span>}
          {imported && <Button variant="primary" onClick={() => apply.mutate()} disabled={apply.isPending}><RotateCw size={13} /> Apply now</Button>}
        </div>
      </Panel>

      <DemoPanel />
    </div>
  )
}

// Setup as a new user would see it (16 Nov 2026: "a way to demo and test this workflow without deleting all my data and
// settings"): a separate copy of SleePO on port 8766 with its own folder, database and Keychain entries (assist/demo.py).
// Here it is started, opened, reset or stopped; inside the demo itself, this panel resets or stops it.
function DemoPanel() {
  const [poll, setPoll] = useState(false)
  const [note, setNote] = useState('')
  const q = useQuery({ queryKey: ['demo'], queryFn: api.demo, refetchInterval: poll ? 1000 : false })
  const d = q.data
  useEffect(() => { if (poll && d?.running && note !== 'stopping') { setPoll(false); setNote('') } if (poll && note === 'stopping' && d && !d.running) { setPoll(false); setNote('') } }, [d, poll, note])
  const act = async (a: 'start' | 'stop' | 'reset') => {
    setNote(a === 'stop' ? 'stopping' : a === 'reset' ? 'resetting' : 'starting')
    await api.demoAction(a).catch((e: Error) => setNote(e.message))
    if (d?.this_is_demo && a !== 'start') {   // this server is the one going away: come back to the fresh demo, or say it stopped
      if (a === 'reset') { setTimeout(() => window.location.replace('/#/welcome'), 9000) } else setNote('stopped')
      return
    }
    setPoll(true)
  }
  if (!d) return null
  const busy = ['starting', 'stopping', 'resetting'].includes(note)
  const open = `${d.url}#/welcome`
  if (d.this_is_demo) return (
    <Panel title="Demo copy">
      <p className="text-[13px] text-ink2">This is a separate copy of SleePO for trying setup as a new user. Your real SleePO, its data and settings are untouched.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => act('reset')} disabled={busy}><RotateCcw size={13} /> Reset and start again</Button>
        <Link to="/welcome" search={{ step: 'welcome' }} className={btnClass('outline')}>Open setup</Link>
        <Button variant="outline" onClick={() => act('stop')} disabled={busy}><Power size={13} /> Stop the demo</Button>
        {note && <span className="text-[12.5px] text-ink2">{note === 'resetting' ? 'Resetting: back in a few seconds…' : note === 'stopped' ? 'Stopped. You can close this tab.' : note}</span>}
      </div>
    </Panel>
  )
  return (
    <Panel title="Try setup as a new user" right={d.running ? <span className="inline-flex items-center gap-1.5 text-[12px] text-ink2"><span className="size-2 rounded-full bg-accent ring-1 ring-ink/20" />Running</span> : undefined}>
      <p className="text-[13px] text-ink2">Opens a separate copy of SleePO with an empty profile, to go through first-run setup as a new colleague would. Your data, settings and sign-ins here are not touched. Nothing in the demo runs by itself; an import you start there reads this Mac's mail and calendar into the demo only.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {d.running
          ? <><a href={open} target="_blank" rel="noopener" className={btnClass('primary')}>Open the demo <ExternalLink size={12} /></a>
              <Button variant="outline" onClick={() => act('reset')} disabled={busy}><RotateCcw size={13} /> Reset</Button>
              <Button variant="outline" onClick={() => act('stop')} disabled={busy}><Power size={13} /> Stop</Button></>
          : <Button variant="primary" onClick={() => act('start')} disabled={busy}>{busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} {d.created ? 'Start the demo' : 'Create the demo'}</Button>}
        {busy && <span className="text-[12.5px] text-ink2">{note === 'starting' ? 'Starting…' : note === 'resetting' ? 'Resetting to a new install…' : 'Stopping…'}</span>}
        {!busy && note && <span className="text-[12.5px] text-hot">{note}</span>}
      </div>
      <p className="mt-3 text-[12px] text-ink3">{d.url.replace(/\/$/, '')} · {d.created ? `made ${d.created_at}` : 'not made yet'} · <span className="font-mono">{d.folder}</span> · Reset deletes only that folder and the demo's Keychain entries.</p>
    </Panel>
  )
}
