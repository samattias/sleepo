// An email step of a task, drawn like the Inbox's draft (views/inbox.tsx Composer, Sam 22 Oct 2026): an email from Sam with
// his photo, a Draft tag, who it goes to, the subject and the text, all editable in place. Edits are kept on the task as
// he types (onSave). Copy puts it on the clipboard; Open in Outlook saves it as a real draft in his Outlook and opens it
// there: a reply goes into the email's own thread (assist/outlook_drafts.py save), a new email into Drafts
// (save_new). For a reply, Rewrite from the thread drafts it again with the Inbox's writer from the whole thread. Nothing
// is ever sent.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, ClipboardCopy, PenLine, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { OutlookLogo } from '@/components/OutlookLogo'
import { openCompose } from '@/lib/outlook'
import { api, type ActionSource } from '@/lib/api'
import { asList, type Action } from '@/components/Actions'
import { Avatar } from '@/components/ui'
import { FillEditor, countFills } from '@/components/FillEditor'
import { cn, editRatio } from '@/lib/util'
import { LOCALE } from '@/lib/time'
import { mentionsMe, myName } from '@/lib/profile'

type Email = Extract<ActionSource, { kind: 'email' }>
const pill = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium text-ink transition-colors hover:bg-panel2 active:bg-line disabled:opacity-60'
const line = 'min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink3 focus:bg-panel2/60'
const nm = (a: { name: string; address: string }) => (a.name || a.address).replace(/\s*\(.*\)$/, '')
const notMe = (a: { name: string; address: string }) => !mentionsMe(`${a.name} ${a.address}`)

// Outlook on the web's compose page, filled in: works without any Outlook permission for SleePO
export const owaCompose = (to: string[], cc: string[], subject: string, body: string) => {
  const q = [to.length && `to=${encodeURIComponent(to.join(';'))}`, cc.length && `cc=${encodeURIComponent(cc.join(';'))}`,
    `subject=${encodeURIComponent(subject)}`, `body=${encodeURIComponent(body.slice(0, 6000))}`].filter(Boolean).join('&')
  return `https://outlook.office.com/mail/deeplink/compose?${q}`
}

export function EmailDraft({ a, taskId, step, email, onSave, onUsed, onRemove }: {
  a: Action; taskId: number; step: number; email?: Email
  onSave: (a: Action) => void; onUsed: (what: string) => void; onRemove: () => void }) {
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 300_000 })
  const me = people.data?.find((p) => p.status === 'me')
  const reply = !!email
  const [mode, setMode] = useState<'reply' | 'replyall'>(email && email.to.length + email.cc.length > 1 ? 'replyall' : 'reply')
  const [to, setTo] = useState(asList(a.to).join(', '))
  const [cc, setCc] = useState(asList(a.cc).join(', '))
  const [showCc, setShowCc] = useState(asList(a.cc).length > 0)
  const [subject, setSubject] = useState(a.subject ?? '')
  const [body, setBody] = useState(a.body ?? '')
  const [origin, setOrigin] = useState(a.body ?? '')   // what edits are measured against (feedback)
  const [state, setState] = useState<'' | 'copied' | 'saving' | 'saved'>('')
  const [confirm, setConfirm] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [quote, setQuote] = useState(false)
  const [fallback, setFallback] = useState(false)   // opened as a prefilled new message, not a saved draft
  const fills = countFills(body)
  const split = (s: string) => s.split(/[,;]/).map((x) => x.trim()).filter(Boolean)

  // keep edits on the task, a moment after Sam stops typing
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    const t = setTimeout(() => onSave({ ...a, to: split(to), cc: split(cc), subject, body }), 700)
    return () => clearTimeout(t)
  }, [to, cc, subject, body])   // eslint-disable-line react-hooks/exhaustive-deps

  const recipients = reply && email
    ? (mode === 'reply' ? nm(email.from) : [email.from, ...email.to].filter(notMe).map(nm).join(', ')) : ''
  const replyCc = reply && email && mode === 'replyall' ? email.cc.filter(notMe).map(nm).join(', ') : ''

  const copy = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    setConfirm(false); setErr('')
    try {
      await navigator.clipboard.writeText(reply ? body : `Subject: ${subject}\n\n${body}`)
      setState('copied'); onUsed('email copied')
      api.feedback({ target_type: reply ? 'reply' : 'action', target_id: reply ? String(email!.item_id) : `task-${taskId}`, copied: true, edit_ratio: editRatio(origin, body) })
    } catch { setErr('The clipboard is not available here.') }
  }
  // the window opens on the click (so the browser allows it) and is pointed at the draft once Outlook has it
  const outlook = async () => {
    if (fills && !confirm) { setConfirm(true); return }
    if (!reply && !split(to).length) { setErr('Add who it goes to.'); return }
    setConfirm(false); setErr(''); setState('saving')
    try {
      const r = reply ? await api.replyOutlook(email!.item_id, body, mode, split(cc))
        : await api.taskOutlook(taskId, { step, to: split(to), cc: split(cc), subject, body })
      if (r.web_link) window.open(r.web_link, '_blank')
      setState('saved'); onUsed(reply ? 'reply saved in Outlook' : 'draft saved in Outlook')
      api.feedback({ target_type: reply ? 'reply' : 'action', target_id: reply ? String(email!.item_id) : `task-${taskId}`, copied: true, edit_ratio: editRatio(origin, body) })
    } catch (e) {
      const msg = String(e instanceof Error ? e.message : e)
      if (/outlook-login|sign in|401/i.test(msg)) {   // no Outlook write access (the tenant needs an admin to approve it): a prefilled new message in Outlook for Mac instead
        const people = (xs: { address: string }[]) => xs.map((x) => x.address).filter((x) => x && !mentionsMe(x))
        const toList = reply && email ? (mode === 'reply' ? people([email.from]) : people([email.from, ...email.to])) : split(to)
        const ccList = [...(reply && email && mode === 'replyall' ? people(email.cc) : []), ...split(cc)]
        const subj = reply && email ? (/^re:/i.test(email.subject) ? email.subject : `Re: ${email.subject}`) : subject
        try { await navigator.clipboard.writeText(body) } catch { /* the text is in the message anyway */ }
        await openCompose(toList, ccList, subj, body)
        setState('saved'); setFallback(true); onUsed('opened in Outlook')
        return
      }
      setState(''); setErr(msg)
    }
  }
  const rewrite = async () => {
    if (!email || busy) return
    setBusy(true); setErr('')
    try {
      const { job } = await api.replyGenerate(email.item_id, a.intent || a.why || '', mode, split(cc), 3)
      for (let i = 0; i < 150; i++) {
        const j = await api.replyJob(job)
        if (!j.running) {
          if (!j.ok) throw new Error(j.error || 'No draft came back')
          setBody(j.body); setOrigin(j.body)
          onSave({ ...a, to: split(to), cc: split(cc), subject, body: j.body })   // kept on the step now, even if Sam has left the page
          break
        }
        await new Promise((r) => setTimeout(r, 2000))
      }
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    setBusy(false)
  }

  return (
    <article aria-label={`Draft: ${a.label}`} className="my-2 rounded-xl border border-dashed border-ink3/60 bg-panel">
      <div className="flex items-start gap-3 px-4 pt-3">
        <Avatar p={me ?? { name: myName(), avatar: '' }} size={36} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="text-[14px] font-semibold">You</span>
            <span className="inline-flex items-center gap-1 rounded-full bg-accentbg px-2 text-[11.5px] font-semibold leading-[18px] text-ink"><PenLine size={11} aria-hidden />Draft</span>
            <span className="truncate text-[12px] text-ink3">{a.label}</span>
            {fills > 0 ? <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-hot px-2 text-[11.5px] font-medium leading-[18px] text-hot">{fills} to fill in</span>
              : <span className="ml-auto inline-flex items-center gap-1 text-[12px] text-ink3"><Check size={12} aria-hidden />ready to send</span>}
            <button onClick={onRemove} title="Remove this email from the step" aria-label="Remove this email" className="rounded-full p-1 text-ink3 hover:bg-panel2 hover:text-ink"><Trash2 size={13} aria-hidden /></button>
          </div>
          {reply && email ? <>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[12.5px] text-ink2">
              <div role="radiogroup" aria-label="Reply or reply all" className="inline-flex rounded-full bg-panel2 p-0.5">
                {(['reply', 'replyall'] as const).map((k) => <button key={k} role="radio" aria-checked={mode === k} onClick={() => setMode(k)}
                  className={cn('rounded-full px-2 py-px text-[11.5px] transition-colors', mode === k ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>{k === 'reply' ? 'Reply' : 'Reply all'}</button>)}
              </div>
              <span className="min-w-0 truncate" title={`To: ${recipients}${replyCc ? `\nCc: ${replyCc}` : ''}`}>to {recipients || '…'}{replyCc && <> · cc {replyCc}</>}</span>
            </div>
            <label className="flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-6 shrink-0">Cc</span>
              <input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="add people (optional)" aria-label="Add to Cc" className={line} /></label>
            <button onClick={() => setQuote(!quote)} aria-expanded={quote} className="mt-0.5 inline-flex max-w-full items-center gap-1 text-[12.5px] text-ink2 hover:text-ink">
              <span className="truncate">Re: {email.subject}</span><ChevronDown size={12} aria-hidden className={cn('shrink-0 transition-transform', quote && 'rotate-180')} /></button>
          </> : <>
            <label className="mt-0.5 flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-6 shrink-0">To</span>
              <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="email addresses, comma-separated" aria-label="To" className={line} />
              {!showCc && <button onClick={() => setShowCc(true)} className="shrink-0 text-[12px] text-ink3 hover:text-ink">Cc</button>}</label>
            {showCc && <label className="flex items-center gap-2 text-[12.5px] text-ink2"><span className="w-6 shrink-0">Cc</span>
              <input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="email addresses" aria-label="Cc" className={line} /></label>}
            <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject" aria-label="Subject" className={cn(line, 'mt-0.5 w-full text-[13px] font-medium')} />
          </>}
        </div>
      </div>
      {quote && email && <div className="mx-4 mt-2 max-h-56 overflow-auto rounded-lg bg-panel2 px-3 py-2 text-[12.5px] leading-relaxed text-ink2 md:ml-[64px]">
        <div className="mb-1 font-medium text-ink">{nm(email.from)}{email.date ? ` · ${new Date(email.date).toLocaleString(LOCALE, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}` : ''}</div>
        <div className="whitespace-pre-wrap">{email.text}</div></div>}
      <div className="px-4 pb-2 pt-1 md:pl-[64px]">
        <FillEditor bare value={body} onChange={(v) => { setBody(v); setConfirm(false); setState('') }} rewrite={{ kind: 'email', item_id: email?.item_id ?? null, subject }} rows={Math.min(18, Math.max(5, body.split('\n').length + 1))} />
      </div>
      {confirm && <div className="mx-4 mb-2 rounded-lg border-l-2 border-l-hot bg-panel2 px-3 py-2 text-[13px] md:ml-[64px]">{fills} highlighted placeholder{fills > 1 ? 's are' : ' is'} still in the text. Fill {fills > 1 ? 'them' : 'it'} in, or press the button again to continue anyway.</div>}
      <footer className="flex flex-wrap items-center gap-1.5 border-t border-line2 px-4 py-2 md:pl-[60px]">
        <button onClick={copy} className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3.5 py-1.5 text-[13px] font-medium text-bg transition-opacity hover:opacity-90">
          {state === 'copied' ? <Check size={14} aria-hidden /> : <ClipboardCopy size={14} aria-hidden />}{confirm ? 'Copy anyway' : state === 'copied' ? 'Copied' : 'Copy'}</button>
        <button onClick={outlook} disabled={state === 'saving' || !body.trim()} title={reply ? "Save this draft into Outlook as a reply in the email's thread, and open it there. Nothing is sent." : 'Save this email as a draft in your Outlook, and open it there. Nothing is sent.'} className={pill}>
          {state === 'saving' ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : state === 'saved' ? <Check size={14} aria-hidden /> : <OutlookLogo size={14} />}
          {state === 'saving' ? 'Saving to Outlook…' : state === 'saved' ? (fallback ? 'Opened in Outlook' : 'In your Outlook drafts') : confirm ? 'Open anyway' : 'Open in Outlook'}</button>
        {reply && <button onClick={rewrite} disabled={busy} title="Draft it again from the whole thread, with what this step says the reply must do" className={pill}>
          {busy ? <RefreshCw size={14} className="animate-spin" aria-hidden /> : <Sparkles size={14} aria-hidden />}{busy ? 'Writing…' : 'Rewrite from the thread'}</button>}
        {!reply && a.outlook?.web_link && state !== 'saved' && <a href={a.outlook.web_link} target="_blank" rel="noopener" className="text-[12px] text-ink2">last saved draft ↗</a>}
        <span className="ml-auto text-[12px] text-ink3 max-sm:hidden">Nothing is sent from here.</span>
      </footer>
      {fallback && <div className="px-4 pb-3 text-[12.5px] text-ink2 md:pl-[64px]">Opened as a new message in Outlook on the web, filled in (the text is also copied). SleePO cannot save drafts into your Outlook until IT approves its access{reply ? ', so this reply is not in the thread' : ''}.</div>}
      {err && <div role="alert" className="px-4 pb-3 text-[12.5px] text-hot md:pl-[64px]">{err}</div>}
    </article>
  )
}
