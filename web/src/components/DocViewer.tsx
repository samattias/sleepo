// Text documents (Markdown, plain text, knowledge-base pages, text-only attachments) never open as a raw file:
// they open here, rendered, in a pop-up that closes with Esc, the X or a click outside. viewText() can be called
// from anywhere (plain functions included); <DocViewerHost /> in the layout shows it.
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, X } from 'lucide-react'
import type { DocItem } from '@/lib/api'
import { btnClass, Loading, Markdown } from './ui'

type View = { title: string; sub?: string; textUrl: string | null; md: boolean; fallback?: string; json?: boolean; base?: string   // json: textUrl returns {md}
  actions?: { label: string; run?: () => void; href?: string }[] }

const TEXT_EXT = ['md', 'markdown', 'mdx', 'txt', 'text']
export const isTextName = (name: string) => TEXT_EXT.includes((name.match(/\.([a-z0-9]+)(?:$|[?#])/i)?.[1] ?? '').toLowerCase())
export const isTextDoc = (d: DocItem) => d.origin === 'kb' || TEXT_EXT.includes(d.ext)

export function viewLibrary(id: string, title?: string, path?: string) {
  viewText({ title: title || id.split('/').pop() || id, sub: 'Library', base: path, textUrl: `/api/docs/${encodeURI(id)}`, json: true, md: true,
    actions: [{ label: 'Open in library', href: `#/explore/library/${id}` }] })
}

export function viewText(v: View) { window.dispatchEvent(new CustomEvent<View>('sleepo:view', { detail: v })) }

export function viewDoc(d: DocItem) {
  const textUrl = d.origin === 'email' ? d.ref : ['kb', 'sharepoint', 'local'].includes(d.origin) ? `/api/documents/${d.id}/text` : null
  const where = d.origin === 'local' ? 'This Mac' : d.origin === 'kb' ? 'Emery Yates' : d.origin === 'sharepoint' ? 'SharePoint' : d.origin === 'email' ? 'Email attachment' : d.origin
  viewText({
    title: d.name, sub: [where, d.where].filter(Boolean).join(' · '), textUrl, md: d.ext !== 'txt' && d.ext !== 'text',
    fallback: d.preview || undefined,
    actions: d.origin === 'local' ? [{ label: 'Show in Finder', run: () => { fetch(`/api/local/${d.id.slice(3)}/open?reveal=1`, { method: 'POST' }) } }]
      : d.origin === 'email' ? [...(d.open_url ? [{ label: `Open in ${d.open_where || 'Outlook'} ↗`, href: d.open_url }] : []), ...(d.mail_id ? [{ label: 'Show the email', href: `#/inbox?open=${d.mail_id}` }] : [])]
      : d.url && d.origin !== 'kb' ? [{ label: d.origin === 'sharepoint' ? 'Open in SharePoint ↗' : 'Open ↗', href: d.url }]
      : d.origin === 'kb' && d.url ? [{ label: 'Open in emery yates ↗', href: d.url }] : [],
  })
}

export function DocViewerHost() {
  const [v, setV] = useState<View | null>(null)
  useEffect(() => {
    const on = (e: Event) => setV((e as CustomEvent<View>).detail)
    window.addEventListener('sleepo:view', on); return () => window.removeEventListener('sleepo:view', on)
  }, [])
  useEffect(() => {
    if (!v) return
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setV(null) }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', esc)
    return () => { window.removeEventListener('keydown', esc); document.body.style.overflow = prev }
  }, [v])
  const t = useQuery({ queryKey: ['viewtext', v?.textUrl], enabled: !!v?.textUrl, retry: false,
    queryFn: async () => { const r = await fetch(v!.textUrl!); if (!r.ok) throw new Error(String(r.status)); return v!.json ? ((await r.json()).md as string ?? '') : r.text() } })
  if (!v) return null
  const text = v.textUrl ? t.data : undefined
  return (
    <div role="dialog" aria-modal="true" aria-label={v.title} onMouseDown={(e) => { if (e.target === e.currentTarget) setV(null) }}
      className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-black/40 px-3 py-8 md:py-14">
      <div className="w-full max-w-[860px] overflow-clip rounded-xl border border-line bg-panel shadow-2xl">
        <header className="sticky top-0 flex items-start gap-3 border-b border-line bg-panel px-5 py-3">
          <FileText size={18} className="mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-[16px] font-semibold leading-snug [overflow-wrap:anywhere]">{v.title}</div>
            {v.sub && <div className="mt-0.5 text-[12.5px] text-ink2 [overflow-wrap:anywhere]">{v.sub}</div>}
          </div>
          {v.actions?.map((a) => a.href
            ? <a key={a.label} href={a.href} target={a.href.startsWith('http') ? '_blank' : undefined} rel="noopener" onClick={() => { if (!a.href!.startsWith('http')) setV(null) }} className={btnClass('outline', 'sm', 'shrink-0')}>{a.label}</a>
            : <button key={a.label} onClick={a.run} className={btnClass('outline', 'sm', 'shrink-0')}>{a.label}</button>)}
          <button onClick={() => setV(null)} aria-label="Close" title="Close (Esc)" className={btnClass('ghost', 'icon')}><X size={18} /></button>
        </header>
        <div className="px-5 py-4 md:px-7">
          {v.textUrl && t.isLoading ? <Loading />
            : text != null ? (v.md ? <Markdown base={v.base}>{text}</Markdown> : <pre className="whitespace-pre-wrap font-sans text-[14px] leading-relaxed">{text}</pre>)
            : v.fallback ? <><p className="mb-3 text-[13px] text-ink2">Only a preview is stored for this document.</p><Markdown>{v.fallback}</Markdown></>
            : <p className="text-[13.5px] text-ink2">No text is stored for this document, so it can’t be shown here.</p>}
        </div>
      </div>
    </div>
  )
}
