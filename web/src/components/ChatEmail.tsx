// An email the chat wrote (assist/chat.py: every email is an ```email block), drawn as a draft card like the Inbox's (Sam,
// 23 Oct 2026): from Sam, with To, Cc, Subject and the text all edited in place; Copy, Open in Outlook and, for a reply to an
// email SleePO holds, Use in reply. Changes shows tracked changes, as one redline (put in highlighted, taken out struck
// through): what SleePO changed since the previous version of this email in the conversation, and what Sam changed himself.
// His edits are kept with the conversation (POST /api/chat/threads/{tid}/drafts) and go to the chat with his next question,
// so a revision starts from his version. Blanks SleePO could not fill ([FILL: …]) become a few questions under the text
// (components/FillQuestions.tsx; Sam, 19 Nov 2026), prepared at once for the newest version of the email. Nothing is sent.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Check, ClipboardCopy, CornerDownRight, Mail, PenLine, RefreshCw } from 'lucide-react'
import { api, type ChatDraftSaved } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { diffRedline, diffStats } from '@/lib/diff'
import { addresses, notSignedIn, openCompose } from '@/lib/outlook'
import { OutlookLogo } from '@/components/OutlookLogo'
import { Avatar } from './ui'
import { FillEditor, countFills } from './FillEditor'
import { FillQuestions } from './FillQuestions'
import { mentionsMe, myName } from '@/lib/profile'

// {mail, body}: a revised draft Sam takes from the chat back to that email's composer (views/inbox/); also kept in
// sessionStorage under `${USE_DRAFT}-${mail}` for a composer that is not open yet
export const USE_DRAFT = 'sleepo:use-draft'

export type EmailFields = { to: string; cc: string; subject: string; body: string }
const HEAD = /^(to|cc|subject)\s*:\s*(.*)$/i
// the block's text -> its header lines (a new email) and the text; a reply holds the text only
export function parseEmail(raw: string): EmailFields {
  const lines = raw.replace(/^\s*\n/, '').split('\n')
  const out: EmailFields = { to: '', cc: '', subject: '', body: '' }
  let i = 0
  for (; i < lines.length; i++) {
    const m = lines[i].match(HEAD)
    if (!m) break
    out[m[1].toLowerCase() as 'to' | 'cc' | 'subject'] = m[2].trim()
  }
  if (i > 0 && !lines[i]?.trim()) i++
  out.body = lines.slice(i).join('\n').trim()
  return out
}

const line = 'min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink3 focus:bg-panel2/60'
const pill = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2 active:bg-line disabled:opacity-60'
const notMe = (a: { name: string; address: string }) => !mentionsMe(`${a.name} ${a.address}`)
const nm = (a: { name: string; address: string }) => (a.name || a.address).replace(/\s*\(.*\)$/, '')

export function ChatEmail({ k, tid, mail, raw, done, earlier, latest = true, saved, onSaved }: {
  k: string; tid: string | null; mail: number | null; raw: string; done: boolean
  earlier: EmailFields[]                                   // the previous versions of this email in the conversation, as Sam left them
  latest?: boolean                                         // no later version of it in the conversation: its blanks are asked about at once
  saved?: ChatDraftSaved; onSaved: (key: string, s: ChatDraftSaved) => void
}) {
  const nav = useNavigate()
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 300_000 })
  const me = people.data?.find((p) => p.status === 'me')
  const orig = useMemo(() => parseEmail(raw), [raw])
  const reply = mail != null
  const src = useQuery({ queryKey: ['mailOne', mail], queryFn: () => api.mailOne(mail!), enabled: reply && done, staleTime: 300_000 })
  const edited = !!saved?.edited_at
  const [f, setF] = useState<EmailFields>(() => edited ? { ...orig, ...pick(saved!) } : orig)
  const [touched, setTouched] = useState(edited)
  useEffect(() => { if (!touched) setF(orig) }, [orig]) // eslint-disable-line react-hooks/exhaustive-deps -- follows the answer as it streams until Sam edits
  const [mode, setMode] = useState<'reply' | 'replyall'>('reply')
  useEffect(() => { if (src.data && src.data.to.length + src.data.cc.length > 1) setMode('replyall') }, [src.data])
  const [pref, setPref] = usePersisted<'edit' | 'last' | 'first'>('assist-chat-redline', 'last')   // the view Sam last chose, for every card
  const [local, setLocal] = useState<typeof pref | null>(null)   // this card's: typing keeps it on Edit
  const view = local ?? pref
  const setView = (v: typeof pref) => { setLocal(v); setPref(v) }
  const [state, setState] = useState<'' | 'copied' | 'saving' | 'saved'>('')
  const [confirm, setConfirm] = useState(false)
  const [fallback, setFallback] = useState(false)
  const [err, setErr] = useState('')
  const [used, setUsed] = useState(false)

  // tracked changes: against the previous version of this email (or the first), else against what SleePO wrote here
  const base = view === 'first' && earlier.length > 1 ? earlier[0] : earlier.length ? earlier[earlier.length - 1] : touched ? orig : null
  const show = done && base && view !== 'edit' && (base.body.trim() !== f.body.trim() || base.subject !== f.subject) ? view : 'edit'
  const parts = useMemo(() => (show !== 'edit' && base ? diffRedline(base.body, f.body) : null), [show, base, f.body])
  const stats = parts ? diffStats(parts) : null
  const mine = touched && orig.body.trim() !== f.body.trim()
  const fills = countFills(f.body)

  // keep Sam's version with the conversation, a moment after he stops typing
  const first = useRef(true)
  useEffect(() => {
    if (first.current || !touched || !tid) { first.current = false; return }
    const t = setTimeout(() => {
      api.chatDraftSave(tid, { key: k, mail, ...f }).then((s) => onSaved(k, s)).catch(() => setErr('Your edits could not be kept; they are still here.'))
    }, 700)
    return () => clearTimeout(t)
  }, [f]) // eslint-disable-line react-hooks/exhaustive-deps
  const edit = (p: Partial<EmailFields>) => { setF((x) => ({ ...x, ...p })); setTouched(true); setLocal('edit'); setConfirm(false); setState('') }

  const copy = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    setConfirm(false); setErr('')
    try { await navigator.clipboard.writeText(f.body); setState('copied') } catch { setErr('The clipboard is not available here.') }
  }
  const use = () => {
    if (mail == null) return
    try { sessionStorage.setItem(`${USE_DRAFT}-${mail}`, f.body) } catch { /* storage off: the event still reaches an open composer */ }
    api.replyWorkingPut(mail, { body: f.body, source: 'chat' }).catch(() => { /* the composer still gets it through the event */ })   // kept, so it survives leaving the email
    window.dispatchEvent(new CustomEvent(USE_DRAFT, { detail: { mail, body: f.body } }))
    nav({ to: '/inbox', search: { open: mail } })
    setUsed(true)
  }
  // the window opens on the click (so the browser allows it) and is pointed at the draft once Outlook has it
  const outlook = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    const to = addresses(f.to), cc = addresses(f.cc)
    if (!reply && !to.out.length) { setErr(to.missing.length ? `Add an email address for ${to.missing.join(', ')}.` : 'Add who it goes to.'); return }
    if (!tid && !reply) return
    setConfirm(false); setErr(''); setState('saving')
    try {
      const r = reply ? await api.replyOutlook(mail!, f.body, mode, cc.out) : await api.chatDraftOutlook(tid!, { key: k, to: to.out, cc: cc.out, subject: f.subject, body: f.body })
      if (r.web_link) window.open(r.web_link, '_blank')
      setState('saved')
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e)
      if (notSignedIn(msg)) {   // no Outlook write access yet: a prefilled new message in Outlook for Mac instead (the web if it cannot open)
        const m = src.data
        const toList = reply && m ? (mode === 'reply' ? [m.from] : [m.from, ...m.to]).filter(notMe).map((a) => a.address) : to.out
        const ccList = [...(reply && m && mode === 'replyall' ? m.cc.filter(notMe).map((a) => a.address) : []), ...cc.out]
        const subj = reply && m ? (/^re:/i.test(m.subject ?? '') ? m.subject ?? '' : `Re: ${m.subject ?? ''}`) : f.subject
        try { await navigator.clipboard.writeText(f.body) } catch { /* the text is in the message anyway */ }
        await openCompose(toList, ccList, subj, f.body)
        setState('saved'); setFallback(true)
        return
      }
      setState(''); setErr(msg)
    }
    if (!reply && (to.missing.length || cc.missing.length)) setErr(`No address for ${[...to.missing, ...cc.missing].join(', ')}: add them in Outlook.`)
  }

  const recipients = reply && src.data ? (mode === 'reply' ? nm(src.data.from) : [src.data.from, ...src.data.to].filter(notMe).map(nm).join(', ')) : ''
  return (
    <article aria-label="Email draft" className="my-2 overflow-hidden rounded-xl border border-dashed border-ink3/60 bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line2 px-3 py-1.5 text-[12px] text-ink2">
        <Avatar p={me ?? { name: myName(), avatar: '' }} size={20} />
        <span className="inline-flex items-center gap-1 rounded-full bg-accentbg px-2 text-[11.5px] font-semibold leading-[18px] text-ink"><PenLine size={11} aria-hidden />Draft</span>
        <span className="truncate">{reply ? <>Reply{src.data?.subject ? <> · {src.data.subject}</> : ''}</> : <><Mail size={12} aria-hidden className="mr-1 inline" />New email</>}</span>
        {earlier.length > 0 && <span className="text-ink3">version {earlier.length + 1}</span>}
        {done && base && <div role="radiogroup" aria-label="Show" className="ml-auto inline-flex rounded-full bg-panel2 p-0.5">
          {([['edit', 'Edit'], ['last', 'Changes'], ...(earlier.length > 1 ? [['first', 'Since first']] : [])] as [typeof view, string][]).map(([key, l]) =>
            <button key={key} role="radio" aria-checked={show === key} onClick={() => setView(key)}
              title={key === 'edit' ? 'Edit the email' : key === 'last' ? (earlier.length ? 'Tracked changes since the previous version, yours included' : 'Your changes to what SleePO wrote') : 'Tracked changes since the first version'}
              className={cn('rounded-full px-2 py-px text-[11.5px] transition-colors', show === key ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>{l}</button>)}
        </div>}
      </div>
      <div className="px-3 pt-1.5">
        {reply ? <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-ink2">
          {src.data && src.data.to.length + src.data.cc.length > 1 && <div role="radiogroup" aria-label="Reply or reply all" className="inline-flex rounded-full bg-panel2 p-0.5">
            {(['reply', 'replyall'] as const).map((x) => <button key={x} role="radio" aria-checked={mode === x} onClick={() => setMode(x)}
              className={cn('rounded-full px-2 py-px text-[11.5px] transition-colors', mode === x ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>{x === 'reply' ? 'Reply' : 'Reply all'}</button>)}
          </div>}
          <span className="min-w-0 truncate">to {recipients || '…'}</span>
        </div> : <>
          <label className="flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-12 shrink-0">To</span>
            <input value={f.to} onChange={(e) => edit({ to: e.target.value })} disabled={!done} placeholder="Name <address>, comma-separated" aria-label="To" className={line} /></label>
          <label className="flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-12 shrink-0">Cc</span>
            <input value={f.cc} onChange={(e) => edit({ cc: e.target.value })} disabled={!done} placeholder="optional" aria-label="Cc" className={line} /></label>
          <label className="flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-12 shrink-0">Subject</span>
            {show !== 'edit' && base && base.subject !== f.subject
              ? <span className="min-w-0 flex-1 text-[13px] font-medium">{base.subject && <del className="mr-1 rounded-sm bg-hot/10 text-hot decoration-hot/70">{base.subject}</del>}<ins className="rounded-sm bg-accent text-onaccent no-underline">{f.subject}</ins></span>
              : <input value={f.subject} onChange={(e) => edit({ subject: e.target.value })} disabled={!done} placeholder="Subject" aria-label="Subject" className={cn(line, 'font-medium')} />}
          </label>
        </>}
      </div>
      {parts && stats && <div className="mx-3 mt-1.5 flex flex-wrap items-center gap-x-2 text-[11.5px] text-ink2">
        <span>{stats.added || stats.removed ? <>{stats.added} word{stats.added === 1 ? '' : 's'} in · {stats.removed} out, since {show === 'first' ? 'the first version' : earlier.length ? 'the previous version' : 'what SleePO wrote'}</> : 'No change in the words'}</span>
        <span className="inline-flex items-center gap-1"><span className="rounded-sm bg-accent px-1 text-onaccent">put in</span><span className="rounded-sm bg-hot/10 px-1 text-hot line-through">taken out</span></span></div>}
      <div className="px-3 pb-2 pt-1.5">
        {parts
          ? <div role="button" tabIndex={0} title="Click to edit" onClick={() => setView('edit')} onKeyDown={(e) => e.key === 'Enter' && setView('edit')}
              className="cursor-text whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">
              {parts.map((p, i) => p.type === 'same' ? <span key={i}>{p.text}</span>
                : p.type === 'add' ? <ins key={i} className="rounded-sm bg-accent text-onaccent no-underline">{p.text}</ins>
                : <del key={i} className="rounded-sm bg-hot/10 text-hot decoration-hot/70">{p.text}</del>)}</div>
          : done ? <FillEditor bare value={f.body} onChange={(v) => edit({ body: v })} rewrite={{ kind: 'email', item_id: mail, tid, subject: f.subject }} rows={Math.min(18, Math.max(4, f.body.split('\n').length + 1))} />
          : <div className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">{f.body}</div>}
      </div>
      {done && <FillQuestions kind="email" itemId={mail ?? undefined} tid={tid} scope={`t${tid ?? ''}:${k}`} auto={latest} draft={f.body}
        onFilled={(t) => edit({ body: t })} className="mx-3 mb-2" />}
      {confirm && <div className="mx-3 mb-2 rounded-lg border-l-2 border-l-hot bg-panel2 px-3 py-1.5 text-[12.5px]">{fills} highlighted placeholder{fills > 1 ? 's are' : ' is'} still in the text. Fill {fills > 1 ? 'them' : 'it'} in, or press the button again to continue anyway.</div>}
      {done && <footer className="flex flex-wrap items-center gap-1 border-t border-line2 px-2 py-1.5">
        <button onClick={copy} title="Copy the text" className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3 py-1 text-[12.5px] font-medium text-bg transition-opacity hover:opacity-90">
          {state === 'copied' ? <Check size={13} aria-hidden /> : <ClipboardCopy size={13} aria-hidden />}{confirm ? 'Copy anyway' : state === 'copied' ? 'Copied' : 'Copy'}</button>
        <button onClick={outlook} disabled={state === 'saving' || !f.body.trim()} title={reply ? "Save it into Outlook as a reply in the email's thread, and open it there. Nothing is sent." : 'Save it as a draft in your Outlook, and open it there. Nothing is sent.'} className={pill}>
          {state === 'saving' ? <RefreshCw size={13} className="animate-spin" aria-hidden /> : state === 'saved' ? <Check size={13} aria-hidden /> : <OutlookLogo size={13} />}
          {state === 'saving' ? 'Saving to Outlook…' : state === 'saved' ? (fallback ? 'Opened in Outlook' : 'In your Outlook drafts') : confirm ? 'Open anyway' : 'Open in Outlook'}</button>
        {reply && <button onClick={use} title="Put this version in the email's reply box in the Inbox (nothing is sent)" className={pill}>
          {used ? <Check size={13} aria-hidden /> : <CornerDownRight size={13} aria-hidden />}{used ? 'In the reply' : 'Use in reply'}</button>}
        {!reply && saved?.outlook_link && state !== 'saved' && <a href={saved.outlook_link} target="_blank" rel="noopener" className="px-1 text-[12px] text-ink2">last saved draft ↗</a>}
        <span className="ml-auto pr-1 text-[11.5px] text-ink3 max-sm:hidden">{mine ? 'Your edits are kept · ' : ''}Nothing is sent</span>
      </footer>}
      {fallback && <div className="px-3 pb-2 text-[12px] text-ink2">Opened as a new message in Outlook on the web, filled in (the text is also copied). SleePO cannot save drafts into your Outlook until IT approves its access{reply ? ', so this reply is not in the thread' : ''}.</div>}
      {err && <div role="alert" className="px-3 pb-2 text-[12px] text-hot">{err}</div>}
    </article>
  )
}

function pick(s: ChatDraftSaved): Partial<EmailFields> {
  const out: Partial<EmailFields> = {}
  for (const k of ['to', 'cc', 'subject', 'body'] as const) if (typeof s[k] === 'string') out[k] = s[k]
  return out
}
