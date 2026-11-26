// The answer panel's Draft response tab: the composer, its lengths, and files to draw on. What the reply should say, and with a
// draft on screen what should change, are typed in the assistant pill at the bottom of the tab (Sam, 17 Nov 2026: the Messages
// pill, "part of the draft response at the bottom"; components/AssistPill.tsx): Draft the reply, or Revise and Write new as two
// equal buttons (Sam, 16 Nov 2026). No quick asks under it (Sam, 17 Nov 2026: "clunky").
import { useEffect, useRef, useState, type RefObject } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, Check, ChevronDown, ClipboardCopy, ExternalLink, Info, FileText, Forward, Link2, MessageSquarePlus, Paperclip, PenLine, RefreshCw, Reply, ReplyAll, RotateCcw, Upload, X } from 'lucide-react'
import { api, type ReplyAttachment, type Addr, type MailFull, type ReplyJob } from '@/lib/api'
import { cn, editRatio, usePersisted } from '@/lib/util'
import { Avatar } from '@/components/ui'
import { DocChip } from '@/components/DocChip'
import { FillEditor, countFills } from '@/components/FillEditor'
import { FillQuestions } from '@/components/FillQuestions'
import { RevisedStrip } from '@/components/ReviseBar'
import { AssistPill, type PillAction } from '@/components/AssistPill'
import { OutlookLogo } from '@/components/OutlookLogo'
import { openCompose } from '@/lib/outlook'
import { USE_DRAFT } from '@/components/Chat'
import { diffRedline } from '@/lib/diff'
import { type Entry, type Mode, isMe, nm, shortWhen, toolBtn } from './model'
import { myName } from '@/lib/profile'

// ---- the reply: what it should say, how long, then the draft to edit and copy into Mail or Outlook
const LENGTH_LABELS = ['One line', 'Brief', 'Standard', 'Detailed', 'Thorough']
const MODE_TABS: Record<Mode, [string, typeof Reply]> = { reply: ['Reply', Reply], replyall: ['Reply all', ReplyAll], followup: ['Follow up', MessageSquarePlus], forward: ['Forward', Forward] }

export function Composer({ m, d, mode, setMode, askRef }: { m: Entry; d?: MailFull; mode: Mode; setMode: (k: Mode) => void; askRef: RefObject<HTMLTextAreaElement | null> }) {
  const [length, setLength] = usePersisted<number>('assist-reply-length', 3)   // 1 one line … 5 thorough (assist/replies.py LENGTHS)
  const [job, setJob] = useState<ReplyJob | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [body, setBody] = useState('')
  const [copied, setCopied] = useState(false)
  const [add, setAdd] = useState('')
  const [confirm, setConfirm] = useState(false)
  const atts = useQuery({ queryKey: ['replyAtts', m.id], queryFn: () => api.replyAttachments(m.id) })
  // mail waiting on Sam opens with the recommended reply written in the background; until it is there, look again every 20 s
  const pre = useQuery({ queryKey: ['replyPredraft', m.id], queryFn: () => api.replyPredraft(m.id), enabled: !m.sent,
    refetchInterval: (q) => (m.needs && !q.state.data?.predraft ? 20_000 : false) })
  const pd = pre.data?.predraft?.status === 'ok' ? pre.data.predraft : null
  const [fromPre, setFromPre] = useState(false)   // the draft on screen is the pre-draft, untouched by a regenerate
  // the reply Sam was working on (Use in reply from the chat, or his own edits), kept across leaving the email
  // (assist/reply_working.py, Sam 22 Oct 2026): it wins over the recommended reply, and edits are kept as he types
  const working = useQuery({ queryKey: ['replyWorking', m.id], queryFn: () => api.replyWorking(m.id), staleTime: 0, refetchOnMount: 'always', enabled: !m.sent })
  const wk = working.data?.working ?? null
  const ready = m.sent || working.isFetchedAfterMount || working.isError   // a fresh read: a cached one may predate Use in reply
  const [kept, setKept] = useState<{ source: 'chat' | 'edit' | 'generated'; at: string } | null>(null)
  // a draft still being written when Sam left this email: followed again when he comes back (the job runs on the server
  // regardless, and keeps its result as his working copy: assist/replies.py run_job)
  const [jid, setJid] = usePersisted<string>(`assist-reply-job-${m.id}`, '')
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const savedText = useRef<string | null>(null)   // the text last kept or loaded: loading a draft is not an edit
  const tookWorking = useRef(false)
  const [notes, setNotes] = useState(false)   // SleePO's notes: a small icon in the card's header (what the draft relied on)
  const peopleQ = useQuery({ queryKey: ['people'], queryFn: api.people })
  const me = peopleQ.data?.find((p) => p.status === 'me')
  useEffect(() => {
    if (!ready || tookWorking.current || !wk) return
    tookWorking.current = true
    savedText.current = wk.body
    setJob({ running: false, ok: true, subject: pd?.subject ?? '', body: wk.body, notes: pd?.notes ?? '', error: '', reply_to: '' })
    setBody(wk.body); setFromPre(false); setKept({ source: wk.source, at: wk.updated_at })
    if (wk.mode && wk.mode !== mode && (['reply', 'replyall', 'followup', 'forward'] as Mode[]).includes(wk.mode as Mode)) setMode(wk.mode as Mode)
  }, [ready]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!pd || job || !ready || wk) return   // Sam's own version, when there is one, comes first
    savedText.current = pd.body ?? ''
    setJob({ running: false, ok: true, subject: pd.subject ?? '', body: pd.body ?? '', notes: pd.notes ?? '', error: '', reply_to: '' })
    setBody(pd.body ?? ''); setFromPre(true)
    // the response the draft chose (Sam, 22 Oct 2026: needs response, not needs reply): reply all, or a forward to his team
    if (pd.mode && pd.mode !== mode && (['reply', 'replyall', 'forward'] as Mode[]).includes(pd.mode)) setMode(pd.mode)
    try { const to: string[] = JSON.parse(pd.recipients || '[]'); if (to.length) setAdd(to.join(', ')) } catch { /* none */ }
  }, [pd?.created_at, ready]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {   // keep Sam's text a moment after he stops typing (or after a regenerate), so it is there when he comes back
    if (!job || !ready || m.sent) return
    if (savedText.current === null) { savedText.current = body; return }
    if (body === savedText.current) return
    const t = setTimeout(() => {
      api.replyWorkingPut(m.id, { body, mode, source: 'edit' }).then(() => { savedText.current = body; setKept({ source: 'edit', at: new Date().toISOString() }) }).catch(() => { /* kept next time */ })
    }, 800)
    return () => clearTimeout(t)
  }, [body]) // eslint-disable-line react-hooks/exhaustive-deps
  const backToRecommended = () => {   // drop Sam's kept version and show the recommended reply again
    if (!pd) return
    api.replyWorkingPut(m.id, { body: '', source: 'edit' }).catch(() => {})
    savedText.current = pd.body ?? ''; setBody(pd.body ?? ''); setFromPre(true); setKept(null); setConfirm(false)
  }
  // No Continue in chat here (Sam, 16 Nov 2026): Ask SleePO's floating button opens a chat on this email with its thread and
  // this draft (assist/page_context.py), and its reply card's Use in reply comes back below.
  useEffect(() => {   // a draft Sam took back from the chat (Use in reply): now, or waiting for this email to open
    const key = `${USE_DRAFT}-${m.id}`
    const take = (text: string) => { tookWorking.current = true; savedText.current = text; setBody(text); setFromPre(false); setKept({ source: 'chat', at: new Date().toISOString() })
      setJob((j) => j ?? { running: false, ok: true, subject: '', body: text, notes: '', error: '', reply_to: '' }); setConfirm(false); setCopied(false) }
    try { const v = sessionStorage.getItem(key); if (v != null) { sessionStorage.removeItem(key); take(v) } } catch { /* storage off */ }
    const on = (e: Event) => { const x = (e as CustomEvent<{ mail: number; body: string }>).detail; if (x?.mail === m.id) { try { sessionStorage.removeItem(key) } catch { /* */ } take(x.body) } }
    window.addEventListener(USE_DRAFT, on); return () => window.removeEventListener(USE_DRAFT, on)
  }, [m.id])
  const people = add.split(/[,;]/).map((x) => x.trim()).filter(Boolean)
  const fills = countFills(body)
  // who it goes to, as Mail would fill it in (the draft itself is pasted, so this is for reading)
  const notMe = (a: Addr) => !isMe(`${a.name} ${a.address}`)
  const to = !d ? m.from_name : mode === 'reply' ? nm(d.from) : mode === 'replyall' || mode === 'followup' ? [d.from, ...d.to].filter(notMe).map(nm).join(', ') : ''
  const cc = d && (mode === 'replyall' || mode === 'followup') ? d.cc.filter(notMe).map(nm).join(', ') : ''
  const modes: Mode[] = m.sent ? ['followup', 'forward'] : ['reply', 'replyall', 'forward']
  const what = mode === 'forward' ? 'forward' : mode === 'followup' ? 'follow-up' : 'reply'

  // follow a writing job to its end; stops quietly if Sam leaves the email (the job goes on and is picked up when he is back)
  const follow = async (id: string) => {
    for (let i = 0; i < 150; i++) {
      if (!alive.current) return
      const j = await api.replyJob(id)
      if (!j.running) {
        setJid('')
        if (!j.ok) throw new Error(j.error || 'No draft came back')
        tookWorking.current = true; savedText.current = j.body   // the job kept it already
        setJob(j); setBody(j.body); setFromPre(false); setKept({ source: 'generated', at: new Date().toISOString() })
        if (revising.current != null) { setPrev(revising.current); setShowChanges(false); setUnchanged(!!j.unchanged); revising.current = null }
        else { setPrev(null); setShowChanges(false); setUnchanged(false); setAsks([]) }
        return
      }
      await new Promise((r) => setTimeout(r, 2000))
    }
  }
  useEffect(() => {   // back on this email while its draft is being written: show it writing, then the draft
    if (!jid || m.sent) return
    setBusy(true); setErr('')
    follow(jid).catch((e) => { setJid(''); if (alive.current) setErr(String(e instanceof Error ? e.message : e)) }).finally(() => { if (alive.current) setBusy(false) })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // With a draft on screen, the box under the card revises it (components/ReviseBar.tsx, assist/revise.py; Sam, 28 Oct 2026):
  // his request, the text on screen, the last text SleePO wrote (the difference is his own wording, kept) and his earlier
  // requests for this draft. Write a new one starts from the thread. After a revision: what changed, Changes, Undo.
  const revising = useRef<string | null>(null)
  const [prev, setPrev] = useState<string | null>(null)
  const [showChanges, setShowChanges] = useState(false)
  const [unchanged, setUnchanged] = useState(false)
  const [asks, setAsks] = useState<string[]>([])
  const [running, setRunning] = useState<'draft' | 'revise' | 'fresh' | null>(null)   // which one is writing, for its spinner
  const generate = async (fresh = false, text = '') => {
    if (busy) return
    setBusy(true); setErr(''); setCopied(false); setRunning(fresh ? 'fresh' : job ? 'revise' : 'draft')
    try {
      if (mode === 'forward' && !people.length) throw new Error('Add who to forward it to.')
      const current = job && !fresh ? body : ''
      revising.current = current || null
      if (current) setAsks((a) => [...a, text])
      const { job: id } = await api.replyGenerate(m.id, text, mode, people, length, current, current ? job?.body ?? '' : '', current ? asks : [])
      setJid(id)
      await follow(id)
    } catch (e) { setJid(''); if (alive.current) setErr(String(e instanceof Error ? e.message : e)) }
    if (alive.current) { setBusy(false); setRunning(null) }
  }
  // Open in Outlook: the draft goes into Sam's Outlook as a real reply in the email's thread, then opens there (Sam,
  // 22 Oct 2026). Until IT approves SleePO's Outlook access, a new message opens in Outlook for Mac, filled in (Sam, 28 Oct
  // 2026: the desktop app, not the web; lib/outlook.ts openCompose, the web only if the app cannot be opened).
  const [saving, setSaving] = useState<'' | 'busy' | 'done' | 'web'>('')
  const toOutlook = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    setConfirm(false); setErr(''); setSaving('busy')
    try {
      const r = await api.replyOutlook(m.id, body, mode, people)
      if (r.web_link) window.open(r.web_link, '_blank')
      setSaving('done')
      api.feedback({ target_type: 'reply', target_id: String(m.id), copied: true, edit_ratio: editRatio(job?.body ?? '', body) })
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e)
      if (/outlook-login|admin approval|Sign in once|401/i.test(msg)) {
        const addrs = (xs: Addr[]) => xs.filter(notMe).map((a) => a.address).filter(Boolean)
        const toA = !d ? [] : mode === 'forward' ? people : mode === 'reply' ? addrs([d.from]) : addrs([d.from, ...d.to])
        const ccA = !d || mode === 'reply' || mode === 'forward' ? (mode === 'reply' ? people : []) : [...addrs(d.cc), ...people]
        const subj = job?.subject || `${mode === 'forward' ? 'Fw' : 'Re'}: ${m.subject}`
        try { await navigator.clipboard.writeText(body) } catch { /* no clipboard */ }
        const where = await openCompose(toA, ccA, subj, body)
        setSaving('web')
        setErr(where === 'desktop' ? 'Opened as a new message in Outlook (text also copied). It is not in the email’s thread until IT approves SleePO’s Outlook access.'
          : 'Opened as a new message in Outlook on the web (text also copied): the Outlook app could not be opened.')
        api.feedback({ target_type: 'reply', target_id: String(m.id), copied: true, edit_ratio: editRatio(job?.body ?? '', body) })
        return
      }
      setSaving(''); setErr(msg)
    }
  }
  const copy = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    setConfirm(false)
    await navigator.clipboard.writeText(body)
    setCopied(true)
    api.feedback({ target_type: 'reply', target_id: String(m.id), copied: true, edit_ratio: editRatio(job?.body ?? '', body) })
  }

  // the pill at the bottom of the tab: what the reply should say, or with a draft on screen what should change
  const first = to.split(',')[0].trim().split(/\s+/)[0]
  const actions: PillAction[] = !job
    ? [{ label: `Draft the ${what}`, icon: PenLine, busy, prompt: (t) => t, run: (t) => void generate(false, t), tip: `SleePO writes the ${what} in your voice, with what you typed (Enter)` }]
    : [{ label: 'Revise', icon: ArrowUp, needsText: true, busy: busy && running !== 'fresh', disabled: busy, prompt: (t) => t, run: (t) => void generate(false, t),
        tip: 'Revise: change this draft as you asked (Enter)' },
       { label: 'Write new', icon: RotateCcw, meta: true, busy: busy && running === 'fresh', disabled: busy, prompt: (t) => t, run: (t) => void generate(true, t),
        tip: 'Write new: start again from the thread, with what you typed if anything (⌘Enter)' }]
  const placeholder = busy ? (running === 'fresh' ? 'Writing a new one… usually 20 to 40 seconds' : running === 'revise' ? 'Revising… usually about 10 seconds' : 'Writing… usually under a minute')
    : job ? 'What should change? e.g. shorter and warmer, and say we need it by Friday' : `What should the ${what}${first ? ` to ${first}` : ''} say? Optional`
  const pill = (cls: string) => <AssistPill className={cls} inputRef={askRef} actions={actions}
    field={{ placeholder, label: job ? 'What should change in this draft?' : `What should the ${what} say?` }} />

  return (
    <div aria-label={`Your ${what}`}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3">
        <div role="tablist" aria-label="Reply type" className="flex rounded-full bg-panel2 p-0.5">
          {modes.map((k) => { const [l, Icon] = MODE_TABS[k]; return (
            <button key={k} role="tab" aria-selected={mode === k} onClick={() => setMode(k)} className={cn('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium transition-colors', mode === k ? 'bg-panel text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>
              <Icon size={13} aria-hidden />{l}</button>) })}
        </div>
        {!job && mode !== 'forward' && <div className="min-w-0 flex-1 truncate text-[13px] text-ink2">To <span className="font-medium text-ink">{to || '…'}</span>{cc && <> · Cc {cc}</>}</div>}
        {/* who to forward to / add to Cc: beside the switcher, not on a line of its own (Sam, 28 Oct 2026) */}
        {mode !== 'reply' && <input value={add} onChange={(e) => setAdd(e.target.value)} placeholder={mode === 'forward' ? 'Forward to: names or emails' : 'Add to Cc: names or emails'}
          aria-label={mode === 'forward' ? 'Forward to' : 'Add to Cc'} className="min-w-[220px] flex-1 rounded-full border border-line bg-bg px-3 py-1 text-[13px] text-ink outline-none placeholder:text-ink3 focus:border-ink" />}
        <DrawOn mailId={m.id} items={atts.data ?? []} className="ml-auto" />
      </header>

      {job ? <>
        {/* the draft as the next email of the thread: Sam's photo, to and subject, a dashed edge and a Draft tag (Sam, 22 Oct 2026) */}
        <article aria-label="Draft" className="mx-3 mt-3 rounded-xl border border-dashed border-ink3/60 bg-panel">
          <div className="flex items-start gap-3 px-4 pt-3">
            <Avatar p={me ?? { name: myName(), avatar: '' }} size={36} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="text-[14px] font-semibold">You</span>
                <span className="inline-flex items-center gap-1 rounded-full bg-accentbg px-2 text-[11.5px] font-semibold leading-[18px] text-ink"><PenLine size={11} aria-hidden />Draft</span>
                {fromPre && pd && <span className="text-[12px] text-ink3" title="Written in the background because this email is waiting on you">recommended · {shortWhen(pd.created_at)}</span>}
                {!fromPre && kept && <span className="text-[12px] text-ink3" title="Kept: it is here when you come back to this email">{kept.source === 'chat' ? 'from the chat' : kept.source === 'generated' ? 'written for you' : 'your version'} · {shortWhen(kept.at)}
                  {pd && <button onClick={backToRecommended} className="ml-1.5 underline decoration-line underline-offset-2 hover:text-ink">use the recommended reply</button>}</span>}
                {fromPre && pd?.mode && pd.mode !== 'reply' && mode === pd.mode && <span title={pd.why ?? ''} className="max-w-full truncate rounded-full bg-panel2 px-2 text-[11.5px] font-medium leading-[18px] text-ink">
                  {pd.mode === 'forward' ? 'Forward' : 'Reply all'}{pd.why ? ` · ${pd.why}` : ''}</span>}
                {job.notes && !prev && <button onClick={() => setNotes(!notes)} aria-expanded={notes} aria-label="SleePO's notes on this draft" title={notes ? 'Hide SleePO’s notes' : `SleePO’s notes: ${job.notes}`}
                  className={cn('ml-auto grid size-6 place-items-center rounded-full text-ink3 hover:bg-panel2 hover:text-ink', notes && 'bg-panel2 text-ink')}><Info size={13} aria-hidden /></button>}
                {fills > 0 ? <span className={cn(!(job.notes && !prev) && 'ml-auto', 'inline-flex items-center gap-1 rounded-full border border-hot px-2 text-[11.5px] font-medium leading-[18px] text-hot')}>{fills} to fill in</span>
                  : <span className={cn(!(job.notes && !prev) && 'ml-auto', 'inline-flex items-center gap-1 text-[12px] text-ink3')}><Check size={12} aria-hidden />ready to send</span>}
              </div>
              {mode === 'forward' ? <div className="truncate text-[12.5px] text-ink2">forward to {people.length ? people.join(', ') : <span className="text-hot">add who above</span>}</div>
                : <div className="truncate text-[12.5px] text-ink2" title={`To: ${to}${cc ? `\nCc: ${cc}` : ''}`}>to {to || '…'}{cc && <> · cc {cc}</>}{people.length > 0 && <> · cc {people.join(', ')}</>}</div>}
              <div className="truncate text-[12.5px] text-ink2">{job.subject || `Re: ${m.subject}`}</div>
            </div>
          </div>
          {notes && job.notes && !prev && <p className="mx-4 mt-2 rounded-lg bg-panel2 px-3 py-1.5 text-[12.5px] leading-relaxed text-ink2 md:ml-[64px]">{job.notes}</p>}
          <div className="px-4 pb-2 pt-1 md:pl-[64px]">
            {prev != null && showChanges
              ? <div className="whitespace-pre-wrap py-1 text-[14px] leading-[1.65] text-ink">{diffRedline(prev, body).map((p, i) => p.type === 'same' ? <span key={i}>{p.text}</span>
                  : p.type === 'add' ? <ins key={i} className="rounded-sm bg-accent text-onaccent no-underline">{p.text}</ins>
                  : <del key={i} className="rounded-sm bg-hot/10 text-hot decoration-hot/70">{p.text}</del>)}</div>
              : <FillEditor bare value={body} onChange={(v) => { setBody(v); setConfirm(false) }} rewrite={{ kind: 'email', item_id: m.id, subject: job?.subject || `Re: ${m.subject}` }} rows={Math.min(22, Math.max(6, body.split('\n').length + 1))} />}
          </div>
          {/* blanks in the draft: a few questions, as Claude asks, and the answers fill them (components/FillQuestions.tsx) */}
          {fills > 0 && <FillQuestions kind="email" itemId={m.id} draft={body} onFilled={(t) => { setBody(t); setConfirm(false) }} className="mx-4 mb-2 md:ml-[64px]" />}
          {confirm && <div className="mx-4 mb-2 rounded-lg border-l-2 border-l-hot bg-panel2 px-3 py-2 text-[13px] md:ml-[64px]">{fills} highlighted placeholder{fills > 1 ? 's are' : ' is'} still in the text. Fill {fills > 1 ? 'them' : 'it'} in, or press the button again to continue anyway.</div>}
          <footer className="flex flex-wrap items-center gap-1.5 border-t border-line2 px-4 py-2 md:pl-[60px]">
            <button onClick={copy} className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3.5 py-1.5 text-[13px] font-medium text-bg transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ink">
              {copied ? <Check size={14} aria-hidden /> : <ClipboardCopy size={14} aria-hidden />}{confirm ? 'Copy anyway' : copied ? 'Copied' : 'Copy'}</button>
            <button onClick={toOutlook} disabled={saving === 'busy' || !body.trim()} title="Open it in Outlook, filled in. Nothing is sent."
              className={cn(toolBtn, 'py-1.5 disabled:opacity-60')}>{saving === 'busy' ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : saving === 'done' ? <Check size={14} aria-hidden /> : <OutlookLogo size={14} />}
              {saving === 'busy' ? 'Saving to Outlook…' : saving === 'done' ? 'In your Outlook drafts' : saving === 'web' ? 'Opened in Outlook' : confirm ? 'Open anyway' : 'Open in Outlook'}</button>
          </footer>
        </article>
        {prev != null && <RevisedStrip className="mx-3" note={job.notes} unchanged={unchanged} showChanges={showChanges} setShowChanges={setShowChanges}
            onUndo={() => {   // kept at once, not after the typing pause: leaving the email right after Undo must not lose it
              setBody(prev); savedText.current = prev; setPrev(null); setShowChanges(false); setUnchanged(false); setAsks((a) => a.slice(0, -1))
              api.replyWorkingPut(m.id, { body: prev, mode, source: 'edit' }).then(() => setKept({ source: 'edit', at: new Date().toISOString() })).catch(() => setErr('Undo was not kept: edit the text once to keep it.'))
            }} />}
        {pill('mx-3 mb-3 mt-3')}
      </> : <div className="px-4 pb-3 pt-3">
        {m.needs && !pd && !busy && pre.isSuccess && <div className="mb-3 flex items-center gap-2 rounded-lg bg-panel2 px-3 py-2 text-[12.5px] text-ink2">
          <RefreshCw size={13} aria-hidden className="animate-spin motion-reduce:animate-none" />Drafting a recommended reply in the background. It appears here, or write one now.</div>}
        <div role="radiogroup" aria-label="Length" className="mb-3 inline-flex rounded-full bg-panel2 p-0.5">
          {LENGTH_LABELS.map((l, i) => <button key={l} role="radio" aria-checked={length === i + 1} onClick={() => setLength(i + 1)}
            className={cn('rounded-full px-2.5 py-0.5 text-[12px] transition-colors', length === i + 1 ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>{l}</button>)}
        </div>
        {pill('')}
      </div>}
      {err && <div role="alert" className="px-4 pb-3 text-[12.5px] text-hot">{err}</div>}
    </div>
  )
}

// ---- what the draft can draw on: attachments on the thread, documents it links to (assist/links.py) and files Sam added.
// A linked document SleePO cannot open (a new SharePoint sharing link) is flagged, with its link and Add a file: Sam downloads
// it (SleePO reads a file of that exact name from ~/Downloads) or adds it, and the reply, the document plan and the briefing
// then read it like an attachment.
const ADD_ACCEPT = '.pdf,.docx,.pptx,.xlsx,.txt,.csv,.md,.html,.htm,.rtf,.doc,.odt'
function DrawOn({ mailId, items, className }: { mailId: number; items: ReplyAttachment[]; className?: string }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [over, setOver] = useState(false)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['replyAtts', mailId] }); qc.invalidateQueries({ queryKey: ['documents'] }) }
  const add = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy(true); setErr('')
    try {
      for (const f of Array.from(files)) {
        const data = await new Promise<string>((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',', 2)[1] ?? ''); r.onerror = () => bad(new Error('Could not read the file')); r.readAsDataURL(f) })
        await api.mailAddFile(mailId, f.name, data)
      }
      refresh()
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    setBusy(false)
    if (input.current) input.current.value = ''
  }
  const remove = async (id: number) => { try { await api.mailRemoveFile(mailId, id); refresh() } catch (e) { setErr(String(e instanceof Error ? e.message : e)) } }
  const missing = items.filter((a) => a.link && !a.readable && a.share !== 'folder')
  const chip = 'inline-flex max-w-full items-center gap-1 rounded-full border border-line px-2 py-px align-baseline text-[12px] text-ink'
  // folded to one button (Sam, 22 Oct 2026: the list crowded the composer); a file SleePO cannot read shows on the button
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(!open)} aria-expanded={open} title="The files this draft reads: attachments in the thread, documents the email links to, files you added"
        onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); setOpen(true); add(e.dataTransfer.files) }}
        className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12.5px] transition-colors hover:bg-panel2', open && 'bg-panel2', over && 'outline outline-2 outline-accent', className)}>
        {busy ? <RefreshCw size={13} className="animate-spin" aria-hidden /> : <Paperclip size={13} aria-hidden />}
        <span className="text-ink">{items.length ? `${items.length} file${items.length > 1 ? 's' : ''}` : 'Add a file'}</span>
        {missing.length > 0 && <span className="font-medium text-hot">· {missing.length} not read</span>}
        <ChevronDown size={12} aria-hidden className={cn('text-ink3 transition-transform', open && 'rotate-180')} /></button>
      {open && <div onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files) }}
        className={cn('basis-full rounded-lg bg-panel2/60 p-2.5', over && 'outline outline-2 outline-offset-2 outline-accent')}>
        <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-ink2">
          {items.map((a) => (
            <span key={`${a.doc ?? a.link}-${a.name}`} className="inline-flex max-w-full flex-wrap items-center gap-x-1 [&>span]:whitespace-nowrap">
              {a.added ? <span className={chip} title="A file you added: its text is read like an attachment"><FileText size={12} aria-hidden />{a.name}</span>
                : a.doc ? <DocChip id={a.doc}>{a.name}</DocChip>
                : <a href={a.link} target="_blank" rel="noopener" className={cn(chip, 'no-underline hover:border-ink')} title={`Opens the link${a.share ? ` (${a.share})` : ''}`}><Link2 size={12} aria-hidden />{a.name}</a>}
              {a.link && a.doc && <Link2 size={11} aria-label="linked in the email" className="text-ink3" />}
              {a.where === 'Downloads' && <span title="Read from the file of that name in your Downloads folder">(from your Downloads)</span>}
              {a.added && <><span>(added by you)</span><button onClick={() => remove(a.id!)} title="Remove this file" aria-label={`Remove ${a.name}`} className="text-ink3 hover:text-ink"><X size={12} aria-hidden /></button></>}
              {!a.readable && <span className="text-hot">{a.share === 'folder' ? '(a folder: not read)' : '(not read)'}</span>}
              {!a.this_email && !a.added && <span className="text-ink3">(earlier in thread)</span>}
            </span>))}
          <button onClick={() => input.current?.click()} disabled={busy} title="Add a file for the draft to read (or drop one here): PDF, Word, PowerPoint, Excel, HTML or text"
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-line px-2 py-px text-[12px] text-ink2 hover:border-ink hover:text-ink disabled:opacity-60">
            {busy ? <RefreshCw size={12} className="animate-spin" aria-hidden /> : <Upload size={12} aria-hidden />}{busy ? 'Reading…' : 'Add a file'}</button>
        </div>
        {missing.length > 0 && (
          <div className="mt-2 rounded-lg border-l-2 border-l-hot bg-panel px-3 py-2 text-[12.5px] text-ink">
            SleePO cannot open {missing.map((a) => a.name).join(', ')} from {missing.length > 1 ? 'their links' : 'its link'}, so the draft will not use {missing.length > 1 ? 'them' : 'it'}.
            {' '}Open {missing.length > 1 ? 'each' : 'it'} and download the file: SleePO then reads it from your Downloads folder. Or add it here, or drop it on this box.
            <span className="mt-1.5 flex flex-wrap gap-2">
              {missing.map((a) => <a key={a.link} href={a.link} target="_blank" rel="noopener" className="inline-flex items-center gap-1 font-medium text-ink underline decoration-accent decoration-2 underline-offset-2"><ExternalLink size={12} aria-hidden />Open {a.name}</a>)}
            </span>
          </div>)}
      </div>}
      <input ref={input} type="file" multiple accept={ADD_ACCEPT} className="hidden" onChange={(e) => add(e.target.files)} />
      {err && <div role="alert" className="basis-full text-[12.5px] text-hot">{err}</div>}
    </>
  )
}
