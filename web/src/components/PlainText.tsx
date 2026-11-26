// A plain-text email, formatted (Sam, 22 Oct 2026: bullets came through as asterisks, links were not clickable).
// Outlook's HTML-to-text turns a bullet into a line holding only "*" with the item on the next line, and a link into
// "Label<https://…>"; others write "* item", "- item", "• item" or "1. item". Those become lists and links here;
// bare addresses and e-mail addresses become links; lines of ____ or ---- become rules; "> " lines become quotes.
// Only http(s) and mailto links are made, and every link opens in a new tab.
import type { ReactNode } from 'react'

type Block = { k: 'p'; lines: string[] } | { k: 'ul'; items: string[] } | { k: 'ol'; items: string[] } | { k: 'hr' } | { k: 'quote'; lines: string[] }

const RULE = /^\s*([_\-=*~])\1{4,}\s*$/
const MARK_ONLY = /^\s*([*•·▪◦‣§\-–]|o)\s*$/
const BULLET = /^\s*[*•·▪◦‣–]\s+(\S.*)$|^\s*-\s+(\S.*)$/
const NUM_ONLY = /^\s*\d{1,2}[.)]\s*$/
const NUM = /^\s*\d{1,2}[.)]\s+(\S.*)$/

function blocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const out: Block[] = []
  const last = () => out[out.length - 1]
  const item = (k: 'ul' | 'ol', t: string) => { const b = last(); if (b && (b.k === 'ul' || b.k === 'ol') && b.k === k) b.items.push(t); else out.push(k === 'ul' ? { k: 'ul', items: [t] } : { k: 'ol', items: [t] }) }
  const nextText = (i: number) => { let j = i + 1; while (j < lines.length && !lines[j].trim()) j++; return j }
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]
    if (!l.trim()) { const b = last(); if (b && b.k === 'p') out.push({ k: 'p', lines: [] }); continue }
    if (RULE.test(l)) { out.push({ k: 'hr' }); continue }
    if (/^\s*>/.test(l)) { const t = l.replace(/^\s*>\s?/, ''); const b = last(); if (b && b.k === 'quote') b.lines.push(t); else out.push({ k: 'quote', lines: [t] }); continue }
    if (MARK_ONLY.test(l) || NUM_ONLY.test(l)) {   // the marker alone: the item is the next line with text
      const j = nextText(i)
      if (j < lines.length && !MARK_ONLY.test(lines[j]) && !NUM_ONLY.test(lines[j])) { item(NUM_ONLY.test(l) ? 'ol' : 'ul', lines[j].trim()); i = j; continue }
    }
    const b1 = BULLET.exec(l); if (b1) { item('ul', (b1[1] ?? b1[2]).trim()); continue }
    const n1 = NUM.exec(l); if (n1) { item('ol', n1[1].trim()); continue }
    const b = last()
    if (b && b.k === 'p') b.lines.push(l.trimEnd()); else out.push({ k: 'p', lines: [l.trimEnd()] })
  }
  return out.filter((b) => b.k !== 'p' || b.lines.length)
}

// inline links: Label<url>, [url] (an image Outlook left behind), bare urls, www. addresses, e-mail addresses
const INLINE = /([^<>|\n[\]]*?)<((?:https?:\/\/|mailto:)[^>\s]+)>|\[((?:https?:\/\/)[^\]\s]+)\]|((?:https?:\/\/|www\.)[^\s<>"'\])]+)|([\w.+-]+@[\w-]+(?:\.[\w-]+)+)/gi
const short = (u: string) => {
  try { const x = new URL(u.startsWith('www.') ? `https://${u}` : u); const p = x.pathname === '/' ? '' : x.pathname; return (x.host.replace(/^www\./, '') + p).slice(0, 48) + ((x.host + p).length > 48 ? '…' : '') }
  catch { return u.slice(0, 48) }
}
const A = ({ href, children, muted }: { href: string; children: ReactNode; muted?: boolean }) =>
  <a href={href} target="_blank" rel="noopener noreferrer" className={muted ? 'text-ink3' : undefined} title={href}>{children}</a>

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let at = 0, n = 0
  for (const m of text.matchAll(INLINE)) {
    const start = m.index ?? 0
    if (m[2]) {   // Label<url>: the label is the link; with no label, the address is
      const label = m[1].trim(), lead = m[1].slice(0, m[1].length - m[1].trimStart().length)
      out.push(text.slice(at, start), lead, <A key={n++} href={m[2]}>{label || short(m[2])}</A>)
    } else if (m[3]) {
      out.push(text.slice(at, start), <A key={n++} href={m[3]} muted>[image]</A>)
    } else if (m[4]) {
      let u = m[4]; const tail = /[.,;:!?]+$/.exec(u)?.[0] ?? ''   // a full stop after an address is not part of it
      if (tail) u = u.slice(0, -tail.length)
      out.push(text.slice(at, start), <A key={n++} href={u.startsWith('www.') ? `https://${u}` : u}>{short(u)}</A>, tail)
    } else if (m[5]) {
      out.push(text.slice(at, start), <A key={n++} href={`mailto:${m[5]}`}>{m[5]}</A>)
    }
    at = start + m[0].length
  }
  out.push(text.slice(at))
  return out
}

export function PlainText({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className ?? 'text-[14px] leading-relaxed [overflow-wrap:anywhere]'}>
      {blocks(text).map((b, i) => b.k === 'hr' ? <hr key={i} className="my-3 border-line" />
        : b.k === 'ul' ? <ul key={i} className="mb-3 list-disc space-y-1 pl-5 marker:text-ink3">{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ul>
        : b.k === 'ol' ? <ol key={i} className="mb-3 list-decimal space-y-1 pl-5 marker:text-ink3">{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ol>
        : b.k === 'quote' ? <blockquote key={i} className="mb-3 border-l-2 border-line pl-3 text-ink2">{b.lines.map((l, j) => <div key={j}>{inline(l) }</div>)}</blockquote>
        : <p key={i} className="mb-3 last:mb-0">{b.lines.map((l, j) => <span key={j}>{j > 0 && <br />}{inline(l)}</span>)}</p>)}
    </div>
  )
}

export const _test = { blocks, inline }
