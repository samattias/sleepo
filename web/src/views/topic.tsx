// A top-of-mind topic's page (Sam, 29 Oct 2026: "click into these and see a page just like on the initiatives where I can see
// what everyone's done and basically take actions from that page like draft emails, create documents ... trigger tasks from
// that page"; assist/topics.py, assist/initiative_work.py). Where it stands and what is open on Sam, the latest on it (the files
// shared, and every place it came up with what was said there, read in place), and the same work bar as an initiative: an
// email, a document, a decision or a question, each a conversation in Ask SleePO with everything behind the topic; and a task.
// Sam pins a topic to keep it first in Top of mind and past the runs that no longer name it; unpins it when it stops mattering.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLink, ListChecks, Lock, Pin, Plus, X } from 'lucide-react'
import { api, workBase, type TopicFile, type TopicPage as TopicData, type TopicSource } from '@/lib/api'
import { ago } from '@/lib/time'
import { cn } from '@/lib/util'
import { Avatar, Empty, Loading } from '@/components/ui'
import { FileIcon } from '@/components/FileIcon'
import { ItemRow, WorkBar, useWork, type Work, type WorkItem } from '@/components/InitnfhgjcAlmi'
import { usePageTitle, useSearchSync } from '@/lib/nav'
import { NewSince } from '@/components/NewSince'

const pill = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium transition-colors disabled:opacity-60'
const HEALTH: Record<string, string> = { 'on track': 'bg-accent ring-1 ring-ink/30', 'at risk': 'bg-transparent ring-2 ring-inset ring-hot', 'off track': 'bg-hot', blocked: 'bg-hot' }
const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`

const item = (s: TopicSource, i: number): WorkItem => ({ key: s.ref_key ?? `ask:${i}`, ref_type: s.ref_type ?? 'ask', ref_id: s.ref_id ?? 0, type: s.kind, title: s.label,
  who: s.who.map((w) => (w === 'you' ? 'you' : w)).join(', '), ts: s.ts, app: s.app })

export function TopicPage({ id, open }: { id: number; open?: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['topic', id], queryFn: () => api.topic(id), retry: false })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const base = workBase({ topic: id })
  const w = useWork({ base, key: `topic-${id}` })   // the items Sam picked; each button opens a conversation in Ask SleePO
  const [openKey, setOpenKey] = useState<string | null>(open ?? null)   // the source read in place (kept in the address)
  const [setAside, setSetAside] = useState(false)
  useSearchSync('open', openKey)
  usePageTitle(q.data?.title)
  const byName = new Map((people.data ?? []).map((p) => [p.name.toLowerCase(), p]))
  const who = (n: string) => byName.get((n || '').replace(/\s*\(.*\)\s*$/, '').trim().toLowerCase())
  const refresh = () => { for (const k of [['topic', id], ['topics'], ['portfolio']]) qc.invalidateQueries({ queryKey: k }) }
  const act = useMutation({ mutationFn: (a: 'pin' | 'unpin' | 'task' | 'dismiss' | 'restore') => api.topicAction(id, a),
    onMutate: (a) => { if (a === 'pin' || a === 'unpin') qc.setQueryData<TopicData>(['topic', id], (d) => d && { ...d, pinned: a === 'pin' }); if (a === 'dismiss') setSetAside(true); if (a === 'restore') setSetAside(false) },
    onSettled: (_r, _e, a) => { refresh(); if (a === 'task') qc.invalidateQueries({ queryKey: ['tasks'] }) } })
  if (q.isError) return <Empty>This topic is no longer top of mind: a later run did not name it. <Link to="/initiatives">Back to Top of mind</Link></Empty>
  if (!q.data) return <Loading />
  const t = q.data
  const items = t.sources.map(item)
  const facts = [t.raised_by === 'you' ? 'You raised it' : t.raised_by ? `Raised by ${t.raised_by}` : '', t.meetings ? plural(t.meetings, 'meeting') : '', t.mails ? plural(t.mails, 'email thread') : '',
    t.chats ? plural(t.chats, 'chat') : '', t.asks ? plural(t.asks, 'question to SleePO', 'questions to SleePO') : '', t.days > 1 ? `over ${t.days} days` : '', t.last_ts ? `last ${ago(t.last_ts)}` : '']
    .filter(Boolean).join(' · ')
  const faces = [...new Set([...(t.raised_by && t.raised_by !== 'you' ? [t.raised_by] : []), ...t.people])]
  return (
    <div className="max-w-[920px]">
      <header className="mb-3 flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[12px]">
            <span className="rounded-full bg-panel2 px-2 py-px font-medium text-ink2">Top of mind</span>
            {t.initiative_slug ? <Link to="/initiatives/$slug" params={{ slug: t.initiative_slug }} className="rounded-full border border-line px-2 py-px font-normal text-ink2 no-underline hover:border-ink">{t.initiative}</Link>
              : <span className="rounded-full border border-dashed border-line px-2 py-px text-ink3">{t.area_name ?? 'No initiative'}</span>}
            {t.importance === 'high' && <span className="text-ink3">high importance</span>}
            {t.private && <span title="A people matter: private to you" className="inline-flex items-center gap-1 text-ink3"><Lock size={12} aria-hidden />private</span>}
          </div>
          <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">{t.title}</h1>
          {t.summary && <p className="mt-1 text-[14px] text-ink2">{t.summary}</p>}
          {/* what came in since a run last wrote it (graph memory); the Top of mind run rewrites topics together, for now */}
          <NewSince kind="topic" id={id} what="this topic was written" className="mt-1.5" />
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2 pt-1">
          <button onClick={() => act.mutate(t.pinned ? 'unpin' : 'pin')} aria-pressed={!!t.pinned}
            title={t.pinned ? 'Unpin: it goes when a run no longer names it' : 'Pin: kept first in Top of mind, and kept when a run no longer names it'}
            className={cn(pill, t.pinned ? 'bg-ink text-bg' : 'border border-line text-ink hover:border-ink')}>
            {t.pinned ? <><Pin size={13} aria-hidden className="fill-current" />Pinned</> : <><Pin size={13} aria-hidden />Pin</>}</button>
          {faces.length > 0 && <div className="flex -space-x-1.5" aria-label="People in it">{faces.slice(0, 6).map((n) => {
            const p = who(n); const face = <Avatar p={p ?? { name: n, avatar: '' }} size={26} />
            return p?.id ? <Link key={n} to="/people/$id" params={{ id: String(p.id) }} title={n} className="rounded-full ring-2 ring-bg">{face}</Link>
              : <span key={n} title={n} className="rounded-full ring-2 ring-bg">{face}</span> })}</div>}
        </div>
      </header>

      {setAside && <div className="mb-3 flex items-center gap-2 rounded-lg bg-panel2 px-3 py-2 text-[12.5px]">
        <span className="min-w-0 flex-1">Set aside. SleePO leaves it out of Top of mind unless it comes up again.</span>
        <button onClick={() => act.mutate('restore')} className="font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Undo</button></div>}
      {!t.current && t.status === 'current' && <p className="mb-3 rounded-lg border-l-2 border-l-ink bg-panel2 px-3 py-2 text-[12.5px] text-ink2">
        The latest run did not name it; it last came up {t.last_ts ? ago(t.last_ts) : 'earlier'}. {t.pinned ? 'It stays because you pinned it.' : 'It goes at the next run unless you pin it.'}</p>}

      <section className="mb-4 border border-line bg-panel px-4 py-3">
        {t.ask && <p className="text-[14px] leading-snug"><span className="font-semibold">On you: </span>{t.ask}</p>}
        <p className={cn('text-[12.5px] text-ink3', t.ask && 'mt-1.5')}>{facts}</p>
        {t.initiative_status?.status && <p className="mt-1.5 flex items-start gap-2 text-[12.5px] text-ink2">
          <span className={cn('mt-1 size-2 shrink-0 rounded-full', HEALTH[t.initiative_status.health ?? ''] ?? 'bg-line')} />
          <span><span className="font-medium text-ink">{t.initiative}: </span>{t.initiative_status.status}</span></p>}
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {t.task ? <Link to="/tasks" search={{ open: t.task.id }} className={cn(pill, 'border border-line font-normal text-ink no-underline hover:border-ink')}><ListChecks size={13} aria-hidden />Task · {t.task.title}</Link>
            : <button onClick={() => act.mutate('task')} disabled={act.isPending} title="Put it on your task list, under its initiative" className={cn(pill, 'border border-line text-ink hover:border-ink')}><Plus size={13} aria-hidden />Make a task</button>}
          {t.status === 'current' && !setAside && <button onClick={() => act.mutate('dismiss')} title="Not top of mind: SleePO leaves it out unless it comes up again"
            className={cn(pill, 'ml-auto text-ink2 hover:bg-panel2 hover:text-ink')}><X size={13} aria-hidden />Set aside</button>}
        </div>
      </section>

      <WorkBar subj={{ kind: 'topic', base, key: `topic-${id}`, name: t.title, work: t.work }} w={w} />

      <Latest t={t} items={items} base={base} w={w} openKey={openKey} setOpenKey={setOpenKey} />
    </div>
  )
}

// Latest (Sam, 29 Oct 2026: "the latest pieces of information on that topic, so, links to the latest emails or what that
// email said or messages or call ... ideally I would have a link to the actual deck"; it replaced Who said what): the files
// shared in its sources first, each opening the real file, then every email thread, message, meeting and question it came up
// in, newest first, each with what it said in a line or two and its files; opened, it reads in place.
function Latest({ t, items, base, w, openKey, setOpenKey }: {
  t: TopicData; items: WorkItem[]; base: string; w: Work; openKey: string | null; setOpenKey: (k: string | null) => void
}) {
  const files = t.files ?? []
  const [allFiles, setAllFiles] = useState(false)
  const shown = allFiles ? files : files.slice(0, 6)
  return (
    <section className="mb-5">
      <h2 className="mb-2 flex items-baseline gap-2 text-[15px] font-semibold">Latest<span className="text-[12.5px] font-normal text-ink3">{plural(t.sources.length, 'source')}, newest first</span></h2>
      {files.length > 0 && <div className="mb-3">
        <div className="grid gap-1.5 sm:grid-cols-2">{shown.map((f) => <FileCard key={f.url} f={f} />)}</div>
        {files.length > 6 && <button onClick={() => setAllFiles(!allFiles)} className="mt-1 px-1 text-[12.5px] font-medium text-ink2 hover:text-ink">
          {allFiles ? 'Fewer files' : `All ${files.length} files`}</button>}
      </div>}
      <div className="border border-line bg-panel">
        {items.map((x, i) => { const s = t.sources[i]; const open = openKey === x.key
          return <ItemRow key={x.key} base={base} x={x} open={open} onToggle={() => setOpenKey(open ? null : x.key)}
            pinned={w.pins.some((p) => p.key === x.key)} onPin={() => w.togglePin(x)} onUse={(p) => w.actFrom(x, p)}
            said={s.kind === 'meeting' ? s.said : undefined} below={<Said s={s} open={open} onOpen={() => setOpenKey(x.key)} />} /> })}
      </div>
    </section>
  )
}

// a type with no app icon (components/FileIcon.tsx) keeps its extension as a badge
const typeOf = (f: TopicFile) => (f.name.match(/\.(\w{2,4})$/)?.[1] ?? 'FILE').toUpperCase()
const fileWhere = (f: TopicFile) => f.url.startsWith('#') ? 'Open the email it came with' : /sharepoint\.com|1drv\.ms|onedrive/i.test(f.url) ? 'Open in SharePoint' : 'Open the file'
const byWho = (w: string) => (w === 'you' ? 'You' : w)

// a shared file: opens the real file (SharePoint or OneDrive, or the email's attachment)
function FileCard({ f }: { f: TopicFile }) {
  const external = !f.url.startsWith('#')
  return (
    <a href={f.url} target={external ? '_blank' : undefined} rel="noopener" title={`${f.name}\n${fileWhere(f)}${f.label ? ` · shared in “${f.label}”` : ''}`}
      className="group flex min-w-0 items-center gap-2.5 border border-line bg-panel px-2.5 py-2 font-normal text-ink no-underline transition-colors hover:border-ink">
      <FileIcon name={f.name} share={f.share} size={30} fallback={<span className="grid h-8 w-9 shrink-0 place-items-center border border-line text-[10px] font-semibold tracking-wide text-ink2 group-hover:border-ink group-hover:text-ink">{typeOf(f)}</span>} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{f.name}</span>
        <span className="block truncate text-[11.5px] text-ink3">{[byWho(f.who), f.ts && ago(f.ts)].filter(Boolean).join(' · ')}</span>
      </span>
      <ExternalLink size={13} aria-hidden className="shrink-0 text-ink3 group-hover:text-ink" />
    </a>
  )
}

// what a source said, in a line or two (hidden while it is read in place), and the files it shares
function Said({ s, open, onOpen }: { s: TopicSource; open: boolean; onOpen: () => void }) {
  const lines = open ? [] : s.lines ?? []
  const files = s.files ?? []
  if (!lines.length && !files.length) return null
  return (
    <div onClick={(e) => { if (!open && !(e.target as HTMLElement).closest('a')) onOpen() }}
      className={cn('-mt-1 space-y-0.5 pb-2 pl-[59px] pr-3 max-sm:pl-4', !open && 'cursor-pointer')}>
      {lines.map((l, i) => <p key={i} className="line-clamp-2 text-[12.5px] leading-snug text-ink2 [overflow-wrap:anywhere]">
        {l.who && <span className="font-medium text-ink">{byWho(l.who)}</span>}
        {l.clock && (l.app ? <a href={l.app} title="Hear it at that moment" className="ml-1 font-normal text-ink3 no-underline hover:underline">at {l.clock}</a> : <span className="ml-1 text-ink3">at {l.clock}</span>)}
        {l.who && ': '}{l.text}</p>)}
      {files.length > 0 && <div className="flex flex-wrap gap-1.5 pt-1">{files.map((f) => <a key={f.url} href={f.url} target={f.url.startsWith('#') ? undefined : '_blank'} rel="noopener" title={`${f.name}\n${fileWhere(f)}`}
        className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full border border-line bg-panel px-2 py-px text-[12px] font-normal text-ink no-underline hover:border-ink">
        <FileIcon name={f.name} share={f.share} size={12} /><span className="truncate">{f.name}</span></a>)}</div>}
    </div>
  )
}
