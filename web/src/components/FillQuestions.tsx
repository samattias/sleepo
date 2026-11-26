// Fill the blanks by answering a few questions (Sam, 22 Oct 2026), the way Claude asks a user (assist/fill_in.py). Shown under
// a draft, email or chat, only while it still has [FILL: …] blanks. The questions are prepared as soon as the blanks appear:
// one at a time, a header chip for each across the top, numbered options with a line on what each means (press 1-4), a tick
// box where several can apply, and Other for his own words. "Fill in" writes the answers into the draft as it stands, keeping
// his edits; a skipped question keeps its blank. Nothing is sent.
// In Ask SleePO (Sam, 19 Nov 2026: "there's no UX to do it") it sits under the chat's email and Teams/Slack cards, its
// questions reading the conversation (`tid`); only the newest version of a draft prepares them by itself (`auto`), older
// ones offer a button, and questions already prepared are kept for the tab's session so reopening a conversation does
// not ask the model again.
import { useEffect, useRef, useState } from 'react'
import { Check, ChevronLeft, RefreshCw, Sparkles } from 'lucide-react'
import { api, type FillJob, type FillQuestion } from '@/lib/api'
import { useJob } from '@/lib/useJob'
import { cn } from '@/lib/util'
import { FILL } from './FillEditor'

type Answer = { picked: string[]; other: string; on: boolean }   // on: Other is chosen
const blanksOf = (t: string) => [...new Set(t.match(FILL) ?? [])]
const plain = (l: string) => l.replace(/\s*\(Recommended\)\s*$/i, '')
// questions prepared for a draft's blanks, kept per card for the tab's session
const cached = (scope: string, key: string): FillQuestion[] | null => {
  try { const v = JSON.parse(sessionStorage.getItem(`assist-fill-qs:${scope}`) || 'null'); return v?.key === key && Array.isArray(v.qs) ? v.qs : null } catch { return null }
}
const keep = (scope: string, key: string, qs: FillQuestion[]) => {
  try { sessionStorage.setItem(`assist-fill-qs:${scope}`, JSON.stringify({ key, qs })) } catch { /* storage off: they are asked again next time */ }
}

export function FillQuestions({ kind, draft, itemId, ids, app, tid, scope: card, auto = true, onFilled, className }: {
  kind: 'email' | 'chat'; draft: string; itemId?: number; ids?: number[]; app?: 'teams' | 'slack'; onFilled: (text: string) => void; className?: string
  tid?: string | null     // the Ask SleePO conversation a chat card's draft was written in
  scope?: string          // the card's own key, where one email or conversation can have several drafts (the chat)
  auto?: boolean          // prepare the questions as soon as blanks appear; else wait for the button
}) {
  const marks = blanksOf(draft)
  const key = marks.join('|')
  // both steps are jobs followed by lib/useJob (a failed check is retried; coming back to the draft picks a running one up)
  const scope = card ?? (kind === 'email' ? `e${itemId ?? ''}` : `c${app ?? ''}${(ids ?? []).at(-1) ?? ''}`)
  const [qs, setQs] = useState<FillQuestion[] | null>(() => cached(scope, key))
  const [state, setState] = useState<'idle' | 'asking' | 'ready' | 'filling' | 'error'>(() => (qs ? 'ready' : 'idle'))
  const [err, setErr] = useState('')
  const [i, setI] = useState(0)
  const [ans, setAns] = useState<Record<string, Answer>>({})
  const [go, setGo] = useState(auto)
  const asked = useRef(qs ? key : '')   // the blanks the current questions were prepared for
  const other = useRef<HTMLInputElement>(null)
  const qJob = useJob<FillJob>(`assist-fill-q:${scope}`, api.fillJob, {
    onDone: (j) => { if (asked.current !== key) return; if (j.questions.length) { setQs(j.questions); setState('ready'); keep(scope, key, j.questions) } else { setErr(j.error || 'No questions came back.'); setState('error') } },
    onError: (msg) => { setErr(msg); setState('error') },
  })
  const aJob = useJob<FillJob>(`assist-fill-a:${scope}`, api.fillJob, {
    onDone: (j) => { if (j.body) onFilled(j.body); else setErr(j.error || 'The draft did not come back filled.'); setState('ready') },
    onError: (msg) => { setErr(msg); setState('ready') },
  })

  const ask = async () => {
    asked.current = key
    setState('asking'); setErr(''); setI(0); setAns({})
    try { qJob.follow((await api.fillQuestions({ kind, draft, item_id: itemId, ids, app, tid })).job) }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); setState('error') }
  }
  // new blanks (a new draft): prepare questions for them; blanks Sam filled by hand drop their questions
  useEffect(() => {
    if (!key) return
    if (qJob.jobId) { asked.current = key; setState('asking'); return }   // questions still being prepared from an earlier visit
    if (aJob.jobId) { asked.current = key; setState('filling'); return }  // answers still being written in
    if (go && !asked.current.split('|').some((b) => marks.includes(b)) && state !== 'asking') ask()
  }, [key, go]) // eslint-disable-line react-hooks/exhaustive-deps
  const live = (qs ?? []).filter((q) => !q.fills.length || q.fills.some((f) => marks.includes(f)))
  const q = live[Math.min(i, live.length - 1)]
  const a: Answer = (q && ans[q.id]) || { picked: [], other: '', on: false }
  const done = (x: FillQuestion) => { const v = ans[x.id]; return !!v && (v.picked.length > 0 || (v.on && !!v.other.trim())) }
  const set = (p: Partial<Answer>) => q && setAns((s) => ({ ...s, [q.id]: { ...a, ...p } }))
  const pick = (label: string) => {
    if (!q) return
    if (q.multi) set({ picked: a.picked.includes(label) ? a.picked.filter((x) => x !== label) : [...a.picked, label] })
    else set({ picked: [label], on: false })
  }
  const chooseOther = () => { set(q?.multi ? { on: !a.on } : { picked: [], on: true }); requestAnimationFrame(() => other.current?.focus()) }
  const last = i >= live.length - 1
  const fill = async () => {
    setState('filling'); setErr('')
    try {
      const answers = live.map((x) => { const v = ans[x.id]; return { question: x.question, fills: x.fills, answer: v ? [...v.picked.map(plain), ...(v.on && v.other.trim() ? [v.other.trim()] : [])] : [] } })
      aJob.follow((await api.fillAnswers({ kind, draft, app, answers })).job)
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setState('ready') }
  }
  const next = () => (last ? fill() : setI(i + 1))

  // keys while the card has focus: 1-4 pick, 5 Other, Enter next or fill
  const onKey = (e: React.KeyboardEvent) => {
    if (state !== 'ready' || !q) return
    const typing = (e.target as HTMLElement).tagName === 'INPUT'
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); next(); return }
    if (typing || e.metaKey || e.ctrlKey) return
    const n = Number(e.key)
    if (n >= 1 && n <= q.options.length) { e.preventDefault(); pick(q.options[n - 1].label) }
    else if (n === q.options.length + 1) { e.preventDefault(); chooseOther() }
  }

  if (!marks.length) return null
  if (!go && state === 'idle') return (   // an older version of a chat draft: asked only on request
    <div className={cn('flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel px-3 py-2 text-[12.5px]', className)}>
      <Sparkles size={13} aria-hidden className="text-ink2" />
      <span className="text-ink2">{marks.length} blank{marks.length > 1 ? 's' : ''} to fill in this {kind === 'email' ? 'email' : 'message'}</span>
      <button onClick={() => setGo(true)} className="ml-auto rounded-full bg-accent px-3 py-1 text-[12.5px] font-semibold text-onaccent transition-[filter] hover:brightness-95">
        Answer {marks.length > 1 ? 'a few questions' : 'a quick question'}</button>
    </div>)
  if (state === 'filling' && !qs) return (
    <div className={cn('flex items-center gap-2 rounded-xl border border-line bg-panel px-3 py-2.5 text-[12.5px] text-ink2', className)}>
      <RefreshCw size={13} className="animate-spin" aria-hidden />Filling in the blanks…</div>)
  if (state === 'asking' || state === 'idle') return (
    <div className={cn('flex items-center gap-2 rounded-xl border border-line bg-panel px-3 py-2.5 text-[12.5px] text-ink2', className)}>
      <RefreshCw size={13} className="animate-spin" aria-hidden />Preparing {marks.length > 1 ? `${marks.length} quick questions` : 'a quick question'} so you can fill the {marks.length > 1 ? 'blanks' : 'blank'}…</div>)
  if (state === 'error' || !q) return (
    <div className={cn('flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel px-3 py-2.5 text-[12.5px]', className)}>
      <span className="text-ink2">{err || 'No questions for these blanks.'}</span>
      <button onClick={ask} className="ml-auto rounded-full px-2.5 py-0.5 font-medium text-ink hover:bg-panel2">Try again</button></div>)

  const row = (on: boolean) => cn('flex w-full items-start gap-2.5 rounded-lg border px-2.5 py-1.5 text-left transition-colors', on ? 'border-ink bg-accentbg' : 'border-line hover:border-ink hover:bg-panel2')
  const mark = (on: boolean, n: number) => <span aria-hidden className={cn('mt-px grid size-5 shrink-0 place-items-center text-[11px] font-semibold tabular-nums', q.multi ? 'rounded-[5px] border' : 'rounded-full border',
    on ? 'border-ink bg-ink text-bg' : 'border-line text-ink2')}>{on ? <Check size={12} /> : n}</span>
  return (
    <section aria-label="Details for this draft" tabIndex={-1} onKeyDown={onKey} className={cn('rounded-xl border border-line bg-panel shadow-sm outline-none', className)}>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line2 px-3 py-2">
        <Sparkles size={13} aria-hidden className="text-ink2" />
        <span className="mr-1 text-[12.5px] font-semibold">A few details for this {kind === 'email' ? 'email' : 'message'}</span>
        {live.map((x, n) => <button key={x.id} onClick={() => setI(n)} aria-current={n === i ? 'step' : undefined} title={x.question}
          className={cn('inline-flex items-center gap-1 rounded-full px-2 py-px text-[11.5px] font-medium transition-colors', n === i ? 'bg-ink text-bg' : done(x) ? 'bg-accentbg text-ink' : 'bg-panel2 text-ink2 hover:text-ink')}>
          {done(x) && n !== i && <Check size={11} aria-hidden />}{x.header || `Question ${n + 1}`}</button>)}
      </div>
      <div className="px-3 py-2.5">
        <div className="mb-2 flex items-baseline gap-2">
          <h4 className="text-[13.5px] font-semibold leading-snug">{q.question}</h4>
          {q.multi && <span className="shrink-0 text-[11.5px] text-ink3">pick any</span>}
        </div>
        <div role={q.multi ? 'group' : 'radiogroup'} aria-label={q.question} className="space-y-1">
          {q.options.map((o, n) => { const on = a.picked.includes(o.label); return (
            <button key={o.label} role={q.multi ? 'checkbox' : 'radio'} aria-checked={on} onClick={() => pick(o.label)} className={row(on)}>
              {mark(on, n + 1)}
              <span className="min-w-0"><span className="block text-[13px] font-medium leading-snug">{o.label}</span>
                {o.detail && <span className="block text-[12px] leading-snug text-ink2">{o.detail}</span>}</span>
            </button>) })}
          <div className={row(a.on)} onClick={() => !a.on && chooseOther()}>
            <button role={q.multi ? 'checkbox' : 'radio'} aria-checked={a.on} aria-label="Other" onClick={(e) => { e.stopPropagation(); chooseOther() }} className="shrink-0">{mark(a.on, q.options.length + 1)}</button>
            <input ref={other} value={a.other} onChange={(e) => set({ other: e.target.value, on: true, ...(q.multi ? {} : { picked: [] }) })} placeholder="Other: type your own"
              aria-label="Your own answer" className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink3" />
          </div>
        </div>
        {err && <div role="alert" className="mt-2 text-[12px] text-hot">{err}</div>}
        <div className="mt-2.5 flex items-center gap-1.5">
          {i > 0 && <button onClick={() => setI(i - 1)} className="inline-flex items-center gap-0.5 rounded-full px-2 py-1 text-[12.5px] font-medium text-ink2 hover:bg-panel2 hover:text-ink"><ChevronLeft size={13} aria-hidden />Back</button>}
          <span className="text-[11.5px] text-ink3 max-sm:hidden">{i + 1} of {live.length} · 1–{q.options.length + 1} to pick · Enter</span>
          <button onClick={() => { setAns((s) => ({ ...s, [q.id]: { picked: [], other: '', on: false } })); next() }} disabled={state === 'filling'}
            className="ml-auto rounded-full px-2.5 py-1 text-[12.5px] font-medium text-ink2 hover:bg-panel2 hover:text-ink">Skip</button>
          <button onClick={next} disabled={state === 'filling'} className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1 text-[12.5px] font-semibold text-onaccent transition-[filter] hover:brightness-95 disabled:opacity-60">
            {state === 'filling' ? <><RefreshCw size={13} className="animate-spin" aria-hidden />Filling in…</> : last ? <><Sparkles size={13} aria-hidden />Fill in the {kind === 'email' ? 'email' : 'message'}</> : 'Next'}</button>
        </div>
      </div>
    </section>
  )
}
