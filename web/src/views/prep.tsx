// The body of a meeting brief written by /prep: its actions panel, the brief, and the background sources folded away.
// Briefs are shown in the meeting panel (calendar.tsx) on the Meetings page; Work › Briefings opens that same page.
import { useQuery } from '@tanstack/react-query'
import { ActionsPanel, splitActions } from '@/components/Actions'
import { Markdown } from '@/components/ui'
import { api } from '@/lib/api'
import { ProposedSteps } from '@/views/tasks'

// eventId: the brief's actions to prepare are proposed prep steps in Tasks (assist/tasks.py propose_from_brief), due the meeting's day
export function BriefBody({ md, label, eventId }: { md: string; label: string; eventId?: string }) {
  const { body, actions } = splitActions(md)
  const steps = useQuery({ queryKey: ['tasks', 'prep', eventId, md.length], queryFn: () => api.prepSteps(eventId!), enabled: !!eventId && actions.length > 0 })
  // Briefs written before the October template repeat the header ("With / Organiser / Bets / Outlook") and end with a
  // Background list of sources already linked above: drop the first, fold the second away.
  let text = body.replace(/^# .*\n+/, '').replace(/^\*\*With:\*\*.*\n+/m, '').trim()
  const at = text.search(/^## Background\b/m)
  const background = at >= 0 ? text.slice(at).replace(/^## Background.*\n+/, '').trim() : ''
  if (at >= 0) text = text.slice(0, at).trim()
  return <>
    {eventId && actions.length > 0 ? <section className="mb-5"><div className="mb-2 text-[13px] font-semibold">Prepare for this meeting</div>
      <ProposedSteps steps={steps.data ?? []} empty={steps.isLoading ? 'Proposing the steps…' : 'Every prep step is dismissed or already in Tasks.'} /></section>
      : <ActionsPanel actions={actions} label={label} title="Actions for this meeting" />}
    <Markdown>{text}</Markdown>
    {background && <details className="mt-5 border-t border-line pt-3"><summary className="cursor-pointer text-[13.5px] font-semibold">Background and sources</summary><div className="mt-2"><Markdown>{background}</Markdown></div></details>}
  </>
}
