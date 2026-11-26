// Word-level differences between two versions of a text, for a redline view (the chat's email drafts). Words and the spaces
// between them are the units, so a changed word shows as one word struck through and one added, and line breaks survive.
// Longest common subsequence over tokens: drafts are a few hundred words, so the table stays small.
export type DiffPart = { type: 'same' | 'add' | 'del'; text: string }

const tokens = (s: string) => s.match(/\s+|[^\s.,;:!?()"“”]+|[.,;:!?()"“”]/g) ?? []   // punctuation apart, so "16:00." → "16:00 instead." marks only "instead"

export function diffWords(before: string, after: string): DiffPart[] {
  const a = tokens(before), b = tokens(after)
  // trim the shared start and end first: most revisions touch a few sentences
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  let end = 0
  while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++
  const x = a.slice(start, a.length - end), y = b.slice(start, b.length - end)
  const n = x.length, m = y.length
  const out: DiffPart[] = []
  const push = (type: DiffPart['type'], text: string) => {
    const last = out[out.length - 1]
    if (last && last.type === type) last.text += text
    else out.push({ type, text })
  }
  if (start) push('same', a.slice(0, start).join(''))
  if (n * m > 4_000_000) {   // far too different to align word by word: show it as replaced
    push('del', x.join('')); push('add', y.join(''))
  } else {
    const L: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1))
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1])
    let i = 0, j = 0
    while (i < n && j < m) {
      if (x[i] === y[j]) { push('same', x[i]); i++; j++ }
      else if (L[i + 1][j] >= L[i][j + 1]) { push('del', x[i]); i++ }
      else { push('add', y[j]); j++ }
    }
    while (i < n) push('del', x[i++])
    while (j < m) push('add', y[j++])
  }
  if (end) push('same', a.slice(a.length - end).join(''))
  return out
}

// How much changed, in words (spaces not counted): for a one-line summary above the redline
export function diffStats(parts: DiffPart[]) {
  const words = (t: string) => (t.match(/[^\s]+/g) ?? []).length
  return parts.reduce((s, p) => (p.type === 'add' ? { ...s, added: s.added + words(p.text) } : p.type === 'del' ? { ...s, removed: s.removed + words(p.text) } : s), { added: 0, removed: 0 })
}

// ---- the redline Sam reads (22 Oct 2026: word by word "is just not super easy to digest"): sentence by sentence. A sentence
// that changed a little keeps its edits inline, with changes a word or two apart merged into one phrase; one that changed a
// lot (or is new, or gone) shows whole: the old sentence struck through, then the new one.
const sentences = (s: string) => (s.match(/[^.!?\n]*(?:[.!?]+["”’)]*|\n|$)[ \t]*\n*/g) ?? []).filter(Boolean)
const norm = (s: string) => s.replace(/\s+/g, ' ').trim()
const wordCount = (t: string) => (t.match(/[^\s.,;:!?()"“”]+/g) ?? []).length

// changes separated only by a short run of kept words (two words or fewer, on one line) become one change
function coalesce(parts: DiffPart[]): DiffPart[] {
  const out: DiffPart[] = []
  let del = '', add = ''
  const flush = () => { if (del) out.push({ type: 'del', text: del }); if (add) out.push({ type: 'add', text: add }); del = add = '' }
  parts.forEach((p, i) => {
    if (p.type === 'del') del += p.text
    else if (p.type === 'add') add += p.text
    else if ((del || add) && i < parts.length - 1 && parts[i + 1].type !== 'same' && wordCount(p.text) <= 2 && !p.text.includes('\n')) { del += p.text; add += p.text }
    else { flush(); out.push(p) }
  })
  flush()
  return out
}

function sentenceLcs(a: string[], b: string[]) {
  const n = a.length, m = b.length
  const L: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1))
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = norm(a[i]) === norm(b[j]) ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1])
  return L
}

export function diffRedline(before: string, after: string): DiffPart[] {
  const a = sentences(before), b = sentences(after)
  const L = sentenceLcs(a, b)
  const out: DiffPart[] = []
  const push = (p: DiffPart) => { const last = out[out.length - 1]; if (last && last.type === p.type) last.text += p.text; else out.push({ ...p }) }
  let gone: string[] = [], come: string[] = []
  const flush = () => {   // a run of changed sentences: pair them up, then inline (small edit) or whole (rewrite)
    const k = Math.max(gone.length, come.length)
    for (let x = 0; x < k; x++) {
      const o = gone[x], nw = come[x]
      if (o != null && nw != null) {
        const parts = coalesce(diffWords(o, nw))
        const changed = parts.filter((p) => p.type !== 'same').reduce((s, p) => s + wordCount(p.text), 0)
        const total = wordCount(o) + wordCount(nw)
        if (total && changed / total <= 0.5) { parts.forEach(push); continue }
      }
      if (o != null) push({ type: 'del', text: o })
      if (nw != null) push({ type: 'add', text: nw })
    }
    gone = []; come = []
  }
  let i = 0, j = 0
  while (i < a.length && j < b.length) {
    if (norm(a[i]) === norm(b[j])) { flush(); push({ type: 'same', text: b[j] }); i++; j++ }
    else if (L[i + 1][j] >= L[i][j + 1]) gone.push(a[i++])
    else come.push(b[j++])
  }
  while (i < a.length) gone.push(a[i++])
  while (j < b.length) come.push(b[j++])
  flush()
  return out
}
