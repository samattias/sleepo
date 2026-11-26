// Documents: every file Assist pulls in from outside (this Mac, SharePoint/OneDrive, the knowledge base, email and chat
// attachments), as a file browser like Finder or Google Drive: on the left, folders by meaning (recent, Sam's initiatives,
// document types, sensitive, sources); in the middle the list (thumbnail, Claude's one-line summary, source, initiative);
// on the right the document card (what it is, key facts, decisions, people, folder, versions) above a preview.
// Folders are virtual (assist/documents.py): a document sits in its initiative(s), its type and its source at once, and
// Sam can move it to another initiative. Search always covers every folder.
import { useSearchSync } from '@/lib/nav'
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { BookText, Clock, ExternalLink, FileSpreadsheet, FileText, FileType, Folder, FolderOpen, Image as ImageIcon, Layers, Library, Mail, Presentation, File as FileIcon, ShieldAlert, Target } from 'lucide-react'
import { api, type DocItem } from '@/lib/api'
import { cn, usePersisted } from '@/lib/util'
import { btnClass, Empty, Loading, Markdown, selectClass } from '@/components/ui'
import { FilterBar, FilterRow, Opt } from '@/components/FilterBar'
import { TZ, LOCALE } from '@/lib/time'
import { AssistPill } from '@/components/AssistPill'
import { documentPill } from '@/lib/assistPills'

const ORIGIN_LABEL: Record<string, string> = { local: 'This Mac', sharepoint: 'SharePoint', email: 'Email attachment', kb: 'Knowledge base', teams: 'Teams file', slack: 'Slack file' }
const TYPES: { key: string; label: string; exts: string[]; icon: typeof FileText }[] = [
  { key: 'slides', label: 'Decks', exts: ['ppt', 'pptx', 'key', 'odp'], icon: Presentation },
  { key: 'word', label: 'Docs', exts: ['doc', 'docx', 'rtf', 'odt', 'pages'], icon: FileText },
  { key: 'pdf', label: 'PDFs', exts: ['pdf'], icon: FileType },
  { key: 'sheet', label: 'Sheets', exts: ['xls', 'xlsx', 'csv', 'numbers', 'ods'], icon: FileSpreadsheet },
  { key: 'page', label: 'Pages', exts: ['md', 'html', 'htm', 'txt'], icon: BookText },
]
const typeOf = (ext: string) => TYPES.find((t) => t.exts.includes(ext))?.key ?? (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext) ? 'image' : 'other')
const iconOf = (d: DocItem) => { const k = typeOf(d.ext); return k === 'image' ? ImageIcon : d.origin === 'email' && k === 'other' ? Mail : TYPES.find((t) => t.key === k)?.icon ?? FileIcon }
const date = (ts: string) => ts ? new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(ts)) : ''
const titleOf = (d: DocItem) => d.card?.title || d.name.replace(/\.[a-z0-9]{2,5}$/i, '')
const thumbable = (d: DocItem) => d.origin === 'local' && (d.view === 'pdf' || d.view === 'quicklook' || d.view === 'image')

// ---------------------------------------------------------------- folders
const RECENT_DAYS = 14
const TYPE_FOLDERS: { key: string; label: string; kinds: string[] }[] = [
  { key: 'decks', label: 'Decks', kinds: ['deck'] },
  { key: 'plans', label: 'Plans, proposals & briefs', kinds: ['plan', 'proposal', 'brief'] },
  { key: 'reports', label: 'Reports & notes', kinds: ['report', 'notes'] },
  { key: 'sheets', label: 'Spreadsheets', kinds: ['spreadsheet'] },
  { key: 'legal', label: 'Contracts & policies', kinds: ['contract', 'policy'] },
  { key: 'other', label: 'Forms & other', kinds: ['form', 'other'] },
]
const SOURCE_FOLDERS: { key: string; label: string; origins: DocItem['origin'][] }[] = [
  { key: 'local', label: 'This Mac', origins: ['local'] }, { key: 'sharepoint', label: 'SharePoint & OneDrive', origins: ['sharepoint'] },
  { key: 'email', label: 'Email attachments', origins: ['email'] }, { key: 'chat', label: 'Teams & Slack', origins: ['teams', 'slack'] },
  { key: 'kb', label: 'Knowledge base', origins: ['kb'] },
]
const MEDIA = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'heic', 'mp3', 'm4a', 'wav', 'mp4', 'mov', 'zip'])
const media = (d: DocItem) => MEDIA.has(d.ext)   // screenshots, recordings and archives shared in chats: their own folder
// the knowledge base is reference material and media are not documents: both have their own folder, not the working list
const working = (d: DocItem) => d.origin !== 'kb' && !media(d)
const sensitive = (d: DocItem) => d.folder?.sensitivity === 'hr-legal' || d.folder?.sensitivity === 'personal'
const recentCut = () => new Date(Date.now() - RECENT_DAYS * 864e5).toISOString()
function inFolder(d: DocItem, key: string, cut: string) {
  const [k, v] = key.split(':')
  if (k === 'all') return working(d)
  if (k === 'recent') return working(d) && (d.ts ?? '') >= cut
  if (k === 'ini') return working(d) && (v ? d.folder?.initiatives.includes(v) : !d.folder?.initiatives.length)
  if (k === 'type') return v === 'media' ? media(d) : working(d) && (TYPE_FOLDERS.find((t) => t.key === v)?.kinds ?? []).includes(d.folder?.kind ?? 'other')
  if (k === 'sens') return sensitive(d)
  if (k === 'src') return (SOURCE_FOLDERS.find((x) => x.key === v)?.origins ?? []).includes(d.origin)
  return true
}

export function Documents({ open: rawOpen }: { open?: string } = {}) {
  const open = rawOpen?.split('?')[0]
  const q = useQuery({ queryKey: ['documents'], queryFn: api.documents })
  const ini = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })
  const nav = useNavigate()
  const [f, setF] = usePersisted('assist-docs3', { folder: 'recent', q: '', carded: false, latest: true })
  const [sel, setSel] = useState<string | null>(open ?? null)
  useEffect(() => { if (open) setSel(open) }, [open])
  useSearchSync('open', sel)   // the open document stays in the address: Back returns to it (lib/nav.ts)
  const iniName = useMemo(() => new Map((ini.data ?? []).map((x) => [x.slug, x.name])), [ini.data])
  const all = q.data ?? []
  const cut = useMemo(recentCut, [q.data])
  // the version and summary filters apply everywhere; the folder narrows the list; a search looks in every folder
  const base = useMemo(() => all.filter((d) => (!f.carded || d.card) && (!f.latest || d.card?.is_current !== 0)), [all, f.carded, f.latest])
  const searching = !!f.q.trim()
  const list = useMemo(() => {
    const re = searching ? new RegExp(f.q.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') : null
    return base.filter((d) => (re ? re.test(`${d.name} ${d.card?.title ?? ''} ${d.card?.summary ?? ''} ${d.where} ${d.author} ${d.preview}`) : inFolder(d, f.folder, cut)))
  }, [base, f.folder, f.q, cut, searching])
  const count = (key: string) => base.filter((d) => inFolder(d, key, cut)).length
  const folders = useMemo(() => {
    const inis = (ini.data ?? []).map((x) => ({ key: `ini:${x.slug}`, label: x.name }))
    return [
      { head: '', rows: [{ key: 'recent', label: `Recent · ${RECENT_DAYS} days`, icon: Clock }, { key: 'all', label: 'All documents', icon: Library }, { key: 'sens', label: 'Sensitive (HR, legal, personal)', icon: ShieldAlert }] },
      { head: 'Initiatives', rows: [...inis.map((x) => ({ ...x, icon: Target })), { key: 'ini:', label: 'No initiative', icon: Folder }] },
      { head: 'Types', rows: [...TYPE_FOLDERS.map((t) => ({ key: `type:${t.key}`, label: t.label, icon: Folder })), { key: 'type:media', label: 'Images & media', icon: ImageIcon }] },
      { head: 'Sources', rows: SOURCE_FOLDERS.map((x) => ({ key: `src:${x.key}`, label: x.label, icon: x.key === 'kb' ? BookText : Folder })) },
    ]
  }, [ini.data])
  const folderLabel = folders.flatMap((g) => g.rows).find((r) => r.key === f.folder)?.label ?? 'Documents'
  useEffect(() => { if (!sel && list.length && matchMedia('(min-width: 768px)').matches) setSel(list[0].id) }, [list, sel])
  const cur = all.find((d) => d.id === sel) ?? null
  const carded = all.filter((d) => d.card).length
  const pick = (key: string) => { setF({ ...f, folder: key, q: '' }); setSel(null) }

  if (q.isError) return <Empty>Could not load documents.</Empty>
  if (!q.data) return <Loading />
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-4 py-2">
        <h1 className="mr-1 text-[17px] font-semibold tracking-[-0.01em]">Documents</h1>
        {/* below the large-screen breakpoint the folder rail becomes a picker */}
        <select value={f.folder} onChange={(e) => pick(e.target.value)} aria-label="Folder" className={cn(selectClass, 'lg:hidden')}>
          {folders.map((g) => <optgroup key={g.head || 'top'} label={g.head || 'Library'}>{g.rows.map((r) => <option key={r.key} value={r.key}>{r.label} ({count(r.key)})</option>)}</optgroup>)}
        </select>
        <FilterBar className="mb-0 min-w-0 flex-1" search={f.q} onSearch={(v) => setF({ ...f, q: v })} placeholder="Search every folder…"
          tokens={[
            ...(f.carded ? [{ label: 'Summarised', onRemove: () => setF({ ...f, carded: false }) }] : []),
            ...(!f.latest ? [{ label: 'All versions', onRemove: () => setF({ ...f, latest: true }) }] : []),
          ]}
          onClear={() => setF({ ...f, carded: false, latest: true })}
          right={<span className="tabular-nums">{list.length.toLocaleString()} files</span>}>
          <FilterRow label="Summary"><Opt on={!f.carded} onClick={() => setF({ ...f, carded: false })}>Any</Opt><Opt on={f.carded} count={carded} onClick={() => setF({ ...f, carded: true })}>Summarised</Opt></FilterRow>
          <FilterRow label="Versions"><Opt on={f.latest} onClick={() => setF({ ...f, latest: true })}>Latest</Opt><Opt on={!f.latest} onClick={() => setF({ ...f, latest: false })}>All</Opt></FilterRow>
        </FilterBar>
      </div>

      <div className="grid min-h-0 flex-1 md:grid-cols-[minmax(300px,400px)_minmax(0,1fr)] lg:grid-cols-[230px_minmax(300px,400px)_minmax(0,1fr)]">
        <nav aria-label="Folders" className="hidden min-h-0 overflow-auto border-r border-line bg-panel py-2 lg:block">
          {folders.map((g) => (
            <div key={g.head || 'top'} className="mb-2">
              {g.head && <div className="px-4 pb-1 pt-2 text-[12px] font-semibold text-ink">{g.head}</div>}
              {g.rows.map((r) => { const n = count(r.key); const on = !searching && f.folder === r.key; const I = r.icon; return (
                <button key={r.key} onClick={() => pick(r.key)} aria-current={on ? 'true' : undefined}
                  className={cn('flex w-full items-center gap-2 border-l-2 px-3.5 py-1.5 text-left text-[13px]', on ? 'border-accent bg-accentbg font-medium' : 'border-transparent hover:bg-panel2', !n && 'text-ink3')}>
                  <I size={14} aria-hidden className="shrink-0 text-ink2" /><span className="min-w-0 flex-1 truncate">{r.label}</span><span className="tabular-nums text-[12px] text-ink2">{n}</span>
                </button>) })}
            </div>))}
        </nav>
        <div className={cn('min-h-0 overflow-auto border-line bg-panel md:border-r', sel && 'max-md:hidden')}>
          <div className="sticky top-0 z-[1] border-b border-line bg-panel px-4 py-2 text-[12.5px]">
            {searching ? <span><b>Search results</b> <span className="text-ink2">· every folder · {list.length}</span></span>
              : <span><b>{folderLabel}</b> <span className="text-ink2">· {list.length}</span></span>}
          </div>
          {list.length === 0 && <div className="p-4"><Empty>{searching ? 'No documents match.' : 'Nothing in this folder.'}</Empty></div>}
          {list.slice(0, 400).map((d) => <Row key={d.id} d={d} on={d.id === sel} onClick={() => { setSel(d.id); if (open) nav({ to: '/documents', search: {} }) }} iniName={iniName} />)}
          {list.length > 400 && <div className="p-3 text-[12px] text-ink3">Showing the newest 400. Pick a folder or search to narrow it down.</div>}
        </div>
        <div className={cn('min-h-0 overflow-hidden bg-bg', !sel && 'max-md:hidden')}>
          {cur ? <Preview key={cur.id} d={cur} iniName={iniName} onBack={() => setSel(null)} onPick={setSel} all={all} /> : <div className="grid h-full place-items-center text-[13.5px] text-ink3">Select a document.</div>}
        </div>
      </div>
    </div>
  )
}

function Row({ d, on, onClick, iniName }: { d: DocItem; on: boolean; onClick: () => void; iniName: Map<string, string> }) {
  const I = iconOf(d)
  const [thumbOk, setThumbOk] = useState(true)
  return (
    <button onClick={onClick} aria-current={on ? 'true' : undefined}
      className={cn('flex w-full gap-3 border-b border-l-2 border-b-line2 py-2.5 pl-3.5 pr-4 text-left', on ? 'border-l-accent bg-accentbg' : 'border-l-transparent hover:bg-panel2')}>
      <span className="grid h-[52px] w-[44px] shrink-0 place-items-center overflow-hidden border border-line bg-panel2">
        {thumbable(d) && thumbOk ? <img src={`/api/preview/${d.id}/thumb.png?s=160`} alt="" loading="lazy" onError={() => setThumbOk(false)} className="max-h-full max-w-full object-contain" /> : <I size={18} className="text-ink3" aria-hidden />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2"><span className="truncate text-[13.5px] font-medium">{titleOf(d)}</span>
          {sensitive(d) && <ShieldAlert size={12} className="shrink-0 text-ink3" aria-label={d.folder.sensitivity} />}</span>
        <span className="block truncate text-[12.5px] text-ink2">{d.card?.summary || d.where || d.name}</span>
        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11.5px] text-ink3">
          <span className="shrink-0">{ORIGIN_LABEL[d.origin]} · {date(d.ts)}</span>
          {(d.folder?.initiatives ?? []).slice(0, 2).map((s) => <span key={s} className="truncate rounded-full border border-line px-2 leading-[16px]">{iniName.get(s) ?? s}</span>)}
          {(d.card?.versions ?? 1) > 1 && <span className="inline-flex shrink-0 items-center gap-0.5"><Layers size={11} />{d.card!.versions}</span>}
        </span>
      </span>
    </button>
  )
}

const btn = btnClass('outline', 'sm', 'font-normal text-ink')
// Preview | Text: the pill switch's look (components/ui.tsx Segmented), kept inline because either tab may be missing
const seg = 'rounded-full px-2.5 py-0.5 text-[12px] transition-colors'
const segOn = 'bg-panel font-medium text-ink shadow-sm'
const segOff = 'text-ink2 hover:text-ink'
type CardData = NonNullable<Awaited<ReturnType<typeof api.documentCard>>['card']>

function Preview({ d, iniName, onBack, onPick, all }: { d: DocItem; iniName: Map<string, string>; onBack: () => void; onPick: (id: string) => void; all: DocItem[] }) {
  const detail = useQuery({ queryKey: ['docCard', d.id], queryFn: () => api.documentCard(d.id) })
  const c = detail.data?.card
  const canPreview = d.view === 'pdf' || d.view === 'image' || d.view === 'quicklook' || (d.view === 'office-web' && !!detail.data?.office_embed)
  const textUrl = d.origin === 'email' ? d.ref : (['kb', 'sharepoint', 'local'].includes(d.origin) ? `/api/documents/${d.id}/text` : null)
  // SharePoint's Office viewer is slow and needs a Microsoft 365 sign-in: open on the text when there is some, and load the
  // viewer only when Sam asks for it
  const [tab, setTab] = useState<'preview' | 'text'>(!d.view || d.view === 'text' || (d.view === 'office-web' && d.has_text) ? 'text' : 'preview')
  const [office, setOffice] = useState(false)
  const [showCard, setShowCard] = useState(true)
  const local = (reveal: boolean) => fetch(`/api/local/${d.id.slice(3)}/open${reveal ? '?reveal=1' : ''}`, { method: 'POST' })
  const primary = btnClass('primary')
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line bg-panel px-4 py-1.5">
        <button onClick={onBack} className={cn(btn, 'md:hidden')}>← Back</button>
        {d.origin === 'local' && <><button onClick={() => local(false)} className={primary}><ExternalLink size={13} />Open</button>
          <button onClick={() => local(true)} className={btn}><FolderOpen size={13} />Show in Finder</button></>}
        {d.origin === 'sharepoint' && d.url && <a href={d.url} target="_blank" rel="noopener" className={primary}><ExternalLink size={13} />Open in SharePoint</a>}
        {d.origin === 'kb' && d.url && <a href={d.url} target="_blank" rel="noopener" className={btn}><ExternalLink size={13} />Open in knowledge base</a>}
        {d.origin === 'email' && <>{d.open_url && <a href={d.open_url} target="_blank" rel="noopener" className={primary}><ExternalLink size={13} />Open in {d.open_where || 'Outlook'}</a>}
          {d.mail_id && <Link to="/inbox" search={{ open: d.mail_id }} className={btn}><Mail size={13} />Show the email</Link>}</>}
        {(d.origin === 'teams' || d.origin === 'slack') && d.url && <a href={d.url} target="_blank" rel="noopener" className={btn}><ExternalLink size={13} />Open in {d.origin === 'teams' ? 'Teams' : 'Slack'}</a>}
        <div role="tablist" className="ml-auto inline-flex rounded-full bg-panel2 p-0.5">
          {canPreview && <button role="tab" aria-selected={tab === 'preview'} onClick={() => setTab('preview')} className={cn(seg, tab === 'preview' ? segOn : segOff)}>Preview</button>}
          {textUrl && <button role="tab" aria-selected={tab === 'text' || !canPreview} onClick={() => setTab('text')} className={cn(seg, tab === 'text' || !canPreview ? segOn : segOff)}>Text</button>}
        </div>
      </div>

      <div className="max-h-[45%] overflow-auto border-b border-line bg-panel px-5 py-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-[17px] font-semibold leading-snug">{c?.title || titleOf(d)}</h2>
            <div className="mt-0.5 truncate text-[12px] text-ink3">{d.name} · {ORIGIN_LABEL[d.origin]}{d.where ? ` · ${d.where}` : ''} · {date(d.ts)}{d.author ? ` · ${d.author}` : ''}</div>
          </div>
          {c && <button onClick={() => setShowCard(!showCard)} className="shrink-0 text-[12px] text-ink3 hover:text-ink">{showCard ? 'Hide summary' : 'Show summary'}</button>}
        </div>
        {d.origin !== 'kb' && <FolderPicker d={d} iniName={iniName} />}
        {c && showCard && <Card c={c} iniName={iniName} onPick={onPick} all={all} />}
        {!c && detail.data && <p className="mt-1.5 text-[12.5px] text-ink3">{d.has_text ? 'Not summarised yet.' : 'No text stored.'}</p>}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden bg-panel2">
        {tab === 'preview' && canPreview
          ? d.view === 'office-web' && !office ? <OfficeGate d={d} onLoad={() => setOffice(true)} /> : <Frame d={d} embed={detail.data?.office_embed ?? null} />
          : <TextView url={textUrl} d={d} />}
      </div>
      {/* the assistant pill (Sam, 16 Nov 2026), where Messages has its own: ask about the document, review it, feedback to its
          author, with the document's chip (its text and summary); no field in this narrow pane (a typed question goes through the
          floating button, whose chip is the open document); clear of that button */}
      <div className="border-t border-line bg-panel py-2.5 pl-4 pr-20"><AssistPill key={d.id} target={{ kind: 'document', ref: d.id }} {...documentPill()} field={undefined} /></div>
    </div>
  )
}

// Which initiative folder a document sits in; Sam can move it, and his choice then wins over Claude's filing.
function FolderPicker({ d, iniName }: { d: DocItem; iniName: Map<string, string> }) {
  const qc = useQueryClient()
  const move = useMutation({ mutationFn: (slug: string) => api.documentFolder(d.id, slug ? [slug] : []),
    onSettled: () => qc.invalidateQueries({ queryKey: ['documents'] }) })
  const by = d.folder?.by
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px]">
      <label className="inline-flex items-center gap-1.5 text-ink2"><FolderOpen size={13} aria-hidden />Folder
        <select value={d.folder?.initiatives[0] ?? ''} disabled={move.isPending} onChange={(e) => move.mutate(e.target.value)}
          className={cn(selectClass, 'py-0.5')}>
          <option value="">No initiative</option>
          {[...iniName].map(([slug, name]) => <option key={slug} value={slug}>{name}</option>)}
        </select></label>
      <span className="text-ink3">{move.isPending ? 'Moving…' : by === 'sam' ? 'moved by you' : by === 'card' || by === 'claude' ? 'filed by Claude' : by === 'links' ? 'from its links' : ''}</span>
    </div>
  )
}

// SharePoint / OneDrive: the Office viewer only on request, so choosing a document is instant
function OfficeGate({ d, onLoad }: { d: DocItem; onLoad: () => void }) {
  return (
    <div className="grid h-full place-items-center p-6 text-center">
      <div className="max-w-[420px]">
        <p className="text-[13.5px] text-ink2">The preview comes from Office for the web. It takes a few seconds and needs your Microsoft 365 sign-in in this browser.</p>
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          <button onClick={onLoad} className={btn}>Load preview</button>
          {d.url && <a href={d.url} target="_blank" rel="noopener" className={cn(btn, 'border-accent bg-accent font-medium text-onaccent hover:brightness-95')}><ExternalLink size={13} />Open in SharePoint</a>}
        </div>
      </div>
    </div>
  )
}

function Card({ c, iniName, onPick, all }: { c: CardData; iniName: Map<string, string>; onPick: (id: string) => void; all: DocItem[] }) {
  return (
    <div className="mt-2.5 text-[13.5px]">
      <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[12px]">
        <span className="rounded-full border border-ink px-2 font-medium capitalize">{c.kind}</span>
        {c.sensitivity !== 'normal' && <span className="inline-flex items-center gap-1 rounded-full border border-hot px-2 text-hot"><ShieldAlert size={11} />{c.sensitivity}</span>}
        {c.is_current === 0 && <span className="rounded-full border border-line px-2 text-ink2">superseded by a newer version</span>}
        {c.doc_date && <span className="text-ink3">about {date(c.doc_date)}</span>}
        {c.initiatives.map((g) => <Link key={g.slug} to="/initiatives/$slug" params={{ slug: g.slug }} title={g.why} className="rounded-full border border-line px-2 text-ink no-underline hover:border-ink">{iniName.get(g.slug) ?? g.slug}</Link>)}
      </div>
      <p className="leading-relaxed">{c.summary}</p>
      {(c.facts.length > 0 || c.decisions.length > 0) && <div className="mt-2 grid gap-x-6 gap-y-1 md:grid-cols-2">
        {c.facts.length > 0 && <div><div className="mb-0.5 text-[12px] font-semibold text-ink">Key facts</div><ul className="list-disc space-y-0.5 pl-4 text-[13px] text-ink2">{c.facts.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
        {c.decisions.length > 0 && <div><div className="mb-0.5 text-[12px] font-semibold text-ink">Decisions and asks</div><ul className="list-disc space-y-0.5 pl-4 text-[13px] text-ink2">{c.decisions.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
      </div>}
      {(c.people.length > 0 || c.orgs.length > 0) && <div className="mt-2 text-[12px] text-ink3">{[...c.people, ...c.orgs].slice(0, 12).join(' · ')}</div>}
      {(c.other_versions?.length ?? 0) > 0 && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-ink3"><Layers size={12} />Other versions:
        {c.other_versions!.map((id) => { const o = all.find((x) => x.id === id); return o ? <button key={id} onClick={() => onPick(id)} className="rounded-full border border-line px-2 text-ink2 hover:border-ink hover:text-ink">{o.name} · {date(o.ts)}</button> : null })}</div>}
    </div>
  )
}

function Frame({ d, embed }: { d: DocItem; embed: string | null }) {
  if (d.view === 'image') return <div className="grid h-full place-items-center overflow-auto p-4"><img src={`/api/preview/${d.id}/file`} alt={d.name} className="max-h-full max-w-full object-contain shadow" /></div>
  if (d.view === 'pdf') return <iframe title={d.name} src={`/api/preview/${d.id}/file#view=FitH`} className="h-full w-full border-0 bg-white" />
  // Quick Look's HTML rendering: sandboxed (scripts for sheet tabs, no same-origin, no network)
  if (d.view === 'quicklook') return <iframe title={d.name} sandbox="allow-scripts" src={`/api/preview/${d.id}/ql/Preview.html`} className="h-full w-full border-0 bg-white" />
  if (d.view === 'office-web' && embed) return (
    <div className="flex h-full flex-col">
      <iframe title={d.name} src={embed} className="min-h-0 w-full flex-1 border-0 bg-white" />
      <div className="border-t border-line bg-panel px-4 py-1.5 text-[11.5px] text-ink3">Blank or asking to sign in? Use Open in SharePoint.</div>
    </div>)
  return null
}

function TextView({ url, d }: { url: string | null; d: DocItem }) {
  const t = useQuery({ queryKey: ['doctext', url], enabled: !!url, retry: false, queryFn: async () => { const r = await fetch(url!); if (!r.ok) throw new Error(String(r.status)); return r.text() } })
  if (!url) return <div className="p-6 text-[13.5px] text-ink3">No preview stored.</div>
  if (t.isLoading) return <div className="p-6"><Loading /></div>
  if (t.isError || !t.data) return <div className="p-6 text-[13.5px] text-ink3">{d.origin === 'sharepoint' ? 'SleePO has only this file\u2019s name and where it lives. Load the preview, or open it in SharePoint.' : 'No text stored for this file.'}</div>
  return <div className="h-full overflow-auto"><div className="mx-auto max-w-[860px] bg-panel px-8 py-6 text-[14px] leading-relaxed">{['md', 'html', 'htm'].includes(d.ext) || d.origin === 'kb' ? <Markdown>{t.data}</Markdown> : <pre className="whitespace-pre-wrap font-sans">{t.data}</pre>}</div></div>
}
