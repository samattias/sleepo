// After a meeting: the actions to take from what was said (assist/followup.py). The counterpart of the brief before it:
// same action rows (nothing is sent; every draft is reviewed), each tied to the moment of the transcript it comes from
// and to the open item it finishes. A meeting that ended in the last three days gets one written as soon as its panel
// opens; older ones on request. Regenerate takes Sam's notes, as the brief does.
import { useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react'
import { ListChecks } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { api } from '@/lib/api'
import { splitActions } from './Actions'
import { ProposedSteps } from '@/views/tasks'
import { PrepGenerate, type GenerateLabels } from './PrepGenerate'
import { Loading, Markdown } from './ui'
import { TaskCreator } from './TaskCreator'

const LABELS: GenerateLabels = { make: 'Suggest actions', busy: 'Reading the meeting…', heading: 'Add context for the follow-up',
  placeholder: 'e.g. Milo must hear about the pricing change before Jordan sends anything. Skip the recap, they all have notes. I already sent Priya the deck.',
  hint: 'What matters most, who must hear what, what is already done.', makeWith: 'Suggest with notes', redoWith: 'Regenerate with notes' }

export function MeetingFollowup({ meetingId, label, Section }: { meetingId: string; label: string
  Section: ComponentType<{ title: string; meta?: ReactNode; right?: ReactNode; children: ReactNode }> }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['followup', meetingId], queryFn: () => api.followup(meetingId), refetchInterval: (s) => (s.state.data?.job?.running ? 4000 : false) })
  const run = useMutation({ mutationFn: (notes: string) => api.followupRun(meetingId, notes),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['followup', meetingId] }); qc.invalidateQueries({ queryKey: ['followups'] }) } })
  const d = q.data
  // the follow-ups are proposed steps in Tasks (assist/tasks.py propose_from_meeting; Sam, 22 Oct 2026), not a list of their own
  const steps = useQuery({ queryKey: ['tasks', 'meeting', meetingId, d?.followup?.updated_at], queryFn: () => api.meetingSteps(meetingId), enabled: !!d?.followup })
  const started = useRef(false)
  const [making, setMaking] = useState(false)   // Make a task: the meeting as a task with steps, or steps for a task Sam has (assist/tasks.py)
  useEffect(() => {   // a meeting that just ended: write its follow-up without being asked, once per panel
    if (d?.auto && !d.job && !started.current) { started.current = true; run.mutate('') }
  }, [d, run])
  const wasRunning = useRef(false)
  useEffect(() => {   // when the job finishes, the meetings list shows the new count
    if (wasRunning.current && !d?.job?.running) qc.invalidateQueries({ queryKey: ['followups'] })
    wasRunning.current = !!d?.job?.running
  }, [d?.job?.running, qc])

  if (!d) return <Section title="Follow-ups from this meeting"><Loading /></Section>
  const f = d.followup
  if (!f && !d.eligible) return null   // personal, no transcript yet, or not over: the panel says why elsewhere
  const busy = !!d.job?.running || run.isPending
  const { body, actions } = splitActions(f?.md ?? '')
  const text = body.replace(/^# .*\n+/, '').trim()
  return (
    <Section title="Follow-ups from this meeting" meta={f ? format(new Date(f.updated_at), 'EEE d MMM, HH:mm') : undefined}
      right={d.eligible && <PrepGenerate key={meetingId} hasBrief={!!f} busy={busy} onRun={(notes) => run.mutate(notes)} lastNotes={f?.notes || d.job?.notes} labels={LABELS} />}>
      <div className="panel-md">
        {f ? <>
          {actions.length > 0 ? <div className="mb-4"><ProposedSteps steps={steps.data ?? []} empty={steps.isLoading ? 'Proposing the steps…' : 'Every follow-up is dismissed or already in Tasks.'} /></div>
            : <p className="mb-3 text-[13px] text-ink2">Nothing for you to do from this meeting.</p>}
          {text && <Markdown>{text}</Markdown>}
        </> : busy ? <p className="text-[13px] text-ink2">Reading the transcript… usually 1–2 minutes.</p>
          : <p className="text-[13px] text-ink2">No suggestions yet.</p>}
      </div>
      {d.eligible && <div className="mt-3">
        <button onClick={() => setMaking(!making)} aria-expanded={making} className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium text-ink transition-colors hover:bg-panel2">
          <ListChecks size={14} aria-hidden />{making ? 'Hide' : 'Make a task from this meeting'}</button>
        {making && <div className="mt-2 rounded-xl border border-line bg-panel"><TaskCreator meetingId={meetingId} title={label} /></div>}
      </div>}
      {f?.notes && !busy && <p className="mt-2 text-[12px] text-ink2">Written with your notes: “{f.notes.length > 140 ? f.notes.slice(0, 140) + '…' : f.notes}”</p>}
      {busy && f && <p className="mt-2 text-[12.5px] text-ink2">Rewriting…</p>}
      {run.isError && <p className="mt-2 text-[12.5px] text-hot">{String(run.error).replace(/^Error: /, '')}</p>}
      {d.job?.ok === false && !busy && <p className="mt-2 text-[12.5px] text-hot">The last attempt failed{d.job.error ? `: ${d.job.error.slice(-160)}` : '.'}</p>}
    </Section>
  )
}
