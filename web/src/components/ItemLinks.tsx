// "Linked to": everyone and everything one email, message or meeting is linked to (assist/entities.py), each with how
// (sent it, spoke, mentioned...) and the evidence on hover. Clicking opens it; the cross tells the linker it is wrong.
// collapsible (the Inbox): one quiet line naming the first few, opened on a click (Sam, 22 Oct 2026: the chips crowded the thread).
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, X } from 'lucide-react'
import { api, type ItemLink } from '@/lib/api'
import { viewEntity, type EntityType } from './EntityPanel'

const ROLE: Record<string, string> = { from: 'sent it', author: 'wrote it', speaker: 'spoke', dm: 'DM', organizer: 'organised', to: 'to', cc: 'cc', attendee: 'attended',
  invitee: 'invited', account: 'account', member: 'in the chat', domain: 'domain', mentioned: 'mentioned', keyword: 'keyword', shared: 'shared', discussed: 'discussed', owner: 'owner', filed: 'filed' }
const TYPE: Record<string, string> = { person: 'People', org: 'Organisations', initiative: 'Initiatives', doc: 'Documents', product: 'Products', roadmap: 'Roadmap', ticket: 'Jira' }

// onClose (the Inbox, opened from the email's ⋯ menu, Sam, 18 Nov 2026): shown open, its label closes it, and it says so
// when nothing is linked rather than showing nothing.
export function ItemLinks({ itemId, collapsible = false, onClose }: { itemId: number; collapsible?: boolean; onClose?: () => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(!collapsible)
  const q = useQuery({ queryKey: ['itemLinks', itemId], queryFn: () => api.itemLinks(itemId) })
  const rows = (q.data ?? []).filter((l) => l.name && (l.verdict === 'confirmed' || l.confidence >= 0.6))
  const close = onClose && <button onClick={onClose} aria-label="Close the links" title="Close" className="inline-flex items-center gap-1 text-ink2 hover:text-ink">Linked to<X size={12} aria-hidden /></button>
  if (!rows.length) return onClose && q.data ? <div className="mt-2 flex items-center gap-2 text-[12.5px]">{close}<span className="text-ink3">nothing yet</span></div> : null
  const wrong = async (l: ItemLink) => {
    if (l.entity_type === 'person' || l.entity_type === 'org' || l.entity_type === 'initiative') await api.linkVerdict(itemId, l.entity_type, l.entity_id, 'rejected')
    else await api.linkVerdictAny(itemId, l.entity_type, l.entity_id, 'rejected')
    qc.invalidateQueries({ queryKey: ['itemLinks', itemId] }); qc.invalidateQueries({ queryKey: ['entity'] })
  }
  const groups = Object.keys(TYPE).map((t) => [t, rows.filter((r) => r.entity_type === t)] as const).filter(([, v]) => v.length)
  if (!open) {
    const names = groups.flatMap(([, v]) => v).map((l) => l.name)
    return (
      <button onClick={() => setOpen(true)} aria-expanded={false} className="mt-2 inline-flex max-w-full items-center gap-1.5 text-left text-[12.5px] text-ink2 hover:text-ink">
        <span className="shrink-0">Linked to</span>
        <span className="min-w-0 truncate text-ink">{names.slice(0, 3).join(', ')}{names.length > 3 ? ` +${names.length - 3}` : ''}</span>
        <ChevronDown size={13} aria-hidden className="shrink-0" />
      </button>)
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
      {close || (collapsible ? <button onClick={() => setOpen(false)} aria-expanded className="inline-flex items-center gap-1 text-ink2 hover:text-ink">Linked to<ChevronDown size={13} aria-hidden className="rotate-180" /></button>
        : <span className="text-ink2">Linked to</span>)}
      {groups.map(([t, v]) => (
        <span key={t} className="flex flex-wrap items-center gap-1">
          {v.map((l) => (
            <span key={`${l.entity_type}-${l.entity_id}`} title={[ROLE[l.role ?? ''] ?? l.role, l.reason].filter(Boolean).join(' · ')} className="group inline-flex items-center rounded-full border border-line pl-2 hover:border-ink">
              <button onClick={() => viewEntity(l.entity_type as EntityType, l.entity_id)} className="max-w-[220px] truncate py-px">{l.name}{l.role && l.role !== 'mentioned' && ROLE[l.role] ? <span className="text-ink2"> · {ROLE[l.role]}</span> : null}</button>
              <button onClick={() => wrong(l)} aria-label={`Not linked to ${l.name}`} title="Wrong link: remove it" className="px-1 py-px text-ink2 opacity-0 hover:text-ink group-hover:opacity-100"><X size={11} /></button>
            </span>))}
        </span>))}
    </div>
  )
}
