// A document reference rendered as a chip. Click opens the document where it lives: SharePoint, the emery yates,
// the email attachment, Teams/Slack, or the file on this Mac. Briefs write these as [Name](doc:<id>).
import { useQuery } from '@tanstack/react-query'
import { FileSpreadsheet, FileText, FileType, Presentation, File as FileIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { api, type DocItem } from '@/lib/api'
import { isTextDoc, viewDoc } from './DocViewer'

const icon = (ext: string) => (['xls', 'xlsx', 'csv'].includes(ext) ? FileSpreadsheet : ['ppt', 'pptx', 'key'].includes(ext) ? Presentation : ext === 'pdf' ? FileType : ['doc', 'docx', 'md', 'txt'].includes(ext) ? FileText : FileIcon)

export function openDoc(d: DocItem) {
  if (isTextDoc(d)) { viewDoc(d); return }   // never a raw Markdown/text file
  if (d.origin === 'local') { fetch(`/api/local/${d.id.slice(3)}/open`, { method: 'POST' }); return }
  // an email attachment opens the real file: its SharePoint/OneDrive/Teams copy, else the email in Outlook. Never the extracted text.
  const href = d.origin === 'email' ? d.open_url : d.url
  if (href) window.open(href, '_blank', 'noopener')
  else viewDoc(d)
}

export function DocChip({ id, children }: { id: string; children?: ReactNode }) {
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.documents, staleTime: 300_000 })
  const d = docs.data?.find((x) => x.id === id)
  const label = children ?? d?.name ?? id
  if (!d) return <span className="inline-flex max-w-full items-center gap-1 rounded-full border border-line px-2 py-px align-baseline text-[0.92em]" title={docs.data ? 'Document no longer available' : undefined}><FileIcon size={13} className="shrink-0" />{label}</span>
  const Icon = icon(d.ext)
  const where = isTextDoc(d) ? 'Read in SleePO' : d.origin === 'local' ? 'Open on this Mac' : d.origin === 'email' ? `Email attachment · ${d.where} · opens in ${d.open_where || 'Outlook'}` : d.origin === 'kb' ? 'Emery Yates' : d.origin === 'sharepoint' ? `SharePoint · ${d.where}` : d.origin === 'slack' ? 'Slack file' : 'Teams file'
  return (
    <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); openDoc(d) }} title={`${d.name}\n${where}`}
      className="inline-flex max-w-full items-center gap-1 rounded-full border border-line bg-panel px-2 py-px align-baseline text-[0.92em] font-medium text-ink hover:border-ink hover:bg-accent hover:text-onaccent">
      <Icon size={13} className="shrink-0" /><span className="truncate">{label}</span>
    </button>
  )
}
