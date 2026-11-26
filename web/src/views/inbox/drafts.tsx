// Inbox › Drafts (Sam, 26 Oct 2026: "a drafts view into the inbox where I can see my latest drafts and ... generate new drafts
// that aren't responses to existing threads ... a clone of my regular mailbox from Apple Mail with the added AI-generated
// emails"). Four kinds, from assist/new_mail.py: Outlook's own drafts (read from Apple Mail, opened in Outlook or improved
// with SleePO), new emails written here (To, Cc, Subject and what it should say; written and revised in Sam's voice from
// what SleePO knows), replies in progress (they open in their email's composer), and new emails SleePO recommends, which are
// email actions on task steps (Tasks shows the same ones). Nothing is sent from here.
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, ChevronDown, ClipboardCopy, CornerUpLeft, Info, ListChecks, Paperclip, PenLine, PenSquare, RefreshCw,
  Search as SearchIcon, Sparkles, Trash2, X } from 'lucide-react'
import { api, type DraftsData, type OutlookDraft, type RecommendedEmail, type ReplyInProgress, type SleepoDraft } from '@/lib/api'
import { cn, dayKey, dayLabel, editRatio, time, usePersisted } from '@/lib/util'
import { ago } from '@/lib/time'
import { Avatar, Empty, Loading } from '@/components/ui'
import { FillEditor, countFills } from '@/components/FillEditor'
import { DictateButton } from '@/components/Dictate'
import { ReviseBar, RevisedStrip } from '@/components/ReviseBar'
import { openChatThread } from '@/components/Chat'
import { OutlookLogo } from '@/components/OutlookLogo'
import { openCompose } from '@/lib/outlook'
import { ListResizer } from '@/components/ListResizer'
import { diffRedline } from '@/lib/diff'
import { usePageTitle, useSearchSync } from '@/lib/nav'
import { type Who, shortWhen, toolBtn, typing } from './model'
import { myName } from '@/lib/profile'

const NEW_INTENTS = ['Ask for it by a date', 'Hand it over with the context', 'Share an update', 'Propose a time to talk', 'Thank them']
const LENGTH_LABELS = ['One line', 'Brief', 'Standard', 'Detailed', 'Thorough']
const split = (s: string) => s.split(/[,;]/).map((x) => x.trim()).filter(Boolean)
const msg = (e: unknown) => String(e instanceof Error ? e.message : e)
// "quinn.irving@acme.example" -> "Quinn Irving", for names and faces where SleePO only has an address
const nameOf = (a: string) => { const m = a.match(/^([^@<\s]+)@/); return m ? m[1].split(/[._-]+/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(' ') : a }
const field = 'min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink3 focus:bg-panel2/60'

type Item = { key: string; kind: 'rec' | 'reply' | 'sleepo' | 'outlook'; ts: string; to: string[]; subject: string; preview: string
  r?: RecommendedEmail; d?: SleepoDraft; o?: OutlookDraft; w?: ReplyInProgress }

function items(data: DraftsData | undefined) {
  if (!data) return { rec: [], replies: [], drafts: [] } as Record<'rec' | 'replies' | 'drafts', Item[]>
  const pv = (t: string) => (t || '').replace(/\s+/g, ' ').trim().slice(0, 160)
  const rec: Item[] = data.recommended.map((r) => ({ key: r.key, kind: 'rec', ts: r.ts, to: (r.action.to ?? []).map(nameOf), subject: r.action.subject || r.step_title, preview: r.why || pv(r.action.body ?? ''), r }))
  const replies: Item[] = data.replies.map((w) => ({ key: w.key, kind: 'reply', ts: w.ts, to: w.to.map((a) => a.name || a.address), subject: w.subject, preview: pv(w.body), w }))
  const drafts: Item[] = [
    ...data.sleepo.map((d): Item => ({ key: d.key, kind: 'sleepo', ts: d.updated_at, to: d.to.map(nameOf), subject: d.subject, preview: pv(d.body) || (d.ask ? `Asked: ${pv(d.ask)}` : ''), d })),
    ...data.outlook.map((o): Item => ({ key: o.key, kind: 'outlook', ts: o.ts, to: o.to.map((a) => a.name || nameOf(a.address)), subject: o.subject, preview: pv(o.body), o })),
  ].sort((a, b) => b.ts.localeCompare(a.ts))
  return { rec, replies, drafts }
}

export function Drafts({ head, listW, setListW, who, openMail, openNeeds, draft }: {
  head: ReactNode; listW: number; setListW: (w: number) => void; who: Who; openMail: (id: number) => void; openNeeds: () => void; draft?: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['drafts'], queryFn: api.drafts, refetchInterval: (x) => (x.state.data?.suggest?.running ? 5000 : 60_000) })
  const flags = useQuery({ queryKey: ['replyInbox'], queryFn: api.replyInbox, refetchInterval: 120000 })
  const readyReplies = (flags.data ?? []).filter((x) => x.needs_reply && x.drafted && !x.answered).length
  const [sel, setSel] = useState<string | null>(draft ?? null)
  const [search, setSearch] = useState('')
  const [tweakFor, setTweakFor] = useState<string | null>(null)   // a draft just taken in from Outlook: open with "Change this draft"
  const [gone, setGone] = useState<{ text: string; undo?: () => void } | null>(null)
  useEffect(() => { if (!gone) return; const t = setTimeout(() => setGone(null), 8000); return () => clearTimeout(t) }, [gone])
  useSearchSync('draft', sel)
  useEffect(() => { if (draft && draft !== sel) setSel(draft) }, [draft]) // eslint-disable-line react-hooks/exhaustive-deps

  const all = useMemo(() => items(q.data), [q.data])
  const shown = useMemo(() => {
    const re = search.trim() ? new RegExp(search.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
    const f = (xs: Item[]) => (re ? xs.filter((x) => re.test(`${x.subject} ${x.to.join(' ')} ${x.preview} ${x.r?.task_title ?? ''}`)) : xs)
    return { rec: f(all.rec), replies: f(all.replies), drafts: f(all.drafts) }
  }, [all, search])
  const byKey = useMemo(() => new Map([...all.rec, ...all.replies, ...all.drafts].map((x) => [x.key, x])), [all])
  const visible = useMemo(() => [...shown.rec, ...shown.drafts], [shown])   // j / k; replies in progress open in the Inbox
  const cur = sel ? byKey.get(sel) ?? null : null
  usePageTitle(cur ? cur.subject || 'Draft' : null)
  // on a desktop, open the first draft; on a phone the list comes first
  useEffect(() => { if (sel == null && q.data && visible.length && matchMedia('(min-width: 768px)').matches) setSel(visible[0].key) }, [q.data, visible, sel])

  const pick = (x: Item) => { if (x.kind === 'reply' && x.w) openMail(x.w.item_id); else setSel(x.key) }
  // a recommended email Sam does not want: out of Drafts at once, with Undo (new_mail.exclude)
  const exclude = async (r: RecommendedEmail) => {
    const i = visible.findIndex((x) => x.key === r.key)
    if (sel === r.key) setSel((visible[i + 1] ?? visible[i - 1])?.key ?? null)
    qc.setQueryData<DraftsData>(['drafts'], (x) => (x ? { ...x, recommended: x.recommended.filter((y) => y.key !== r.key) } : x))
    try {
      await api.draftsExclude(r.step_id, r.index)
      setGone({ text: `Removed “${r.action.subject || r.step_title}” from Drafts`, undo: async () => {
        await api.draftsExclude(r.step_id, r.index, true)
        for (const k of ['drafts', 'tasks']) qc.invalidateQueries({ queryKey: [k] })
      } })
    } catch (e) { setGone({ text: `Could not remove it: ${msg(e)}` }) }
    for (const k of ['drafts', 'tasks']) qc.invalidateQueries({ queryKey: [k] })
  }
  const [creating, setCreating] = useState(false)
  const newEmail = async () => {
    if (creating) return
    setCreating(true)
    try {
      const d = await api.draftNew({})
      qc.setQueryData<DraftsData>(['drafts'], (x) => (x ? { ...x, sleepo: [d, ...x.sleepo] } : x))
      setSel(d.key)
    } catch (e) { setGone({ text: `Could not start a new email: ${msg(e)}` }) }
    setCreating(false)
  }
  const suggest = q.data?.suggest ?? null
  const startSuggest = async () => {
    try { await api.draftsSuggest(); await new Promise((r) => setTimeout(r, 800)); qc.invalidateQueries({ queryKey: ['drafts'] }) } catch (e) { setGone({ text: msg(e) }) }
  }
  const improve = async (o: OutlookDraft) => {
    const r = await api.draftFromOutlook(o.key)
    if (r.item_id) { openMail(r.item_id); return }
    await qc.invalidateQueries({ queryKey: ['drafts'] })
    setTweakFor(`d-${r.draft}`); setSel(`d-${r.draft}`)
  }

  useEffect(() => {   // j / k move through the list, n starts a new email
    const k = (e: KeyboardEvent) => {
      if (typing(e)) return
      if (e.key === 'n') { e.preventDefault(); void newEmail(); return }
      if ((e.key === '#' || e.key === 'Delete' || e.key === 'Backspace') && cur?.r) { e.preventDefault(); void exclude(cur.r); return }
      const i = visible.findIndex((x) => x.key === sel)
      const go = (j: number) => { const x = visible[Math.max(0, Math.min(visible.length - 1, j))]; if (x) { setSel(x.key); document.getElementById(`draft-${x.key}`)?.scrollIntoView({ block: 'nearest' }) } }
      if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); go(i + 1) }
      if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); go(i - 1) }
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }) // eslint-disable-line react-hooks/exhaustive-deps

  const today = dayKey(new Date().toISOString())
  const groups = useMemo(() => {
    const g: { day: string; items: Item[] }[] = []
    for (const x of shown.drafts) { const d = dayKey(x.ts); if (g.at(-1)?.day !== d) g.push({ day: d, items: [] }); g.at(-1)!.items.push(x) }
    return g
  }, [shown.drafts])
  const section = 'sticky top-0 z-[1] flex items-center gap-2 border-b border-line2 bg-panel px-4 py-1 text-[12px] font-semibold text-ink'
  const row = (x: Item) => <DraftRow key={x.key} x={x} on={x.key === sel} who={who} onClick={() => pick(x)} onExclude={x.r ? () => void exclude(x.r!) : undefined} />

  return (
    <div className="flex min-h-0 flex-1">
      <aside aria-label="Drafts" style={listW ? ({ '--list-w': `${listW}px` } as CSSProperties) : undefined}
        className={cn('@container/list relative flex min-h-0 w-full flex-col border-line bg-panel md:shrink-0 md:border-r', listW ? 'md:w-[min(var(--list-w),50vw)]' : 'md:w-[clamp(320px,30vw,420px)]', sel != null && 'max-md:hidden')}>
        <ListResizer width={listW} onChange={setListW} label="Resize the drafts list" />
        <div className="border-b border-line px-4 pt-3">
          {head}
          <div className="mt-2.5 flex items-center gap-2">
            <label className="relative block min-w-0 flex-1">
              <SearchIcon size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink3" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search drafts" aria-label="Search drafts"
                className="w-full rounded-full border border-line bg-bg py-1.5 pl-8 pr-3 text-[13px] text-ink outline-none transition-colors placeholder:text-ink3 focus:border-ink" />
            </label>
            <button onClick={() => void newEmail()} disabled={creating} title="Write a new email with SleePO (n)"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-ink px-3 py-1.5 text-[13px] font-medium text-bg transition-opacity hover:opacity-90 disabled:opacity-60">
              <PenSquare size={14} aria-hidden />New email</button>
          </div>
          <div className="py-2.5 text-[12.5px] text-ink2">
            {readyReplies > 0 ? <button onClick={openNeeds} className="text-left hover:text-ink">{readyReplies} recommended {readyReplies > 1 ? 'replies are' : 'reply is'} ready in <span className="font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Needs response</span></button>
              : <span>Your Outlook drafts, emails you write here and the ones SleePO recommends. Nothing is sent from here.</span>}
          </div>
        </div>
        {gone && <div role="status" className="flex items-center gap-2 border-b border-line2 px-4 py-1.5 text-[12.5px] text-ink2">
          <span className="min-w-0 truncate">{gone.text}</span>
          {gone.undo ? <button onClick={() => { gone.undo!(); setGone(null) }} className="ml-auto shrink-0 font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Undo</button>
            : <button onClick={() => setGone(null)} aria-label="Dismiss" className="ml-auto shrink-0 text-ink hover:opacity-70"><X size={13} aria-hidden /></button>}</div>}
        <div className="relative min-h-0 flex-1 overflow-auto">
          {q.isError && <div className="p-4"><Empty>Could not load drafts.</Empty></div>}
          {!q.data && !q.isError && <div className="p-4"><Loading /></div>}
          {q.data && <>
            <div>
              <div className={section}>
                <Sparkles size={12} aria-hidden /><span title="Most important first: the bet, the CEO or a customer among the recipients, the date and the priority">Recommended by SleePO</span><span className="font-normal tabular-nums text-ink3">{all.rec.length || ''}</span>
                <button onClick={() => void startSuggest()} disabled={!!suggest?.running} title="Look through recent mail, meetings and your tasks for new emails you should send (a minute or two)"
                  className="ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium text-ink2 transition-colors hover:bg-panel2 hover:text-ink disabled:opacity-60">
                  {suggest?.running ? <RefreshCw size={12} className="animate-spin" aria-hidden /> : <Sparkles size={12} aria-hidden />}{suggest?.running ? 'Looking…' : 'Suggest emails'}</button>
              </div>
              {suggest?.running && <div className="px-4 py-2 text-[12.5px] text-ink2">Reading recent mail, meetings and your tasks for emails you should start. Usually a minute or two.</div>}
              {!suggest?.running && suggest?.finished && Date.now() - Date.parse(suggest.finished) < 15 * 60_000 && (
                <div className={cn('px-4 py-2 text-[12.5px]', suggest.ok ? 'text-ink2' : 'text-hot')}>
                  {suggest.ok ? (suggest.count ? `${suggest.count} new email${suggest.count > 1 ? 's' : ''} recommended ${ago(suggest.finished)}.` : `Nothing new to send (checked ${ago(suggest.finished)}).`) : `The search stopped: ${suggest.error ?? 'try again'}`}</div>)}
              {shown.rec.map(row)}
              {!all.rec.length && !suggest?.running && <div className="px-4 py-2 text-[12.5px] text-ink3">None right now. The morning refresh looks, or press Suggest emails.</div>}
            </div>
            {shown.replies.length > 0 && <div>
              <div className={section}><CornerUpLeft size={12} aria-hidden />Replies in progress<span className="font-normal tabular-nums text-ink3">{shown.replies.length}</span></div>
              {shown.replies.map(row)}
            </div>}
            <div className={section}><PenLine size={12} aria-hidden />Drafts<span className="font-normal tabular-nums text-ink3">{all.drafts.length || ''}</span></div>
            {q.data.outlook_error && <div className="px-4 py-2 text-[12.5px] text-hot">Outlook's drafts could not be read from Apple Mail: {q.data.outlook_error}</div>}
            {groups.map((g) => <div key={g.day}>
              <div className="border-b border-line2 bg-panel px-4 py-1 text-[11.5px] font-medium text-ink3">{dayLabel(g.day, today)}</div>
              {g.items.map(row)}
            </div>)}
            {!shown.drafts.length && <div className="p-4"><Empty>{search ? 'No match.' : 'No drafts.'}</Empty></div>}
          </>}
        </div>
      </aside>
      <section aria-label="Draft" className={cn('min-h-0 min-w-0 flex-1 overflow-auto bg-bg', sel == null && 'max-md:hidden')}>
        <button onClick={() => setSel(null)} className="m-3 inline-flex items-center gap-1 text-[13px] text-ink2 md:hidden"><ArrowLeft size={14} aria-hidden />Drafts</button>
        {cur?.kind === 'outlook' && cur.o ? <OutlookView key={cur.key} o={cur.o} openMail={openMail} onImprove={improve} />
          : (cur?.kind === 'sleepo' && cur.d) || (cur?.kind === 'rec' && cur.r)
            ? <NewEmail key={cur.key} d={cur.d} r={cur.r} startTweak={tweakFor === cur.key} who={who} onExclude={cur.r ? () => void exclude(cur.r!) : undefined}
                onGone={(text, undo) => { setGone({ text, undo }); const i = visible.findIndex((x) => x.key === cur.key); setSel((visible[i + 1] ?? visible[i - 1])?.key ?? null) }} />
            : <div className="grid h-full place-items-center p-6 text-center text-[13.5px] text-ink2">{q.data ? <div>{sel ? 'This draft is no longer here: sent, discarded or deleted.' : 'Select a draft, or write a new email.'}
              <div className="mt-1 text-[12.5px] text-ink3">n for a new email · j / k to move</div></div> : null}</div>}
      </section>
    </div>
  )
}

function DraftRow({ x, on, who, onClick, onExclude }: { x: Item; on: boolean; who: Who; onClick: () => void; onExclude?: () => void }) {
  const to = x.to.map((n) => who(n)?.name ?? n)   // the people database spells names right ("Rowan Lowell", not "Rowan Lowell")
  const first = to[0] ?? ''
  const name = to.length ? `To ${to.slice(0, 2).join(', ')}${to.length > 2 ? ` +${to.length - 2}` : ''}` : 'No recipients yet'
  return (
    <div className="group relative">
    <button id={`draft-${x.key}`} onClick={onClick} aria-current={on ? 'true' : undefined}
      className={cn('flex w-full gap-2.5 border-b border-l-2 border-b-line2 py-1.5 pl-4 pr-4 text-left', on ? 'border-l-accent bg-accentbg' : 'border-l-transparent hover:bg-panel2')}>
      <Avatar p={who(first) ?? { name: first || '?', avatar: '' }} size={28} className="mt-0.5" />
      <span className="min-w-0 flex-1 leading-[18px]">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-[13.5px] font-medium">{name}</span>
          {x.kind === 'outlook' && x.o?.attachments.length ? <Paperclip size={12} aria-label="has attachments" className="shrink-0 text-ink3" /> : null}
          <span className="ml-auto shrink-0 text-[12px] tabular-nums text-ink3">{x.kind === 'outlook' || x.kind === 'sleepo' ? time(x.ts) : shortWhen(x.ts)}</span>
        </span>
        <span className="block truncate text-[13px] font-semibold">{x.subject || '(no subject)'}</span>
        <span className="flex items-center gap-1.5 text-[12.5px] text-ink3">
          {x.kind === 'rec' && x.r?.level === 'high' && <span className="shrink-0 rounded-full bg-accent px-1.5 text-[11.5px] font-semibold leading-[18px] text-onaccent"
            title={`Send first${x.r.rank_why.length ? `: ${x.r.rank_why.join(', ')}` : ''}`}>Send first</span>}
          {x.kind === 'rec' && x.r && <span className={cn('shrink-0 rounded-full px-1.5 text-[11.5px] font-medium leading-[18px]', x.r.suggested ? 'bg-accentbg text-ink' : 'bg-panel2 text-ink')}
            title={x.r.suggested ? 'Suggested: not on your task list until you add it' : `A step of your task: ${x.r.task_title}`}>{x.r.suggested ? 'Suggested' : 'On your list'}</span>}
          {x.kind === 'reply' && <span className="inline-flex shrink-0 items-center gap-0.5 text-ink2"><CornerUpLeft size={12} aria-hidden />{x.w?.source === 'chat' ? 'From the chat' : x.w?.source === 'generated' ? 'Written for you' : 'Your version'}</span>}
          {x.kind === 'sleepo' && <span className="shrink-0 rounded-full bg-panel2 px-1.5 text-[11.5px] font-medium leading-[18px] text-ink" title="Written in SleePO">SleePO</span>}
          {x.kind === 'outlook' && x.o?.reply_to_item && <span className="inline-flex shrink-0 items-center gap-0.5 text-ink2" title={`A reply to “${x.o.reply_subject}”`}><CornerUpLeft size={12} aria-hidden />Reply</span>}
          <span className="truncate">{x.preview}</span>
        </span>
      </span>
    </button>
    {onExclude && <button onClick={onExclude} aria-label={`Remove “${x.subject}” from Drafts`} title="Remove from Drafts (#)"
      className="absolute bottom-1.5 right-2 grid size-6 place-items-center rounded-full bg-panel text-ink2 opacity-0 shadow-sm transition-opacity hover:text-ink focus:opacity-100 group-hover:opacity-100"><X size={13} aria-hidden /></button>}
    </div>
  )
}

// ---- an Outlook draft: read here, edited and sent in Outlook; "Improve with SleePO" takes a copy in
function OutlookView({ o, openMail, onImprove }: { o: OutlookDraft; openMail: (id: number) => void; onImprove: (o: OutlookDraft) => Promise<void> }) {
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 300_000 })
  const me = people.data?.find((p) => p.status === 'me')
  const [quote, setQuote] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState(false)
  const names = (xs: { name: string; address: string }[]) => xs.map((a) => a.name || a.address).join(', ')
  const improve = async () => { setBusy(true); setErr(''); try { await onImprove(o) } catch (e) { setErr(msg(e)) } setBusy(false) }
  return (
    <div className="mx-auto max-w-[880px] px-3 py-3">
      {o.reply_to_item && <div className="mb-2 flex items-center gap-2 px-1 text-[12.5px] text-ink2"><CornerUpLeft size={13} aria-hidden />A reply to
        <button onClick={() => openMail(o.reply_to_item!)} className="min-w-0 truncate font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">“{o.reply_subject}”</button></div>}
      <article aria-label="Outlook draft" className="rounded-xl border border-dashed border-ink3/60 bg-panel">
        <div className="flex items-start gap-3 px-4 pt-3">
          <Avatar p={me ?? { name: myName(), avatar: '' }} size={36} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="text-[14px] font-semibold">You</span>
              <span className="inline-flex items-center gap-1 rounded-full bg-accentbg px-2 text-[11.5px] font-semibold leading-[18px] text-ink"><PenLine size={11} aria-hidden />Outlook draft</span>
              <span className="text-[12px] text-ink3">saved {shortWhen(o.ts)}</span>
            </div>
            <div className="truncate text-[12.5px] text-ink2" title={`To: ${names(o.to)}${o.cc.length ? `\nCc: ${names(o.cc)}` : ''}`}>to {names(o.to) || <span className="text-hot">no one yet</span>}{o.cc.length > 0 && <> · cc {names(o.cc)}</>}</div>
            <div className="truncate text-[13px] font-medium text-ink">{o.subject || '(no subject)'}</div>
          </div>
        </div>
        <div className="whitespace-pre-wrap px-4 pb-3 pt-2 text-[14px] leading-[1.65] text-ink md:pl-[64px]">{o.body || <span className="text-ink3">(empty)</span>}</div>
        {o.attachments.length > 0 && <div className="flex flex-wrap gap-1.5 px-4 pb-2 md:pl-[64px]">{o.attachments.map((a) =>
          <span key={a} className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-px text-[12px] text-ink"><Paperclip size={12} aria-hidden />{a}</span>)}</div>}
        {o.quoted && <div className="px-4 pb-2 md:pl-[64px]">
          <button onClick={() => setQuote(!quote)} aria-expanded={quote} className="inline-flex items-center gap-1 text-[12.5px] text-ink2 hover:text-ink">The email it answers<ChevronDown size={12} aria-hidden className={cn('transition-transform', quote && 'rotate-180')} /></button>
          {quote && <div className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-panel2 px-3 py-2 text-[12.5px] leading-relaxed text-ink2">{o.quoted}</div>}
        </div>}
        <footer className="flex flex-wrap items-center gap-1.5 border-t border-line2 px-4 py-2 md:pl-[60px]">
          <a href={o.web_link} target="_blank" rel="noopener" className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3.5 py-1.5 text-[13px] font-medium text-bg no-underline transition-opacity hover:opacity-90">
            <OutlookLogo size={14} />Open in Outlook</a>
          <button onClick={() => void improve()} disabled={busy} title={o.reply_to_item ? 'Open it in its email, where SleePO can revise it with what you ask' : 'Take a copy into SleePO, where it can be revised with what you ask'}
            className={cn(toolBtn, 'py-1.5 disabled:opacity-60')}>{busy ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : <Sparkles size={14} aria-hidden />}Improve with SleePO</button>
          <button onClick={async () => { try { await navigator.clipboard.writeText(o.body); setCopied(true) } catch { setErr('The clipboard is not available here.') } }} className={cn(toolBtn, 'py-1.5')}>
            {copied ? <Check size={14} aria-hidden /> : <ClipboardCopy size={14} aria-hidden />}{copied ? 'Copied' : 'Copy'}</button>
          <span className="ml-auto text-[12px] text-ink3 max-sm:hidden">Edit and send it in Outlook.</span>
        </footer>
        {err && <div role="alert" className="px-4 pb-3 text-[12.5px] text-hot md:pl-[64px]">{err}</div>}
      </article>
      <p className="mt-2 px-1 text-[12px] text-ink3">SleePO reads Outlook's Drafts through Apple Mail, so a change you make there shows here a minute or two later.</p>
    </div>
  )
}

// ---- a new email: SleePO's own draft, or one it recommends (an email action on a task step). To, Cc, Subject and what it
// should say; Write it (or, with text there, revise it with Sam's words as feedback); the email edited in place and kept as he
// types; Copy, Open in Outlook (a draft in his Outlook; until IT approves SleePO's access, Outlook on the web's compose page,
// filled in), Continue in chat. The initiative page writes its emails with it too (components/InitiativeWork.tsx).
export function NewEmail({ d, r, startTweak, who, onGone, onExclude }: { d?: SleepoDraft; r?: RecommendedEmail; startTweak: boolean; who: Who; onGone: (text: string, undo?: () => void) => void; onExclude?: () => void }) {
  const qc = useQueryClient()
  const key = (d?.key ?? r?.key)!
  const a = r?.action
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 300_000 })
  const me = people.data?.find((p) => p.status === 'me')
  const [to, setTo] = useState((d ? d.to : a?.to ?? []).join(', '))
  const [cc, setCc] = useState((d ? d.cc : a?.cc ?? []).join(', '))
  const [showCc, setShowCc] = useState((d ? d.cc : a?.cc ?? []).length > 0)
  const [subject, setSubject] = useState(d ? d.subject : a?.subject ?? '')
  const [body, setBody] = useState(d ? d.body : a?.body ?? '')
  const [ask, setAsk] = useState(d?.ask ?? '')
  const [length, setLength] = usePersisted<number>('assist-newmail-length', 3)
  const [notes, setNotes] = useState(d?.notes ?? a?.notes ?? '')
  const [prev, setPrev] = useState<string | null>(d?.prev_body ?? a?.prev_body ?? null)
  const [showChanges, setShowChanges] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [unchanged, setUnchanged] = useState(false)
  const [asks, setAsks] = useState<string[]>([])   // his requests for this email in this session (assist/revise.py)
  const base = useRef(a?.body ?? d?.first_body ?? '')   // the last text SleePO wrote: what differs is Sam's own wording
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [unknown, setUnknown] = useState<string[]>([])
  const [copied, setCopied] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [saving, setSaving] = useState<'' | 'busy' | 'done' | 'web'>('')
  const [openedIn, setOpenedIn] = useState<'desktop' | 'web'>('desktop')
  const [chatting, setChatting] = useState(false)
  const [jid, setJid] = usePersisted<string>(`assist-draft-job-${key}`, '')
  const first = useRef(d?.first_body ?? a?.body ?? '')   // what edits are measured against
  const askRef = useRef<HTMLTextAreaElement>(null)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const fills = countFills(body)
  const hasText = !!body.trim()

  // edits are kept a moment after Sam stops typing: on the draft, or on the task step for a recommended email
  const snap = () => JSON.stringify([to, cc, subject, body, ask])
  const saved = useRef(snap())
  const save = async () => {
    const now = snap()
    if (now === saved.current) return
    if (d) await api.draftEdit(d.id, { to: split(to), cc: split(cc), subject, body, ask })
    else if (r) {   // the step's actions as the server last had them (a revision may have changed them), this one as Sam has it
      const fresh = qc.getQueryData<DraftsData>(['drafts'])?.recommended.find((x) => x.key === r.key) ?? r
      await api.taskPatch(r.step_id, { actions: fresh.actions.map((x, i) => (i === r.index ? { ...x, to: split(to), cc: split(cc), subject, body } : x)) })
    }
    saved.current = now
  }
  const latest = useRef(save)
  latest.current = save
  useEffect(() => { const t = setTimeout(() => { latest.current().catch(() => { /* kept on the next change */ }) }, 700); return () => clearTimeout(t) }, [to, cc, subject, body, ask])
  useEffect(() => () => { latest.current().then(() => qc.invalidateQueries({ queryKey: ['drafts'] })).catch(() => {}) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // names typed in To or Cc become addresses when the field is left ("Gray" -> gray.selby@acme.example)
  const resolve = async (v: string, set: (s: string) => void) => {
    const names = split(v)
    if (!names.some((x) => !x.includes('@'))) { setUnknown([]); return }
    try { const res = await api.draftResolve(names); set(res.addresses.join(', ')); setUnknown(res.unknown) } catch { /* left as typed */ }
  }

  // follow a writing run to its end; the server keeps the result on the draft (or step) even if Sam has left
  const follow = async (id: string) => {
    for (let i = 0; i < 150; i++) {
      if (!alive.current) return
      const j = await api.draftJob(id)
      if (!j.running) {
        setJid('')
        if (!j.ok) throw new Error(j.error || 'No email came back')
        const data = await qc.fetchQuery({ queryKey: ['drafts'], queryFn: api.drafts })
        const nd = d ? data.sleepo.find((x) => x.id === d.id) : undefined
        const na = r ? data.recommended.find((x) => x.key === r.key)?.action : undefined
        const nb = nd?.body ?? na?.body ?? j.body
        const ns = nd?.subject ?? na?.subject ?? subject
        const nt = nd?.to ?? na?.to ?? []
        const np = nd?.prev_body ?? na?.prev_body ?? null
        if (!alive.current) return
        setBody(nb); setSubject(ns); if (!split(to).length && nt.length) setTo(nt.join(', '))
        setNotes(j.notes); setPrev(j.revised ? np : null); setShowChanges(false); setUnchanged(!!(j.revised && j.unchanged))
        if (!j.revised) setAsks([])
        base.current = nb
        if (!first.current) first.current = nb
        saved.current = JSON.stringify([!split(to).length && nt.length ? nt.join(', ') : to, cc, ns, nb, j.revised ? '' : ask])
        return
      }
      await new Promise((res) => setTimeout(res, 2000))
    }
  }
  useEffect(() => {   // back on this draft while it is being written: show it writing, then the email
    if (!jid) return
    setBusy(true)
    follow(jid).catch((e) => { setJid(''); if (alive.current) setErr(msg(e)) }).finally(() => { if (alive.current) setBusy(false) })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // write (no text yet, or fresh: a new one) or revise the text on screen with Sam's request (components/ReviseBar.tsx)
  const write = async (fresh = false, text = ask) => {
    if (busy) return
    if (!hasText && !text.trim() && !subject.trim()) { setErr('Say what the email should do, or give it a subject.'); askRef.current?.focus(); return }
    setBusy(true); setErr(''); setCopied(false); setSaving('')
    const revising = hasText && !fresh
    try {
      await save()
      const b = { ask: text, length, fresh, ...(revising ? { base: base.current, history: asks } : {}) }
      if (revising) setAsks((x) => [...x, text])
      const { job } = d ? await api.draftWrite(d.id, b) : await api.draftWriteStep(r!.step_id, r!.index, b)
      setJid(job)
      await follow(job)
    } catch (e) { setJid(''); if (alive.current) setErr(msg(e)) }
    if (alive.current) setBusy(false)
  }

  const copy = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    setConfirm(false)
    try { await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`); setCopied(true) } catch { setErr('The clipboard is not available here.'); return }
    if (r) api.feedback({ target_type: 'action', target_id: `task-${r.task_id}`, copied: true, edit_ratio: editRatio(first.current, body) })
  }
  const toOutlook = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    if (!split(to).length) { setErr('Add who it goes to.'); return }
    setConfirm(false); setErr(''); setSaving('busy')
    try {
      await save()
      const res = d ? await api.draftOutlook(d.id) : await api.taskOutlook(r!.step_id, { step: r!.index, to: split(to), cc: split(cc), subject, body })
      if (res.web_link) window.open(res.web_link, '_blank')
      setSaving('done')
    } catch (e) {
      const m = msg(e)
      if (/outlook-login|admin approval|Sign in once|401/i.test(m)) {
        // no Outlook write access until IT approves it (22 Oct 2026): a new message in Outlook for Mac, filled in (the web
        // only if the app cannot be opened; Sam, 28 Oct 2026)
        try { await navigator.clipboard.writeText(body) } catch { /* the text is in the message anyway */ }
        setOpenedIn(await openCompose(split(to).filter((x) => x.includes('@')), split(cc).filter((x) => x.includes('@')), subject, body))
        setSaving('web')
      } else { setSaving(''); setErr(m) }
    }
    if (r) api.feedback({ target_type: 'action', target_id: `task-${r.task_id}`, copied: true, edit_ratio: editRatio(first.current, body) })
  }
  const toChat = async () => {
    setChatting(true); setErr('')
    try { await save(); const { thread } = await api.draftChat({ to: split(to), cc: split(cc), subject, body, notes, ask, draft: d?.id }); openChatThread(thread) } catch (e) { setErr(msg(e)) }
    setChatting(false)
  }
  const discard = async () => {
    if (!d) return
    try {
      await api.draftEdit(d.id, { status: 'discarded' })
      qc.invalidateQueries({ queryKey: ['drafts'] })
      onGone(`Discarded “${subject || 'New email'}”`, async () => { await api.draftEdit(d.id, { status: 'draft' }); qc.invalidateQueries({ queryKey: ['drafts'] }) })
    } catch (e) { setErr(msg(e)) }
  }
  const accept = async () => {
    if (!r) return
    try {
      await save()
      await api.taskPatch(r.step_id, { status: 'open' })
      for (const k of ['drafts', 'tasks']) qc.invalidateQueries({ queryKey: [k] })
    } catch (e) { setErr(msg(e)) }
  }

  // what Sam asks for before there is any text (once there is, the bar inside the card revises it)
  const form = (
    <div className="px-4 py-3">
      <label htmlFor={`ask-${key}`} className="sr-only">What should the email say?</label>
      <div className="rounded-xl border border-line bg-bg transition-colors focus-within:border-ink">
        <textarea id={`ask-${key}`} ref={askRef} value={ask} onChange={(e) => setAsk(e.target.value)} rows={3}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void write() } }}
          placeholder={'What should it say? e.g. ask finance for the Q4 spend numbers by Thursday, for the board pack'}
          className="block w-full resize-y bg-transparent px-3 pb-1 pt-2.5 text-[13.5px] leading-relaxed text-ink outline-none placeholder:text-ink3" />
        <div className="flex flex-wrap items-center gap-1 px-2 pb-2">
          {NEW_INTENTS.map((t) => <button key={t} onClick={() => { setAsk(ask ? `${ask.trim()} ${t}.` : `${t}.`); askRef.current?.focus() }}
            className="rounded-full bg-panel2 px-2 py-0.5 text-[12px] text-ink2 transition-colors hover:bg-line hover:text-ink">{t}</button>)}
          <DictateButton target={askRef} className="ml-auto" />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {<div role="radiogroup" aria-label="Length" className="inline-flex rounded-full bg-panel2 p-0.5">
          {LENGTH_LABELS.map((l, i) => <button key={l} role="radio" aria-checked={length === i + 1} onClick={() => setLength(i + 1)}
            className={cn('rounded-full px-2.5 py-0.5 text-[12px] transition-colors', length === i + 1 ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>{l}</button>)}
        </div>}
        <button onClick={() => void write()} disabled={busy} title="Write it (⌘↵)"
          className={cn('ml-auto', 'inline-flex items-center gap-2 rounded-full bg-accent px-4 py-1.5 text-[13px] font-semibold text-onaccent hover:brightness-95 disabled:opacity-60')}>
          {busy ? <RefreshCw size={15} className="animate-spin" aria-hidden /> : <Sparkles size={15} aria-hidden />}{busy ? 'Writing…' : 'Write it'}</button>
      </div>
      {busy && <div className="mt-2 text-[12.5px] text-ink2">Reading what you know about the people and the topic. Usually under a minute.</div>}
    </div>
  )

  return (
    <div className="mx-auto max-w-[880px] px-3 py-3">
      {r && <div className="mb-2 rounded-xl bg-panel px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
          <span className="inline-flex items-center gap-1 rounded-full bg-accent px-2 text-[11.5px] font-semibold leading-[18px] text-onaccent"><Sparkles size={11} aria-hidden />Recommended</span>
          <a href={`#/tasks?open=${r.task_id}`} className="inline-flex min-w-0 items-center gap-1 font-medium text-ink no-underline hover:underline" title="Open the task"><ListChecks size={13} aria-hidden className="shrink-0" /><span className="truncate">{r.task_title}</span></a>
          {r.filed && <span className="text-ink3">· {r.filed}</span>}
          <span className="text-ink3">· {r.suggested ? 'suggested, not on your list yet' : 'on your task list'}</span>
        </div>
        {r.level === 'high' && <p className="mt-1.5 text-[12.5px] font-medium text-ink">Send first{r.rank_why.length > 0 && `: ${r.rank_why.join(', ')}`}</p>}
        {r.why && <p className="mt-1.5 text-[13px] leading-relaxed text-ink2">{r.why}</p>}
        {r.sources.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1.5">{r.sources.map((s) => s.url
          ? <a key={s.label + s.url} href={s.url} target={s.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className="max-w-full truncate rounded-full border border-line px-2 py-px text-[12px] text-ink no-underline hover:border-ink">{s.label}</a>
          : <span key={s.label} className="max-w-full truncate rounded-full border border-line px-2 py-px text-[12px] text-ink2">{s.label}</span>)}</div>}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {r.suggested && <button onClick={() => void accept()} className={cn(toolBtn, 'border border-line py-1')}><Check size={13} aria-hidden />Add to my tasks</button>}
          {onExclude && <button onClick={onExclude} title={r.suggested ? 'Remove it: SleePO will not suggest it again (#)' : 'Remove it from Drafts; the step stays on your task (#)'}
            className={cn(toolBtn, 'py-1')}><X size={13} aria-hidden />Remove from Drafts</button>}
        </div>
      </div>}
      <article aria-label="New email" className="rounded-xl border border-dashed border-ink3/60 bg-panel">
        <div className="flex items-start gap-3 px-4 pt-3">
          <Avatar p={me ?? { name: myName(), avatar: '' }} size={36} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="text-[14px] font-semibold">You</span>
              <span className="inline-flex items-center gap-1 rounded-full bg-accentbg px-2 text-[11.5px] font-semibold leading-[18px] text-ink"><PenLine size={11} aria-hidden />{hasText ? 'Draft' : 'New email'}</span>
              {d?.in_outlook && <a href={d.in_outlook} target="_blank" rel="noopener" className="text-[12px] text-ink3 hover:text-ink">also in your Outlook drafts ↗</a>}
              {hasText && notes && prev == null && <button onClick={() => setShowNotes(!showNotes)} aria-expanded={showNotes} aria-label="SleePO's notes on this email" title={showNotes ? 'Hide SleePO’s notes' : `SleePO’s notes: ${notes}`}
                className={cn('ml-auto grid size-6 place-items-center rounded-full text-ink3 hover:bg-panel2 hover:text-ink', showNotes && 'bg-panel2 text-ink')}><Info size={13} aria-hidden /></button>}
              {hasText && (fills > 0 ? <span className={cn(!(notes && prev == null) && 'ml-auto', 'inline-flex items-center gap-1 rounded-full border border-hot px-2 text-[11.5px] font-medium leading-[18px] text-hot')}>{fills} to fill in</span>
                : <span className={cn(!(notes && prev == null) && 'ml-auto', 'inline-flex items-center gap-1 text-[12px] text-ink3')}><Check size={12} aria-hidden />ready to send</span>)}
            </div>
            <label className="mt-0.5 flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-12 shrink-0">To</span>
              <input value={to} onChange={(e) => setTo(e.target.value)} onBlur={() => void resolve(to, setTo)} placeholder={hasText || ask ? 'names or addresses' : 'names or addresses (or leave it: SleePO picks them from what you ask)'} aria-label="To" className={field} />
              {!showCc && <button onClick={() => setShowCc(true)} className="shrink-0 text-[12px] text-ink3 hover:text-ink">Cc</button>}</label>
            {showCc && <label className="flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-12 shrink-0">Cc</span>
              <input value={cc} onChange={(e) => setCc(e.target.value)} onBlur={() => void resolve(cc, setCc)} placeholder="names or addresses" aria-label="Cc" className={field} /></label>}
            {unknown.length > 0 && <div className="text-[12px] text-hot">No address found for {unknown.join(', ')}: type the address.</div>}
            <label className="flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-12 shrink-0">Subject</span>
              <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder={hasText ? 'Subject' : 'Subject (optional: SleePO writes one)'} aria-label="Subject" className={cn(field, 'font-medium')} /></label>
            {split(to).length > 0 && <div className="mt-1 flex items-center gap-1">{split(to).slice(0, 5).map((x) => { const n = nameOf(x); return <Avatar key={x} p={who(n) ?? { name: n, avatar: '' }} size={18} /> })}</div>}
          </div>
        </div>
        {hasText ? <>
          {showNotes && notes && prev == null && <p className="mx-4 mt-2 rounded-lg bg-panel2 px-3 py-1.5 text-[12.5px] leading-relaxed text-ink2 md:ml-[64px]">{notes}</p>}
          <div className="px-4 pb-2 pt-1 md:pl-[64px]">
            {prev != null && showChanges
              ? <div className="whitespace-pre-wrap py-1 text-[14px] leading-[1.65] text-ink">{diffRedline(prev, body).map((p, i) => p.type === 'same' ? <span key={i}>{p.text}</span>
                  : p.type === 'add' ? <ins key={i} className="rounded-sm bg-accent text-onaccent no-underline">{p.text}</ins>
                  : <del key={i} className="rounded-sm bg-hot/10 text-hot decoration-hot/70">{p.text}</del>)}</div>
              : <FillEditor bare value={body} onChange={(v) => { setBody(v); setConfirm(false); setSaving('') }} rewrite={{ kind: 'email', subject }} rows={Math.min(24, Math.max(6, body.split('\n').length + 1))} />}
          </div>
          {confirm && <div className="mx-4 mb-2 rounded-lg border-l-2 border-l-hot bg-panel2 px-3 py-2 text-[13px] md:ml-[64px]">{fills} highlighted placeholder{fills > 1 ? 's are' : ' is'} still in the text. Fill {fills > 1 ? 'them' : 'it'} in, or press the button again to continue anyway.</div>}
          <footer className="flex flex-wrap items-center gap-1.5 border-t border-line2 px-4 py-2 md:pl-[60px]">
            <button onClick={() => void copy()} className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3.5 py-1.5 text-[13px] font-medium text-bg transition-opacity hover:opacity-90">
              {copied ? <Check size={14} aria-hidden /> : <ClipboardCopy size={14} aria-hidden />}{confirm ? 'Copy anyway' : copied ? 'Copied' : 'Copy'}</button>
            <button onClick={() => void toOutlook()} disabled={saving === 'busy'} title="Save this email as a draft in your Outlook and open it there. Nothing is sent." className={cn(toolBtn, 'py-1.5 disabled:opacity-60')}>
              {saving === 'busy' ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : saving === 'done' || saving === 'web' ? <Check size={14} aria-hidden /> : <OutlookLogo size={14} />}
              {saving === 'busy' ? 'Saving to Outlook…' : saving === 'done' ? 'In your Outlook drafts' : saving === 'web' ? 'Opened in Outlook' : confirm ? 'Open anyway' : 'Open in Outlook'}</button>
            {d && <button onClick={() => void discard()} title="Discard this draft" aria-label="Discard this draft" className="ml-auto rounded-full p-1.5 text-ink3 hover:bg-panel2 hover:text-ink"><Trash2 size={14} aria-hidden /></button>}
            {!d && <span className="ml-auto text-[12px] text-ink3 max-sm:hidden">Nothing is sent from here.</span>}
          </footer>
          {saving === 'web' && <div className="px-4 pb-3 text-[12.5px] text-ink2 md:pl-[64px]">{openedIn === 'desktop' ? 'Opened as a new message in Outlook, filled in (the text is also copied).' : 'Opened in Outlook on the web, filled in (the text is also copied): the Outlook app could not be opened.'}</div>}
        </> : <div className="border-t border-line2">{form}</div>}
        {err && <div role="alert" className="px-4 pb-3 text-[12.5px] text-hot md:pl-[64px]">{err}</div>}
      </article>
      {/* changing it: under the card, outside its dashed edge (components/ReviseBar.tsx) */}
      {hasText && <>
        {prev != null && <RevisedStrip note={notes} unchanged={unchanged} showChanges={showChanges} setShowChanges={setShowChanges}
          onUndo={() => { setBody(prev); setPrev(null); setShowChanges(false); setUnchanged(false); setAsks((x) => x.slice(0, -1)) }} />}
        <ReviseBar busy={busy} focus={startTweak} onChat={() => void toChat()} chatting={chatting} onRevise={(t) => void write(false, t)} onFresh={(t) => void write(true, t)} />
      </>}
    </div>
  )
}
