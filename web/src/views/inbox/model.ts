// The Inbox's shared pieces: the list's entries and threads, filters, modes and button styles (split from views/inbox.tsx, 22 Oct 2026).
import { type Addr, type InboxItem, type MailItem, type Person } from '@/lib/api'
import { btnClass } from '@/components/ui'
import { dayTime, TZ } from '@/lib/time'
import { mentionsMe } from '@/lib/profile'

export { TZ }   // the user's zone (lib/time, from the profile)
export const INTENTS = ['Agree and confirm next steps', 'Decline politely', 'Ask for more detail', 'Propose a time to talk', 'Short acknowledgment', 'Push back with the reason']
export const FOLLOW_INTENTS = ['Nudge for an answer', 'Share an update', 'Ask for a decision by a date', 'Propose a time to talk', 'Thank them and close the loop']
export type Folder = 'inbox' | 'drafts' | 'sent'   // Drafts: views/inbox/drafts.tsx (Sam, 26 Oct 2026)
export type Filter = 'all' | 'unread' | 'needs'   // narrows the Inbox; Sent has no filter
export type Mode = 'reply' | 'replyall' | 'forward' | 'followup'
export type Panel = 'reply' | 'doc' | 'task'   // the briefing sits above the thread (Sam, 22 Oct 2026), not in this panel
export type Who = (name: string) => Person | undefined
export const typing = (e: KeyboardEvent) => { const t = e.target as HTMLElement; return e.metaKey || e.ctrlKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable }

export const isMe = (s: string) => mentionsMe(s)   // the user's name or address in it (lib/profile)
export const nm = (a: Addr) => a.name || a.address
export const toolBtn = btnClass('ghost')       // components/ui.tsx: the shared button styles
export const primaryBtn = btnClass('primary')
export const shortWhen = dayTime   // 14:05 today, otherwise 22 Oct (lib/time.ts)

// One email in the list, received or sent. needs, answered and automated come from the reply flags (replies.inbox, the one
// definition of "waiting on Sam", last 14 days); older mail has no flags, so answered is worked out from Sent instead.
export type Entry = {
  id: number; sent: boolean; ts: string; subject: string; from_name: string; from_address: string; to: string[]; preview: string
  has_attachments: boolean; importance: string | null; unread: boolean; noise: boolean; full: boolean; needs: boolean; answered: boolean; automated: boolean
  drafted: boolean   // a recommended reply is waiting in the composer (assist/replies.py predraft)
  task: { task_id: number; title: string } | null   // the task this email's thread belongs to (assist/task_links.py)
  taskProposed: boolean   // a task is proposed for it in the background, more than a reply (assist/tasks.py preplan)
  response: 'reply' | 'replyall' | 'forward' | null   // the response SleePO suggests, when not a plain reply (Needs response, 22 Oct 2026)
  why: string   // why it is, or is not, waiting on Sam (replies.asked): "addressed to you by name", "group mail, not asked by name"…
  conv: string | null
}
export function entries(inbox: MailItem[], sent: MailItem[], flags: InboxItem[]) {
  const f = new Map(flags.map((x) => [x.id, x]))
  const lastSent = new Map<string, string>()   // when Sam last wrote in each conversation
  for (const s of sent) if (s.conversation_id && s.ts > (lastSent.get(s.conversation_id) ?? '')) lastSent.set(s.conversation_id, s.ts)
  const mk = (m: MailItem, isSent: boolean): Entry => {
    const x = f.get(m.id)
    return { id: m.id, sent: isSent, ts: m.ts, subject: m.subject || '(no subject)', from_name: m.from_name || '', from_address: m.from_address || '', to: m.to,
      preview: m.preview || m.text || '', has_attachments: !!m.has_attachments, importance: m.importance, unread: !isSent && m.is_read === 0, noise: !!m.noise, full: !!m.full,
      needs: !!x && x.needs_reply, why: x?.reply_why ?? '', answered: x ? x.answered : !isSent && !!m.conversation_id && (lastSent.get(m.conversation_id) ?? '') > m.ts,
      automated: x ? x.automated : !!m.noise, conv: m.conversation_id, drafted: !!x?.drafted, response: x?.response ?? null, task: m.task ?? null, taskProposed: !!m.task_proposed }
  }
  return { inbox: inbox.map((m) => mk(m, false)), sent: sent.map((m) => mk(m, true)) }
}
// Threads in the list, like Outlook's conversations (Sam, 22 Oct 2026). Conversation ids are patchy (about a third of the
// mail has one, from two systems: Microsoft 365 and Apple Mail), so mail is also joined by conversation topic: the same
// subject without Re:/Fw:, with at least one person in common besides Sam. Returns each email's thread key (its root id).
const topic = (t: string) => t.replace(/^\s*((re|fw|fwd|aw|tr|wg|sv|antw)\s*:\s*)+/i, '').replace(/\s+/g, ' ').trim().toLowerCase()
// Sam's forward of an email joins its thread whoever it went to (Sam, 23 Oct 2026: his forward of Noel Owner's advisory to
// Gray did not show under it): "FW: <same subject>" from him, within 30 days after the email (assist/replies.py forwarded)
const FORWARD = /^\s*(fw|fwd|wg|tr)\s*(\[\d+\])?\s*:/i
const forwardOf = (f: Entry, m: Entry) => f.sent && !m.sent && FORWARD.test(f.subject) && f.ts > m.ts && Date.parse(f.ts) - Date.parse(m.ts) <= 30 * 86_400_000
export function threadKeys(all: Entry[]): Map<number, number> {
  const up = new Map<number, number>()
  const find = (x: number): number => { let r = x; while (up.has(r) && up.get(r) !== r) r = up.get(r)!; up.set(x, r); return r }
  const join = (a: number, b: number) => { const ra = find(a), rb = find(b); if (ra !== rb) up.set(ra, rb) }
  const people = (m: Entry) => new Set([m.from_address, m.from_name, ...m.to].map((x) => (x || '').toLowerCase().trim()).filter((x) => x && !mentionsMe(x)))
  const byConv = new Map<string, number>(), byTopic = new Map<string, Entry[]>()
  for (const m of all) {
    find(m.id)
    if (m.conv) { const o = byConv.get(m.conv); if (o != null) join(m.id, o); else byConv.set(m.conv, m.id) }
    const t = topic(m.subject)
    if (t.length >= 4 && t !== '(no subject)' && !m.automated) byTopic.set(t, [...(byTopic.get(t) ?? []), m])
  }
  for (const ms of byTopic.values()) {
    if (ms.length < 2 || ms.length > 60) continue   // a subject used everywhere is not one conversation
    const ps = ms.map(people)
    for (let i = 0; i < ms.length; i++) for (let j = i + 1; j < ms.length; j++)
      if ([...ps[i]].some((x) => ps[j].has(x)) || forwardOf(ms[i], ms[j]) || forwardOf(ms[j], ms[i])) join(ms[i].id, ms[j].id)
  }
  return new Map(all.map((m) => [m.id, find(m.id)]))
}

// Sam, 22 Oct 2026: a switch between Inbox and Sent (no counts: the Unread chip and the sidebar's Needs response badge carry
// them), then filter chips under it (All by default, Unread, Needs response)
export const FILTERS: [Filter, string, string][] = [['all', 'All', 'Everything received'], ['unread', 'Unread', 'Unread mail, without newsletters and notifications'],
  ['needs', 'Needs response', 'Waiting on you: asks you for something (by name, to you alone, or a question to a few people), not yet answered (last 14 days). Group mail, FYIs and mail you are copied on are left out. Remove any email, or add one from All (e)']]
