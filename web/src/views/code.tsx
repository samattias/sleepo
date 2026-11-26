// Knowledge › Product › Code base (Sam, 20 Nov 2026: "a page with the code base where it references the full [company] code base
// that we have in GitLab with the monolith ... there as a reference if ever the assistant needs to query the code directly").
// The git clones of the company's code on this Mac (assist/codebase.py): what each is, the branch SleePO reads and how
// current it is, Update from GitLab, a search over the code with links into GitLab at the line, and the repositories the
// knowledge base names that are not cloned here. Ask SleePO reads the same code through ask-code, as a last resort after
// the knowledge base and the product docs. A document page: the page scrolls, nothing inside it does.
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, ExternalLink, FolderGit2, GitBranch, MessageCircleQuestion, RefreshCw, Search, X } from 'lucide-react'
import { api, type CodeHit, type CodeOverview, type CodeRepo } from '@/lib/api'
import { ago, day } from '@/lib/time'
import { cn } from '@/lib/util'
import { useSearchSync } from '@/lib/nav'
import { org } from '@/lib/profile'
import { btnClass, Card, inputClass, Loading, selectClass } from '@/components/ui'
import { AssistPill } from '@/components/AssistPill'

const STALE_DAYS = 30
const daysOld = (iso: string) => (iso ? Math.floor((Date.now() - Date.parse(iso)) / 86400000) : null)
const CHECK = ' Look in the code (ask-code) if the knowledge base and product docs do not answer it, and say which branch and date the answer comes from.'

export function CodeBase({ q: q0 }: { q?: string }) {
  const qc = useQueryClient()
  const data = useQuery({ queryKey: ['code'], queryFn: api.code, refetchInterval: (s) => (s.state.data?.running ? 4000 : false) })
  const [q, setQ] = useState(q0 ?? '')
  const [asked, setAsked] = useState(q0 ?? '')
  const [repo, setRepo] = useState('')
  const [path, setPath] = useState('')
  useEffect(() => { if (q0 !== undefined && q0 !== asked) { setQ(q0); setAsked(q0) } }, [q0])   // eslint-disable-line react-hooks/exhaustive-deps
  useSearchSync('q', asked || null)   // the search stays in the address: Back returns to it (lib/nav.ts)
  const res = useQuery({ queryKey: ['code-search', asked, repo, path], queryFn: () => api.codeSearch(asked, repo || undefined, path || undefined),
    enabled: !!asked.trim(), staleTime: 60_000 })
  const update = async (name?: string) => { await api.codeUpdate(name); qc.invalidateQueries({ queryKey: ['code'] }) }
  const wasRunning = data.data?.running
  useEffect(() => { if (wasRunning === false) qc.invalidateQueries({ queryKey: ['code-search'] }) }, [wasRunning, qc])
  if (!data.data) return <Loading />
  const d = data.data
  const company = org().name || 'the company'

  return (
    <div className="max-w-[1100px]">
      <div className="mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Code base</h1>
        <span className="text-[13px] text-ink2">{d.repos.length} {d.repos.length === 1 ? 'clone' : 'clones'} on this Mac</span>
        <div className="ml-auto">
          {d.repos.length > 0 && <button className={btnClass('outline')} disabled={d.running} onClick={() => update()}>
            <RefreshCw size={13} className={cn(d.running && 'animate-spin')} />{d.running ? 'Updating…' : `Update from ${d.host}`}</button>}
        </div>
      </div>
      <p className="mb-5 max-w-[760px] text-[13px] text-ink2">
        {company}'s source code from {d.host}, read from the clones on this Mac. Ask SleePO looks here when the knowledge base and the product
        docs don't say how the product actually behaves (roles and permissions, settings, limits, APIs). It reads each repository's main branch as {d.host} last
        gave it, never your local edits, and nothing is copied into SleePO.
      </p>

      <AssistPill className="mb-6 max-w-[860px]" target={null}
        field={{ label: 'Ask SleePO about the code', placeholder: 'How does the platform handle user roles and permissions?' }}
        actions={[{ label: 'Ask', icon: MessageCircleQuestion, prompt: (t) => (t || 'What is in the code base, and which parts matter for product questions?') + CHECK }]}
        quick={[
          { label: 'Roles and permissions', prompt: (t) => 'How do user roles and permissions work in our product: which roles exist, what each can do, and where an admin sets them?' + (t ? ` Also: ${t}` : '') + CHECK },
          { label: 'Single sign-on', prompt: (t) => 'How are single sign-on and user provisioning (SAML, SCIM) supported?' + (t ? ` Also: ${t}` : '') + CHECK },
          { label: 'Public APIs', prompt: (t) => 'Which public APIs does our product offer, and what can they do?' + (t ? ` Also: ${t}` : '') + CHECK },
          { label: 'Admin settings', prompt: (t) => 'What can an administrator configure in our product, and where?' + (t ? ` Also: ${t}` : '') + CHECK },
        ]} />

      {!d.repos.length && <Card className="mb-6 p-4 text-[13px] text-ink2">
        No clone of {company}'s code is on this Mac{d.configured ? '' : ' (the org pack names no code host)'}. Clone a repository from {d.host}, or add a folder below.
      </Card>}
      <div className="mb-8 grid gap-3 md:grid-cols-2">
        {d.repos.map((r) => <RepoCard key={r.path} r={r} host={d.host} running={d.running} onUpdate={() => update(r.name)}
          onHide={async () => { qc.setQueryData(['code'], await api.codeRepos({ hide: r.path })) }} />)}
      </div>

      {d.repos.length > 0 && <section className="mb-8">
        <h2 className="mb-2 text-[15px] font-semibold">Search the code</h2>
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); setAsked(q.trim()) }}>
          <div className="relative min-w-[260px] flex-1">
            <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink3" />
            <input className={cn(inputClass, 'w-full py-1.5 pl-8 font-mono')} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="A class, setting or words, e.g. RoleManager or permission.*admin" aria-label="Search the code" />
          </div>
          {d.repos.length > 1 && <select className={selectClass} value={repo} onChange={(e) => setRepo(e.target.value)} aria-label="Repository">
            <option value="">All repositories</option>
            {d.repos.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
          </select>}
          <input className={cn(inputClass, 'w-[180px] py-1.5')} value={path} onChange={(e) => setPath(e.target.value)} placeholder="In paths like… (*.java)" aria-label="Path filter" />
          <button className={btnClass('primary')} type="submit" disabled={!q.trim()}>Search</button>
        </form>
        <p className="mt-1.5 text-[12px] text-ink3">Not case-sensitive; a regular expression works too. Tests are listed last.</p>
        {asked && <Results q={asked} loading={res.isFetching} data={res.data} />}
      </section>}

      {d.not_cloned.length > 0 && <details className="mb-8 group">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[15px] font-semibold">
          <ChevronRight size={14} className="transition-transform group-open:rotate-90" />
          In {d.host}, not on this Mac <span className="font-normal text-ink3">({d.not_cloned.length})</span>
        </summary>
        <p className="mb-2 mt-1 text-[12.5px] text-ink3">From the knowledge base's map of repositories. SleePO cannot read these; when an answer may live in one, it says so.</p>
        <ul className="divide-y divide-line border-y border-line">
          {d.not_cloned.map((x) => <li key={x.url} className="flex items-baseline gap-3 py-1.5 text-[12.5px]">
            <a href={x.url} target="_blank" rel="noopener" className="shrink-0 font-mono hover:underline">{x.path}</a>
            <span className="text-ink2">{x.about}</span>
          </li>)}
        </ul>
      </details>}

      <AddClone hidden={d.hidden} onDone={(o) => qc.setQueryData(['code'], o)} />
    </div>
  )
}

function RepoCard({ r, host, running, onUpdate, onHide }: { r: CodeRepo; host: string; running: boolean; onUpdate: () => void; onHide: () => void }) {
  const old = daysOld(r.as_of)
  const stale = old != null && old > STALE_DAYS
  return (
    <Card className="p-4">
      <div className="flex items-start gap-2.5">
        <FolderGit2 size={18} className="mt-0.5 shrink-0 text-ink2" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-[14px] font-semibold">{r.name}</span>
            {r.label && <span className="text-[13px] text-ink2">{r.label}</span>}
          </div>
          {r.about && <p className="mt-1 text-[12.5px] leading-snug text-ink2">{r.about}</p>}
        </div>
        {r.web && <a href={r.web} target="_blank" rel="noopener" className={btnClass('ghost')} title={`Open in ${host}`}><ExternalLink size={13} />{host}</a>}
      </div>
      <div className="mt-3 space-y-1 text-[12.5px]">
        <div className="flex flex-wrap items-center gap-x-1.5">
          <GitBranch size={12} className="text-ink3" />
          <span className="font-mono">{r.branch}</span>
          <span className={cn(stale ? 'text-hot' : 'text-ink2')}>· code as of {r.as_of ? day(r.as_of) : 'unknown'}{old != null && old > 1 ? ` (${old} days old)` : ''}</span>
          {!r.tracking && <span className="text-ink3">· the clone's own branch</span>}
        </div>
        <div className="text-ink3">{r.files.toLocaleString()} files{r.languages.length ? ' · ' + r.languages.slice(0, 4).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(' · ') : ''}</div>
        <div className="text-ink3">
          {r.fetch?.note ? <span className={cn(r.fetch.ok === false && 'text-hot')}>Last update {ago(r.fetch.finished)}: {r.fetch.note}</span>
            : r.fetched_at ? `Last updated from ${host} ${ago(r.fetched_at)}` : `Not updated from ${host} since it was cloned`}
        </div>
        <div className="truncate font-mono text-[11.5px] text-ink3" title={r.path}>{r.path.replace(/^\/Users\/[^/]+/, '~')}</div>
      </div>
      <div className="mt-3 flex gap-1.5">
        <button className={btnClass('outline')} disabled={running} onClick={onUpdate}><RefreshCw size={12} className={cn(running && 'animate-spin')} />{running ? 'Updating…' : 'Update'}</button>
        <button className={btnClass('ghost')} onClick={onHide} title="SleePO stops reading this clone (the folder is not touched)"><X size={12} />Don't use</button>
      </div>
    </Card>
  )
}

function Results({ q, loading, data }: { q: string; loading: boolean; data?: import('@/lib/api').CodeSearch }) {
  if (loading && !data) return <div className="mt-4"><Loading label={`Searching for “${q}”`} /></div>
  if (!data) return null
  if (data.error && !data.repos.length) return <p className="mt-4 text-[13px] text-hot">{data.error}</p>
  return (
    <div className="mt-4 space-y-6">
      {data.repos.map((r) => (
        <div key={r.name}>
          <div className="mb-1.5 text-[12.5px] text-ink2">
            <span className="font-mono font-semibold text-ink">{r.name}</span>
            {r.error ? <span className="text-hot"> · {r.error}</span>
              : <> · {r.total ? `${r.total.toLocaleString()} line${r.total === 1 ? '' : 's'} in ${r.file_count.toLocaleString()} file${r.file_count === 1 ? '' : 's'}` : 'no match'}
                {r.file_count > r.files.length ? ` · first ${r.files.length} files shown` : ''} · {r.branch}, {day(r.as_of)}</>}
          </div>
          <div className="divide-y divide-line border-y border-line">
            {r.files.map((f) => <FileHit key={f.path} f={f} repo={r.name} />)}
          </div>
        </div>
      ))}
    </div>
  )
}

function FileHit({ f, repo }: { f: CodeHit; repo: string }) {
  const [open, setOpen] = useState(false)
  const first = f.lines[0]?.n ?? 1
  const file = useQuery({ queryKey: ['code-file', repo, f.path, first], queryFn: () => api.codeFile(repo, f.path, Math.max(1, first - 12), first + 40), enabled: open })
  const dir = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/') + 1) : ''
  return (
    <div className="py-2">
      <div className="flex items-baseline gap-2">
        <button className="min-w-0 truncate text-left font-mono text-[12.5px] hover:underline" onClick={() => setOpen(!open)} title={open ? 'Hide the code' : 'Show the code around the first match'}>
          <span className="text-ink3">{dir}</span><span className="font-semibold">{f.path.slice(dir.length)}</span>
        </button>
        <span className="shrink-0 text-[11.5px] text-ink3">{f.hits} line{f.hits === 1 ? '' : 's'}{f.test ? ' · test' : ''}</span>
        <a href={f.link} target="_blank" rel="noopener" className="no-underline ml-auto shrink-0 text-ink3 hover:text-ink" title="Open in GitLab"><ExternalLink size={12} /></a>
      </div>
      {!open && <div className="mt-1 space-y-0.5">
        {f.lines.map((l) => <a key={l.n} href={l.link} target="_blank" rel="noopener" className="no-underline flex gap-3 rounded-sm font-mono text-[11.5px] leading-snug text-ink2 hover:bg-panel2 hover:text-ink" title="Open this line in GitLab">
          <span className="w-10 shrink-0 text-right text-ink3">{l.n}</span><span className="min-w-0 truncate">{l.text}</span></a>)}
      </div>}
      {open && <div className="mt-1.5 overflow-hidden rounded-md border border-line bg-bg">
        {file.data ? <pre className="max-h-[420px] overflow-auto p-2 font-mono text-[11.5px] leading-snug">{file.data.text.split('\n').map((ln) => {
          const m = /^\s*(\d+)\s{2}(.*)$/.exec(ln)
          const n = m ? Number(m[1]) : 0
          return <div key={n || ln} className={cn('flex gap-3', f.lines.some((x) => x.n === n) && 'bg-accentbg')}>
            <span className="w-10 shrink-0 select-none text-right text-ink3">{n || ''}</span><span className="whitespace-pre">{m ? m[2] : ln}</span></div>
        })}</pre> : file.isError ? <p className="p-2 text-[12px] text-hot">{String((file.error as Error)?.message || 'Could not read it')}</p> : <p className="p-2 text-[12px] text-ink3">Reading…</p>}
      </div>}
    </div>
  )
}

function AddClone({ hidden, onDone }: { hidden: string[]; onDone: (o: CodeOverview) => void }) {
  const [path, setPath] = useState('')
  const [err, setErr] = useState('')
  const add = async () => {
    setErr('')
    try { onDone(await api.codeRepos({ add: path.trim() })); setPath('') } catch (e) { setErr(String((e as Error).message || e)) }
  }
  return (
    <details className="group text-[12.5px]">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-ink2">
        <ChevronRight size={13} className="transition-transform group-open:rotate-90" />Add a clone SleePO did not find
      </summary>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input className={cn(inputClass, 'w-[360px] py-1.5 font-mono')} value={path} onChange={(e) => setPath(e.target.value)} placeholder="~/code/some-repo" aria-label="Folder of the clone" />
        <button className={btnClass('outline')} disabled={!path.trim()} onClick={add}>Add</button>
        {err && <span className="text-hot">{err}</span>}
      </div>
      {hidden.length > 0 && <div className="mt-3 space-y-1">
        <div className="text-ink3">Not used:</div>
        {hidden.map((h) => <div key={h} className="flex items-center gap-2 font-mono text-[11.5px]">{h.replace(/^\/Users\/[^/]+/, '~')}
          <button className={btnClass('ghost', 'sm', 'font-sans')} onClick={async () => onDone(await api.codeRepos({ show: h }))}>Use again</button></div>)}
      </div>}
      <p className="mt-2 text-ink3">SleePO finds the clones in your home folder whose remote is on the company's code host by itself.</p>
    </details>
  )
}
