// A document from an email: Sam says what it should be, SleePO plans it from everything it knows around the email (a
// tool-free run over the Actions context pack: the request in full, its attachments, meetings, documents, people, strategy
// and the CPO soul's rules for what goes out), Sam edits the plan, and Claude Cowork builds the file from SleePO's context
// in ~/SleePO Workspace (assist/deliverables.py). Nothing is sent: Sam reviews the file and sends it from Mail or Outlook.
// It is the Create document tab of the Inbox's answer panel, next to Reply (views/inbox/), which draws the frame. What it should
// be (or, with a plan on screen, what should be different) is typed in the assistant pill at the bottom of the tab (Sam,
// 17 Nov 2026; components/AssistPill.tsx).
import { useEffect, useState, type ReactNode, type RefObject } from 'react'
import { AlertTriangle, Check, ChevronDown, ClipboardCopy, FileSpreadsheet, FileText, MessageSquare, Presentation, RefreshCw, RotateCcw, Sparkles, X } from 'lucide-react'
import { api, type DeliverablePlan } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { useJob } from '@/lib/useJob'
import { ClaudeMark } from '@/components/ClaudeMark'
import { DocChip } from '@/components/DocChip'
import { FillEditor } from '@/components/FillEditor'
import { openChatThread } from '@/components/Chat'
import { AssistPill } from './AssistPill'

type Fmt = 'pptx' | 'docx' | 'xlsx'
const FORMATS: [Fmt | '', string, typeof FileText][] = [['', 'SleePO chooses', Sparkles], ['pptx', 'Deck', Presentation], ['docx', 'Document', FileText], ['xlsx', 'Workbook', FileSpreadsheet]]

export function DocumentCreator({ mailId, sendTo, askRef }: { mailId: number; sendTo: string; askRef?: RefObject<HTMLTextAreaElement | null> }) {
  const key = String(mailId)
  const [ask, setAsk] = useState('')
  const [fmt, setFmt] = useState<Fmt | ''>('')
  const [last, setLast] = usePersisted<string>(`assist-deliverable-last-${key}`, '')   // the last plan's job (its file is kept a day)
  const [starting, setStarting] = useState(false)
  const [err, setErr] = useState('')
  const [plan, setPlan] = useState<DeliverablePlan | null>(null)
  const [outline, setOutline] = useState('')
  const [openPart, setOpenPart] = useState<'' | 'covers' | 'gaps' | 'prompt'>('')   // the folded parts of a plan
  const [opening, setOpening] = useState<'' | 'busy' | 'done' | 'error'>('')
  const [msg, setMsg] = useState('')

  const take = (p: DeliverablePlan) => { setPlan(p); setOutline(p.outline.join('\n')); setOpening(''); setMsg('') }
  // a running plan is followed until it ends and picked up again on coming back (lib/useJob.ts); a finished one from earlier
  // today is shown again from its job file
  const run = useJob(`assist-deliverable-${key}`, api.deliverableJob, {
    onDone: (j) => { if (!j.plan) { setErr('No plan came back'); return } if (j.ask && !ask) setAsk(j.ask); take(j.plan) },
    onError: setErr,
  })
  const busy = starting || run.busy
  useEffect(() => {   // back on this email: the plan from earlier today, if its file is still there
    if (!last || run.jobId) return
    let live = true
    api.deliverableJob(last).then((j) => { if (live && !j.running && j.ok && j.plan) { if (j.ask) setAsk(j.ask); take(j.plan) } }).catch(() => setLast(''))
    return () => { live = false }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  const planIt = async (text: string) => {
    if (busy) return
    setStarting(true); setErr(''); setAsk(text)
    try {
      const { job } = await api.deliverablePlan(mailId, text, fmt || null)
      setLast(job); run.follow(job)
    }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    setStarting(false)
  }
  const set = (k: keyof DeliverablePlan, v: unknown) => setPlan((p) => (p ? { ...p, [k]: v } : p))
  // Refine in chat: a conversation that starts from the plan as edited here, with its context pack in the conversation's
  // folder (assist/deliverables.py to_chat); the chat's Claude button then builds the file in Claude Desktop from it
  const [chatting, setChatting] = useState(false)
  const toChat = async () => {
    if (!plan) return
    setChatting(true); setMsg('')
    try {
      const spec = { ...plan, outline: outline.split('\n').map((x) => x.trim()).filter(Boolean), ask }
      const { thread } = await api.deliverableChat(mailId, spec)
      openChatThread(thread)
    } catch (e) { setOpening('error'); setMsg(String(e instanceof Error ? e.message : e)) }
    setChatting(false)
  }
  const create = async () => {
    if (!plan) return
    setOpening('busy'); setMsg('')
    try {
      const spec = { ...plan, outline: outline.split('\n').map((x) => x.trim()).filter(Boolean) }
      const r = await api.deliverableOpen(mailId, spec)
      const k = r.context_chars ? `${Math.round(r.context_chars / 1000)}k characters of context` : 'its context'
      setMsg(`Opened in Claude Cowork with ${k}${r.start_from ? `, building on “${r.start_from}” (a copy)` : ''}${r.sources?.length ? ` and ${r.sources.length} source file${r.sources.length > 1 ? 's' : ''}` : ''}. `
        + `Press send there. The file is saved in ${r.workspace?.replace(/^.*\/(SleePO Workspace\/)/, '$1') ?? 'SleePO Workspace'}; review it, then ${sendTo ? `send it to ${sendTo}` : 'share it'} yourself.`)
      setOpening('done')
    } catch (e) { setOpening('error'); setMsg(String(e instanceof Error ? e.message : e)) }
  }

  // the pill at the bottom of the tab: what it should be; with a plan on screen, what should be different (planned again from
  // the first request with it)
  const pill = <AssistPill className="mx-3 mb-3 mt-1" inputRef={askRef}
    field={{ label: plan ? 'What should be different?' : 'What should the document be?',
      placeholder: busy ? 'Planning… usually under a minute' : plan ? 'What should be different? e.g. five slides, and lead with the decision'
        : 'What should it be? e.g. the Q4 plan they asked for, ten slides at most. Optional' }}
    actions={[plan
      ? { label: 'Plan again', icon: RotateCcw, busy, prompt: (t) => t, run: (t) => void planIt([ask, t].filter(Boolean).join('. ')), tip: 'Plan it again, with what should be different (Enter)' }
      : { label: 'Plan it', icon: Sparkles, busy, prompt: (t) => t, run: (t) => void planIt(t), tip: 'SleePO plans it from the email and everything around it; Claude builds it (Enter)' }]} />
  const form = (
    <div className="pt-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-3">
        <span className="min-w-0 flex-1 text-[13px] text-ink2">A deck, document or workbook{sendTo ? ` for ${sendTo}` : ''}: SleePO plans it, Claude builds it.</span>
        <div role="radiogroup" aria-label="Format" className="inline-flex rounded-full bg-panel2 p-0.5">
          {FORMATS.map(([k, l, Icon]) => <button key={l} role="radio" aria-checked={fmt === k} onClick={() => setFmt(k)}
            className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] transition-colors', fmt === k ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}><Icon size={12} aria-hidden />{l}</button>)}
        </div>
      </div>
      {pill}
    </div>
  )
  const Icon = (FORMATS.find(([k]) => k === plan?.format)?.[2]) ?? FileText
  const steps = outline.split('\n').filter((x) => x.trim()).length
  const fold = (k: 'covers' | 'gaps' | 'prompt', label: ReactNode, show: boolean) => show && (
    <button onClick={() => setOpenPart(openPart === k ? '' : k)} aria-expanded={openPart === k}
      className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2', openPart === k && 'bg-panel2')}>
      {label}<ChevronDown size={12} aria-hidden className={cn('text-ink3 transition-transform', openPart === k && 'rotate-180')} /></button>)

  return (
    <div aria-label="Create a document">
      {!plan ? form : <>
        {/* the plan as the document it will become: format, title and audience in place, then the outline */}
        <article aria-label="Document plan" className="mx-3 mt-3 rounded-xl border border-line bg-panel">
          <div className="flex items-start gap-3 px-4 pt-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accentbg"><Icon size={18} aria-hidden /></span>
            <div className="min-w-0 flex-1">
              {/* title and audience grow to fit (field-sizing), so a long title is never cut off */}
              <textarea value={plan.title} onChange={(e) => set('title', e.target.value.replace(/\n/g, ' '))} aria-label="Title" placeholder="Title" rows={1}
                className="block w-full resize-none rounded bg-transparent text-[15px] font-semibold leading-snug text-ink outline-none [field-sizing:content] placeholder:text-ink3 focus:bg-panel2" />
              <div className="flex items-start gap-1 text-[12.5px] text-ink2"><span className="pt-px">for</span>
                <textarea value={plan.audience} onChange={(e) => set('audience', e.target.value.replace(/\n/g, ' '))} aria-label="Audience" placeholder="who it is for" rows={1}
                  className="block min-w-0 flex-1 resize-none rounded bg-transparent leading-snug text-ink2 outline-none [field-sizing:content] placeholder:text-ink3 focus:bg-panel2" /></div>
            </div>
            <div role="radiogroup" aria-label="Format of the document" className="flex shrink-0 rounded-full bg-panel2 p-0.5">
              {FORMATS.slice(1).map(([k, l, I]) => <button key={l} role="radio" aria-checked={plan.format === k} onClick={() => set('format', k)} title={l}
                className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] transition-colors', plan.format === k ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}><I size={12} aria-hidden /><span className="max-sm:sr-only">{l}</span></button>)}
            </div>
          </div>
          <div className="px-4 pb-3 pt-2 md:pl-[68px]">
            <div className="mb-1 text-[12px] text-ink3">Outline · {steps} {plan.format === 'pptx' ? 'slide' : 'section'}{steps === 1 ? '' : 's'}, one per line</div>
            <textarea value={outline} onChange={(e) => setOutline(e.target.value)} aria-label="Outline" rows={Math.min(14, Math.max(4, outline.split('\n').length + 1))}
              className="w-full resize-y rounded-lg bg-panel2/60 px-3 py-2 text-[13.5px] leading-relaxed text-ink outline-none focus:bg-panel2" />
            {plan.doc && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink2">Builds on a copy of <DocChip id={plan.doc} />
              <button onClick={() => set('doc', null)} title="Start from scratch instead" aria-label="Start from scratch instead" className="text-ink2 hover:text-ink"><X size={13} aria-hidden /></button></div>}
          </div>
          <footer className="flex flex-wrap items-center gap-1.5 border-t border-line2 px-4 py-2 md:pl-[64px]">
            <button onClick={create} disabled={opening === 'busy' || !(plan.title || plan.prompt)} className="inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-1.5 text-[13px] font-semibold text-onaccent hover:brightness-95 disabled:opacity-60">
              {opening === 'busy' ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : opening === 'done' ? <Check size={14} aria-hidden /> : <ClaudeMark size={14} />}
              {opening === 'busy' ? 'Gathering context…' : `Create in Claude`}</button>
            <button onClick={toChat} disabled={chatting} title="Ask questions about the plan, change it or have it written in Ask SleePO"
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium text-ink transition-colors hover:bg-panel2 disabled:opacity-60">
              {chatting ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : <MessageSquare size={14} aria-hidden />}Refine in chat</button>
          </footer>
          {msg && <div className={cn('border-t border-line2 px-4 py-2 text-[12.5px] md:pl-[64px]', opening === 'error' ? 'text-hot' : 'text-ink2')}>{msg}</div>}
        </article>
        <div className="flex flex-wrap items-center gap-1 px-3 py-2">
          {fold('covers', <><Check size={13} aria-hidden />Answers {plan.covers.length}</>, plan.covers.length > 0)}
          {fold('gaps', <><AlertTriangle size={13} aria-hidden className="text-hot" /><span>{plan.gaps.length} not known yet</span></>, plan.gaps.length > 0)}
          {fold('prompt', <><ClaudeMark size={13} />Instruction for Claude</>, !!plan.prompt)}
        </div>
        {openPart === 'covers' && <ul className="mx-4 mb-3 space-y-0.5 rounded-lg bg-panel2 px-3 py-2 text-[12.5px]">{plan.covers.map((c) => <li key={c} className="flex items-start gap-1.5 text-ink2"><Check size={13} className="mt-0.5 shrink-0 text-ink" aria-hidden />{c}</li>)}</ul>}
        {openPart === 'gaps' && <div className="mx-4 mb-3 rounded-lg border-l-2 border-l-hot bg-panel2 px-3 py-2 text-[12.5px]"><span className="text-ink2">Claude marks these [FILL] for you:</span>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink2">{plan.gaps.map((g) => <li key={g}>{g}</li>)}</ul></div>}
        {openPart === 'prompt' && <div className="mx-4 mb-3 rounded-lg bg-panel2 p-3">
          <FillEditor value={plan.prompt} onChange={(v) => set('prompt', v)} rows={Math.min(12, Math.max(4, plan.prompt.split('\n').length + 2))} />
          <div className="mt-1.5 flex items-center gap-2 text-[11.5px] text-ink2">Your edits are what Claude gets. SleePO adds the email in full, its attachments, meetings, documents, people and strategy as a context file.
            <button onClick={async () => { try { await navigator.clipboard.writeText(plan.prompt) } catch { /* no clipboard */ } }} title="Copy the instruction" aria-label="Copy the instruction"
              className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 hover:bg-panel"><ClipboardCopy size={12} aria-hidden />Copy</button></div></div>}
        {pill}
      </>}
      {err && <div role="alert" className="px-4 pb-3 text-[12.5px] text-hot">{err}</div>}
    </div>
  )
}
