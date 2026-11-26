// Reviewing a shared file inside Ask SleePO (Sam, 29 Oct 2026: "inside the AI chat ... just like the email drafting ...
// inline components like document editing"). Review on a file's chip in Messages opens the file's own conversation
// (assist/file_review.py start_chat), whose first answer is a ```review block; the chat (assist/chat.py) writes the others.
// - ReviewCard (```review <attachment id>): SleePO's review, written in the background against Sam's mail, meetings,
//   documents and data: the verdict, the comments with their evidence, each clear fix a tracked change in its sentence that
//   he keeps, drops or rewords in place, then Make the updated deck (the real file, formatting kept) and Draft the reply,
//   which asks the chat for it.
// - ChatEdits (```edits <attachment id>): more changes he asked the chat for, as tracked changes; kept ones join the review.
// - UpdatedFile: the deck SleePO made, as an attachment chip (also on the Teams reply, components/ChatTeamsDraft.tsx).
// Nothing is sent and nothing changes in SharePoint.
import { Fragment, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Check, ChevronDown, ChevronUp, CircleDot, ClipboardCopy, Download, ExternalLink, FileText, FolderOpen, Mail, MessageSquare, Pencil, RefreshCw, Reply, Sparkles, Upload, X, type LucideIcon } from 'lucide-react'
import { api, type ReviewComment, type ReviewRecord } from '@/lib/api'
import { cn } from '@/lib/util'
import { ago } from '@/lib/time'
import { useJob } from '@/lib/useJob'
import { Button } from '@/components/ui'
import { DocChip } from '@/components/DocChip'
import { DictateButton } from './Dictate'

type Comment = ReviewComment & { before?: string; after?: string; from?: string }   // the words around an edit; "chat" when the chat proposed it
type Edit = { where?: string; what?: string; find: string; replace: string }

const FOCUS = ['Do what they asked', 'Check every number', 'Is it board-ready?', 'Tighten the wording']
const KIND: Record<ReviewComment['kind'], string> = { fix: 'Fix', update: 'Update', suggest: 'Suggestion', question: 'Question' }
const SURE: Record<ReviewComment['confidence'], string> = { confirmed: 'Confirmed', likely: 'Likely', unverified: 'Unverified' }
const REF = /\[(S\d+)\]/g
const ICON: Record<string, LucideIcon> = { email: Mail, chat: MessageSquare, meeting: CalendarDays, item: CircleDot }
const kindOf = (name: string) => (/\.docx$/i.test(name) ? 'document' : /\.xlsx$/i.test(name) ? 'workbook' : /\.pdf$/i.test(name) ? 'PDF' : 'deck')
const pill = 'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-medium transition-colors hover:bg-panel2 active:bg-line disabled:opacity-50'
const useReview = (attId: number) => useQuery({ queryKey: ['review', attId], queryFn: () => api.review(attId) })

// one piece of evidence as a chip: a document opens to read, the rest open where they live in SleePO
function Src({ k, refs }: { k: string; refs: ReviewRecord['refs'] }) {
  const r = refs[k]
  if (!r) return null
  if (r.kind === 'doc' && r.doc) return <DocChip id={r.doc}>{r.label}</DocChip>
  const Icon = ICON[r.kind] ?? CircleDot
  return (
    <a href={r.url ? `#${r.url}` : undefined} title={[r.title, r.label, r.date].filter(Boolean).join(' · ')}
      className="mx-0.5 inline-flex max-w-[15rem] items-center gap-1 rounded-full border border-line bg-panel px-1.5 py-px align-baseline text-[11.5px] font-medium text-ink no-underline hover:border-ink hover:bg-accent hover:text-onaccent">
      <Icon size={11} className="shrink-0" aria-hidden /><span className="truncate">{r.label}</span></a>)
}
const Cited = ({ text, refs }: { text: string; refs: ReviewRecord['refs'] }) =>
  <>{text.split(REF).map((p, i) => (i % 2 ? <Src key={i} k={p} refs={refs} /> : <Fragment key={i}>{p}</Fragment>))}</>

const fileData = (f: File) => new Promise<string>((ok, bad) => {
  const r = new FileReader(); r.onload = () => ok(String(r.result).split(',', 2)[1] ?? ''); r.onerror = () => bad(new Error('Could not read the file')); r.readAsDataURL(f)
})

// A tracked change in its own sentence: the words around it, the old text struck and the new highlighted (kept), or the old
// text standing and the new struck (dropped). Double-click the new text to reword it.
function Tracked({ c, text, on, onKeep, onDrop, onReword }: {
  c: Pick<Comment, 'before' | 'after' | 'find'>; text: string; on: boolean | null; onKeep: () => void; onDrop: () => void; onReword?: (t: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(text)
  const kept = on !== false
  const done = (t: string) => { if (t !== text) onReword?.(t); setEditing(false) }
  return (
    <div className={cn('group mt-1.5 flex items-start gap-2 rounded-lg bg-panel2 px-2.5 py-1.5', on === false && 'opacity-60')}>
      <p className="min-w-0 flex-1 text-[13px] leading-relaxed">
        {c.before && <span className="text-ink2">{c.before}</span>}
        <del className={cn(kept ? 'text-ink3 decoration-hot' : 'text-ink no-underline')}>{c.find}</del>
        {editing
          ? <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={Math.min(5, Math.max(1, Math.ceil(draft.length / 60)))} autoFocus
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); done(draft) } if (e.key === 'Escape') { setDraft(text); setEditing(false) } }}
              onBlur={() => done(draft)} className="my-0.5 block w-full resize-y rounded-md border border-ink bg-bg px-1.5 py-0.5 text-[13px] outline-none" />
          : <ins onDoubleClick={() => { if (onReword) { setDraft(text); setEditing(true) } }} title={onReword ? 'Double-click to reword' : undefined}
              className={cn('rounded px-0.5 no-underline', kept ? 'bg-accent/45' : 'text-ink3 line-through')}>{text}</ins>}
        {c.after && <span className="text-ink2">{c.after}</span>}
      </p>
      <span className="flex shrink-0 gap-0.5 pt-0.5">
        {onReword && <button onClick={() => { setDraft(text); setEditing(true) }} aria-label="Reword the change" title="Reword" className="rounded-full p-0.5 text-ink3 opacity-0 hover:bg-panel hover:text-ink group-hover:opacity-100"><Pencil size={13} aria-hidden /></button>}
        <button onClick={onKeep} aria-label="Keep the change" aria-pressed={on === true} title="Keep" className={cn('rounded-full p-0.5', on === true ? 'bg-ink text-bg' : 'text-ink3 hover:bg-panel hover:text-ink')}><Check size={13} aria-hidden /></button>
        <button onClick={onDrop} aria-label="Drop the change" aria-pressed={on === false} title="Drop" className={cn('rounded-full p-0.5', on === false ? 'bg-ink text-bg' : 'text-ink3 hover:bg-panel hover:text-ink')}><X size={13} aria-hidden /></button>
      </span>
    </div>)
}

// The updated file SleePO made, as an attachment chip
export function UpdatedFile({ attId, className }: { attId: number; className?: string }) {
  const out = useReview(attId).data?.review?.output
  if (!out) return null
  const n = Object.keys(out.applied).length
  return (
    <div className={cn('inline-flex max-w-full flex-wrap items-center gap-1 rounded-xl border border-line bg-panel px-2 py-1 text-[12.5px]', className)}>
      <FileText size={14} aria-hidden className="shrink-0" /><span className="min-w-0 truncate font-medium" title={out.path}>{out.name}</span>
      <span className="text-ink3">· {n} change{n === 1 ? '' : 's'}</span>
      <button onClick={() => api.reviewOpen(attId)} className={pill}><ExternalLink size={12} aria-hidden />Open</button>
      <button onClick={() => api.reviewOpen(attId, true)} className={pill}><FolderOpen size={12} aria-hidden />Show in Finder</button>
    </div>)
}

// ```review <attachment id>: the review card. focus: what the chat was asked to look for (the block's text). live: the answer
// holding it is still coming in; the server starts the review when it ends (assist/chat.py turn, file_review.from_chat).
export function ReviewCard({ attId, focus = '', live = false, onReply }: { attId: number; focus?: string; live?: boolean; onReply: (name: string, who: string, file: string | null) => void }) {
  const qc = useQueryClient()
  const q = useReview(attId)
  const [ask, setAsk] = useState(focus)
  const [again, setAgain] = useState(false)
  const [folded, setFolded] = useState(false)
  const [err, setErr] = useState('')
  const [making, setMaking] = useState(false)
  const askRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['review', attId] }); qc.invalidateQueries({ queryKey: ['chat'] }) }
  // written on the server and kept with the file: a review the server started (Review in Messages) is followed here too
  const run = useJob(`assist-review:${attId}`, api.reviewJob, { onDone: () => { refresh(); setAsk(''); setAgain(false) }, onError: (m) => setErr(m || 'No review came back. Try again.'), every: 3000 })
  const st = q.data
  useEffect(() => { if (st?.job && !run.busy) run.follow(st.job) }, [st?.job]) // eslint-disable-line react-hooks/exhaustive-deps
  const rec = st?.review ?? null
  const name = st?.name ?? 'the file'
  const first = (st?.shared_by || 'them').split(' ')[0]
  const word = kindOf(name)

  const go = async () => {
    if (run.busy) return
    setErr('')
    try { run.follow((await api.reviewStart(attId, ask)).job) } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }
  const act = async (f: () => Promise<unknown>) => { setErr(''); try { await f(); refresh() } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } }
  const addFile = (f?: File | null) => f && act(async () => api.reviewFile(attId, f.name, await fileData(f)))
  const make = async () => { setMaking(true); await act(() => api.reviewMake(attId)); setMaking(false) }
  const save = (b: { decisions?: Record<string, boolean>; replace?: Record<string, string> }) => act(() => api.reviewDecide(attId, b))
  const ticked = (rec?.review.comments ?? []).filter((c) => c.find && rec?.decisions[c.id])

  return (
    <div className="my-2 overflow-hidden rounded-xl border border-line bg-panel text-[13px]" onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); addFile(e.dataTransfer.files?.[0]) }}>
      <div className="flex items-center gap-2 border-b border-line2 px-3 py-2">
        <FileText size={15} aria-hidden className="shrink-0" />
        <div className="min-w-0 flex-1"><div className="truncate font-semibold" title={name}>{name}</div>
          <div className="truncate text-[11.5px] text-ink2">Review{st?.shared_by && ` · shared by ${st.shared_by}`}{rec && !run.busy && ` · ${ago(rec.created_at)}`}
            {rec && ` · ${rec.review.comments.length} comment${rec.review.comments.length === 1 ? '' : 's'}`}</div></div>
        {st?.url && <a href={st.url} target="_blank" rel="noopener" title="Open the file in SharePoint" className="rounded-full p-1 text-ink2 hover:bg-panel2 hover:text-ink"><ExternalLink size={13} aria-hidden /></a>}
        <button onClick={() => setFolded(!folded)} aria-label={folded ? 'Show the review' : 'Fold the review'} className="rounded-full p-1 text-ink2 hover:bg-panel2 hover:text-ink">
          {folded ? <ChevronDown size={14} aria-hidden /> : <ChevronUp size={14} aria-hidden />}</button>
      </div>
      {!folded && <div className="px-3 py-2.5">
        {!st ? <p className="text-ink3">{q.isError ? 'Could not load the file.' : 'Loading…'}</p> : <>
          {st.request && !rec && <p className="mb-2 border-l-2 border-line pl-2 text-[12.5px] italic text-ink2">{st.request}</p>}
          {st.editable && !st.file && <div className="mb-2.5 rounded-lg border border-dashed border-line px-2.5 py-2 text-[12.5px] text-ink2">
            To change the {word} itself, SleePO needs the file{st.read ? ' (its text is enough for the review)' : ''}: open it, choose File › Download a copy, then Check again, or drop it here.
            <div className="mt-1.5 flex flex-wrap gap-1">
              {st.url && <a href={st.url} target="_blank" rel="noopener" className={cn(pill, 'border border-line text-ink no-underline')}><Download size={12} aria-hidden />Open to download</a>}
              <button onClick={refresh} className={cn(pill, 'border border-line')}><RefreshCw size={12} aria-hidden />Check again</button>
              <button onClick={() => fileRef.current?.click()} className={cn(pill, 'border border-line')}><Upload size={12} aria-hidden />Add the file</button>
              <input ref={fileRef} type="file" accept=".pptx,.docx" className="hidden" onChange={(e) => { addFile(e.target.files?.[0]); e.target.value = '' }} />
            </div></div>}
          {!st.read && !st.file && <p className="mb-2 text-[12.5px] text-hot">SleePO has not read this file yet: download or add it first.</p>}

          {live && !rec && !run.busy && <p className="text-ink2">The review starts when this answer is done.</p>}
          {(!rec || again) && !run.busy && !(live && !rec) && <div className="mb-1">
            <div className="relative" data-dictate>
              <textarea ref={askRef} value={ask} onChange={(e) => setAsk(e.target.value)} rows={1}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go() } }}
                placeholder={`Anything to look for beyond what ${first} asked? (optional)`}
                className="w-full resize-none rounded-lg border border-line bg-bg px-2.5 py-1.5 pr-8 text-[13px] outline-none focus:border-ink" />
              <DictateButton target={askRef} className="absolute right-1.5 top-1.5" />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1">
              {FOCUS.map((f) => <button key={f} onClick={() => setAsk((a) => (a ? `${a}; ${f.toLowerCase()}` : f))}
                className="rounded-full border border-line px-2 py-0.5 text-[12px] text-ink2 hover:border-ink hover:text-ink">{f}</button>)}
              <span className="ml-auto flex gap-1">
                {again && <Button onClick={() => setAgain(false)}>Cancel</Button>}
                <Button variant="primary" onClick={go} disabled={!st.read && !st.file}><Sparkles size={13} aria-hidden />{rec ? 'Review again' : 'Review it'}</Button>
              </span>
            </div>
          </div>}
          {run.busy && <div className="flex items-center gap-2 text-ink2" aria-live="polite">
            <span className="inline-flex shrink-0 gap-1">{[0, 1, 2].map((i) => <span key={i} className="size-1.5 animate-bounce rounded-full bg-ink2" style={{ animationDelay: `${i * 150}ms` }} />)}</span>
            Reading the {word} and checking it against your mail, meetings, documents and pipeline: a few minutes. You can keep chatting, or leave.</div>}

          {rec && <div className={cn(run.busy && 'mt-3 opacity-50')}>
            <p className="font-medium leading-relaxed"><Cited text={rec.review.verdict} refs={rec.refs} /></p>
            <ol className="mt-2 divide-y divide-line2">
              {(rec.review.comments as Comment[]).map((c) => <CommentRow key={c.id} c={c} rec={rec} save={save} />)}
            </ol>
            {rec.review.questions.length > 0 && <div className="mt-2 border-t border-line2 pt-2">
              <p className="mb-1 text-[12.5px] font-semibold">For you to check</p>
              <ul className="list-disc space-y-0.5 pl-5">{rec.review.questions.map((x, i) => <li key={i}><Cited text={x} refs={rec.refs} /></li>)}</ul>
            </div>}
          </div>}
          {err && <p role="alert" className="mt-2 text-[12.5px] text-hot">{err}</p>}
        </>}
      </div>}
      {rec && !run.busy && !folded && <div className="border-t border-line2 px-3 py-2">
        {rec.output && <div className="mb-1.5"><UpdatedFile attId={attId} />
          {rec.output.failed.length > 0 && <p className="mt-0.5 text-[12px] text-hot">Not made, its words were not found: {rec.output.failed.map((id) => rec.review.comments.find((c) => c.id === id)?.where || id).join('; ')}. Make these by hand.</p>}</div>}
        <div className="flex flex-wrap items-center gap-1">
          {st?.editable && <button onClick={make} disabled={making || !st.file || ticked.length === 0}
            title={!st.file ? `SleePO needs the ${word} itself: download it or add it above` : ticked.length === 0 ? 'Keep a change to make it' : undefined}
            className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-0.5 text-[12px] font-semibold text-onaccent transition-[filter] hover:brightness-95 disabled:opacity-50">
            <FileText size={12} aria-hidden />{making ? 'Making…' : `${rec.output ? 'Make it again' : `Make the updated ${word}`} · ${ticked.length} change${ticked.length === 1 ? '' : 's'}`}</button>}
          <button onClick={() => onReply(name, first, rec.output?.name ?? null)} className={cn(pill, 'border border-line')}><Reply size={12} aria-hidden />Draft the reply to {first}</button>
          <button onClick={() => setAgain(true)} className={cn(pill, 'text-ink2')}><RefreshCw size={12} aria-hidden />Review again</button>
        </div>
      </div>}
    </div>)
}

// one comment of the review; a clear fix is a tracked change Sam keeps, drops or rewords
function CommentRow({ c, rec, save }: { c: Comment; rec: ReviewRecord; save: (b: { decisions?: Record<string, boolean>; replace?: Record<string, string> }) => void }) {
  const [copied, setCopied] = useState(false)
  const made = rec.output?.applied[c.id]
  const tag = (t: string, cls = '') => <span className={cn('rounded-full border border-line px-1.5 text-[10.5px] leading-[17px] text-ink2', cls)}>{t}</span>
  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <div className="mb-0.5 flex flex-wrap items-center gap-1">
        {c.where && <span className="mr-0.5 text-[12px] font-semibold">{c.where}</span>}
        {c.from === 'chat' ? tag('Asked in the chat') : <>{tag(KIND[c.kind], c.kind === 'fix' ? 'border-hot text-hot' : '')}{tag(SURE[c.confidence], c.confidence === 'unverified' ? 'border-dashed' : '')}</>}
        {made && tag(`Made · ${made}`, 'border-ink text-ink')}
      </div>
      <p className="leading-snug"><Cited text={c.what} refs={rec.refs} />{c.why && <span className="text-ink2"> <Cited text={c.why} refs={rec.refs} /></span>}</p>
      {c.find && <Tracked c={c} text={rec.replace[c.id] ?? c.replace} on={!!rec.decisions[c.id]}
        onKeep={() => save({ decisions: { [c.id]: true } })} onDrop={() => save({ decisions: { [c.id]: false } })} onReword={(t) => save({ replace: { [c.id]: t } })} />}
      {c.suggested && <div className="mt-1.5 rounded-lg border border-dashed border-line px-2.5 py-1.5">
        <div className="mb-0.5 flex items-center gap-1.5 text-[11.5px] text-ink3">Suggested text: SleePO could not find where it goes, so put it in yourself
          <button onClick={async () => { try { await navigator.clipboard.writeText(c.suggested); setCopied(true) } catch { /* no clipboard */ } }}
            className={cn(pill, 'ml-auto text-ink2')}>{copied ? <Check size={12} aria-hidden /> : <ClipboardCopy size={12} aria-hidden />}{copied ? 'Copied' : 'Copy'}</button></div>
        {c.suggested}</div>}
    </li>)
}

// ```edits <attachment id>: changes Sam asked the chat for, each a tracked change; Keep adds it to the review (kept), so
// it goes into the updated file with the others.
export function ChatEdits({ attId, raw, done }: { attId: number; raw: string; done: boolean }) {
  const qc = useQueryClient()
  const q = useReview(attId)
  const [err, setErr] = useState('')
  const [dropped, setDropped] = useState<Set<number>>(new Set())
  let edits: Edit[] = []
  try { const v = JSON.parse(raw); edits = (Array.isArray(v) ? v : []).filter((e) => e && typeof e.replace === 'string') } catch { /* still being written */ }
  if (!done || !edits.length) return <div className="my-2 rounded-xl border border-dashed border-line px-3 py-2 text-[12.5px] text-ink3">Proposing changes…</div>
  const rec = q.data?.review
  const mine = (e: Edit) => (rec?.review.comments as Comment[] | undefined)?.find((c) => c.from === 'chat' && (c.find || '') === e.find.trim() && (c.replace || c.suggested) === e.replace.trim())
  const keep = async (es: Edit[]) => {
    setErr('')
    try { await api.reviewEdits(attId, es); setDropped(new Set()); qc.invalidateQueries({ queryKey: ['review', attId] }) } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }
  const drop = async (e: Edit, i: number) => {
    const c = mine(e)
    if (c) await api.reviewDecide(attId, { decisions: { [c.id]: false } }).then(() => qc.invalidateQueries({ queryKey: ['review', attId] })).catch(() => {})
    setDropped((d) => new Set(d).add(i))
  }
  const open = edits.filter((e, i) => !mine(e) && !dropped.has(i))
  return (
    <div className="my-2 overflow-hidden rounded-xl border border-line bg-panel text-[13px]">
      <div className="flex items-center gap-2 border-b border-line2 px-3 py-1.5 text-[12px] text-ink2">
        <Pencil size={13} aria-hidden />Changes to {q.data?.name ?? 'the file'}
        {open.length > 1 && <button onClick={() => keep(open)} className={cn(pill, 'ml-auto border border-line text-ink')}><Check size={12} aria-hidden />Keep all</button>}
      </div>
      <ol className="divide-y divide-line2 px-3">
        {edits.map((e, i) => {
          const c = mine(e)
          const on = c ? !!(c.find && rec?.decisions[c.id]) : dropped.has(i) ? false : null
          return <li key={i} className="py-2">
            {(e.where || e.what) && <p className="leading-snug">{e.where && <span className="mr-1 text-[12px] font-semibold">{e.where}</span>}<span className="text-ink2">{e.what}</span></p>}
            {c && !c.find ? <p className="mt-1 text-[12.5px] text-hot">SleePO could not find these words in the file: added to the review as text to put in yourself.</p>
              : <Tracked c={{ find: e.find, before: c?.before, after: c?.after }} text={e.replace} on={on} onKeep={() => keep([e])} onDrop={() => drop(e, i)} />}
          </li>
        })}
      </ol>
      {err && <p role="alert" className="px-3 pb-2 text-[12.5px] text-hot">{err}</p>}
    </div>)
}
