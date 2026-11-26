// The account menu, top right of the header (16 Nov 2026): the user's picture, and under it who they are, Account,
// Personalisation and Check for updates (Sam, 26 Nov 2026; components/Updates.tsx). One person per Mac: no sign-in
// (Log in / Log out removed the same day: "we don't need this for now").
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import { SlidersHorizontal, UserRound } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/util'
import { Avatar, popoverClass } from './ui'
import { UpdateDot, UpdateMenuSection } from './Updates'

export function AccountMenu() {
  const q = useQuery({ queryKey: ['account'], queryFn: api.account, staleTime: 300_000 })
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const href = useRouterState({ select: (s) => s.location.href })
  useEffect(() => setOpen(false), [href])   // a page change closes it
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  const a = q.data
  const u = a?.user
  const item = 'flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] text-ink no-underline hover:bg-panel2 disabled:cursor-default disabled:hover:bg-transparent'
  return (
    <div ref={box} className="relative">
      <button onClick={() => setOpen(!open)} aria-label="Account" aria-haspopup="menu" aria-expanded={open} title={u?.name || 'Account'}
        className="relative grid size-8 place-items-center rounded-full ring-offset-2 ring-offset-panel hover:ring-2 hover:ring-line focus-visible:ring-2 focus-visible:ring-ink">
        {u?.name ? <Avatar p={{ name: u.name, avatar: u.avatar }} size={30} /> : <UserRound size={17} className="text-ink2" aria-hidden />}
        <UpdateDot />
      </button>
      {open && (
        <div role="menu" className={cn(popoverClass, 'absolute right-0 top-[calc(100%+8px)] z-50 w-[280px]')}>
          {a?.known && u ? (
            <div className="flex items-center gap-3 border-b border-line px-3 py-3">
              <Avatar p={{ name: u.name, avatar: u.avatar }} size={40} />
              <div className="min-w-0">
                <p className="truncate text-[13.5px] font-semibold">{u.name}</p>
                {u.email && <p className="truncate text-[12px] text-ink2">{u.email}</p>}
                {(u.role || u.company) && <p className="truncate text-[12px] text-ink3">{[u.role, u.company].filter(Boolean).join(' · ')}</p>}
              </div>
            </div>
          ) : (
            <p className="border-b border-line px-3 py-3 text-[12.5px] text-ink2">SleePO does not know who you are yet.</p>
          )}
          <div className="py-1">
            <Link to="/account" role="menuitem" className={item} onClick={() => setOpen(false)}><UserRound size={15} className="text-ink3" /> Account</Link>
            <Link to="/settings" role="menuitem" className={item} onClick={() => setOpen(false)}><SlidersHorizontal size={15} className="text-ink3" /> Personalisation</Link>
          </div>
          <UpdateMenuSection item={item} />
        </div>)}
    </div>
  )
}
