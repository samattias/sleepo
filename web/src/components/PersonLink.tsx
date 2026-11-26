// A person's name or photo as a link to their page (Sam, 18 Nov 2026: "every name is a hot link to the person's page ...
// if I wanted to go to someone's page, I could just click on their name"). id: the person's id ("p-7") or the number in
// it; without one (someone SleePO does not know) the children show as they are. The click stops here, so a link inside a
// clickable card (an email's header, which opens and folds the message) opens the page and does not fold the card.
// Never inside another link or button: a row that is itself a link (an Inbox or Messages list row, a Today row) keeps
// opening what it opens.
import type { ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { cn } from '@/lib/util'

export const personId = (id: string | number | null | undefined) => (id == null || id === '' ? '' : typeof id === 'number' || /^\d+$/.test(id) ? `p-${id}` : id)

export function PersonLink({ id, children, className, title, photo = false }: { id?: string | number | null; children: ReactNode; className?: string; title?: string
  photo?: boolean }) {
  const pid = personId(id)
  if (!pid) return <>{children}</>
  return (
    <Link to="/people/$id" params={{ id: pid }} title={title} onClick={(e) => e.stopPropagation()}
      className={cn(photo ? 'shrink-0 rounded-full transition-shadow hover:ring-2 hover:ring-ink/25 focus-visible:ring-2 focus-visible:ring-ink'
        : 'text-inherit no-underline decoration-ink/40 underline-offset-2 hover:underline', className)}>{children}</Link>
  )
}
