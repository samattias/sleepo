// Ask SleePO: the chat. One conversation state (ChatProvider) shared by two views: the floating badge (bottom right, every
// page, or ⌘J) and the full-screen Assistant page (#/assistant, views/assistant.tsx), so a conversation, even one still
// streaming, carries over when Sam switches between them. Each turn runs a read-only Claude Code session on the server
// (assist/chat.py): it reads files, Office documents and the database, makes files only in the conversation's own folder
// in ~/SleePO Workspace, and proposes changes to SleePO as cards that do nothing until Sam presses Apply. It never sends
// anything. Conversations are saved (and deleted 30 days after their last turn); follow-ups resume the session.
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { Archive, ArrowDown, ArrowUp, ArrowUpRight, ChartColumn, Check, ChevronDown, CircleDollarSign, CircleUserRound, Clock, Compass, Copy, CornerDownRight, Crosshair, File as FileIcon,
  FileSpreadsheet, FileText, Flag, FolderOpen, History, Hourglass, Lightbulb, ListChecks, ListTodo, Mail, Map as MapIcon, Maximize2, MessageCircleQuestion,
  MessageSquareQuote, Network, Pencil, Plus, RefreshCw, RotateCcw, Scale, Sparkles, Square, Target, Trash2, Undo2, UserRound, UsersRound, X, CalendarDays,
  CircleCheck, MessagesSquare, Hash, type LucideIcon } from 'lucide-react'
import { api, type PageCtx, workBase, type ChatDraftSaved, type ChatLive } from '@/lib/api'
import { ChatEmail, parseEmail, type EmailFields } from './ChatEmail'
import { ChatEdits, ReviewCard } from './ChatReview'
import { ChatTeamsDraft } from './ChatTeamsDraft'
import { MessageCard } from './ChatMessage'
import { DesktopRequests, LooseRequests } from './ChatDesktop'
import { ChipHover, openLabel } from './ContextChip'
import { cn } from '@/lib/util'
import { Avatar, Markdown, RetentionDays, Segmented, popoverClass } from './ui'
import { Logo } from './Logo'
import { ClaudeMark } from './ClaudeMark'
import { DictateButton } from './Dictate'
import { TZ, LOCALE, day, parse } from '@/lib/time'
import { hi, profile } from '@/lib/profile'

type Made = { name: string; size: number }   // a file the turn wrote in the conversation's folder
type Turn = { role: 'user' | 'assistant'; text: string; steps?: string[]; error?: string | null; secs?: number | null; page?: string | null; at?: string; made?: Made[]
  ctx?: PageCtx   // ctx: the chip the question was asked with, drawn above it (this visit only; saved turns keep page)
  acts?: string[]; run?: string; asks?: boolean }   // steps on the Mac it asked to do (components/ChatDesktop.tsx): saved ids, or this run's while it is live
// a change the model proposes (a ```changes block): shown as a card, applied only by Sam's click
type Change = { type: 'loop' | 'action' | 'refresh' | 'decide'; id?: number | string; status?: string; snooze_until?: string; note?: string; mode?: 'mail' | 'sync' | 'full'; label?: string
  subject?: string; question?: string; choice?: string; task_id?: number | null; decided?: boolean }   // decide: Sam's call in a conversation started from an initiative's or topic's page
type ThreadRow = { id: string; title: string; first?: string; updated_at: string; turns: number; live?: string | null }   // title: SleePO's summary (assist/chat.py summarize); first: the first question; live: the job answering in it now
const OPEN = 'sleepo:chat'
const CUR = 'sleepo-chat-thread'
export const ASSISTANT = '/assistant'
export const openChat = (prompt?: string) => window.dispatchEvent(new CustomEvent(OPEN, { detail: prompt }))
// open a saved conversation, e.g. the one an email briefing starts (components/Briefing.tsx); prompt goes in the box, unsent,
// or, with send, is asked at once. hint: the box's placeholder until Sam writes his first message there (a button on an
// initiative's or topic's page waits for him to say what the email or document is: components/InitiativeWork.tsx)
export const openChatThread = (thread: string, prompt?: string, { send = false, hint = '' }: { send?: boolean; hint?: string } = {}) =>
  window.dispatchEvent(new CustomEvent(OPEN, { detail: { thread, prompt, send, hint } }))
export { USE_DRAFT } from './ChatEmail'   // a draft taken from the chat back to the Inbox composer

// ---------------------------------------------------------------- suggestions
// The welcome screen's questions come from assist/suggest.py: the questions Sam keeps asking, each with why it is suggested
// now ("16 open items · CEO", "next meeting · tomorrow 14:00"). The panel adds questions about the page Sam is on. After each
// answer the model proposes follow-ups (a ```followups block at the end of its answer, shown as buttons, not as text).
type Suggestion = { id: string; group: string; icon: string; label: string; prompt: string; hint?: string | null }
type Suggestions = { groups: { key: string; label: string }[]; items: Suggestion[] }
// One icon per kind of question, chosen to look the same size in a row (Sam, 16 Nov 2026: "I don't like the icons too much,
// they're different sizes"): outline glyphs that fill their square, no hands, coins or quote marks, all drawn by SuggIcon.
const ICONS: Record<string, LucideIcon> = { focus: Crosshair, meeting: CalendarDays, asked: MessageCircleQuestion, person: CircleUserRound,
  waiting: Hourglass, reach: UsersRound, reply: Mail, promise: ListTodo, decision: Scale, drop: Archive, numbers: ChartColumn, deal: CircleDollarSign,
  bet: Compass, v2mom: Flag, idea: Lightbulb, time: Clock, said: MessageSquareQuote, doc: FileText, sheet: FileSpreadsheet, graph: Network, roadmap: MapIcon }
const SuggIcon = ({ name, className }: { name: string; className?: string }) => {
  const Icon = ICONS[name] ?? Sparkles
  return <Icon size={16} strokeWidth={1.75} className={cn('shrink-0 text-ink3 transition-colors', className)} aria-hidden />
}
const fallback = (): Suggestion[] => [   // while the live ones load, or if they cannot (built after the profile is known)
  { id: 'focus', group: 'today', icon: 'focus', label: 'What should I focus on today?', prompt: 'What should I focus on today, and why? Rank the few things that matter most.' },
  ...(profile().manager ? [{ id: 'ceo', group: 'people', icon: 'person', label: `What is open between me and ${profile().manager.split(' ')[0]}?`, prompt: `What is open between me and ${profile().manager}? Group it into what I owe, what ${({ he: 'he', she: 'she' } as Record<string, string>)[profile().manager_pronouns.split('/')[0]] ?? 'they'} owe${['he', 'she'].includes(profile().manager_pronouns.split('/')[0]) ? 's' : ''} me and what is waiting on a decision.` }] : []),
  { id: 'decisions', group: 'open', icon: 'decision', label: 'Which decisions have been pending longest?', prompt: 'Which decisions are pending with me, oldest first? For each: what is the call, who is waiting on it, and what do you recommend?' },
  { id: 'quarter', group: 'numbers', icon: 'numbers', label: 'How did last quarter go by region?', prompt: 'How did last quarter go by region versus the one before? New business, renewals and win rate, with what stands out.' },
]
// the best few, at most two from any group, so the first screen covers more than one kind of question
const pickTop = (xs: Suggestion[], n: number) => { const per: Record<string, number> = {}; return xs.filter((x) => (per[x.group] = (per[x.group] ?? 0) + 1) <= 2).slice(0, n) }
const greeting = () => { const h = Number(new Intl.DateTimeFormat(LOCALE, { hour: 'numeric', hour12: false, timeZone: TZ }).format(new Date()))
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' }

// Questions about the chip a new chat holds (what is open on the page: assist/page_context.py), for the welcome screen and
// the badge's hover menu. Short labels; the full question is what is asked.
function chipSuggestions(ctx: PageCtx | null): Suggestion[] {
  const s = (id: string, icon: string, label: string, prompt: string): Suggestion => ({ id: `chip-${id}`, group: 'page', icon, label, prompt })
  if (!ctx) return []
  const t = ctx.label, first = t.split(' ')[0]
  if (ctx.kind === 'message') return [
    s('sum', 'said', 'Summarise the conversation', 'Summarise this conversation: what was asked, what was agreed, and what is still open on each side.'),
    s('need', 'asked', 'What do they need from me?', 'What do they need from me in this conversation, by when, and what should I answer?'),
    s('reply', 'reply', 'Draft my reply', 'Draft my reply to the latest message in this conversation, in my voice.')]
  if (ctx.kind === 'email') return [
    ctx.draft ? s('improve', 'reply', 'Improve my draft', 'Review my draft reply to this email against the thread: what it misses, what to cut, and a better version.')
      : s('reply', 'reply', 'Draft a reply', 'Draft my reply to this email, in my voice.'),
    s('ask', 'asked', 'What is being asked of me?', 'What is this email thread asking of me, from whom and by when? What is the history behind it?'),
    s('who', 'person', 'Who else should know?', 'Who else should hear about this email, and what would I tell them?')]
  if (ctx.kind === 'initiative') return [
    s('track', 'bet', 'Is it on track?', `Is ${t} on track? What has moved in the last two weeks, what is stuck, and what should I do about it?`),
    s('decide', 'decision', 'What needs my decision?', `What on ${t} is waiting on a decision from me, who is waiting, and what do you recommend?`),
    s('update', 'doc', "Draft this week's update", `Draft this week's update for ${t}: what moved, what is at risk, and what I need from whom. Short, in my voice.`)]
  if (ctx.kind === 'topic') return [
    s('stand', 'focus', 'Where does it stand?', 'Where does this topic stand, who is driving it, and what is open on me?'),
    s('next', 'idea', 'What should I do next?', 'What should I do next on this topic, and who should I talk to?')]
  if (ctx.kind === 'task') return [
    s('next', 'focus', 'What is the next step?', 'What is the next step on this task, who owns it, and is anything blocking it?'),
    s('email', 'reply', 'Draft the next email', 'Draft the email that moves this task forward, in my voice.')]
  if (ctx.kind === 'person') return [
    s('open', 'person', 'What is open between us?', `What is open between me and ${t}? Group it into what I owe, what they owe me and what is waiting on a decision.`),
    s('prep', 'meeting', `Prep my next meeting with ${first}`, `Prep me for my next meeting with ${t}: what is open, what they care about right now, and what I should push for.`),
    s('said', 'said', `What has ${first} said lately?`, `What has ${t} said in meetings, mail and chat over the last two weeks that I should know about?`)]
  if (ctx.kind === 'meeting') return [
    s('agreed', 'said', 'What was agreed?', 'What was agreed in this meeting, who owes what, and what should I follow up on?'),
    s('follow', 'reply', 'Draft the follow-up', 'Draft a short follow-up email for this meeting: the decisions, the owners and the dates. In my voice.')]
  if (ctx.kind === 'event') return [
    s('prep', 'meeting', 'Prep me for it', 'Prep me for this meeting: who is in it, what is open with them, and what I should get out of it.')]
  return []
}
// what the chip is, in a word, for "Ask about this email…"
const chipNoun = (ctx: PageCtx) => ctx.kind === 'person' ? ctx.label.split(' ')[0]
  : `this ${({ message: 'conversation', event: 'meeting' } as Record<string, string>)[ctx.kind] ?? ctx.kind}`

// questions about the page Sam is on when nothing on it is open (the chat is told the page)

function pageSuggestions(path: string, title: string): Suggestion[] {
  const t = title.trim(), first = t.split(' ')[0]
  const s = (id: string, icon: string, label: string, prompt: string): Suggestion => ({ id: `page-${id}`, group: 'page', icon, label, prompt })
  if (/^\/people\/p-\d+/.test(path) && t) return [
    s('open', 'person', `What is open between me and ${first}?`, `What is open between me and ${t}? Group it into what I owe, what they owe me and what is waiting on a decision.`),
    s('prep', 'meeting', `Prep me for my next meeting with ${first}`, `Prep me for my next meeting with ${t}: what is open, what they care about right now, and what I should push for.`),
    s('said', 'said', `What has ${first} said lately that matters?`, `What has ${t} said in meetings, mail and chat over the last two weeks that I should know about?`)]
  if (/^\/initiatives\/[^/]+/.test(path) && t) return [
    s('track', 'bet', `Is ${t} on track?`, `Is ${t} on track? What has moved in the last two weeks, what is stuck, and what should I do about it?`),
    s('decided', 'decision', `What have we decided on ${t} lately?`, `What has been decided on ${t} in the last month, by whom, and what is still open?`),
    s('update', 'doc', `Draft this week's update for ${t}`, `Draft this week's update for ${t}: what moved, what is at risk, and what I need from whom. Short, in my voice.`)]
  if (/^\/meetings\/m-\d+/.test(path)) return [
    s('asked', 'asked', 'What was asked of me in this meeting?', 'In this meeting, what was asked of me, what did I commit to, and by when?'),
    s('decided', 'decision', 'What was decided, and who owns what?', 'What was decided in this meeting, who owns each follow-up, and what is still unresolved?'),
    s('follow', 'reply', 'Draft a follow-up email for this meeting', 'Draft a short follow-up email for this meeting: the decisions, the owners and the dates. In my voice.'),
    s('minutes', 'doc', 'Write up this meeting as a Word document', 'Write up this meeting as a Word document: purpose, decisions, actions with owners and dates, and open questions.')]
  if (path.startsWith('/inbox')) return [
    s('matter', 'reply', 'Which emails matter most today?', 'Which emails in my inbox matter most today, and why? Give me a one-line answer for each that needs one.'),
    s('draft', 'reply', 'Draft a reply to the email I have open', 'Draft a reply to the email I have open. Short, purpose first, in my voice.')]
  if (path.startsWith('/loops')) return [
    s('drop', 'drop', 'Which open items should I close or drop?', 'Which of my open items are done, stale or no longer mine? Recommend close, chase or drop for each.'),
    s('overdue', 'promise', 'What is overdue?', 'Which promises and waits are overdue, with whom, and what is the quickest way to clear each?')]
  if (path.startsWith('/pipeline')) return [
    s('risk', 'deal', 'Which deals are at risk this quarter?', 'Which open deals this quarter are at risk, why, and what would move them?'),
    s('compare', 'numbers', 'How does pipeline compare with last quarter?', 'How does the open pipeline compare with this point last quarter, by region and deal type?'),
    s('export', 'sheet', 'Export the open pipeline to Excel', 'Make an Excel workbook of the open pipeline: account, deal, stage, close date, ACV in USD, forecast category and region, sorted by close date.')]
  if (path.startsWith('/roadmap')) return [
    s('risk', 'roadmap', 'What is at risk on the roadmap?', 'Which roadmap items due this quarter are at risk, and what is blocking them?'),
    s('bets', 'bet', 'Does the roadmap match my bets?', 'Does the roadmap match the weights of my bets? Where is effort going that the strategy does not ask for?')]
  if (path.startsWith('/code')) return [   // Knowledge › Product › Code base (views/code.tsx): ask-code reads the clones
    s('roles', 'doc', 'How do user roles and permissions work?', 'How do user roles and permissions work in our product: which roles exist, what each can do, and where an admin sets them? Check the code if the docs do not say.'),
    s('apis', 'doc', 'Which public APIs does the product offer?', 'Which public APIs does our product offer and what can they do? Check the code if the docs do not say.')]
  if (path.startsWith('/explore/graph')) return [
    s('people', 'graph', 'Who should I spend more time with?', 'Looking at who I work with and how often, who should I spend more time with, and who less?'),
    s('bets', 'bet', 'Who really drives each bet?', 'For each of my bets, who actually drives it day to day, judging by meetings, mail and open items?')]
  if (path.startsWith('/documents')) return [
    s('sum', 'doc', 'Summarise the document I have open', 'Summarise the document I have open: what it says, what it asks of me, and what is missing.')]
  if (path.startsWith('/calendar') || path === '/meetings') return [
    s('drop', 'meeting', 'Which meetings this week could I drop?', 'Which of my meetings this week could I drop, shorten or delegate, and to whom?')]
  return []
}

function usePageSuggestions(on: boolean) {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const [title, setTitle] = useState('')
  useEffect(() => {   // the page's heading names the person, bet or meeting; it can arrive after the page's data
    if (!on) return
    const read = () => setTitle(document.querySelector('main h1')?.textContent?.trim() || '')
    read()
    const ts = [setTimeout(read, 300), setTimeout(read, 1200)]
    return () => ts.forEach(clearTimeout)
  }, [path, on])
  return useMemo(() => ({ title, items: on ? pageSuggestions(path, title) : [] }), [on, path, title])
}

// the blocks at the end of an answer (```changes, then ```followups), split from its text; while streaming, a half-written
// block is hidden too. A change that is not one of the known kinds is dropped.
const STATUSES = { loop: ['done', 'dropped', 'snoozed', 'open'], action: ['done', 'dismissed', 'snoozed', 'open'] } as const
const validChange = (x: unknown): x is Change => {
  if (!x || typeof x !== 'object') return false
  const c = x as Change
  if (c.type === 'refresh') return c.mode === 'mail' || c.mode === 'sync' || c.mode === 'full'
  if (c.type === 'decide') return typeof c.subject === 'string' && /^(topic:\d+|[a-z0-9-]+)$/.test(c.subject) && !!c.question?.trim()
    && (c.decided === false || !!(c.choice?.trim() || c.note?.trim()))
  return (c.type === 'loop' || c.type === 'action') && c.id != null && (STATUSES[c.type] as readonly string[]).includes(c.status ?? '')
}
function splitBlocks(text: string, live: boolean): { body: string; follow: string[]; changes: Change[] } {
  const start = text.search(/\n*```(?:followups|changes)/)
  if (start < 0) {
    const tail = live ? text.match(/`{1,3}[a-z]*$/)?.[0] : undefined
    return { body: tail && ['```followups', '```changes'].some((f) => f.startsWith(tail)) ? text.slice(0, -tail.length).trimEnd() : text, follow: [], changes: [] }
  }
  let follow: string[] = [], changes: Change[] = []
  for (const m of text.slice(start).matchAll(/```(followups|changes)[^\n]*\n([\s\S]*?)(?:\n```|$)/g)) {
    try {
      const v = JSON.parse(m[2])
      if (!Array.isArray(v)) continue
      if (m[1] === 'followups') follow = v.filter((x): x is string => typeof x === 'string' && !!x.trim()).slice(0, 3)
      else changes = v.filter(validChange).slice(0, 8)
    } catch { /* still streaming */ }
  }
  return { body: text.slice(0, start).trimEnd(), follow, changes }
}
const iso = (s: string) => new Date(s.endsWith('Z') || s.includes('+') ? s : s + 'Z')
const dayGroup = (s: string) => { const d = iso(s), t = new Date(); const k = (x: Date) => x.toDateString(); const y = new Date(t); y.setDate(t.getDate() - 1)
  return k(d) === k(t) ? 'Today' : k(d) === k(y) ? 'Yesterday' : (t.getTime() - d.getTime()) < 7 * 864e5 ? 'This week' : 'Earlier' }
const hm = (s: string) => iso(s).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' })

// the app address on screen (hash routing), what the chip is resolved from
const herePath = () => location.hash.replace(/^#/, '').split('?nolive')[0] || '/'

// ---------------------------------------------------------------- shared state
type Chat = {
  open: boolean; setOpen: (o: boolean | ((o: boolean) => boolean)) => void   // the floating panel
  full: boolean                                                             // on the Assistant page
  tid: string | null; turns: Turn[]; busy: boolean; unread: boolean; notice: string   // busy: the conversation on screen is answering
  running: number; answering: (id: string) => boolean; unreadIds: Set<string>      // answers running anywhere; finished while Sam was elsewhere
  edits: Record<string, ChatDraftSaved>; setEdit: (key: string, s: ChatDraftSaved) => void   // Sam's versions of the emails (components/ChatEmail.tsx)
  input: string; setInput: (s: string) => void
  threads: ThreadRow[]; groups: { label: string; rows: ThreadRow[] }[]; title: string
  send: (text: string, o?: SendOpts) => void; stop: () => void; fresh: () => void; pick: (id: string) => void; remove: (id: string) => void; handoff: () => void
  box: RefObject<HTMLTextAreaElement | null>; focus: () => void
  chip: PageCtx | null; dropChip: () => void; startHere: () => void   // what a new chat from the floating button holds (assist/page_context.py)
  ask: (text: string, ctx: PageCtx | null) => void                   // the badge's hover menu: a new chat about ctx, asked at once
  hint: string   // the placeholder the page that opened this conversation asked for, until Sam writes in it
}
type SendOpts = { thread?: null; chip?: PageCtx | null }   // thread null: a new conversation; chip: the context to ask with
const Ctx = createContext<Chat | null>(null)
// every email draft in the conversation, in order (as Sam left it), so a card can show what changed since an earlier version
type DraftVersion = { turn: number; n: number; mail: number | null; orig: string; fields: EmailFields }
const DraftHistory = createContext<DraftVersion[]>([])
export const useChat = () => { const c = useContext(Ctx); if (!c) throw new Error('useChat outside ChatProvider'); return c }

// Answers run on the server on their own (assist/chat.py start; Sam, 25 Nov 2026: "When the assistant is working, I'm not able
// to access any other chats or previous chats ... make sure that we can run multiple assistants in parallel without affecting
// the rest of the application"). Asking returns at once with the answer's job, and the page fetches what it has said since
// with short requests: every 300 ms while it is on screen, every 2 s otherwise. No request stays open, so answers never take
// the browser's connections from the rest of the app, and Sam can switch conversation, open History, start another answer,
// close the panel or reload while answers come in. Each conversation answers one question at a time.
type LiveAnswer = { job: string; turns: Turn[]; next: number; run?: string }
const NEW = '(new)'   // the conversation being started, before the server names it
const POLL_MS = 300, AWAY_EVERY = 7   // on screen every tick; off screen every 7th (about 2 s)

export function ChatProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const full = useRouterState({ select: (s) => s.location.pathname }) === ASSISTANT
  const [open, setOpen] = useState(() => /[?&]chat=open\b/.test(location.hash))   // a link with chat=open opens the chat
  const [tid, setTid] = useState<string | null>(() => { try { return sessionStorage.getItem(CUR) } catch { return null } })
  const [saved, setTurns] = useState<Turn[]>([])   // the conversation on screen as saved; while it answers, its live turns are shown
  const [edits, setEdits] = useState<Record<string, ChatDraftSaved>>({})
  const setEdit = (key: string, v: ChatDraftSaved) => setEdits((e) => ({ ...e, [key]: v }))
  const [input, setInput] = useState('')
  const [starting, setStarting] = useState<string | null>(null)   // a question on its way to the server: its conversation, or NEW
  const [unread, setUnread] = useState(false)
  const [unreadIds, setUnreadIds] = useState<Set<string>>(() => new Set())   // conversations that finished answering while Sam was elsewhere
  const [notice, setNotice] = useState('')
  const [opened, setOpened] = useState<{ thread: string; hint: string } | null>(null)
  // the chip a new chat from the floating button starts with: what is on screen (assist/page_context.py); × removes it
  const [chip, setChip] = useState<PageCtx | null>(null)
  const chipOff = useRef(false)   // removed by hand: not put back when the page changes
  const box = useRef<HTMLTextAreaElement | null>(null)
  const pending = useRef<{ thread: string; prompt: string } | null>(null)   // a question to ask once its conversation is on screen
  const [loaded, setLoaded] = useState<string | null>(null)                 // the conversation whose saved turns are on screen
  const visible = open || full
  const startRef = useRef<() => void>(() => {})
  // the answers running, by conversation: kept in a ref (the poller reads it between renders), drawn through a counter
  const lives = useRef<Record<string, LiveAnswer>>({})
  const [, redraw] = useState(0)
  const putLive = (th: string, a: LiveAnswer | null) => {
    const n = { ...lives.current }
    if (a) n[th] = a; else delete n[th]
    lives.current = n; redraw((x) => x + 1)
  }
  const turns = tid && lives.current[tid] ? lives.current[tid].turns : saved
  const busy = !!(tid && lives.current[tid]) || starting === (tid ?? NEW)   // the conversation on screen is answering
  const live = useRef({ open, full, visible, busy, tid })
  live.current = { open, full, visible, busy, tid }
  const focus = () => setTimeout(() => box.current?.focus(), 60)
  const flash = (s: string) => { setNotice(s); setTimeout(() => setNotice((n) => (n === s ? '' : n)), 7000) }

  const running = Object.keys(lives.current).length
  const history = useQuery({ queryKey: ['chatThreads'], queryFn: () => api.chatThreads<ThreadRow>(), enabled: visible, refetchInterval: running ? 5000 : false })
  const threads = useMemo(() => history.data ?? [], [history.data])
  const current = threads.find((t) => t.id === tid)
  // answering now: the ones this tab follows, and the ones the server says run (asked in another tab)
  const answering = (id: string) => !!lives.current[id] || !!threads.find((t) => t.id === id)?.live

  // follow an answer running in a conversation (just asked, or found running when the conversation opened)
  const follow = (th: string, job: string, base: Turn[]) => {
    if (lives.current[th]?.job === job) return
    putLive(th, { job, turns: [...base, { role: 'assistant', text: '', steps: [] }], next: 0 })
  }
  // an answer has ended: the saved conversation replaces its live turns
  const ending = useRef(new Set<string>())
  const finish = (th: string) => {
    if (ending.current.has(th)) return
    ending.current.add(th)
    qc.invalidateQueries({ queryKey: ['chatThreads'] })
    qc.invalidateQueries({ queryKey: ['review'] })   // a ```review block in the answer has just started its review (assist/chat.py turn)
    if (!live.current.visible || live.current.tid !== th) setUnreadIds((s) => new Set(s).add(th))
    if (!live.current.visible) setUnread(true)
    api.chatThread<Turn>(th).then((t) => { if (live.current.tid === th) { setTurns(t.turns); setEdits(t.drafts ?? {}) } })
      .catch(() => {}).finally(() => { ending.current.delete(th); if (lives.current[th]) putLive(th, null) })
  }
  const apply = (th: string, d: ChatLive) => {
    const a = lives.current[th]
    if (!a || a.job !== d.job || d.next < a.next) return
    let ts = a.turns, run = a.run
    const patch = (f: (m: Turn) => Turn) => { ts = [...ts.slice(0, -1), f(ts[ts.length - 1])] }
    for (const e of d.events) {
      if (e.type === 'run' && e.run) { run = e.run; patch((m) => ({ ...m, run: e.run })) }
      else if (e.type === 'text') patch((m) => ({ ...m, text: m.text + (e.text ?? '') }))
      else if (e.type === 'tool') {
        patch((m) => ({ ...m, steps: [...(m.steps ?? []), e.label ?? ''], asks: m.asks || !!e.desktop }))
        if (e.desktop) {   // it waits for Sam to allow a step on the Mac: show him
          qc.invalidateQueries({ queryKey: ['chatDesktop'] })
          if (!live.current.visible) { setTid(th); setOpen(true); setUnread(true) }
          else if (live.current.tid !== th) { setUnreadIds((s) => new Set(s).add(th)); flash('Another conversation is waiting for you to allow a step on your Mac: open it from History.') }
        }
      }
      else if (e.type === 'error') patch((m) => ({ ...m, error: e.error }))
      else if (e.type === 'files') patch((m) => ({ ...m, made: e.files }))
      else if (e.type === 'done') patch((m) => ({ ...m, secs: e.secs }))
    }
    if (d.events.length || d.next !== a.next) putLive(th, { ...a, turns: ts, next: d.next, run })
    if (d.done) finish(th)
  }
  // the poller: one short request per answer, never two at once for the same one
  const inflight = useRef(new Set<string>())
  const tick = useRef(0)
  const followed = Object.keys(lives.current).join('|')
  useEffect(() => {
    if (!followed) return
    const t = window.setInterval(() => {
      tick.current++
      for (const [th, a] of Object.entries(lives.current)) {
        const near = live.current.visible && live.current.tid === th
        if ((!near && tick.current % AWAY_EVERY) || inflight.current.has(a.job) || ending.current.has(th)) continue
        inflight.current.add(a.job)
        api.chatLive(a.job, a.next).then((d) => apply(th, d))
          .catch((err) => { if (String(err?.message ?? err).startsWith('404')) finish(th) })   // gone (the server restarted): the saved turns say what happened
          .finally(() => inflight.current.delete(a.job))
      }
    }, POLL_MS)
    return () => window.clearInterval(t)
  }, [followed])   // eslint-disable-line react-hooks/exhaustive-deps

  // load the saved turns when switching conversation; one that is answering shows its live turns and is followed
  useEffect(() => {
    try { if (tid) sessionStorage.setItem(CUR, tid); else sessionStorage.removeItem(CUR) } catch { /* private window */ }
    if (!tid) { if (starting !== NEW) { setTurns([]); setEdits({}) } setLoaded(null); return }
    setUnreadIds((s) => { if (!s.has(tid)) return s; const n = new Set(s); n.delete(tid); return n })
    let on = true   // a slow load for a conversation Sam has already left must not overwrite the one he switched to
    api.chatThread<Turn>(tid).then((t) => {
      if (!on) return
      setEdits(t.drafts ?? {})
      if (!lives.current[tid]) { setTurns(t.turns); if (t.live) follow(tid, t.live, t.turns) }
      setLoaded(tid)
    }).catch(() => { if (on && !lives.current[tid]) { setTid(null); setTurns([]); setEdits({}) } })
    return () => { on = false }
  }, [tid])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (visible) setUnread(false) }, [visible])
  useEffect(() => { if (full) setOpen(false) }, [full])   // the page replaces the panel; it does not pop back up on the next page
  useEffect(() => {
    const onOpen = (e: Event) => {
      const d = (e as CustomEvent<string | { thread: string; prompt?: string; send?: boolean; hint?: string } | undefined>).detail
      let p = typeof d === 'string' ? d : d?.prompt
      if (d && typeof d === 'object') {   // a saved conversation, even while answers run elsewhere
        setTid(d.thread); setOpened(d.hint ? { thread: d.thread, hint: d.hint } : null); qc.invalidateQueries({ queryKey: ['chatThreads'] })
        if (d.send && p) { pending.current = { thread: d.thread, prompt: p }; p = undefined }
      }
      if (!live.current.full) setOpen(true); if (p) setInput(p); focus()
    }
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') {
        e.preventDefault()
        if (live.current.full) focus(); else if (live.current.open) setOpen(false); else startRef.current()
      } else if (e.key === 'Escape' && live.current.open) setOpen(false)
    }
    window.addEventListener(OPEN, onOpen); window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener(OPEN, onOpen); window.removeEventListener('keydown', onKey) }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  const send = async (text: string, o: SendOpts = {}) => {
    const message = text.trim()
    const thread = 'thread' in o ? null : tid
    if (!message || (thread ? !!lives.current[thread] : false) || starting === (thread ?? NEW)) return   // this conversation is still answering
    // what Sam is looking at, so "this page" means something; on the Assistant page there is nothing to point at
    const path = location.hash.replace(/^#/, '').split('?nolive')[0] || '/'
    const title = document.querySelector('main h1')?.textContent?.trim() || ''
    const ctx = 'chip' in o ? o.chip ?? null : !thread ? chip : null
    const page = live.current.full ? null : { path, title, ...(ctx ? { context: { kind: ctx.kind, ref: ctx.ref } } : {}) }
    const q: Turn = { role: 'user', text: message, page: ctx ? ctx.label : page ? title || path : null, ctx: ctx ?? undefined }
    const blank: Turn = { role: 'assistant', text: '', steps: [] }
    const base = thread && thread === tid ? saved : []
    setTurns([...base, q, blank])   // shown at once, while the server stores the question
    setChip(null); setInput(''); setStarting(thread ?? NEW)
    try {
      const r = await api.chatStart({ message, thread, page })
      putLive(r.thread, { job: r.job, turns: [...base, q, blank], next: 0 })
      if (!thread && live.current.tid === null) setTid(r.thread)   // still on the new chat: it becomes this conversation (elsewhere: it is in History)
      qc.invalidateQueries({ queryKey: ['chatThreads'] })
    } catch (err) {   // refused (this conversation is answering, or too many answers at once) or the server is away
      if (live.current.tid === thread) setTurns([...base, q, { ...blank, error: String(err instanceof Error ? err.message : err) }])
    } finally { setStarting(null) }
  }
  // a page's button: its question is asked as soon as its conversation's saved turns are on screen and it is not answering
  useEffect(() => {
    const q = pending.current
    if (q && tid === q.thread && loaded === q.thread && !busy) { pending.current = null; void send(q.prompt) }
  }, [tid, loaded, busy])   // eslint-disable-line react-hooks/exhaustive-deps
  const stop = async () => { const a = tid ? lives.current[tid] : null; if (a) await api.chatStopJob(a.job).catch(() => {}) }
  const fresh = () => { setTid(null); setTurns([]); setEdits({}); setChip(null); focus() }
  const loadChip = () => { if (live.current.full) { setChip(null); return } api.chatPageContext(herePath()).then((r) => setChip(chipOff.current ? null : r.context)).catch(() => setChip(null)) }
  // the floating button and ⌘J (16 Nov 2026): a new chat that holds what is on screen; while the conversation on screen is
  // answering, just the panel with it (New conversation starts another meanwhile)
  const startHere = () => {
    if (!live.current.busy) { setTid(null); setTurns([]); setEdits({}); setOpened(null); chipOff.current = false; setChip(null); loadChip() }
    setOpen(true); focus()
  }
  const dropChip = () => { chipOff.current = true; setChip(null); focus() }
  const ask = (text: string, ctx: PageCtx | null) => {
    setOpened(null); chipOff.current = !ctx; setChip(null); setTid(null); setTurns([]); setEdits({}); setOpen(true)
    void send(text, { thread: null, chip: ctx })
  }
  const pick = (id: string) => setTid(id)
  const remove = async (id: string) => {
    const a = lives.current[id]
    if (a) { await api.chatStopJob(a.job).catch(() => {}); putLive(id, null) }   // a conversation deleted while it answers stops first
    await api.chatDelete(id).catch(() => {})
    if (id === tid) { setTid(null); setTurns([]) }
    qc.invalidateQueries({ queryKey: ['chatThreads'] })
  }
  // Continue in Claude Desktop (Cowork): the conversation and its cited sources go into a workspace folder; the text in the
  // box (if any) becomes the request, e.g. "turn this into a two-page memo".
  const handoff = async () => {
    if (!tid || busy) return
    setNotice('Opening Claude…')
    try {
      const d = await api.chatHandoff(tid, input)
      setInput('')
      setNotice(`Opened in Claude Desktop with the conversation${d.files.length > 1 ? ` and ${d.files.length - 1} source file${d.files.length > 2 ? 's' : ''}` : ''}.`)
    } catch (e) { setNotice(`Could not open Claude: ${e instanceof Error ? e.message : e}`) }
    setTimeout(() => setNotice(''), 6000)
  }
  const groups = useMemo(() => {
    const g: { label: string; rows: ThreadRow[] }[] = []
    for (const t of threads) { const l = dayGroup(t.updated_at); if (g.at(-1)?.label !== l) g.push({ label: l, rows: [] }); g.at(-1)!.rows.push(t) }
    return g
  }, [threads])
  const title = current?.title ?? (turns.length ? turns[0].text : '')
  const hint = opened && opened.thread === tid && loaded === tid && turns.length <= 2 ? opened.hint : ''   // the seed's two turns, nothing asked yet

  startRef.current = startHere
  // an empty new chat follows the page: the chip names what is open now (not after Sam removed it, nor once he has asked)
  const here = useRouterState({ select: (s) => s.location.href })
  useEffect(() => { if (open && !tid && !turns.length && !chipOff.current && !busy) loadChip() }, [here])   // eslint-disable-line react-hooks/exhaustive-deps
  return <Ctx.Provider value={{ open, setOpen, full, tid, turns, edits, setEdit, busy, running, answering, unreadIds, unread, notice, input, setInput, threads, groups, title,
    send, stop, fresh, pick, remove, handoff, box, focus, hint, chip, dropChip, startHere, ask }}>{children}</Ctx.Provider>
}

// ---------------------------------------------------------------- the floating badge and panel (every page but Assistant)
// Size (Sam, 29 Oct 2026: "too small ... big enough and adjustable to the screen size"): by default it grows with the window,
// 42% of its width (520 to 820 px) and its full height below the top bar (900 px at most). Sam drags the left edge, the top edge or the
// top-left corner to resize it; the size is kept in this browser and never exceeds the window. Double-click the corner resets.
const SIZE = 'assist-chat-size'
type Size = { w: number; h: number }
const readSize = (): Size | null => { try { const s = JSON.parse(localStorage.getItem(SIZE) || 'null'); return s?.w && s?.h ? s : null } catch { return null } }

export function ChatHost() {
  const c = useChat()
  const navigate = useNavigate()
  const [showHistory, setShowHistory] = useState(false)
  const [size, setSize] = useState<Size | null>(readSize)
  const panel = useRef<HTMLElement>(null)
  useEffect(() => { const reset = () => setShowHistory(false); window.addEventListener(OPEN, reset); return () => window.removeEventListener(OPEN, reset) }, [])
  // the panel is anchored bottom right, so dragging left or up makes it bigger
  const drag = (dir: 'x' | 'y' | 'xy') => (e: ReactPointerEvent) => {
    const el = panel.current
    if (!el || e.button !== 0) return
    e.preventDefault()
    const r = el.getBoundingClientRect(), x0 = e.clientX, y0 = e.clientY
    let next: Size = { w: Math.round(r.width), h: Math.round(r.height) }
    const body = document.body.style, cursor = getComputedStyle(e.currentTarget).cursor
    body.cursor = cursor; body.userSelect = 'none'
    const move = (m: PointerEvent) => {
      next = { w: dir === 'y' ? next.w : Math.round(Math.min(Math.max(r.width + x0 - m.clientX, 380), window.innerWidth - 40)),
        h: dir === 'x' ? next.h : Math.round(Math.min(Math.max(r.height + y0 - m.clientY, 360), window.innerHeight - 140)) }
      setSize(next)
    }
    const up = () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
      body.cursor = ''; body.userSelect = ''
      try { localStorage.setItem(SIZE, JSON.stringify(next)) } catch { /* private window: kept for this visit */ }
    }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
  }
  const resetSize = () => { setSize(null); try { localStorage.removeItem(SIZE) } catch { /* private window */ } }
  // hovering the badge shows quick questions about what is on screen (Sam, 16 Nov 2026: "hover over the assistant pop-up and it
  // comes up with kind of quick actions"): shown after a short pause, kept while the pointer moves between badge and menu
  const qc = useQueryClient()
  const [menu, setMenu] = useState(false)
  const menuT = useRef<number | undefined>(undefined)
  const hoverMenu = (on: boolean) => {
    window.clearTimeout(menuT.current)
    if (on && menu) return
    if (on) void qc.prefetchQuery({ queryKey: ['pageContext', herePath()], queryFn: () => api.chatPageContext(herePath()), staleTime: 30_000 })
    menuT.current = window.setTimeout(() => setMenu(on), on ? 260 : 200)
  }
  useEffect(() => { if (c.open) { window.clearTimeout(menuT.current); setMenu(false) } }, [c.open])
  if (c.full) return null
  const { open, setOpen } = c
  return <>
    {!open && menu && <QuickMenu onHover={hoverMenu} onDone={() => setMenu(false)} />}
    {/* the floating badge: always there, bottom right */}
    <button onClick={() => (open ? setOpen(false) : c.startHere())} title={open ? 'Close SleePO (⌘J)' : undefined} aria-label={open ? 'Close SleePO chat' : 'Ask SleePO about this page (⌘J)'} aria-expanded={open}
      onMouseEnter={() => !open && hoverMenu(true)} onMouseLeave={() => hoverMenu(false)}
      className="group fixed bottom-5 right-5 z-50 size-[52px] rounded-full bg-accent shadow-[0_6px_20px_-6px_rgba(0,0,0,0.45)] ring-1 ring-ink/20 transition-transform hover:scale-105 active:scale-95">
      <span className="absolute inset-0 overflow-hidden rounded-full">
        {open ? <span className="grid size-full place-items-center text-onaccent"><ChevronDown size={24} strokeWidth={2.5} /></span>
          : <span className="grid size-full place-items-center"><Logo size={36} /></span>}
      </span>
      {c.running > 0 && <span aria-hidden title={`${c.running} answer${c.running > 1 ? 's' : ''} coming in`} className="absolute -inset-1 animate-spin rounded-full border-2 border-transparent border-t-ink" />}
      {c.unread && !open && <span aria-label="new answer" className="absolute -right-0.5 -top-0.5 size-3.5 rounded-full bg-hot ring-2 ring-bg" />}
    </button>

    {open && (
      <section ref={panel} role="dialog" aria-label="Ask SleePO"
        style={size ? { width: `min(${size.w}px, calc(100vw - 40px))`, height: `min(${size.h}px, calc(100dvh - 140px))` } : undefined}
        className="fixed bottom-[84px] right-5 z-50 flex h-[min(900px,calc(100dvh-140px))] w-[min(max(520px,42vw),820px,calc(100vw-40px))] flex-col rounded-[20px] border border-line bg-panel shadow-[0_28px_70px_-24px_rgba(0,0,0,0.4),0_6px_18px_-8px_rgba(0,0,0,0.14)]">
        <div aria-hidden onPointerDown={drag('x')} className="absolute -left-1 top-3 bottom-0 z-10 w-2 cursor-ew-resize" />
        <div aria-hidden onPointerDown={drag('y')} className="absolute -top-1 left-3 right-0 z-10 h-2 cursor-ns-resize" />
        <div role="separator" aria-label="Resize the chat" title="Drag to resize · double-click for the default size" onPointerDown={drag('xy')} onDoubleClick={resetSize}
          className="group/rs absolute -left-1 -top-1 z-20 grid size-6 cursor-nwse-resize place-items-start p-1.5">
          <span className="size-2 rounded-tl-[3px] border-l-2 border-t-2 border-ink3 opacity-0 transition-opacity group-hover/rs:opacity-100" /></div>
        <header className="flex shrink-0 items-center gap-2 border-b border-line2 py-2.5 pl-4 pr-2.5">
          <Logo size={22} className="shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-semibold leading-tight">{showHistory ? 'Conversations' : c.title || 'Ask SleePO'}</div>
            {showHistory && <div className="text-[11.5px] leading-tight text-ink3">{c.threads.length} saved · kept <RetentionDays /> days</div>}
          </div>
          {c.tid && <IconBtn title={c.input.trim() ? 'Continue in Claude Desktop with this request' : 'Continue in Claude Desktop (type a request first to say what to produce)'} onClick={c.handoff} disabled={c.busy}><ClaudeMark size={15} /></IconBtn>}
          <IconBtn title="Conversations" on={showHistory} onClick={() => setShowHistory((h) => !h)}><History size={15} /></IconBtn>
          <IconBtn title="New conversation" onClick={() => { c.fresh(); setShowHistory(false) }}><Plus size={16} /></IconBtn>
          <IconBtn title="Open full screen (Assistant)" onClick={() => navigate({ to: ASSISTANT })}><Maximize2 size={14} /></IconBtn>
          <IconBtn title="Close (Esc)" onClick={() => setOpen(false)}><X size={16} /></IconBtn>
        </header>
        {showHistory
          ? <div className="min-h-0 flex-1 overflow-y-auto py-1"><ThreadList onPick={() => setShowHistory(false)} /></div>
          : <Conversation onHistory={() => setShowHistory(true)} inner="px-4 pb-2 pt-4" />}
        <div className="shrink-0 px-3 pb-3 pt-2"><Composer onSend={() => setShowHistory(false)} /></div>
      </section>)}
  </>
}

// ---------------------------------------------------------------- pieces both views use
// a conversation in History: a spinner while it answers, a dot when an answer finished while Sam was elsewhere
function RowMark({ id }: { id: string }) {
  const c = useChat()
  if (c.answering(id)) return <span role="status" aria-label="Answering" title="Answering" className="mr-1 size-3 shrink-0 animate-spin rounded-full border-[1.5px] border-line border-t-ink" />
  if (c.unreadIds.has(id) && id !== c.tid) return <span aria-label="New answer" title="New answer" className="mr-1.5 size-2 shrink-0 rounded-full bg-hot" />
  return null
}
// compact (the Assistant page, Sam 22 Oct 2026): one line per conversation, its title, like Claude's sidebar; when it was and how
// many questions show on hover
export function ThreadList({ onPick, compact = false }: { onPick?: () => void; compact?: boolean }) {
  const c = useChat()
  if (!c.groups.length) return <p className="px-4 py-6 text-[13px] text-ink2">No conversations yet.</p>
  if (compact) return <>{c.groups.map((g) => (
    <div key={g.label} className="px-2">
      <div className="px-2 pb-0.5 pt-3 text-[11.5px] font-medium text-ink3">{g.label}</div>
      {g.rows.map((t) => (
        <div key={t.id} className={cn('group flex items-center rounded-lg transition-colors', t.id === c.tid ? 'bg-panel2' : 'hover:bg-panel2/70')}>
          <button onClick={() => { c.pick(t.id); onPick?.() }} title={`${t.title}\n${t.first && t.first !== t.title ? `Started: ${t.first}\n` : ''}${hm(t.updated_at)} · ${Math.ceil(t.turns / 2)} question${t.turns > 2 ? 's' : ''}`}
            className={cn('min-w-0 flex-1 truncate px-2 py-1.5 text-left text-[13px]', t.id === c.tid ? 'font-medium text-ink' : 'text-ink2 group-hover:text-ink')}>{t.title}</button>
          <RowMark id={t.id} />
          <button onClick={() => c.remove(t.id)} title="Delete conversation" aria-label={`Delete ${t.title}`} className="mr-1 shrink-0 rounded p-1 text-ink3 opacity-0 hover:text-hot group-hover:opacity-100 focus:opacity-100"><Trash2 size={13} /></button>
        </div>))}
    </div>))}</>
  return <>{c.groups.map((g) => (
    <div key={g.label}>
      <div className="px-4 pb-1 pt-3 text-[12px] font-semibold text-ink">{g.label}</div>
      {g.rows.map((t) => (
        <div key={t.id} className={cn('group flex items-center gap-2 border-l-2 px-4 py-2 hover:bg-panel2', t.id === c.tid ? 'border-accent bg-accentbg' : 'border-transparent')}>
          <button onClick={() => { c.pick(t.id); onPick?.() }} className="min-w-0 flex-1 text-left">
            <div className="truncate text-[13.5px]">{t.title}</div>
            <div className="text-[11.5px] text-ink3">{c.answering(t.id) ? 'Answering…' : <>{hm(t.updated_at)} · {Math.ceil(t.turns / 2)} question{t.turns > 2 ? 's' : ''}</>}</div>
          </button>
          <RowMark id={t.id} />
          <button onClick={() => c.remove(t.id)} title="Delete conversation" aria-label={`Delete ${t.title}`} className="p-1 text-ink3 opacity-0 hover:text-hot group-hover:opacity-100 focus:opacity-100"><Trash2 size={14} /></button>
        </div>))}
    </div>))}</>
}

// The conversation with its own scroll area. It follows a reply as it streams only while Sam is at the bottom: scrolled up to
// re-read, the view stays put and a "Latest" button brings him back. Sending, or opening a conversation, jumps to the end.
// wide: the Assistant page (larger type, centred welcome). inner: padding / width of the column inside the scroll area.
export function Conversation({ wide, onHistory, inner }: { wide?: boolean; onHistory?: () => void; inner?: string }) {
  const c = useChat()
  const box = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const [away, setAway] = useState(false)
  const toEnd = (smooth?: boolean) => { const el = box.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' }) }
  const onScroll = () => { const el = box.current; if (!el) return; const near = el.scrollHeight - el.scrollTop - el.clientHeight < 96; stick.current = near; setAway(!near) }
  useLayoutEffect(() => { stick.current = true; setAway(false); toEnd() }, [c.tid, c.turns.length])
  useLayoutEffect(() => { if (stick.current) toEnd() }, [c.turns])
  const size = wide ? 'text-[15px] leading-[1.6]' : 'text-[13.5px] leading-[1.55]'
  const lastQuestion = [...c.turns].reverse().find((t) => t.role === 'user')?.text
  // drafts are numbered across an answer's email and Teams/Slack blocks, as AnswerBody numbers them; the emails' history
  const drafts = useMemo(() => c.turns.flatMap((m, i) => m.role === 'user' ? [] : [...splitBlocks(m.text, false).body.matchAll(BLOCK)]
    .filter((x) => x[1] === 'email' || x[1] === 'teams' || x[1] === 'slack').map((x, n) => ({ x, n })).filter(({ x }) => x[1] === 'email')
    .map(({ x, n }) => { const orig = parseEmail(x[3]), e = c.edits[`${i}:${n}`]
      return { turn: i, n, mail: Number(x[2].trim().match(/^(\d+)/)?.[1]) || null, orig: orig.body, fields: e?.edited_at ? { ...orig, ...Object.fromEntries(Object.entries(e).filter(([k, v]) => ['to', 'cc', 'subject', 'body'].includes(k) && typeof v === 'string')) } : orig } })),
  [c.turns, c.edits])
  return (
    <DraftHistory.Provider value={drafts}>
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={box} onScroll={onScroll} role="log" aria-live="polite" aria-busy={c.busy} aria-label="Conversation" className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn(inner, !c.turns.length && 'flex min-h-full flex-col')}>
          {!c.turns.length ? <Welcome wide={wide} onHistory={onHistory} />
            : c.turns.map((m, i) => m.role === 'user'
              ? <Question key={i} m={m} size={size} />
              : <Answer key={i} m={m} turn={i} size={size} live={c.busy && i === c.turns.length - 1}
                  onRetry={!c.busy && i === c.turns.length - 1 && lastQuestion ? () => c.send(lastQuestion) : undefined}
                  onFollow={!c.busy && i === c.turns.length - 1 ? (q) => c.send(q) : undefined} k={`${c.tid}|${m.at ?? i}`} />)}
          {!c.busy && c.turns.length > 0 && <LooseRequests tid={c.tid} known={c.turns.flatMap((m) => m.acts ?? [])} runs={c.turns.flatMap((m) => m.run ? [m.run] : [])} />}
        </div>
      </div>
      {away && c.turns.length > 0 && (
        <button onClick={() => toEnd(true)} className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-line bg-panel px-3 py-1 text-[12px] text-ink shadow-[0_4px_14px_-4px_rgba(0,0,0,0.25)] hover:border-ink">
          <ArrowDown size={13} aria-hidden />{c.busy ? 'Following the answer' : 'Latest'}</button>)}
    </div>
    </DraftHistory.Provider>
  )
}

function Welcome({ wide, onHistory }: { wide?: boolean; onHistory?: () => void }) {
  const c = useChat()
  const q = useQuery({ queryKey: ['chatSuggestions'], queryFn: () => api.chatSuggestions<Suggestions>(), staleTime: 60_000 })
  const page = usePageSuggestions(!wide)
  const chipItems = c.chip && !c.tid ? chipSuggestions(c.chip) : []
  const items = (q.data?.items.length ? q.data.items : fallback()).filter((x) => !page.items.some((p) => p.label === x.label))   // asked once, under the page
  const groups = (q.data?.groups ?? []).filter((g) => items.some((x) => x.group === g.key))
  const [tab, setTab] = useState('suggested')
  const [more, setMore] = useState(false)
  const top = pickTop(items, wide ? 6 : 4)
  const row = (x: Suggestion) => <SuggestionRow key={x.id} s={x} wide={wide} onSend={() => c.send(x.prompt)} onEdit={() => { c.setInput(x.prompt); c.focus() }} />
  // the Assistant page is the panel made larger (Sam, 16 Nov 2026: "keep it consistent with the assistant"): the greeting in the
  // middle, the questions as quiet rows by the box, a pill switch between their groups instead of "more suggestions"
  if (wide) {
    const shown = tab === 'suggested' ? top : items.filter((x) => x.group === tab)
    return (
      <div className="flex flex-1 flex-col">
        <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
          <Logo size={44} />
          <h2 className="mt-3 text-[22px] font-semibold tracking-[-0.01em]">{greeting()}{hi()}</h2>
        </div>
        <div className="pb-1">
          {groups.length > 0
            ? <div className="mb-1.5 overflow-x-auto px-1.5 [scrollbar-width:none]"><Segmented label="Suggestions" value={tab} onChange={setTab} className="whitespace-nowrap"
                options={[['suggested', 'Suggested'] as const, ...groups.map((g) => [g.key, g.label] as const)]} /></div>
            : <div className="mb-1 px-2.5 text-[12.5px] text-ink3">Suggested</div>}
          <div className="min-h-[216px]">{shown.map(row)}</div>
        </div>
      </div>
    )
  }
  const rest = items.filter((x) => !top.includes(x))
  // the greeting sits quietly in the middle, the questions at the foot by the box. With a chip, only questions about it (Sam,
  // 16 Nov 2026: "a bit too much content"); × on the chip brings back the rest.
  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-1 flex-col items-center justify-center py-8 text-center">
        <Logo size={40} />
        <div className="mt-2.5 text-[17px] font-semibold tracking-[-0.01em]">{greeting()}{hi()}</div>
      </div>
      <div className="pb-1">
        {chipItems.length ? <>
          <div className="mb-0.5 px-2 text-[12px] text-ink3">Ask about {chipNoun(c.chip!)}</div>
          {chipItems.map(row)}
        </> : <>
          {page.items.length > 0 && <><div className="mb-0.5 px-2 text-[12px] text-ink3">On this page</div>{page.items.slice(0, 3).map(row)}</>}
          <div className={cn('mb-0.5 px-2 text-[12px] text-ink3', page.items.length > 0 && 'mt-3')}>Suggested</div>
          {top.map(row)}
          {more && groups.map((g) => { const xs = rest.filter((x) => x.group === g.key); return xs.length ? <div key={g.key}><div className="mb-0.5 mt-3 px-2 text-[12px] text-ink3">{g.label}</div>{xs.map(row)}</div> : null })}
          <div className="mt-2 flex items-center gap-3 px-2 text-[12px] text-ink3">
            {rest.length > 0 && !more && <button onClick={() => setMore(true)} className="hover:text-ink">{rest.length} more suggestions</button>}
            {c.threads.length > 0 && onHistory && <button onClick={onHistory} className="inline-flex items-center gap-1 hover:text-ink"><History size={12} aria-hidden />Earlier conversations</button>}
          </div>
        </>}
      </div>
    </div>
  )
}

// One suggestion: a quiet row (icon, question, why now), the background on hover; clicking asks it, the pencil puts it in the
// box to edit first. The full question shows on hover. wide: the Assistant page, a size up.
function SuggestionRow({ s, wide, onSend, onEdit }: { s: Suggestion; wide?: boolean; onSend: () => void; onEdit: () => void }) {
  return (
    <div className="group/s relative">
      <button onClick={onSend} title={s.prompt} className={cn('flex w-full items-center gap-2.5 rounded-xl pr-9 text-left transition-colors hover:bg-panel2', wide ? 'px-2.5 py-2' : 'px-2 py-[7px]')}>
        <SuggIcon name={s.icon} className="group-hover/s:text-ink" />
        <span className={cn('min-w-0 flex-1 truncate text-ink', wide ? 'text-[14px]' : 'text-[13px]')}>{s.label}</span>
        {s.hint && <span className={cn('max-w-[40%] shrink-0 truncate text-ink3', wide ? 'text-[12px]' : 'text-[11.5px]')}>{s.hint}</span>}
      </button>
      <button onClick={onEdit} title="Edit the question first" aria-label={`Edit first: ${s.label}`}
        className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-ink3 opacity-0 transition-opacity hover:bg-panel hover:text-ink focus:opacity-100 group-hover/s:opacity-100">
        <Pencil size={12} aria-hidden /></button>
    </div>
  )
}

// Sam's question: a soft, rounded bubble on the right (the tighter corner points at the speaker); copy and time on hover.
function Question({ m, size }: { m: Turn; size: string }) {
  const go = useChipOpen()
  return (
    <div className="group/q mb-5 flex flex-col items-end">
      {/* the thing it was asked about (components/AssistContext.tsx), like an attachment: who or what, and its line (a
          conversation's latest message); kept with the question, so a reopened conversation shows it too. Clicking it opens
          the thing; hovering it shows it as it is now (components/ContextChip.tsx) */}
      {m.ctx && <ChipHover ctx={m.ctx} asked mark={<ChipMark ctx={m.ctx} size={32} />} onOpen={go} className="mb-1.5 inline-flex max-w-[85%]">
        <button type="button" onClick={() => go(m.ctx?.href)} disabled={!m.ctx.href} aria-label={`${openLabel(m.ctx)}: ${m.ctx.label}`}
          className="page-chip group/chip inline-flex max-w-full items-center gap-2 rounded-2xl py-1.5 pl-1.5 pr-3 text-left transition-[filter] enabled:hover:brightness-[0.97] disabled:cursor-default">
          <ChipMark ctx={m.ctx} size={28} />
          <span className="min-w-0 leading-tight"><span className="block truncate text-[12.5px] font-medium text-ink">{m.ctx.label}</span>
            <span className="mt-0.5 block truncate text-[11.5px] text-ink2">{chipSub(m.ctx)}</span></span>
          {m.ctx.href && <ArrowUpRight size={14} className="shrink-0 text-ink3 opacity-0 transition-opacity group-hover/chip:opacity-100" aria-hidden />}
        </button>
      </ChipHover>}
      <div title={m.at ? hm(m.at) : undefined} className={cn('max-w-[85%] rounded-[20px] rounded-br-md bg-accentbg px-4 py-2.5 text-ink', size)}>
        <span className="sr-only">You: </span><div className="whitespace-pre-wrap break-words">{m.text}</div>
      </div>
      <div className="mt-1 flex h-5 items-center gap-1 pr-1 text-[11.5px] text-ink3">
        {m.page && !m.ctx && <span>on {m.page}</span>}
        <span className="flex items-center opacity-0 transition-opacity group-hover/q:opacity-100 focus-within:opacity-100"><CopyBtn text={m.text} /></span>
      </div>
    </div>
  )
}

// One answer: what it did (live while working, folded afterwards), the text, then copy, time and, after a failure, try again.
function Answer({ m, live, size, onRetry, onFollow, k, turn = -1 }: { m: Turn; live: boolean; size: string; onRetry?: () => void; onFollow?: (q: string) => void; k?: string; turn?: number }) {
  const c = useChat()
  const [steps, setSteps] = useState(false)
  const { body, follow, changes } = splitBlocks(m.text, live)
  const n = m.steps?.length ?? 0
  const stopped = m.error === 'Stopped.'
  return (
    <div className="group/a mb-7 flex gap-3">
      <Logo size={24} animate={live} className="mt-0.5 shrink-0" />
      <div className={cn('min-w-0 flex-1', size)}>
        <span className="sr-only">SleePO: </span>
        {live && !body && <div className="flex flex-col gap-1 pt-1 text-[12.5px] text-ink3">
          {(m.steps ?? []).map((s, j) => <span key={j} className="flex items-center gap-1.5"><span className={cn('size-1.5 rounded-full', j === n - 1 ? 'animate-pulse bg-ink' : 'bg-ink3')} />{s}</span>)}
          {!n && <span className="flex items-center gap-2"><Dots />Thinking</span>}
        </div>}
        {!live && n > 0 && <button onClick={() => setSteps(!steps)} className="mb-1 inline-flex items-center gap-1 text-[11.5px] text-ink3 hover:text-ink">
          <ChevronDown size={12} className={cn('transition-transform', !steps && '-rotate-90')} />{n} step{n > 1 ? 's' : ''}{m.secs != null ? ` · ${Math.round(m.secs)} s` : ''}</button>}
        {!live && steps && <div className="mb-1.5 flex flex-col gap-0.5 border-l border-line pl-2 text-[12px] text-ink3">{m.steps!.map((s, j) => <span key={j}>{s}</span>)}</div>}
        {body && <AnswerBody text={body} live={live} turn={turn} />}
        {(!!m.acts?.length || m.asks) && <DesktopRequests tid={c.tid} ids={m.acts} run={m.run} live={live} />}
        {live && body && <div className="mt-1.5 flex items-center gap-2 text-[12px] text-ink3"><Dots />Writing</div>}
        {m.error && <div className={cn('mt-1.5 text-[12.5px]', stopped ? 'text-ink3' : 'text-hot')}>{stopped ? 'Stopped before it finished.' : m.error}</div>}
        {!live && !!m.made?.length && <MadeFiles files={m.made} />}
        {!live && changes.length > 0 && (
          <div className="mt-3" aria-label="Proposed changes">
            <div className="mb-1.5 text-[12px] font-semibold text-ink">Proposed {changes.length === 1 ? 'change' : 'changes'} <span className="font-normal text-ink3">· nothing changes until you apply</span></div>
            <div className="flex flex-col gap-1.5">{changes.map((ch, j) => ch.type === 'decide' ? <DecideCard key={j} ch={ch} k={`${k}|${j}`} /> : <ChangeCard key={j} ch={ch} k={`${k}|${j}`} />)}</div>
          </div>)}
        {onFollow && follow.length > 0 && (
          <div className="mt-3 flex flex-col items-start gap-1.5" aria-label="Follow-up questions">
            {follow.map((f) => <button key={f} onClick={() => onFollow(f)}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-panel py-1 pl-2 pr-3 text-left text-[12.5px] text-ink transition-colors hover:border-ink hover:bg-panel2">
              <CornerDownRight size={13} className="shrink-0 text-ink3" aria-hidden /><span className="truncate">{f}</span></button>)}
          </div>)}
        {!live && (body || m.error) && (
          <div className={cn('mt-1.5 flex h-6 items-center gap-0.5 text-[11.5px] text-ink3 transition-opacity', !onRetry && 'opacity-0 group-hover/a:opacity-100 focus-within:opacity-100')}>
            {body && <CopyBtn text={body} label />}
            {onRetry && (m.error || !body) && <button onClick={onRetry} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-panel2 hover:text-ink"><RotateCcw size={12} aria-hidden />Try again</button>}
            {m.at && <span className="px-1.5">{hm(m.at)}</span>}
          </div>)}
      </div>
    </div>
  )
}

// An answer's text, with its blocks drawn as cards: each ```email block (assist/chat.py: every email the chat writes;
// ```email <id> replies to that email) as a draft card Sam edits, copies or opens in Outlook, with tracked changes
// (components/ChatEmail.tsx); a ```teams / ```slack <item id> block as his reply in that conversation
// (components/ChatTeamsDraft.tsx); a ```review <attachment id> block as SleePO's review of a shared file and an ```edits
// block as more changes to it, both as tracked changes he keeps or drops (components/ChatReview.tsx, Sam, 29 Oct 2026).
// a block may be empty (```message 12628 then ``` on the next line): the closing fence then follows the header directly
const BLOCK = /```(email|review|edits|teams|slack|message)[ \t]*([^\n]*)\n([\s\S]*?)(\n?```|$)/g
function AnswerBody({ text, live, turn = -1 }: { text: string; live: boolean; turn?: number }) {
  const c = useChat()
  const history = useContext(DraftHistory)
  const parts: ReactNode[] = []
  let last = 0, n = 0
  for (const m of text.matchAll(BLOCK)) {
    if (m.index! > last && text.slice(last, m.index).trim()) parts.push(<Markdown key={`t${last}`}>{text.slice(last, m.index)}</Markdown>)
    const [kind, head, raw, closed] = [m[1], m[2].trim(), m[3], !!m[4]]
    const id = Number(head.match(/^(\d+)/)?.[1]) || null
    if (kind === 'email') {
      const i = n++, mail = id, body = parseEmail(raw).body.trim()
      const earlier = turn < 0 ? [] : history.filter((x) => (x.turn < turn || (x.turn === turn && x.n < i)) && x.mail === mail && x.fields.body.trim() !== body).map((x) => x.fields)
      // the newest version of this email asks about its blanks at once; an older one on request (components/FillQuestions.tsx)
      const latest = turn < 0 || !history.some((x) => (x.turn > turn || (x.turn === turn && x.n > i)) && x.mail === mail)
      parts.push(<ChatEmail key={`e${m.index}`} k={`${turn}:${i}`} tid={c.tid} mail={mail} raw={raw} done={!live || closed} earlier={earlier}
        latest={latest} saved={c.edits[`${turn}:${i}`]} onSaved={c.setEdit} />)
    } else if (kind === 'teams' || kind === 'slack') {
      const i = n++
      const latest = turn < 0 || !c.turns.slice(turn + 1).some((t) => t.role !== 'user' && /```(teams|slack)\b/.test(t.text))
      parts.push(<ChatTeamsDraft key={`m${m.index}`} k={`${turn}:${i}`} tid={c.tid} app={kind} item={id} attach={Number(head.match(/attach=(\d+)/)?.[1]) || null}
        raw={raw} done={!live || closed} latest={latest} saved={c.edits[`${turn}:${i}`]} onSaved={c.setEdit} />)
    } else if (kind === 'review' && id) {
      parts.push(<ReviewCard key={`r${m.index}`} attId={id} focus={raw.trim()} live={live} onReply={(name, who, file) =>
        c.send(`Draft my reply to ${who} on the review of ${name}${file ? `, with the updated file (${file}) attached` : ''}.`)} />)
    } else if (kind === 'message' && id) {   // a message Sam opened here from Messages (assist/message_chat.py)
      parts.push(<MessageCard key={`g${m.index}`} item={id} />)
    } else if (kind === 'edits' && id) {
      parts.push(<ChatEdits key={`x${m.index}`} attId={id} raw={raw} done={!live || closed} />)
    }
    last = m.index! + m[0].length
  }
  if (!parts.length) return <Markdown>{text}</Markdown>
  if (text.slice(last).trim()) parts.push(<Markdown key={`t${last}`}>{text.slice(last)}</Markdown>)
  return <>{parts}</>
}

// Files the answer made in the conversation's folder (~/SleePO Workspace): open in their app, or show in Finder.
function MadeFiles({ files }: { files: Made[] }) {
  const c = useChat()
  const [err, setErr] = useState('')
  const open = async (name: string, reveal: boolean) => {
    if (!c.tid) return
    try { await api.chatFileOpen(c.tid, name, reveal); setErr('') } catch (e) { setErr(`Could not open ${name}: ${e instanceof Error ? e.message : e}`) }
  }
  return (
    <div className="mt-3 flex flex-col gap-1.5" aria-label="Files made">
      {files.map((f) => { const ext = f.name.split('.').pop()?.toLowerCase() ?? ''; const Icon = ['xlsx', 'csv', 'tsv'].includes(ext) ? FileSpreadsheet : ['docx', 'md', 'rtf', 'odt', 'html', 'txt'].includes(ext) ? FileText : FileIcon
        return (
          <div key={f.name} className="flex items-center gap-2.5 rounded-xl border border-line bg-panel px-3 py-2">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-panel2 text-ink"><Icon size={15} aria-hidden /></span>
            <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium text-ink">{f.name}</div>
              <div className="text-[11.5px] text-ink2">{f.size < 1024 ? `${f.size} bytes` : `${Math.round(f.size / 1024)} KB`} · in this conversation's folder</div></div>
            <button onClick={() => open(f.name, false)} className="rounded-full border border-line px-3 py-1 text-[12.5px] text-ink transition-colors hover:border-ink hover:bg-panel2">Open</button>
            <button onClick={() => open(f.name, true)} title="Show in Finder" aria-label={`Show ${f.name} in Finder`} className="grid size-7 place-items-center rounded-full text-ink2 hover:bg-panel2 hover:text-ink"><FolderOpen size={14} /></button>
          </div>) })}
      {err && <div className="text-[12px] text-hot">{err}</div>}
    </div>
  )
}

// Whether Sam applied or dismissed a proposed change, kept in this browser so a reopened conversation shows it.
const APPLIED = 'sleepo-chat-applied'
const readApplied = (): Record<string, 'applied' | 'dismissed'> => { try { return JSON.parse(localStorage.getItem(APPLIED) || '{}') } catch { return {} } }
const writeApplied = (k: string, v?: 'applied' | 'dismissed') => { try { const a = readApplied(); if (v) a[k] = v; else delete a[k]; localStorage.setItem(APPLIED, JSON.stringify(a)) } catch { /* private window */ } }
const VERB = { loop: { done: 'Close', dropped: 'Drop', snoozed: 'Snooze', open: 'Reopen' }, action: { done: 'Mark done', dismissed: 'Dismiss', snoozed: 'Snooze', open: 'Reopen' } } as Record<string, Record<string, string>>

// One proposed change. It shows the item's real title from SleePO (not the model's wording), so what Apply does is what Sam
// reads; an item that cannot be found cannot be applied. Nothing happens until Apply; Undo reopens a closed or snoozed item.
function ChangeCard({ ch, k }: { ch: Change; k: string }) {
  const qc = useQueryClient()
  const loops = useQuery({ queryKey: ['loops', 'chat'], queryFn: () => api.loopsRecent<{ items: { id: number; title: string; status: string }[] }>(60), enabled: ch.type === 'loop', staleTime: 30_000 })
  const todo = useQuery({ queryKey: ['todo'], queryFn: api.todo, enabled: ch.type === 'action', staleTime: 30_000 })
  const [state, setState] = useState<'applied' | 'dismissed' | undefined>(() => readApplied()[k])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const target = ch.type === 'loop' ? loops.data?.items.find((x) => x.id === Number(ch.id))?.title
    : ch.type === 'action' ? todo.data?.items.find((x) => x.id === String(ch.id))?.title : undefined
  const loading = (ch.type === 'loop' && loops.isLoading) || (ch.type === 'action' && todo.isLoading)
  const missing = ch.type !== 'refresh' && !loading && !target
  const verb = ch.type === 'refresh' ? { mail: 'Refresh mail', sync: 'Quick sync', full: 'Full refresh' }[ch.mode!] : VERB[ch.type][ch.status!]
  const until = ch.status === 'snoozed' && ch.snooze_until ? ` until ${ch.snooze_until}` : ''
  const Icon = ch.type === 'loop' ? ListChecks : ch.type === 'action' ? Target : RefreshCw
  const run = async (status?: string) => {
    setBusy(true); setErr('')
    try {
      if (ch.type === 'loop') await api.loopPatch(Number(ch.id), { status: status ?? ch.status!, snooze_until: status ? null : ch.snooze_until ?? null, note: status ? null : ch.note ?? null })
      else if (ch.type === 'action') await api.todoPatch(String(ch.id), { status: status ?? ch.status!, snooze_until: status ? null : ch.snooze_until ?? null })
      else await api.runRefresh(ch.mode as 'mail' | 'sync' | 'full')
      const next = status ? undefined : 'applied'
      writeApplied(k, next); setState(next)
      qc.invalidateQueries()
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const dismiss = () => { writeApplied(k, 'dismissed'); setState('dismissed') }
  return (
    <div className={cn('flex items-start gap-2.5 rounded-xl border bg-panel px-3 py-2.5', state === 'applied' ? 'border-accent' : 'border-line', state === 'dismissed' && 'opacity-60')}>
      <span className={cn('grid size-7 shrink-0 place-items-center rounded-lg', state === 'applied' ? 'bg-accent text-onaccent' : 'bg-panel2 text-ink')}>{state === 'applied' ? <Check size={14} /> : <Icon size={14} aria-hidden />}</span>
      <div className="min-w-0 flex-1 text-[13px] leading-snug">
        <div className="text-ink"><span className="font-semibold">{verb}{until}</span>{ch.type !== 'refresh' && <>{' · '}{loading ? '…' : target ?? <span className="text-hot">{ch.type === 'loop' ? 'open item' : 'action'} {String(ch.id)} not found</span>}</>}</div>
        {(ch.note || ch.label) && (ch.note || ch.label) !== verb && <div className="mt-0.5 text-[12px] text-ink2">{ch.note || ch.label}</div>}
        {err && <div className="mt-0.5 text-[12px] text-hot">{err}</div>}
      </div>
      {state === 'applied' ? (
        <div className="flex shrink-0 items-center gap-1 text-[12px]"><span className="text-ink">Applied</span>
          {ch.type !== 'refresh' && ch.status !== 'open' && <button onClick={() => run('open')} disabled={busy} title="Undo: reopen it" className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-ink2 hover:bg-panel2 hover:text-ink"><Undo2 size={12} aria-hidden />Undo</button>}</div>
      ) : state === 'dismissed' ? <button onClick={() => { writeApplied(k); setState(undefined) }} className="shrink-0 text-[12px] text-ink3 hover:text-ink">Dismissed</button>
        : (
        <div className="flex shrink-0 items-center gap-1">
          <button onClick={() => run()} disabled={busy || missing || loading} className="rounded-full bg-accent px-3 py-1 text-[12.5px] font-medium text-onaccent transition hover:brightness-95 disabled:bg-panel2 disabled:text-ink3">{busy ? 'Applying…' : 'Apply'}</button>
          <button onClick={dismiss} disabled={busy} className="rounded-full px-2 py-1 text-[12.5px] text-ink2 hover:bg-panel2 hover:text-ink">Dismiss</button>
        </div>)}
    </div>
  )
}

// A decision Sam took in a conversation started from an initiative's or topic's page (assist/initiative_work.py SEED): Apply
// records it as a decide step in Tasks, closed with his call (or open, to decide later), under the task the conversation
// named or a new "Decide: …" task. What the card shows is what is recorded; to change it, Sam asks the chat for a new card.
function DecideCard({ ch, k }: { ch: Change; k: string }) {
  const qc = useQueryClient()
  const tasks = useQuery({ queryKey: ['tasks'], queryFn: api.tasks, enabled: !!ch.task_id, staleTime: 30_000 })
  const [state, setState] = useState<'applied' | 'dismissed' | undefined>(() => readApplied()[k])
  const [done, setDone] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const subject = ch.subject!, topic = /^topic:(\d+)$/.exec(subject)
  const base = topic ? workBase({ topic: Number(topic[1]) }) : workBase({ slug: subject })
  const decided = ch.decided !== false
  const under = ch.task_id ? tasks.data?.tasks.find((t) => t.id === ch.task_id)?.title ?? `task ${ch.task_id}` : 'a new task'
  const apply = async () => {
    setBusy(true); setErr('')
    try {
      const r = await api.workDecideRecord(base, { question: ch.question!, choice: decided ? ch.choice ?? '' : '', note: decided ? ch.note ?? '' : '', task_id: ch.task_id ?? null, decided })
      writeApplied(k, 'applied'); setState('applied'); setDone(r.task_id)
      for (const q of [['tasks'], ['topic'], ['topics'], ['initiative'], ['portfolio']]) qc.invalidateQueries({ queryKey: q })
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <div className={cn('flex items-start gap-2.5 rounded-xl border bg-panel px-3 py-2.5', state === 'applied' ? 'border-accent' : 'border-line', state === 'dismissed' && 'opacity-60')}>
      <span className={cn('grid size-7 shrink-0 place-items-center rounded-lg', state === 'applied' ? 'bg-accent text-onaccent' : 'bg-panel2 text-ink')}>{state === 'applied' ? <Check size={14} /> : <Scale size={14} aria-hidden />}</span>
      <div className="min-w-0 flex-1 text-[13px] leading-snug">
        <div className="font-semibold text-ink">{decided ? 'Record the decision' : 'Keep it to decide later'}</div>
        <div className="mt-0.5 text-ink">{ch.question}</div>
        {decided && (ch.choice || ch.note) && <div className="mt-0.5 text-ink2"><span className="font-medium text-ink">Your call: </span>{[ch.choice, ch.note].filter(Boolean).join('. ')}</div>}
        <div className="mt-0.5 text-[12px] text-ink3">A decide step in Tasks, under {under}</div>
        {err && <div className="mt-0.5 text-[12px] text-hot">{err}</div>}
      </div>
      {state === 'applied' ? (
        <div className="flex shrink-0 items-center gap-1 text-[12px]"><span className="text-ink">Recorded</span>
          <a href={done ? `#/tasks?open=${done}` : '#/tasks'} className="rounded-full px-2 py-1 font-normal text-ink2 no-underline hover:bg-panel2 hover:text-ink">Open in Tasks</a></div>
      ) : state === 'dismissed' ? <button onClick={() => { writeApplied(k); setState(undefined) }} className="shrink-0 text-[12px] text-ink3 hover:text-ink">Dismissed</button>
        : (
        <div className="flex shrink-0 items-center gap-1">
          <button onClick={() => void apply()} disabled={busy} className="rounded-full bg-accent px-3 py-1 text-[12.5px] font-medium text-onaccent transition hover:brightness-95 disabled:bg-panel2 disabled:text-ink3">{busy ? 'Recording…' : 'Apply'}</button>
          <button onClick={() => { writeApplied(k, 'dismissed'); setState('dismissed') }} disabled={busy} className="rounded-full px-2 py-1 text-[12.5px] text-ink2 hover:bg-panel2 hover:text-ink">Dismiss</button>
        </div>)}
    </div>
  )
}

function CopyBtn({ text, label }: { text: string; label?: boolean }) {
  const [done, setDone] = useState(false)
  const copy = () => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500) }).catch(() => {})
  return <button onClick={copy} title="Copy" aria-label={done ? 'Copied' : 'Copy'} className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-panel2 hover:text-ink">
    {done ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}{label && (done ? 'Copied' : 'Copy')}</button>
}

const Dots = () => <span aria-hidden className="inline-flex items-center gap-[3px]">{[0, 1, 2].map((i) =>
  <span key={i} className="size-[5px] animate-bounce rounded-full bg-ink3" style={{ animationDelay: `${i * 0.15}s`, animationDuration: '1s' }} />)}</span>

// The message box: rounded, grows with the text, Enter sends; Sam can type the next question while an answer streams.
export function Composer({ wide, onSend }: { wide?: boolean; onSend?: () => void }) {
  const c = useChat()
  const send = () => { if (c.busy || !c.input.trim()) return; onSend?.(); c.send(c.input) }
  const waiting = c.turns.length === 1 && c.turns[0].role === 'assistant' && c.turns[0].text.startsWith('```message ')   // opened from Messages, nothing asked yet
  const chip = !c.tid ? c.chip : null
  useLayoutEffect(() => {
    const el = c.box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, wide ? 288 : 160)}px`
  }, [c.input, wide, c.box])
  return (
    <form onSubmit={(e) => { e.preventDefault(); send() }}>
      {c.notice && <div className="mb-2 flex items-center gap-1.5 text-[12px] text-ink2"><ClaudeMark size={14} />{c.notice}</div>}
      {c.tid && !c.busy && c.turns.length > 0 && !c.notice && (
        <button type="button" onClick={c.handoff} title="Opens this conversation and its sources in Claude Desktop; text in the box becomes the request"
          className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-line bg-panel py-1 pl-1.5 pr-2.5 text-[12px] text-ink2 transition-colors hover:border-ink hover:text-ink">
          <ClaudeMark size={16} />Continue in Claude Desktop{c.input.trim() ? ' with this request' : ''}</button>)}
      <div className={cn('border border-line bg-panel shadow-[0_2px_10px_-6px_rgba(0,0,0,0.18)] transition-colors focus-within:border-ink', wide ? 'rounded-[22px]' : 'rounded-[18px]')}>
        {chip && <div className={wide ? 'px-2.5 pt-2.5' : 'px-2 pt-2'}><PageChip ctx={chip} onRemove={c.dropChip} /></div>}
        <div className={cn('flex items-end gap-2', wide ? 'py-2 pl-4 pr-2' : 'py-1.5 pl-3.5 pr-1.5')}>
          <textarea ref={c.box} value={c.input} onChange={(e) => c.setInput(e.target.value)} rows={1}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
            placeholder={c.hint || (waiting ? 'What should SleePO do with this message?' : chip ? `Ask about ${chipNoun(chip)}…` : c.turns.length ? 'Ask a follow-up…' : 'Ask SleePO…')} aria-label="Message"
            className={cn('flex-1 resize-none overflow-y-auto bg-transparent leading-snug text-ink outline-none placeholder:text-ink3', wide ? 'py-1.5 text-[15px]' : 'py-1 text-[13.5px]')} />
          <DictateButton target={c.box} className={wide ? 'size-8' : undefined} />
          {c.busy
            ? <button type="button" onClick={c.stop} title="Stop" aria-label="Stop" className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-bg hover:opacity-85"><Square size={11} fill="currentColor" /></button>
            : <button type="submit" disabled={!c.input.trim()} title="Send (Enter)" aria-label="Send" className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-onaccent transition-opacity hover:brightness-95 disabled:bg-panel2 disabled:text-ink3"><ArrowUp size={16} strokeWidth={2.5} /></button>}
        </div>
      </div>
    </form>
  )
}

const CHIP_ICON: Record<string, LucideIcon> = { message: MessagesSquare, email: Mail, initiative: Target, topic: Hash, task: CircleCheck,
  person: UserRound, meeting: CalendarDays, event: CalendarDays }
const APP_NAME: Record<string, string> = { teams: 'Teams', slack: 'Slack' }
// the chip's second line: what kind of thing it is
function chipSub(ctx: PageCtx) {
  if (ctx.sub) return ctx.sub   // the server's line for it (assist/page_context.py chip): a conversation's latest message, an email's sender
  const when = ctx.date ? ` · ${day(ctx.date)}` : ''
  switch (ctx.kind) {
    case 'message': return `${APP_NAME[ctx.app ?? ''] ?? 'Chat'} conversation`
    case 'email': return ctx.draft ? 'Email · with your draft' : 'Email thread'
    case 'person': return ctx.detail || 'Person'
    case 'meeting': case 'event': return `Meeting${when}`
    default: return ({ initiative: 'Initiative', topic: 'Topic', task: 'Task' } as Record<string, string>)[ctx.kind] ?? 'Page'
  }
}
// The chip's picture: the person's face with the app's logo on its corner (a conversation, an email, a person), the app's
// logo for a channel, the day on a little calendar for a meeting, otherwise a round mark (an initiative in volt).
function ChipMark({ ctx, size = 22 }: { ctx: PageCtx; size?: number }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 300_000 })
  const logo = ctx.app ? meta.data?.logos?.[ctx.app] : undefined
  const box = { width: size, height: size }
  if (ctx.who) {
    const b = Math.max(10, Math.round(size * 0.5))
    return (
      <span className="relative shrink-0" style={box}>
        <Avatar p={{ name: ctx.who, avatar: ctx.avatar ?? '' }} size={size} />
        {logo && <img src={logo} alt="" className="absolute -bottom-[3px] -right-[4px] rounded-[4px] bg-panel p-[1.5px] shadow-[0_0_0_1px_var(--line)]" style={{ width: b, height: b }} />}
      </span>)
  }
  if (logo) return <span className="grid shrink-0 place-items-center rounded-full border border-line bg-panel" style={box}><img src={logo} alt="" style={{ width: size * 0.58, height: size * 0.58 }} /></span>
  if ((ctx.kind === 'meeting' || ctx.kind === 'event') && ctx.date) {
    const d = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', timeZone: TZ }).format(parse(ctx.date))
    return (
      <span className="flex shrink-0 flex-col overflow-hidden rounded-[5px] border border-line bg-panel" style={box}>
        <span className="h-[28%] bg-hot" /><span className="grid flex-1 place-items-center font-semibold leading-none text-ink" style={{ fontSize: size * 0.42 }}>{d}</span>
      </span>)
  }
  const Icon = CHIP_ICON[ctx.kind] ?? FileText
  return <span className={cn('grid shrink-0 place-items-center rounded-full', ctx.kind === 'initiative' ? 'bg-accent text-onaccent' : 'bg-ink text-bg')} style={box}>
    <Icon size={Math.round(size * 0.55)} strokeWidth={2} aria-hidden /></span>
}
// A chip opens the thing it names (Sam, 17 Nov 2026: "click on them and go back to the context"). From the Assistant page the
// conversation moves to the panel, so it stays beside the page it opened.
function useChipOpen() {
  const c = useChat()
  const navigate = useNavigate()
  return (href?: string) => {
    if (!href) return
    if (c.full) c.setOpen(true)
    if (herePath() !== href) void navigate({ href })
  }
}
// What the new chat holds, inside the message box like an attachment: the thing open on the page, read in full with the first
// question (assist/page_context.py). Clicking it opens the thing, hovering it shows it (components/ContextChip.tsx); × removes
// it: a normal chat.
function PageChip({ ctx, onRemove }: { ctx: PageCtx; onRemove: () => void }) {
  const go = useChipOpen()
  return (
    <ChipHover ctx={ctx} mark={<ChipMark ctx={ctx} size={32} />} onOpen={go}
      className="page-chip inline-flex max-w-full items-center gap-1 rounded-full py-[3px] pl-[3px] pr-1 text-[12.5px]">
      <button type="button" onClick={() => go(ctx.href)} aria-label={`${openLabel(ctx)}: ${ctx.label}`}
        className="flex min-w-0 items-center gap-2 rounded-full pr-1 text-left">
        <ChipMark ctx={ctx} size={20} />
        <span className="min-w-0 truncate"><span className="font-medium text-ink">{ctx.label}</span><span className="text-ink3"> · {chipSub(ctx)}</span></span>
      </button>
      <button type="button" onClick={onRemove} aria-label="Remove this context" title="Remove: a normal chat"
        className="grid size-5 shrink-0 place-items-center rounded-full text-ink3 hover:bg-ink/10 hover:text-ink"><X size={12} strokeWidth={2.25} /></button>
    </ChipHover>
  )
}

// Hovering the floating badge: what is on screen and two or three questions about it, asked in a new chat with one click; with
// nothing open, questions about the page or the day. "Ask something else" opens the chat as clicking the badge does.
function QuickMenu({ onHover, onDone }: { onHover: (on: boolean) => void; onDone: () => void }) {
  const c = useChat()
  const path = herePath()
  const route = useRouterState({ select: (s) => s.location.pathname })
  const ctxQ = useQuery({ queryKey: ['pageContext', path], queryFn: () => api.chatPageContext(path), staleTime: 30_000 })
  const sugg = useQuery({ queryKey: ['chatSuggestions'], queryFn: () => api.chatSuggestions<Suggestions>(), staleTime: 60_000 })
  const ctx = ctxQ.data?.context ?? null
  const items = useMemo(() => {
    if (ctx) return chipSuggestions(ctx)
    const page = pageSuggestions(route, document.querySelector('main h1')?.textContent?.trim() || '').slice(0, 3)
    return page.length ? page : pickTop(sugg.data?.items.length ? sugg.data.items : fallback(), 3)
  }, [ctx, route, sugg.data])
  const go = (f: () => void) => { onDone(); f() }
  return (
    <div role="menu" aria-label="Quick questions" onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}
      className={cn(popoverClass, 'quick-menu fixed bottom-[84px] right-5 z-50 w-[320px] rounded-2xl shadow-[0_18px_44px_-16px_rgba(0,0,0,0.35)]')}>
      {ctxQ.isLoading ? <div className="flex items-center gap-2 px-4 py-3.5 text-[12.5px] text-ink3"><Dots /></div> : <>
        {ctx
          ? <div className="flex items-center gap-2.5 px-3.5 pb-2 pt-3">
              <ChipMark ctx={ctx} size={28} />
              <div className="min-w-0 leading-tight"><div className="truncate text-[13px] font-medium text-ink">{ctx.label}</div><div className="mt-0.5 truncate text-[11.5px] text-ink3">{chipSub(ctx)}</div></div>
            </div>
          : <div className="px-4 pb-1 pt-3 text-[11.5px] font-medium text-ink3">Quick questions</div>}
        <div className="px-1.5 pb-1.5">{items.map((x) => {
          return <button key={x.id} role="menuitem" onClick={() => go(() => c.ask(x.prompt, ctx))} title={x.prompt}
            className="group/q flex w-full items-center gap-2.5 rounded-xl px-2.5 py-[7px] text-left text-[13px] text-ink transition-colors hover:bg-panel2">
            <SuggIcon name={x.icon} className="group-hover/q:text-ink" />
            <span className="min-w-0 flex-1 truncate">{x.label}</span>
            <ArrowUp size={14} className="shrink-0 rotate-45 text-ink3 opacity-0 transition-opacity group-hover/q:opacity-100" aria-hidden />
          </button>
        })}</div>
        <button role="menuitem" onClick={() => go(c.startHere)}
          className="flex w-full items-center gap-2 border-t border-line2 px-4 py-2.5 text-left text-[12.5px] text-ink2 transition-colors hover:bg-panel2 hover:text-ink">
          <span className="flex-1">Ask something else…</span><kbd className="font-sans text-[11px] text-ink3">⌘J</kbd></button>
      </>}
    </div>
  )
}

export function IconBtn({ title, onClick, children, on, disabled }: { title: string; onClick: () => void; children: React.ReactNode; on?: boolean; disabled?: boolean }) {
  return <button type="button" onClick={onClick} title={title} aria-label={title} disabled={disabled}
    className={cn('inline-flex size-7 shrink-0 items-center justify-center rounded-full text-ink2 hover:bg-panel2 hover:text-ink disabled:opacity-40', on && 'bg-panel2 text-ink')}>{children}</button>
}
