import { useEffect, useState } from 'react'
import type { QueryClient } from '@tanstack/react-query'

// Server-sent events from FastAPI: 'data' when the database changes -> refetch every active query;
// 'code' when the built app changes -> reload (in dev, Vite's hot reload handles code instead).
//
// One connection for every SleePO tab (Sam, 19 Nov 2026: "when the AI assistant is loading, I can't access other
// functionality in the app because it's in a loading state"). Chrome opens at most 6 connections to one site, shared by
// all its tabs. Each tab's EventSource held one for good and an Ask SleePO answer holds another until it ends, so with
// five tabs open an answer left none, and every request in every tab waited for it (measured: with 6 held, /api/meta was
// still waiting after 8 s; with 5, 21 ms). Now the tab holding the Web Lock 'sleepo-live' keeps /api/events open and
// passes its events to the other tabs on a BroadcastChannel; when it closes, another tab takes the lock and opens it.
// A tab in the background marks its data stale on a change and refetches when it is shown again, so the open tab's
// requests do not queue behind every hidden tab's.
type Msg = { type: 'hello'; v: string } | { type: 'code' } | { type: 'data' } | { type: 'state'; s: 'live' | 'reconnecting' } | { type: 'ask' }

export function useLive(qc: QueryClient) {
  const [state, setState] = useState<'live' | 'reconnecting'>('reconnecting')
  useEffect(() => {
    if (location.search.includes('nolive')) return
    let first: string | null = null
    let now: 'live' | 'reconnecting' = 'reconnecting'
    let t: number | undefined
    let missed = false
    // one round of refetches at a time (6 Nov 2026): a new round cancelled the one in flight and started every query again,
    // so while a job wrote the requests piled up and the app froze. Waits up to 15 s for the last round, then goes anyway.
    let waits = 0
    const refetch = () => {
      if (document.hidden) { missed = true; qc.invalidateQueries({ refetchType: 'none' }); return }
      if (qc.isFetching() && waits++ < 15) { t = window.setTimeout(refetch, 1000); return }
      waits = 0
      qc.invalidateQueries()
    }
    const shown = () => { if (!document.hidden && missed) { missed = false; refetch() } }
    document.addEventListener('visibilitychange', shown)

    let es: EventSource | null = null
    let lead = false
    let ch: BroadcastChannel | null = null
    const on = (m: Msg) => {
      if (m.type === 'hello') {
        if (first && first !== m.v && !import.meta.env.DEV) location.reload()
        first = m.v
        now = 'live'
        setState('live')
      } else if (m.type === 'code') {
        if (!import.meta.env.DEV) location.reload()
      } else if (m.type === 'data') {
        clearTimeout(t)
        t = window.setTimeout(refetch, 300)
      } else if (m.type === 'state') {
        now = m.s
        setState(m.s)
      } else if (m.type === 'ask' && lead) {   // a tab just opened: tell it where things stand
        if (first) ch?.postMessage({ type: 'hello', v: first } satisfies Msg)
        ch?.postMessage({ type: 'state', s: now } satisfies Msg)
      }
    }
    const connect = (send: (m: Msg) => void) => {
      es = new EventSource('/api/events')
      es.addEventListener('hello', (e) => send({ type: 'hello', v: (e as MessageEvent).data }))
      es.addEventListener('code', () => send({ type: 'code' }))
      es.addEventListener('data', () => send({ type: 'data' }))
      es.onopen = () => send({ type: 'state', s: 'live' })
      es.onerror = () => send({ type: 'state', s: 'reconnecting' })
    }
    const done = () => { es?.close(); clearTimeout(t); document.removeEventListener('visibilitychange', shown) }

    if (typeof BroadcastChannel === 'undefined' || !navigator.locks) {   // no way to share it: this tab keeps its own
      connect(on)
      return done
    }
    ch = new BroadcastChannel('sleepo-live')
    ch.onmessage = (e: MessageEvent<Msg>) => on(e.data)
    ch.postMessage({ type: 'ask' } satisfies Msg)
    let closed = false
    let release: (() => void) | undefined
    const ctl = new AbortController()
    navigator.locks.request('sleepo-live', { signal: ctl.signal }, () => {
      if (closed) return undefined
      lead = true
      connect((m) => { on(m); ch?.postMessage(m) })
      return new Promise<void>((r) => { release = r })   // held until this tab closes or the page unmounts
    }).catch(() => {})   // AbortError: unmounted while waiting for the lock
    return () => { closed = true; ctl.abort(); release?.(); ch?.close(); done() }
  }, [qc])
  return state
}
