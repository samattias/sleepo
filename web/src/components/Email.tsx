// Email parts for the Inbox: attachment chips and the sandboxed HTML body.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, FileText, Image as ImageIcon, Mail as MailIcon } from 'lucide-react'
import { api, type MailAttachment, type MailFull } from '@/lib/api'
import { cn } from '@/lib/util'
import { hasRemoteImages } from '@/lib/emailhtml'
import { isTextName, viewText } from '@/components/DocViewer'
import { PlainText } from '@/components/PlainText'

const kb = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

// Clicking an attachment opens the real file: a stored original, else its SharePoint/OneDrive/Teams copy, else the email in
// Outlook (where the original attachment opens). The extracted text is a secondary "Text" button, read in the pop-up.
export function AttachmentChip({ mail, a, webLink }: { mail: number; a: MailAttachment; webLink?: string | null }) {
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.documents, staleTime: 300_000 })
  const url = `/api/mail/${mail}/attachments/${a.id}`
  const d = docs.data?.find((x) => x.id === `ma-${a.id}`)
  const textOnly = !a.on_disk
  const real = !textOnly && a.available ? url : (d?.open_url || webLink || '')
  const where = !textOnly && a.available ? '' : d?.open_where && d.open_where !== 'Outlook' ? `opens in ${d.open_where}` : 'opens the email in Outlook'
  const Icon = a.content_type?.startsWith('image/') ? ImageIcon : a.kind === 'item' ? MailIcon : FileText
  const body = <><Icon size={16} className="shrink-0" /><span className="min-w-0"><span className="block max-w-[220px] truncate text-[13px] font-medium">{a.name}</span><span className="block text-[11.5px] text-ink2">{where || (a.available ? kb(a.size || 0) : a.kind === 'reference' ? 'cloud link' : 'not downloaded')}</span></span></>
  const readText = () => viewText({ title: a.name, sub: 'Email attachment · extracted text', textUrl: url, md: isTextName(a.name) && !/\.txt$/i.test(a.name),
    actions: [...(real ? [{ label: where ? where.replace(/^opens/, 'Open') + ' ↗' : 'Open the file ↗', href: real }] : [])] })
  if (!a.available && !real) return <div className="flex items-center gap-2 border border-line px-2.5 py-1.5 text-ink2">{body}</div>
  return (
    <div className="flex items-center border border-line hover:border-ink">
      {isTextName(a.name)
        ? <button type="button" onClick={readText} className="flex items-center gap-2 px-2.5 py-1.5 text-left text-ink">{body}</button>
        : <a href={real} target="_blank" rel="noopener" className="flex items-center gap-2 px-2.5 py-1.5 text-ink no-underline">{body}</a>}
      {a.has_text && !isTextName(a.name) && <button type="button" onClick={readText} title="Read the extracted text" className="self-stretch border-l border-line px-2 text-[12px] font-medium text-ink hover:bg-panel2">Text</button>}
      {!textOnly && a.available && <a href={url + '?download=1'} title="Download" aria-label={`Download ${a.name}`} className="self-stretch border-l border-line px-2 py-2 text-ink no-underline hover:bg-accent hover:text-onaccent"><Download size={14} /></a>}
    </div>
  )
}

// The body renders in a sandboxed iframe: no scripts, links open in a new tab, inline (cid:) images come from the
// stored attachments or Apple Mail, and remote images stay blocked until asked for (they are often tracking pixels).
export function Body({ m }: { m: MailFull }) {
  const [remote, setRemote] = useState(false)
  const body = m.body ?? ''
  if (m.body_type !== 'html') return <PlainText text={body} />   // lists and links, not a <pre> of asterisks
  const content = body
  return (
    <div>
      {hasRemoteImages(content) && !remote && <div className="mb-3 flex items-center gap-3 rounded-lg bg-panel2 px-3 py-2 text-[12.5px]">Remote images blocked.<button onClick={() => setRemote(true)} className="font-medium underline decoration-accent decoration-2 underline-offset-2">Show images</button></div>}
      <div className="rounded-lg bg-white p-4"><EmailFrame mailId={m.id} html={content} remote={remote} attachments={m.attachments} /></div>
    </div>
  )
}

// Addresses typed into an HTML email without a link (signatures, pasted text) become links too, opening in a new tab
// (Sam, 22 Oct 2026). Text inside existing links, scripts, styles and form fields is left alone; http(s) and www. only.
const URLISH = /\b(?:https?:\/\/|www\.)[^\s<>"']+[^\s<>"'.,;:!?)\]]/gi
function linkify(d: Document) {
  const walk = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT, { acceptNode: (n) =>
    n.parentElement?.closest('a,script,style,textarea,title') || !/(https?:\/\/|www\.)/i.test(n.nodeValue ?? '') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT })
  const nodes: Text[] = []
  while (walk.nextNode()) nodes.push(walk.currentNode as Text)
  for (const t of nodes) {
    const text = t.nodeValue ?? '', frag = d.createDocumentFragment()
    let at = 0
    for (const m of text.matchAll(URLISH)) {
      const i = m.index ?? 0
      frag.append(text.slice(at, i))
      const a = d.createElement('a')
      a.href = m[0].toLowerCase().startsWith('www.') ? `https://${m[0]}` : m[0]
      a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = m[0]
      frag.append(a)
      at = i + m[0].length
    }
    if (at === 0) continue
    frag.append(text.slice(at))
    t.replaceWith(frag)
  }
  d.querySelectorAll('a[href]').forEach((a) => { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener noreferrer') })
}

// One email's HTML (or one message cut from it, with the page's <style> blocks in css). Images that do not load (blocked,
// missing) are hidden rather than shown broken, and the frame follows its content's height as it loads and reflows.
export function EmailFrame({ mailId, html, css = '', remote, attachments = [], className }: {
  mailId: number; html: string; css?: string; remote: boolean; attachments?: MailAttachment[]; className?: string
}) {
  const [h, setH] = useState(40)
  const ro = useRef<ResizeObserver | null>(null)
  useEffect(() => () => ro.current?.disconnect(), [])
  const origin = location.origin
  const doc = useMemo(() => {
    let body = html
    for (const a of attachments) if (a.content_id && a.available) body = body.split(`cid:${a.content_id}`).join(`${origin}/api/mail/${mailId}/attachments/${a.id}`)
    body = body.replace(/\bcid:([^"'\s)>]+)/gi, (_, c: string) => `${origin}/api/mail/${mailId}/cid/${encodeURIComponent(c)}`)
    const csp = `default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data: ${origin}${remote ? ' https: http:' : ''}`
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank">
<style>html,body{margin:0;background:#fff;color:#111;font:14px/1.5 Inter,-apple-system,Segoe UI,Helvetica,Arial,sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%}blockquote{margin-left:0;padding-left:12px;border-left:2px solid #ddd}</style>${css}</head><body>${body}</body></html>`
  }, [html, css, remote, attachments, mailId, origin])
  const onLoad = (e: React.SyntheticEvent<HTMLIFrameElement>) => {
    const d = e.currentTarget.contentDocument
    if (!d?.body) return
    d.querySelectorAll('img').forEach((img) => { if (img.complete && !img.naturalWidth) img.style.display = 'none' })
    linkify(d)
    const fit = () => { const n = Math.min(40000, Math.max(24, Math.ceil(d.documentElement.scrollHeight))); setH((o) => (Math.abs(o - n) > 1 ? n : o)) }
    fit()
    ro.current?.disconnect()
    ro.current = new ResizeObserver(fit)
    ro.current.observe(d.body)
  }
  return <iframe title="Email" sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin" srcDoc={doc} onLoad={onLoad} className={cn('block w-full border-0', className)} style={{ height: h }} />
}
