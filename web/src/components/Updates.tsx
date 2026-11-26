// Versions and updates (Sam, 26 Nov 2026: "add a manual check for update button under the person's icon in the top right hand
// corner"; assist/updates.py). The account menu has Check for updates, with the answer under it and Update now when a newer
// release is out; the picture carries a dot while one is waiting. The Account page's Version panel says the same with the
// release notes and how the last update went. An update runs only on a click, in the background, then SleePO restarts.
import { useEffect, useState, type ReactElement, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Download, ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { api, type Updates } from '@/lib/api'
import { ago } from '@/lib/time'
import { cn } from '@/lib/util'
import { Button, btnClass } from './ui'

export function useUpdates() {
  return useQuery({
    queryKey: ['updates'], queryFn: api.updates, staleTime: 3_600_000,
    refetchInterval: (q) => (q.state.data?.running ? 1500 : 3_600_000),
  })
}

/** Check now and Update now, sharing the query's cache; after an update SleePO restarts and the page reloads. */
function useUpdateActions() {
  const qc = useQueryClient()
  const [asked, setAsked] = useState(false)
  const check = useMutation({ mutationFn: api.updatesCheck, onSuccess: (d) => { qc.setQueryData(['updates'], d); setAsked(true) } })
  const install = useMutation({
    mutationFn: (tag?: string) => api.updatesInstall(tag),
    onSuccess: (d) => qc.setQueryData(['updates'], d),
  })
  return { check, install, asked }
}

function useReloadAfterUpdate(d: Updates | undefined) {
  const done = !!d && !d.running && d.update?.ok === true && d.update?.phase === 'Restarting' && !!d.update?.finished
    && Date.now() - Date.parse(d.update.finished) < 120_000
  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => window.location.reload(), 9000)   // the server restarts in a few seconds; the new pages are already on disk
    return () => clearTimeout(t)
  }, [done])
  return done
}

/** The answer to a check, in one or two lines. */
function Answer({ d, asked }: { d: Updates; asked: boolean }) {
  if (d.running) return <span className="flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> {d.update?.phase || 'Updating'}…</span>
  if (d.update?.ok === false && d.update.finished && Date.now() - Date.parse(d.update.finished) < 3_600_000)
    return <span className="text-hot">Update stopped: {d.update.error}</span>
  if (d.dev) return <span>Development copy: it isn't updated from GitHub.</span>
  if (d.available && d.latest) return <span><b className="text-ink">SleePO {d.latest.version}</b> is available.</span>
  if (d.error) return <span>{d.error}</span>
  if (d.latest) return <span className="flex items-center gap-1.5"><Check size={12} /> You're up to date{asked ? '' : ` · checked ${ago(d.checked)}`}.</span>
  return asked ? <span>No release is published yet.</span> : null
}

/** Under the person's picture: Check for updates, then what it found. */
export function UpdateMenuSection({ item }: { item: string }) {
  const q = useUpdates()
  const { check, install, asked } = useUpdateActions()
  const d = q.data
  const restarting = useReloadAfterUpdate(d)
  return (
    <div className="border-t border-line py-1">
      <button role="menuitem" className={item} disabled={check.isPending || !!d?.running} onClick={() => check.mutate()}>
        {check.isPending ? <Loader2 size={15} className="animate-spin text-ink3" /> : <RefreshCw size={15} className="text-ink3" />}
        {check.isPending ? 'Checking for updates…' : 'Check for updates'}
        <span className="ml-auto text-[11px] text-ink3">{d ? (d.version ?? 'dev') : ''}</span>
      </button>
      {d && !check.isPending && (asked || d.available || d.running || restarting || (d.update?.ok === false && d.update.finished)) && (
        <div className="px-3 pb-2 pt-0.5 text-[12px] leading-snug text-ink2">
          {restarting ? <span className="flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> Updated to {d.update.version}. Restarting SleePO…</span>
            : <Answer d={d} asked={asked} />}
          {d.available && d.latest && !d.running && !restarting && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button variant="primary" size="xs" disabled={!!d.blocked || install.isPending} title={d.blocked || undefined}
                onClick={() => install.mutate(d.latest!.tag)}><Download size={12} /> Update now</Button>
              {d.latest.url && <a href={d.latest.url} target="_blank" rel="noreferrer" className={btnClass('ghost', 'xs')}>What's new <ExternalLink size={11} /></a>}
            </div>)}
          {d.available && d.blocked && !d.running && <p className="mt-1.5 text-[11.5px] text-ink3">{d.blocked}</p>}
          {install.data?.reason && <p className="mt-1.5 text-[11.5px] text-hot">{install.data.reason}</p>}
        </div>)}
    </div>
  )
}

/** A dot on the picture while a newer release waits. */
export function UpdateDot() {
  const d = useUpdates().data
  if (!d?.available && !d?.running) return null
  return <span aria-label="Update available" className={cn('absolute -right-0.5 -top-0.5 size-2.5 rounded-full ring-2 ring-panel', d.running ? 'bg-ink3' : 'bg-accent')} />
}

/** Release notes are the changelog's entries: dated headings and bullets with a bold lead. Shown as text, never raw markdown. */
function Notes({ md }: { md: string }) {
  const bold = (t: string) => t.split(/\*\*(.+?)\*\*/g).map((s, i) => (i % 2 ? <b key={i}>{s}</b> : s))
  const blocks: { head?: string; items: string[] }[] = []
  for (const raw of md.split('\n')) {
    const ln = raw.trimEnd()
    if (ln.startsWith('## ')) blocks.push({ head: ln.slice(3), items: [] })
    else if (/^\s*[-*] /.test(ln)) { if (!blocks.length) blocks.push({ items: [] }); blocks[blocks.length - 1].items.push(ln.replace(/^\s*[-*] /, '')) }
    else if (ln.trim() && blocks.length && blocks[blocks.length - 1].items.length) {
      const b = blocks[blocks.length - 1]; b.items[b.items.length - 1] += ' ' + ln.trim()
    }
  }
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => (
        <div key={i}>
          {b.head && <p className="mb-1 text-[12px] font-semibold text-ink2">{b.head}</p>}
          <ul className="list-disc space-y-1 pl-5 text-[13px] leading-snug">{b.items.map((t, j) => <li key={j}>{bold(t)}</li>)}</ul>
        </div>))}
    </div>
  )
}

/** The Account page's Version panel. */
export function UpdatesPanel({ Panel }: { Panel: (p: { title: string; children: ReactNode; right?: ReactNode }) => ReactElement }) {
  const q = useUpdates()
  const { check, install, asked } = useUpdateActions()
  const d = q.data
  const restarting = useReloadAfterUpdate(d)
  if (!d) return null
  const last = d.update
  const tpl = last?.ok && last.templates
  return (
    <Panel title="Version" right={
      <span className="flex items-center gap-2">
        <Button variant="outline" disabled={check.isPending || d.running} onClick={() => check.mutate()}>
          {check.isPending ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Check for updates</Button>
        {d.available && d.latest && <Button variant="primary" disabled={!!d.blocked || d.running || install.isPending} title={d.blocked || undefined}
          onClick={() => install.mutate(d.latest!.tag)}><Download size={13} /> Update to {d.latest.version}</Button>}
      </span>}>
      <p className="text-[13px]">{d.dev ? 'Development copy' : <>SleePO <b>{d.version}</b></>}
        {d.checked && !d.dev && <span className="text-ink3"> · checked {ago(d.checked)}{d.auto ? ', and once a day' : ''}</span>}</p>
      <div className="mt-1 text-[12.5px] text-ink2">{restarting ? `Updated to ${last.version}. Restarting SleePO…` : <Answer d={d} asked={asked} />}</div>
      {d.blocked && !d.dev && <p className="mt-1 text-[12.5px] text-ink3">{d.blocked}</p>}
      {install.data?.reason && <p className="mt-1 text-[12.5px] text-hot">{install.data.reason}</p>}
      {d.available && d.latest?.notes && (
        <div className="mt-3 border-t border-line2 pt-3">
          <p className="mb-2 text-[12px] text-ink3">What's new in {d.latest.version}
            {d.latest.url && <> · <a href={d.latest.url} target="_blank" rel="noreferrer" className="underline decoration-accent decoration-2 underline-offset-2">on GitHub</a></>}</p>
          <Notes md={d.latest.notes} />
        </div>)}
      {last?.ok && last.finished && (
        <p className="mt-3 text-[12.5px] text-ink3">Last update: {last.from ?? 'development copy'} to {last.version}, {ago(last.finished, 'long')}.
          {tpl && tpl.kept.length > 0 && <> Your own edits were kept in {tpl.kept.join(', ')}; the new template is in the code folder's templates.</>}</p>)}
      {!d.dev && <p className="mt-2 text-[12px] text-ink3">Updates come from {d.repo ? <a href={`https://github.com/${d.repo}/releases`} target="_blank" rel="noreferrer" className="underline decoration-line underline-offset-2">GitHub</a> : 'GitHub'}, only when you click Update. Your data stays as it is; the database is backed up first.</p>}
    </Panel>
  )
}
