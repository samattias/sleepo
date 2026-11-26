// How the app passes context to Ask SleePO (Sam, 16 Nov 2026: "make sure there's a framework throughout the app that we use to
// pass context to the assistant"). One way, for every entry point (the assistant pill, components/AssistPill.tsx; the floating
// button and its hover menu, components/Chat.tsx):
//
//  1. Name the thing. A page says what it is about as an AssistTarget, {kind, ref}: message (a Teams or Slack message id: its
//     conversation and latest message), email (an item id: the thread and the draft being written), initiative (slug), topic,
//     task, person, meeting (ids) or event (its external id). Pass it to the pill (target=), or wrap a part of the page in
//     <AssistScope target={…}> so every pill inside uses it. With neither, it is what the page's address has open (the floating
//     button's rule, assist/page_context.py resolve).
//  2. The server builds the chip from the database by that kind and id (GET /api/chat/context, page_context.chip): its label,
//     its second line (a conversation's latest message, an email's sender and draft) and its picture. Never from the page.
//  3. useChat().ask(question, chip) starts a new chat with it (useAskAssistant does 1 to 3). With the question, the server
//     builds the chip again, writes its full context to "Page context.md" in the conversation's folder, adds a note telling the
//     chat how to answer (a reply as an email, Teams or Slack card) and keeps the chip with the question (chat_turns.ctx_json),
//     so the chat shows it above the question, now and whenever the conversation is reopened.
//  4. The chip is alive (Sam, 17 Nov 2026): clicking it opens the thing (its href, page_context.href), and hovering it shows
//     the thing as it is now (components/ContextChip.tsx, assist/chip_preview.py).
//
// A new kind of thing needs a builder in page_context.CHIPS (label, line, picture), its pack in page_context.pack, its address in
// page_context.href (and, when the address can name it, a line in page_context.resolve) and its snapshot in chip_preview.BUILDERS.
// Tests: tests/test_page_context.py, tests/test_chip_preview.py.
import { createContext, useContext, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type PageCtx } from '@/lib/api'
import { useChat } from './Chat'

export type AssistTarget = { kind: string; ref: string }

const Scope = createContext<AssistTarget | null>(null)
/** Every assistant pill inside works on this thing. */
export function AssistScope({ target, children }: { target: AssistTarget | null; children: ReactNode }) {
  return <Scope.Provider value={target}>{children}</Scope.Provider>
}
export const useAssistTarget = () => useContext(Scope)

/** The app address on screen (hash routing), which the floating button's chip is resolved from. */
export const herePath = () => location.hash.replace(/^#/, '').split('?nolive')[0] || '/'

/** The chip for a thing (or, with none, for what the address has open), as the server builds it; null when it names nothing. */
export async function assistContext(target: AssistTarget | null): Promise<PageCtx | null> {
  try { return (target ? await api.chatContext(target.kind, target.ref) : await api.chatPageContext(herePath())).context }
  catch { return null }
}

/** The chip a target resolves to, or null (still loading, or SleePO holds no such thing, as for a personal meeting): a page
 *  shows its pill only when there is something to pass. Reads only. */
export function useAssistChip(target: AssistTarget | null) {
  return useQuery({ queryKey: ['assist-chip', target?.kind, target?.ref], queryFn: () => assistContext(target), enabled: !!target, staleTime: 60_000 }).data ?? null
}

/** Ask SleePO a question about a thing, in a new chat that holds its chip. target: this one; else the nearest AssistScope;
 *  else what the address has open. Resolves once the chat has been asked. It is never busy: a new chat asks while other answers
 *  are still coming in (Sam, 25 Nov 2026: answers run in parallel; components/Chat.tsx). */
export function useAskAssistant(target?: AssistTarget | null) {
  const chat = useChat()
  const scoped = useAssistTarget()
  return {
    busy: false,
    ask: async (question: string) => {
      chat.ask(question, await assistContext(target ?? scoped))
      return true
    },
  }
}
