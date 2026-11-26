// First-run setup, led by SleePO's onboarding agent (Sam, 16 Nov 2026: "use Claude as an onboarding agent ... connect their
// email and all their sources first and then it would scan over all the data and infer what their role is, what their
// priorities are, what their title is ... ask them a few questions ... do the onboarding for them rather than ask them for
// their own inputs"). A page of its own, without the sidebar:
//   Welcome   what is about to happen
//   Connect   the sources, each with its own way to connect (Claude Code, Mail and Calendar, Granola, FluidVoice, Claude's connectors,
//             the company file); SleePO says what it can already see
//   Read      the agent at work (assist/onboard_agent.py, its own process on the server): the import, Teams and Slack when
//             chosen, what it found as it reads, then the run that works out the role, team and priorities
//   Review    what it found, its questions (asked the way FillQuestions asks), every field editable; nothing is saved before
//             "Looks right": the profile, the company, the bets, and About me and the voice page while they are templates
//   Done      the server restarts so every prompt reads the new profile
// It opens by itself while SleePO does not know who the user is and setup was never finished or skipped (main.tsx Root);
// Account › Run setup again opens it later. The step is in the address (?step=read): a reload or Back stays put, and the
// agent keeps running whatever the page does.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ArrowLeft, ArrowRight, Check, ChevronLeft, ExternalLink, FolderSearch, KeyRound, ListChecks, Loader2, Plug, Plus, RotateCw, ScanSearch,
  Settings2, Upload, X } from 'lucide-react'
import { api, type Conf, type Onboard, type OnboardBet, type OnboardPerson, type OnboardQuestion, type ScanState, type SetupCheck, type SetupState } from '@/lib/api'
import { cn } from '@/lib/util'
import { Logo } from '@/components/Logo'
import { DictateButton } from '@/components/Dictate'
import { Avatar, Button, btnClass, inputClass, Segmented } from '@/components/ui'
import granolaIcon from '@/assets/apps/granola.png'
import fluidvoiceIcon from '@/assets/apps/fluidvoice.png'

// The two apps SleePO is built around (Sam, 25 Nov 2026: "almost critical alongside SleePO"): each app's own icon, from its bundle
const APPS: Record<string, { name: string; icon: string; url: string }> = {
  granola: { name: 'Granola', icon: granolaIcon, url: 'https://granola.ai' },
  fluidvoice: { name: 'FluidVoice', icon: fluidvoiceIcon, url: 'https://github.com/altic-dev/FluidVoice' },
}
const AppIcon = ({ id, size = 18, className }: { id: string; size?: number; className?: string }) =>
  <img src={APPS[id].icon} alt="" width={size} height={size} draggable={false} className={cn('inline-block shrink-0', className)} style={{ width: size, height: size }} />
const AppName = ({ id }: { id: string }) => (
  <a href={APPS[id].url} target="_blank" rel="noopener" className="whitespace-nowrap font-medium text-ink no-underline hover:underline">
    <AppIcon id={id} size={16} className="mr-1 align-[-3px]" />{APPS[id].name}</a>)

export const STEPS = ['welcome', 'connect', 'read', 'review', 'done'] as const
export type Step = typeof STEPS[number]
const LABEL: Record<Step, string> = { welcome: 'Welcome', connect: 'Connect', read: 'Read', review: 'Review', done: 'Done' }
const quiet = 'w-full min-w-0 rounded-full border border-transparent bg-transparent px-3 py-1 text-[14px] text-ink outline-none transition-colors placeholder:text-ink3 hover:border-line focus:border-ink focus:bg-panel'
const zones = (() => { try { return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone') } catch { return [] } })()

export function SetupPage({ step = 'welcome' }: { step?: Step }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['setup'], queryFn: api.setup, staleTime: 0 })
  const scan = useQuery({ queryKey: ['setupScan'], queryFn: api.setupScan, staleTime: 0, refetchInterval: (x) => (x.state.data?.running ? 1500 : false) })
  const go = (s: Step) => nav({ to: '/welcome', search: { step: s } })
  const i = STEPS.indexOf(step)
  const skip = async () => {   // never opens by itself again; Account › Run setup again brings it back
    await api.setupFinish(false).catch(() => {})
    qc.setQueryData(['meta'], (m: object | undefined) => m && { ...m, setup: { needed: false, done: true } })
    nav({ to: '/' })
  }
  const s = q.data, sc = scan.data
  // opened at Welcome while a run is under way or waiting for review (the window was closed half-way): straight back to it
  const resumed = useRef(false)
  useEffect(() => {
    if (resumed.current || !sc) return
    resumed.current = true
    if (step === 'welcome' && sc.stage && !sc.applied) go(sc.stage === 'review' ? 'review' : 'read')
  }, [sc]) // eslint-disable-line react-hooks/exhaustive-deps
  const reached = (k: Step) => k === 'connect' || (k === 'read' && !!sc?.stage) || (k === 'review' && !!sc?.result)
  return (
    <div className="min-h-dvh bg-bg text-ink">
      <header className="mx-auto flex h-14 max-w-[1040px] items-center gap-3 px-5">
        <Logo size={26} /><span className="text-[15px] font-semibold tracking-[-0.01em]">SleePO</span>
        {s?.demo && <DemoTag />}
        <span className="flex-1" />
        {step !== 'done' && <button onClick={skip} className="text-[12.5px] text-ink3 hover:text-ink">Skip setup</button>}
      </header>
      <div className={cn('mx-auto px-5 pb-16 pt-4', step === 'review' ? 'max-w-[760px]' : 'max-w-[680px]')}>
        {step !== 'welcome' && <Stepper at={i} onGo={(k) => k !== step && STEPS.indexOf(k) < i && reached(k) && go(k)} />}
        {!s ? <div className="grid h-64 place-items-center"><Loader2 className="animate-spin text-ink3" /></div>
          : step === 'welcome' ? <Welcome demo={s.demo} onStart={() => go('connect')} />
          : step === 'connect' ? <Connect s={s} scan={sc} onBack={() => go('welcome')} onRead={() => go('read')} />
          : step === 'read' ? <Read scan={sc} onBack={() => go('connect')} onReview={() => go('review')} />
          : step === 'review' ? <Review s={s} scan={sc} onRead={() => go('read')} onConnect={() => go('connect')} onDone={() => go('done')} />
          : <Done s={s} />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- frame
function Stepper({ at, onGo }: { at: number; onGo: (s: Step) => void }) {
  const shown = STEPS.slice(1)
  return (
    <ol aria-label="Setup steps" className="mb-6 flex items-center gap-1.5">
      {shown.map((k, n) => {
        const idx = n + 1, done = idx < at, cur = idx === at
        return (
          <li key={k} className="flex min-w-0 flex-1 flex-col gap-1.5">
            <button onClick={() => onGo(k)} disabled={!done} aria-current={cur ? 'step' : undefined}
              className={cn('h-1 rounded-full transition-colors', done ? 'bg-ink hover:bg-ink2' : cur ? 'bg-accent' : 'bg-line')} aria-label={LABEL[k]} />
            <span className={cn('hidden truncate text-[11.5px] sm:block', cur ? 'font-medium text-ink' : 'text-ink3')}>{LABEL[k]}</span>
          </li>)
      })}
    </ol>
  )
}

function Card({ title, lead, children, foot, className }: { title?: string; lead?: ReactNode; children?: ReactNode; foot?: ReactNode; className?: string }) {
  return (
    <section className={cn('border border-line bg-panel', className)}>
      <div className="px-7 pb-6 pt-7 max-sm:px-5">
        {title && <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.02em]">{title}</h1>}
        {lead && <p className="mt-1.5 text-[14px] leading-relaxed text-ink2">{lead}</p>}
        {children && <div className={title || lead ? 'mt-5' : ''}>{children}</div>}
      </div>
      {foot && <div className="flex flex-wrap items-center gap-2 border-t border-line2 px-7 py-4 max-sm:px-5">{foot}</div>}
    </section>
  )
}

const Foot = ({ onBack, next, nextLabel = 'Continue', busy, disabled, extra }: { onBack?: () => void; next: () => void; nextLabel?: string; busy?: boolean; disabled?: boolean; extra?: ReactNode }) => <>
  {onBack && <Button onClick={onBack} size="md"><ArrowLeft size={14} /> Back</Button>}
  <span className="flex-1" />
  {extra}
  <Button variant="primary" size="md" onClick={next} disabled={busy || disabled}>{busy ? <Loader2 size={14} className="animate-spin" /> : null}{nextLabel}{!busy && <ArrowRight size={14} />}</Button>
</>

const Err = ({ children }: { children?: ReactNode }) => children ? <p role="alert" className="mt-3 text-[12.5px] text-hot">{children}</p> : null

// SleePO speaking: its mark, then what it says (as its answers in Ask SleePO are drawn)
function Says({ children, live, className }: { children: ReactNode; live?: boolean; className?: string }) {
  return (
    <div className={cn('flex items-start gap-3', className)}>
      <Logo size={30} animate={live} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 pt-[3px] text-[15px] leading-relaxed text-ink">{children}</div>
    </div>
  )
}

function DemoTag() {
  return <a href="#/account" title="A separate copy for trying setup as a new user: your real SleePO, its data and settings are untouched"
    className="ml-1 rounded-full border border-accent bg-accent/15 px-2.5 py-0.5 text-[11.5px] font-medium text-ink no-underline hover:bg-accent">Demo copy</a>
}

// ---------------------------------------------------------------- Welcome
function Welcome({ demo, onStart }: { demo: boolean; onStart: () => void }) {
  const steps: [typeof Plug, string, string][] = [
    [Plug, 'You connect', 'Your mail, calendar, meeting notes and chat. Read only.'],
    [ScanSearch, 'I read and learn', 'Your role, your team and what you are working towards, from the last few weeks.'],
    [ListChecks, 'You check', 'A couple of questions, then you confirm. Nothing is saved before that.']]
  return (
    <div className="pt-[5vh] text-center">
      <Logo size={72} className="mx-auto" />
      <h1 className="mt-5 text-[32px] font-semibold leading-tight tracking-[-0.02em]">Hi, I'm SleePO</h1>
      <p className="mx-auto mt-2 max-w-[500px] text-[15px] leading-relaxed text-ink2">Your chief of staff on this Mac. No forms to fill in: connect your sources and I'll set myself up, then check what I found with you.</p>
      <ol className="mx-auto mt-8 grid max-w-[640px] gap-3 text-left sm:grid-cols-3">
        {steps.map(([Icon, t, d], n) => (
          <li key={t} className="border border-line bg-panel p-4">
            <div className="flex items-center gap-2">
              <span className="grid size-6 place-items-center rounded-full bg-ink text-[11.5px] font-semibold text-bg">{n + 1}</span>
              <Icon size={16} strokeWidth={1.75} className="text-ink3" aria-hidden />
            </div>
            <div className="mt-2.5 text-[13.5px] font-semibold">{t}</div>
            <div className="mt-0.5 text-[12.5px] leading-snug text-ink2">{d}</div>
          </li>))}
      </ol>
      <p className="mx-auto mt-6 max-w-[560px] text-[13.5px] leading-relaxed text-ink2">
        I work best with <AppName id="granola" /> for your meeting notes and <AppName id="fluidvoice" /> so you can talk to me
        instead of typing. If you don't have them yet, install them now: we'll connect them in the next step.</p>
      <Button variant="primary" size="md" onClick={onStart} className="mt-7 px-5 py-2 text-[14px]">Let's start <ArrowRight size={15} /></Button>
      <p className="mt-4 text-[12.5px] text-ink3">About five minutes. Everything stays on this Mac, and SleePO never sends anything.</p>
      {demo && <p className="mt-1 text-[12.5px] text-ink3">This is the demo copy: what you set up here stays in it. Reset it from Account.</p>}
    </div>
  )
}

// ---------------------------------------------------------------- Connect
function Connect({ s, scan, onBack, onRead }: { s: SetupState; scan?: ScanState; onBack: () => void; onRead: () => void }) {
  const qc = useQueryClient()
  const [chat, setChat] = useState(!!scan?.chat)
  const [checking, setChecking] = useState(false)
  const recheck = async () => { setChecking(true); await qc.invalidateQueries({ queryKey: ['setup'] }); setChecking(false) }
  const ok = (id: string) => s.checks.find((c) => c.id === id)?.status === 'ok'
  const claude = ok('claude'), something = ok('disk') || ok('granola') || chat
  const me = s.profile.emails[0] || s.suggest.emails?.[0]
  const start = useMutation({ mutationFn: () => api.setupScanStart(chat), onSuccess: (d) => { qc.setQueryData(['setupScan'], d); onRead() } })
  const running = !!scan?.running
  return <>
    <Says className="mb-5">
      {me ? <>I can already see your calendar: you're <span className="font-semibold">{me}</span>. Connect everything else you use, and I'll read it all.</>
        : <>First, connect what you'd like me to read. The more I can see, the less I'll need to ask you.</>}
    </Says>
    <Card title="Connect your sources" lead="Everything is read only and stays on this Mac. Connect what you use; the rest can be added later."
      foot={<Foot onBack={onBack} next={() => (running ? onRead() : start.mutate())} nextLabel={running ? 'Back to reading' : 'Start reading'} busy={start.isPending}
        disabled={!running && (!claude || !something)}
        extra={<Button onClick={recheck} size="md" disabled={checking}><RotateCw size={14} className={checking ? 'animate-spin' : ''} /> Check again</Button>} />}>
      <ul className="divide-y divide-line2 border-y border-line2">
        {s.checks.map((c) => <CheckRow key={c.id} c={c} onChanged={recheck} chat={chat} setChat={setChat} />)}
        <CompanyRow s={s} />
      </ul>
      {!claude ? <p className="mt-4 text-[12.5px] text-ink2">I think with Claude Code on this Mac: install it and sign in, then press Check again.</p>
        : !something ? <p className="mt-4 text-[12.5px] text-ink2">Connect your mail and calendar, Granola, or Teams and Slack, so I have something to read.</p> : null}
      <Err>{start.error?.message}</Err>
    </Card>
  </>
}

const MARK: Record<SetupCheck['status'], ReactNode> = {
  ok: <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent text-onaccent"><Check size={15} strokeWidth={2.5} /></span>,
  todo: <span className="size-7 shrink-0 rounded-full border-2 border-ink" />,
  optional: <span className="size-7 shrink-0 rounded-full border-2 border-dashed border-ink3" />,
}

function CheckRow({ c, onChanged, chat, setChat }: { c: SetupCheck; onChanged: () => void; chat: boolean; setChat: (on: boolean) => void }) {
  const [key, setKey] = useState('')
  const granola = useMutation({ mutationFn: () => api.setupGranola(key), onSuccess: () => { setKey(''); onChanged() } })
  const open = (what: 'disk' | 'python') => api.setupOpen(what).catch(() => {})
  const connectors = c.id === 'connectors'
  const status = connectors && chat ? 'ok' : c.status
  const app = APPS[c.id], tryBox = useRef<HTMLInputElement>(null)
  return (
    <li className="flex gap-3.5 py-4">
      {MARK[status]}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {app && <AppIcon id={c.id} size={20} />}
          <span className="text-[14px] font-semibold">{c.title}</span>
          <span className={cn('text-[12px]', status === 'ok' ? 'text-ink2' : c.required ? 'font-medium text-hot' : c.recommended ? 'font-medium text-ink' : 'text-ink3')}>
            {status === 'ok' ? (connectors ? 'Will be read' : c.id === 'fluidvoice' ? 'Ready' : 'Connected') : c.required ? 'Needed' : c.recommended ? 'Recommended' : 'Optional'}</span></div>
        <p className="mt-0.5 text-[13px] leading-snug text-ink2">{c.why}</p>
        {c.status !== 'ok' && !connectors && <p className="mt-1 text-[12.5px] text-ink3">{c.detail}</p>}
        {c.status !== 'ok' && app && c.app === false && (
          <div className="mt-2.5 flex flex-wrap gap-2"><a href={app.url} target="_blank" rel="noopener" className={btnClass('outline')}>Get {app.name} <ExternalLink size={12} /></a></div>)}
        {c.status !== 'ok' && c.id === 'fluidvoice' && c.app && (
          <div className="mt-2.5 flex max-w-[460px] items-center gap-1 rounded-full border border-line bg-panel pl-3 pr-1">
            <input ref={tryBox} placeholder="Try it: click the microphone and say something" aria-label="Try dictation"
              className="min-w-0 flex-1 bg-transparent py-1.5 text-[13px] outline-none placeholder:text-ink3" />
            <DictateButton target={tryBox} />
          </div>)}
        {c.status !== 'ok' && c.id === 'claude' && (
          <div className="mt-2.5 flex flex-wrap gap-2"><a href="https://claude.com/claude-code" target="_blank" rel="noopener" className={btnClass('outline')}>Get Claude Code <ExternalLink size={12} /></a></div>)}
        {c.status !== 'ok' && c.id === 'disk' && (
          <ol className="mt-2.5 space-y-2 text-[12.5px] text-ink2">
            <li className="flex flex-wrap items-center gap-2"><span className="w-4 text-ink3">1.</span><Button variant="outline" onClick={() => open('disk')}><Settings2 size={13} /> Open Full Disk Access</Button></li>
            <li className="flex flex-wrap items-center gap-2"><span className="w-4 text-ink3">2.</span><Button variant="outline" onClick={() => open('python')}><FolderSearch size={13} /> Show Python in Finder</Button><span>then drag it into the list and switch it on</span></li>
            <li className="flex items-center gap-2"><span className="w-4 text-ink3">3.</span><span>Come back and press Check again</span></li>
          </ol>)}
        {c.status !== 'ok' && c.id === 'granola' && (
          <form onSubmit={(e) => { e.preventDefault(); if (key.trim()) granola.mutate() }} className="mt-2.5 flex max-w-[460px] gap-2">
            <span className="relative flex-1"><KeyRound size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink3" aria-hidden />
              <input value={key} onChange={(e) => setKey(e.target.value)} type="password" autoComplete="off" placeholder="Granola API key" aria-label="Granola API key" className={cn(inputClass, 'w-full py-1.5 pl-8')} /></span>
            <Button type="submit" variant="outline" disabled={!key.trim() || granola.isPending}>{granola.isPending ? <Loader2 size={13} className="animate-spin" /> : null}Connect</Button>
          </form>)}
        {c.status !== 'ok' && c.id === 'granola' && <Err>{granola.error?.message}</Err>}
        {connectors && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {c.url && <a href={c.url} target="_blank" rel="noopener" className={btnClass('outline')}>Open Claude's connectors <ExternalLink size={12} /></a>}
            <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] text-ink2">
              <input type="checkbox" checked={chat} onChange={(e) => setChat(e.target.checked)} className="size-4 accent-[var(--ink)]" />
              They're connected: read Teams and Slack too <span className="text-ink3">(2 to 3 minutes more)</span></label>
          </div>)}
      </div>
    </li>
  )
}

function CompanyRow({ s }: { s: SetupState }) {
  const qc = useQueryClient()
  const file = useRef<HTMLInputElement>(null)
  const pack = useMutation({
    mutationFn: async (f: File) => { let d: unknown; try { d = JSON.parse(await f.text()) } catch { throw new Error('That file is not a SleePO company file (JSON).') } return api.setupPack(d) },
    onSuccess: (d) => qc.setQueryData(['setup'], d),
  })
  const has = s.org.pack
  return (
    <li className="flex gap-3.5 py-4">
      {MARK[has ? 'ok' : 'optional']}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2"><span className="text-[14px] font-semibold">Your company's SleePO file</span>
          <span className={cn('text-[12px]', has ? 'text-ink2' : 'text-ink3')}>{has ? 'Installed' : 'Optional'}</span></div>
        <p className="mt-0.5 text-[13px] leading-snug text-ink2">{has
          ? <>{s.org.name}: {s.org.domains.join(', ')}{(s.org.crm || s.org.jira || s.org.roadmap) && <>, with {[s.org.crm && 'the CRM', s.org.jira && 'Jira', s.org.roadmap && 'the roadmap'].filter(Boolean).join(', ')}</>}.</>
          : 'If a colleague already uses SleePO, their company file gives me your org chart, your tools and what counts as internal mail.'}</p>
        <div className="mt-2.5">
          <Button variant="outline" onClick={() => file.current?.click()} disabled={pack.isPending}>
            {pack.isPending ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}{has ? 'Replace…' : 'Add the file…'}</Button>
          <input ref={file} type="file" accept="application/json,.json" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) pack.mutate(f); e.target.value = '' }} />
        </div>
        <Err>{pack.error?.message}</Err>
      </div>
    </li>
  )
}

// ---------------------------------------------------------------- Read: the agent at work
const STAGES = ['import', 'chat', 'read', 'think', 'review'] as const
const PHASE_NAME: Record<string, string> = { Calendar: 'Your calendar', 'Granola meetings': 'Meeting notes from Granola', 'Local files': 'Files on this Mac',
  'Mail sync': 'Your mail', Documents: 'Documents', 'Open items': 'What you owe and wait for' }
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

function Read({ scan, onBack, onReview }: { scan?: ScanState; onBack: () => void; onReview: () => void }) {
  const qc = useQueryClient()
  const stage = scan?.stage ?? null
  const failed = stage === 'failed'
  const at = STAGES.indexOf((failed ? scan?.failed_at : stage) as typeof STAGES[number])
  const restart = useMutation({ mutationFn: () => api.setupScanStart(!!scan?.chat), onSuccess: (d) => qc.setQueryData(['setupScan'], d) })
  // seen running here: moving on to the review when it ends is this page's to do (not when it opens on an old result)
  const saw = useRef(false)
  useEffect(() => {
    if (scan?.running) saw.current = true
    if (saw.current && stage === 'review') { const t = setTimeout(onReview, 1400); return () => clearTimeout(t) }
  }, [scan?.running, stage]) // eslint-disable-line react-hooks/exhaustive-deps
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { if (stage !== 'think') return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [stage])
  if (!stage) return (
    <Card title="Nothing read yet" lead="Connect your sources first, then I'll read them." foot={<Foot onBack={onBack} next={() => restart.mutate()} nextLabel="Start reading" busy={restart.isPending} />} />)
  const status = (k: typeof STAGES[number]) => { const n = STAGES.indexOf(k); return n < at ? 'done' : n > at ? 'pending' : failed ? 'failed' : k === 'review' ? 'done' : 'running' }
  const think = scan?.think_started ? Math.max(0, (now - Date.parse(scan.think_started)) / 1000) : 0
  const line = failed ? 'I had to stop.' : stage === 'review' ? "Done. Here's what I found."
    : stage === 'think' ? "Now I'm working out your role, your team and your priorities. This is the slow part."
    : stage === 'read' ? 'Looking at who you work with and what you work on.'
    : stage === 'chat' ? 'Now Teams and Slack, through Claude’s connectors.'
    : "I'm reading your calendar, meeting notes, mail and files into my own database on this Mac."
  const phases = (scan?.phases ?? []).filter((p) => p.status !== 'skipped')   // the onboarding import leaves document cards to the next sync
  return <>
    <Says live={!!scan?.running} className="mb-5"><span className="font-semibold">{line}</span>
      {scan?.running && <span className="block text-[13px] text-ink2">You can leave this page: I'll keep going, and you can come back.</span>}</Says>
    <Card foot={failed ? <Foot onBack={onBack} next={() => restart.mutate()} nextLabel="Try again" busy={restart.isPending} />
      : stage === 'review' ? <Foot next={onReview} nextLabel="See what I found" /> : undefined}>
      <ol className="space-y-4">
        <Stage state={status('import')} title="Reading your sources" sub="Calendar, meeting notes, mail and files">
          {status('import') === 'running' && phases.length > 0 && (
            <ul className="mt-2 space-y-1.5">{phases.map((p) => (
              <li key={p.name} className="flex items-center gap-2 text-[13px]">
                <Tick state={p.status === 'done' ? 'done' : p.status === 'running' ? 'running' : p.status === 'failed' ? 'failed' : 'pending'} small />
                <span className={cn(p.status === 'pending' && 'text-ink3', p.status === 'skipped' && 'text-ink3 line-through')}>{PHASE_NAME[p.name] ?? p.name}</span>
              </li>))}</ul>)}
        </Stage>
        {scan?.chat && <Stage state={status('chat')} title="Reading Teams and Slack" sub="Through Claude’s connectors, read only" />}
        <Stage state={status('read')} title="Looking at who you work with">
          {scan!.notes.length > 0 && <ul className="mt-2 space-y-1.5">{scan!.notes.map((n) => (
            <li key={n} className="note-in flex items-start gap-2 text-[13.5px] leading-snug"><span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent ring-1 ring-ink/20" />{n}</li>))}</ul>}
        </Stage>
        <Stage state={status('think')} title="Working out your role, team and priorities"
          sub={status('think') === 'running' ? `${mmss(think)} · usually about ${Math.round((scan?.typical_secs ?? 150) / 60 * 2) / 2} minutes` : status('think') === 'pending' ? 'One careful read of everything above' : undefined} />
      </ol>
      {failed && <Err>{scan?.error}</Err>}
    </Card>
  </>
}

function Tick({ state, small }: { state: 'done' | 'running' | 'failed' | 'pending'; small?: boolean }) {
  const s = small ? 'size-4' : 'size-6'
  if (state === 'done') return <span className={cn('grid shrink-0 place-items-center rounded-full bg-accent text-onaccent', s)}><Check size={small ? 10 : 14} strokeWidth={3} /></span>
  if (state === 'running') return <Loader2 className={cn('shrink-0 animate-spin text-ink', s)} />
  if (state === 'failed') return <span className={cn('grid shrink-0 place-items-center rounded-full bg-hot text-white', s)}><X size={small ? 10 : 14} strokeWidth={3} /></span>
  return <span className={cn('shrink-0 rounded-full border-2 border-line', s)} />
}

function Stage({ state, title, sub, children }: { state: 'done' | 'running' | 'failed' | 'pending'; title: string; sub?: string; children?: ReactNode }) {
  return (
    <li className="flex gap-3">
      <Tick state={state} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className={cn('text-[14px] font-semibold', state === 'pending' && 'text-ink3')}>{title}</div>
        {sub && <div className="text-[12.5px] text-ink3">{sub}</div>}
        {children}
      </div>
    </li>
  )
}

// ---------------------------------------------------------------- Review: what it found, its questions, every field editable
type Draft = {
  summary: string
  identity: { full_name: string; first_name: string; emails: string[]; title: string; role_short: string }
  company: { name: string; domains: string[] }
  timezone: string
  manager: { name: string; title: string } | null
  team: OnboardPerson[]; key_people: OnboardPerson[]; bets: OnboardBet[]
  voice: { signoff: string; spelling: '' | 'British' | 'American'; notes: string[] }
  calendar: { meeting_days: string; meeting_hours: string; meeting_minutes: number }
  personal_meetings: string[]
}
const toDraft = (r: Onboard, s: SetupState): Draft => ({
  summary: r.summary,
  identity: { full_name: r.identity.full_name || s.profile.full_name, first_name: r.identity.first_name || s.profile.first_name,
    emails: r.identity.emails.length ? r.identity.emails : s.profile.emails, title: r.identity.title || s.profile.role, role_short: r.identity.role_short },
  company: s.org.pack ? { name: s.org.name, domains: s.org.domains } : { name: r.company.name || s.org.name, domains: r.company.domains.length ? r.company.domains : s.org.domains },
  timezone: r.timezone || s.profile.timezone,
  manager: r.manager ? { name: r.manager.name, title: r.manager.title } : null,
  team: r.team, key_people: r.key_people, bets: r.bets,
  voice: { signoff: r.voice.signoff || s.profile.signoff, spelling: r.voice.spelling, notes: r.voice.notes },
  calendar: { meeting_days: r.calendar.meeting_days || 'mon,tue,wed,thu,fri', meeting_hours: r.calendar.meeting_hours || '09:00-17:00', meeting_minutes: r.calendar.meeting_minutes || 30 },
  personal_meetings: r.personal_meetings.map((p) => p.title),
})

// an answer changes the draft: a title, a manager or a company is the answer; for people, bets and meetings the options
// picked are kept or added and the ones left are taken off; the top bet gets weight 5
function answer(d: Draft, r: Onboard, q: OnboardQuestion, picked: string[]): Draft {
  const opts = q.options.map((o) => o.value), v = picked[0] ?? ''
  switch (q.field) {
    case 'role': return v ? { ...d, identity: { ...d.identity, title: v } } : d
    case 'company': return v ? { ...d, company: { ...d.company, name: v } } : d
    case 'manager': return v ? { ...d, manager: { name: v, title: d.manager?.name === v ? d.manager.title : '' } } : d
    case 'team': {
      const keep = d.team.filter((t) => !opts.includes(t.name) || picked.includes(t.name))
      return { ...d, team: [...keep, ...picked.filter((n) => !keep.some((t) => t.name === n)).map((n) => ({ name: n, refs: [] }))] }
    }
    case 'bets': {
      const keep = d.bets.filter((b) => !opts.includes(b.name) || picked.includes(b.name))
      return { ...d, bets: [...keep, ...r.bets.filter((b) => picked.includes(b.name) && !keep.some((k) => k.name === b.name))] }
    }
    case 'top_bet': return v ? { ...d, bets: d.bets.map((b) => (b.name === v ? { ...b, weight: 5 } : b.weight === 5 ? { ...b, weight: 4 } : b)) } : d
    case 'personal': {
      const keep = d.personal_meetings.filter((t) => !opts.includes(t) || picked.includes(t))
      return { ...d, personal_meetings: [...keep, ...picked.filter((t) => !keep.includes(t))] }
    }
  }
  return d
}

function Review({ s, scan, onRead, onConnect, onDone }: { s: SetupState; scan?: ScanState; onRead: () => void; onConnect: () => void; onDone: () => void }) {
  const qc = useQueryClient()
  const r = scan?.result
  const [d, setD] = useState<Draft | null>(() => (r ? toDraft(r, s) : null))
  useEffect(() => { if (r && !d) setD(toDraft(r, s)) }, [r]) // eslint-disable-line react-hooks/exhaustive-deps
  const again = useMutation({ mutationFn: () => api.setupScanStart(!!scan?.chat), onSuccess: (x) => { qc.setQueryData(['setupScan'], x); onRead() } })
  const save = useMutation({
    mutationFn: () => api.setupApply({ ...d!, identity: { ...d!.identity, first_name: d!.identity.full_name.split(/\s+/).includes(d!.identity.first_name) ? d!.identity.first_name : '' } }),
    onSuccess: (x) => { qc.setQueryData(['setup'], x); void qc.invalidateQueries({ queryKey: ['meta'] }); onDone() },
  })
  if (!r || !d) return (
    <Card title="Nothing to review yet" lead={scan?.running ? "I'm still reading." : 'Connect your sources and let me read them first.'}
      foot={<Foot next={scan?.running ? onRead : onConnect} nextLabel={scan?.running ? 'Back to reading' : 'Connect your sources'} />} />)
  const labels = r.ref_labels
  const set = (p: Partial<Draft>) => setD({ ...d, ...p })
  const ok = !!d.identity.full_name.trim() && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(d.identity.emails[0] ?? '')
  return <>
    <Says className="mb-5">
      {r.summary && <p>{r.summary}</p>}
      <p className={cn('text-[13.5px] text-ink2', r.summary && 'mt-2')}>Here's how I'd set myself up. {r.questions.length ? 'Answer my questions, fix' : 'Fix'} anything I got wrong, then confirm. Nothing is saved before that.</p>
    </Says>
    {r.questions.length > 0 && <Questions qs={r.questions} onAnswer={(q, picked) => setD((x) => x && answer(x, r, q, picked))} className="mb-4" />}

    <Section title="You">
      <Row label="Name"><input value={d.identity.full_name} onChange={(e) => set({ identity: { ...d.identity, full_name: e.target.value } })} aria-label="Your name" className={cn(quiet, 'font-medium')} />
        <Why conf={r.identity.confidence} text={r.identity.evidence} /></Row>
      <Row label="Job title"><input value={d.identity.title} onChange={(e) => set({ identity: { ...d.identity, title: e.target.value } })} placeholder="Your job title" aria-label="Job title" className={quiet} /></Row>
      <Row label="Work email"><input value={d.identity.emails[0] ?? ''} onChange={(e) => set({ identity: { ...d.identity, emails: [e.target.value.trim().toLowerCase(), ...d.identity.emails.slice(1)] } })} type="email" aria-label="Work email" className={quiet} />
        {d.identity.emails.length > 1 && <p className="px-3 text-[12px] text-ink3">Also: {d.identity.emails.slice(1).join(', ')}</p>}</Row>
      <Row label="Company">{s.org.pack
        ? <p className="px-3 py-1 text-[14px]">{d.company.name} <span className="text-[12px] text-ink3">· from your company file</span></p>
        : <><input value={d.company.name} onChange={(e) => set({ company: { ...d.company, name: e.target.value } })} placeholder="Company name" aria-label="Company" className={quiet} />
          <input value={d.company.domains.join(', ')} onChange={(e) => set({ company: { ...d.company, domains: e.target.value.split(/[\s,]+/).filter(Boolean) } })}
            placeholder="mail domains, e.g. acme.com" aria-label="Company mail domains" className={cn(quiet, 'text-[12.5px] text-ink2')} />
          {r.company.about && <p className="px-3 text-[12px] text-ink3">{r.company.about}</p>}</>}</Row>
      <Row label="Time zone">
        <select value={d.timezone} onChange={(e) => set({ timezone: e.target.value })} aria-label="Time zone" className={cn(quiet, 'appearance-none')}>
          {(zones.includes(d.timezone) ? zones : [d.timezone, ...zones]).map((z) => <option key={z} value={z}>{z.replace(/_/g, ' ')}</option>)}
        </select></Row>
    </Section>

    <Section title="Who you work with" hint="I keep their mail, meetings and promises to you near the top.">
      <Row label="Manager">
        {d.manager ? <div className="flex items-center gap-1">
          <input value={d.manager.name} onChange={(e) => set({ manager: { ...d.manager!, name: e.target.value } })} aria-label="Manager" className={cn(quiet, 'w-[46%] font-medium')} />
          <input value={d.manager.title} onChange={(e) => set({ manager: { ...d.manager!, title: e.target.value } })} placeholder="their title" aria-label="Manager's title" className={cn(quiet, 'w-[46%] text-ink2')} />
          <RemoveBtn label="No manager" onClick={() => set({ manager: null })} /></div>
          : <AddPerson placeholder="Who you report to" onAdd={(n) => set({ manager: { name: n, title: '' } })} />}
        {r.manager && d.manager?.name === r.manager.name && <Why conf={r.manager.confidence} text={r.manager.evidence} refs={r.manager.refs} labels={labels} />}
      </Row>
      <Row label="Your team">
        <People xs={d.team} onRemove={(n) => set({ team: d.team.filter((t) => t.name !== n) })} onAdd={(n) => set({ team: [...d.team, { name: n, refs: [] }] })} add="Add someone" />
      </Row>
      <Row label="Also works with">
        <People xs={d.key_people} onRemove={(n) => set({ key_people: d.key_people.filter((t) => t.name !== n) })} onAdd={(n) => set({ key_people: [...d.key_people, { name: n, refs: [] }] })} add="Add someone" />
      </Row>
    </Section>

    <Section title="What you're working towards" hint="Your bets: I file mail, meetings and tasks under them and rank your work by their weight.">
      <div className="space-y-2.5">
        {d.bets.map((b, n) => <BetRow key={n} b={b} labels={labels} onChange={(x) => set({ bets: d.bets.map((y, j) => (j === n ? { ...y, ...x } : y)) })}
          onRemove={() => set({ bets: d.bets.filter((_, j) => j !== n) })} />)}
      </div>
      {d.bets.length < 8 && <Button onClick={() => set({ bets: [...d.bets, { name: '', goal: '', weight: 3, refs: [] }] })} className="mt-3"><Plus size={14} /> Add a bet</Button>}
    </Section>

    <Section title="How you work" hint="From your calendar and your sent mail. I use it when I propose times and write drafts.">
      <Row label="Meeting days">
        <div className="flex flex-wrap gap-1 px-1">{['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((k) => { const on = d.calendar.meeting_days.split(',').includes(k)
          return <button key={k} onClick={() => { const xs = d.calendar.meeting_days.split(',').filter(Boolean); set({ calendar: { ...d.calendar, meeting_days: (on ? xs.filter((x) => x !== k) : [...xs, k]).join(',') } }) }}
            aria-pressed={on} className={btnClass(on ? 'ink' : 'outline', 'xs', 'capitalize')}>{k}</button> })}</div></Row>
      <Row label="Meeting hours">
        <div className="flex flex-wrap items-center gap-2 px-1 text-[13px] text-ink2">
          {(['from', 'to'] as const).map((w, n) => <input key={w} type="time" step={1800} aria-label={`Meetings ${w}`} value={d.calendar.meeting_hours.split('-')[n] ?? ''}
            onChange={(e) => { const h = d.calendar.meeting_hours.split('-'); h[n] = e.target.value; set({ calendar: { ...d.calendar, meeting_hours: `${h[0] ?? '09:00'}-${h[1] ?? '17:00'}` } }) }}
            className={cn(inputClass, 'py-1')} />)}
          <span className="ml-2">usually</span>
          <Segmented label="Usual meeting length" value={d.calendar.meeting_minutes} onChange={(m) => set({ calendar: { ...d.calendar, meeting_minutes: m } })}
            options={[15, 30, 45, 60].map((m) => [m, `${m} min`] as const)} />
        </div></Row>
      <Row label="Email sign-off"><input value={d.voice.signoff} onChange={(e) => set({ voice: { ...d.voice, signoff: e.target.value } })} placeholder="-Milo" aria-label="Email sign-off" className={quiet} /></Row>
      <Row label="Spelling"><div className="px-1"><Segmented label="Spelling" value={d.voice.spelling || 'British'} onChange={(x) => set({ voice: { ...d.voice, spelling: x } })}
        options={[['British', 'British'], ['American', 'American']] as const} /></div></Row>
      {d.voice.notes.length > 0 && <Row label="How you write">
        <ul className="space-y-0.5 px-3 text-[13.5px] text-ink2">{d.voice.notes.map((n) => <li key={n}>{n}</li>)}</ul></Row>}
    </Section>

    {d.personal_meetings.length > 0 && <Section title="Kept out" hint="Personal entries on your calendar: never in briefs, tasks or drafts.">
      <div className="flex flex-wrap gap-1.5">{d.personal_meetings.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-full border border-line py-0.5 pl-3 pr-1 text-[13px]">{t}
          <RemoveBtn label={`Not personal: ${t}`} onClick={() => set({ personal_meetings: d.personal_meetings.filter((x) => x !== t) })} /></span>))}</div>
    </Section>}

    <div className="sticky bottom-0 z-10 -mx-5 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-bg/95 px-5 py-3 backdrop-blur">
      <span className="text-[12.5px] text-ink3">{save.error ? <span className="text-hot">{save.error.message}</span> : 'Nothing is saved until you confirm.'}</span>
      <span className="flex-1" />
      <Button size="md" onClick={() => again.mutate()} disabled={again.isPending || save.isPending}><RotateCw size={14} className={again.isPending ? 'animate-spin' : ''} /> Read again</Button>
      <Button variant="primary" size="md" onClick={() => save.mutate()} disabled={!ok || save.isPending}>
        {save.isPending ? <><Loader2 size={14} className="animate-spin" /> Setting up…</> : <>Looks right, set me up <ArrowRight size={14} /></>}</Button>
    </div>
  </>
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="mb-4 border border-line bg-panel px-6 pb-5 pt-5 max-sm:px-4">
      <h2 className="text-[16px] font-semibold tracking-[-0.01em]">{title}</h2>
      {hint && <p className="mt-0.5 text-[12.5px] text-ink3">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-3 gap-y-1 border-t border-line2 py-2 first:border-t-0 sm:grid-cols-[132px_1fr]">
      <div className="pt-1.5 text-[12.5px] text-ink3">{label}</div>
      <div className="min-w-0 sm:-ml-3">{children}</div>
    </div>
  )
}

const CONF: Record<Conf, [string, string]> = { confirmed: ['Confirmed', 'bg-accentbg text-ink'], likely: ['Likely', 'bg-panel2 text-ink2'], unverified: ['A guess', 'border border-dashed border-ink3 text-ink2'] }
// why SleePO thinks so: how sure, in a few words, and the sources (their labels; the full list on hover)
function Why({ conf, text, refs = [], labels = {} }: { conf?: Conf; text?: string; refs?: string[]; labels?: Record<string, string> }) {
  const named = refs.map((x) => labels[x]).filter(Boolean)
  if (!conf && !text && !named.length) return null
  return (
    <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 px-3 text-[12px] text-ink3" title={named.length ? `Based on:\n${named.join('\n')}` : undefined}>
      {conf && <span className={cn('rounded-full px-1.5 py-px text-[11px] font-medium', CONF[conf][1])}>{CONF[conf][0]}</span>}
      {text && <span>{text}</span>}
      {!text && named.length > 0 && <span>from {named.slice(0, 2).join(' · ')}{named.length > 2 ? ` and ${named.length - 2} more` : ''}</span>}
    </p>
  )
}

const RemoveBtn = ({ label, onClick }: { label: string; onClick: () => void }) => (
  <button onClick={onClick} title={label} aria-label={label} className="grid size-6 shrink-0 place-items-center rounded-full text-ink3 hover:bg-panel2 hover:text-ink"><X size={13} /></button>)

function AddPerson({ placeholder, onAdd }: { placeholder: string; onAdd: (name: string) => void }) {
  const [v, setV] = useState('')
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (v.trim()) { onAdd(v.trim()); setV('') } }} className="flex items-center gap-1">
      <input value={v} onChange={(e) => setV(e.target.value)} placeholder={placeholder} aria-label={placeholder} className={cn(quiet, 'max-w-[240px]')} />
      {v.trim() && <Button type="submit" variant="outline" size="xs">Add</Button>}
    </form>
  )
}

function People({ xs, onRemove, onAdd, add }: { xs: OnboardPerson[]; onRemove: (n: string) => void; onAdd: (n: string) => void; add: string }) {
  const [adding, setAdding] = useState(false)
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-1 py-0.5">
      {xs.map((p) => (
        <span key={p.name} title={[p.title, p.why || p.evidence].filter(Boolean).join(' · ') || undefined}
          className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-panel py-0.5 pl-0.5 pr-1 text-[13px]">
          <Avatar p={{ name: p.name, avatar: '' }} size={22} />
          <span className="truncate">{p.name}</span>
          {(p.title || p.why) && <span className="truncate text-[12px] text-ink3 max-sm:hidden">{p.title || p.why}</span>}
          <RemoveBtn label={`Remove ${p.name}`} onClick={() => onRemove(p.name)} />
        </span>))}
      {adding ? <AddPerson placeholder="Full name" onAdd={(n) => { onAdd(n); setAdding(false) }} />
        : <button onClick={() => setAdding(true)} className={btnClass('ghost', 'xs', 'text-ink2')}><Plus size={13} />{add}</button>}
    </div>
  )
}

function BetRow({ b, labels, onChange, onRemove }: { b: OnboardBet; labels: Record<string, string>; onChange: (x: Partial<OnboardBet>) => void; onRemove: () => void }) {
  const named = b.refs.map((x) => labels[x]).filter(Boolean)
  return (
    <div className="group/b border border-line px-3 py-2.5">
      <div className="flex items-center gap-1">
        <input value={b.name} onChange={(e) => onChange({ name: e.target.value })} placeholder="An outcome you're working towards" aria-label="Bet" className={cn(quiet, 'text-[14.5px] font-semibold')} autoFocus={!b.name} />
        <Segmented label={`Weight of ${b.name || 'this bet'}`} value={b.weight} onChange={(w) => onChange({ weight: w })} options={[1, 2, 3, 4, 5].map((w) => [w, String(w), w === 5 ? 'Weight 5: matters most' : `Weight ${w}`] as const)} />
        <RemoveBtn label={`Remove ${b.name || 'this bet'}`} onClick={onRemove} />
      </div>
      <textarea value={b.goal} onChange={(e) => onChange({ goal: e.target.value })} placeholder="Done when… (optional)" aria-label={`Goal of ${b.name}`}
        rows={Math.min(3, Math.max(1, Math.ceil(b.goal.length / 78)))} className={cn(quiet, 'block resize-none rounded-xl text-[13px] leading-snug text-ink2')} />
      {(b.why || named.length > 0) && <p className="px-3 pt-0.5 text-[12px] leading-snug text-ink3" title={named.length ? `Based on:\n${named.join('\n')}` : undefined}>
        {b.why}{named.length > 0 && <span className="text-ink3">{b.why ? ' · ' : ''}{named.length} source{named.length > 1 ? 's' : ''}</span>}</p>}
    </div>
  )
}

// The agent's questions, asked the way FillQuestions asks: one at a time, a header chip each across the top, numbered
// options with a line on what each means, a tick box where several apply, Other for your own words (a title, a person, a
// company). Each answer changes the draft below at once; Change asks it again.
function Questions({ qs, onAnswer, className }: { qs: OnboardQuestion[]; onAnswer: (q: OnboardQuestion, picked: string[]) => void; className?: string }) {
  const [i, setI] = useState(0)
  const [ans, setAns] = useState<Record<string, string[]>>({})
  const [sel, setSel] = useState<string[]>([])
  const [other, setOther] = useState('')
  const q = qs[Math.min(i, qs.length - 1)]
  const done = qs.every((x) => ans[x.id])
  const free = q.field === 'role' || q.field === 'manager' || q.field === 'company'
  useEffect(() => { setSel(ans[q.id] ?? []); setOther('') }, [q.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const commit = (picked: string[]) => {
    onAnswer(q, picked)
    const a = { ...ans, [q.id]: picked }
    setAns(a)
    const next = qs.findIndex((x, n) => n > i && !a[x.id])
    setI(next >= 0 ? next : qs.findIndex((x) => !a[x.id]) >= 0 ? qs.findIndex((x) => !a[x.id]) : i)
  }
  const pick = (v: string) => (q.multi ? setSel(sel.includes(v) ? sel.filter((x) => x !== v) : [...sel, v]) : setSel([v]))
  const said = (x: OnboardQuestion) => (ans[x.id] ?? []).map((v) => x.options.find((o) => o.value === v)?.label ?? v).join(', ') || 'None'
  const row = (on: boolean) => cn('flex w-full items-start gap-2.5 rounded-lg border px-2.5 py-1.5 text-left transition-colors', on ? 'border-ink bg-accentbg' : 'border-line hover:border-ink hover:bg-panel2')
  const mark = (on: boolean, n: number) => <span aria-hidden className={cn('mt-px grid size-5 shrink-0 place-items-center text-[11px] font-semibold tabular-nums', q.multi ? 'rounded-[5px] border' : 'rounded-full border',
    on ? 'border-ink bg-ink text-bg' : 'border-line text-ink2')}>{on ? <Check size={12} /> : n}</span>
  const onKey = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).tagName === 'INPUT' || e.metaKey || e.ctrlKey || done) return
    const n = Number(e.key)
    if (n >= 1 && n <= q.options.length) { e.preventDefault(); pick(q.options[n - 1].value) }
    else if (e.key === 'Enter' && (sel.length || q.multi)) { e.preventDefault(); commit(sel) }
  }
  return (
    <section aria-label="SleePO's questions" tabIndex={-1} onKeyDown={onKey} className={cn('rounded-xl border border-line bg-panel shadow-sm outline-none', className)}>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line2 px-4 py-2.5">
        <span className="mr-1 text-[13px] font-semibold">{done ? 'Thanks: your answers are in below' : qs.length > 1 ? `${qs.length} questions for you` : 'A question for you'}</span>
        {qs.map((x, n) => <button key={x.id} onClick={() => setI(n)} aria-current={!done && n === i ? 'step' : undefined} title={x.question}
          className={cn('inline-flex items-center gap-1 rounded-full px-2 py-px text-[11.5px] font-medium transition-colors', !done && n === i ? 'bg-ink text-bg' : ans[x.id] ? 'bg-accentbg text-ink' : 'bg-panel2 text-ink2 hover:text-ink')}>
          {ans[x.id] && (done || n !== i) && <Check size={11} aria-hidden />}{x.header}</button>)}
      </div>
      {done ? (
        <ul className="divide-y divide-line2 px-4">{qs.map((x, n) => (
          <li key={x.id} className="flex items-baseline gap-3 py-2 text-[13px]">
            <span className="min-w-0 flex-1 text-ink2">{x.question}</span>
            <span className="shrink-0 font-medium">{said(x)}</span>
            <button onClick={() => { setAns(Object.fromEntries(Object.entries(ans).filter(([k]) => k !== x.id))); setI(n) }} className="shrink-0 text-[12px] text-ink3 hover:text-ink">Change</button>
          </li>))}</ul>
      ) : (
        <div className="px-4 py-3">
          <div className="mb-2 flex items-baseline gap-2">
            <h3 className="text-[14px] font-semibold leading-snug">{q.question}</h3>
            {q.multi && <span className="shrink-0 text-[11.5px] text-ink3">pick any</span>}
          </div>
          <div role={q.multi ? 'group' : 'radiogroup'} aria-label={q.question} className="space-y-1">
            {q.options.map((o, n) => { const on = sel.includes(o.value); return (
              <button key={o.value} role={q.multi ? 'checkbox' : 'radio'} aria-checked={on} onClick={() => pick(o.value)} className={row(on)}>
                {mark(on, n + 1)}
                <span className="min-w-0"><span className="block text-[13px] font-medium leading-snug">{o.label}</span>
                  {o.description && <span className="block text-[12px] leading-snug text-ink2">{o.description}</span>}</span>
              </button>) })}
            {free && <div className={row(!!other.trim())}>
              {mark(!!other.trim(), q.options.length + 1)}
              <input value={other} onChange={(e) => { setOther(e.target.value); setSel([]) }} onKeyDown={(e) => { if (e.key === 'Enter' && other.trim()) { e.preventDefault(); commit([other.trim()]) } }}
                placeholder="Other: type your own" aria-label="Your own answer" className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink3" />
            </div>}
          </div>
          <div className="mt-2.5 flex items-center gap-1.5">
            {i > 0 && <button onClick={() => setI(i - 1)} className="inline-flex items-center gap-0.5 rounded-full px-2 py-1 text-[12.5px] font-medium text-ink2 hover:bg-panel2 hover:text-ink"><ChevronLeft size={13} aria-hidden />Back</button>}
            <span className="text-[11.5px] text-ink3 max-sm:hidden">{i + 1} of {qs.length} · 1–{q.options.length} to pick · Enter</span>
            <button onClick={() => commit([])} className="ml-auto rounded-full px-2.5 py-1 text-[12.5px] font-medium text-ink2 hover:bg-panel2 hover:text-ink">{q.multi ? 'None of these' : 'Skip'}</button>
            <Button variant="primary" onClick={() => commit(other.trim() ? [other.trim()] : sel)} disabled={!q.multi && !sel.length && !other.trim()}>{q.multi ? 'Confirm' : 'Answer'}</Button>
          </div>
        </div>)}
    </section>
  )
}

// ---------------------------------------------------------------- Done
function Done({ s }: { s: SetupState }) {
  const [busy, setBusy] = useState(false)
  const first = s.profile.first_name
  const tips = useMemo(() => [
    ['Today', 'Your day: meetings, what you owe and what is next.'],
    ['Inbox', 'Mail that needs a response, each with a recommended reply.'],
    ['⌘J', 'Ask SleePO about whatever is on screen: an email, a conversation, a meeting.'],
    ['You', 'Everything I set up is in Personalisation, in the menu under your picture.']] as const, [])
  const open = async () => {
    setBusy(true)
    const r = await api.setupFinish(true).catch(() => ({ restarting: false }))
    if (r.restarting) {   // the server restarts so every prompt reads the new profile: wait for it, then open Today
      await new Promise((ok) => setTimeout(ok, 2500))
      for (let n = 0; n < 40; n++) { try { if ((await fetch('/status', { cache: 'no-store' })).ok) break } catch { /* restarting */ } await new Promise((ok) => setTimeout(ok, 500)) }
    }
    window.location.replace('/#/'); window.location.reload()
  }
  return <>
    <Says className="mb-5"><span className="font-semibold">{first ? `All set, ${first}.` : 'All set.'}</span> I've saved your profile, your company and your bets.
      {s.demo ? ' This demo copy runs nothing by itself: imports happen when you press Refresh.' : ' From now on I refresh every weekday morning, and every half hour through the day.'}</Says>
    <Card foot={<><span className="flex-1" /><Button variant="primary" size="md" onClick={open} disabled={busy}>{busy ? <><Loader2 size={14} className="animate-spin" /> Starting SleePO…</> : <>Open SleePO <ArrowRight size={14} /></>}</Button></>}>
      <ul className="divide-y divide-line2">
        {tips.map(([k, t]) => <li key={k} className="flex items-baseline gap-4 py-3 first:pt-0"><span className="w-14 shrink-0 text-[13px] font-semibold">{k}</span><span className="text-[13.5px] text-ink2">{t}</span></li>)}
      </ul>
    </Card>
  </>
}
