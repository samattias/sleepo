// Proposed actions from the daily brief and meeting briefs. Nothing here ever sends:
// - create / edit / draft  → open the prompt in the Claude desktop app (Cowork or chat), document attached for edits
// - email / teams / slack  → copy the (edited) text to paste into Outlook, Teams or Slack. No Microsoft 365 or Slack
//                             integration: nothing is drafted or sent from here.
import { useState } from 'react'
import { Check, ClipboardCopy, ExternalLink, FilePen, FilePlus2, Mail, MessageSquare, Hash, RefreshCw, Sparkles } from 'lucide-react'
import { ClaudeMark } from './ClaudeMark'
import { api } from '@/lib/api'
import { useMutation } from '@tanstack/react-query'
import { cn, editRatio } from '@/lib/util'
import { DocChip } from './DocChip'
import { FillEditor, countFills } from './FillEditor'

export type Action = {
  type: 'create' | 'edit' | 'draft' | 'email' | 'teams' | 'slack'; label: string; why?: string
  app?: 'cowork' | 'chat'; doc?: string; prompt?: string
  to?: string[]; cc?: string[]; subject?: string; body?: string; reply_to?: string
  channel?: string; user?: string; message?: string
  links?: { label: string; url: string }[]   // the real files the action is about (deck, doc, folder): open in one click
  steps?: Action[]   // one move that needs several messages (ask Finley, then update Milo): one step per recipient
  // create: the deliverable Claude Cowork builds from SleePO's context pack (assist/action_context.py)
  format?: 'pptx' | 'docx' | 'xlsx' | 'md'; title?: string; audience?: string; outline?: string[]
  intent?: string   // email replies: what the reply must say, for the full-thread reply writer
  outlook?: { id: string; web_link: string | null }   // a task's new email saved as a draft in Outlook (assist/tasks.py to_outlook)
  // meeting follow-ups (assist/followup.py): the transcript turn the action comes from, and the open item it finishes
  meeting?: string; said?: { t: number; at: string; clock: string; me: boolean; who: string; quote: string }
  loop?: number; loop_state?: { id: number; kind: string; title: string; status: string } | null
}

const ICON = { create: FilePlus2, edit: FilePen, draft: Sparkles, email: Mail, teams: MessageSquare, slack: Hash } as const
const KIND = { create: 'Create · Claude Cowork', edit: 'Edit a document · Claude Cowork', draft: 'Draft · Claude chat', email: 'Email · copy and paste', teams: 'Teams message · copy and paste', slack: 'Slack message · copy and paste' } as const

// The fenced ```actions block (JSON) at the end of a brief.
export function splitActions(md: string): { body: string; actions: Action[] } {
  const m = md.match(/```actions\s*\n([\s\S]*?)\n```/)
  let actions: Action[] = []
  if (m) { try { const a = JSON.parse(m[1]); if (Array.isArray(a)) actions = a.filter((x) => x && x.label && (x.type || x.steps?.length)) } catch { /* malformed: show none */ } }
  return { body: m ? md.replace(m[0], '') : md, actions }
}

// Rows keep their own edited draft, so a row must be keyed by what the action is, not by its position: when the brief or the
// Actions list is rebuilt while the page is open, a positional key would put the new label above the old draft.
// Recipients may arrive as a list or, from some writers, as one string: always treat them as a list.
export const asList = (x: unknown): string[] => (Array.isArray(x) ? x.map(String) : typeof x === 'string' && x.trim() ? x.split(/[,;]\s*/) : [])

export const actionKey = (a: Action, i: number) => `${i}|${a.type ?? 'steps'}|${a.label}|${asList(a.to).join(',')}|${a.reply_to ?? ''}|${(a.body ?? a.message ?? a.prompt ?? '').length}`

// Only the meeting panel uses it (brief and follow-up), so it takes the Inbox's shapes: a rounded card and pill buttons (Sam, 22 Oct 2026)
export function ActionsPanel({ actions, label, title = 'Recommended actions' }: { actions: Action[]; label: string; title?: string }) {
  if (!actions.length) return null
  return (
    <section className="mb-5 overflow-hidden rounded-xl border border-line bg-panel shadow-sm">
      <div className="flex items-baseline gap-2 border-b border-line bg-panel2 px-4 py-2"><span className="text-[13px] font-semibold">{title}</span><span className="text-[12px] text-ink2">nothing is sent; you review every draft</span></div>
      {actions.map((a, i) => a.steps?.length ? <ActionGroup key={actionKey(a, i)} a={a} label={label} /> : <ActionRow key={actionKey(a, i)} a={a} label={label} soft />)}
    </section>
  )
}

// The files an action is about, as buttons that open the original (SharePoint/OneDrive/Teams) in a new tab.
export function FileLinks({ links, compact, soft }: { links: { label: string; url: string }[]; compact?: boolean; soft?: boolean }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {links.map((l) => (
        <a key={l.url} href={l.url} target="_blank" rel="noopener" onClick={(e) => e.stopPropagation()} title={l.url}
          className={cn('inline-flex max-w-full items-center gap-1.5 border border-ink bg-panel font-medium text-ink no-underline hover:bg-accent hover:text-onaccent', compact ? 'px-2 py-0.5 text-[12px]' : 'px-2.5 py-1 text-[12.5px]', soft && 'rounded-full border-line')}>
          <ExternalLink size={compact ? 12 : 13} className="shrink-0" aria-hidden /><span className="truncate">{l.label}</span>
        </a>))}
    </div>
  )
}

// An action made of several messages, each to its own recipient, shown as numbered steps.
function ActionGroup({ a, label }: { a: Action; label: string }) {
  return (
    <div className="border-b border-line2 px-4 py-3 last:border-0">
      <div className="text-[14px] font-medium">{a.label}</div>
      {a.why && <div className="mt-0.5 text-[13px] text-ink2">{a.why}</div>}
      {(a.said || a.loop_state) && <Provenance a={a} />}
      <div className="mt-1">{a.steps!.map((x, i) => <ActionRow key={actionKey(x, i)} a={x} label={label} compact step={i + 1} soft />)}</div>
    </div>
  )
}

// Compact, one-click version for the Today widget: one small button per step (copy a message, or open in Claude).
const firstName = (x: string) => { const n = x.includes('@') ? x.split('@')[0].split(/[._]/)[0] : x.split(' ')[0]; return n ? n[0].toUpperCase() + n.slice(1) : '' }
export const recipientOf = (a: Action) => a.type === 'slack' ? (a.user ? firstName(a.user) : a.channel ? `#${a.channel.replace(/^#/, '')}` : '') : a.type === 'email' && a.reply_to && !asList(a.to).length ? 'reply' : asList(a.to).map(firstName).join(', ')

export function QuickActions({ actions, label, targetId }: { actions: Action[]; label: string; targetId?: string }) {
  const [hit, setHit] = useState(-1)
  const flat = actions.flatMap((a) => a.steps?.length ? a.steps : [a]).filter((a) => a.type)
  const files = [...new Map(actions.flatMap((a) => [...(a.links ?? []), ...(a.steps ?? []).flatMap((x) => x.links ?? [])]).map((l) => [l.url, l])).values()]
  if (!flat.length && !files.length) return null
  const run = async (a: Action, i: number) => {
    try {
      const step = targetId ? actions.indexOf(a) : -1
      if ((a.type === 'create' || a.type === 'edit' || a.type === 'draft') && step >= 0 && targetId) await api.todoAct(targetId, step)   // an Actions item: opens with its context pack
      else if (a.type === 'create' || a.type === 'edit' || a.type === 'draft') await api.claudeOpen({ prompt: a.prompt ?? '', app: a.app === 'cowork' ? 'cowork' : a.type === 'draft' ? 'chat' : 'cowork', doc: a.doc, label })
      else { const t = a.type === 'email' ? a.body ?? '' : a.message ?? ''; await navigator.clipboard.writeText(a.type === 'email' && !a.reply_to ? `Subject: ${a.subject ?? ''}\n\n${t}` : t)
        api.feedback({ target_type: 'action', target_id: (targetId ?? `${label} · ${a.label}`).slice(0, 200), copied: true, edit_ratio: 0 }) }
      setHit(i); setTimeout(() => setHit(-1), 1800)
    } catch { /* clipboard blocked: the Actions page has the full editor */ }
  }
  return (
    <span className="mt-1.5 flex flex-wrap gap-1.5">
      {files.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noopener" title={l.url} onClick={(e) => e.stopPropagation()}
        className="inline-flex max-w-full items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[12px] font-medium text-ink no-underline hover:border-ink"><ExternalLink size={12} /><span className="truncate">{l.label}</span></a>)}
      {flat.map((a, i) => { const Icon = ICON[a.type] ?? Sparkles; const isClaude = a.type === 'create' || a.type === 'edit' || a.type === 'draft'; const who = recipientOf(a)
        const fills = countFills(a.type === 'email' ? a.body ?? '' : a.message ?? a.prompt ?? '')
        return (
          <button key={i} type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); run(a, i) }}
            title={`${a.label}${fills ? ` · ${fills} placeholder${fills > 1 ? 's' : ''} to fill after pasting` : ''}\n${isClaude ? 'Opens in Claude' : 'Copies the draft'}; review & edit on the Actions page`}
            className="inline-flex max-w-full items-center gap-1 rounded-full border border-line bg-panel px-2 py-0.5 text-[12px] font-medium text-ink hover:border-ink">
            {flat.length > 1 && <span className="tabular-nums text-ink2">{i + 1}</span>}
            {hit === i ? <Check size={12} /> : isClaude ? <ClaudeMark size={13} /> : <Icon size={12} />}
            <span className="truncate">{hit === i ? (isClaude ? 'Opened' : 'Copied') : isClaude ? 'Open in Claude' : `Copy · ${who || a.type}`}</span>
            {fills > 0 && hit !== i && <span className="size-1.5 shrink-0 rounded-full bg-hot" />}
          </button>) })}
    </span>
  )
}

// Where a follow-up action comes from: the moment in the transcript (opens the transcript there) and the open item it finishes,
// which Sam can close from here once it is done.
function Provenance({ a }: { a: Action }) {
  const l = a.loop_state
  const [status, setStatus] = useState(l?.status ?? '')
  const close = useMutation({ mutationFn: (s: string) => api.loopSet(l!.id, s), onSuccess: (_, s) => setStatus(s) })
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink2">
      {a.said && a.meeting && <a href={`#/meetings/${a.meeting}?t=${a.said.t}`} title={`“${a.said.quote}”`} className="font-medium">
        {a.said.me ? 'You said it' : `${a.said.who} said it`} at {a.said.at}</a>}
      {l && <span className="inline-flex min-w-0 items-center gap-1.5">
        <span className="truncate">Open item: {l.title}</span>
        {status === 'open' ? <button onClick={() => close.mutate('done')} disabled={close.isPending} className="shrink-0 rounded-full border border-line px-2 py-px font-medium text-ink hover:border-ink disabled:opacity-60">{close.isPending ? 'Closing…' : 'Mark done'}</button>
          : <span className="shrink-0 font-medium text-ink">{status === 'done' ? 'done' : status}{status === 'done' && <button onClick={() => close.mutate('open')} className="ml-1.5 font-normal underline decoration-line underline-offset-2">reopen</button>}</span>}
      </span>}
    </div>
  )
}

const btn = 'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-medium'
const primary = cn(btn, 'border-accent bg-accent text-onaccent hover:brightness-95 disabled:opacity-60')
const secondary = cn(btn, 'border-line font-normal hover:border-ink')
// soft: the Inbox's borderless pills, for the meeting panel (ActionsPanel); elsewhere the bordered pills above
const softPrimary = 'inline-flex items-center gap-1.5 rounded-full bg-accent px-3.5 py-1 text-[12.5px] font-semibold text-onaccent transition-[filter] hover:brightness-95 active:brightness-90 disabled:opacity-60'
const softSecondary = 'inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2 active:bg-line'

// compact: a nested step inside an action card (Actions page): smaller type and buttons, numbered, no row padding of its own.
// targetId: the todo id when the action belongs to an Actions item, so feedback joins back to it (assist/feedback.py)
// onUsed: a Tasks step logs what Sam did with the action (assist/tasks.py log_action)
export function ActionRow({ a, label, compact, step, targetId, soft, onUsed }: { a: Action; label: string; compact?: boolean; step?: number; targetId?: string; soft?: boolean; onUsed?: (what: string) => void }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(a.type === 'email' ? a.body ?? '' : a.type === 'teams' || a.type === 'slack' ? a.message ?? '' : a.prompt ?? '')
  const [state, setState] = useState<'' | 'busy' | 'done' | 'copied' | 'error'>('')
  const [msg, setMsg] = useState('')
  const [link, setLink] = useState('')
  const Icon = ICON[a.type] ?? Sparkles
  const isClaude = a.type === 'create' || a.type === 'edit' || a.type === 'draft'
  const who = a.type === 'email' ? [...asList(a.to), ...asList(a.cc).map((x) => `cc ${x}`)].join(', ') : a.type === 'teams' ? asList(a.to).join(', ') : a.type === 'slack' ? a.channel || a.user || '' : ''

  const run = async () => {
    setState('busy'); setMsg(''); setLink('')
    try {
      if (isClaude) {
        await api.claudeOpen({ prompt: text, app: a.type === 'draft' && a.app !== 'cowork' ? 'chat' : a.app === 'chat' ? 'chat' : 'cowork', doc: a.doc, label })
        onUsed?.('opened in Claude')
        setState('done'); setMsg(a.doc ? 'Opened in Claude with the document attached; outputs go to “SleePO Workspace”.' : 'Opened in Claude.')
        return
      }
      await navigator.clipboard.writeText(a.type === 'email' && !a.reply_to ? `Subject: ${a.subject ?? ''}\n\n${text}` : text)
      api.feedback({ target_type: 'action', target_id: (targetId ?? `${label} · ${a.label}`).slice(0, 200), copied: true, edit_ratio: editRatio(a.type === 'email' ? a.body ?? '' : a.message ?? '', text) })
      onUsed?.(`${a.type === 'email' ? 'email' : a.type === 'teams' ? 'Teams message' : 'Slack message'} copied`)
      setState('copied'); setMsg(`Copied. Paste it into ${a.type === 'email' ? 'Outlook' : a.type === 'teams' ? 'Teams' : 'Slack'}${countFills(text) ? ` and fill in the ${countFills(text)} highlighted placeholder${countFills(text) > 1 ? 's' : ''}` : ''}.`)
    } catch (e) { setState('error'); setMsg(String(e instanceof Error ? e.message : e)) }
  }
  const copy = async () => { try { await navigator.clipboard.writeText(a.type === 'email' ? `Subject: ${a.subject ?? ''}\n\n${text}` : text); setState('copied') } catch { setState('error'); setMsg('Clipboard not available') } }
  const primaryLabel = isClaude ? 'Open in Claude' : 'Copy'

  const P = soft ? softPrimary : compact ? cn(primary, 'px-2.5 py-1 text-[12.5px]') : primary
  const S = soft ? softSecondary : compact ? cn(secondary, 'px-2 py-1 text-[12.5px]') : secondary
  return (
    <div className={compact ? 'relative py-2.5 pl-7' : 'border-b border-line2 px-4 py-3 last:border-0'}>
      {compact && <span aria-hidden className="absolute left-0 top-[11px] inline-flex size-5 items-center justify-center rounded-full border border-line bg-panel text-[11px] tabular-nums text-ink2">{step}</span>}
      <div className={cn('flex flex-wrap items-start', compact ? 'gap-2.5' : 'gap-3')}>
        <Icon size={compact ? 15 : 18} className="mt-0.5 shrink-0 text-ink2" />
        <div className="min-w-0 flex-1">
          <div className={compact ? 'text-[13.5px] font-medium leading-snug' : 'text-[14px] font-medium'}>{a.label}</div>
          {a.why && <div className={cn('mt-0.5 text-ink2', compact ? 'text-[12.5px] leading-snug' : 'text-[13px]')}>{a.why}</div>}
          <div className={cn('mt-1 flex flex-wrap items-center gap-2 text-ink2', compact ? 'text-[12px]' : 'text-[12.5px]')}>
            {KIND[a.type]}{who && <span>· {who}</span>}{a.doc && <DocChip id={a.doc} />}
            <button onClick={() => setOpen(!open)} className="underline decoration-line underline-offset-2 hover:decoration-ink">{open ? 'Hide' : isClaude ? 'Review prompt' : 'Review & edit'}</button>
          </div>
          {a.links && a.links.length > 0 && <FileLinks links={a.links} compact={compact} soft={soft} />}
          {(a.said || a.loop_state) && <Provenance a={a} />}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={run} disabled={state === 'busy'} className={P}>{state === 'busy' ? <RefreshCw size={14} className="animate-spin" /> : state === 'done' || (state === 'copied' && !isClaude) ? <Check size={14} /> : isClaude ? <ClaudeMark size={15} /> : <ClipboardCopy size={14} />}{state === 'busy' ? 'Working…' : state === 'copied' && !isClaude ? 'Copied' : primaryLabel}</button>
          {isClaude && <button onClick={copy} title="Copy" aria-label="Copy" className={soft ? S : cn(S, compact ? 'px-1.5' : 'px-2.5')}>{state === 'copied' ? <Check size={14} /> : <ClipboardCopy size={14} />}</button>}
        </div>
      </div>
      {msg && <div className={cn('mt-2 text-[12.5px]', state === 'error' ? 'text-hot' : 'text-ink2')}>{msg}{link && <> · <a href={link} target="_blank" rel="noopener">open it ↗</a></>}</div>}
      {open && (
        <div className={cn('mt-3 border border-line bg-panel2 p-3', soft && 'rounded-lg')}>
          {a.type === 'email' && <div className="mb-2 grid grid-cols-[60px_1fr] gap-x-2 gap-y-1 text-[12.5px]"><span className="text-ink2">To</span><span>{asList(a.to).join(', ') || (a.reply_to ? 'reply to the sender' : '—')}</span>{asList(a.cc).length > 0 && <><span className="text-ink2">Cc</span><span>{asList(a.cc).join(', ')}</span></>}<span className="text-ink2">Subject</span><span>{a.subject || (a.reply_to ? 'Re: (thread subject)' : '—')}</span></div>}
          <FillEditor value={text} onChange={setText} rows={Math.min(16, Math.max(5, text.split('\n').length + 1))} />
          {countFills(text) > 0 && <div className="mt-1 text-[12px] font-medium text-hot">{countFills(text)} highlighted placeholder{countFills(text) > 1 ? 's' : ''} to fill in before you send.</div>}
          <div className="mt-1 text-[11.5px] text-ink2">Your edits are what gets copied.</div>
        </div>
      )}
    </div>
  )
}
