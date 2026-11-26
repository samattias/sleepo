// A background job the server runs (a reply draft, a briefing, a document plan, a task proposal), followed until it ends
// (22 Oct 2026, from the codebase review: seven hand-written polling loops, some of which kept polling after the page was
// left and could run twice). The job id is kept per item (`key`), so coming back to the email picks a running job up;
// polling stops when the component unmounts; onDone / onError run once. A failed check (a server error, or the server
// restarting after a code change) is retried: only the 4th failure in a row gives up, so a finished draft is not lost.
import { useEffect, useRef, useState } from 'react'
import { usePersisted } from './util'

export type JobState = { running: boolean; ok: boolean | null; error?: string | null }

export function useJob<J extends JobState>(key: string, fetchJob: (id: string) => Promise<J>,
  { onDone, onError, every = 2000, timeout = 10 * 60_000 }: { onDone?: (j: J) => void; onError?: (msg: string) => void; every?: number; timeout?: number } = {}) {
  const [id, setId] = usePersisted<string>(key, '')
  const [busy, setBusy] = useState(false)
  const cb = useRef({ onDone, onError })
  cb.current = { onDone, onError }
  useEffect(() => {
    if (!id) { setBusy(false); return }
    let live = true
    setBusy(true)
    const t0 = Date.now()
    let fails = 0
    const tick = async () => {
      if (!live) return
      try {
        const j = await fetchJob(id)
        if (!live) return
        fails = 0
        if (j.running && Date.now() - t0 < timeout) { setTimeout(tick, every); return }
        setId(''); setBusy(false)
        if (j.running) cb.current.onError?.('This is taking too long. Try again.')
        else if (j.ok) cb.current.onDone?.(j)
        else cb.current.onError?.(j.error || 'It stopped without a result.')
      } catch (e) {
        if (!live) return
        if (++fails < 4) { setTimeout(tick, every * 2); return }   // a blip or a restart: look again
        setId(''); setBusy(false)
        cb.current.onError?.(String(e instanceof Error ? e.message : e))
      }
    }
    tick()
    return () => { live = false }
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  /** Follow a job the caller just started. */
  const follow = (jobId: string) => setId(jobId)
  return { busy, follow, jobId: id }
}
