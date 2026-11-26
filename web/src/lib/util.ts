import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
export const cn = (...c: ClassValue[]) => twMerge(clsx(c))
export const ageDays = (d: string, today: string) => { const a = Date.parse(d), b = Date.parse(today); return isNaN(a) || isNaN(b) ? 0 : Math.floor((b - a) / 86400000) }
export const initials = (n: string) => (n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
export const hue = (n: string) => { let h = 0; for (const c of n || '') h = (h * 31 + c.charCodeAt(0)) % 360; return h }
// A value kept in this browser (localStorage) under `key`. Read once per key (not on every render); the setter is stable
// and takes a value or an updater; when `key` changes, the value for the new key is read.
function readPersisted<T>(key: string, init: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw) {
      const saved = JSON.parse(raw)
      // objects merge over the defaults (new fields keep their default); numbers, strings and booleans are taken as saved
      return init !== null && typeof init === 'object' && !Array.isArray(init) ? { ...init, ...saved } : (typeof saved === typeof init ? saved : init)
    }
  } catch { /* storage unavailable */ }
  return init
}
export function usePersisted<T>(key: string, init: T): [T, (v: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<{ key: string; v: T }>(() => ({ key, v: readPersisted(key, init) }))
  const v = state.key === key ? state.v : readPersisted(key, init)
  const keyRef = useRef(key)
  keyRef.current = key
  const set = useCallback((n: T | ((prev: T) => T)) => {
    setState((s) => {
      const k = keyRef.current
      const prev = s.key === k ? s.v : readPersisted(k, init)
      const next = typeof n === 'function' ? (n as (p: T) => T)(prev) : n
      try { localStorage.setItem(k, JSON.stringify(next)) } catch { /* ignore */ }
      return { key: k, v: next }
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return [v, set]
}
import { useCallback, useRef, useState } from 'react'

/** Label for an online-meeting join link. */
export const joinLabel = (url: string) => (/zoom\.us/.test(url) ? 'Join Zoom' : /meet\.google\.com/.test(url) ? 'Join Google Meet' : 'Join Teams meeting')
/** True while a meeting can still be joined: it has not ended yet (end as local "YYYY-MM-DDTHH:MM"). */
export const joinable = (end?: string) => !!end && new Date(end.length === 16 ? end + ':00' : end).getTime() > Date.now()

/** Share of a draft that was changed before it was used (0 = untouched, 1 = rewritten), by words. */
export function editRatio(original: string, final: string) {
  const a = (original || '').toLowerCase().match(/\w+/g) ?? [], b = (final || '').toLowerCase().match(/\w+/g) ?? []
  if (!a.length && !b.length) return 0
  const bag = new Map<string, number>(); a.forEach((w) => bag.set(w, (bag.get(w) ?? 0) + 1))
  let common = 0; b.forEach((w) => { const n = bag.get(w) ?? 0; if (n > 0) { common++; bag.set(w, n - 1) } })
  return Math.round((1 - common / Math.max(a.length, b.length)) * 100) / 100
}


// Dates: the helpers live in lib/time.ts; these names stay for the files that import them from here.
export { dayKey, dayLabel, hm as time } from './time'
