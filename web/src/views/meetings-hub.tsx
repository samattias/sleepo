// Meetings: one page, reached from two places in the sidebar (Work › Briefings at /prep, Knowledge › Meetings at
// /meetings). Both show exactly the same thing: the calendar and history (meetings.tsx), where clicking a meeting opens its
// panel with the brief (generate, regenerate with notes, actions), the people, the invite and the summary.
// /prep?event=<id> opens that meeting's panel directly (links from Today and Actions).
import { MeetingsPage } from '@/views/meetings'

export function MeetingsHub({ event, open }: { tab?: 'upcoming' | 'calendar'; event?: string; open?: string }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h1 className="sr-only">Meetings</h1>{/* no visible title or breadcrumb (Sam, 22 Oct 2026); the sidebar says where you are */}
      <MeetingsPage key={event ?? ''} event={event} open={open} />
    </div>
  )
}
