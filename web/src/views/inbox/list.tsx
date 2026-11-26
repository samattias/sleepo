// The Inbox's message list: rows, thread rows, the Needs response button and Refresh mail.
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, CornerUpLeft, ListChecks, ListPlus, Forward, Paperclip, PenLine, Plus, RefreshCw, ReplyAll, X } from 'lucide-react'
import { api, type Person } from '@/lib/api'
import { cn, time } from '@/lib/util'
import { Avatar } from '@/components/ui'
import { ago as agoOf, LOCALE } from '@/lib/time'
import { type Entry, TZ, shortWhen } from './model'

// onNeeds: received mail Sam has not answered can be added to Needs response or removed from it, from a button that shows on
// hover in place of the time (the open email has the same button, and the e key)
// One row of the list (compact, Sam 22 Oct 2026: unread is bold, no dot). thread: the row heads a conversation of several
// emails; the chevron on the left opens the rest under it, like Outlook.
type ThreadInfo = { count: number; open: boolean; unread: boolean; onToggle: () => void }
export function Row({ m, on, p, flagNeeds, onClick, onNeeds, thread }: { m: Entry; on: boolean; p?: Person; flagNeeds: boolean; onClick: () => void; onNeeds?: () => void; thread?: ThreadInfo }) {
  const name = m.sent ? (m.to.length ? `To ${m.to.slice(0, 2).join(', ')}${m.to.length > 2 ? ` +${m.to.length - 2}` : ''}` : 'No recipients') : m.from_name || m.from_address || '(unknown sender)'
  const bold = m.unread || !!thread?.unread
  return (
    <div className="group relative">
    {thread && <button onClick={thread.onToggle} aria-expanded={thread.open} aria-label={`${thread.open ? 'Hide' : 'Show'} the ${thread.count} emails in this conversation`}
      title={`${thread.count} emails in this conversation`}
      className="absolute left-1 top-[11px] z-[1] grid size-5 place-items-center rounded text-ink2 transition-colors hover:bg-line hover:text-ink">
      <ChevronRight size={14} aria-hidden className={cn('transition-transform duration-200 motion-reduce:transition-none', thread.open && 'rotate-90')} /></button>}
    <button id={`mail-${m.id}`} onClick={onClick} aria-current={on ? 'true' : undefined}
      className={cn('flex w-full gap-2.5 border-b border-l-2 border-b-line2 py-1.5 pl-6 pr-4 text-left', on ? 'border-l-accent bg-accentbg' : 'border-l-transparent hover:bg-panel2', m.noise && !on && 'opacity-60')}>
      <Avatar p={p ?? { name: (m.sent ? m.to[0] : m.from_name || m.from_address) || '?', avatar: '' }} size={28} className="mt-0.5" />
      <span className="min-w-0 flex-1 leading-[18px]">
        <span className="flex items-center gap-1.5">
          <span className={cn('truncate text-[13.5px]', bold ? 'font-bold' : 'font-medium')}>{name}</span>
          {thread && <span title={`${thread.count} emails in this conversation`} className="shrink-0 rounded-full bg-panel2 px-1.5 text-[11px] font-semibold tabular-nums leading-[16px] text-ink2">{thread.count}</span>}
          {m.importance === 'high' && <span title="High importance" className="shrink-0 text-[13px] font-bold text-hot">!</span>}
          {m.has_attachments && <Paperclip size={12} aria-label="has attachments" className="shrink-0 text-ink3" />}
          {m.task && <ListChecks size={12} role="img" aria-label={`Part of the task ${m.task.title}`} className="shrink-0 text-ink2"><title>{`Task: ${m.task.title}`}</title></ListChecks>}
          {!m.task && m.taskProposed && <ListPlus size={12} role="img" aria-label="A task is proposed for this email" className="shrink-0 text-ink2"><title>A task is proposed: open the email, Create task</title></ListPlus>}
          {m.needs && m.drafted && <PenLine size={12} role="img" aria-label="A response is drafted" className="shrink-0 text-ink2"><title>A response is drafted: open the email to read, edit or send it from Outlook</title></PenLine>}
          <span className={cn('ml-auto shrink-0 text-[12px] tabular-nums text-ink3', onNeeds && 'group-hover:invisible')}>{time(m.ts)}</span>
        </span>
        <span className={cn('block truncate text-[13px]', bold && 'font-semibold')}>{m.subject}</span>
        <span className="flex items-center gap-1.5 text-[12.5px] text-ink3">
          {m.answered && <span className="inline-flex shrink-0 items-center gap-0.5 text-ink2"><CornerUpLeft size={12} aria-hidden />Replied</span>}
          {flagNeeds && m.needs && <span title={m.why} className="inline-flex shrink-0 items-center gap-1 rounded-full border border-hot/40 bg-hot/10 px-1.5 text-[11.5px] font-medium leading-[18px] text-hot"><span aria-hidden className="size-1.5 rounded-full bg-hot" />Needs response{m.response === 'forward' ? ' · forward' : m.response === 'replyall' ? ' · reply all' : ''}</span>}
          {!flagNeeds && m.needs && m.response && m.response !== 'reply' && <span title={m.why} className="inline-flex shrink-0 items-center gap-1 text-[11.5px] font-semibold text-ink">
            {m.response === 'forward' ? <Forward size={11} aria-hidden /> : <ReplyAll size={11} aria-hidden />}{m.response === 'forward' ? 'Forward' : 'Reply all'}</span>}
          <span className="truncate">{m.preview}</span>
        </span>
      </span>
    </button>
    {onNeeds && <NeedsButton needs={m.needs} onClick={onNeeds} className="invisible absolute right-3 top-1.5 bg-panel group-hover:visible" />}
    </div>
  )
}

// Another email of an open conversation, under its head row: who, a line of it, when. Bold when unread.
export function ThreadRow({ m, on, onClick }: { m: Entry; on: boolean; onClick: () => void }) {
  return (
    <button id={`mail-${m.id}`} onClick={onClick} aria-current={on ? 'true' : undefined}
      className={cn('flex w-full items-baseline gap-2 border-b border-l-2 border-b-line2 py-1 pl-[62px] pr-4 text-left text-[12.5px]', on ? 'border-l-accent bg-accentbg' : 'border-l-transparent bg-panel2/40 hover:bg-panel2')}>
      <span className={cn('max-w-[40%] shrink-0 truncate', m.unread ? 'font-bold text-ink' : 'font-medium text-ink')}>{m.sent ? 'You' : m.from_name || m.from_address}</span>
      <span className={cn('min-w-0 flex-1 truncate', m.unread ? 'font-semibold text-ink' : 'text-ink3')}>{m.preview || m.subject}</span>
      {m.needs && <span aria-label="needs response" title="Needs response" className="size-1.5 shrink-0 self-center rounded-full bg-hot" />}
      <span className="shrink-0 tabular-nums text-ink3">{shortWhen(m.ts)}</span>
    </button>
  )
}

export function NeedsButton({ needs, onClick, className }: { needs: boolean; onClick: () => void; className?: string }) {
  return (
    <button onClick={onClick} title={needs ? 'Remove from Needs response: no response needed (e)' : 'Add to Needs response (e)'}
      className={cn('inline-flex shrink-0 items-center gap-1 rounded-full border border-line px-2 py-px text-[12px] font-medium text-ink transition-colors hover:border-ink', className)}>
      {needs ? <X size={12} aria-hidden /> : <Plus size={12} aria-hidden />}{needs ? 'No response needed' : 'Add to Needs response'}</button>
  )
}

// "Refresh mail": Apple Mail's Inbox and Sent, nothing else (the full refresh in the header pulls every source). It also runs
// by itself, quietly, when Sam comes back to this page (from Mail, say) and every 2 minutes while it is on screen, if the
// last import is over 90 seconds old: read and unread then follow Mail without a click.
const AUTO_MIN_AGE = 90_000   // a quiet re-read every 2 minutes while the page is on screen (Sam, 22 Oct 2026), and on coming back to it
export function MailRefresh() {
  const qc = useQueryClient()
  const st = useQuery({ queryKey: ['mailRefresh'], queryFn: api.mailRefreshStatus, refetchInterval: 60000 })
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null)
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 30000); return () => clearInterval(t) }, [])
  useEffect(() => { if (!note || note.bad) return; const t = setTimeout(() => setNote(null), 5000); return () => clearTimeout(t) }, [note])
  const running = useRef(false)
  const run = async (auto = false) => {
    if (running.current) return
    running.current = true
    setBusy(true); if (!auto) setNote(null)
    try {
      const r = await api.mailRefresh()
      const n = (r.new.inbox ?? 0) + (r.new.sent ?? 0)
      if (!auto) setNote(!r.mail_running ? { text: 'Apple Mail is not open, so new mail may not have arrived yet. Open Mail and refresh again.', bad: true }
        : { text: [n ? `${n} new` : 'Up to date', r.read ? `${r.read} now read` : ''].filter(Boolean).join(' · ') })
      if (auto) {   // reload the lists only when something changed: no flicker on a quiet run
        qc.invalidateQueries({ queryKey: ['mailRefresh'] })
        if (n || r.read) for (const k of ['mail', 'replyInbox', 'loops', 'todo', 'today']) qc.invalidateQueries({ queryKey: [k] })
      }
      else qc.invalidateQueries()
    } catch (e) { if (!auto) setNote({ text: e instanceof Error ? e.message : String(e), bad: true }) }   // a quiet run says nothing
    running.current = false
    setBusy(false)
  }
  const last = st.data?.last
  const auto = useRef(() => {})
  useEffect(() => { auto.current = () => { if (document.visibilityState === 'visible' && st.data && !st.data.running && (!last || Date.now() - Date.parse(last) > AUTO_MIN_AGE)) run(true) } })
  useEffect(() => {
    const go = () => auto.current()
    window.addEventListener('focus', go)
    document.addEventListener('visibilitychange', go)
    const t = setInterval(go, 2 * 60_000)
    return () => { window.removeEventListener('focus', go); document.removeEventListener('visibilitychange', go); clearInterval(t) }
  }, [])
  return (
    <>
      <span className="ml-auto truncate text-[12px] text-ink3 @max-[360px]/list:hidden" title={last ? `Last read from Apple Mail ${new Date(last).toLocaleString(LOCALE, { timeZone: TZ })}` : undefined}>
        {busy ? 'Reading Apple Mail…' : note && !note.bad ? note.text : last ? ago(last) : ''}</span>
      <button onClick={() => run()} disabled={busy} title="Fetch new mail (inbox and sent) from Apple Mail on this Mac. Takes a few seconds; nothing else is refreshed."
        className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 @max-[360px]/list:ml-auto text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2 active:bg-line disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ink">
        <RefreshCw size={13} aria-hidden className={cn(busy && 'animate-spin')} /><span className="@max-[330px]/list:sr-only">Refresh</span></button>
      {note?.bad && <div role="alert" className="basis-full border-l-2 border-hot pl-2 text-[12px] text-ink">{note.text}</div>}
    </>
  )
}
const ago = (iso: string) => agoOf(iso)
