// Explore: one place to wander through everything Assist knows, either as the connected graph or as the library of documents.
// The two views link into each other: a graph node opens its document, a document shows where it sits in the graph.
import { BookOpen, Network } from 'lucide-react'
import { PageTabs } from '@/components/ui'
import { cn } from '@/lib/util'
import { Graph } from '@/views/graph'
import { Library } from '@/views/knowledge'

export type ExploreView = 'graph' | 'library'

const VIEWS = [
  { key: 'graph', label: 'Graph', icon: Network, to: '/explore/graph' },
  { key: 'library', label: 'Library', icon: BookOpen, to: '/explore/library' },
] as const

// documents that are also graph nodes: meetings, people and initiatives share their ids
export const inGraph = (id?: string) => !!id && /^(m|p|i)-\d+$/.test(id)

export function Explore({ view, doc, focus }: { view: ExploreView; doc?: string; focus?: string }) {
  return (
    <div className={cn(view === 'graph' && 'flex min-h-0 flex-1 flex-col')}>{/* the graph fills the fixed canvas (Layout); the library scrolls as a page */}
      <div className="shrink-0">
        <PageTabs title="Explore" label="Explore view" active={view}
          tabs={VIEWS.map((v) => ({ key: v.key, to: v.to, label: <><v.icon size={15} strokeWidth={v.key === view ? 2.25 : 1.75} aria-hidden />{v.label}</> }))} />
      </div>
      {view === 'graph' ? <Graph focus={focus} /> : <Library id={doc} />}
    </div>
  )
}
