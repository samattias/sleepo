// Top of mind (assist/topics.py; Sam, 28 Oct 2026: "the initiatives and topics that are most top of mind right now ... the most
// important topics that have been brought to my attention during calls or that I have raised"). The specific subjects of the
// last days, most important first, each under the bet it moves: who raised it, where it came up (a meeting opens at the moment
// it was said), what is open on Sam, his task for it. Sam sets a topic aside (Undo) or makes it a task. On the Initiatives page
// it asks SleePO for a fresh set when the last one is old and meetings or mail came in since.
// Sam, 29 Oct 2026: a topic's title opens its page (views/topic.tsx: who said what, where it came up, and an email, a document
// or a decision from it), and he pins the ones that matter now: pinned topics come first and stay past the runs that no longer
// name them, until he unpins them.
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronDown, ChevronRight, ListChecks, Lock, Mail, MessageSquare, Pin, Plus, RefreshCw, Sparkles, Video, X } from 'lucide-react'
import { api, type Person, type Topic, type TopicSource } from '@/lib/api'
import { ago, dayKey, dayLabel, hm } from '@/lib/time'
import { cn } from '@/lib/util'
import { AvatarStack } from '@/components/ui'

const pill = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium transition-colors disabled:opacity-60'
const ICON: Record<TopicSource['kind'], typeof Mail> = { meeting: Video, mail: Mail, chat: MessageSquare, ask: Sparkles }
const KIND: Record<TopicSource['kind'], string> = { meeting: 'Meeting', mail: 'Email', chat: 'Chat', ask: 'You asked SleePO' }

const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`
const when = (ts: string | null) => { if (!ts) return ''; const k = dayKey(ts), l = dayLabel(k); return l === 'Today' ? `today ${hm(ts)}` : l === 'Yesterday' ? 'yesterday' : l }
const first = (n: string) => n.split(' ')[0]

/** "You raised it · 3 meetings · 2 emails · over 3 days · last today 15:45" */
function facts(t: Topic) {
  const parts = [t.raised_by === 'you' ? 'You raised it' : t.raised_by ? `Raised by ${t.raised_by}` : '',
    t.meetings ? plural(t.meetings, 'meeting') : '', t.mails ? plural(t.mails, 'email') : '', t.chats ? plural(t.chats, 'chat') : '',
    t.asks ? plural(t.asks, 'question to SleePO', 'questions to SleePO') : '', t.days > 1 ? `over ${t.days} days` : '', t.last_ts ? `last ${when(t.last_ts)}` : '']
  return parts.filter(Boolean).join(' · ')
}

export function TopOfMind({ initiativeId, people }: { initiativeId?: number; people?: Person[] }) {
  const qc = useQueryClient()
  const key = ['topics', initiativeId ?? 'all']
  const q = useQuery({ queryKey: key, queryFn: () => api.topics(initiativeId), refetchInterval: (s) => (s.state.data?.running ? 4000 : false) })
  const wasRunning = useRef(false)
  useEffect(() => {   // a run just ended: the initiatives' order and topic chips change with it
    if (wasRunning.current && q.data && !q.data.running) { qc.invalidateQueries({ queryKey: ['topics'] }); qc.invalidateQueries({ queryKey: ['portfolio'] }) }
    wasRunning.current = !!q.data?.running
  }, [q.data?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = useMutation({ mutationFn: (auto: boolean) => api.topicsRefresh(auto), onSuccess: () => qc.invalidateQueries({ queryKey: ['topics'] }) })
  const asked = useRef(false)
  useEffect(() => {   // the full list asks for a fresh set by itself when the last one is old and something came in since
    if (!initiativeId && q.data?.stale && !q.data.running && !asked.current) { asked.current = true; refresh.mutate(true) }
  }, [q.data?.stale, q.data?.running]) // eslint-disable-line react-hooks/exhaustive-deps
  const [gone, setGone] = useState<Topic | null>(null)
  const act = useMutation({ mutationFn: ({ t, action }: { t: Topic; action: 'dismiss' | 'restore' | 'task' | 'pin' | 'unpin' }) => api.topicAction(t.id, action),
    onMutate: ({ t, action }) => {
      if (action === 'dismiss') setGone(t); if (action === 'restore') setGone(null)
      if (action === 'pin' || action === 'unpin') qc.setQueryData<typeof q.data>(key, (d) => d && { ...d, topics: d.topics.map((x) => x.id === t.id ? { ...x, pinned: action === 'pin' } : x) })
    },
    onSettled: (_r, _e, { t, action }) => {
      qc.invalidateQueries({ queryKey: ['topics'] }); qc.invalidateQueries({ queryKey: ['portfolio'] }); qc.invalidateQueries({ queryKey: ['topic', t.id] })
      if (action === 'task') qc.invalidateQueries({ queryKey: ['tasks'] })
    } })
  const [all, setAll] = useState(false)
  const d = q.data
  if (!d) return null
  const list = d.topics.filter((t) => !(gone && t.id === gone.id && act.variables?.action === 'dismiss'))
  const running = d.running || refresh.isPending
  if (initiativeId && !list.length) return null   // an initiative nobody discussed lately shows no section
  const pinned = list.filter((t) => t.pinned).length
  const shown = all ? list : list.slice(0, pinned + (initiativeId ? 4 : 6))   // pinned ones always show
  return (
    <section className="mb-5" aria-labelledby={`tom-${initiativeId ?? 'all'}`}>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h2 id={`tom-${initiativeId ?? 'all'}`} className="text-[15px] font-semibold">Top of mind</h2>
        <span className="text-[12.5px] text-ink3">
          {running ? 'SleePO is reading your calls, mail and chats…' : initiativeId ? `discussed in the last ${d.days} days` : `what you discussed in the last ${d.days} days, most important first`}
          {!running && d.run_at && <> · updated {ago(d.run_at)}</>}</span>
        {!initiativeId && <button onClick={() => refresh.mutate(false)} disabled={running} title="Read the last days' calls, mail and chats again"
          className={cn(pill, 'ml-auto text-ink hover:bg-panel2')}><RefreshCw size={13} aria-hidden className={cn(running && 'animate-spin')} />{running ? 'Reading…' : 'Refresh'}</button>}
      </div>
      {d.error && !running && <p className="mb-2 text-[12.5px] text-hot">The last run failed: {d.error}</p>}
      {gone && act.variables?.action === 'dismiss' && (
        <div className="mb-2 flex items-center gap-2 rounded-lg bg-panel2 px-3 py-2 text-[12.5px]">
          <span className="min-w-0 truncate">Set aside “{gone.title}”. SleePO leaves it out unless it comes up again.</span>
          <button onClick={() => act.mutate({ t: gone, action: 'restore' })} className="ml-auto shrink-0 font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Undo</button>
          <button onClick={() => setGone(null)} aria-label="Close" className="shrink-0 text-ink3 hover:text-ink"><X size={13} aria-hidden /></button>
        </div>)}
      {list.length ? (
        <ol className={cn('border border-line bg-panel transition-opacity', running && 'opacity-70')}>
          {shown.map((t, i) => [pinned > 0 && i === pinned && <li key="rest" aria-hidden className="border-b border-line2 bg-panel2 px-4 py-1 text-[12px] font-semibold text-ink2">This week</li>,
            <TopicRow key={t.id} t={t} n={i - pinned + 1} people={people} inInitiative={!!initiativeId} busy={act.isPending && act.variables?.t.id === t.id && act.variables?.action !== 'pin' && act.variables?.action !== 'unpin'}
              onDismiss={() => act.mutate({ t, action: 'dismiss' })} onTask={() => act.mutate({ t, action: 'task' })} onPin={() => act.mutate({ t, action: t.pinned ? 'unpin' : 'pin' })} />])}
        </ol>
      ) : <p className="border border-line bg-panel px-4 py-3 text-[13.5px] text-ink2">{running ? 'Reading the last days. Usually a minute or two.' : 'Nothing yet. Refresh reads the last days.'}</p>}
      {list.length > shown.length || all ? <button onClick={() => setAll(!all)} className="mt-1.5 inline-flex items-center gap-1 px-1 text-[12.5px] font-medium text-ink2 hover:text-ink">
        {all ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}{all ? 'Show fewer' : `Show all ${list.length}`}</button> : null}
    </section>
  )
}

function TopicRow({ t, n, people, inInitiative, busy, onDismiss, onTask, onPin }: { t: Topic; n: number; people?: Person[]; inInitiative: boolean; busy: boolean; onDismiss: () => void; onTask: () => void; onPin: () => void }) {
  const [open, setOpen] = useState(false)
  const where = t.initiative_slug
    ? <Link to="/initiatives/$slug" params={{ slug: t.initiative_slug }} className="rounded-full border border-line px-2 py-px text-[11.5px] font-normal text-ink2 no-underline hover:border-ink">{t.initiative}</Link>
    : <span title={t.area_name ? 'A day-to-day area, not one of your bets' : 'Taking your time, but filed under none of your bets'}
        className="rounded-full border border-dashed border-line px-2 py-px text-[11.5px] text-ink3">{t.area_name ?? 'No initiative'}</span>
  return (
    <li className={cn('group border-b border-line2 px-4 py-3 last:border-0', busy && 'opacity-50')}>
      <div className="flex items-start gap-3">
        {!inInitiative && (t.pinned ? <Pin size={13} aria-label="Pinned" className="mt-0.5 w-4 shrink-0 fill-current text-ink" />
          : <span className="w-4 shrink-0 pt-px text-right text-[12px] tabular-nums text-ink3" aria-hidden>{n}</span>)}   {/* by position: a pinned topic leaves no gap */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Link to="/topics/$id" params={{ id: String(t.id) }} title="Open the topic: who said what, where it came up, and act on it"
              className="text-left text-[14.5px] font-semibold leading-snug text-ink no-underline hover:underline">{t.title}</Link>
            {t.private && <span title="A people matter: private to you" className="text-ink3"><Lock size={12} aria-label="Private" /></span>}
            {t.is_new && <span className="rounded-full bg-accent px-1.5 text-[10.5px] font-semibold text-onaccent">new</span>}
            {!inInitiative && where}
          </div>
          {t.pinned && t.current === false && <p className="mt-0.5 text-[12px] text-ink3">Pinned · not in the latest run</p>}
          {t.summary && <p className="mt-0.5 text-[13px] leading-snug text-ink2">{t.summary}</p>}
          {t.ask && <p className="mt-1 text-[13px] leading-snug"><span className="font-medium">On you: </span>{t.ask}</p>}
          <button onClick={() => setOpen(!open)} aria-expanded={open} className="mt-1 inline-flex items-center gap-1 text-left text-[12px] text-ink3 hover:text-ink">
            {open ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}{facts(t)}</button>
          {open && <Sources sources={t.sources} />}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="flex items-center gap-1">
            {t.people.length > 0 && <span className="max-sm:hidden"><AvatarStack names={t.people} person={(n) => people?.find((p) => p.name === n)} size={22} max={3} linked /></span>}
            <button onClick={onPin} aria-pressed={!!t.pinned} aria-label={t.pinned ? `Unpin ${t.title}` : `Pin ${t.title}`}
              title={t.pinned ? 'Unpin: it goes when a run no longer names it' : 'Pin: keep it first, and keep it when a run no longer names it'}
              className={cn('ml-1 grid size-7 place-items-center rounded-full transition hover:bg-panel2', t.pinned ? 'text-ink' : 'text-ink3 opacity-0 hover:text-ink focus:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100')}>
              <Pin size={14} aria-hidden className={cn(t.pinned && 'fill-current')} /></button>
            <button onClick={onDismiss} disabled={busy} aria-label={`Set aside ${t.title}`} title="Not top of mind: set it aside"
              className="grid size-7 place-items-center rounded-full text-ink3 opacity-0 transition hover:bg-panel2 hover:text-ink focus:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100"><X size={14} aria-hidden /></button>
          </div>
          {t.task_id
            ? <Link to="/tasks" search={{ open: t.task_id }} className="inline-flex items-center gap-1 text-[12px] font-medium text-ink2 no-underline hover:text-ink"><ListChecks size={13} aria-hidden />Task</Link>
            : <button onClick={onTask} disabled={busy} title="Put it on your task list, under its initiative"
                className="inline-flex items-center gap-1 text-[12px] font-medium text-ink3 opacity-0 transition hover:text-ink focus:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100"><Plus size={13} aria-hidden />Make a task</button>}
        </div>
      </div>
    </li>
  )
}

// Where it came up, newest first: a meeting opens its transcript at the moment, an email or chat opens in the app
function Sources({ sources }: { sources: TopicSource[] }) {
  return (
    <ul className="mt-2 space-y-1 border-l-2 border-line pl-3">
      {sources.map((s, i) => { const I = ICON[s.kind] ?? Mail
        const who = s.who.map((w) => (w === 'you' ? 'you' : first(w))).join(', ')
        return (
          <li key={i} className="flex items-center gap-2 text-[12.5px]">
            <I size={13} aria-label={KIND[s.kind]} className="shrink-0 text-ink3" />
            <a href={s.app} className="min-w-0 flex-1 truncate font-normal text-ink no-underline hover:underline" title={s.label}>{s.label}</a>
            {(who || s.clock) && <span className="shrink-0 text-ink3">{who}{s.clock && s.kind === 'meeting' ? ` at ${s.clock}` : ''}</span>}
            <span className="w-[72px] shrink-0 text-right tabular-nums text-ink3">{when(s.ts)}</span>
          </li>) })}
    </ul>
  )
}
