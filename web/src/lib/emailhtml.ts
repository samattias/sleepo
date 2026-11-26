// One email's HTML, split into the conversation it quotes, so every message reads on its own with its formatting.
// Outlook (new and classic, Windows and Mac, EN/FR/DE), Gmail and Apple Mail start each quoted message with a header
// block ("From: … Sent: … To: … Subject: …" or "On …, X wrote:"). Each header is a cut; the HTML between two cuts is one
// message, cloned with the structure around it (Range.cloneContents keeps the open tags), so its styles survive.
// The plain-text counterpart is assist/threadparse.py (used when there is no HTML).

export type Head = { from: string; address: string; date: string; to: string; cc: string; subject: string }
export type HtmlMsg = Head & { html: string; snippet: string; latest: boolean }

const OUTLOOK = /^(?:[-_ ]*(?:Forwarded message|Original Message|Message d'origine|Ursprüngliche Nachricht|Begin forwarded message:?)[-_ ]*\n)?(?:From|De|Von)\s*:[^\n]*\n(?:[^\n]*\n){0,2}?(?:Sent|Date|Envoyé|Gesendet|Datum)\s*:/i
const ATTRIB = /^(?:On|Le|Am)\s[\s\S]{4,260}?(?:wrote|a écrit|schrieb)\s*:?$/i
const FOOTER = /^(?:This email and any files transmitted|Cet e-mail et tous les fichiers|This message (?:and any attachments )?is confidential|CONFIDENTIALITY NOTICE)/i
const BLOCK = /^(P|DIV|TR|LI|H[1-6]|TABLE|BLOCKQUOTE|HR|UL|OL|SECTION)$/

// Text with line breaks where the email shows them (<br>, block elements).
export function blockText(n: Node): string {
  let out = ''
  const walk = (x: Node) => {
    if (x.nodeType === 3) { out += x.nodeValue; return }
    if (x.nodeType !== 1 && x.nodeType !== 11) return
    const tag = (x as Element).tagName ?? ''
    if (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'TITLE') return
    if (tag === 'BR') { out += '\n'; return }
    const block = BLOCK.test(tag)
    if (block) out += '\n'
    x.childNodes.forEach(walk)
    if (block) out += '\n'
  }
  walk(n)
  return out.replace(/ /g, ' ').replace(/[ \t\r]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{2,}/g, '\n').trim()
}
const flat = (s: string | null | undefined) => (s ?? '').replace(/[\s ]+/g, ' ').trim()

// "Bryn Mercer <f@x.com>", "Mercer, Bryn [mailto:f@x.com]", "f@x.com"
function person(v: string): { name: string; address: string } {
  const m = v.match(/^\s*"?(.*?)"?\s*(?:<([^>]*)>|\[mailto:([^\]]*)\])\s*$/)
  if (m) return { name: m[1].trim() || m[2] || m[3] || '', address: (m[2] || m[3] || '').trim() }
  return /@/.test(v) && !/\s/.test(v.trim()) ? { name: v.trim(), address: v.trim() } : { name: v.trim(), address: '' }
}
const names = (v: string) => v.split(/;\s*/).map((x) => person(x).name).filter(Boolean).join(', ')

function parseHead(t: string): Head {
  const g = (re: RegExp) => (t.match(re)?.[1] ?? '').trim()
  const from = g(/^(?:From|De|Von)\s*:\s*(.+)$/im)
  if (from) {
    const p = person(from)
    return { from: p.name, address: p.address, date: g(/^(?:Sent|Date|Envoyé|Gesendet|Datum)\s*:\s*(.+)$/im), to: names(g(/^(?:To|À|An)\s*:\s*(.+)$/im)),
      cc: names(g(/^Cc\s*:\s*(.+)$/im)), subject: g(/^(?:Subject|Objet|Betreff)\s*:\s*(.+)$/im) }
  }
  const m = t.replace(/\n/g, ' ').match(/^(?:On|Le|Am)\s+(.+?),?\s+([^,]*?)\s*(?:<([^>]+)>|\[mailto:([^\]]+)\])?\s*(?:wrote|a écrit|schrieb)\s*:?$/i)
  return { from: m?.[2]?.trim() || m?.[3] || '', address: m?.[3] || m?.[4] || '', date: m?.[1]?.trim() ?? '', to: '', cc: '', subject: '' }
}

// The header blocks, outermost wrapper of each that holds nothing else, in document order.
function separators(body: HTMLElement): Element[] {
  const cands = Array.from(body.querySelectorAll('div, p, font, span, td, blockquote, section')).filter((el) => {
    const t = el.textContent ?? ''
    if (t.length > 2500) return false
    if (/(?:From|De|Von)\s*:/.test(t) && /(?:Sent|Date|Envoyé|Gesendet|Datum)\s*:/.test(t)) return OUTLOOK.test(blockText(el))
    return t.length < 400 && /wrote|a écrit|schrieb/.test(t) && ATTRIB.test(blockText(el))
  })
  const inner = cands.filter((el) => !cands.some((o) => o !== el && el.contains(o)))
  const out: Element[] = []
  for (let el of inner) {
    while (el.parentElement && el.parentElement !== body && flat(el.parentElement.textContent) === flat(el.textContent)) el = el.parentElement
    if (!out.some((o) => o === el || o.contains(el) || el.contains(o))) out.push(el)
  }
  return out.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
}

const isBlank = (n: Node): boolean => {
  if (n.nodeType === 8) return true
  if (n.nodeType === 3) return !flat(n.nodeValue)
  if (n.nodeType !== 1) return false
  const el = n as Element
  if (el.tagName === 'BR' || el.tagName === 'HR' || el.id === 'appendonsend') return true
  if (el.tagName === 'IMG' || el.querySelector('img, video, svg, canvas')) return false
  return !flat(el.textContent)
}
function trimEnd(n: Node) { for (let c = n.lastChild; c; c = n.lastChild) { if (isBlank(c)) { n.removeChild(c); continue } if (c.nodeType === 1) trimEnd(c); break } }
function trimStart(n: Node) { for (let c = n.firstChild; c; c = n.firstChild) { if (isBlank(c)) { n.removeChild(c); continue } if (c.nodeType === 1) trimStart(c); break } }

// Quote wrappers the cut left open around a quoted message, a confidentiality footer, empty lines at either end.
function tidy(box: HTMLElement, quoted: boolean) {
  if (quoted) box.querySelectorAll('blockquote[type="cite"], blockquote.gmail_quote, div.gmail_quote').forEach((q) => q.replaceWith(...Array.from(q.childNodes)))
  box.querySelectorAll('#appendonsend').forEach((x) => x.remove())
  const foot = Array.from(box.querySelectorAll('p, div, span, font, td')).find((el) => FOOTER.test(flat(el.textContent)))
  if (foot && flat(box.textContent).indexOf(flat(foot.textContent)) > 0) {
    const r = box.ownerDocument.createRange()
    r.setStartBefore(foot); r.setEnd(box, box.childNodes.length); r.deleteContents()
  }
  trimEnd(box); trimStart(box)
}

// -> the page's <style> blocks (shared by every message) and the messages, newest first as in the email.
// `latest` is the header of the email itself (its sender, recipients and date come from the database).
export function splitThread(html: string, latest: Head): { css: string; msgs: HtmlMsg[] } {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const css = Array.from(doc.querySelectorAll('style')).map((s) => s.outerHTML).join('\n')
  doc.querySelectorAll('style, script, title, meta, base, link').forEach((s) => s.remove())
  const body = doc.body
  const msgs: HtmlMsg[] = []
  let prev: Element | null = null
  let head = latest
  for (const sep of [...separators(body), null]) {
    const r = doc.createRange()
    if (prev) r.setStartAfter(prev); else r.setStart(body, 0)
    if (sep) r.setEndBefore(sep); else r.setEnd(body, body.childNodes.length)
    const box = doc.createElement('div')
    box.appendChild(r.cloneContents())
    tidy(box, !!prev)
    const snippet = flat(blockText(box)).slice(0, 220)
    if (!prev || snippet || box.querySelector('img')) msgs.push({ ...head, html: box.innerHTML, snippet, latest: !prev })
    if (sep) { head = parseHead(blockText(sep)); prev = sep }
  }
  return { css, msgs }
}

export const hasRemoteImages = (html: string) => /<img[^>]+src=["']?https?:/i.test(html) || /url\(\s*["']?https?:/i.test(html)
