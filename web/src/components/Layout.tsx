import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, Outlet, useRouter, useRouterState } from '@tanstack/react-router'
import { useBackTarget, useNavRecorder } from '@/lib/nav'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAgents } from '@/lib/agents'
import { api } from '@/lib/api'
import { AccountMenu } from './AccountMenu'
import { useLive } from '@/lib/live'
import { cn, usePersisted } from '@/lib/util'
import { wall } from '@/lib/time'
import { Logo } from './Logo'
import { HeaderSearch } from './HeaderSearch'
import { LivePill } from './LivePill'
import { RefreshButton } from './RefreshButton'
import { DocViewerHost } from './DocViewer'
import { ChatHost, ChatProvider } from './Chat'
import { EntityPanelHost } from './EntityPanel'
import { ArrowLeft, Zap, Brain, Map as MapIcon, Bot, ChevronDown, ChevronRight, Loader2, Pin, X, TrendingUp, Handshake, Repeat, ListTodo, CalendarDays, Compass, Files, FolderGit2, Inbox as InboxIcon, Menu, MessagesSquare, Package, PanelLeftClose, PanelLeftOpen, Plug, Sparkles, Sun, Moon, Target, Users, type LucideIcon } from 'lucide-react'
import { profile } from '@/lib/profile'

// Light / dark switch, in the header left of Refresh (27 Oct 2026; the sidebar's footer is gone). Names the mode it switches
// to; the choice is remembered per browser.
function ThemeToggle() {
  const current = () => document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  const [theme, setTheme] = useState(current)
  const flip = () => {
    const next = current() === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try { localStorage.setItem('assist-theme', next) } catch { /* private window: still switches for this visit */ }
    setTheme(next)
  }
  const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
  return (
    <button onClick={flip} title={label} aria-label={label}
      className="inline-flex size-8 items-center justify-center rounded-full text-ink2 transition-colors hover:bg-panel2 hover:text-ink">
      {theme === 'dark' ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
    </button>
  )
}

// Sidebar: the daily tier (Actions + Work) is always open; the reference sections fold away and remember it.
// A folded section opens by itself while you are on one of its pages. An entry can be a sub-list (Knowledge › Product:
// Roadmap; Knowledge › Sales: Pipeline, Retention) that folds the same way; the icon rail shows its pages in line.
// Pinned (Sam, 29 Oct 2026): the top-of-mind topics he pinned sit under Work, one row each, opening the topic's page; × on
// hover unpins. The section shows only while something is pinned (assist/topics.py pins; components/TopOfMind.tsx).
type NavLink = { to: string; label: string; icon: LucideIcon; count?: string; badge?: 'needs' | 'meetings' }   // badge: a live count (needs: asks for attention; meetings: information)
type NavSub = { label: string; icon: LucideIcon; items: NavLink[] }
type NavGroup = { group: string; label?: boolean; fold?: boolean; foldDefault?: boolean; items: (NavLink | NavSub)[] }
const isSub = (e: NavLink | NavSub): e is NavSub => 'items' in e
const navLinks = (g: NavGroup) => g.items.flatMap((e) => (isSub(e) ? e.items : [e]))
const NAV: NavGroup[] = [
  // Actions replaced Today, the widget board (Sam, 25 Nov 2026: "get rid of the dashboard page"): reactive and proactive actions
  { group: 'Overview', label: false, items: [{ to: '/assistant', label: 'Assistant', icon: Sparkles }, { to: '/', label: 'Actions', icon: Zap }] },
  { group: 'Work', items: [{ to: '/tasks', label: 'Tasks', icon: ListTodo }, { to: '/initiatives', label: 'Initiatives', icon: Target, count: 'initiatives' }, { to: '/meetings', label: 'Meetings', icon: CalendarDays, badge: 'meetings' }, { to: '/inbox', label: 'Inbox', icon: InboxIcon, badge: 'needs' }, { to: '/messages', label: 'Messages', icon: MessagesSquare }] },
  // Context is gone: People, renamed Relationships (people and companies), moved to Knowledge (Sam, 27 Oct 2026).
  // Explore first, above Relationships (Sam, 30 Oct 2026)
  { group: 'Knowledge', fold: true, items: [{ to: '/explore', label: 'Explore', icon: Compass, count: 'library' }, { to: '/people', label: 'Relationships', icon: Users, count: 'people' }, { to: '/documents', label: 'Documents', icon: Files, count: 'documents' },
    // Product holds the roadmap (Sam, 30 Oct 2026: "create a products subsection and put roadmap in it"; then "Product. No S.")
    // Code base: the GitLab clones the assistant reads when the docs don't answer (Sam, 20 Nov 2026; views/code.tsx)
    { label: 'Product', icon: Package, items: [{ to: '/roadmap', label: 'Roadmap', icon: MapIcon }, { to: '/code', label: 'Code base', icon: FolderGit2 }] },
    { label: 'Sales', icon: Handshake, items: [{ to: '/pipeline', label: 'Pipeline', icon: TrendingUp, count: 'pipeline' }, { to: '/retention', label: 'Retention', icon: Repeat }] }] },
  { group: 'System', fold: true, foldDefault: true, items: [{ to: '/agents', label: 'Agents', icon: Bot }, { to: '/memory', label: 'Memory', icon: Brain }, { to: '/sources', label: 'Sources', icon: Plug }] },
]

// true while the window is at least this wide (the sidebar is a drawer on a phone)
function useWide(q = '(min-width: 768px)') {
  const [wide, setWide] = useState(() => matchMedia(q).matches)
  useEffect(() => { const m = matchMedia(q); const f = () => setWide(m.matches); m.addEventListener('change', f); return () => m.removeEventListener('change', f) }, [q])
  return wide
}

const APP = 'SleePO'
type Crumb = { label: string; to?: string; params?: Record<string, string> }

// Breadcrumb trail: SleePO › section › page › record. Record names come from queries the page already runs (shared cache).
function useCrumbs(path: string, search: Record<string, unknown>): Crumb[] {
  const seg = path.split('/').filter(Boolean)
  const id = seg.length > 1 ? decodeURIComponent(seg.slice(1).join('/')) : ''
  const person = useQuery({ queryKey: ['person', id], queryFn: () => api.person(id), enabled: seg[0] === 'people' && !!id })
  const sources = useQuery({ queryKey: ['sources'], queryFn: api.sources, enabled: seg[0] === 'sources' && !!id })
  const ini = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio, enabled: seg[0] === 'initiatives' && !!id })
  const topic = useQuery({ queryKey: ['topic', Number(id)], queryFn: () => api.topic(Number(id)), enabled: seg[0] === 'topics' && /^\d+$/.test(id), retry: false })
  const docId = seg[0] === 'explore' && seg[1] === 'library' ? decodeURIComponent(seg.slice(2).join('/')) : ''
  const doc = useQuery({ queryKey: ['doc', docId], queryFn: () => api.doc(docId), enabled: !!docId })
  const transcript = useQuery({ queryKey: ['transcript', id], queryFn: () => api.transcript(id), enabled: seg[0] === 'meetings' && /^m-\d+$/.test(id) })
  const root: Crumb = { label: APP, to: '/' }
  const company = useQuery({ queryKey: ['company', Number(id)], queryFn: () => api.company(Number(id)), enabled: seg[0] === 'companies' && /^\d+$/.test(id) })
  if (seg[0] === 'companies' || seg[0] === 'company') {   // Relationships › Companies › company (Sam, 23 Oct 2026)
    const out: Crumb[] = [root, { label: 'Knowledge' }, { label: 'Relationships', to: '/people' }, { label: 'Companies', to: id ? '/companies' : undefined }]
    if (id) out.push({ label: company.data?.name ?? '…' })
    return out
  }
  if (seg[0] === 'search') return [root, { label: 'Search' }, { label: `“${String(search.q ?? '')}”` }]
  if (seg[0] === 'topics') return [root, { label: 'Work' }, { label: 'Initiatives', to: '/initiatives' }, { label: 'Top of mind', to: '/initiatives' }, { label: topic.data?.title ?? '…' }]   // a topic's page (29 Oct 2026)
  if (seg[0] === 'explore') {
    const view = seg[1] === 'library' ? 'Library' : 'Graph'
    const out: Crumb[] = [root, { label: 'Knowledge' }, { label: 'Explore', to: '/explore' }, { label: view, to: docId ? '/explore/library' : undefined }]
    if (docId) { if (doc.data?.section) out.push({ label: doc.data.section }); out.push({ label: doc.data?.title ?? '…' }) }
    return out
  }
  if (seg[0] === 'soul') {   // a tab of Agents
    const sub = ({ sleepo: 'SleePO', cpo: profile().role_short || 'Role' } as Record<string, string>)[seg[1] ?? ''] ?? 'Company'
    return [root, { label: 'System' }, { label: 'Agents', to: '/agents' }, { label: 'Soul', to: '/soul' }, { label: sub }]
  }
  if (seg[0] === 'action-types') return [root, { label: 'System' }, { label: 'Agents', to: '/agents' }, { label: 'Action types' }]
  if (seg[0] === 'account') return [root, { label: 'Account' }]   // the account menu, top right
  if (seg[0] === 'settings') return [root, { label: 'Account', to: '/account' }, { label: 'Personalisation' }]
  const top = '/' + (seg[0] ?? '')
  const g = NAV.find((x) => navLinks(x).some((i) => i.to === top))
  const item = g && navLinks(g).find((i) => i.to === top)
  if (!g || !item) return [root]
  const out: Crumb[] = [root]
  if (g.group !== 'Overview') out.push({ label: g.group })
  const sub = g.items.find((e): e is NavSub => isSub(e) && e.items.includes(item))
  if (sub) out.push({ label: sub.label })
  out.push({ label: item.label, to: id ? item.to : undefined })
  if (id) {
    const name = seg[0] === 'people' ? person.data?.name
      : seg[0] === 'initiatives' ? ini.data?.find((x) => x.slug === id)?.name
      : seg[0] === 'sources' ? sources.data?.systems.find((x) => x.id === id)?.name
      : seg[0] === 'meetings' ? transcript.data?.title
      : undefined
    out.push({ label: name ?? '…' })
  }
  return out
}

function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-4 flex min-w-0 flex-wrap items-center gap-1.5 text-[13px] text-ink2">
      <BackButton divider />
      {crumbs.map((c, i) => {
        const last = i === crumbs.length - 1
        return (
          <span key={i} className="inline-flex min-w-0 items-center gap-1.5">
            {i > 0 && <span aria-hidden className="text-ink3">›</span>}
            {c.to && !last ? <Link to={c.to} className="text-ink2 no-underline hover:text-ink hover:underline">{c.label}</Link>
              : <span aria-current={last ? 'page' : undefined} className={cn('truncate', last ? 'max-w-[48ch] font-medium text-ink' : '')}>{c.label}</span>}
          </span>
        )
      })}
    </nav>
  )
}

// Back one step, saying where to (lib/nav.ts; Sam, 22 Oct 2026). It opens the breadcrumb line above each page's title (Sam:
// not in the top bar), or a slim line of its own on pages without breadcrumbs (the mail-client pages, Meetings). Hidden at
// the start of the history. Alt+← does the same anywhere (useBackKey, mounted once by Layout).
function useBackKey() {
  const router = useRouter()
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.altKey && e.key === 'ArrowLeft' && !/INPUT|TEXTAREA/.test((e.target as HTMLElement).tagName)) { e.preventDefault(); router.history.back() } }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [router])
}
function BackButton({ divider }: { divider?: boolean }) {
  const router = useRouter()
  const to = useBackTarget()
  if (!to) return null
  return (<>
    <button onClick={() => router.history.back()} title={`Back to ${to.title} (Alt+←)`}
      className="-ml-1.5 inline-flex max-w-[320px] items-center gap-1 rounded-full px-1.5 py-0.5 font-medium text-ink transition-colors hover:bg-panel2">
      <ArrowLeft size={14} aria-hidden className="shrink-0" /><span className="truncate">{to.title}</span></button>
    {divider && <span aria-hidden className="mx-1 h-3.5 w-px bg-line" />}
  </>)
}
// pages without breadcrumbs: Back on a slim line of its own, only when there is somewhere to go back to
function BackLine({ flush }: { flush?: boolean }) {
  const to = useBackTarget()
  if (!to) return null
  return <div className={cn('flex text-[13px]', flush ? 'border-b border-line bg-panel px-4 py-1' : 'mb-2')}><BackButton /></div>
}

// Until SleePO knows who the user is, every page says so and links to Personalisation (16 Nov 2026).
// The demo copy (assist/demo.py): a separate SleePO for trying setup as a new user; its controls are on the Account page
function DemoPill() {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 60_000 })
  if (!meta.data?.demo) return null
  return <Link to="/account" title="A separate copy of SleePO for trying setup as a new user. Your real SleePO, its data and settings are untouched."
    className="hidden items-center rounded-full border border-accent bg-accent/15 px-2.5 py-1 text-[12px] font-medium text-ink no-underline hover:bg-accent sm:inline-flex">Demo copy</Link>
}

function SetupBar() {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 60_000 })
  const p = meta.data?.profile
  if (!p || (p.full_name && p.emails.length)) return null
  return <a href="#/welcome?step=connect" className="mb-3 block border border-line bg-panel px-3 py-2 text-[13px]">SleePO does not know who you are yet, so it cannot tell your mail and meetings from anyone else’s. <b className="underline decoration-accent decoration-2 underline-offset-2">Finish setting up</b></a>
}

export function Layout({ children }: { children?: ReactNode }) {
  useNavRecorder()
  useBackKey()
  const qc = useQueryClient()
  const live = useLive(qc)
  const [folded, setFolded] = usePersisted<Record<string, boolean>>('assist-nav-folded', {})
  // The sidebar folds to an icon rail on a desktop (remembered; [ toggles it), so mail and other wide pages get the room.
  const [collapsed, setCollapsed] = usePersisted<boolean>('assist-nav-collapsed', false)
  const wide = useWide()
  // Below 1200px the sidebar is the rail by itself (Sam, 28 Oct 2026); opening it there lasts until the window is wide again,
  // and the remembered choice is for wide windows only.
  const roomy = useWide('(min-width: 1200px)')
  const [openNarrow, setOpenNarrow] = useState(false)
  useEffect(() => { setOpenNarrow(false) }, [roomy])
  const railed = roomy ? collapsed : !openNarrow
  const toggleRail = () => (roomy ? setCollapsed(!collapsed) : setOpenNarrow(!openNarrow))
  const rail = railed && wide
  // The rail's labels: hovering or tabbing to an icon shows its name beside it in volt. One label for the whole rail, fixed to
  // the window so the scrolling nav does not clip it; any element in the rail with data-tip gets one.
  const [tip, setTip] = useState<{ text: string; sub?: string; top: number; left: number } | null>(null)
  const tipFor = useRef<HTMLElement | null>(null)
  const placeTip = (el: HTMLElement | null) => {
    tipFor.current = el
    const r = el?.getBoundingClientRect()
    const box = el?.closest('nav')?.getBoundingClientRect()
    const y = r ? r.top + r.height / 2 : 0
    if (!el || !r || (box && (y < box.top || y > box.bottom))) { setTip(null); return }   // scrolled out of the rail's view
    setTip({ text: el.dataset.tip!, sub: el.dataset.tipSub, top: y, left: r.right + 10 })
  }
  const showTip = (e: React.SyntheticEvent) => placeTip((e.target as HTMLElement).closest<HTMLElement>('[data-tip]'))
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  // Inbox badge: mail that needs a reply (Sam, 22 Oct 2026). Same query as the Inbox's Needs reply chip, so his own
  // add / remove there moves the badge at once
  const replyFlags = useQuery({ queryKey: ['replyInbox'], queryFn: api.replyInbox, refetchInterval: 120_000 })
  // pinned topics: the same list Top of mind reads (shared cache), so a pin there shows here at once
  const topicsQ = useQuery({ queryKey: ['topics', 'all'], queryFn: () => api.topics(), staleTime: 60_000 })
  const pinned = (topicsQ.data?.topics ?? []).filter((t) => t.pinned)
  const unpin = async (id: number) => {
    qc.setQueryData<typeof topicsQ.data>(['topics', 'all'], (d) => d && { ...d, topics: d.topics.map((t) => t.id === id ? { ...t, pinned: false } : t) })
    try { await api.topicAction(id, 'unpin') } finally { for (const k of [['topics'], ['topic', id], ['portfolio']]) qc.invalidateQueries({ queryKey: k }) }
  }
  // Meetings badge: today's real meetings still to come (Sam, 22 Oct 2026): not over yet, people invited, not tentative or
  // unanswered, not cancelled, not all-day, not personal. Holds he put in with nobody invited do not count. A meeting drops
  // off when it ends: the clock ticks each minute so the badge does not wait for the next fetch.
  const todayQ = useQuery({ queryKey: ['today'], queryFn: api.today, refetchInterval: 300_000 })
  const [clock, setClock] = useState(() => Date.now())
  useEffect(() => { const t = setInterval(() => setClock(Date.now()), 60_000); return () => clearInterval(t) }, [])
  // The server's today is London's, which runs to 09:00 the next morning in Lisbon: keep the meetings on this Mac's today.
  const meetingsToday = (todayQ.data?.calendar_today ?? []).filter((e) => wall(e.end).getTime() > clock && wall(e.start).toDateString() === new Date(clock).toDateString() && e.attendees.length > 0 && !e.cancelled && !e.all_day
    && e.reply !== 'tentative' && e.reply !== 'not answered' && e.reply !== 'declined' && !/personal/i.test(e.skip || '')).length
  const badges: Record<string, number> = { needs: (replyFlags.data ?? []).filter((x) => x.needs_reply).length, meetings: meetingsToday }
  const badgeTip = (k: string, n: number) => k === 'needs' ? `${n} email${n > 1 ? 's' : ''} need${n > 1 ? '' : 's'} a reply` : `${n} meeting${n > 1 ? 's' : ''} still to come today`
  const badgeTone = (k: string) => k === 'needs' ? 'bg-hot text-white' : 'border border-line bg-panel2 text-ink'   // magenta only for what asks for attention
  const agents = useAgents()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const search = useRouterState({ select: (s) => s.location.search as Record<string, unknown> })
  const [menu, setMenu] = useState(false)
  useEffect(() => { setTip(null) }, [rail, path])
  const crumbs = useCrumbs(path, search)
  useEffect(() => { setMenu(false) }, [path])
  useEffect(() => { const page = crumbs.length > 1 ? crumbs[crumbs.length - 1].label : 'Actions'; document.title = `${page} · ${APP}` }, [crumbs])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.metaKey || e.ctrlKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable) return
      if (e.key === '/') { e.preventDefault(); document.getElementById('globalsearch')?.focus() }
      if (e.key === '[') { e.preventDefault(); toggleRail() }
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [collapsed, setCollapsed, roomy, openNarrow]) // eslint-disable-line react-hooks/exhaustive-deps
  // pages reached by older links light up the entry that replaced them: /prep is Meetings, /commitments and /decisions are Open items
  const alias: Record<string, string> = { '/strategy': '/initiatives', '/companies': '/people', '/company': '/people', '/prep': '/meetings', '/commitments': '/tasks', '/decisions': '/tasks', '/loops': '/tasks', '/actions': '/tasks', '/action-types': '/agents' }   // Tasks replaced Actions and Open items (22 Oct 2026)
  const at = alias[path] ?? (path.startsWith('/topics/') ? (pinned.some((t) => path === `/topics/${t.id}`) ? path : '/initiatives') : path.startsWith('/companies/') ? '/people' : path === '/soul' || path.startsWith('/soul/') ? '/agents' : path)   // Soul and Action types are tabs of Agents   // a company page is under Relationships (Relationships › Companies)
  const active = (to: string) => (to === '/company' ? path === '/company' : to === '/' ? path === '/' : at === to || at.startsWith(to + '/'))
  return (
    <ChatProvider>
      <div className="min-h-screen pt-12">
        <header className="fixed inset-x-0 top-0 z-40 grid h-12 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-line bg-panel px-3 md:grid-cols-[1fr_minmax(0,560px)_1fr] md:px-4">
          <div className="flex items-center gap-3"><button className="grid size-8 place-items-center rounded-full text-ink2 hover:bg-panel2 hover:text-ink md:hidden" aria-label="Menu" onClick={() => setMenu(!menu)}><Menu size={16} aria-hidden /></button>
          <Link to="/" className="flex shrink-0 items-center gap-2 text-ink no-underline">
            <Logo size={28} className="shrink-0" />
            <span className="hidden font-brand text-[16px] font-semibold tracking-[-0.02em] sm:inline">{APP}</span>
          </Link></div>
          <HeaderSearch />
          <div className="flex items-center justify-end gap-2">
            <DemoPill />
            <ThemeToggle />
            <LivePill />
            <RefreshButton live={live} />
            <AccountMenu />
          </div>
        </header>
        <div>
          {menu && <div className="fixed inset-0 top-12 z-20 bg-black/30 md:hidden" onClick={() => setMenu(false)} />}
          <aside id="sidebar" onMouseOver={rail ? showTip : undefined} onFocus={rail ? showTip : undefined} onMouseLeave={() => placeTip(null)} onBlur={() => placeTip(null)}
            className={cn('fixed bottom-0 left-0 top-12 z-30 w-[min(300px,85vw)] flex-col border-r border-line bg-panel shadow-2xl md:fixed md:bottom-0 md:top-12 md:z-20 md:flex md:shadow-none', rail ? 'md:w-14' : 'md:w-[250px]', menu ? 'flex' : 'hidden')}>
            {rail ? <nav aria-label="Sections" onScroll={() => tipFor.current && placeTip(tipFor.current)} className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1.5">
              {NAV.map((g, gi) => (
                <div key={g.group} className={gi ? 'mt-1.5 border-t border-line2 pt-1.5' : 'mt-1'}>
                  {navLinks(g).map((it) => {
                    const on = active(it.to)
                    const working = it.to === '/agents' ? !!agents.data?.running.length : agents.data?.busy_pages.includes(it.to)
                    const n = it.count ? meta.data?.counts[it.count] : undefined
                    return (
                      <Link key={it.to} to={it.to} aria-label={it.label} aria-current={on ? 'page' : undefined} data-tip={it.label}
                        data-tip-sub={working ? 'working…' : it.badge && badges[it.badge] ? badgeTip(it.badge, badges[it.badge]) : n?.toLocaleString()}
                        className={cn('relative flex h-9 w-full items-center justify-center border-l-2 no-underline', on ? 'border-accent bg-accentbg text-ink' : 'border-transparent text-ink3 hover:bg-panel2 hover:text-ink')}>
                        <it.icon aria-hidden size={17} strokeWidth={on ? 2.25 : 1.75} />
                        {working && <span aria-label="an agent is working" className="absolute right-2.5 top-1.5 size-1.5 animate-pulse rounded-full bg-accent ring-1 ring-ink/30" />}
                        {it.badge && badges[it.badge] > 0 && <span aria-label={badgeTip(it.badge, badges[it.badge])} className={cn('absolute right-1 top-0.5 min-w-[16px] rounded-full px-1 text-center text-[10px] font-semibold leading-[16px] tabular-nums', badgeTone(it.badge))}>{badges[it.badge]}</span>}
                      </Link>)
                  })}
                  {g.group === 'Work' && pinned.length > 0 && <div className="mt-1.5 border-t border-line2 pt-1.5" aria-label="Pinned topics">
                    {pinned.map((t) => { const on = path === `/topics/${t.id}`
                      return <Link key={t.id} to="/topics/$id" params={{ id: String(t.id) }} aria-label={`Pinned: ${t.title}`} aria-current={on ? 'page' : undefined}
                        data-tip={t.title} data-tip-sub={t.initiative ?? 'Pinned topic'}
                        className={cn('flex h-9 w-full items-center justify-center border-l-2 no-underline', on ? 'border-accent bg-accentbg text-ink' : 'border-transparent text-ink3 hover:bg-panel2 hover:text-ink')}>
                        <Pin aria-hidden size={16} strokeWidth={on ? 2.25 : 1.75} className={cn(on && 'fill-current')} /></Link> })}
                  </div>}
                </div>))}
            </nav> : <>
            <nav className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1.5 pr-3">
              {NAV.map((g) => {
                const shut = !!g.fold && (folded[g.group] ?? !!g.foldDefault) && !navLinks(g).some((it) => active(it.to))
                const isBusy = (it: NavLink) => (it.to === '/agents' ? !!agents.data?.running.length : !!agents.data?.busy_pages.includes(it.to))
                const busy = navLinks(g).some(isBusy)
                const row = (it: NavLink, inSub = false) => (
                  <Link key={it.to} to={it.to} className={cn('flex items-center gap-2.5 border-l-2 py-[5px] pr-2.5 text-[13.5px] no-underline', inSub ? 'pl-7' : 'pl-2.5', active(it.to) ? 'border-accent bg-accentbg font-medium text-ink' : 'border-transparent text-ink2 hover:bg-panel2 hover:text-ink')}>
                    <it.icon aria-hidden size={15} strokeWidth={active(it.to) ? 2.25 : 1.75} className={cn('shrink-0', active(it.to) ? 'text-ink' : 'text-ink3')} />{it.label}
                    {isBusy(it) && <Loader2 aria-label="an agent is working" size={13} className={cn('shrink-0 animate-spin text-ink2', !it.count && 'ml-auto')} />}
                    {it.count && meta.data && <small className="ml-auto text-[11.5px] font-normal tabular-nums text-ink3">{meta.data.counts[it.count]?.toLocaleString()}</small>}
                    {it.badge && badges[it.badge] > 0 && <span title={badgeTip(it.badge, badges[it.badge])} aria-label={badgeTip(it.badge, badges[it.badge])}
                      className={cn('min-w-[18px] rounded-full px-1.5 text-center text-[11px] font-semibold leading-[18px] tabular-nums', badgeTone(it.badge), !isBusy(it) && 'ml-auto')}>{badges[it.badge]}</span>}
                  </Link>)
                const pins = g.group === 'Work' && pinned.length > 0 && (
                  <div key="pinned" className="mt-3" aria-label="Pinned topics">
                    <h5 className="mx-3 mb-0.5 py-0.5 text-[12.5px] font-semibold text-ink">Pinned</h5>
                    {pinned.map((t) => { const on = path === `/topics/${t.id}`
                      return (
                        <div key={t.id} className="group relative">
                          <Link to="/topics/$id" params={{ id: String(t.id) }} title={t.initiative ? `${t.title} · ${t.initiative}` : t.title}
                            className={cn('flex items-center gap-2.5 border-l-2 py-[5px] pl-2.5 pr-8 text-[13.5px] no-underline', on ? 'border-accent bg-accentbg font-medium text-ink' : 'border-transparent text-ink2 hover:bg-panel2 hover:text-ink')}>
                            <Pin aria-hidden size={15} strokeWidth={on ? 2.25 : 1.75} className={cn('shrink-0', on ? 'fill-current text-ink' : 'text-ink3')} />
                            <span className="min-w-0 truncate">{t.title}</span>
                          </Link>
                          <button onClick={() => void unpin(t.id)} aria-label={`Unpin ${t.title}`} title="Unpin"
                            className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-ink3 opacity-0 transition hover:bg-panel2 hover:text-ink focus:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100"><X size={13} aria-hidden /></button>
                        </div>)
                    })}
                  </div>)
                return [
                  <div key={g.group} className={g.label === false ? 'mt-1' : 'mt-3'}>
                    {g.label !== false && (g.fold
                      ? <button onClick={() => setFolded({ ...folded, [g.group]: !shut })} aria-expanded={!shut}
                          className="group mx-1.5 mb-0.5 flex w-[calc(100%-0.375rem)] items-center gap-1 px-1.5 py-0.5 text-left text-[12.5px] font-semibold text-ink hover:bg-panel2">
                          <span className="flex-1">{g.group}</span>
                          {shut && busy && <Loader2 aria-label="an agent is working in this section" size={12} className="animate-spin text-ink2" />}
                          {shut ? <ChevronRight size={14} className="text-ink3 group-hover:text-ink" aria-hidden /> : <ChevronDown size={14} className="text-ink3 group-hover:text-ink" aria-hidden />}
                        </button>
                      : <h5 className="mx-3 mb-0.5 py-0.5 text-[12.5px] font-semibold text-ink">{g.group}</h5>)}
                    {!shut && g.items.map((e) => {
                      if (!isSub(e)) return row(e)
                      const key = `${g.group}/${e.label}`, here = e.items.some((it) => active(it.to))
                      const closed = !!folded[key] && !here
                      return (
                        <div key={key}>
                          <button onClick={() => setFolded({ ...folded, [key]: !closed })} aria-expanded={!closed}
                            className={cn('group flex w-full items-center gap-2.5 border-l-2 border-transparent py-[5px] pl-2.5 pr-1.5 text-left text-[13.5px] hover:bg-panel2 hover:text-ink', here ? 'font-medium text-ink' : 'text-ink2')}>
                            <e.icon aria-hidden size={15} strokeWidth={here ? 2.25 : 1.75} className={cn('shrink-0', here ? 'text-ink' : 'text-ink3')} />
                            <span className="flex-1">{e.label}</span>
                            {closed && e.items.some(isBusy) && <Loader2 aria-label="an agent is working in this list" size={12} className="animate-spin text-ink2" />}
                            {closed ? <ChevronRight size={14} className="text-ink3 group-hover:text-ink" aria-hidden /> : <ChevronDown size={14} className="text-ink3 group-hover:text-ink" aria-hidden />}
                          </button>
                          {!closed && e.items.map((it) => row(it, true))}
                        </div>)
                    })}
                  </div>, pins]
              })}
            </nav></>}
            {/* The sidebar's own fold control (Sam, 16 Nov 2026: out of the header, "in the sidebar itself in the bottom left-hand
                corner"). Pinned under the scrolling nav, in the same spot folded and open (so a second click undoes the first) and in
                line with the icons above it; [ does the same. Not in the phone drawer, which the header's menu button opens. */}
            <div className="hidden shrink-0 border-t border-line2 py-1.5 md:block">
              <button onClick={toggleRail} aria-controls="sidebar" aria-expanded={!rail} aria-label={rail ? 'Expand the sidebar' : 'Collapse the sidebar'}
                title={rail ? undefined : 'Collapse the sidebar ([)'} data-tip={rail ? 'Expand the sidebar' : undefined} data-tip-sub={rail ? '[' : undefined}
                className={cn('grid size-8 place-items-center rounded-full text-ink3 hover:bg-panel2 hover:text-ink', rail ? 'mx-auto' : 'ml-1')}>
                {rail ? <PanelLeftOpen size={17} aria-hidden /> : <PanelLeftClose size={17} aria-hidden />}
              </button>
            </div>
          </aside>
          {/^\/(inbox|messages|documents|assistant|live)(\/|$)/.test(path)
            // Mail-client pages, the Assistant and a live call fill the whole area beside the sidebar: their own panes scroll, the page does not.
            ? <main className={cn('flex h-[calc(100dvh-3rem)] min-w-0 flex-col overflow-hidden', rail ? 'md:ml-14' : 'md:ml-[250px]')}><BackLine flush /><SetupBar />{children ?? <Outlet />}</main>
            // Meetings has no breadcrumb trail (Sam, 22 Oct 2026: superfluous; its toolbar is the top of the page). A transcript keeps it.
            // Meetings uses the width a wide window has (Sam, 22 Oct 2026): the mini calendar sits beside the grid
            // Meetings and the Explore graph are a fixed canvas with margins (Sam, 22 Oct 2026): the page does not scroll at all (no
            // fallback scroll either: a few pixels over made it bounce), the calendar or graph fills the window and scrolls inside
            // itself. Other pages are documents and scroll as a whole, without the rubber-band bounce (index.css).
            : <main className={cn('min-w-0 px-3 pt-3 md:px-7 md:pt-4', /^\/(meetings|prep|explore\/graph)\/?$/.test(path) ? 'flex h-[calc(100dvh-3rem)] flex-col overflow-hidden pb-3 md:pb-4' : 'pb-24',
              /^\/(meetings|prep)\/?$/.test(path) ? 'max-w-[1800px]' : 'max-w-[1490px] md:max-w-[1240px]', rail ? 'md:ml-14' : 'md:ml-[250px]')}>{/^\/(account|settings)\/?$/.test(path) ? null : !/^\/(meetings|prep)\/?$/.test(path) ? <Breadcrumbs crumbs={crumbs} /> : <BackLine />}{/^\/settings\/?$/.test(path) ? null : <SetupBar />}{children ?? <Outlet />}</main>}
          {rail && tip && (
            <div role="tooltip" key={tip.text} style={{ top: tip.top, left: tip.left }}
              className="rail-tip pointer-events-none fixed z-50 flex -translate-y-1/2 items-baseline gap-2 whitespace-nowrap border border-onaccent bg-accent py-1 pl-2.5 pr-3 text-[13px] font-semibold leading-tight text-onaccent shadow-[3px_3px_0_0_var(--color-onaccent)]">
              <span aria-hidden className="absolute -left-[5px] top-1/2 size-2 -translate-y-1/2 rotate-45 border-b border-l border-onaccent bg-accent" />
              {tip.text}{tip.sub && <span className="text-[12px] font-normal tabular-nums opacity-70">{tip.sub}</span>}
            </div>)}
          <DocViewerHost />
          <ChatHost />
          <EntityPanelHost />
        </div>
      </div>
    </ChatProvider>
  )
}
