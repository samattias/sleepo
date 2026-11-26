// Live call (Sam, 26 Oct 2026): during a call, the brief on the left and Granola's transcript on the right, growing as people
// speak, with a box under it to ask about the call so far (assist/live_call.py). Granola saves the transcript while it
// records; the page reads it every 10 seconds through the server, which writes nothing. While the call runs the lines are
// labelled by audio source only: Sam (his microphone) and Others (the call's audio). Nothing is stored or sent; the finished
// note comes in with the usual sync.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { format } from 'date-fns'
import { ArrowUp, Loader2, Video } from 'lucide-react'
import { api, type LiveState } from '@/lib/api'
import { cn } from '@/lib/util'
import { usePageTitle } from '@/lib/nav'
import { Loading, Markdown } from '@/components/ui'
import { DictateButton } from '@/components/Dictate'
import { BriefBody } from './prep'
import { toolBtn } from './calendar'
import { isMe } from '@/lib/profile'

const QUICK = ['What was just agreed?', 'What do they want from me?', 'What should I push back on?', 'Summarise the last 5 minutes']
type QA = { q: string; a: string; error?: string; running?: boolean }

const ago = (iso: string | null, now: number) => {
  if (!iso) return ''
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  return s < 60 ? `${s} s ago` : `${Math.round(s / 60)} min ago`
}

export function LivePage({ event, note }: { event?: string; note?: string }) {
  const [pick, setPick] = useState(note)
  const q = useQuery({ queryKey: ['live', event, pick], queryFn: () => api.live(event, pick), refetchInterval: 10000, refetchIntervalInBackground: true, retry: true, retryDelay: 3000 })
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const d = q.data
  usePageTitle(d?.event?.subject ?? d?.note?.title)
  if (!d) return <Loading label="Finding the call in Granola…" />
  const live = !!d.grew && now - new Date(d.grew).getTime() < 45000
  const title = d.event?.subject || d.note?.title || 'Live call'
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5 md:px-6">
        <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-semibold', live ? 'bg-accent text-onaccent' : 'border border-line text-ink2')}>
          <span aria-hidden className={cn('size-1.5 rounded-full', live ? 'animate-pulse bg-onaccent' : 'bg-ink3')} />{live ? 'Live' : d.note ? 'Quiet' : 'Waiting'}
        </span>
        <h1 className="min-w-0 truncate text-[17px] font-semibold">{title}</h1>
        {d.event && d.event.attendees.length > 0 && <span className="min-w-0 truncate text-[13px] text-ink2">with {d.event.attendees.join(', ')}</span>}
        <div className="ml-auto flex items-center gap-1.5 text-[12px] text-ink2">
          {d.fetched && <span title="When SleePO last read the transcript from Granola">read {ago(d.fetched, now)}</span>}
          {d.notes.length > 1 && (
            <select aria-label="Granola note" value={d.note?.id ?? ''} onChange={(e) => setPick(e.target.value || undefined)}
              className="max-w-[220px] rounded-full border border-line bg-panel px-2 py-1 text-[12px] text-ink">
              {!d.note && <option value="">Pick the note…</option>}
              {d.notes.map((n) => <option key={n.id} value={n.id}>{format(new Date(n.meeting_at), 'HH:mm')} · {n.title || 'New note'}</option>)}
            </select>
          )}
          {d.note?.url && <a href={d.note.url} target="_blank" rel="noopener" className={toolBtn}><Video size={13} aria-hidden />Granola</a>}
          {d.event && <Link to="/meetings" search={{ open: d.event.id }} className={toolBtn}>Meeting</Link>}
        </div>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section aria-label="Briefing" className="min-h-0 overflow-auto border-line px-4 py-4 max-md:hidden md:border-r md:px-6">
          <h2 className="mb-3 text-[13px] font-semibold text-ink2">Briefing</h2>
          {d.event ? <Brief eventId={d.event.id} label={d.event.subject} /> : <p className="text-[13px] text-ink2">No calendar meeting for this call, so no brief. Open Live from a meeting's panel to see its brief here.</p>}
        </section>
        <section aria-label="Transcript" className="flex min-h-0 flex-col">
          <Transcript d={d} />
          <Ask d={d} />
        </section>
      </div>
    </div>
  )
}

function Brief({ eventId, label }: { eventId: string; label: string }) {
  const b = useQuery({ queryKey: ['prepBrief', eventId], queryFn: () => api.prepBrief(eventId) })
  const brief = b.data?.brief
  const doc = useQuery({ queryKey: ['doc', brief?.doc_id, brief?.updated_at], queryFn: () => api.doc(brief!.doc_id), enabled: !!brief })
  if (b.isLoading || (brief && !doc.data)) return <Loading />
  if (!brief) return <p className="text-[13px] text-ink2">No brief was written for this meeting.</p>
  return <div className="panel-md"><BriefBody md={doc.data?.md ?? ''} label={label} eventId={eventId} /></div>
}

// the transcript follows the newest line while Sam is at the bottom; scrolled up, it stays where he is
function Transcript({ d }: { d: LiveState }) {
  const box = useRef<HTMLDivElement>(null)
  const atEnd = useRef(true)
  useEffect(() => { const el = box.current; if (el && atEnd.current) el.scrollTop = el.scrollHeight }, [d.chars])
  return (
    <div ref={box} onScroll={(e) => { const el = e.currentTarget; atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }}
      className="min-h-0 flex-1 overflow-auto px-4 py-4 md:px-6">
      {d.error ? <p className={cn('text-[13px]', d.signed_in ? 'text-ink2' : 'text-hot')}>{d.error}</p>
        : !d.note ? <p className="text-[13px] text-ink2">No Granola note is recording for this meeting yet. Start one in Granola; it shows here within a few seconds.</p>
        : d.turns.length === 0 ? <p className="text-[13px] text-ink2">Granola is recording; nothing transcribed yet.</p>
        : <div className="flex flex-col gap-1.5">
            {d.turns.map((t, i) => {
              const mine = isMe(t.who)
              const first = i === 0 || d.turns[i - 1].who !== t.who
              return (
                <div key={i} className={cn('flex flex-col', mine ? 'items-end' : 'items-start', first && i > 0 && 'mt-2')}>
                  {first && <span className="mb-0.5 px-1 text-[11.5px] font-medium text-ink2">{mine ? 'You' : t.who === 'Others' ? 'The call' : t.who || 'Unknown'}</span>}
                  <div className={cn('max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-1.5 text-[13.5px] leading-relaxed', mine ? 'msg-mine' : 'bg-panel2')}>{t.text}</div>
                </div>)
            })}
          </div>}
    </div>
  )
}

function Ask({ d }: { d: LiveState }) {
  const key = d.note ? `assist-live-qa-${d.note.id}` : ''
  const [qa, setQa] = useState<QA[]>(() => { try { return key ? JSON.parse(sessionStorage.getItem(key) ?? '[]') : [] } catch { return [] } })
  const [text, setText] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => { try { if (key) sessionStorage.setItem(key, JSON.stringify(qa.filter((x) => !x.running))) } catch { /* private window */ } }, [qa, key])
  useEffect(() => { const el = list.current; if (el) el.scrollTop = el.scrollHeight }, [qa.length, qa[qa.length - 1]?.a])
  const busy = qa.some((x) => x.running)
  const ask = async (question: string) => {
    if (!question.trim() || !d.note || busy) return
    setText('')
    const history = qa.filter((x) => x.a).map(({ q, a }) => ({ q, a }))
    setQa((l) => [...l, { q: question, a: '', running: true }])
    const done = (patch: Partial<QA>) => setQa((l) => l.map((x, i) => (i === l.length - 1 ? { ...x, ...patch, running: false } : x)))
    try {
      const { job } = await api.liveAsk({ question, note: d.note.id, event: d.event?.id, history })
      let j = await api.liveJob(job)
      while (j.running) { await new Promise((r) => setTimeout(r, 1000)); j = await api.liveJob(job) }
      done(j.ok ? { a: j.answer } : { error: j.error || 'No answer came back. Try again.' })
    } catch (e) { done({ error: (e as Error).message }) }
  }
  return (
    <div className="shrink-0 border-t border-line bg-panel">
      {qa.length > 0 && (
        <div ref={list} className="max-h-[42vh] overflow-auto px-4 pt-3 md:px-6">
          {qa.map((x, i) => (
            <div key={i} className="mb-3">
              <div className="text-[13px] font-semibold">{x.q}</div>
              {x.running ? <div className="mt-1 inline-flex items-center gap-1.5 text-[12.5px] text-ink2"><Loader2 size={13} className="animate-spin" />Reading the call so far…</div>
                : x.error ? <div className="mt-1 text-[12.5px] text-hot">{x.error}</div>
                : <div className="panel-md mt-1 text-[13.5px]"><Markdown>{x.a}</Markdown></div>}
            </div>))}
        </div>
      )}
      <div className="px-4 pb-3 pt-2 md:pl-6 md:pr-24">{/* clear of the chat button in the corner */}
        <div className="mb-2 flex flex-wrap gap-1">
          {QUICK.map((s) => <button key={s} disabled={!d.note || busy} onClick={() => ask(s)}
            className="rounded-full border border-line px-2.5 py-0.5 text-[12px] text-ink2 hover:border-ink hover:text-ink disabled:opacity-50">{s}</button>)}
        </div>
        <div data-dictate className="flex items-end gap-2 rounded-2xl border border-line bg-bg px-3 py-2 focus-within:border-ink">
          <textarea ref={input} rows={1} value={text} onChange={(e) => setText(e.target.value)} disabled={!d.note}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(text) } }}
            placeholder={d.note ? 'Ask about the call so far…' : 'Waiting for a Granola note…'}
            className="max-h-32 min-h-[22px] flex-1 resize-none bg-transparent text-[13.5px] text-ink outline-none placeholder:text-ink3" />
          <DictateButton target={input} />
          <button onClick={() => ask(text)} disabled={!text.trim() || !d.note || busy} aria-label="Ask"
            className="grid size-7 shrink-0 place-items-center rounded-full bg-ink text-bg disabled:opacity-40"><ArrowUp size={15} /></button>
        </div>
      </div>
    </div>
  )
}
