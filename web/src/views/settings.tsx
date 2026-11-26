// Personalisation (16 Nov 2026, DESIGN-PERSONALISATION.md; in the account menu, top right): everything that is the user's
// own, so the app itself names no one. Five tabs of square panels; rarely needed fields fold under More. Changes collect
// across tabs and a floating bar appears only while something is unsaved or just saved. Prompts read the profile when the
// server starts, so after a save Apply now restarts it.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import { Check, ChevronRight, FileText, Loader2, RotateCw, Sparkles, X } from 'lucide-react'
import { api, type ProfileArea, type ProfileData } from '@/lib/api'
import { useSearchSync } from '@/lib/nav'
import { Button, inputClass, Loading, PageTabs, popoverClass, selectClass } from '@/components/ui'
import { cn } from '@/lib/util'
import { day } from '@/lib/time'

type Kind = 'text' | 'list' | 'select' | 'number' | 'date' | 'days' | 'zone'
type Field = { key: string; label: string; help?: string; kind?: Kind; options?: [string, string][]; placeholder?: string }
type Group = { title: string; note?: string; fields: Field[]; more?: Field[] }
type Tab = 'you' | 'calendar' | 'privacy' | 'work' | 'org'

const PRONOUNS: [string, string][] = [['', 'Not set'], ['he/him', 'he/him'], ['she/her', 'she/her'], ['they/them', 'they/them']]
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const FROM_RECORD = new Set(['full_name', 'emails', 'aliases', 'role', 'manager', 'manager_title'])   // from the People record when empty

const GROUPS: Record<Exclude<Tab, 'work' | 'org'>, Group[]> = {
  you: [{
    title: 'Who you are', note: 'SleePO recognises you in mail, chat and transcripts by these names and addresses, and writes as you.',
    fields: [
      { key: 'full_name', label: 'Name', placeholder: 'Milo Rivera' },
      { key: 'role', label: 'Role', placeholder: 'VP of Sales' },
      { key: 'role_short', label: 'Short role', placeholder: 'VP Sales', help: 'In prompts and on the Soul tab.' },
      { key: 'pronouns', label: 'Pronouns', kind: 'select', options: PRONOUNS },
      { key: 'emails', label: 'Your addresses', kind: 'list', help: 'Work and personal, one per line.' },
      { key: 'aliases', label: 'Other names', kind: 'list', help: 'Names people use for you, one per line.' },
    ],
    more: [
      { key: 'first_name', label: 'First name' },
      { key: 'speaker_label', label: 'Granola speaker label', help: 'How Granola labels your microphone.' },
      { key: 'manager', label: 'Manager' },
      { key: 'manager_title', label: 'Manager’s title', placeholder: 'CEO' },
      { key: 'manager_pronouns', label: 'Manager’s pronouns', kind: 'select', options: PRONOUNS },
    ],
  }],
  calendar: [
    { title: 'Time and meetings', note: 'Times are shown and reasoned in your zone; drafts only offer slots inside your meeting hours.', fields: [
      { key: 'timezone', label: 'Time zone', kind: 'zone' },
      { key: 'locale', label: 'Date format', kind: 'select', options: [['en-GB', 'English (UK) · 22 Oct'], ['en-US', 'English (US) · Oct 22'], ['fr-FR', 'Français'], ['de-DE', 'Deutsch'], ['ja-JP', '日本語']] },
      { key: 'meeting_days', label: 'Meeting days', kind: 'days' },
      { key: 'meeting_hours', label: 'Meeting hours', placeholder: '09:00-17:00' },
      { key: 'meeting_minutes', label: 'Usual length (minutes)', kind: 'number' },
      { key: 'second_timezone', label: 'Second clock', kind: 'zone', help: 'On the calendar and beside proposed times. Empty for none.' },
      { key: 'second_timezone_label', label: 'Its label', placeholder: 'PT' },
    ] },
    { title: 'Writing', note: 'How drafts end and spell. The rest of your voice is a page under Work.', fields: [
      { key: 'signoff', label: 'Email sign-off' },
      { key: 'spelling', label: 'Spelling', kind: 'select', options: [['', 'From the date format'], ['British', 'British'], ['American', 'American']] },
    ] },
  ],
  privacy: [{
    title: 'What stays out', note: 'Patterns are words separated by | (any case).', fields: [
      { key: 'personal_meetings', label: 'Personal meetings', placeholder: 'dentist|school run', help: 'Meetings whose title matches are skipped everywhere.' },
      { key: 'personal_meetings_title', label: 'How prompts name them', placeholder: 'Milo <> family sync' },
      { key: 'sensitive_names', label: 'Sensitive names', help: 'A meeting title with one of these is kept as an HR matter.' },
      { key: 'private_files', label: 'Private file words', help: 'Local files with these in their name are never read (on top of HR, medical, tax…).' },
      { key: 'forwarded_mailboxes', label: 'Forwarded mailboxes', kind: 'list', help: 'Mail only to these (a predecessor’s mailbox) is noise.' },
      { key: 'mail_since', label: 'Mail history starts', kind: 'date' },
    ],
  }],
}
const PAGE_FIELDS: Field[] = [
  { key: 'plan_file', label: 'Plan file', placeholder: 'memory/context/plan.md' },
  { key: 'plan_title', label: 'Plan name', placeholder: 'V2MOM 2026' },
  { key: 'role_soul_file', label: 'Role soul file', placeholder: 'memory/context/role-soul.md' },
  { key: 'role_soul_title', label: 'Role soul heading' },
]
const ALL: Field[] = [...Object.values(GROUPS).flat().flatMap((g) => [...g.fields, ...(g.more ?? [])]), ...PAGE_FIELDS]
const TABS: readonly { key: Tab; label: string }[] = [
  { key: 'you', label: 'You' }, { key: 'calendar', label: 'Calendar & writing' }, { key: 'privacy', label: 'Privacy' },
  { key: 'work', label: 'Work' }, { key: 'org', label: 'Organisation' }]

const asText = (v: unknown) => (Array.isArray(v) ? v.join('\n') : v == null ? '' : String(v))
const zones = (() => { try { return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone') } catch { return [] } })()
const startVals = (d: ProfileData) => Object.fromEntries(ALL.map((f) => [f.key, asText(d.stored[f.key] ?? (FROM_RECORD.has(f.key) || f.key === 'timezone' ? d.profile[f.key] : ''))]))
const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)

const Panel = ({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) => (
  <section className="mb-5 border border-line bg-panel">
    <header className="border-b border-line2 px-4 py-3">
      <h2 className="text-[14px] font-semibold">{title}</h2>{note && <p className="mt-0.5 text-[12.5px] text-ink3">{note}</p>}
    </header>
    <div className="divide-y divide-line2 px-4">{children}</div>
  </section>
)

function Control({ f, value, onChange, placeholder }: { f: Field; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const id = `pf-${f.key}`
  if (f.kind === 'select') return <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={cn(selectClass, 'w-full max-w-[340px]')}>{f.options!.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
  if (f.kind === 'list') return <textarea id={id} value={value} onChange={(e) => onChange(e.target.value)} rows={Math.max(2, value.split('\n').length)} placeholder={placeholder}
    className="w-full max-w-[420px] resize-y rounded-xl border border-line bg-panel px-3 py-1.5 text-[12.5px] outline-none placeholder:text-ink3 focus:border-ink" />
  if (f.kind === 'days') {
    const on = new Set(value.split(',').map((x) => x.trim()).filter(Boolean))
    return <span className="flex flex-wrap gap-1">{DAYS.map((d) => (
      <button key={d} type="button" aria-pressed={on.has(d)} onClick={() => onChange(DAYS.filter((x) => (x === d ? !on.has(d) : on.has(x))).join(','))}
        className={cn('rounded-full border px-2.5 py-0.5 text-[12px] capitalize', on.has(d) ? 'border-ink bg-ink text-bg' : 'border-line text-ink2 hover:border-ink')}>{d}</button>))}</span>
  }
  return <input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} list={f.kind === 'zone' ? 'pf-zones' : undefined}
    type={f.kind === 'number' ? 'number' : f.kind === 'date' ? 'date' : 'text'} className={cn(inputClass, 'w-full max-w-[340px]')} />
}

function Row({ f, value, onChange, fallback, source }: { f: Field; value: string; onChange: (v: string) => void; fallback?: string; source?: string }) {
  const help = [f.help, source].filter(Boolean).join(' ')
  return (
    <div className="grid gap-1.5 py-3 md:grid-cols-[190px_1fr] md:gap-4">
      <label htmlFor={`pf-${f.key}`} className="pt-1 text-[13px] font-medium">{f.label}</label>
      <div className="min-w-0"><Control f={f} value={value} onChange={onChange} placeholder={fallback || f.placeholder} />
        {help && <p className="mt-1 text-[12px] text-ink3">{help}</p>}</div>
    </div>
  )
}

function More({ children, count, label }: { children: ReactNode; count: number; label?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="py-1">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex items-center gap-1 py-2 text-[12.5px] text-ink2 hover:text-ink">
        <ChevronRight size={13} className={cn('transition-transform', open && 'rotate-90')} /> {open ? 'Less' : label ?? `More (${count})`}
      </button>
      {open && <div className="divide-y divide-line2 border-t border-line2">{children}</div>}
    </div>
  )
}

export function Personalisation() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['profile'], queryFn: api.profile, staleTime: Infinity })
  const arrived = useRouterState({ select: (s) => (s.location.search as Record<string, unknown>).tab as Tab | undefined })
  const [tab, setTab] = useState<Tab>(TABS.some((t) => t.key === arrived) ? arrived! : 'you')
  useSearchSync('tab', tab === 'you' ? null : tab)
  useEffect(() => { const k = TABS.some((t) => t.key === arrived) ? arrived! : 'you'; setTab((cur) => (cur === k ? cur : k)) }, [arrived])   // the address changed (a link, Back)
  const [vals, setVals] = useState<Record<string, string>>({})
  const [channels, setChannels] = useState('')
  const [areas, setAreas] = useState<ProfileArea[]>([])
  const [orgName, setOrgName] = useState('')
  const [pack, setPack] = useState('')
  const [phase, setPhase] = useState<'idle' | 'saved' | 'restarting'>('idle')
  const [msg, setMsg] = useState('')

  const load = (d: ProfileData) => {
    setVals(startVals(d)); setChannels(d.followed_channels.join('\n')); setAreas(d.task_areas)
    setOrgName(String(d.org.overrides.name ?? '')); setPack(d.org.pack_setting); setMsg('')
  }
  useEffect(() => { if (q.data) load(q.data) }, [q.data])   // eslint-disable-line react-hooks/exhaustive-deps
  const init = useMemo(() => (q.data ? { vals: startVals(q.data), channels: q.data.followed_channels.join('\n'), areas: JSON.stringify(q.data.task_areas),
    orgName: String(q.data.org.overrides.name ?? ''), pack: q.data.org.pack_setting } : null), [q.data])
  const changed = init ? Object.keys(vals).filter((k) => vals[k] !== init.vals[k]) : []
  const extra = init ? [channels !== init.channels, JSON.stringify(areas) !== init.areas, orgName !== init.orgName, pack !== init.pack] : []
  const nChanges = changed.length + extra.filter(Boolean).length

  const save = useMutation({
    mutationFn: () => {
      const byKey = Object.fromEntries(ALL.map((f) => [f.key, f]))
      const fields = Object.fromEntries(changed.map((k) => {
        const v = vals[k].trim(), f = byKey[k]
        return [k, f.kind === 'list' ? lines(v) : f.kind === 'number' ? (v ? Number(v) : null) : v || null]
      }))
      return api.profileSave({ fields, ...(extra[0] ? { followed_channels: lines(channels) } : {}), ...(extra[1] ? { task_areas: areas } : {}),
        ...(extra[2] ? { org: { name: orgName.trim() || null } } : {}), ...(extra[3] ? { org_pack: pack.trim() } : {}) })
    },
    onSuccess: (d) => { qc.setQueryData(['profile'], d); qc.invalidateQueries({ queryKey: ['meta'] }); qc.invalidateQueries({ queryKey: ['account'] }); setPhase('saved') },
    onError: (e: Error) => setMsg(e.message),
  })
  const apply = useMutation({
    mutationFn: api.profileApply,
    onSuccess: (r) => { if (r.restarting) { setPhase('restarting'); setTimeout(() => window.location.reload(), 6000) } else setMsg(r.reason ?? 'Could not restart now.') },
  })

  if (!q.data) return <Loading />
  const d = q.data
  const set = (k: string) => (v: string) => { setVals((x) => ({ ...x, [k]: v })); if (phase === 'saved') setPhase('idle') }
  const source = (k: string) => (!(k in d.stored) && FROM_RECORD.has(k) && vals[k] ? (k.startsWith('manager') ? 'From the org chart.' : 'From your People record.') : undefined)
  const fallback = (k: string) => (!(k in d.stored) && !vals[k] ? asText(d.profile[k]) : '')
  const row = (f: Field) => <Row key={f.key} f={f} value={vals[f.key] ?? ''} onChange={set(f.key)} fallback={fallback(f.key)} source={source(f.key)} />
  const useSuggest = () => {
    const s = d.suggest ?? {}
    setVals({ ...vals, ...(s.full_name ? { full_name: s.full_name } : {}), ...(s.emails ? { emails: s.emails.join('\n') } : {}), ...(s.role ? { role: s.role } : {}), ...(s.timezone ? { timezone: s.timezone } : {}) })
  }

  return (
    <div className="max-w-[860px] pb-24">
      <PageTabs title="Personalisation" tabs={TABS} active={tab} onSelect={setTab} label="Personalisation sections" />
      <datalist id="pf-zones">{zones.map((z) => <option key={z} value={z} />)}</datalist>

      {d.needs_setup && (
        <div className="mb-5 flex flex-wrap items-center gap-3 border border-line bg-panel px-4 py-3">
          <Sparkles size={16} className="shrink-0" />
          <p className="min-w-0 flex-1 text-[13px]"><b>Set up SleePO for you.</b> It cannot tell your mail and meetings from anyone else’s until it knows who you are.
            {d.suggest?.full_name && <> On this Mac you look like <b>{d.suggest.full_name}</b>{d.suggest.emails?.length ? ` (${d.suggest.emails.join(', ')})` : ''}.</>}</p>
          {d.suggest?.full_name && <Button variant="primary" onClick={useSuggest}>Use these</Button>}
        </div>)}

      {tab !== 'work' && tab !== 'org' && GROUPS[tab].map((g) => (
        <Panel key={g.title} title={g.title} note={g.note}>
          {g.fields.map(row)}
          {tab === 'privacy' && <Row f={{ key: 'followed_channels', label: 'Followed Slack channels', kind: 'list', help: 'Read like DMs; other channels are background only.' }} value={channels} onChange={setChannels} />}
          {g.more && <More count={g.more.length}>{g.more.map(row)}</More>}
        </Panel>))}

      {tab === 'work' && <>
        <Panel title="Day-to-day areas" note={<>Where tasks that move none of your bets are filed. The bets themselves are on <Link to="/initiatives" className="underline decoration-accent decoration-2 underline-offset-2">Initiatives</Link>.</>}>
          {areas.map((a, i) => (
            <div key={a.key} className="grid gap-2 py-2.5 md:grid-cols-[190px_1fr] md:gap-4">
              <input aria-label={`Name of ${a.key}`} value={a.name} onChange={(e) => setAreas(areas.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} className={cn(inputClass, 'font-medium')} />
              <input aria-label={`What goes in ${a.name}`} value={a.hint} onChange={(e) => setAreas(areas.map((x, j) => (j === i ? { ...x, hint: e.target.value } : x)))} placeholder="What goes here" className={inputClass} />
            </div>))}
        </Panel>
        <Panel title="Pages SleePO reads about you" note="In your SleePO folder. Edit them in place; SleePO reads the new text on its next run.">
          {d.pages.map((p) => (
            <div key={p.key} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2.5 text-[13px]">
              <FileText size={14} className="shrink-0 text-ink3" />
              <span className="font-medium">{p.label === 'Your voice and calendar rules' ? 'Your voice' : p.label}</span>
              <code className="min-w-0 truncate text-[12px] text-ink3" title={p.path}>{p.path}</code>
              <span className="ml-auto text-[12px] text-ink3">{p.exists ? (p.updated ? day(p.updated) : '') : 'missing'}</span>
              {p.route && p.exists && <a href={`#${p.route}`} className="text-[12.5px] text-ink2 underline decoration-accent decoration-2 underline-offset-2 hover:text-ink">Open</a>}
            </div>))}
          <More count={PAGE_FIELDS.length} label="Change which files">{PAGE_FIELDS.map(row)}</More>
        </Panel>
      </>}

      {tab === 'org' && (
        <Panel title={d.org.name || 'No organisation'} note="What everyone at your company sets the same way comes from its org pack: domains, org chart, products, systems and mail rules.">
          <div className="py-3 text-[12.5px]">
            <p className="text-ink2">{d.org.pack_exists ? 'Pack' : 'No pack at'} <code className="break-all text-[12px]">{d.org.pack_path}</code></p>
            {d.org.domains.length > 0 && <p className="mt-1 text-ink3">{d.org.domains.join(' · ')}</p>}
            {d.org.pack_exists && <p className="mt-1 text-ink3">{[
              d.org.has.org_chart ? `org chart (${d.org.has.org_chart} managers)` : '', d.org.has.known_people ? `${d.org.has.known_people} known contacts` : '',
              d.org.has.products ? `${d.org.has.products} products` : '', d.org.has.jira_projects ? `Jira (${d.org.has.jira_projects} projects)` : '',
              d.org.has.crm ? 'CRM' : '', d.org.has.roadmap ? 'roadmap' : '', d.org.has.kb ? 'emery yates' : '',
              d.org.has.noise_senders || d.org.has.shared_mailboxes ? 'mail rules' : ''].filter(Boolean).join(' · ')}</p>}
          </div>
          <Row f={{ key: 'org_name', label: 'Company name', help: 'Only to call it something other than the pack does.' }} value={orgName} onChange={setOrgName} fallback={d.org.name} />
          <Row f={{ key: 'org_pack', label: 'Org pack file', help: 'Empty for org/pack.json in your SleePO folder.' }} value={pack} onChange={setPack} fallback="org/pack.json" />
        </Panel>)}

      {(nChanges > 0 || phase !== 'idle' || msg) && (
        <div role="status" className={cn(popoverClass, 'fixed bottom-6 left-1/2 z-40 flex w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 items-center gap-3 px-4 py-2.5 text-[13px] md:ml-[125px]')}>
          {phase === 'restarting' ? <span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Restarting SleePO; the page reloads in a few seconds.</span>
            : msg ? <span className="min-w-0 flex-1 text-red-600">{msg}</span>
            : nChanges > 0 ? <span className="min-w-0 flex-1">{nChanges} unsaved change{nChanges === 1 ? '' : 's'}</span>
            : <span className="flex min-w-0 flex-1 items-center gap-2"><Check size={14} /> Saved. SleePO uses it after a restart.</span>}
          {phase !== 'restarting' && <span className="ml-auto flex shrink-0 items-center gap-1.5">
            {nChanges > 0 && <Button variant="ghost" onClick={() => load(d)}>Discard</Button>}
            {nChanges > 0 && <Button variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save'}</Button>}
            {nChanges === 0 && phase === 'saved' && <Button variant="primary" disabled={apply.isPending} onClick={() => apply.mutate()}><RotateCw size={13} /> Apply now</Button>}
            {nChanges === 0 && <button aria-label="Dismiss" onClick={() => { setPhase('idle'); setMsg('') }} className="grid size-7 place-items-center rounded-full text-ink3 hover:bg-panel2 hover:text-ink"><X size={14} /></button>}
          </span>}
        </div>)}
    </div>
  )
}
