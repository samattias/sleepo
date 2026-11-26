// What the assistant pill offers on each kind of page (components/AssistPill.tsx; Sam, 16 Nov 2026: "put it in as many places
// as possible where appropriate in the UI"). One set per kind of thing, so the same thing is asked about the same way wherever
// it shows. Each action is a question in the user's words: the chat gets the thing's chip and its full context from the server
// (components/AssistContext.tsx, assist/page_context.py), so the words only say what to do. Ask takes what is typed in the
// pill's field (Enter), else a useful overview; the other actions add it as "Also: …". Emails come back as email cards in the
// chat. Nothing is sent. Messages keeps its own reply actions (views/messages.tsx), an initiative's or topic's work bar its own
// seeded conversations (components/InitiativeWork.tsx), the Inbox's email its own (views/inbox).
import { CalendarCheck, FileSearch, ListChecks, Mail, MessageCircleQuestion, PenLine } from 'lucide-react'
import type { PillAction } from '@/components/AssistPill'

type Pill = { actions: PillAction[]; quick: PillAction[]; field: { label: string; placeholder: string } }

const also = (d: string) => (d ? ` Also: ${d}` : '')
const ask = (overview: string): PillAction => ({ label: 'Ask', icon: MessageCircleQuestion, prompt: (d) => d || overview })
const q = (label: string, text: string): PillAction => ({ label, prompt: (d) => text + also(d) })
const field = (what: string) => ({ label: `Ask SleePO about ${what}`, placeholder: `Ask about ${what}…` })

export function personPill(name: string): Pill {
  const first = name.split(' ')[0]
  return {
    field: field(first),
    actions: [
      ask(`What's going on with ${name}? What is open between us, what have they said recently, and what should I raise next time we talk?`),
      { label: 'Write an email', icon: Mail, prompt: (d) => d ? `Write an email to ${name}, in my voice. It should say: ${d}`
        : `Write an email to ${name}, in my voice, about what is most open between us. If what it should say is not clear, ask me first.` },
    ],
    quick: [
      q('Prep me for our next talk', `Prep me for my next conversation with ${name}: what to raise, what they will want from me, and what to follow up on.`),
      q('What do I owe them?', `What do I owe ${name}: replies, promises and steps of mine, oldest first, with where each came from.`),
      q('What do they owe me?', `What is ${name} meant to deliver to me or my team, and is any of it late?`),
      q('What have they said lately?', `What has ${name} said lately in mail, messages and meetings that matters to my bets?`),
    ],
  }
}

export function taskPill(next?: string): Pill {
  return {
    field: field('this task'),
    actions: [
      ask('Where does this task stand, and what should I do next?'),
      { label: 'Do the next step', icon: PenLine, prompt: (d) => `Help me do the next step of this task${next ? `: “${next}”` : ''}. If it needs an email or a message,`
        + ' write it in my voice; if it needs a document, propose the plan first.' + also(d) },
    ],
    quick: [
      q('Plan the remaining steps', 'Plan the remaining steps of this task, each with an owner and a date, and say which I could delegate.'),
      q('Who could own this?', 'Who on my team could own this task or its next step instead of me, and what would I hand over?'),
      q("What's blocking it?", 'What is blocking this task, who is it waiting on, and how do I unblock it?'),
      q('Write a status update', 'Write a short status update on this task that I could send to the people involved, in my voice.'),
    ],
  }
}

export function meetingPill(upcoming: boolean): Pill {
  return upcoming ? {
    field: field('this meeting'),
    actions: [
      ask('Prep me for this meeting: what it is for, what to raise, what they will want from me, and what to be careful with.'),
      { label: 'Draft an agenda', icon: ListChecks, prompt: (d) => 'Draft a short agenda for this meeting that I could send to the people invited, in my voice.' + also(d) },
    ],
    quick: [
      q('What should I raise?', 'What should I raise in this meeting, most important first, and what outcome should I aim for?'),
      q('What do they want from me?', 'What will the people in this meeting want from me, going by what they said and asked lately?'),
      q("What's open with them?", 'What is open between me and the people in this meeting: replies, promises, waits and tasks?'),
      q('Write a pre-read', 'Write a short pre-read email for this meeting, in my voice: the purpose, the decision needed and what to read first.'),
    ],
  } : {
    field: field('this meeting'),
    actions: [
      ask('What happened in this meeting? What was agreed, what do I owe, and what should I do next?'),
      { label: 'Write the follow-up', icon: Mail, prompt: (d) => 'Write the follow-up email for this meeting, in my voice: what was agreed, and who does what by when.' + also(d) },
    ],
    quick: [
      q('What was agreed?', 'What was agreed in this meeting? Attribute each point and say how sure it is.'),
      q('What do I owe?', 'What did I promise or get asked to do in this meeting, with the moment it was said?'),
      q('What should I push back on?', 'What was said in this meeting that I should push back on or check, and why?'),
      q('Summarise for someone who missed it', 'Summarise this meeting for someone who missed it, in a few lines: decisions, open questions and next steps.'),
    ],
  }
}

export function companyPill(name: string): Pill {
  return {
    field: field(name),
    actions: [
      ask(`Where do we stand with ${name}? What is open, what are the deals, who is involved, and what should I do next?`),
      { label: 'Write an email', icon: Mail, prompt: (d) => d ? `Write an email to the right person at ${name}, in my voice. It should say: ${d}`
        : `Write an email to the right person at ${name}, in my voice, about what is most open with them. If who or what is not clear, ask me first.` },
    ],
    quick: [
      q('Prep me for our next meeting', `Prep me for my next meeting with ${name}: where it stands, what they want, my goals, and what to be careful with.`),
      q("What's open with them?", `What is open with ${name}: replies, promises, waits, tasks and deals, oldest first?`),
      q('Who should I talk to?', `Who at ${name} matters most for my bets, and who on our side owns the relationship?`),
      q('Risks and opportunities', `What are the risks and the opportunities with ${name} for my bets, with the evidence for each?`),
    ],
  }
}

export function documentPill(): Pill {
  return {
    field: field('this document'),
    actions: [
      ask('What is this document about, and what in it matters for me?'),
      { label: 'Review it', icon: FileSearch, prompt: (d) => 'Review this document: what is strong, what is wrong, weak or missing, and what I should push back on, citing where in it.' + also(d) },
    ],
    quick: [
      q('Summarise it', 'Summarise this document in a few lines: its point, its key facts and what it asks of anyone.'),
      q('What does it mean for my bets?', 'What does this document mean for my bets, and does it change anything I should do?'),
      q('Draft feedback to the author', 'Draft my feedback on this document to whoever wrote or shared it, in my voice: short, the main points first.'),
      q('What should I ask?', 'What questions should I ask about this document before I rely on it?'),
    ],
  }
}

export function roadmapPill(): Pill {
  return {
    field: field('this roadmap item'),
    actions: [
      ask('Where does this roadmap item stand: what was said about it lately, is it on track, and what is open?'),
      { label: 'Write an update', icon: PenLine, prompt: (d) => 'Write a short status update on this roadmap item that I could share with the team, in my voice.' + also(d) },
    ],
    quick: [
      q('Is it on track?', 'Is this roadmap item on track for its dates? Say what the evidence is and how sure it is.'),
      q("What's the money story?", 'What is the money story for this roadmap item: who pays, how much, and what evidence there is?'),
      q('What are the risks?', 'What are the risks to this roadmap item (scope, owners, size, dependencies), and what would reduce them?'),
      q('Who should I talk to?', 'Who should I talk to about this roadmap item, and what should I ask each of them?'),
    ],
  }
}

// the Actions page (it replaced Today, 25 Nov 2026): ask anything, or what is waiting
export function actionsPill(): Pill {
  return {
    field: { label: 'Ask SleePO', placeholder: 'Ask SleePO anything…' },
    actions: [ask('What matters most today, and what should I do first?'),
      { label: 'Prep my next meeting', icon: CalendarCheck, prompt: (d) => 'Prep me for my next meeting today.' + also(d) }],
    quick: [
      q('What am I late on?', 'What am I late on: overdue steps, replies and promises, oldest first?'),
      q("Who's waiting on me?", 'Who is waiting on me right now, and for what?'),
      q('What changed since yesterday?', 'What changed since yesterday that I should know about: new asks, decisions and news on my bets?'),
      q('Plan my week', 'Plan my week: what to do on which day around my meetings, most important first.'),
    ],
  }
}
