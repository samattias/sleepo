// One person, organisation or initiative across every source: open items with them, (for accounts) the Salesforce deals
// and the people involved, then the timeline of mail, chat, meetings, calendar and documents linked to them.
// viewEntity() opens it from anywhere; <EntityPanelHost /> in the layout shows it as a pop-up (Esc, X or click outside).
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Box, Building2, CalendarDays, ExternalLink, FileText, Map as MapIcon, Mail, MessageSquare, Target, Ticket, TrendingUp, User, Video, X, type LucideIcon } from 'lucide-react'
import { api, type EntityView } from '@/lib/api'
import { btnClass, Loading } from './ui'
import { TZ, LOCALE } from '@/lib/time'

export type EntityType = 'person' | 'org' | 'initiative' | 'doc' | 'product' | 'roadmap' | 'ticket'
type Ref = { type: EntityType; id: number }
export function viewEntity(type: Ref['type'], id: number) { window.dispatchEvent(new CustomEvent<Ref>('sleepo:entity', { detail: { type, id } })) }

const ICON: Record<string, LucideIcon> = { mail: Mail, sent: Mail, chat: MessageSquare, channel: MessageSquare, teams: MessageSquare, note: Video, event: CalendarDays, doc: FileText, opportunity: TrendingUp }
const day = (iso?: string | null) => { try { return iso ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(iso)) : '' } catch { return '' } }
// how the item is linked (assist/entities.py ROLE_RANK); the evidence is in the tooltip
const ROLE: Record<string, string> = { from: 'sent it', author: 'wrote it', speaker: 'spoke', dm: 'DM', organizer: 'organised', to: 'to', cc: 'cc', attendee: 'attended',
  invitee: 'invited', account: 'account', member: 'in the chat', domain: 'by domain', mentioned: 'mentioned', keyword: 'keyword', shared: 'shared it', owner: 'owner', filed: 'filed', discussed: 'discussed' }
const KIND = { reply: 'Reply owed', promise: 'You owe', waiting: 'Owed to you', decision: 'Decision' } as const

export function EntityPanelHost() {
  const [ref, setRef] = useState<Ref | null>(null)
  useEffect(() => {
    const on = (e: Event) => setRef((e as CustomEvent<Ref>).detail)
    window.addEventListener('sleepo:entity', on); return () => window.removeEventListener('sleepo:entity', on)
  }, [])
  useEffect(() => {
    if (!ref) return
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setRef(null) }
    window.addEventListener('keydown', esc); return () => window.removeEventListener('keydown', esc)
  }, [ref])
  const q = useQuery({ queryKey: ['entity', ref?.type, ref?.id], queryFn: () => api.entity(ref!.type, ref!.id), enabled: !!ref })
  if (!ref) return null
  return (
    <div role="dialog" aria-modal="true" onMouseDown={(e) => { if (e.target === e.currentTarget) setRef(null) }}
      className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-black/40 px-3 py-8 md:py-14">
      <div className="w-full max-w-[860px] overflow-clip rounded-xl border border-line bg-panel shadow-2xl">
        {!q.data ? <div className="p-5">{q.isError ? 'Could not load this.' : <Loading />}</div> : <Body v={q.data} close={() => setRef(null)} />}
      </div>
    </div>
  )
}

function Body({ v, close }: { v: EntityView; close: () => void }) {
  const e = v.entity
  const Icon = ({ org: Building2, initiative: Target, doc: FileText, product: Box, roadmap: MapIcon, ticket: Ticket } as Record<string, LucideIcon>)[v.type] ?? User
  const sub = v.type === 'org' ? [e.kind === 'account' ? 'Salesforce account' : e.kind === 'external' ? 'Organisation (from mail)' : e.kind, e.region, (e.domains ?? []).join(', ')].filter(Boolean).join(' · ')
    : v.type === 'person' ? (e.title || e.role || '') : v.type === 'ticket' ? ['Jira issue', e.issue_type, e.status].filter(Boolean).join(' · ')
    : ({ doc: 'Document', product: 'Product', roadmap: 'Roadmap item' } as Record<string, string>)[v.type] ?? ''
  const opps = (e.opportunities ?? []).filter((o) => o.is_open !== false)
  return (
    <>
      <header className="sticky top-0 flex items-start gap-3 border-b border-line bg-panel px-5 py-3">
        <Icon size={18} className="mt-1 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-[17px] font-semibold leading-snug">{e.name}</div>
          <div className="mt-0.5 text-[12.5px] text-ink2">{sub}{sub ? ' · ' : ''}{v.last_activity ? `last contact ${day(v.last_activity)}` : v.type === 'person' || v.type === 'org' ? 'no mail or meeting contact on record' : ''}
            {e.url && <> · <a href={e.url} target={e.url.startsWith('http') ? '_blank' : undefined} rel="noopener" className="inline-flex items-center gap-1">Open<ExternalLink size={11} /></a></>}</div>
        </div>
        <button onClick={close} aria-label="Close" title="Close (Esc)" className={btnClass('ghost', 'icon')}><X size={18} /></button>
      </header>
      <div className="space-y-5 px-5 py-4">
        {opps.length > 0 && <section>
          <h3 className="mb-1.5 text-[13px] font-semibold">Open deals</h3>
          <div className="border border-line">{opps.map((o, i) => (
            <div key={i} className="flex flex-wrap gap-x-3 border-b border-line2 px-3 py-2 text-[13px] last:border-b-0">
              <span className="font-medium">{o.sale_type || 'Deal'}</span><span>{o.stage}</span>
              <span className="tabular-nums">{o.currency} {Math.round(o.acv || 0).toLocaleString(LOCALE)}</span>
              <span className="ml-auto text-ink2">closes {o.close_date}</span>
            </div>))}</div>
        </section>}
        {v.open.length > 0 && <section>
          <h3 className="mb-1.5 text-[13px] font-semibold">Open items · {v.open.length}</h3>
          <div className="border border-line">{v.open.map((l) => (
            <a key={l.id} href="#/loops" onClick={close} className="flex gap-3 border-b border-line2 px-3 py-2 text-[13px] text-ink no-underline last:border-b-0 hover:bg-panel2">
              <span className="w-[86px] shrink-0 text-ink2">{KIND[l.kind]}</span>
              <span className="min-w-0 flex-1">{l.title}</span>
              <span className="shrink-0 text-ink2">{l.age_days != null ? `${l.age_days}d` : ''}</span>
            </a>))}</div>
        </section>}
        {(e.people ?? []).length > 0 && <section>
          <h3 className="mb-1.5 text-[13px] font-semibold">People involved</h3>
          <div className="flex flex-wrap gap-1.5">{e.people!.map((p) => (
            <button key={p.id} onClick={() => viewEntity('person', p.id)} className="rounded-full border border-line px-2.5 py-0.5 text-[12.5px] hover:border-ink">{p.name} <span className="text-ink2">{p.n}</span></button>))}</div>
        </section>}
        {(e.links ?? []).length > 0 && <section>
          <h3 className="mb-1.5 text-[13px] font-semibold">Linked to</h3>
          <div className="flex flex-wrap gap-1.5">{e.links!.map((l) => (
            <button key={`${l.entity_type}-${l.entity_id}`} onClick={() => viewEntity(l.entity_type as EntityType, l.entity_id)} title={l.reason ?? ''} className="rounded-full border border-line px-2.5 py-0.5 text-[12.5px] hover:border-ink">{l.name}{l.role ? <span className="text-ink2"> · {l.role}</span> : null}</button>))}</div>
        </section>}
        {(v.spoke ?? []).length > 0 && <section>
          <h3 className="mb-1.5 text-[13px] font-semibold">What they said in meetings</h3>
          <div className="border border-line">{v.spoke!.slice(0, 3).map((m) => (
            <div key={m.meeting_id} className="border-b border-line2 px-3 py-2 last:border-b-0">
              <a href={`#/meetings/m-${m.meeting_id}`} onClick={close} className="text-[13px] font-medium">{m.title}</a>
              <span className="ml-2 text-[12px] text-ink2">{day(m.starts_at)} · {Math.round(m.share * 100)}%</span>
              {m.points.slice(0, 3).map((p, i) => <a key={i} href={`#/meetings/m-${m.meeting_id}?t=${p.t}`} onClick={close} className="block text-[12.5px] font-normal text-ink no-underline hover:underline"><span className="mr-1.5 tabular-nums text-ink2">{p.clock}</span>{p.text}</a>)}
            </div>))}</div>
        </section>}
        <section>
          <h3 className="mb-1.5 text-[13px] font-semibold">Timeline · {v.timeline.length}{v.timeline.length >= 60 ? '+' : ''}</h3>
          {v.timeline.length === 0 ? <p className="text-[13px] text-ink2">Nothing linked yet.</p> : (
            <ol className="border-l border-line pl-4">{v.timeline.map((t) => { const I = ICON[t.kind] ?? FileText; return (
              <li key={t.id} className="relative pb-3 last:pb-0">
                <span className="absolute -left-[22px] top-1 grid size-3 place-items-center rounded-full border border-line bg-panel" />
                <div className="flex items-baseline gap-2 text-[12px] text-ink2"><I size={12} className="shrink-0 self-center" />{t.label}<span>·</span>{day(t.ts)}{t.from && <><span>·</span><span className="truncate">{t.from}</span></>}
                  {t.link?.role && ROLE[t.link.role] && <span title={t.link.reason ?? ''} className="rounded-full border border-line px-1.5 text-[11px]">{ROLE[t.link.role]}</span>}</div>
                {t.url ? <a href={t.url} target={t.url.startsWith('http') ? '_blank' : undefined} rel="noopener" onClick={() => { if (!t.url.startsWith('http')) close() }} className="text-[13.5px] font-medium">{t.title || '(untitled)'}</a>
                  : <div className="text-[13.5px] font-medium">{t.title || '(untitled)'}</div>}
                {t.snippet && <p className="line-clamp-2 text-[12.5px] text-ink2">{t.snippet}</p>}
              </li>) })}</ol>)}
        </section>
      </div>
    </>
  )
}
