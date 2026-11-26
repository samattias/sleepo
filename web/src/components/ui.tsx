import type { MouseEvent as ReactMouseEvent, ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link as RouterLink } from '@tanstack/react-router'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn, initials } from '@/lib/util'
import { DocChip } from './DocChip'
import { SleepyLoader } from './Logo'
import { PersonLink } from './PersonLink'
import { isTextName, viewDoc, viewLibrary, viewText } from './DocViewer'
import { api, type Link, type Person, type System } from '@/lib/api'

export const Card = ({ className, children, onClick }: { className?: string; children: ReactNode; onClick?: () => void }) => (
  <div onClick={onClick} className={cn('border border-line bg-panel p-4', onClick && 'cursor-pointer hover:border-ink', className)}>{children}</div>
)
export const H1 = ({ children }: { children: ReactNode }) => <h1 className="mb-4 text-[28px] font-semibold leading-tight tracking-[-0.02em]">{children}</h1>
export const Section = ({ children, right }: { children: ReactNode; right?: ReactNode }) => (
  <h2 className="mb-2.5 mt-6 flex items-center gap-2 text-[15px] font-semibold text-ink first:mt-0">{children}{right && <span className="ml-auto normal-case tracking-normal">{right}</span>}</h2>
)
export const Muted = ({ children, className }: { children: ReactNode; className?: string }) => <p className={cn('text-[12.5px] text-ink3', className)}>{children}</p>
export const Empty = ({ children }: { children: ReactNode }) => <div className="py-4 text-ink3">{children}</div>

const toneDot: Record<string, string> = { good: 'bg-accent ring-1 ring-ink/25', pending: 'bg-hot' }
export const Tag = ({ children, tone = 'plain', className }: { children: ReactNode; tone?: 'good' | 'pending' | 'plain'; className?: string }) => (
  <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2 py-px text-[11.5px] leading-tight text-ink', className)}>
    {tone !== 'plain' && <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', toneDot[tone])} />}{children}
  </span>
)
export function Chip({ on, children, onClick, count }: { on?: boolean; children: ReactNode; onClick?: () => void; count?: number }) {
  return (
    <button onClick={onClick} className={cn('rounded-full border px-2.5 py-1 text-[12.5px]', on ? 'border-ink bg-ink font-medium text-bg' : 'border-line bg-panel text-ink2 hover:border-ink')}>
      {children}{count !== undefined && <span className={cn('ml-1', on ? 'opacity-60' : 'text-ink3')}>{count.toLocaleString()}</span>}
    </button>
  )
}
export const Chips = ({ children, label, right }: { children: ReactNode; label?: string; right?: ReactNode }) => (
  <div className="mb-3 flex flex-wrap items-center gap-1.5">{label && <span className="mr-1 text-[12.5px] text-ink3">{label}</span>}{children}{right && <span className="ml-auto text-[12.5px] text-ink3">{right}</span>}</div>
)
export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => (
  <input {...p} className={cn(inputClass, p.className)} />
)
/** One look for single-line fields and dropdowns (UI review, 30 Oct 2026): rounded like the buttons. */
export const inputClass = 'rounded-full border border-line bg-panel px-3 py-1 text-[12.5px] text-ink outline-none placeholder:text-ink3 focus:border-ink'
/** Menus, dropdowns and dialogs that float over the page: rounded with a soft shadow, like the Refresh menu (27 Oct 2026). */
export const popoverClass = 'overflow-hidden rounded-xl border border-line bg-panel text-ink shadow-lg'
export const selectClass = 'rounded-full border border-line bg-panel py-1 pl-2.5 pr-1.5 text-[12.5px] text-ink outline-none hover:border-ink focus:border-ink'

const healthCls: Record<string, string> = { ok: 'bg-good', stale: 'bg-warn', broken: 'bg-critical', capped: 'bg-serious', planned: 'bg-ink3' }
export const HEALTH_LABEL: Record<string, string> = { ok: 'OK', stale: 'Stale', broken: 'Broken', capped: 'Capped', planned: 'Not pulled yet' }
export const Dot = ({ health, className }: { health: string; className?: string }) => <span className={cn('inline-block size-2 rounded-full ring-1 ring-ink/15', healthCls[health] ?? 'bg-ink3', className)} />
export const Pill = ({ health }: { health: string }) => (
  <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2 py-0.5 text-[12px] text-ink"><Dot health={health} />{HEALTH_LABEL[health] ?? health}</span>
)

export function Avatar({ p, size = 28, className }: { p: Pick<Person, 'name' | 'avatar'>; size?: number; className?: string }) {
  const st = { width: size, height: size }
  return p.avatar
    ? <img src={p.avatar} alt="" style={st} className={cn('shrink-0 rounded-full object-cover', className)} />
    : <span style={{ ...st, fontSize: Math.round(size * 0.38) }} className={cn('inline-flex shrink-0 items-center justify-center rounded-full border border-line bg-panel2 font-semibold text-ink2', className)}>{initials(p.name)}</span>
}

export function SystemIcon({ sys, logos, size = 28 }: { sys: System; logos: Record<string, string>; size?: number }) {
  const uri = sys.logo && logos[sys.logo]
  return uri
    ? <span style={{ width: size, height: size, padding: Math.round(size * 0.12) }} className="inline-flex shrink-0 items-center justify-center overflow-hidden border border-line bg-panel"><img src={uri} alt="" className="size-full object-contain" /></span>
    : <span style={{ width: size, height: size, fontSize: size * 0.4 }} className="inline-flex shrink-0 items-center justify-center bg-ink font-bold text-bg">{sys.mono}</span>
}

export const Links = ({ links }: { links: Link[] }) => (
  <>{links.map((l, i) => <a key={i} href={l.url} target="_blank" rel="noopener" className="whitespace-nowrap text-[12.5px]">{l.label} ↗</a>)}</>
)

// base: the path of the document being shown, so relative links ("../x/y.md") resolve inside the library.
export function Markdown({ children, base }: { children: string; base?: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(url) => (url.startsWith('doc:') ? url : defaultUrlTransform(url))}
        components={{ a: ({ href, children }) => href?.startsWith('doc:') ? <DocChip id={href.slice(4)}>{children}</DocChip>
          : href && isTextName(href) && !href.startsWith('#') ? <MdLink href={href} base={base}>{children}</MdLink>
          : <a href={href} target={href?.startsWith('http') ? '_blank' : undefined} rel="noopener">{children}</a> }}>{children}</ReactMarkdown>
    </div>
  )
}

// "../a/b.md" against "public-docs/docs/x/y.md" -> "public-docs/docs/a/b.md"
function resolvePath(href: string, base?: string) {
  const clean = decodeURI(href.split('#')[0].split('?')[0])
  const parts = (clean.startsWith('/') || !base ? [] : base.split('/').slice(0, -1))
  for (const seg of clean.replace(/^\/+/, '').split('/')) {
    if (seg === '..') parts.pop()
    else if (seg && seg !== '.') parts.push(seg)
  }
  return parts.join('/')
}

// A link to a Markdown or text file never opens the raw file. A library document (memory, briefs, prep, product docs)
// opens in the pop-up; a SharePoint/OneDrive file opens its stored copy in the pop-up, with a button to the original.
function MdLink({ href, base, children }: { href: string; base?: string; children: ReactNode }) {
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.documents, staleTime: 300_000 })
  const lib = useQuery({ queryKey: ['docs'], queryFn: api.docs, staleTime: 300_000 })
  const open = (e: ReactMouseEvent) => {
    e.preventDefault()
    if (/^https?:/i.test(href)) {
      const d = docs.data?.find((x) => x.url && (x.url === href || decodeURI(x.url) === decodeURI(href)))
      if (d) return viewDoc(d)
      return viewText({ title: decodeURI(href.split('/').pop() || href), textUrl: null, md: true, actions: [{ label: 'Open the original ↗', href }] })
    }
    const want = resolvePath(href, base)
    const tail = decodeURI(href).replace(/^(\.\.?\/)+/, '')
    const hit = lib.data?.find((x) => x.path === want) ?? lib.data?.find((x) => x.path && (x.path.endsWith('/' + tail) || x.path === tail))
    if (hit) return viewLibrary(hit.id, hit.title, hit.path)
    viewText({ title: decodeURI(href.split('/').pop() || href), textUrl: null, md: true, fallback: 'This document is not in the library.' })
  }
  return <a href={href} onClick={open}>{children}</a>
}

export function Table({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <Card className="overflow-x-auto px-3 py-1">
      <table className="w-full border-collapse text-[13.5px]">
        <thead><tr className="text-left text-[12.5px] text-ink [&>th]:whitespace-nowrap [&>th]:border-b [&>th]:border-line [&>th]:px-2 [&>th]:py-2 [&>th]:font-medium">{head}</tr></thead>
        <tbody className="[&>tr>td]:border-b [&>tr>td]:border-line2 [&>tr>td]:px-2 [&>tr>td]:py-2.5 [&>tr>td]:align-top">{children}</tbody>
      </table>
    </Card>
  )
}
export const GroupRow = ({ cols, children }: { cols: number; children: ReactNode }) => (
  <tr><td colSpan={cols} className="!bg-panel2 font-semibold">{children}</td></tr>
)

export const Tile = ({ value, label, note }: { value: ReactNode; label: string; note?: ReactNode }) => (
  <Card className="px-4 py-3.5"><div className="text-[32px] font-semibold leading-tight tracking-[-0.03em]">{value}</div><div className="mt-1 text-[13px] font-medium text-ink">{label}</div>{note && <div className="mt-1.5 text-[12px] text-ink3">{note}</div>}</Card>
)
export const Loading = ({ label }: { label?: string } = {}) => <SleepyLoader label={label} />   // the animated mark (components/Logo.tsx)

// The retention period, for text that names it: RETENTION_DAYS in assist/retention.py, served by /api/meta
export function RetentionDays() {
  return <>{useQuery({ queryKey: ['meta'], queryFn: api.meta }).data?.retention_days ?? '…'}</>
}

// ---- shared controls (22 Oct 2026, from the codebase review: six copies of the pill button styles, twelve hand-rolled
// segmented groups). Rounded, borderless until hover; one filled primary per toolbar. Since the UI review (Sam, 30 Oct 2026:
// "some of the pages have pill-shaped buttons, others have square-shaped buttons") every page uses them: buttons and
// switches are pills, page tabs are underlined (PageTabs), fields and dropdowns are rounded (inputClass, selectClass),
// tags are rounded, cards stay square. outline is a pill with a border, for a button standing on its own; icon is round.
type BtnVariant = 'ghost' | 'primary' | 'outline' | 'ink'
const BTN: Record<BtnVariant, string> = {
  ghost: 'text-ink hover:bg-panel2 active:bg-line',
  primary: 'bg-accent font-semibold text-onaccent hover:brightness-95 active:brightness-90',
  outline: 'border border-line text-ink hover:border-ink',
  ink: 'bg-ink text-bg hover:opacity-90',
}
type BtnSize = 'xs' | 'sm' | 'md' | 'icon'
const SIZE: Record<BtnSize, string> = { xs: 'px-2.5 py-0.5 text-[12px]', sm: 'px-3 py-1 text-[12.5px]', md: 'px-3.5 py-1.5 text-[13px]', icon: 'size-7 shrink-0 justify-center' }
export const btnClass = (variant: BtnVariant = 'ghost', size: BtnSize = 'sm', className?: string | false | null) => cn(
  'inline-flex items-center gap-1.5 rounded-full font-medium no-underline transition-[background-color,filter,opacity,border-color] disabled:opacity-60',
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ink',
  SIZE[size], BTN[variant], className)
export function Button({ variant = 'ghost', size = 'sm', className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: BtnSize }) {
  return <button {...p} className={btnClass(variant, size, className)} />
}

/** A pill switch between a few options (Inbox | Sent, Reply | Reply all | Forward, lengths, formats). */
export function Segmented<K extends string | number>({ value, onChange, options, label, size = 'sm', className }: {
  value: K; onChange: (k: K) => void; options: readonly (readonly [K, ReactNode] | readonly [K, ReactNode, string])[]; label?: string; size?: 'sm' | 'md'; className?: string }) {
  return (
    <div role="radiogroup" aria-label={label} className={cn('inline-flex shrink-0 rounded-full bg-panel2 p-0.5', className)}>
      {options.map(([k, l, title]) => (
        <button key={String(k)} role="radio" aria-checked={value === k} title={title} onClick={() => onChange(k)}
          className={cn('inline-flex items-center gap-1.5 rounded-full transition-colors', size === 'sm' ? 'px-2.5 py-0.5 text-[12px]' : 'px-3.5 py-1 text-[13px] font-semibold',
            value === k ? 'bg-panel font-medium text-ink shadow-sm' : 'text-ink2 hover:text-ink')}>{l}</button>))}
    </div>
  )
}

/** Tabs between the sections of one page (Pipeline: Open pipeline | Closed deals; Explore: Graph | Library), underlined, on
 *  the title's row. A tab with `to` is a link (its own address), otherwise a button calling onSelect. */
export function PageTabs<K extends string>({ title, tabs, active, onSelect, right, label }: {
  title: ReactNode; tabs: readonly { key: K; label: ReactNode; to?: string }[]; active: K; onSelect?: (k: K) => void; right?: ReactNode; label?: string }) {
  const cls = (on: boolean) => cn('-mb-px inline-flex items-center gap-1.5 border-b-2 pb-2.5 text-[14px] no-underline', on ? 'border-accent font-semibold text-ink' : 'border-transparent font-normal text-ink2 hover:text-ink')
  return (
    <div className="mb-4 flex flex-wrap items-end gap-x-6 gap-y-2 border-b border-line">
      <h1 className="mr-2 pb-2 text-[28px] font-semibold leading-tight tracking-[-0.02em]">{title}</h1>
      <nav aria-label={label} className="contents">
        {tabs.map((t) => t.to
          ? <RouterLink key={t.key} to={t.to} aria-current={t.key === active ? 'page' : undefined} className={cls(t.key === active)}>{t.label}</RouterLink>
          : <button key={t.key} onClick={() => onSelect?.(t.key)} aria-pressed={t.key === active} className={cls(t.key === active)}>{t.label}</button>)}
      </nav>
      {right && <div className="mb-2 ml-auto flex flex-wrap items-center gap-2 text-[12.5px] text-ink2">{right}</div>}
    </div>
  )
}

/** Overlapping photos of a few people, "+N" beyond max. */
// linked: each face opens the person's page (Sam, 18 Nov 2026); only where the stack is not inside another link or button
export function AvatarStack({ names, person, size = 24, max = 4, ring = 'ring-panel', linked = false }: {
  names: string[]; person: (n: string) => (Pick<Person, 'name' | 'avatar'> & { id?: string }) | undefined; size?: number; max?: number; ring?: string; linked?: boolean }) {
  return (
    <span className="flex items-center">
      <span className="flex -space-x-1.5">{names.slice(0, max).map((nm) => { const p = person(nm), face = <Avatar p={p ?? { name: nm, avatar: '' }} size={size} />
        return linked && p?.id ? <PersonLink key={nm} id={p.id} photo title={nm} className={cn('ring-2', ring)}>{face}</PersonLink>
          : <span key={nm} title={nm} className={cn('rounded-full ring-2', ring)}>{face}</span> })}</span>
      {names.length > max && <span className="ml-1 text-[11px] tabular-nums text-ink3">+{names.length - max}</span>}
    </span>
  )
}
