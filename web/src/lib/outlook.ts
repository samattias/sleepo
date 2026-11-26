// Outlook helpers shared by the draft cards (chat emails, components/ChatEmail.tsx). Nothing here sends anything.

// Outlook on the web's compose page, filled in: works without any Outlook permission for SleePO
export const owaCompose = (to: string[], cc: string[], subject: string, body: string) => {
  const q = [to.length && `to=${encodeURIComponent(to.join(';'))}`, cc.length && `cc=${encodeURIComponent(cc.join(';'))}`,
    `subject=${encodeURIComponent(subject)}`, `body=${encodeURIComponent(body.slice(0, 6000))}`].filter(Boolean).join('&')
  return `https://outlook.office.com/mail/deeplink/compose?${q}`
}

// "Gray Selby <gray.selby@acme.example>, rowan.lowell@acme.example, Ellis" -> the addresses, and the names given without one
export const addresses = (s: string) => {
  const out: string[] = [], missing: string[] = []
  for (const part of s.split(/[,;]/).map((x) => x.trim()).filter(Boolean)) {
    const m = part.match(/<([^<>\s]+@[^<>\s]+)>/) ?? part.match(/^([^\s<>]+@[^\s<>]+)$/)
    if (m) out.push(m[1]); else missing.push(part)
  }
  return { out, missing }
}

// a 401 from SleePO's Outlook routes: no Outlook write access yet (the Acme tenant needs IT to approve it)
export const notSignedIn = (msg: string) => /outlook-login|sign in|401/i.test(msg)

// Open a filled-in new message (Sam, 28 Oct 2026: in Outlook desktop rather than the web): the server hands Outlook for Mac a
// mailto: link (assist/outlook_desktop.py); if that fails, Outlook on the web's compose page in a new tab. Sends nothing.
export async function openCompose(to: string[], cc: string[], subject: string, body: string): Promise<'desktop' | 'web'> {
  try {
    const r = await fetch('/api/outlook/compose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to, cc, subject, body }) })
    if (r.ok) return 'desktop'
  } catch { /* the web below */ }
  window.open(owaCompose(to, cc, subject, body), '_blank')
  return 'web'
}
