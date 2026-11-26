// Assistant: the chat full screen. The same conversations and state as the floating badge (components/Chat.tsx), with the
// conversation list always beside the conversation; on a phone the list takes the place of the conversation instead.
import { useEffect, useState } from 'react'
import { History, Plus } from 'lucide-react'
import { cn, usePersisted } from '@/lib/util'
import { Composer, Conversation, IconBtn, ThreadList, useChat } from '@/components/Chat'
import { ListResizer } from '@/components/ListResizer'
import { Logo } from '@/components/Logo'
import { RetentionDays, btnClass } from '@/components/ui'

export function Assistant() {
  const c = useChat()
  const [list, setList] = useState(false)
  const [listW, setListW] = usePersisted<number>('assist-assistant-list-width', 0)   // dragged like the other lists; 0: the default
  useEffect(() => { c.focus() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="flex min-h-0 flex-1">
      {/* the conversation list: compact, one line each (like Claude's), and as wide as Sam drags it (Sam, 22 Oct 2026) */}
      <aside style={listW ? { width: `min(${listW}px, 40vw)` } : undefined}
        className={cn('relative w-full shrink-0 flex-col border-r border-line bg-panel md:flex', !listW && 'md:w-[248px]', list ? 'flex' : 'hidden')}>
        <ListResizer width={listW} onChange={setListW} label="Resize the conversation list" min={200} max={420} share={0.4} />
        <div className="shrink-0 px-3 pb-1 pt-3">
          <button onClick={() => { c.fresh(); setList(false) }} className={btnClass('primary', 'md', 'w-full justify-center disabled:opacity-40')}>
            <Plus size={15} aria-hidden />New conversation</button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto pb-2"><ThreadList compact onPick={() => setList(false)} /></div>
        <p className="shrink-0 border-t border-line px-4 py-2 text-[11.5px] text-ink3">{c.threads.length} saved · kept <RetentionDays /> days</p>
      </aside>

      <section className={cn('min-w-0 flex-1 flex-col bg-panel', list ? 'hidden md:flex' : 'flex')}>
        {/* one line, like the panel's header (Sam, 16 Nov 2026: no line of rules under the title); Continue in Claude Desktop is the
            pill above the box, not repeated here */}
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-3 md:px-6">
          <span className="md:hidden"><IconBtn title="Conversations" onClick={() => setList(true)}><History size={15} /></IconBtn></span>
          <Logo size={22} className="shrink-0" />
          <h1 className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-[-0.01em]">{c.title || 'Assistant'}</h1>
          <span className="md:hidden"><IconBtn title="New conversation" onClick={c.fresh}><Plus size={16} /></IconBtn></span>
        </header>
        <Conversation wide inner="mx-auto max-w-[780px] px-4 pb-4 pt-6 md:px-6" />
        <div className="shrink-0"><div className="mx-auto max-w-[780px] px-4 pb-4 pt-1 md:px-6"><Composer wide /></div></div>
      </section>
    </div>
  )
}
