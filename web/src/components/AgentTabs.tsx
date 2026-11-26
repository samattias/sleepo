// System › Agents holds three views (Sam, 28 Oct 2026: "combine the action types and the soul within the agents page, so we
// simplify the sidebar"): the agents themselves, the action types SleePO learns Sam's work from, and the soul pages the
// agents carry. Each keeps its own address (/agents, /action-types, /soul…) so Back and links still land on it; the sidebar
// shows Agents only, lit for all three (Layout's alias).
import type { ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { cn } from '@/lib/util'

export type AgentTab = 'agents' | 'action-types' | 'soul'
const TABS: [AgentTab, string, string][] = [['agents', 'Agents', '/agents'], ['action-types', 'Action types', '/action-types'], ['soul', 'Soul', '/soul']]

export function AgentTabs({ active, right, className }: { active: AgentTab; right?: ReactNode; className?: string }) {
  return (
    <div className={cn('mb-4', className)}>
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">Agents</h1>
        {right && <div className="ml-auto flex flex-wrap items-center gap-2">{right}</div>}
      </div>
      <nav aria-label="Agents views" className="flex gap-1 border-b border-line">
        {TABS.map(([k, label, to]) => (
          <Link key={k} to={to} aria-current={active === k ? 'page' : undefined}
            className={cn('-mb-px border-b-2 px-3 py-2 text-[14px] no-underline', active === k ? 'border-accent font-semibold text-ink' : 'border-transparent text-ink2 hover:text-ink')}>{label}</Link>))}
      </nav>
    </div>
  )
}
