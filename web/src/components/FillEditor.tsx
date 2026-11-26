// A textarea that highlights placeholders ([FILL: …], or any [ … ]) so nothing is copied or saved unfilled by accident.
// Technique: a backdrop with the same font, padding and wrapping renders the marks; the transparent textarea sits on top.
//
// Rewrite a part (Sam, 26 Oct 2026): with `rewrite`, selecting text shows "Rewrite" by the selection (or ⌘K); Sam says what
// he wants and only that part is written again (assist/rewrite_part.py), with the whole draft and its thread as context.
// The new part is highlighted with Undo, Again and Change it; the rest of the draft is untouched.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Loader2, Sparkles, Undo2, X } from 'lucide-react'
import { api, type RewriteCtx } from '@/lib/api'

export const FILL = /\[(?:FILL:)?[^\]\n]{1,120}\]/g
export const countFills = (t: string) => (t.match(FILL) ?? []).length

const QUICK = ['Shorter', 'Clearer', 'More direct', 'Warmer']
type Range = { start: number; end: number }
type Phase = { open: boolean; ask: string; running: boolean; error: string; done: null | { prev: string; ask: string; notes: string } }
const idle: Phase = { open: false, ask: '', running: false, error: '', done: null }

const fillMarks = (text: string, key: string): ReactNode[] => {
  const out: ReactNode[] = []
  let last = 0, i = 0
  for (const m of text.matchAll(FILL)) {
    out.push(<span key={`${key}${i++}`}>{text.slice(last, m.index)}</span>)
    out.push(<mark key={`${key}${i++}`} style={{ background: 'color-mix(in srgb, var(--hot) 22%, transparent)', color: 'transparent', outline: '1.5px solid var(--hot)', borderRadius: 2 }}>{m[0]}</mark>)
    last = (m.index ?? 0) + m[0].length
  }
  out.push(<span key={`${key}${i}`}>{text.slice(last)}</span>)
  return out
}

// bare: no box of its own (the Inbox's draft card draws the frame). rows is the least height: the box grows with the text
// (Sam, 22 Oct 2026: one scroll, the page's or the pane's, never a second one inside a draft).
export function FillEditor({ value, onChange, rows = 10, bare = false, rewrite }: { value: string; onChange: (v: string) => void; rows?: number; bare?: boolean; rewrite?: RewriteCtx }) {
  const back = useRef<HTMLDivElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const markRef = useRef<HTMLElement>(null)
  const askRef = useRef<HTMLInputElement>(null)
  const alive = useRef(true)
  const [sel, setSel] = useState<Range | null>(null)
  const [ph, setPh] = useState<Phase>(idle)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    const fit = () => { el.style.height = 'auto'; el.style.height = `${el.scrollHeight + 2}px` }
    fit()
    let w = el.clientWidth   // re-fit when the width changes (lines rewrap), not on the height change fit() makes
    const ro = new ResizeObserver(() => { if (el.clientWidth !== w) { w = el.clientWidth; fit() } })
    ro.observe(el)
    return () => ro.disconnect()
  }, [value, rows])

  const locked = ph.open || ph.running || !!ph.done
  // the bar sits under the selection's last line, inside the editor's width
  useLayoutEffect(() => {
    const m = markRef.current, w = wrap.current
    if (!sel || !m || !w) { setPos(null); return }
    const rs = m.getClientRects(), box = w.getBoundingClientRect()
    const r = rs[rs.length - 1] ?? m.getBoundingClientRect()
    const width = locked ? Math.min(420, box.width) : 110
    setPos({ top: r.bottom - box.top + 6, left: Math.max(0, Math.min(r.left - box.left, box.width - width)) })
  }, [sel, locked, value])

  const readSel = () => {
    const el = area.current
    if (!rewrite || !el || locked) return
    const { selectionStart: s, selectionEnd: e } = el
    setSel(e > s && value.slice(s, e).trim().length >= 2 ? { start: s, end: e } : null)
  }
  const ask = (r: Range | null) => { setPh({ ...idle, open: true }); setSel(r); setTimeout(() => askRef.current?.focus(), 0) }
  const close = () => { setPh(idle); setSel(null) }

  const go = async (what: string, base = value, range = sel) => {
    if (!rewrite || !range) return
    setPh((p) => ({ ...p, open: true, ask: what, running: true, error: '', done: null }))
    try {
      const { job } = await api.rewritePart({ ...rewrite, draft: base, start: range.start, end: range.end, ask: what })
      let j = await api.rewriteJob(job)
      while (j.running && alive.current) { await new Promise((r) => setTimeout(r, 1000)); j = await api.rewriteJob(job) }
      if (!alive.current) return
      if (!j.ok) throw new Error(j.error || 'The new text did not come back. Try again.')
      onChange(base.slice(0, range.start) + j.part + base.slice(range.end))
      setSel({ start: range.start, end: range.start + j.part.length })
      setPh({ ...idle, done: { prev: base, ask: what, notes: j.notes } })
    } catch (e) {
      if (!alive.current) return
      setSel(range)
      setPh((p) => ({ ...p, open: true, running: false, error: (e as Error).message }))
    }
  }
  const undo = () => { if (ph.done) onChange(ph.done.prev); close() }
  // the same ask again, on the text as it was before this rewrite
  const again = () => { if (ph.done && sel) { const d = ph.done; onChange(d.prev); go(d.ask, d.prev, { start: sel.start, end: sel.end - (value.length - d.prev.length) }) } }
  const change = () => { if (ph.done && sel) { const d = ph.done; onChange(d.prev); ask({ start: sel.start, end: sel.end - (value.length - d.prev.length) }) } }

  const shared: CSSProperties = { font: 'inherit', fontSize: 14, lineHeight: 1.65, padding: bare ? '4px 0' : 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', letterSpacing: 'normal' }
  const tint = ph.done ? 'color-mix(in srgb, var(--accent) 45%, transparent)' : locked ? 'color-mix(in srgb, var(--accent) 30%, transparent)' : 'transparent'
  const s = sel && sel.end <= value.length ? sel : null
  return (
    <div ref={wrap} className={bare ? 'relative' : 'relative border border-line bg-bg focus-within:border-ink'}>
      <div ref={back} aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden text-transparent" style={shared}>
        {s ? <>{fillMarks(value.slice(0, s.start), 'a')}<mark ref={markRef} className={ph.running ? 'animate-pulse' : ''} style={{ background: tint, color: 'transparent' }}>{value.slice(s.start, s.end)}</mark>{fillMarks(value.slice(s.end) + '\n', 'b')}</>
          : fillMarks(value + '\n', 'a')}
      </div>
      <textarea ref={area} value={value} rows={rows} spellCheck readOnly={ph.running}
        onChange={(e) => { if (locked) close(); onChange(e.target.value) }}
        onSelect={readSel} onMouseUp={readSel} onKeyUp={readSel}
        onBlur={() => { if (!locked) setSel(null) }}
        onKeyDown={(e) => { if (rewrite && s && !locked && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); ask(s) } }}
        onScroll={(e) => { if (back.current) back.current.scrollTop = e.currentTarget.scrollTop }}
        className="relative block w-full resize-none overflow-hidden border-0 bg-transparent text-ink outline-none" style={{ ...shared, caretColor: 'var(--ink)' }} />
      {rewrite && s && pos && (
        <div className="absolute z-20" style={{ top: pos.top, left: pos.left }} onMouseDown={(e) => { if (!(e.target instanceof HTMLInputElement)) e.preventDefault() }}>
          {!locked ? (
            <button onClick={() => ask(s)} title="Write this part again (⌘K)"
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1 text-[12px] font-medium text-ink shadow-md hover:bg-panel2">
              <Sparkles size={13} /> Rewrite
            </button>
          ) : ph.done ? (
            <div className="flex max-w-[420px] flex-wrap items-center gap-1 rounded-xl border border-line bg-panel px-2 py-1.5 text-[12px] text-ink shadow-md">
              <span className="px-1 text-ink2">Rewritten</span>
              <button onClick={undo} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 hover:bg-panel2"><Undo2 size={12} /> Undo</button>
              <button onClick={again} title="The same ask again, from the text before" className="rounded-full px-2 py-0.5 hover:bg-panel2">Again</button>
              <button onClick={change} title="Undo and ask for something else" className="rounded-full px-2 py-0.5 hover:bg-panel2">Change it</button>
              <button onClick={close} className="rounded-full bg-ink px-2.5 py-0.5 font-medium text-bg">Keep</button>
              {ph.done.notes && <div className="w-full px-1 pt-0.5 text-[11.5px] text-ink2">{ph.done.notes}</div>}
            </div>
          ) : (
            <div className="w-[420px] max-w-full rounded-xl border border-line bg-panel p-2 shadow-md">
              <div className="flex items-center gap-2">
                {ph.running ? <Loader2 size={14} className="shrink-0 animate-spin text-ink2" /> : <Sparkles size={14} className="shrink-0 text-ink2" />}
                <input ref={askRef} autoFocus value={ph.ask} disabled={ph.running} placeholder="How should this part change?"
                  onChange={(e) => setPh((p) => ({ ...p, ask: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); go(ph.ask) } if (e.key === 'Escape') { e.preventDefault(); close(); area.current?.focus() } }}
                  className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink3 disabled:opacity-70" />
                {!ph.running && <button onClick={close} title="Cancel (Esc)" className="text-ink3 hover:text-ink"><X size={14} /></button>}
              </div>
              {ph.running ? <div className="pt-1.5 text-[12px] text-ink2">Rewriting this part; the rest stays as it is…</div> : (
                <div className="flex flex-wrap gap-1 pt-1.5">
                  {QUICK.map((q) => <button key={q} onClick={() => go(q)} className="rounded-full border border-line px-2 py-0.5 text-[12px] text-ink2 hover:bg-panel2 hover:text-ink">{q}</button>)}
                </div>
              )}
              {ph.error && <div className="pt-1.5 text-[12px] text-hot">{ph.error}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
