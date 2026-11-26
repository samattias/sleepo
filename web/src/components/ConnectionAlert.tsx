// Connection problems (Sam, 17 Nov 2026: "If there are issues with the data load, for example, now it's asking me to sign
// back into my Microsoft 365 account ... I want this to be flagged to me ... I would click on something and it would take me
// to the login page to reauthenticate Microsoft. 'Cause right now I only see these issues when I go looking for them.").
// The server knows what SleePO cannot reach (assist/connections.py, GET /api/connections): a connector that needs a new
// sign-in, one that does not answer, Apple Mail or Calendar.app without access, SleePO's own Granola sign-in. One list, at
// the top of the Refresh menu and the top of Sources; while something needs Sam, the Refresh button carries its hot dot
// (Sam, 17 Nov 2026: a pill of its own in the header beside that dot was too much). Check again asks Claude Code which
// connectors are signed in (about 7 seconds) and updates them all. Sign in asks Claude Code for the connector's own sign-in
// link (`claude mcp login`) and opens it in the browser; when Sam comes back to this tab SleePO checks again by itself
// (17 Nov 2026: the Connectors settings page the first version linked to only said connectors had moved).
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, Copy, ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { api, type ConnFix, type ConnIssue, type ConnLogin, type Connections } from '@/lib/api'
import { cn } from '@/lib/util'
import { LOCALE, TZ } from '@/lib/time'
import { btnClass } from '@/components/ui'

export const useConnections = () => useQuery({ queryKey: ['connections'], queryFn: api.connections, staleTime: 60_000 })

// "today 15:48", "16 Nov"
function day(iso: string | null) {
  if (!iso) return 'never'
  const d = new Date(/Z|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')
  if (isNaN(d.getTime())) return iso.slice(0, 10)
  const key = (x: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(x)
  return key(d) === key(new Date())
    ? 'today ' + d.toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit', timeZone: TZ })
    : d.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short', timeZone: TZ })
}

// the one thing to do, or how many problems there are (the Refresh button's tooltip)
export function alertLabel(issues: ConnIssue[]) {
  if (issues.length !== 1) return `${issues.length} connection problems`
  const i = issues[0]
  return i.kind === 'signin' ? `Sign in to ${i.name}` : i.kind === 'access' ? `${i.name}: no access` : i.kind === 'app' ? `${i.name} not running` : `${i.name} not answering`
}

function FixButton({ fix, primary, onLogin }: { fix: ConnFix; primary?: boolean; onLogin?: (r: ConnLogin) => void }) {
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const cls = btnClass(primary ? 'primary' : 'outline', 'sm')
  if (fix.login) return (
    <button className={cls} disabled={busy} onClick={async () => {
      setBusy(true)
      try { onLogin?.(await api.connectionsLogin(fix.login!)) } catch (e) { onLogin?.({ url: null, opened: false, note: String((e as Error).message || e) }) } finally { setBusy(false) }
    }}>{busy && <Loader2 size={12} aria-hidden className="animate-spin" />}{fix.label}<ExternalLink size={12} aria-hidden /></button>)
  if (fix.command) return (
    <button className={cls} onClick={async () => { try { await navigator.clipboard.writeText(fix.command!); setDone(true); setTimeout(() => setDone(false), 2500) } catch { /* no clipboard */ } }}
      title={fix.command}>{done ? <><Check size={12} aria-hidden />Copied</> : <><Copy size={12} aria-hidden />{fix.label}</>}</button>)
  if (fix.open) return <button className={cls} onClick={() => api.connectionsOpen(fix.open!).catch(() => undefined)}>{fix.label}</button>
  return null
}

function Issue({ i, onLogin, login }: { i: ConnIssue; onLogin: (r: ConnLogin) => void; login?: ConnLogin }) {
  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex items-start gap-2">
        <AlertTriangle size={14} aria-hidden className="mt-[3px] shrink-0 text-hot" />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold text-ink">{i.headline}</div>
          <div className="mt-0.5 text-[12.5px] leading-snug text-ink2">
            {i.affected.length
              ? <>Not coming in: {i.affected.map((a, n) => <span key={a.id}>{n > 0 && ', '}{a.name} <span className="tabular-nums text-ink3">(last {day(a.last_ok)})</span></span>)}.</>
              : <>SleePO reads {i.feeds} through it.</>}
          </div>
          {i.fix.steps && <div className="mt-1 text-[12px] leading-snug text-ink3">{i.fix.steps}</div>}
          {(i.fix.login || i.fix.open || i.fix.command) && <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <FixButton fix={i.fix} primary={i.urgent} onLogin={onLogin} />
            {i.fix.also && <FixButton fix={i.fix.also} />}
          </div>}
          {login && <div className="mt-1.5 text-[12px] leading-snug text-ink2">
            {login.opened ? <>Claude's sign-in opened in your browser. Finish there, then come back: SleePO checks again by itself.
              {login.url && <> Nothing opened? <a href={login.url} target="_blank" rel="noopener noreferrer">Open the sign-in page</a>.</>}</>
              : <>Could not get a sign-in link from Claude Code ({login.note}). Use the Terminal command instead.</>}</div>}
        </div>
      </div>
    </li>
  )
}

// the problems with Check again under them. Without problems it renders nothing, unless a check just cleared them.
export function ConnectionIssues({ className }: { className?: string }) {
  const qc = useQueryClient()
  const q = useConnections()
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState<'cleared' | 'same' | 'failed' | null>(null)
  const [logins, setLogins] = useState<Record<string, ConnLogin>>({})
  const issues = q.data?.issues ?? []
  const check = async () => {
    setChecking(true); setResult(null)
    try {
      const before = issues.length
      const r: Connections = await api.connectionsCheck()
      qc.setQueryData(['connections'], r)
      qc.invalidateQueries({ queryKey: ['sources'] })
      setResult(!r.checked_now ? 'failed' : r.issues.length < before ? 'cleared' : 'same')
    } catch { setResult('failed') } finally { setChecking(false) }
  }
  // after a sign-in was opened: check again when Sam comes back to this tab
  const waiting = Object.values(logins).some((l) => l.opened)
  useEffect(() => {
    if (!waiting) return
    const back = () => { if (document.visibilityState === 'visible') { setLogins({}); check() } }
    window.addEventListener('focus', back); document.addEventListener('visibilitychange', back)
    return () => { window.removeEventListener('focus', back); document.removeEventListener('visibilitychange', back) }
  }, [waiting]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!issues.length && result !== 'cleared') return null
  return (
    <div className={className} aria-live="polite">
      {issues.length > 0 && <ul className="divide-y divide-line2">{issues.map((i) => <Issue key={i.key} i={i} login={logins[i.key]} onLogin={(r) => setLogins((x) => ({ ...x, [i.key]: r }))} />)}</ul>}
      {result === 'cleared' && <div className={cn('flex items-start gap-2 text-[12.5px] text-ink', issues.length > 0 && 'mt-2.5')}>
        <Check size={14} aria-hidden className="mt-[2px] shrink-0" />
        <span>{issues.length ? 'One problem is fixed.' : 'Connected.'} What was missed comes in with the next full refresh; Messages › Refresh pulls Teams now.</span></div>}
      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12px] text-ink3">
        <button onClick={check} disabled={checking} className={btnClass('ghost', 'xs', '-ml-2.5')}>
          {checking ? <Loader2 size={12} aria-hidden className="animate-spin" /> : <RefreshCw size={12} aria-hidden />}{checking ? 'Checking…' : 'Check again'}</button>
        <span className="tabular-nums">{result === 'same' ? `Still the same · checked ${day(new Date().toISOString())}` : result === 'failed' ? 'Could not ask Claude Code; try again in a minute'
          : q.data?.checked ? `Checked ${day(q.data.checked)}` : ''}</span>
      </div>
    </div>
  )
}
