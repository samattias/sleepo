// ```message <item id>: a Teams or Slack message Sam opened in Ask SleePO from Messages (Review beside its bubble;
// assist/message_chat.py), drawn as it looks in Messages: who, when, where, the text and its files. The conversation waits
// for Sam to say what he wants done with it.
import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ExternalLink, FileText, Paperclip, Sparkles } from 'lucide-react'
import { api } from '@/lib/api'
import { hue } from '@/lib/util'
import { TZ, LOCALE } from '@/lib/time'
import { Avatar, Markdown } from './ui'
import { PersonLink } from '@/components/PersonLink'

// Teams HTML becomes text with blank and whitespace-only lines; keep paragraphs, keep single line breaks, drop the gaps.
export const tidyChat = (b: string) => b.split('\n').map((l) => l.trimEnd()).join('\n').replace(/\n\s*\n(\s*\n)+/g, '\n\n').replace(/([^\n])\n(?!\n)/g, '$1  \n').trim()
const when = (ts: string) => new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(ts))

export function MessageCard({ item }: { item: number }) {
  const q = useQuery({ queryKey: ['message', item], queryFn: () => api.message(item) })
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 300_000 })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: 300_000 })
  const m = q.data
  if (!m) return <div className="my-2 rounded-xl border border-line bg-panel px-3 py-2 text-[12.5px] text-ink3">{q.isError ? 'This message is no longer in SleePO.' : 'Loading the message…'}</div>
  const app = m.app === 'slack' ? 'Slack' : 'Teams'
  const logo = meta.data?.logos[m.app]
  const name = m.author || 'Unknown'
  const p = (people.data ?? []).find((x) => x.name.toLowerCase() === name.toLowerCase())
  return (
    <div className="my-2 overflow-hidden rounded-xl border border-line bg-panel">
      <div className="flex items-center gap-1.5 border-b border-line2 px-3 py-1.5 text-[11.5px] text-ink2">
        {logo ? <img src={logo} alt="" className="size-3.5 shrink-0 object-contain" /> : null}
        <span className="min-w-0 flex-1 truncate">{app} · {m.conversation || 'a conversation'}</span>
        {m.link && <a href={m.link} target="_blank" rel="noopener" className="inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-ink2 no-underline hover:bg-panel2 hover:text-ink">
          <ExternalLink size={12} aria-hidden />Open in {app}</a>}
      </div>
      <div style={{ '--h': hue(name) } as CSSProperties} className="flex gap-2 px-3 py-2.5">
        <PersonLink id={p?.id} photo className="self-start"><Avatar p={p ?? { name, avatar: '' }} size={28} /></PersonLink>
        <div className="min-w-0 flex-1">
          <div className="mb-0.5 flex items-baseline gap-2"><PersonLink id={p?.id}><span className="msg-name text-[12px] font-semibold">{name}</span></PersonLink>
            <span className="text-[11.5px] tabular-nums text-ink3">{when(m.sent_at)}</span></div>
          <div className="msg-them inline-block max-w-full rounded-2xl rounded-tl-md px-3 py-1.5 text-[13px] leading-snug [overflow-wrap:anywhere] [&_.md_p]:my-0.5 [&_.md>*:first-child]:mt-0 [&_.md>*:last-child]:mb-0">
            <div className="md"><Markdown>{tidyChat(m.body || '')}</Markdown></div>
          </div>
          {m.attachments.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1.5">
            {m.attachments.map((a) => {
              const Icon = a.reviewable ? FileText : Paperclip
              const inner = <><Icon size={13} aria-hidden className="shrink-0" /><span className="truncate">{a.name || 'attachment'}</span>
                {a.read && <Check size={12} aria-label="SleePO has read it" className="shrink-0 text-ink3" />}</>
              return <span key={a.id} className="flex max-w-full flex-wrap items-center gap-x-1.5 gap-y-0.5">
                {a.url ? <a href={a.url} target="_blank" rel="noopener" title={a.read ? 'Open the file · SleePO has read it' : 'Open the file · SleePO has not read it'}
                  className="inline-flex min-w-0 items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-0.5 text-[12.5px] font-normal no-underline hover:border-ink">{inner}</a>
                  : <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-0.5 text-[12.5px]">{inner}</span>}
                {a.review && <span className="inline-flex shrink-0 items-center gap-1 text-[11.5px] text-ink3"><Sparkles size={11} aria-hidden />Reviewed · {a.review.comments} comment{a.review.comments === 1 ? '' : 's'}</span>}
              </span>
            })}
          </div>}
        </div>
      </div>
    </div>)
}
