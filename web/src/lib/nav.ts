// Back navigation across the app (Sam, 22 Oct 2026: "when I click on the person in a Teams message it takes me to their
// page but I cannot go back to the message").
//
// 1. The header's Back button (components/Layout.tsx BackButton) goes back one step in the browser history and says where
//    to ("← Messages · Indigo Ellison"). Each history entry's page name is remembered by its position (the router's
//    __TSR_index), in sessionStorage, so the label survives reloads and works after going back and forward.
// 2. Pages keep what is selected in the address (useSearchSync), replacing the current entry rather than adding one, so
//    going back lands on the same email, message, task or meeting, not just the same page.
// 3. Pages may name what is open (usePageTitle), which the Back label shows.
import { useEffect, useRef, useState } from 'react'
import { useRouter, useRouterState } from '@tanstack/react-router'

type Entry = { href: string; title: string; detail?: string }   // detail: what that page had open (usePageTitle)
const STORE = 'assist-nav'
const read = (): Record<string, Entry> => { try { return JSON.parse(sessionStorage.getItem(STORE) || '{}') } catch { return {} } }
const write = (m: Record<string, Entry>) => { try { sessionStorage.setItem(STORE, JSON.stringify(m)) } catch { /* storage off */ } }

const PAGES: Record<string, string> = {
  '': 'Today', today: 'Today', inbox: 'Inbox', mail: 'Inbox', replies: 'Inbox', messages: 'Messages', people: 'Relationships', meetings: 'Meetings',
  prep: 'Meeting prep', tasks: 'Tasks', actions: 'Actions', loops: 'Open items', documents: 'Documents', roadmap: 'Roadmap', pipeline: 'Pipeline',
  retention: 'Retention', strategy: 'Strategy', initiatives: 'Initiatives', topics: 'Top of mind', explore: 'Explore', search: 'Search', assistant: 'Assistant',
  agents: 'Agents', soul: 'Soul', company: 'Company', me: 'Me', knowledge: 'Knowledge', sources: 'Sources', 'action-types': 'Action types', memory: 'Memory',
}
export function pageName(path: string) {
  const seg = path.replace(/^\/+/, '').split('/')[0] ?? ''
  if (seg === 'meetings' && path.split('/').length > 2) return 'Meeting'
  if (seg === 'people' && path.split('/').length > 2) return 'Person'
  return PAGES[seg] ?? seg.replace(/-/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

let detail = ''   // what the current page has open, named by usePageTitle
function idx(state: unknown) { const i = (state as { __TSR_index?: number } | undefined)?.__TSR_index; return typeof i === 'number' ? i : null }

// Records the page at each history position; Layout mounts it once.
export function useNavRecorder() {
  const loc = useRouterState({ select: (s) => s.location })
  useEffect(() => {
    const i = idx(loc.state)
    if (i == null) return
    const m = read()
    detail = ''
    // the page's own name for what it has open may already be there (child effects run first): keep it on the same page
    const keep = m[i] && m[i].href.split('?')[0] === loc.href.split('?')[0] ? m[i].detail : undefined
    m[i] = { href: loc.href, title: pageName(loc.pathname), detail: keep }
    write(m)
  }, [loc.href, loc.state]) // eslint-disable-line react-hooks/exhaustive-deps
}

// A page names what it has open ("Indigo Ellison", the email's subject): the Back label of the next page shows it.
export function usePageTitle(title: string | null | undefined) {
  const state = useRouterState({ select: (s) => s.location.state })
  useEffect(() => {
    const i = idx(state)
    if (i == null || !title) return
    detail = title
    const m = read()
    const href = window.location.hash.replace(/^#/, '')
    m[i] = { ...(m[i] ?? { href, title: pageName(href.split('?')[0]) }), detail: title.slice(0, 60) }
    write(m)
  }, [title, state])
}

// Where Back goes: the previous history entry's page, or null at the start.
export function useBackTarget(): Entry | null {
  const state = useRouterState({ select: (s) => s.location.state })
  const [t, setT] = useState<Entry | null>(null)
  useEffect(() => {
    const i = idx(state)
    if (i == null || i <= 0) { setT(null); return }
    const prev = read()[i - 1]
    setT(prev ? { ...prev, title: prev.detail ? `${prev.title} · ${prev.detail}` : prev.title } : { href: '', title: 'Back' })
  }, [state])
  return t
}

// Keeps one search parameter in step with a page's selection, replacing the current history entry (no new entry per
// click), so Back returns to the same item. value null or '' removes the parameter.
export function useSearchSync(key: string, value: string | number | null | undefined) {
  const router = useRouter()
  const current = useRouterState({ select: (s) => (s.location.search as Record<string, unknown>)[key] })
  const mounted = useRef(false)
  useEffect(() => {
    // not on arrival: the page has not read the address yet, and its empty first selection would wipe ?open=
    if (!mounted.current) { mounted.current = true; return }
    const v = value == null || value === '' ? undefined : value
    if (String(current ?? '') === String(v ?? '')) return
    router.navigate({ to: '.', search: ((prev: Record<string, unknown>) => ({ ...prev, [key]: v })) as never, replace: true, resetScroll: false } as never)
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps
}

export const _detail = () => detail
