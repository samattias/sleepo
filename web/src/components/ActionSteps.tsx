// The Actions page's working parts: what an action is about (the email it answers, the message, the open item, the meeting),
// and its steps done properly. A reply shows the email and drafts from the whole thread (assist/replies.py, the Inbox's
// writer); a deliverable is built by Claude Cowork from a context pack SleePO gathers (assist/action_context.py: the request in
// full, meetings, documents, people) with the existing draft attached. Nothing is sent from here.
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CalendarDays, Check, ChevronDown, ChevronRight, ClipboardCopy, ExternalLink, FileSpreadsheet, FileText, Mail, MessageSquare, MessageSquareQuote, Paperclip, Presentation, RefreshCw, Sparkles } from 'lucide-react'
import { api, type ActionSource, type Addr, type EmailInfo } from '@/lib/api'
import { cn, editRatio, usePersisted } from '@/lib/util'
import { Segmented, Tag } from '@/components/ui'
import { Body } from '@/components/Email'
import { DocChip } from '@/components/DocChip'
import { FillEditor, countFills } from '@/components/FillEditor'
import { ClaudeMark } from '@/components/ClaudeMark'
import type { Action } from '@/components/Actions'
import { DictateButton } from './Dictate'
import { TZ, LOCALE } from '@/lib/time'
import { mentionsMe } from '@/lib/profile'

const when = (iso?: string | null) => { try { return iso ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(iso)) : '' } catch { return '' } }
const day = (iso?: string | null) => { try { return iso ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short' }).format(new Date(iso.length === 10 ? iso + 'T12:00:00Z' : iso)) : '' } catch { return '' } }
const names = (xs: Addr[]) => xs.map((x) => (x.name || x.address).replace(/\s*\(.*\)$/, '')).filter(Boolean).join(', ')
const link = 'inline-flex items-center gap-1 text-[12px] text-ink2 underline decoration-line underline-offset-2 hover:text-ink hover:decoration-ink'
const btn = 'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-medium'   // pills, like every button (UI review, 30 Oct 2026)
const primary = cn(btn, 'border-accent bg-accent text-onaccent hover:brightness-95 disabled:opacity-60')
const secondary = cn(btn, 'border-line font-normal hover:border-ink')

type Src<K extends ActionSource['kind']> = Extract<ActionSource, { kind: K }>

// ---------------------------------------------------------------- what the action is about
export function SourceList({ sources }: { sources: ActionSource[] }) {
  const main = sources.filter((s) => s.closes && s.kind !== 'file' && s.kind !== 'other')
  const lead = main.length ? main : sources.filter((s) => s.kind === 'email' || s.kind === 'chat').slice(0, 1)
  const rest = sources.filter((s) => !lead.includes(s) && s.kind !== 'other')
  const [more, setMore] = useState(false)
  if (!lead.length && !rest.length) return null
  return (
    <div className="mb-3">
      {lead.length > 0 && <>
        <div className="mb-1.5 text-[11.5px] font-semibold text-ink2">{main.length ? 'What this answers' : 'What this is about'}</div>
        <div className="flex flex-col gap-2">{lead.map((s) => <Source key={s.ref} s={s} open />)}</div>
      </>}
      {rest.length > 0 && <div className="mt-2">
        <button onClick={() => setMore(!more)} aria-expanded={more} className="inline-flex items-center gap-1 text-[12px] text-ink2 hover:text-ink">
          {more ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />}Also based on {rest.length} {rest.length > 1 ? 'sources' : 'source'}
        </button>
        {more && <div className="mt-1.5 flex flex-col gap-2">{rest.map((s) => <Source key={s.ref} s={s} />)}</div>}
      </div>}
    </div>
  )
}

function Source({ s, open }: { s: ActionSource; open?: boolean }) {
  if (s.kind === 'email') return <EmailSource s={s} open={open} />
  if (s.kind === 'chat') return <ChatSource s={s} />
  if (s.kind === 'item') return <ItemSource s={s} open={open} />
  if (s.kind === 'meeting') return <MeetingSource s={s} />
  if (s.kind === 'file') return <a href={s.url} target={s.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className="inline-flex w-fit max-w-full items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[12.5px] text-ink no-underline hover:border-ink"><ExternalLink size={12} aria-hidden /><span className="truncate">{s.label.replace(/^(File|Document): /, '')}</span></a>
  return null
}

function EmailSource({ s, open: initial }: { s: EmailInfo; open?: boolean }) {
  const [open, setOpen] = useState(!!initial)
  const [all, setAll] = useState(false)
  const [rich, setRich] = useState(false)
  const [earlier, setEarlier] = useState(false)
  if (s.missing) return null
  const long = s.text.length > 900 || s.text.split('\n').length > 14
  return (
    <div className="border border-line bg-bg">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 px-3 py-2 text-left text-[12.5px]">
        <Mail size={13} className="shrink-0 self-center text-ink2" aria-hidden />
        <span className="font-semibold text-ink">{s.sent ? 'You' : s.from.name || s.from.address}</span>
        <span className="min-w-0 truncate text-ink2">to {names(s.to) || '…'}{s.cc.length ? ` · cc ${names(s.cc)}` : ''}</span>
        <span className="ml-auto shrink-0 tabular-nums text-ink2">{when(s.date)}</span>
        <span className="basis-full text-[13.5px] font-medium text-ink">{s.subject || '(no subject)'}</span>
        {!open && <span className="basis-full truncate text-ink2">{s.text.replace(/\s+/g, ' ').slice(0, 160)}</span>}
      </button>
      {open && <div className="border-t border-line2 px-3 py-2.5">
        {(s.needs_reply || s.answered) && <div className="mb-2">{s.needs_reply ? <Tag tone="pending">Waiting on you · {s.reply_why}</Tag> : <Tag tone="good">You replied</Tag>}</div>}
        {rich ? <MailRich id={s.item_id} />
          : <div className={cn('whitespace-pre-wrap text-[13.5px] leading-relaxed', long && !all && 'max-h-[260px] overflow-hidden')}>{s.text || '(only a summary of this email is stored)'}</div>}
        {s.attachments.length > 0 && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-ink2"><Paperclip size={12} aria-hidden />{s.attachments.join(' · ')}</div>}
        {earlier && <div className="mt-2 flex flex-col gap-2">{s.earlier.map((e) => (
          <div key={e.item_id} className="border-l-2 border-line pl-2.5 text-[12.5px] text-ink2"><b className="font-medium text-ink">{e.me ? 'You' : e.from}</b> · {when(e.date)}
            <div className="mt-0.5 whitespace-pre-wrap">{e.text}</div></div>))}</div>}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          {long && !rich && <button onClick={() => setAll(!all)} className={link}>{all ? 'Show less' : 'Show all'}</button>}
          {s.earlier.length > 0 && <button onClick={() => setEarlier(!earlier)} className={link}>{earlier ? 'Hide earlier messages' : `${s.earlier.length} earlier message${s.earlier.length > 1 ? 's' : ''}`}</button>}
          {s.full && <button onClick={() => setRich(!rich)} className={link}>{rich ? 'Plain text' : 'As formatted'}</button>}
          <Link to="/inbox" search={{ open: s.item_id }} className={link}>Open in Inbox</Link>
          {s.web_link && <a href={s.web_link} target="_blank" rel="noopener" className={link}><ExternalLink size={11} aria-hidden />{s.web_link.startsWith('message:') ? 'Open in Mail' : 'Open in Outlook'}</a>}
        </div>
      </div>}
    </div>
  )
}

// The email as it was formatted (sandboxed), loaded only when asked for
function MailRich({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['mailOne', id], queryFn: () => api.mailOne(id) })
  if (!q.data) return <div className="text-[12.5px] text-ink2">{q.isError ? 'Could not load the email.' : 'Loading…'}</div>
  return <Body m={q.data} />
}

// An email an open item came from: header and its words, loaded on demand
function MailById({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['mailOne', id], queryFn: () => api.mailOne(id) })
  const d = q.data
  if (!d) return <div className="text-[12.5px] text-ink2">{q.isError ? 'Could not load the email.' : 'Loading…'}</div>
  return (
    <div className="mt-2 border border-line bg-panel">
      <div className="flex flex-wrap items-baseline gap-x-2 border-b border-line2 px-3 py-1.5 text-[12.5px]">
        <Mail size={13} className="self-center text-ink2" aria-hidden /><b className="font-semibold">{d.from.name || d.from.address}</b>
        <span className="text-ink2">to {names(d.to)}</span><span className="ml-auto tabular-nums text-ink2">{when(d.ts)}</span>
        <span className="basis-full text-[13px] font-medium">{d.subject}</span>
      </div>
      <div className="p-2">{d.full ? <Body m={d} /> : <p className="text-[13px] text-ink2">{d.note || 'Only a summary of this email is stored.'}</p>}</div>
      <div className="flex gap-3 px-3 pb-2"><Link to="/inbox" search={{ open: id }} className={link}>Open in Inbox</Link></div>
    </div>
  )
}

function ChatSource({ s }: { s: Src<'chat'> }) {
  if (s.missing) return null
  return (
    <div className="border border-line bg-bg px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
        <MessageSquare size={13} className="shrink-0 self-center text-ink2" aria-hidden />
        <span className="font-semibold text-ink">{s.author}</span><span className="min-w-0 truncate text-ink2">in {s.source === 'slack' ? 'Slack' : 'Teams'} · {s.conversation}</span>
        <span className="ml-auto shrink-0 tabular-nums text-ink2">{when(s.date)}</span>
      </div>
      {s.earlier.length > 0 && <div className="mt-1.5 flex flex-col gap-1">{s.earlier.map((e, i) => <div key={i} className="truncate text-[12.5px] text-ink3"><b className="font-medium text-ink2">{e.author}</b>: {e.text.replace(/\s+/g, ' ')}</div>)}</div>}
      <div className="mt-1.5 whitespace-pre-wrap text-[13.5px] leading-relaxed">{s.text}</div>
      {s.web_link && <a href={s.web_link} target="_blank" rel="noopener" className={cn(link, 'mt-1.5')}><ExternalLink size={11} aria-hidden />Open the conversation</a>}
    </div>
  )
}

const ITEM_KIND: Record<string, string> = { promise: 'You owe', waiting: 'Owed to you', decision: 'Decision', reply: 'Reply owed' }

function ItemSource({ s, open }: { s: Src<'item'>; open?: boolean }) {
  const [mail, setMail] = useState(!!open && s.emails.length > 0 && s.item_kind !== 'decision')
  if (s.missing) return null
  const other = s.links.filter((l) => !/#\/mail\?open=/.test(l.url))
  return (
    <div className="border border-line bg-bg px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[11px] font-semibold text-ink2">{ITEM_KIND[s.item_kind] ?? s.item_kind}</span>
        <span className="text-[13.5px] font-medium leading-snug">{s.title}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-ink2">
        {s.who && <span>{s.who}</span>}{s.since && <span>· since {day(s.since)}</span>}{s.due && <span>· due {day(s.due)}</span>}
        {s.status !== 'open' && <span>· {s.status}</span>}
        <a href="#/loops" className={link}>Open items</a>
      </div>
      {s.detail && !s.said && <div className="mt-1 text-[12.5px] text-ink2">{s.detail}</div>}
      {s.said && <a href={`#/meetings/m-${s.said.meeting_id}?t=${s.said.t}`} className="mt-1 block text-[12.5px] text-ink2 no-underline hover:text-ink">
        <MessageSquareQuote size={12} className="-mt-0.5 mr-1 inline" aria-hidden />{s.said.me ? 'You' : s.said.name} said{s.said.clock ? ` at ${s.said.clock}` : ''}: “{s.said.quote}”</a>}
      {(s.emails.length > 0 || other.length > 0) && <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        {s.emails.length > 0 && <button onClick={() => setMail(!mail)} className={link}>{mail ? 'Hide the email' : 'Show the email it came from'}</button>}
        {other.map((l) => <a key={l.url} href={l.url} target={l.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className={cn(link, 'max-w-[300px] truncate')}>{l.label}</a>)}
      </div>}
      {mail && (s.email ? <div className="mt-2"><EmailSource s={s.email} open /></div> : s.emails.slice(0, 1).map((id) => <MailById key={id} id={id} />))}
    </div>
  )
}

function MeetingSource({ s }: { s: Src<'meeting'> }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 border border-line bg-bg px-3 py-2 text-[12.5px]">
      <CalendarDays size={13} className="shrink-0 self-center text-ink2" aria-hidden />
      <span className="font-semibold text-ink">{s.subject || 'Meeting'}</span>
      <span className="text-ink2">{when(s.start)}</span>
      {s.attendees && s.attendees.length > 0 && <span className="min-w-0 truncate text-ink2">· {s.attendees.slice(0, 5).map((a) => a.split('@')[0].replace(/[._]/g, ' ')).join(', ')}</span>}
      {s.event_id && <Link to="/prep" search={{ event: s.event_id }} className={cn(link, 'ml-auto')}>Meeting brief</Link>}
    </div>
  )
}

// ---------------------------------------------------------------- a reply: the email, what to say, a draft from the whole thread
const LENGTHS = ['One line', 'Brief', 'Standard', 'Detailed', 'Thorough']

// onUsed: a Tasks step logs what Sam did with it (assist/tasks.py log_action)
export function ReplyStep({ a, email, step, targetId, onUsed }: { a: Action; email: Src<'email'>; step: number; targetId: string; onUsed?: (what: string) => void }) {
  const [ask, setAsk] = useState(a.intent || a.why || '')
  const [text, setText] = useState(a.body ?? '')
  const [origin, setOrigin] = useState(a.body ?? '')   // what the edits are measured against: the first draft, or the full-thread one
  const [full, setFull] = useState(false)
  const [notes, setNotes] = useState('')
  const [mode, setMode] = useState<'reply' | 'replyall'>(email.to.length + email.cc.length > 1 ? 'replyall' : 'reply')
  const [length, setLength] = usePersisted<number>('assist-reply-length', 3)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState(false)
  const fills = countFills(text)

  const redraft = async () => {
    if (busy) return
    setBusy(true); setErr(''); setCopied(false)
    try {
      const { job } = await api.replyGenerate(email.item_id, ask, mode, [], length)
      for (let i = 0; i < 150; i++) {
        const j = await api.replyJob(job)
        if (!j.running) { if (!j.ok) throw new Error(j.error || 'No draft came back'); setText(j.body); setOrigin(j.body); setNotes(j.notes); setFull(true); break }
        await new Promise((r) => setTimeout(r, 2000))
      }
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    setBusy(false)
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      onUsed?.('reply copied')
      api.feedback({ target_type: full ? 'reply' : 'action', target_id: full ? String(email.item_id) : targetId, copied: true, edit_ratio: editRatio(origin, text) })
    } catch { setErr('The clipboard is not available here.') }
  }
  const to = mode === 'reply' ? (email.sent ? names(email.to) : email.from.name || email.from.address) : [email.sent ? '' : email.from.name, names(email.to.filter((x) => !mentionsMe(x.address))), names(email.cc.filter((x) => !mentionsMe(x.address)))].filter(Boolean).join(', ')
  return (
    <div className="relative py-2.5 pl-7">
      <span aria-hidden className="absolute left-0 top-[11px] inline-flex size-5 items-center justify-center rounded-full border border-line bg-panel text-[11px] tabular-nums text-ink2">{step}</span>
      <div className="flex flex-wrap items-start gap-2.5">
        <Mail size={15} className="mt-0.5 shrink-0 text-ink2" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium leading-snug">{a.label}</div>
          <div className="mt-0.5 text-[12px] text-ink2">Email reply · to {to || '…'} · copy and paste in Mail</div>
        </div>
        <Segmented label="Reply or reply all" value={mode} onChange={setMode} options={[['reply', 'Reply'], ['replyall', 'Reply all']] as const} />
      </div>
      <div className="mt-2 border border-line bg-panel2 p-3">
        <label className="mb-1 flex items-center gap-1.5 text-[12.5px] font-semibold"><Sparkles size={13} aria-hidden />What the reply should say</label>
        <div className="relative" data-dictate>
        <textarea value={ask} onChange={(e) => setAsk(e.target.value)} rows={2} onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); redraft() } }}
          className="w-full resize-y rounded-xl border border-line bg-bg p-2.5 pr-10 text-[13px] leading-relaxed text-ink outline-none focus:border-ink" />
          <span className="absolute bottom-2 right-2"><DictateButton /></span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Segmented label="Length" value={length} onChange={setLength} options={LENGTHS.map((l, i) => [i + 1, l] as const)} />
          <button onClick={redraft} disabled={busy} title="Draft from the whole thread, its attachments, your meetings and open items with these people (⌘↵)" className={cn(primary, 'ml-auto px-2.5 py-1 text-[12.5px]')}>
            {busy ? <RefreshCw size={13} className="animate-spin" aria-hidden /> : <Sparkles size={13} aria-hidden />}{busy ? 'Reading the thread…' : full ? 'Redraft' : 'Draft from the full thread'}</button>
        </div>
        {err && <div role="alert" className="mt-2 text-[12.5px] text-hot">{err}</div>}
        <div className="mb-1 mt-3 flex flex-wrap items-center gap-2 text-[12px] text-ink2">
          <b className="text-ink">{full ? 'Draft from the full thread' : 'Quick draft'}</b>{!full && <span>written with the action list; the full-thread draft reads the whole conversation</span>}
          {fills > 0 && <span className="ml-auto rounded-full border border-hot px-2 py-px font-medium text-hot">{fills} to fill in</span>}
        </div>
        <FillEditor value={text} onChange={(v) => { setText(v); setCopied(false) }} rows={Math.min(16, Math.max(5, text.split('\n').length + 1))} />
        {notes && <div className="mt-1.5 text-[12px] text-ink2"><b className="text-ink">Check:</b> {notes}</div>}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button onClick={copy} disabled={!text.trim()} className={cn(btn, 'border-ink bg-ink px-2.5 py-1 text-[12.5px] text-bg hover:opacity-90 disabled:opacity-50')}>
            {copied ? <Check size={13} aria-hidden /> : <ClipboardCopy size={13} aria-hidden />}{copied ? 'Copied' : 'Copy'}</button>
          {email.web_link && <a href={email.web_link} target="_blank" rel="noopener" className={cn(secondary, 'px-2.5 py-1 text-[12.5px] no-underline')}><ExternalLink size={13} aria-hidden />{email.web_link.startsWith('message:') ? 'Open in Mail' : 'Open in Outlook'}</a>}
          <span className="text-[11.5px] text-ink3">{mode === 'replyall' ? 'Reply all' : 'Reply'} there and paste. Nothing is sent from here.</span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- a deliverable or a think-through: Claude with SleePO's context pack
const FORMAT: Record<string, [string, typeof FileText]> = { pptx: ['PowerPoint deck', Presentation], docx: ['Word document', FileText], xlsx: ['Excel workbook', FileSpreadsheet], md: ['Markdown note', FileText] }

// act: how to open the step with its context (Actions items by default; Tasks pass their own, which logs it)
export function ClaudeStep({ a, step, index, targetId, act }: { a: Action; step: number; index: number; targetId: string
  act?: (index: number, prompt?: string) => Promise<{ context_chars?: number; start_from?: string; sources?: string[]; workspace?: string }> }) {
  const [prompt, setPrompt] = useState(a.prompt ?? '')
  const [edit, setEdit] = useState(false)
  const [state, setState] = useState<'' | 'busy' | 'done' | 'error'>('')
  const [msg, setMsg] = useState('')
  const chat = a.type === 'draft' && a.app !== 'cowork'
  const fmt = a.format ? FORMAT[a.format] : a.type === 'create' ? FORMAT.docx : null
  const Icon = fmt ? fmt[1] : Sparkles
  const run = async () => {
    setState('busy'); setMsg('')
    try {
      const r = await (act ?? ((i: number, p?: string) => api.todoAct(targetId, i, p)))(index, prompt !== (a.prompt ?? '') ? prompt : undefined)
      const k = r.context_chars ? `${Math.round(r.context_chars / 1000)}k characters of context` : 'its context'
      setMsg(chat ? `Opened a Claude chat with ${k} after your prompt. Press send there.`
        : `Opened in Claude Cowork with ${k}${r.start_from ? `, building on “${r.start_from}” (a copy)` : ''}${r.sources?.length ? ` and ${r.sources.length} source file${r.sources.length > 1 ? 's' : ''}` : ''}. Press send there; the file is saved in ${r.workspace?.replace(/^.*\/(SleePO Workspace\/)/, '$1') ?? 'SleePO Workspace'}.`)
      setState('done')
    } catch (e) { setState('error'); setMsg(String(e instanceof Error ? e.message : e)) }
  }
  return (
    <div className="relative py-2.5 pl-7">
      <span aria-hidden className="absolute left-0 top-[11px] inline-flex size-5 items-center justify-center rounded-full border border-line bg-panel text-[11px] tabular-nums text-ink2">{step}</span>
      <div className="flex flex-wrap items-start gap-2.5">
        <Icon size={15} className="mt-0.5 shrink-0 text-ink2" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium leading-snug">{a.label}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-ink2">
            <span>{chat ? 'Think it through · Claude chat' : `${fmt ? fmt[0] : 'Document'} · Claude Cowork`}</span>
            {a.title && <span className="text-ink">· “{a.title}”</span>}{a.audience && <span>· for {a.audience}</span>}
            {a.doc && <span className="inline-flex items-center gap-1">· builds on <DocChip id={a.doc} /></span>}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={run} disabled={state === 'busy'} className={cn(primary, 'px-2.5 py-1 text-[12.5px]')}>
            {state === 'busy' ? <RefreshCw size={13} className="animate-spin" aria-hidden /> : state === 'done' ? <Check size={13} aria-hidden /> : <ClaudeMark size={14} />}
            {state === 'busy' ? 'Gathering context…' : chat ? 'Open in Claude' : a.type === 'edit' ? 'Edit in Claude' : 'Create in Claude'}</button>
          <button onClick={async () => { try { await navigator.clipboard.writeText(prompt) } catch { /* no clipboard */ } }} title="Copy the instruction" aria-label="Copy the instruction" className={cn(secondary, 'px-1.5 py-1')}><ClipboardCopy size={13} aria-hidden /></button>
        </div>
      </div>
      {a.outline && a.outline.length > 0 && <ol className="mt-2 list-decimal space-y-0.5 border-l border-line2 pl-8 text-[12.5px] leading-snug text-ink2 marker:text-ink3">{a.outline.map((o, i) => <li key={i}>{o}</li>)}</ol>}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 text-[12px] text-ink2">
        <button onClick={() => setEdit(!edit)} className={link}>{edit ? 'Hide the instruction' : 'Review the instruction'}</button>
        <span>{chat ? 'The context follows your prompt in the chat.' : 'SleePO adds the request in full, meetings, documents and people as a context file, plus working copies of the files involved.'}</span>
      </div>
      {edit && <div className="mt-2 border border-line bg-panel2 p-3"><FillEditor value={prompt} onChange={setPrompt} rows={Math.min(12, Math.max(4, prompt.split('\n').length + 1))} />
        <div className="mt-1 text-[11.5px] text-ink2">Your edits are what Claude gets.</div></div>}
      {msg && <div className={cn('mt-2 text-[12.5px]', state === 'error' ? 'text-hot' : 'text-ink2')}>{msg}</div>}
    </div>
  )
}
