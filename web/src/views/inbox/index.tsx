// Inbox: all of Sam's mail as a mail client (message list, conversation, and under it one panel with three tabs: Draft
// response, Create document (components/DocumentCreator.tsx) and Create briefing, the situation around the thread with
// its sources, continued in the chat (components/Briefing.tsx)). Needs response, Unread, everything received
// and Sent in one place; any email can be answered (or, for his own sent mail, followed up or forwarded) with a draft in
// his voice from the context around it (thread, attachments, the people, open items, recent meetings, his own emails to
// them). Mail comes from Apple Mail on this Mac; "Refresh mail" re-reads it in seconds. Never sends.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Inbox as InboxIcon, PenLine, Search as SearchIcon, Send, X } from 'lucide-react'
import { useRouter } from '@tanstack/react-router'
import { api, type InboxItem } from '@/lib/api'
import { cn, dayKey, dayLabel, usePersisted } from '@/lib/util'
import { Empty, Loading } from '@/components/ui'
import { USE_DRAFT } from '@/components/Chat'
import { ListResizer } from '@/components/ListResizer'   // the list's width: shared with Messages
import { usePageTitle, useSearchSync } from '@/lib/nav'
import { Conversation } from './conversation'
import { Drafts } from './drafts'
import { MailRefresh, Row, ThreadRow } from './list'
import { type Entry, FILTERS, type Filter, type Folder, type Who, entries, threadKeys, typing } from './model'

export function Inbox({ open, draft }: { open?: number; draft?: string } = {}) {
  const inboxQ = useQuery({ queryKey: ['mail', 'inbox'], queryFn: () => api.mail('inbox') })
  const sentQ = useQuery({ queryKey: ['mail', 'sent'], queryFn: () => api.mail('sent') })
  const flagsQ = useQuery({ queryKey: ['replyInbox'], queryFn: api.replyInbox, refetchInterval: 120000 })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const [f, setF] = usePersisted<{ folder: Folder; filter: Filter; q: string; noise: boolean }>('assist-inbox-v2', { folder: 'inbox', filter: 'all', q: '', noise: false })
  const show: Filter | 'sent' = f.folder === 'sent' ? 'sent' : f.filter
  const [sel, setSel] = useState<number | null>(null)
  const [listW, setListW] = usePersisted<number>('assist-inbox-list-width', 0)   // 0: the default, 30% of the window
  const opened = useRef<number | undefined>(undefined)   // the ?open= email already shown
  const ready = !!(inboxQ.data && sentQ.data && flagsQ.data)
  const failed = inboxQ.isError || sentQ.isError || flagsQ.isError
  const mail = useMemo(() => (ready ? entries(inboxQ.data!, sentQ.data!, flagsQ.data!) : { inbox: [], sent: [] }), [ready, inboxQ.data, sentQ.data, flagsQ.data])
  const byId = useMemo(() => new Map([...mail.inbox, ...mail.sent].map((e) => [e.id, e])), [mail])

  // the open email is kept in the address (?open=), so Back from a person or task page returns to it (lib/nav.ts)
  useSearchSync('open', sel)
  // A link to one email (?open=…, from search, Today, an action): show the folder it is in and select it.
  useEffect(() => {
    if (!open || !ready) return
    if (open === sel) { opened.current = open; return }   // the address only caught up with a click here
    const e = byId.get(open)
    if (e) {
      const fits = e.sent ? show === 'sent' : show === 'all' || (show === 'needs' && e.needs) || (show === 'unread' && e.unread && !e.automated && !e.noise)
      if (!fits || f.q || f.folder === 'drafts') setF({ ...f, folder: e.sent ? 'sent' : 'inbox', filter: 'all', q: '' })
    }
    opened.current = open
    setSel(open)
    setTimeout(() => document.getElementById(`mail-${open}`)?.scrollIntoView({ block: 'center' }), 50)   // after the folder switch renders
  }, [open, ready]) // eslint-disable-line react-hooks/exhaustive-deps

  const base = useMemo(() => ({
    needs: mail.inbox.filter((m) => m.needs),
    unread: mail.inbox.filter((m) => m.unread && !m.automated && !m.noise),
    all: mail.inbox.filter((m) => f.noise || !m.noise),
    sent: mail.sent.filter((m) => f.noise || !m.noise),
  }), [mail, f.noise])
  const hiddenNoise = f.noise ? 0 : (show === 'sent' ? mail.sent : show === 'all' ? mail.inbox : []).filter((m) => m.noise).length
  const list = useMemo(() => {
    const re = f.q.trim() ? new RegExp(f.q.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
    return re ? base[show].filter((m) => re.test(`${m.subject} ${m.from_name} ${m.from_address} ${m.to.join(' ')} ${m.preview}`)) : base[show]
  }, [base, show, f.q])
  // one row per thread: the newest email of the thread that this view shows; the rest of the thread (both folders) opens under it
  const keyOf = useMemo(() => threadKeys([...mail.inbox, ...mail.sent]), [mail])
  const members = useMemo(() => {
    const t = new Map<number, Entry[]>()
    for (const m of [...mail.inbox, ...mail.sent]) { const k = keyOf.get(m.id)!; t.set(k, [...(t.get(k) ?? []), m]) }
    for (const v of t.values()) v.sort((a, b) => b.ts.localeCompare(a.ts))
    return t
  }, [mail, keyOf])
  const heads = useMemo(() => { const seen = new Set<number>(); return list.filter((m) => { const k = keyOf.get(m.id)!; if (seen.has(k)) return false; seen.add(k); return true }) }, [list, keyOf])
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggleThread = (k: number) => setExpanded((x) => { const n = new Set(x); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const others = (h: Entry) => (members.get(keyOf.get(h.id)!) ?? []).filter((x) => x.id !== h.id)
  // the rows on screen, in order (j / k move through them)
  const visible = useMemo(() => heads.flatMap((h) => { const k = keyOf.get(h.id)!; return expanded.has(k) ? [h, ...(members.get(k) ?? []).filter((x) => x.id !== h.id)] : [h] }), [heads, expanded, keyOf, members])
  useEffect(() => {   // an email opened inside a thread (a link, j / k): keep its thread open
    if (sel == null) return
    const k = keyOf.get(sel)
    if (k != null && !heads.some((h) => h.id === sel) && heads.some((h) => keyOf.get(h.id) === k) && !expanded.has(k)) setExpanded((x) => new Set(x).add(k))
  }, [sel, keyOf, heads]) // eslint-disable-line react-hooks/exhaustive-deps
  const groups = useMemo(() => {
    const g: { day: string; items: Entry[] }[] = []
    for (const m of heads) { const d = dayKey(m.ts); if (g.at(-1)?.day !== d) g.push({ day: d, items: [] }); g.at(-1)!.items.push(m) }
    return g
  }, [heads])
  // Drafts keeps its open draft in the address (?draft=): leaving the folder clears it first, so Back and a reload do not
  // bring the folder back
  const router = useRouter()
  const leaveDrafts = async () => {
    if (f.folder === 'drafts') await router.navigate({ to: '.', search: ((p: Record<string, unknown>) => ({ ...p, draft: undefined })) as never, replace: true, resetScroll: false } as never)
  }
  const pickFolder = async (folder: Folder) => { if (folder !== f.folder) { await leaveDrafts(); setSel(null); setF({ ...f, folder }) } }
  useEffect(() => { if (draft && f.folder !== 'drafts') setF({ ...f, folder: 'drafts' }) }, [draft]) // eslint-disable-line react-hooks/exhaustive-deps
  // from Drafts: a reply in progress opens in its email (the composer has it); "ready in Needs response" opens that list
  const openMail = async (id: number) => {
    await leaveDrafts()
    const e = byId.get(id)
    setF({ ...f, folder: e?.sent ? 'sent' : 'inbox', filter: 'all', q: '' })
    setSel(id)
    setTimeout(() => document.getElementById(`mail-${id}`)?.scrollIntoView({ block: 'center' }), 50)
  }
  const openNeeds = async () => { await leaveDrafts(); setSel(null); setF({ ...f, folder: 'inbox', filter: 'needs', q: '' }) }
  const pickFilter = (filter: Filter) => { if (filter !== f.filter) { setSel(null); setF({ ...f, filter }) } }
  // Open on the newest message on a desktop; on a phone the list comes first.
  // Never when a link names an email: both effects run in the same render when the mail arrives, and this one would win.
  useEffect(() => { if (sel == null && !(open && byId.has(open)) && opened.current === open && list.length && matchMedia('(min-width: 768px)').matches) setSel(list[0].id) }, [list, sel, open, byId])   // list[0] is the first head too
  const byName = useMemo(() => new Map((people.data ?? []).map((p) => [p.name.toLowerCase(), p])), [people.data])
  // a name as mail writes it: "Gray Selby", "Gray Selby (Acme)", "Gray Selby <gray@…>", "Selby, Gray"
  const who: Who = (n) => {
    const s = (n || '').replace(/\s*<[^>]*>\s*$/, '').replace(/\s*\(.*\)\s*$/, '').replace(/^["']+|["']+$/g, '').trim().toLowerCase()
    const flip = /^([^,]+),\s*(.+)$/.exec(s)
    return byName.get(s) ?? (flip ? byName.get(`${flip[2]} ${flip[1]}`) : undefined)
  }
  const cur = sel != null ? byId.get(sel) ?? null : null
  usePageTitle(cur ? (cur.sent ? `To ${cur.to[0] ?? ''}` : cur.from_name || cur.subject) : null)

  // How many rows sit below the fold: macOS hides scrollbars, so the list says it goes on.
  const listRef = useRef<HTMLDivElement>(null)
  const [below, setBelow] = useState(0)
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const count = () => { const edge = el.scrollTop + el.clientHeight; setBelow(Array.from(el.querySelectorAll<HTMLElement>('[id^="mail-"]')).filter((r) => r.offsetTop + 24 > edge).length) }
    count()
    el.addEventListener('scroll', count, { passive: true })
    const ro = new ResizeObserver(count)
    ro.observe(el)
    return () => { el.removeEventListener('scroll', count); ro.disconnect() }
  }, [list])

  // "Use in reply" in the chat (components/Chat.tsx DraftCard): select that email; its composer takes the draft
  useEffect(() => {
    const on = (e: Event) => { const id = (e as CustomEvent<{ mail: number }>).detail?.mail; if (id != null && byId.has(id)) setSel(id) }
    window.addEventListener(USE_DRAFT, on); return () => window.removeEventListener(USE_DRAFT, on)
  }, [byId])

  // j/k or ↓/↑ move through the list, like a mail client
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (typing(e)) return
      const i = visible.findIndex((m) => m.id === sel)
      const go = (j: number) => { const m = visible[Math.max(0, Math.min(visible.length - 1, j))]; if (m) { setSel(m.id); document.getElementById(`mail-${m.id}`)?.scrollIntoView({ block: 'nearest' }) } }
      if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); go(i + 1) }
      if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); go(i - 1) }
    }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [visible, sel])

  // Sam's own call on an email: add it to Needs response or remove it (loops.mark_reply). The flag flips at once; removing
  // the open email from the Needs response list moves on to the next one, like archiving; Undo puts it back.
  const qc = useQueryClient()
  const [marked, setMarked] = useState<{ id: number; subject: string; needs: boolean; error?: string } | null>(null)
  useEffect(() => { if (!marked || marked.error) return; const t = setTimeout(() => setMarked(null), 8000); return () => clearTimeout(t) }, [marked])
  const setNeeds = async (e: Entry, needs: boolean, announce = true) => {
    const why = needs ? 'you added it to Needs response' : 'you said no response is needed'
    qc.setQueryData<InboxItem[]>(['replyInbox'], (xs) => !xs ? xs : xs.some((x) => x.id === e.id) ? xs.map((x) => (x.id === e.id ? { ...x, needs_reply: needs, reply_why: why } : x))
      : [...xs, { id: e.id, graph_id: '', subject: e.subject, from_name: e.from_name, from_address: e.from_address, received_at: e.ts, preview: e.preview, note: '',
          has_attachments: e.has_attachments, importance: e.importance, is_read: !e.unread, automated: e.automated, answered: false, to_me: true, needs_reply: needs, reply_why: why }])
    if (!needs && show === 'needs' && sel === e.id) { const i = list.findIndex((x) => x.id === e.id); setSel((list[i + 1] ?? list[i - 1])?.id ?? null) }
    try { await api.replyNeeds(e.id, needs); if (announce) setMarked({ id: e.id, subject: e.subject, needs }) }
    catch (err) { setMarked({ id: e.id, subject: e.subject, needs, error: err instanceof Error ? err.message : String(err) }) }
    for (const k of ['replyInbox', 'loops', 'todo', 'today']) qc.invalidateQueries({ queryKey: [k] })
  }
  const undo = () => { const e = marked && byId.get(marked.id); if (!e) return; setNeeds(e, !marked!.needs, false); setSel(e.id); setMarked(null) }
  const canMark = (m: Entry) => !m.sent && !m.answered

  const today = dayKey(new Date().toISOString())
  const n: Record<Filter, number> = { all: base.all.length, needs: base.needs.length, unread: base.unread.length }
  // Inbox | Drafts | Sent, as in Mail (Drafts: Sam, 26 Oct 2026); no counts: the Unread chip and the sidebar carry them
  const FOLDERS: [Folder, string, typeof InboxIcon][] = [['inbox', 'Inbox', InboxIcon], ['drafts', 'Drafts', PenLine], ['sent', 'Sent', Send]]
  const folderBar = (
    <div className="flex items-center gap-2">
      <h1 className="sr-only">Mail</h1>
      <div role="tablist" aria-label="Folder" className="flex shrink-0 rounded-full bg-panel2 p-0.5">
        {FOLDERS.map(([k, l, Icon]) => (
          <button key={k} role="tab" aria-selected={f.folder === k} onClick={() => void pickFolder(k)}
            className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[13px] font-semibold transition-colors', f.folder === k ? 'bg-panel text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>
            <Icon size={13} aria-hidden />{l}</button>))}
      </div>
      <MailRefresh />
    </div>
  )
  if (f.folder === 'drafts') return <Drafts head={folderBar} listW={listW} setListW={setListW} who={who} openMail={(id) => void openMail(id)} openNeeds={() => void openNeeds()} draft={draft} />
  return (
    <div className="flex min-h-0 flex-1">
      <aside aria-label="Mail" style={listW ? ({ '--list-w': `${listW}px` } as CSSProperties) : undefined}
        className={cn('@container/list relative flex min-h-0 w-full flex-col border-line bg-panel md:shrink-0 md:border-r', listW ? 'md:w-[min(var(--list-w),50vw)]' : 'md:w-[clamp(320px,30vw,420px)]', sel != null && 'max-md:hidden')}>
        <ListResizer width={listW} onChange={setListW} label="Resize the mail list" />
        <div className="border-b border-line px-4 pt-3">
          {folderBar}
          <label className="relative mt-2.5 block">
            <SearchIcon size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink3" />
            <input value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder={show === 'sent' ? 'Search sent mail' : 'Search sender, subject, text'} aria-label="Search mail"
              className="w-full rounded-full border border-line bg-bg py-1.5 pl-8 pr-3 text-[13px] text-ink outline-none transition-colors placeholder:text-ink3 focus:border-ink" />
          </label>
          {/* filter chips for the Inbox: one at a time; the count says how many each would show */}
          <div role="radiogroup" aria-label="Filter" className={cn('flex flex-wrap gap-1.5 py-2.5', f.folder === 'sent' && 'invisible')} aria-hidden={f.folder === 'sent'}>
            {FILTERS.map(([k, l, tip]) => { const on = f.filter === k; return (
              <button key={k} role="radio" aria-checked={on} title={tip} tabIndex={f.folder === 'sent' ? -1 : 0} onClick={() => pickFilter(k)}
                className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12.5px] font-medium transition-colors',
                  on ? 'border-ink bg-ink text-bg' : 'border-line text-ink hover:border-ink')}>
                {k === 'needs' && <span aria-hidden className={cn('size-1.5 rounded-full', on ? 'bg-accent' : 'bg-hot')} />}{l}
                {k !== 'all' && ready && <span className={cn('tabular-nums', on ? 'opacity-70' : k === 'needs' && n.needs ? 'text-hot' : 'text-ink3')}>{n[k]}</span>}</button>) })}
          </div>
        </div>
        {marked && <div role="status" className={cn('flex items-center gap-2 border-b border-line2 px-4 py-1.5 text-[12.5px]', marked.error ? 'text-hot' : 'text-ink2')}>
          <span className="min-w-0 truncate">{marked.error ? `Could not change “${marked.subject}”: ${marked.error}` : <>{marked.needs ? 'Added' : 'Removed'} “<span className="text-ink">{marked.subject}</span>” {marked.needs ? 'to' : 'from'} Needs response</>}</span>
          {marked.error ? <button onClick={() => setMarked(null)} aria-label="Dismiss" className="ml-auto shrink-0 text-ink hover:opacity-70"><X size={13} aria-hidden /></button>
            : <button onClick={undo} className="ml-auto shrink-0 font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Undo</button>}</div>}
        {f.q.trim() && ready && <div className="flex items-center gap-2 border-b border-line2 px-4 py-1.5 text-[12.5px] text-ink2">
          {list.length} of {base[show].length} match “{f.q.trim()}”<button onClick={() => setF({ ...f, q: '' })} className="ml-auto font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Clear search</button></div>}
        <div className="relative min-h-0 flex-1">
        <div ref={listRef} className="absolute inset-0 overflow-auto">
          {failed && <div className="p-4"><Empty>Could not load mail.</Empty></div>}
          {!ready && !failed && <div className="p-4"><Loading /></div>}
          {ready && list.length === 0 && <div className="p-4"><Empty>{f.q ? 'No match.' : show === 'needs' ? 'Nothing waiting on a response.' : show === 'unread' ? 'Nothing unread.' : 'Nothing here.'}</Empty></div>}
          {groups.map((g) => (
            <div key={g.day}>
              <div className="sticky top-0 z-[2] border-b border-line2 bg-panel px-4 py-1 text-[12px] font-semibold text-ink">{dayLabel(g.day, today)}</div>{/* above the rows' thread chevrons (z-[1]), which scrolled over it */}
              {g.items.map((m) => { const k = keyOf.get(m.id)!, rest = others(m), isOpen = expanded.has(k); return <div key={m.id}>
                <Row m={m} on={m.id === sel} p={who(m.sent ? m.to[0] ?? '' : m.from_name)} flagNeeds={show !== 'needs'} onClick={() => setSel(m.id)}
                  onNeeds={canMark(m) ? () => setNeeds(m, !m.needs) : undefined}
                  thread={rest.length ? { count: rest.length + 1, open: isOpen, unread: rest.some((x) => x.unread), onToggle: () => toggleThread(k) } : undefined} />
                {rest.length > 0 && <div className={cn('grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none', isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                  <div className="min-h-0 overflow-hidden">{isOpen && rest.map((x) => <ThreadRow key={x.id} m={x} on={x.id === sel} onClick={() => setSel(x.id)} />)}</div>
                </div>}
              </div> })}
            </div>
          ))}
          {ready && (hiddenNoise > 0 || (f.noise && (show === 'all' || show === 'sent'))) && (
            <div className="px-4 py-4 text-[12.5px] text-ink2">
              {f.noise ? <>Showing {show === 'sent' ? 'calendar responses' : 'newsletters, notifications'} and other noise. <button onClick={() => setF({ ...f, noise: false })} className="font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Hide them</button></>
                : <>{hiddenNoise.toLocaleString()} {show === 'sent' ? 'calendar responses' : 'newsletters, notifications'} and other noise hidden. <button onClick={() => setF({ ...f, noise: true })} className="font-medium text-ink underline decoration-accent decoration-2 underline-offset-2">Show them</button></>}
            </div>)}
        </div>
        {below > 0 && <>
          <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-panel to-transparent" />
          <button onClick={() => listRef.current?.scrollBy({ top: listRef.current.clientHeight * 0.8, behavior: 'smooth' })}
            className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1 text-[12.5px] font-medium text-ink shadow-md transition-colors hover:bg-panel2">
            <ChevronDown size={14} aria-hidden />{below.toLocaleString()} more</button>
        </>}
        </div>
      </aside>
      <section aria-label="Conversation" className={cn('min-h-0 min-w-0 flex-1 overflow-auto bg-bg', sel == null && 'max-md:hidden')}>
        {cur ? <Conversation key={cur.id} m={cur} who={who} onBack={() => setSel(null)} onNeeds={canMark(cur) ? () => setNeeds(cur, !cur.needs) : undefined} />
          : <div className="grid h-full place-items-center p-6 text-center text-[13.5px] text-ink2">{ready ? <div>{sel != null ? 'This email is no longer in the mailbox.' : 'Select an email.'}<div className="mt-1 text-[12.5px] text-ink3">j / k to move · r to reply · e to add or remove from Needs response</div></div> : null}</div>}
      </section>
    </div>
  )
}
