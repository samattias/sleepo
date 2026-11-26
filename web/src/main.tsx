import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createHashHistory, createRootRoute, createRoute, createRouter, Outlet, redirect, RouterProvider, useNavigate, useRouterState } from '@tanstack/react-router'
import './index.css'
import { api, type Meta } from '@/lib/api'
import { setProfile } from '@/lib/profile'
import { configure } from '@/lib/time'
import { Layout } from '@/components/Layout'
import { ActionsPage } from '@/views/actions'
import { InitiativePage, InitiativesPage } from '@/views/initiatives'
import { TopicPage } from '@/views/topic'
import { SoulPage, MeRedirect, People, PersonPage } from '@/views/knowledge'
import { MemoryPage } from '@/views/memory'
import { Personalisation } from '@/views/settings'
import { AccountPage } from '@/views/account'
import { SetupPage, STEPS, type Step } from '@/views/setup'
import { Companies, CompanyPage, OursRedirect } from '@/views/companies'
import { LivePage } from '@/views/live'
import { MeetingsHub } from '@/views/meetings-hub'
import { Assistant } from '@/views/assistant'
import { TranscriptPage } from '@/views/transcript'
import { LinksPage } from '@/views/links'
import { Sources, SourcePage } from '@/views/system'
import { SearchPage } from '@/views/search'
import { Explore } from '@/views/explore'
import { PERSON_TABS, type PersonTab } from '@/components/PersonPage'
import { Documents } from '@/views/documents'
import { Inbox } from '@/views/inbox'
import { Messages } from '@/views/messages'
import { Tasks } from '@/views/tasks'
import { Agents } from '@/views/agents'
import { Loops } from '@/views/loops'
import { Roadmap } from '@/views/roadmap'
import { CodeBase } from '@/views/code'
import { ActionTypes } from '@/views/action-types'
import { Pipeline } from '@/views/pipeline'
import { Retention } from '@/views/retention'

try { const t = localStorage.getItem('assist-theme'); if (t) document.documentElement.dataset.theme = t } catch { /* ignore */ }

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } } })

// First-run setup (/welcome, views/setup.tsx) is a page of its own, without the sidebar; it opens by itself while SleePO does
// not know who the user is and setup was never finished or skipped (a new install, or the demo copy: assist/demo.py).
function Root() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const nav = useNavigate()
  const setup = (qc.getQueryData(['meta']) as Meta | undefined)?.setup
  useEffect(() => { if (setup?.needed && !setup.done && path !== '/welcome') nav({ to: '/welcome', search: { step: 'welcome' } }) }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  return path === '/welcome' ? <Outlet /> : <Layout />
}
const rootRoute = createRootRoute({ component: Root })
// Actions replaced Today, the widget board, as the first page (Sam, 25 Nov 2026; views/actions.tsx)
const todayRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: ActionsPage })
const assistantRoute = createRoute({ getParentRoute: () => rootRoute, path: '/assistant', component: Assistant })
// Tasks replaced Actions, Commitments and Decisions (22 Oct 2026): old links land on Tasks; Open items (/loops) stays a page
const commitmentsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/commitments', beforeLoad: () => { throw redirect({ to: '/tasks' }) } })
const decisionsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/decisions', beforeLoad: () => { throw redirect({ to: '/tasks' }) } })
const initiativesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/initiatives', component: InitiativesPage })
const topicRoute = createRoute({ getParentRoute: () => rootRoute, path: '/topics/$id', validateSearch: (s: Record<string, unknown>): { open?: string } => ({ open: s.open ? String(s.open) : undefined }),   // a top-of-mind topic (29 Oct 2026)
  component: function TopicRoute() { const { id } = topicRoute.useParams(); const { open } = topicRoute.useSearch(); return <TopicPage key={id} id={Number(id)} open={open} /> } })
const initiativeRoute = createRoute({ getParentRoute: () => rootRoute, path: '/initiatives/$slug', validateSearch: (s: Record<string, unknown>): { open?: string } => ({ open: s.open ? String(s.open) : undefined }),
  component: function InitiativeRoute() { const { slug } = initiativeRoute.useParams(); const { open } = initiativeRoute.useSearch(); return <InitiativePage key={slug} slug={slug} open={open} /> } })
const meRoute = createRoute({ getParentRoute: () => rootRoute, path: '/me', component: MeRedirect })
const companyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/company', component: OursRedirect })   // the Company page became Acme's company page (People › Companies)
const companiesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/companies', component: Companies })
const oneCompanyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/companies/$id', component: function OneCompany() { const { id } = oneCompanyRoute.useParams(); return <CompanyPage id={Number(id)} /> } })
const soulRoute = createRoute({ getParentRoute: () => rootRoute, path: '/soul', component: () => <SoulPage tab="company" /> })
const soulSleepoRoute = createRoute({ getParentRoute: () => rootRoute, path: '/soul/sleepo', component: () => <SoulPage tab="sleepo" /> })
const soulCpoRoute = createRoute({ getParentRoute: () => rootRoute, path: '/soul/cpo', component: () => <SoulPage tab="cpo" /> })
const calendarRoute = createRoute({ getParentRoute: () => rootRoute, path: '/calendar', beforeLoad: () => { throw redirect({ to: '/meetings' }) } })
const meetingsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/meetings', validateSearch: (s: Record<string, unknown>): { open?: string } => ({ open: s.open ? String(s.open) : undefined }), component: function MeetingsRoute() { const { open } = meetingsRoute.useSearch(); return <MeetingsHub tab="calendar" open={open} /> } })
const liveRoute = createRoute({ getParentRoute: () => rootRoute, path: '/live', validateSearch: (s: Record<string, unknown>): { event?: string; note?: string } => ({ event: s.event ? String(s.event) : undefined, note: s.note ? String(s.note) : undefined }),
  component: function LiveRoute() { const { event, note } = liveRoute.useSearch(); return <LivePage key={`${event}-${note}`} event={event} note={note} /> } })   // a call in progress (26 Oct 2026)
const peopleRoute = createRoute({ getParentRoute: () => rootRoute, path: '/people', component: People })
const linksRoute = createRoute({ getParentRoute: () => rootRoute, path: '/links', component: LinksPage })
const personRoute = createRoute({ getParentRoute: () => rootRoute, path: '/people/$id', validateSearch: (s: Record<string, unknown>): { tab?: PersonTab } => ({ tab: PERSON_TABS.includes(s.tab as PersonTab) ? s.tab as PersonTab : undefined }),
  component: function PersonRoute() { const { id } = personRoute.useParams(); const { tab } = personRoute.useSearch(); return <PersonPage id={id} tab={tab} /> } })
// Inbox = the old Replies (Work) and Emails (Knowledge) pages in one. Their addresses redirect, so links to them keep working.
const openSearch = (s: Record<string, unknown>): { open?: number } => ({ open: s.open ? Number(s.open) : undefined })
// ?draft=: the draft open in Inbox › Drafts (views/inbox/drafts.tsx)
const inboxRoute = createRoute({ getParentRoute: () => rootRoute, path: '/inbox', validateSearch: (s: Record<string, unknown>): { open?: number; draft?: string } => ({ ...openSearch(s), draft: s.draft ? String(s.draft) : undefined }),
  component: function InboxRoute() { const { open, draft } = inboxRoute.useSearch(); return <Inbox open={open} draft={draft} /> } })
const repliesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/replies', validateSearch: openSearch, beforeLoad: ({ search }) => { throw redirect({ to: '/inbox', search }) } })
const prepRoute = createRoute({ getParentRoute: () => rootRoute, path: '/prep', validateSearch: (s: Record<string, unknown>): { event?: string } => ({ event: s.event ? String(s.event) : undefined }),
  component: function PrepRoute() { const { event } = prepRoute.useSearch(); return <MeetingsHub tab="upcoming" event={event} /> } })
const documentsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/documents', validateSearch: (s: Record<string, unknown>): { open?: string } => ({ open: s.open ? String(s.open) : undefined }), component: function DocumentsRoute() { const { open } = documentsRoute.useSearch(); return <Documents open={open} /> } })
const transcriptRoute = createRoute({ getParentRoute: () => rootRoute, path: '/meetings/$id', validateSearch: (s: Record<string, unknown>): { q?: string; t?: number } => ({ q: s.q ? String(s.q) : undefined, t: s.t != null && !isNaN(Number(s.t)) ? Number(s.t) : undefined }), component: function TranscriptRoute() { const { id } = transcriptRoute.useParams(); const { q, t } = transcriptRoute.useSearch(); return <TranscriptPage id={id} q={q} at={t} /> } })
const mailRoute = createRoute({ getParentRoute: () => rootRoute, path: '/mail', validateSearch: openSearch, beforeLoad: ({ search }) => { throw redirect({ to: '/inbox', search }) } })
const pipelineRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pipeline', component: Pipeline })
const retentionRoute = createRoute({ getParentRoute: () => rootRoute, path: '/retention', component: Retention })
const agentsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/agents', component: Agents })
const todoRoute = createRoute({ getParentRoute: () => rootRoute, path: '/actions', beforeLoad: () => { throw redirect({ to: '/' }) } })   // the Actions page is the first page (25 Nov 2026)
// Tasks (22 Oct 2026) replaced Actions and Open items in the menu; /actions and /loops stay reachable by link
const tasksRoute = createRoute({ getParentRoute: () => rootRoute, path: '/tasks', validateSearch: openSearch, component: function TasksRoute() { const { open } = tasksRoute.useSearch(); return <Tasks open={open} /> } })
const actionTypesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/action-types', component: ActionTypes })
const memoryRoute = createRoute({ getParentRoute: () => rootRoute, path: '/memory', component: MemoryPage })   // what SleePO remembers (assist/remember.py)
const strategyRoute = createRoute({ getParentRoute: () => rootRoute, path: '/strategy', beforeLoad: () => { throw redirect({ to: '/initiatives' }) } })   // Strategy page removed (29 Oct 2026)
const codeRoute = createRoute({ getParentRoute: () => rootRoute, path: '/code', validateSearch: (s: Record<string, unknown>): { q?: string } => ({ q: s.q ? String(s.q) : undefined }),
  component: function CodeRoute() { const { q } = codeRoute.useSearch(); return <CodeBase q={q} /> } })
const roadmapRoute = createRoute({ getParentRoute: () => rootRoute, path: '/roadmap', validateSearch: (s: Record<string, unknown>): { item?: string } => ({ item: s.item ? String(s.item) : undefined }),
  component: function RoadmapRoute() { const { item } = roadmapRoute.useSearch(); return <Roadmap item={item} /> } })
const loopsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/loops', validateSearch: openSearch, component: function LoopsRoute() { const { open } = loopsRoute.useSearch(); return <Loops open={open} /> } })
const messagesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/messages', validateSearch: (s: Record<string, unknown>): { open?: number; review?: number } => ({ ...openSearch(s), review: Number(s.review) || undefined }), component: function MessagesRoute() { const { open, review } = messagesRoute.useSearch(); return <Messages open={open} review={review} /> } })
// Explore = graph + library. The old /graph and /library addresses redirect so existing links keep working.
const exploreRoute = createRoute({ getParentRoute: () => rootRoute, path: '/explore', beforeLoad: () => { throw redirect({ to: '/explore/graph', search: { focus: undefined } }) } })
const exploreGraphRoute = createRoute({ getParentRoute: () => rootRoute, path: '/explore/graph', validateSearch: (s: Record<string, unknown>) => ({ focus: s.focus ? String(s.focus) : undefined }),
  component: function ExploreGraph() { const { focus } = exploreGraphRoute.useSearch(); return <Explore view="graph" focus={focus} /> } })
const exploreLibraryRoute = createRoute({ getParentRoute: () => rootRoute, path: '/explore/library', component: () => <Explore view="library" /> })
const exploreDocRoute = createRoute({ getParentRoute: () => rootRoute, path: '/explore/library/$', component: function ExploreDoc() { const { _splat } = exploreDocRoute.useParams(); return <Explore view="library" doc={_splat} /> } })
const graphRoute = createRoute({ getParentRoute: () => rootRoute, path: '/graph', beforeLoad: () => { throw redirect({ to: '/explore/graph', search: { focus: undefined } }) } })
const libraryRoute = createRoute({ getParentRoute: () => rootRoute, path: '/library', beforeLoad: () => { throw redirect({ to: '/explore/library' }) } })
const docRoute = createRoute({ getParentRoute: () => rootRoute, path: '/library/$', beforeLoad: ({ params }) => { throw redirect({ to: '/explore/library/$', params: { _splat: params._splat } }) } })
const sourcesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/sources', component: Sources })
const sourceRoute = createRoute({ getParentRoute: () => rootRoute, path: '/sources/$id', component: function SourceRoute() { const { id } = sourceRoute.useParams(); return <SourcePage id={id} /> } })
const searchRoute = createRoute({ getParentRoute: () => rootRoute, path: '/search', validateSearch: (s: Record<string, unknown>) => ({ q: String(s.q ?? '') }), component: function SearchRoute() { const { q } = searchRoute.useSearch(); return <SearchPage q={q} /> } })

const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/settings', component: Personalisation })   // Account › Personalisation
const accountRoute = createRoute({ getParentRoute: () => rootRoute, path: '/account', component: AccountPage })   // the account menu, top right
const welcomeRoute = createRoute({ getParentRoute: () => rootRoute, path: '/welcome', validateSearch: (s: Record<string, unknown>): { step?: Step } => ({ step: STEPS.includes(s.step as Step) ? s.step as Step : undefined }),
  component: function WelcomeRoute() { const { step } = welcomeRoute.useSearch(); return <SetupPage step={step} /> } })   // first-run setup
const routeTree = rootRoute.addChildren([settingsRoute, accountRoute, welcomeRoute, assistantRoute, tasksRoute, actionTypesRoute, memoryRoute, strategyRoute, roadmapRoute, codeRoute, agentsRoute, loopsRoute, pipelineRoute, retentionRoute, soulSleepoRoute, soulCpoRoute, todoRoute, inboxRoute, repliesRoute, soulRoute, transcriptRoute, prepRoute, documentsRoute, exploreRoute, exploreGraphRoute, exploreLibraryRoute, exploreDocRoute, mailRoute, messagesRoute, graphRoute, todayRoute, commitmentsRoute, decisionsRoute, initiativesRoute, initiativeRoute, topicRoute, meRoute, companyRoute, calendarRoute, meetingsRoute, liveRoute,
  peopleRoute, companiesRoute, oneCompanyRoute, linksRoute, personRoute, libraryRoute, docRoute, sourcesRoute, sourceRoute, searchRoute])
const router = createRouter({ routeTree, history: createHashHistory(), defaultPreload: 'intent' })
declare module '@tanstack/react-router' { interface Register { router: typeof router } }

const render = () => createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)

// The user's profile first (16 Nov 2026): times are shown in their zone and "me" is them, from the first render on.
api.meta().then((m) => {
  setProfile(m.profile, m.org)
  configure(m.profile?.timezone, m.profile?.locale)
  qc.setQueryData(['meta'], m)
}).catch(() => { /* the server is down: render anyway, the pages say so */ }).finally(render)
