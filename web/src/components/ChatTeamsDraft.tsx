// A Teams or Slack reply the chat wrote (assist/chat.py: ```teams <item id>, or ```slack <item id>), drawn as Sam's next
// message in that conversation: the text edited in place, Copy, and Copy and open Teams. A reply that goes with a reviewed
// file (attach=<attachment id>) carries the updated file as its attachment (components/ChatReview.tsx), which Sam attaches in
// Teams himself. His edits are kept with the conversation like an email card's and go to the chat with his next question.
// Blanks become a few questions under it, as on an email card (components/FillQuestions.tsx). Nothing is sent.
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ClipboardCopy, MessageSquare } from 'lucide-react'
import { api, type ChatDraftSaved } from '@/lib/api'
import { cn } from '@/lib/util'
import { FillEditor } from './FillEditor'
import { FillQuestions } from './FillQuestions'
import { UpdatedFile } from './ChatReview'
import { mentionsMe } from '@/lib/profile'

const pill = 'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2 active:bg-line disabled:opacity-60'

export function ChatTeamsDraft({ k, tid, app, item, attach, raw, done, latest = true, saved, onSaved }: {
  k: string; tid: string | null; app: 'teams' | 'slack'; item: number | null; attach: number | null; raw: string; done: boolean
  latest?: boolean   // no later reply drafted after it: its blanks are asked about at once
  saved?: ChatDraftSaved; onSaved: (key: string, s: ChatDraftSaved) => void
}) {
  const where = useQuery({ queryKey: ['messageLink', item], queryFn: () => api.messageLink(item!), enabled: !!item, staleTime: 300_000 })
  const written = raw.trim()
  const [text, setText] = useState(saved?.body ?? written)
  const [copied, setCopied] = useState(false)
  const [err, setErr] = useState('')
  const edited = useRef(!!saved?.body)
  useEffect(() => { if (!edited.current) setText(written) }, [written])   // still being written: follow it until Sam edits
  // his edits, kept with the conversation (a moment after he stops typing)
  useEffect(() => {
    if (!edited.current || !tid || !done) return
    const t = setTimeout(() => {
      api.chatDraftSave(tid, { key: k, mail: null, to: '', cc: '', subject: '', body: text, kind: app, item: item ?? undefined })
        .then((s) => onSaved(k, s)).catch(() => setErr('Your edits could not be kept; they are still here.'))
    }, 700)
    return () => clearTimeout(t)
  }, [text]) // eslint-disable-line react-hooks/exhaustive-deps
  const name = app === 'slack' ? 'Slack' : 'Teams'
  const to = where.data?.author && !mentionsMe(where.data.author) ? where.data.author : where.data?.conversation
  const copy = async (open: boolean) => {
    try { await navigator.clipboard.writeText(text); setCopied(true) } catch { setErr('The clipboard is not available here.') }
    if (open && where.data?.link) window.open(where.data.link, '_blank', 'noopener')
  }
  return (
    <div className="my-2 flex flex-col items-end">
      <div className="mb-0.5 flex items-center gap-1.5 px-1 text-[11px] text-ink3"><MessageSquare size={12} aria-hidden />{name} reply{to ? ` to ${to}` : ''} · draft, not sent</div>
      <div className="msg-mine w-full rounded-2xl rounded-tr-md px-3 py-0.5 ring-1 ring-accent">
        <FillEditor value={text} onChange={(v) => { edited.current = true; setText(v); setCopied(false) }} rows={Math.min(12, Math.max(2, text.split('\n').length + 1))} bare />
      </div>
      {done && <FillQuestions kind="chat" app={app} ids={item ? [item] : []} tid={tid} scope={`t${tid ?? ''}:${k}`} auto={latest} draft={text}
        onFilled={(v) => { edited.current = true; setText(v); setCopied(false) }} className="mt-1.5 w-full" />}
      {attach != null && done && <UpdatedFile attId={attach} className="mt-1" />}
      {done && <div className="mt-1 flex flex-wrap items-center justify-end gap-0.5">
        <button onClick={() => copy(false)} disabled={!text.trim()} className={pill}><ClipboardCopy size={13} aria-hidden />Copy</button>
        {where.data?.link && <button onClick={() => copy(true)} disabled={!text.trim()}
          className={cn('ml-1 inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-[12.5px] font-semibold text-onaccent transition-[filter] hover:brightness-95 disabled:opacity-50')}>
          {copied ? <Check size={13} aria-hidden /> : <MessageSquare size={13} aria-hidden />}{copied ? 'Copied' : `Copy and open ${name}`}</button>}
      </div>}
      {attach != null && done && <p className="mt-0.5 px-1 text-[11.5px] text-ink3">Attach the file in {name} when you paste the reply.</p>}
      {err && <p role="alert" className="mt-0.5 px-1 text-[12px] text-hot">{err}</p>}
    </div>)
}
