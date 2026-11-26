// Typed access to the FastAPI back end. Types mirror assist/views.py.
export type Link = { label: string; url: string }
export type Task = { id: string; title: string; context: string; links: Link[]; group: 'active' | 'waiting' | 'someday' | 'done'; kind: string; origin: string; person: string | null; done: boolean; due: string | null; initiatives: string[] }
export type RefreshPhase = { name: string; status: 'pending' | 'running' | 'done' | 'skipped' | 'failed'; started: number | null; secs: number | null }
export type RefreshStatus = { running: boolean; mode: string | null; started: string | null; finished: string | null; ok: boolean | null; log: string
  phases?: RefreshPhase[]; progress: number | null; eta_secs: number | null; elapsed_secs: number | null; tools?: number ; pulls?: Record<string, { name: string; ok: boolean; pulled: number | null; newest: string | null; note: string }>}
export type IniUpdate = { id: number; health: string | null; status: string | null; progress: string | null; blockers: string | null; next: string | null; scope: string | null; sources: { label: string; url: string }[]; drafted_at: string | null; approved_at: string | null; edited: boolean; drafted_by: string | null }
export type IniPerson = { name: string; count: number; key: boolean; id: string | null; title: string }
export type IniLink = { key: string; ref_type: string; ref_id: number; type: string; ts: string | null; title: string; who: string; where: string; gist: string; url: string; app: string; source?: string; status?: string; due?: string | null; kind?: string
  confidence: number | null; reason: string; link_source: string; verdict: 'confirmed' | 'rejected' | null; shown: boolean }
export type IniSummary = { id: number; slug: string; name: string; weight: number; goal: string; owner: string; v2mom: string; health: string; milestone: string; themes: string[]
  update_age_days: number | null; last_update: IniUpdate | null; draft: IniUpdate | null; quiet_days: number | null; newest: string | null; activity: number[]; linked: number; suggested: number
  open_commitments: number; people: IniPerson[]; attention?: string[]; tasks_open?: number; tasks_suggested?: number
  topics?: string[]; heat?: number }   // what is top of mind on it (assist/topics.py) and how much attention it had lately
// Top of mind (assist/topics.py; Sam, 28 Oct 2026): the topics Sam discussed in the last days, filed under his initiatives.
// Who raised it, the counts and the sources are read from what each topic cites, not from the model.
export type TopicSource = { kind: 'meeting' | 'mail' | 'chat' | 'ask'; label: string; ts: string | null; app: string; clock: string; who: string[]
  said?: { who: string; text: string; clock?: string; app?: string }[]; ref_type?: string; ref_id?: number | null; ref_key?: string | null   // said: who said what in it (runs from 29 Oct 2026)
  lines?: { who: string; text: string; clock?: string; app?: string }[]; files?: TopicFile[] }   // its page: what it said, in a line or two, and the files it shares
// a file shared in a topic's sources: url is the real file (SharePoint or OneDrive, an email's attachment) or the email it came with
export type TopicFile = { name: string; url: string; share: string; who: string; ts: string | null; key?: string | null; label?: string }
export type Topic = { id: number; title: string; summary: string | null; ask: string | null; initiative_id: number | null; initiative: string | null
  initiative_slug: string | null; area: string | null; area_name: string | null; importance: 'high' | 'medium' | 'low'; private: boolean
  raised_by: string | null; people: string[]; sources: TopicSource[]; meetings: number; mails: number; chats: number; asks: number; days: number
  first_ts: string | null; last_ts: string | null; rank: number; is_new: boolean; task_id: number | null; status: 'current' | 'dismissed'
  pinned?: boolean; current?: boolean }   // pinned by Sam (kept first); current: named in the latest run (a pin can outlive it)
// a topic's own page (Sam, 29 Oct 2026): the topic, its sources with what each points at, its initiative's status, its task,
// and what is in progress on it
export type TopicPage = Topic & { current: boolean; days_window: number; work: IniWork; initiative_status?: { health: string | null; status: string | null } | null
  task: { id: number; title: string; status: string } | null; files?: TopicFile[] }
// where an initiative's or a topic's page sends its work (routes/initiative_work.py)
export const workBase = (s: { slug: string } | { topic: number }) => 'topic' in s ? `/api/topics/${s.topic}/work` : `/api/initiatives/${encodeURIComponent(s.slug)}`
export type TopicList = { topics: Topic[]; run_at: string | null; days: number; running: boolean; error: string | null; stale: string | null }
export type IniDetail = IniSummary & { timeline: IniLink[]; suggestions: IniLink[]; open_loops: { owed_by_me: IniLink[]; owed_to_me: IniLink[] }; documents: IniLink[]; profile_md: string; updates: IniUpdate[]; merged: string[]; work?: IniWork }
// Working on an initiative from its page (assist/initiative_work.py; Sam, 29 Oct 2026): one linked item read in place, what is
// in progress on it (new emails started there, decide steps), and a decision laid out by SleePO for Sam to take.
export type IniRead = { kind: string; title: string; who: string; to?: string; ts: string | null; text: string; earlier: { who: string; ts: string | null; text: string }[]
  attachments: string[]; open: string; url: string; note: string }
export type IniWork = { chats?: { id: string; title: string; updated_at: string }[]; drafts: { id: number; key: string; subject: string; to: string[]; ask: string; has_text: boolean; updated_at: string }[]
  decisions: { id: number; title: string; task_id: number; task: string; status: string; note: string | null; at: string }[] }
export type IniJob = { id: string; kind: string; running: boolean; ok: boolean | null; error: string | null; done: number; total: number; result?: { answer?: string; refs?: Record<string, { label: string; url: string }>; records?: number; links?: number }; log?: string[] }
export type Person = { id: string; name: string; title: string; role: string; department: string; location: string; manager: string; reports: number; my_org: boolean; status: string; relationship: string; threads: number; last: string; meetings: number; kb: string; avatar: string; affiliation: string; org: string; affiliation_note: string; directs: string[]; profile?: string; open_items?: number; last_contact?: string }
export type Meeting = { id: string; start: string; end: string; event_item_id: number | null; match: string; date: string; when: string; title: string; with: string[]; segments: number; status: string; granola: string; transcript: string; calendar: string; organizer: string; outlook: string; initiatives: string[] }
export type CalEvent = { join_url?: string; id: string; subject: string; date: string; day: string; time: string; minutes: number; organizer: string; attendees: string[]; cancelled: boolean; webLink: string; location: string; recorded: boolean; unrecorded: boolean; skip: string; meeting_id: string; start: string; end: string; all_day: boolean; agenda?: string; showAs?: string; reply?: '' | 'accepted' | 'tentative' | 'not answered' | 'declined' | 'organizer' }
export type MailItem = { id: number; source_id: string; ts: string; from_name: string | null; from_address: string | null; subject: string | null; text: string | null; noise: number; preview: string | null; to: string[]; has_attachments: number | null; is_read: number | null; importance: string | null; conversation_id: string | null; web_link: string | null; full: number; task?: { task_id: number; title: string } | null; task_proposed?: boolean }
export type Addr = { name: string; address: string }
export type MailAttachment = { id: number; name: string; content_type: string; size: number; is_inline: number; content_id: string | null; kind: string; available: boolean; has_text?: boolean; on_disk?: boolean }
export type ThreadMsg = { from: string; date: string; to: string; cc: string; subject: string; text: string; latest: boolean; me: boolean }
// Every stored message in the email's thread, received and sent, oldest first (assist/replies.py thread); snippet = the sender's own words
export type ThreadItem = { id: number; source_id: string; ts: string; from_name: string; from_address: string; subject: string; me: boolean; to: string; cc: string; snippet: string }
export type MailFull = { id: number; folder: string; ts: string; note: string | null; noise: number; subject: string | null; from: Addr; to: Addr[]; cc: Addr[]; bcc: Addr[]; body: string | null; body_type: 'html' | 'text' | null; web_link: string | null; importance?: string; attachments: MailAttachment[]; thread: ThreadItem[]; full: boolean; rich?: 'apple-mail' }
export type DocItem = { id: string; origin: 'sharepoint' | 'kb' | 'email' | 'teams' | 'slack' | 'local'; name: string; ext: string; author: string; ts: string; where: string; url: string; preview: string; has_text: boolean; size: number | null; ref: string | null; mail_id?: number; cloud_only?: boolean; open_url?: string; open_where?: string
  card?: { title: string; kind: string; summary: string; sensitivity: string; is_current: number | null; versions: number | null; initiatives: string[] } | null
  view?: 'pdf' | 'image' | 'quicklook' | 'office-web' | 'text' | null
  // where it is filed (assist/documents.py): moved by Sam > its card > the filing pass > confirmed links; kb = emery yates page
  folder: { initiatives: string[]; kind: string; sensitivity: string; by: 'sam' | 'card' | 'claude' | 'links' | 'kb' } }
export type PrepItem = { event_id: string; item_id: number; subject: string; start: string; end: string; local: string; attendees: string[]; organizer: string; location: string; web_link: string; join_url?: string; brief: { doc_id: string; title: string; updated_at: string; generated: string } | null; job: { running: boolean; started: string; finished: string | null; ok: boolean | null; error?: string; notes?: string } | null }
export type PrepJob = NonNullable<PrepItem['job']>
// After a meeting: the actions suggested from what was said (assist/followup.py), in the same ```actions block as a brief
export type Followup = { doc_id: string; title: string; updated_at: string; md: string; generated?: string; notes: string; checks: Record<string, unknown> }
export type FollowupStatus = { eligible: boolean; reason: string; auto: boolean; followup: Followup | null; job: PrepJob | null }
export type FollowupList = { items: Record<string, { actions: number; updated_at: string }>; todo: string[]; running: string[] }
export type Turn = { t: number; end: number; clock: string; me: boolean; speaker?: string | null; lines: string[] }
export type Transcript = { id: string; title: string; calendar_title: string; starts_at: string; ends_at: string | null; granola: string; outlook: string; attendees: string[]; status: string; other_label: string; other_inferred: boolean; summary_md: string; turns: Turn[]; segments: number; available: boolean; words?: { me: number; others: number }; speakers?: { name: string; words: number }[]; by_speaker?: SpeakerPoints[]; item_id?: number; duration?: number; shots?: Shot[]; speakers_split?: boolean }
// a screenshot of the shared screen (assist/granola_shots.py): t = second of the recording; the image is kept RETENTION_DAYS (assist/retention.py)
export type Shot = { id: string; captured_at: string; description: string; t: number | null; available: boolean; width: number | null; height: number | null; sensitive: boolean }
export const shotUrl = (id: string, thumb = false) => `/api/shots/${encodeURIComponent(id)}/image${thumb ? '?thumb=1' : ''}`
export type InboxItem = { id: number; graph_id: string; subject: string; from_name: string; from_address: string; received_at: string; preview: string; note: string; has_attachments: boolean; importance: string | null; is_read: boolean; automated: boolean; answered: boolean; to_me: boolean; needs_reply: boolean; asked?: boolean; reply_why?: string; drafted?: boolean; response?: 'reply' | 'replyall' | 'forward' | null }
// what a reply can draw on: attachments on the thread, files Sam added, and documents it links to (assist/links.py)
export type ReplyAttachment = { doc: string | null; name: string; readable: boolean; this_email: boolean; added?: boolean; id?: number; link?: string; share?: string; where?: string | null }
export type DeliverablePlan = { format: 'pptx' | 'docx' | 'xlsx'; title: string; audience: string; outline: string[]; prompt: string; covers: string[]; gaps: string[]; doc: string | null }
export type DeliverableJob = { running: boolean; ok: boolean | null; error: string; ask: string; plan: DeliverablePlan | null }
// a briefing on an email thread (assist/briefing.py); refs: the sources it cites, E123 an email, C45 a message, M12 a meeting,
// K9 a calendar event, L7 an open item, documents by id (sp-12, ma-9)
// Reviewing a file shared in Teams (assist/file_review.py): comments with evidence, exact edits Sam ticks, the updated copy
export type ReviewComment = { id: string; where: string; kind: 'fix' | 'update' | 'suggest' | 'question'; what: string; why: string
  confidence: 'confirmed' | 'likely' | 'unverified'; find: string; replace: string; suggested: string }
export type ReviewRecord = { attachment_id: number; name: string; ask: string; source: 'file' | 'text'; shared_by: string | null
  review: { verdict: string; comments: ReviewComment[]; questions: string[]; reply: string[] }
  refs: Record<string, BriefingRef & { doc?: string }>; decisions: Record<string, boolean>; replace: Record<string, string>
  output: { path: string; name: string; applied: Record<string, string>; failed: string[]; made_at: string } | null; created_at: string; chat_thread?: string }
export type ReviewState = { attachment_id: number; item_id: number; name: string; url: string | null; shared_by: string | null; sent_at: string
  request: string; read: boolean; file: { where: string; name: string } | null; editable: boolean; review: ReviewRecord | null
  job: string | null; chat_thread: string | null }   // job: a review of it still being written (the card follows it)
export type ReviewJob = { running: boolean; ok: boolean | null; error: string; attachment_id: number; result?: ReviewRecord }
export type BriefingRef = { kind: 'email' | 'chat' | 'meeting' | 'event' | 'item' | 'doc'; label: string; date: string | null; url: string | null; title?: string; web_link?: string | null; thread?: boolean }
export type Briefing = {
  headline: string; situation: string; needs: string | null
  timeline: { date: string; what: string; ref: string }[]
  people: { name: string; id: string | null; title: string | null; part: string; ref: string | null }[]
  open: { what: string; owner: string | null; ref: string | null }[]
  read: { doc: string; why: string }[]; watch: string[]; questions: string[]
}
export type BriefingRecord = { item_id: number; subject: string; ask: string; briefing: Briefing; refs: Record<string, BriefingRef>; created_at: string
  stats: { thread: number; mail: number; messages: number; meetings: number; open: number; documents: number }; chat_thread?: string }
export type BriefingJob = { running: boolean; ok: boolean | null; error: string; ask: string; result?: BriefingRecord | null }
export type ItemTask = { task_id: number; title: string; status: string; done_when: string | null; url: string; source: 'thread' | 'model' | 'sam'; confidence: number; why: string | null; suggested: boolean }
export type MsgRefresh = { running: boolean; started: string | null; finished: string | null; ok: boolean | null; note: string; last: string | null }
export type Predraft = { item_id: number; status: 'ok' | 'error'; subject: string | null; body: string | null; notes: string | null; length: number | null; created_at: string; error: string | null
  mode: 'reply' | 'replyall' | 'forward' | null; recipients: string | null; why: string | null }   // mode: the response the draft chose; recipients: JSON list
export type CompanyRelation = 'ours' | 'partner' | 'customer' | 'prospect' | 'investor' | 'vendor' | 'other' | 'hidden'
export type CompanyRow = { id: number; name: string; relation: CompanyRelation; relation_by: 'you' | 'sleepo'; region: string | null; merged: string[]
  links: number; last: string | null; people: number; deals_open: number; open_usd: number; won_usd: number; logo: string | null; logo_px: number | null }
export type CompanyDeal = { name: string; stage: string; close_date: string | null; acv: number | null; currency: string | null; net_forecast_usd: number | null
  sale_type: string | null; is_open: boolean | number | null; forecast_category: string | null; probability: number | null }
export type CompanyPage = { id: number; name: string; relation: CompanyRelation; relation_by: 'you' | 'sleepo'; kind: string | null; region: string | null
  sf_type: string | null; logo: string | null; logo_px: number | null
  domains: string[]; records: { id: number; name: string; kind: string | null }[]
  people: { id: string; name: string; title: string; n: number }[]; people_total: number; our_people: { id: string; name: string; title: string; n: number }[]
  deals: CompanyDeal[]; activity: { id: number; kind: string; label: string; ts: string; from: string; title: string; url: string; mine?: boolean; where?: string }[]
  initiatives: { id: number; slug: string; name: string; n: number }[] }
// an answer running on the server (assist/chat.py live_events): its events since `after`, and where to ask from next
export type ChatLiveEvent = { type: string; text?: string; label?: string; desktop?: boolean; file?: string; run?: string; error?: string
  files?: { name: string; size: number }[]; secs?: number; thread?: string }
export type ChatLive = { job: string; thread: string; events: ChatLiveEvent[]; next: number; done: boolean }
export type ChatDraftSaved = { mail?: number; to?: string; cc?: string; subject?: string; body?: string; edited_at?: string; sent?: boolean; outlook_id?: string; outlook_link?: string
  kind?: 'teams' | 'slack'; item?: number }   // kind: a Teams or Slack reply (```teams <item id>), not an email
export type FillQuestion = { id: string; header: string; question: string; multi: boolean; options: { label: string; detail: string }[]; fills: string[] }
export type FillJob = { running: boolean; ok: boolean | null; body: string; notes: string; error: string; questions: FillQuestion[] }
// what a part rewrite reads besides the draft: the email it answers, the chat conversation, the Ask SleePO thread
export type RewriteCtx = { kind: 'email' | 'chat'; item_id?: number | null; ids?: number[]; app?: 'teams' | 'slack'; tid?: string | null; subject?: string }
export type LiveNote = { id: string; title: string; meeting_at: string; url: string }
export type LiveState = { event: { id: string; subject: string; attendees: string[]; start: string | null; end: string | null } | null; note: LiveNote | null; notes: LiveNote[]
  turns: { who: string; text: string }[]; chars: number; fetched: string | null; grew: string | null; signed_in: boolean; error: string }
export type ReplyJob = { running: boolean; ok: boolean | null; subject: string; body: string; notes: string; error: string; reply_to: string; revised?: boolean; unchanged?: boolean }
// Inbox › Drafts (assist/new_mail.py, Sam 26 Oct 2026): Outlook's drafts (read from Apple Mail, never stored), new emails written in
// SleePO, replies in progress, and new emails SleePO recommends (email actions on task steps)
export type OutlookDraft = { key: string; subject: string; to: Addr[]; cc: Addr[]; ts: string; body: string; quoted: string
  reply_to_item: number | null; reply_subject: string | null; web_link: string; attachments: string[] }
export type SleepoDraft = { id: number; key: string; origin: 'sam' | 'mail'; to: string[]; cc: string[]; subject: string; body: string; ask: string
  length: number | null; notes: string | null; prev_body: string | null; first_body: string | null; mail_key: string | null
  outlook: { id: string; web_link: string | null } | null; job: string | null; status: 'draft' | 'sent' | 'discarded'; created_at: string; updated_at: string
  in_outlook?: string; initiative_id?: number | null; focus?: string[] }
export type ReplyInProgress = { key: string; item_id: number; subject: string; body: string; mode: string; source: 'chat' | 'edit' | 'generated'; ts: string; to: Addr[] }
// most important first (new_mail._rank): level 'high' is what to send first, rank_why says why
export type RecommendedEmail = { key: string; step_id: number; index: number; task_id: number; task_title: string; step_title: string; suggested: boolean
  score: number; level: 'high' | 'normal' | 'low'; rank_why: string[]; due: string | null
  origin: string; why: string; filed: string; sources: { label: string; url: string }[]; ts: string; logged: string[]; actions: Record<string, unknown>[]
  action: { type: 'email'; label: string; to?: string[]; cc?: string[]; subject?: string; body?: string; notes?: string; prev_body?: string | null; outlook?: { id: string; web_link: string | null } } }
export type DraftsSuggest = { running: boolean; ok: boolean | null; error: string | null; count: number | null; finished: string | null; started: string } | null
// The Actions page (assist/actions_view.py; Sam, 25 Nov 2026): reactive (someone waits on Sam) and proactive (SleePO recommends).
// Every row is an email, a register item or a task step; acting on it goes through that thing's own routes.
export type ActionKind = 'email' | 'message' | 'followup' | 'send' | 'promise' | 'next'
export type ActionItem = { key: string; kind: ActionKind; title: string; line: string; why?: string; who: string; person_id: number | null
  app?: 'outlook' | 'teams' | 'slack'; ts: string | null; due?: string | null; tags: string[]; hot: boolean; open: string
  item_id?: number; loop_id?: number; attachments?: boolean; ready?: boolean   // emails and messages
  task?: string; task_id?: number; step_id?: number; filed?: string; suggested?: boolean; status?: string   // task steps
  draft?: string | null; index?: number; level?: 'high' | 'normal' | 'low'; rank_why?: string[]; made?: string | null
  said?: { label: string; url: string } | null; meeting?: { id: number; title: string; at: string | null; url: string }
  sources?: { label: string; url: string }[]; action?: { type: string; label?: string; to?: string[]; cc?: string[]; subject?: string; channel?: string; user?: string } | null }
export type ActionsData = { reactive: { emails: ActionItem[]; messages: ActionItem[]; followups: ActionItem[] }
  proactive: { send: ActionItem[]; promises: ActionItem[]; next: ActionItem[] }; counts: { reactive: number; proactive: number } }
export type DraftsData = { outlook: OutlookDraft[]; sleepo: SleepoDraft[]; replies: ReplyInProgress[]; recommended: RecommendedEmail[]; outlook_error: string; suggest: DraftsSuggest }
export type DraftJob = { running: boolean; ok: boolean | null; subject: string; body: string; notes: string; error: string; revised: boolean; unchanged?: boolean; to?: string[] }
export type SearchHit = { kind: string; ref: string; title: string; title_hl: string; ts: string; url: string; sub: string; snippet: string; score: number; how: string; more?: number }
export type SearchResult = { query: string; results: SearchHit[]; counts: Record<string, number>; total: number; expanded: string[]; mode: string; hinted?: string[]; filters: { types: string[]; from: string[]; after: string | null; before: string | null } }
// the graph puts people in the middle: Sam is `me`; each person carries their days in touch with Sam (90 days) and open items
export type GNode = { id: string; type: 'person' | 'partner' | 'org' | 'initiative' | 'area' | 'topic' | 'task' | 'meeting' | 'document'; label: string; sub: string; href: string; weight: number | null; avatar?: string
  me?: boolean; contact?: number; tasks?: number; group?: string; org_logo?: string
  relation?: string; logo?: string; deals?: number; open_usd?: number   // companies
  rank?: number; detail?: string; ask?: string; private?: boolean       // top of mind
  status?: 'open' | 'snoozed' | 'suggested' }                           // tasks
export type GEdge = { source: string; target: string; rel: string; w?: number }
export type Initiative = { id: string; name: string; status: string; owner: string; milestone: string; stands: string; pending: number; risks: number; weight: number }
export type Doc = { id: string; section: string; title: string; path: string; mtime: string; meta: Record<string, string>; words: number; md?: string }
export type Stream = { id: string; name: string; source: string }
// freshness of a source, computed on the server (assist/source_status.py); the same everywhere it is shown
export type SourceState = 'fresh' | 'stale' | 'capped' | 'off' | 'unknown'
// issue: the key of a connection problem that stopped it (assist/connections.py); its label then says Sign-in needed etc.
// and its age is that of the last pull that came in full
export type SourceStream = { id: string; system: string; name: string; last: string | null; age_hours: number | null; max_age_hours: number | null; state: SourceState; label: string; note: string; via: string | null; issue?: string | null }
export type SourceStatus = { state: SourceState; label: string; age_hours: number | null; last: string | null; via: string | null; note: string; streams: SourceStream[]; issue?: string | null }
// what SleePO cannot reach and what to do (assist/connections.py, GET /api/connections; Sam, 17 Nov 2026)
// login: SleePO asks Claude Code for that connector's sign-in link and opens it (claude.ai/settings/connectors only says "moved")
export type ConnFix = { label: string; steps: string; login?: string; open?: 'disk' | 'python' | 'mail' | 'calendar'; command?: string; check?: boolean; also?: ConnFix }
export type ConnLogin = { url: string | null; opened: boolean; note: string }
export type ConnIssue = { key: string; name: string; status: string; kind: 'signin' | 'unreachable' | 'access' | 'app'; headline: string; feeds: string
  since: string | null; seen: string | null; urgent: boolean; affected: { id: string; name: string; last_ok: string | null }[]; fix: ConnFix }
export type Connections = { checked: string | null; issues: ConnIssue[]; checked_now?: boolean }
// what came in since a record was written (graph memory: assist/graph_memory.py, DESIGN-GRAPH-MEMORY.md; Sam, 17 Nov 2026)
export type GraphKind = 'initiative' | 'topic' | 'task' | 'event' | 'person' | 'org' | 'doc'
export type GraphChange = { item_id: number; kind: string; label: string; who: string; title: string; ts: string | null; app: string; hop: number; via: string }
// graph memory, phase 2 (assist/graph_refresh.py): SleePO's latest read of a record's new material; current = it describes the
// record as it stands (the rewrite it made, or "no change" read after the record was written)
export type GraphFact = { text: string; certainty: 'confirmed' | 'likely' | 'unverified'; items: (Omit<GraphChange, 'hop' | 'via'>)[] }
export type GraphReview = { at: string; verdict: 'no change' | 'changed'; applied: 'status' | 'topic' | 'brief' | null; current: boolean; facts: GraphFact[]; read: number }
export type GraphChanges = { kind: GraphKind; id: number; record_at: string | null; count: number; hops: { '1': number; '2': number }; items: GraphChange[];
  unreviewed: number; refreshing: boolean; review: GraphReview | null }
export type System = { id: string; name: string; vendor: string; color: string; mono: string; logo: string; kind: string; how: string; auth: string; connect: string; keys: string[]; streams: Stream[]; status?: SourceStatus | null }
export type CoverageRow = { key: string; source: string; available: string | number; digested: string | number; analysed: string | number; health: string; last_seen: string; note: string }
export type Coverage = { sources: CoverageRow[]; gaps: string[]; freshness_rule: string; updated: string }
// assist/gaps.py: a gap with when a pull last reported it; current = in the last 3 days
export type SourceGap = { text: string; seen: string | null; current: boolean }
// api._source_pulls: per system, pulls that brought something in (newest first) and the quiet checks counted
export type SourcePull = { stream: string; at: string; available: number | null; pulled: number; complete: boolean; agent: string; note: string }
export type SourcePulls = { total: number; quiet_week: number; last: string | null; recent: SourcePull[] }
export type StreamTable = { title: string; mtime: string; heading: string; headers: string[]; rows: { c: string[]; l: Link[] }[] }
export type Brief = { title: string; today: string; sources_line: string; sections: Record<string, string>; path: string; actions?: Record<string, unknown>[] }
export type MsgItem = { id: number; source_id: string; kind: string; ts: string; from_name: string | null; subject: string | null; text: string | null; thread: string | null; url: string | null; noise: number; conv_kind?: string | null; conv_id?: string | null; conv_title?: string | null }
export type RecentConv = { key: string; kind: 'dm' | 'group' | 'meeting' | 'channel'; title: string; person: string | null; apps: ('teams' | 'slack')[]; count: number
  item_id: number; app: 'teams' | 'slack'; sent_at: string; author: string | null; mine: boolean; text: string; files: number; people: string[] }
export type MessageCard = { item_id: number; app: 'teams' | 'slack'; author: string | null; sent_at: string; body: string; link: string | null; conversation: string | null
  attachments: { id: number; name: string; content_type: string | null; size: number | null; url: string | null; read: boolean; reviewable: boolean; review: { comments: number } | null }[] }
export type ChatFull = { body: string | null; links: { url: string; title: string }[]; attachments: { id: number; name: string; content_type: string | null; size: number | null; url: string | null; read?: boolean }[]; sent_at: string }   // read: SleePO holds the file's text
export type TodoItem = { id: string; rank: number; priority: 'now' | 'today' | 'this_week'; category: string; title: string; why: string | null; effort_min: number | null; due: string | null
  status: 'open' | 'done' | 'dismissed' | 'snoozed'; snooze_until: string | null; updated_at: string; sources: { ref: string; label: string; url: string }[]; actions: import('@/components/Actions').Action[] }
// Tasks (assist/tasks.py): initiative → task → sub-task (step) → action. A step owned by someone else is a wait on them.
export type TaskStatus = 'suggested' | 'open' | 'snoozed' | 'done' | 'dropped' | 'dismissed' | 'expired'
export type TaskKind = 'do' | 'reply' | 'chase' | 'decide' | 'create' | 'prep'
export type TaskNode = { id: number; parent_id: number | null; initiative_id: number | null; initiative: string | null; weight: number | null
  area: string | null; area_name: string | null   // a day-to-day area instead of an initiative (never both)
  title: string; done_when: string | null; why: string | null; notes: string | null; kind: TaskKind | null; owner: string | null; owner_person_id: number | null
  due: string | null; priority: 'now' | 'today' | 'this_week' | 'later' | null; status: TaskStatus; snooze_until: string | null; position: number
  origin: 'sam' | 'mail' | 'meeting' | 'register' | 'assistant' | null; sources: { ref: string; label: string; url: string; closes?: boolean }[]
  actions: import('@/components/Actions').Action[]; log: { at: string; what: string; step?: number | null; label?: string | null; url?: string }[]
  loop_id: number | null; created_at: string; accepted_at: string | null; closed_at: string | null; closed_by: string | null; close_reason: string | null
  close_ref: { label: string; url: string } | null; people: string[]
  // tasks only
  subtasks: TaskNode[]; next_id?: number | null; waiting?: boolean; all_done?: boolean; steps_done?: number; steps_total?: number; score?: number | null
  next_due?: string | null; parent_title?: string | null; parent_status?: TaskStatus | null; decide_or_drop?: string | null
  handoff?: boolean   // steps: someone else's, with a message Sam has not sent yet (his move first, then a wait on them)
}
export type TaskArea = { key: string; name: string; hint: string }
export type CalRefreshState = { running: boolean; started?: string; finished?: string; ok?: boolean; secs?: number | null; log?: string[]; granola?: string | null; error?: string | null }
// Tasks › History (assist/task_history.py): the tasks Sam would have had, rebuilt from what he did
export type HistoryAction = { ref: string; key: string; ts: string; label: string; url: string | null; item_id: number | null; step_id: number | null }
export type HistoryStep = { id: number; task_id: number; title: string; kind: string | null; owner: string | null; position: number; actions: HistoryAction[] }
export type HistoryTask = { id: number; title: string; done_when: string | null; initiative_id: number | null; initiative: string | null; area: string | null
  kind: string | null; started_at: string; finished_at: string; days: number | null; status: 'done' | 'removed'; edited: number; people: string[]; week: string
  steps: HistoryStep[]; other_actions: HistoryAction[] }
export type HistoryWeek = { week: string; tasks: HistoryTask[]; status: 'ok' | 'error' | null; actions: number | null; not_tasks: number; error: string | null }
export type TaskHistory = { weeks: HistoryWeek[]; retention_days: number; earliest: string; pending: string[]; job: { running: boolean; ok?: boolean; note?: string; finished?: string } }
export type HistoryEval = { suggestions_answered: number; accepted_when_like_history: string; accepted_otherwise: string; history_tasks: number; edited_by_sam: number; removed_by_sam: number }
export type TasksData = { tasks: TaskNode[]; suggestions: TaskNode[]; initiatives: { id: number; slug: string; name: string; weight: number }[]; areas: TaskArea[]
  cutover_at: string | null; suggested_at: string | null; job: { running: boolean; ok: boolean | null; error: string | null; count: number | null; finished: string | null } | null }
export type TaskStepSpec = { title: string; owner?: string | null; kind?: TaskKind; due?: string | null; actions?: import('@/components/Actions').Action[] }
export type TaskProposal = { title: string; done_when: string; why: string; initiative_id: number | null; area: string | null; priority: TaskNode['priority']; due: string | null
  add_to: number | null; add_to_title: string | null; subtasks: TaskStepSpec[]; sources: TaskNode['sources'] }
// a task's documents (assist/tasks.py documents): one per file family, newest version first, older versions counted
export type TaskDoc = { id: string; name: string; ts: string; reason: string; pinned: boolean; versions: string[] }
// mail threads, messages and meeting notes linked to a task (assist/task_links.py for_task), newest first
export type TaskLinked = { item_id: number; kind: 'mail' | 'chat' | 'meeting'; title: string; who: string; ts: string; url: string; source: 'thread' | 'model' | 'sam'; confidence: number }
export type TaskDocs = { pinned: TaskDoc[]; related: TaskDoc[]; words: string[] }
export type MailTaskProposal = { status: 'ok' | 'error' | 'used' | 'dismissed' | null; proposal: TaskProposal | null; needs_task: boolean | null; note: string | null
  created_at: string | null; task_id: number | null; task_title: string | null; pending: boolean }
export type TaskJob = { running: boolean; ok: boolean | null; error: string; proposal: TaskProposal | null }
// An action's sources resolved by the server (assist/action_context.py): what the action answers or builds on, shown under it
export type EmailInfo = { item_id: number; graph_id?: string; subject: string; from: Addr; to: Addr[]; cc: Addr[]; date: string | null; sent?: boolean; text: string; full: boolean
  web_link: string | null; attachments: string[]; earlier: { item_id: number; from: string; me: boolean; date: string | null; text: string }[]
  needs_reply?: boolean; reply_why?: string; answered?: boolean; missing?: boolean }
export type ActionSource = { ref: string; label: string; url: string; closes: boolean } & (
  | ({ kind: 'email' } & EmailInfo)
  | { kind: 'chat'; item_id: number; source: string; conversation: string; conversation_kind: string; author: string; date: string; text: string; web_link: string | null
      earlier: { author: string; date: string; text: string }[]; missing?: boolean }
  | { kind: 'item'; loop_id: number; item_kind: 'reply' | 'promise' | 'waiting' | 'decision'; title: string; detail: string | null; who: string | null; since: string | null
      due: string | null; status: string; suggestion: string | null; said: { meeting_id: number; t: number; quote: string; name?: string; me?: boolean; clock?: string } | null
      links: { label: string; url: string }[]; emails: number[]; email?: EmailInfo | null; missing?: boolean }
  | { kind: 'meeting'; event_id?: string; subject?: string; start?: string; end?: string; attendees?: string[]; web_link?: string }
  | { kind: 'file' } | { kind: 'other' })
export type ActResult = { ok: boolean; app: string; attached: string | null; workspace: string | null; context?: string; start_from?: string | null; sources?: string[]; context_chars?: number }
export type TodoList = { items: TodoItem[]; generated_at: string | null; job: { running: boolean; ok: boolean | null; error: string | null; started: string; finished: string | null; count?: number } | null }
export type PipelineRow = { id: string; item_id: number; url: string | null; account: string; name: string; stage: string; stage_rank: number; forecast_category: string; probability: number | null
  sale_type: string; use_case: string; region: string; currency: string; acv: number; acv_usd: number; weighted_usd: number; forecast_usd: number; close_date: string; quarter: string; created: string; overdue: boolean; odd_date: boolean }
export type ClosedDeal = { id: string; item_id: number; url: string | null; account: string; name: string; won: boolean; sale_type: string; kind: 'New business' | 'Renewal' | 'Services'
  region: string; use_case: string; currency: string; acv: number; value_usd: number; net_usd: number; close_date: string; quarter: string; created: string; cycle_days: number | null }
// Revenue retention from Salesforce renewals (assist/renewals.py)
export type RetAgg = { n: number; won: number; lost: number; prior: number; renewed: number; kept: number; churn: number; downsell: number; uplift: number
  lost_arr: number; grr: number | null; nrr: number | null; renewal_rate: number | null }
export type RetSegment = { region: string; band: string; n: number; prior: number; share: number; quoted: number; grr: number; nrr: number; renewal_rate: number
  hist_n: number; source: 'segment' | 'region' | 'all'; expected_kept: number; expected_renewed: number }
export type RetOutlook = { n: number; accounts: number; prior: number; segments: RetSegment[]; grr: number | null; nrr: number | null
  expected_kept: number; expected_renewed: number; expected_lost: number; stage: { grr: number | null; nrr: number | null }
  as_quoted: { grr: number | null; nrr: number | null }; downsell_quoted: number }
export type RetBasis = {
  actual: RetAgg & { by_quarter: (RetAgg & { key: string })[]; by_region: (RetAgg & { key: string })[]; by_band: (RetAgg & { key: string })[]
    by_region_quarter: (RetAgg & { region: string; quarter: string })[]; logos: number; logos_lost: number; logo_retention: number | null; lost_logo_accounts: string[] }
  company: { base_start: number; new_logo: number; expansion: number; expansion_taken_back: number; grr: number | null; nrr: number | null
    fy: { lost: number; uplift: number; expansion: number; grr: number | null; nrr: number | null } }
  rest_of_year: RetOutlook
  next_year: RetOutlook & { year: number; base_start: number; expansion: number; uplift: number; company_grr: number | null; company_nrr: number | null
    by_quarter: { quarter: string; prior: number; n: number; expected_kept: number }[] }
}
export type RetRenewal = { id: string; item_id: number; url: string | null; account: string; region: string; band: string; outcome: 'won' | 'lost' | 'open'
  close_date: string; quarter: string; prior_usd: number; value_usd: number; change_usd: number; stage: string; probability: number | null; overdue: boolean
  replaced_by?: { sale_type: string; close_date: string; value_usd: number; url: string | null; kind: string } | null
  history?: string; rate?: { recorded: number; adjusted: number } }
export type Retention = { today: string; pulled: string | null; since: string; year: number; min_n: number; repaper_days: number; fx: Record<string, number>
  base_now: { arr: number; contracts: number; accounts: number; by_region: Record<string, number> }
  bases: { recorded: RetBasis; adjusted: RetBasis }; closed: RetRenewal[]; upcoming: RetRenewal[]
  notes: { loss_reasons: number; lost_renewals: number; repapers: number; regions_other: string[] } }
export type AgentRunning = { key: string; what: string; started: string | null; elapsed: number | null; progress?: number | null; eta_secs?: number | null; phases?: { name: string; status: string }[]; manual?: boolean }
export type AgentInfo = { key: string; name: string; what: string; trigger: string; page: string; running: boolean; last: string | null; ok: boolean | null; error: string | null; runs_24h: number; avg_secs?: number | null; avg_n?: number; runnable?: boolean; not_runnable?: string | null; has_log?: boolean; manual?: { started: string | null; finished: string | null; ok: boolean | null; running: boolean } | null }
export type AgentLogTail = { running: boolean; started?: string | null; finished?: string | null; ok?: boolean | null; lines: string[]; source: 'refresh' | 'manual' | null }
export type AgentLog = { id: number; agent: string; key: string; started: string; finished: string | null; secs: number | null; ok: boolean | null; error: string | null }
export type AgentsSnap = { running: AgentRunning[]; agents: AgentInfo[]; log: AgentLog[]; busy_pages: string[]; now: string }
export type ProfilePage = { key: string; label: string; path: string; exists: boolean; route: string | null; updated: string | null }
export type ProfileArea = { key: string; name: string; hint: string }
export type ProfileData = {
  profile: Record<string, unknown>; stored: Record<string, unknown>; defaults: Record<string, unknown>; me_person: { id: number; name: string } | null
  followed_channels: string[]; task_areas: ProfileArea[]; pages: ProfilePage[]; needs_setup: boolean; restart_needed?: boolean; wrote_seed?: boolean
  org: { name: string; pack_path: string; pack_exists: boolean; domains: string[]; overrides: Record<string, unknown>; pack_setting: string; has: Record<string, number | boolean> }
  suggest?: { timezone?: string; emails?: string[]; full_name?: string; role?: string; org_matches?: boolean }
}
export type ProfileSave = { fields?: Record<string, unknown>; followed_channels?: string[]; task_areas?: ProfileArea[]; org?: Record<string, unknown>; org_pack?: string }
// what the user is looking at (assist/page_context.py): label names it, detail says what the chat reads; who / avatar / app /
// draft / date draw the chip (a face with the app's logo, or the meeting's day)
// a chip: one thing a page passes to Ask SleePO (assist/page_context.py chip; components/AssistContext.tsx). sub: its second line
export type PageCtx = { kind: string; ref: string; label: string; detail: string; who?: string; avatar?: string; app?: '' | 'teams' | 'slack' | 'outlook'; draft?: boolean; date?: string; sub?: string
  href?: string; gone?: boolean }   // href: the app address clicking the chip opens; gone: a kept chip whose thing SleePO no longer holds
// What hovering a chip shows (assist/chip_preview.py): the thing as it is now, in a few lines
export type ChipLine = { who?: string; when?: string; when_text?: string; text: string; mine?: boolean; done?: boolean; kind?: string }
export type ChipPreview = PageCtx & { kicker: string; at: string; end?: string; facts: [string, string, string?][]; text: string; md: string
  lines_label: string; lines: ChipLine[]; draft_text: string; url: string; reads: string }
export type Account = {
  signed_in: boolean; method: 'local' | string; accounts: boolean; note: string
  user: { name: string; first_name: string; email: string; emails: string[]; role: string; company: string; avatar: string; person_id: number | null }
  data: { folder: string; code: string; database: string }
}
// First-run setup (assist/onboarding.py, views/setup.tsx) and the demo copy (assist/demo.py)
export type SetupCheck = { id: string; title: string; why: string; status: 'ok' | 'todo' | 'optional'; detail: string; required: boolean; python_app?: string; url?: string
  recommended?: boolean; app?: boolean; allowed?: boolean }   // Granola and FluidVoice: strongly recommended, installed or not
export type SetupBet = { slug?: string; name: string; weight: number; goal: string }
export type SetupState = { needed: boolean; done: boolean; demo: boolean; imported: number
  profile: { full_name: string; first_name: string; emails: string[]; role: string; timezone: string; signoff: string }
  suggest: { emails?: string[]; full_name?: string; role?: string; timezone?: string; org_matches?: boolean }
  org: { name: string; domains: string[]; pack: boolean; pack_path: string; crm: boolean; jira: boolean; roadmap: boolean }
  checks: SetupCheck[]; initiatives: SetupBet[] }
// The onboarding agent (assist/onboard_agent.py): what it read and what it inferred, for the Welcome page to confirm
export type OnboardPerson = { name: string; title?: string; why?: string; evidence?: string; refs: string[] }
export type OnboardBet = { name: string; goal: string; weight: number; why?: string; refs: string[] }
export type OnboardOption = { label: string; value: string; description?: string }
export type OnboardQuestion = { id: string; field: 'role' | 'manager' | 'team' | 'bets' | 'top_bet' | 'personal' | 'company'; header: string; question: string; multi: boolean; options: OnboardOption[] }
export type Conf = 'confirmed' | 'likely' | 'unverified'
export type Onboard = { summary: string
  identity: { full_name: string; first_name: string; emails: string[]; title: string; role_short: string; confidence: Conf; evidence: string; refs: string[] }
  company: { name: string; domains: string[]; about: string; confidence: Conf; refs: string[] }
  manager: { name: string; title: string; confidence: Conf; evidence: string; refs: string[] } | null
  team: OnboardPerson[]; key_people: OnboardPerson[]; bets: OnboardBet[]
  voice: { signoff: string; spelling: '' | 'British' | 'American'; notes: string[]; refs: string[] }
  personal_meetings: { title: string; why: string }[]
  calendar: { meeting_days?: string; meeting_hours?: string; meeting_minutes?: number }
  timezone: string; questions: OnboardQuestion[]; ref_labels: Record<string, string> }
export type ScanState = { running: boolean; stage?: 'import' | 'chat' | 'read' | 'think' | 'review' | 'failed' | null; chat?: boolean; started?: string | null
  finished?: string | null; notes: string[]; result?: Onboard | null; error?: string | null; applied?: string | null; think_started?: string | null
  phases?: { name: string; status: string }[]; typical_secs?: number; failed_at?: string | null }
export type DemoState = { running: boolean; url: string; folder: string; created: boolean; created_at: string | null; this_is_demo: boolean }
export type Meta = { built: string; built_iso: string; initiatives: string[]; logos: Record<string, string>; db: string; retention_days: number; counts: Record<string, number>; last_data?: string | null; last_agents?: string | null; profile?: import('./profile').Profile; org?: import('./profile').Org; app_name?: string
  demo?: boolean; setup?: { needed: boolean; done: boolean } }

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `${r.status} ${path}`)
  return r.json()
}

// a request from Ask SleePO to do steps on the Mac (assist/desktop.py): nothing runs until Sam allows it
export type DesktopStep = { do: 'folder' | 'copy' | 'move' | 'rename' | 'trash' | 'download' | 'open' | 'show'; label: string; detail: string[]; warn: string
  state: 'waiting' | 'running' | 'done' | 'failed' | 'skipped'; result?: string; error?: string; out?: string[]; progress?: string }
export type DesktopReq = { id: string; thread: string; run: string; created_at: string; why: string; status: 'pending' | 'running' | 'done' | 'declined' | 'expired' | 'stopped'
  steps: DesktopStep[]; answer?: { approve: boolean; steps: number[]; by: 'you' | 'expired' | 'stopped'; at: string } | null; lost?: boolean }

export type SoulUse = { agent: string; label: string; how: 'carried' | 'reads' | 'inline' | 'summary'; sections: string[]; chars: number | null; missing: string[]; note: string | null }
export type Souls = Record<'company' | 'cpo' | 'sleepo', { file: string; exists: boolean; updated: string | null; chars: number; used_by: SoulUse[] }>

async function send<T>(method: string, path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) { let m = await r.text(); try { m = JSON.parse(m).detail ?? m } catch { /* plain text */ } throw new Error(m) }
  return r.json()
}
async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { cache: 'no-store' })
  if (!r.ok) throw new Error(`${r.status} ${path}`)
  return r.json()
}

export type Loop = { id: number; kind: 'reply' | 'promise' | 'waiting' | 'decision'; title: string; detail: string | null; counterpart: string | null
  person_id: number | null; person?: string | null; org_id: number | null; org?: string | null; due: string | null; origin_at: string | null
  origin_basis: 'source' | 'text' | 'recorded' | null; age_days: number | null; status: 'open' | 'done' | 'dropped' | 'snoozed'; snooze_until: string | null
  closed_at: string | null; closed_by: string | null; close_reason: string | null; close_ref: { label: string; url: string } | null
  suggestion: 'decide_or_drop' | 'duplicate' | null; suggestion_note: string | null; dup_of?: number | null; links: { label: string; url: string }[]; initiatives: string[]; reply_to: string | null
  said?: { meeting_id: number; name: string; person_id: number | null; me: boolean; t: number; clock: string; quote: string } | null }   // the meeting turn it was said in
export type TimelineItem = { id: number; kind: string; label: string; source: string; ts: string; from: string; title: string; snippet: string; url: string; confidence: number
  role?: 'from' | 'to' | 'cc' | null; mine?: boolean; where?: string; dm?: boolean   // email: how the person was on it; chat: its conversation
  link?: { role: string | null; reason: string | null; verdict: 'confirmed' | 'rejected' | null } }   // how this item is linked to the entity, and the evidence   // email: how the person was on it; chat: its conversation
export type EntityView = { type: 'person' | 'org' | 'initiative' | 'doc' | 'product' | 'roadmap' | 'ticket'; entity: { id: number; name: string; kind?: string; title?: string; role?: string; region?: string | null
  domains?: string[]; opportunities?: { name: string; stage: string; close_date: string; acv: number; currency: string; sale_type: string; is_open: boolean | null }[]
  people?: { id: number; name: string; n: number }[]; url?: string; key?: string; status?: string | null; issue_type?: string | null; links?: ItemLink[] }; open: Loop[]; timeline: TimelineItem[]; last_activity: string | null; spoke?: Spoke[] }
export type LinkSample = { item_id: number; entity_type: 'person' | 'org'; entity_id: number; name: string; role: string | null; reason: string | null; confidence: number; kind: string; label: string; ts: string; from: string; title: string; snippet: string; url: string }
export type LinkQuality = { precision: Record<string, { reviewed: number; precision: number | null }>; recall: { confirmed: number; found_and_shown: number; hidden_right: number; recall: number | null }; coverage: Record<string, { items: number; person: number; org: number; initiative: number }> }
export type ItemLink = { entity_type: string; entity_id: number; confidence: number; role: string | null; reason: string | null; verdict: 'confirmed' | 'rejected' | null; name: string | null }
export type Point = { t: number; clock: string; text: string }
export type Spoke = { meeting_id: number; title: string; starts_at: string; words: number; turns: number; share: number; points: Point[] }   // a meeting where the person spoke
// Everything about one person for their page (assist/person_page.py); the day-by-day activity is api.entity('person', id)
export type PersonSaid = { kind: 'chat' | 'email' | 'meeting'; ts: string; url: string; text?: string; where?: string; dm?: boolean; channel?: boolean; subject?: string
  meeting_id?: number; title?: string; share?: number; points?: Point[] }
export type PersonDoc = { id: string; name: string; title: string; ts: string | null; how: 'theirs' | 'sent' | 'shared_with' | 'discussed' | 'named'; where: string; url: string
  copies: number; kind: string; summary: string; ext: string; sensitive: boolean }
export type PersonUpcoming = { event_id: string; item_id: number; subject: string; start: string; end: string | null; others: number; one_to_one: boolean; join_url: string; web_link: string
  organizer: string; brief: { doc_id: string; title: string; updated_at: string; generated: string } | null }
export type PersonPageData = { id: number; name: string; email: string; teams: string; upcoming: PersonUpcoming[]; open: Loop[]; closed: Loop[]
  last: Partial<Record<'email' | 'chat' | 'meeting', { ts: string; title: string; url: string; mine: boolean; where: string | null }>>
  contact: { weeks: number[]; days_84: number; usual_gap: number | null; since_last: number | null }; counts_30: { email: number; messages: number; meetings: number }
  said: PersonSaid[]; documents: PersonDoc[]; initiatives: { slug: string; name: string; weight: number; key: boolean; n: number }[]
  roadmap: { id: string; name: string; status: string; horizon: string }[]; with: { id: number; name: string; title: string; avatar: string | null; n: number }[]; profile_updated: string
  topics: PersonTopic[] }
// a current Top of mind topic the person raised or is part of (person_page.on_the_table); raised: 'them', 'you' or another name
export type PersonSummaryRef = { kind: 'item' | 'topic' | 'meeting' | 'email' | 'chat' | 'event'; label: string; url: string; date: string | null }
export type PersonSummary = { person_id: number; name: string; summary: { situation: string; raise: { text: string; refs: string[] }[] }
  refs: Record<string, PersonSummaryRef>; newest: string | null; created_at: string; prompt_version: string; model?: string | null }
export type PersonSummaryState = { summary: PersonSummary | null; running: boolean; error: string | null; newer: boolean; activity: string | null }
export type PersonTopic = { id: number; title: string; summary: string; ask: string; initiative: string | null; initiative_slug: string | null; area_name: string | null
  private: boolean; pinned: boolean; raised: string; last_ts: string | null; is_new: boolean }
export type SpeakerPoints = { name: string; person_id: number | null; is_me: number; words: number; share: number; points: Point[] }
export type MeetingPerson = { meeting_id: number; key: string; person_id: number | null; name: string; email: string | null; confidence: number; sources: string[]; evidence: string | null; status: 'suggested' | 'confirmed' | 'rejected'; accepted: boolean }
// Knowledge › Product › Code base (assist/codebase.py): the company's code from the git clones on this Mac
export type CodeRepo = { name: string; path: string; remote: string; web: string; label: string; about: string; ref: string; sha: string; branch: string
  as_of: string; subject: string; files: number; languages: [string, number][]; folders: [string, number][]; guide: string | null; tracking: boolean
  fetched_at: string | null; fetch: { ok?: boolean; note?: string; new_commits?: number | null; finished?: string } }
export type CodeOverview = { repos: CodeRepo[]; not_cloned: { path: string; url: string; about: string }[]; hidden: string[]; host: string; map_doc: string
  configured: boolean; running: boolean; fetch: { running?: boolean; started?: string; finished?: string; ok?: boolean } }
export type CodeHit = { path: string; hits: number; test: boolean; link: string; lines: { n: number; text: string; link: string }[] }
export type CodeSearch = { error: string | null; repos: { name: string; branch: string; sha: string; as_of: string; web: string; total: number; file_count: number; files: CodeHit[]; error?: string }[] }
export type CodeFile = { repo: string; path: string; branch: string; sha: string; link: string; start: number; end: number; total: number; text: string }
export type RoadmapItem = { id: string; name_internal: string; name_external: string; theme: string; grp: string; headline: string; platform_theme: string; start_q: string; end_q: string; horizon: string; status: string; committed: boolean; owners: string[]; owner_ids: Record<string, string>; size: string; confidence: string; customers: string; value: string; detail: string; gap: string; src: string; notes: string; show_investor: boolean; show_internal: boolean; show_nda: boolean; show_public: boolean }
export type RoadmapRefresh = { running: boolean; started?: string; finished?: string; ok?: boolean; note?: string; status?: 'imported' | 'unchanged' | 'refused'
  added?: string[]; changed?: string[]; removed?: string[]; count?: number; modified?: string | null }
export type StrategyThought = { title: string; type: string; horizon: string; confidence: string; thesis: string; evidence: string[]; implications: string; questions: string[]; raise_with: string[]; sources: { code: string; label: string; url: string }[] }
export type StrategyMemo = { id: number; created_at: string; memo: { headline: string; thoughts: StrategyThought[]; watch: string[] }; refs: Record<string, { label: string; url: string }>; marks: Record<string, string> }
export type ActionType = { key: string; name: string; category: string; how: string; measured: boolean; sleepo: string | null; count: number; per_week: number; prev: number; trend: number | null; weeks: number[]; last: string | null; peak_hours: number[]; peak_days: string[]; people: { name: string; count: number }[]; median_words: number | null; suggested: number | null }
export type ActionProfile = { days: number; computed: string; types: ActionType[]; by_person: { name: string; total: number; channels: Record<string, number>; preferred: string }[]; suggestions: { by_type: Record<string, number>; copied: number | null } }
// What SleePO remembers from what Sam tells it (assist/remember.py, 28 Oct 2026): System › Memory
export type MemoryKind = 'preference' | 'fact' | 'correction'
export type Memory = { id: number; text: string; kind: MemoryKind; scope: string[]; people: string[]; people_ids: number[]; quote: string | null
  source: string | null; source_ref: string | null; source_label: string | null; status: 'active' | 'deleted' | 'replaced'
  created_at: string; updated_at: string | null; confirmed_at: string | null; expires_at: string | null }
export type MemoryList = { memories: Memory[]; retention_days: number; learning: { running: boolean; last_run: string | null; read_until: string | null } }
export type MemoryIn = { text?: string; kind?: MemoryKind; scope?: string[]; people?: number[] }

export const api = {
  memory: () => get<MemoryList>('/api/memory'),
  memoryAdd: (b: MemoryIn) => post<{ id: number }>('/api/memory', b),
  memoryUpdate: (id: number, b: MemoryIn) => post<{ changed: boolean }>(`/api/memory/${id}`, b),
  memoryOp: (id: number, op: 'keep' | 'delete' | 'restore') => post<{ ok: boolean }>(`/api/memory/${id}/${op}`),
  memoryLearn: () => post<{ started: boolean }>('/api/memory/learn'),
  meta: () => get<Meta>('/api/meta'),
  account: () => get<Account>('/api/account'),
  accountLogout: () => post<{ ok: boolean; reason?: string }>('/api/account/logout'),
  profile: () => get<ProfileData>('/api/profile'),
  profileSave: (b: ProfileSave) => send<ProfileData>('PUT', '/api/profile', b),
  profileApply: () => post<{ restarting: boolean; reason?: string }>('/api/profile/apply'),
  profileImport: (data: unknown) => post<ProfileData>('/api/profile/import', { data }),
  setup: () => get<SetupState>('/api/setup'),
  setupGranola: (key: string) => post<{ ok: boolean; checks: SetupCheck[] }>('/api/setup/granola-key', { key }),
  setupPack: (data: unknown) => post<SetupState>('/api/setup/org-pack', { data }),
  setupBets: (rows: SetupBet[]) => post<{ initiatives: SetupBet[] }>('/api/setup/initiatives', { rows }),
  setupOpen: (what: 'disk' | 'python') => post<{ ok: boolean }>('/api/setup/open', { what }),
  setupScan: () => get<ScanState>('/api/setup/scan'),
  setupScanStart: (chat: boolean) => post<ScanState>('/api/setup/scan', { chat }),
  setupApply: (draft: unknown) => post<SetupState>('/api/setup/apply', { draft }),
  setupFinish: (restart = true) => post<{ ok: boolean; restarting: boolean }>('/api/setup/finish', { restart }),
  demo: () => get<DemoState>('/api/demo'),
  demoAction: (action: 'start' | 'stop' | 'reset') => post<{ ok: boolean }>(`/api/demo/${action}`),
  today: () => get<{ brief: Brief | null; calendar_today: CalEvent[]; built_iso: string; sources: System[]; coverage: Coverage; meetings_status: Record<string, number> }>('/api/today'),
  commitments: () => get<Task[]>('/api/commitments'),
  initiatives: () => get<Initiative[]>('/api/initiatives'),
  portfolio: () => get<IniSummary[]>('/api/initiatives'),
  initiative: (slug: string) => get<IniDetail>(`/api/initiatives/${encodeURIComponent(slug)}`),
  iniJob: (id: string) => get<IniJob>(`/api/initiatives/jobs/${id}`),
  topics: (initiative?: number) => get<TopicList>(`/api/topics${initiative ? `?initiative=${initiative}` : ''}`),
  topicsRefresh: (auto = false) => post<{ started: boolean }>(`/api/topics/refresh${auto ? '?auto=1' : ''}`),
  topicAction: (id: number, action: 'dismiss' | 'restore' | 'task' | 'pin' | 'unpin') => post<{ ok?: boolean; task?: number }>(`/api/topics/${id}/${action}`),
  iniDraft: (slug: string) => post<{ job: string }>(`/api/initiatives/${encodeURIComponent(slug)}/update`),
  iniVerdict: (slug: string, ref_type: string, ref_id: number, verdict: 'confirmed' | 'rejected' | null) => post<{ ok: boolean }>(`/api/initiatives/${encodeURIComponent(slug)}/links`, { ref_type, ref_id, verdict }),
  // the work an initiative's or a topic's page does (assist/initiative_work.py): `base` is workBase(...) below
  workRead: (base: string, ref_type: string, ref_id: number) => get<IniRead>(`${base}/read/${ref_type}/${ref_id}`),
  // a decision taken in a conversation started from the page (the chat's decide card)
  workDecideRecord: (base: string, b: { question: string; choice: string; note: string; task_id: number | null; decided: boolean; refs?: Record<string, { label: string; url: string }> }) =>
    send<{ task_id: number; step_id: number }>('POST', `${base}/decide/record`, b),
  // every button on the page is a conversation in Ask SleePO: intent email | document | decide ('' = Ask in chat); prompt is
  // its first question, which the app sends at once
  workChat: (base: string, focus: string[], intent = '') => send<{ thread: string; hint: string }>('POST', `${base}/chat`, { focus, intent }),
  topic: (id: number) => get<TopicPage>(`/api/topics/${id}`),
  linksReview: (n = 20) => get<{ sample: LinkSample[]; quality: LinkQuality; history: { at: string; precision: number | null; recall: number | null }[] }>(`/api/links/review?n=${n}`),
  itemLinks: (id: number) => get<ItemLink[]>(`/api/items/${id}/links`),
  linkVerdictAny: (ref_id: number, entity_type: string, entity_id: number, verdict: 'confirmed' | 'rejected' | null) => post<{ ok: boolean }>('/api/links', { ref_type: 'item', ref_id, entity_type, entity_id, verdict }),
  linkVerdict: (ref_id: number, entity_type: 'person' | 'org' | 'initiative', entity_id: number, verdict: 'confirmed' | 'rejected' | null) =>
    post<{ ok: boolean }>('/api/links', { ref_type: 'item', ref_id, entity_type, entity_id, verdict }),
  people: () => get<Person[]>('/api/people'),
  person: (id: string) => get<Person>(`/api/people/${encodeURIComponent(id)}`),
  personPage: (id: string) => get<PersonPageData>(`/api/people/${encodeURIComponent(id)}/page`),
  // where things stand with them (assist/person_summary.py): poll the GET while running
  personSummary: (id: string) => get<PersonSummaryState>(`/api/people/${encodeURIComponent(id)}/summary`),
  personSummaryStart: (id: string) => post<{ job: string }>(`/api/people/${encodeURIComponent(id)}/summary`),
  meetingPeople: (id: string) => get<MeetingPerson[]>(`/api/meetings/${encodeURIComponent(id)}/people`),
  meetingPeopleDecide: async (id: string, b: { key?: string; status?: string; who?: string }) => { const r = await fetch(`/api/meetings/${encodeURIComponent(id)}/people`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() as Promise<MeetingPerson[]> },
  agentRun: async (key: string) => { const r = await fetch(`/api/agents/${key}/run`, { method: 'POST' }); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() },
  agentLog: (key: string) => get<AgentLogTail>(`/api/agents/${key}/log`),
  actionProfile: (days = 30) => get<ActionProfile>(`/api/action-profile?days=${days}`),
  strategy: () => get<{ memos: StrategyMemo[] }>('/api/strategy'),
  strategyMark: async (id: number, index: number, mark: string) => { const r = await fetch(`/api/strategy/${id}/mark`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ index, mark }) }); if (!r.ok) throw new Error(r.statusText); return r.json() },
  roadmap: () => get<{ meta: { url: string; file: string; owner: string; modified: string | null; imported: string; count: number } | null; items: RoadmapItem[] }>('/api/roadmap'),
  // Roadmap › Refresh: reads Rowan's workbook again in the background (a minute or two); poll the state until it ends
  roadmapRefresh: () => post<RoadmapRefresh>('/api/roadmap/refresh'),
  code: () => get<CodeOverview>('/api/code'),
  codeSearch: (q: string, repo?: string, path?: string) => get<CodeSearch>(`/api/code/search?q=${encodeURIComponent(q)}${repo ? `&repo=${encodeURIComponent(repo)}` : ''}${path ? `&path=${encodeURIComponent(path)}` : ''}`),
  codeFile: (repo: string, path: string, start = 1, end?: number) => get<CodeFile>(`/api/code/file?repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}&start=${start}${end ? `&end=${end}` : ''}`),
  codeUpdate: (repo?: string) => post<CodeOverview['fetch']>('/api/code/update', { repo: repo ?? null }),
  codeRepos: (b: { add?: string; hide?: string; show?: string }) => post<CodeOverview>('/api/code/repos', b),
  roadmapRefreshState: () => get<RoadmapRefresh>('/api/roadmap/refresh'),
  loops: () => get<{ items: Loop[]; reviewed_at: string | null }>('/api/loops'),
  loopDistinct: async (id: number) => { const r = await fetch(`/api/loops/${id}/distinct`, { method: 'POST' }); if (!r.ok) throw new Error(await r.text()); return r.json() },
  loopSet: async (id: number, status: string, snooze_until?: string) => { const r = await fetch(`/api/loops/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, snooze_until }) }); if (!r.ok) throw new Error(await r.text()); return r.json() },
  entity: (type: string, id: number, days?: number) => get<EntityView>(`/api/entities/${type}/${id}${days ? `?days=${days}` : ''}`),
  orgs: () => get<{ id: number; name: string; kind: string; n: number; last: string }[]>('/api/orgs'),
  pipeline: () => get<{ opportunities: PipelineRow[]; fx: Record<string, number>; pulled: string | null; today: string }>('/api/pipeline'),
  pipelineClosed: () => get<{ deals: ClosedDeal[]; since: string; pulled: string | null; today: string; fx: Record<string, number> }>('/api/pipeline/closed'),
  retention: () => get<Retention>('/api/retention'),
  feedback: (b: { target_type: string; target_id: string; rating?: 1 | -1; copied?: boolean; edit_ratio?: number; note?: string }) =>
    fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).catch(() => undefined),
  llmCosts: (days = 7) => get<{ days: number; by_purpose: { purpose: string; model: string | null; calls: number; ok: number; cost_usd: number | null; avg_secs: number | null; in_tokens: number | null; out_tokens: number | null }[] }>(`/api/llm/costs?days=${days}`),
  agents: () => get<AgentsSnap>('/api/agents'),
  tasks: () => get<TasksData>('/api/tasks'),
  taskHistory: () => get<TaskHistory>('/api/tasks/history'),
  taskHistoryEval: () => get<HistoryEval>('/api/tasks/history/eval'),
  taskHistoryBuild: (redo = false) => post<TaskHistory['job']>('/api/tasks/history/build', { redo }),
  taskHistoryEdit: (id: number, b: { title?: string; done_when?: string; initiative?: string | null; area?: string | null; status?: 'done' | 'removed' }) =>
    send<{ ok: boolean }>('PATCH', `/api/tasks/history/${id}`, b),
  taskHistoryMerge: (id: number, into: number) => post<{ ok: boolean }>(`/api/tasks/history/${id}/merge`, { into }),
  taskHistorySplit: (stepId: number, title?: string) => post<{ id: number }>(`/api/tasks/history/steps/${stepId}/split`, { title }),
  taskHistoryMove: (ref: string, step_id: number | null) => post<{ ok: boolean }>('/api/tasks/history/actions/move', { ref, step_id }),
  taskCreate: (body: Record<string, unknown>) => send<{ id: number }>('POST', '/api/tasks', body),
  taskPatch: (id: number, body: Record<string, unknown>) => send<{ ok: boolean }>('PATCH', `/api/tasks/${id}`, body),
  taskLog: (id: number, step: number | null, what: string) => send<{ ok: boolean }>('POST', `/api/tasks/${id}/log`, { step, what }),
  taskSources: (id: number) => get<ActionSource[]>(`/api/tasks/${id}/sources`),
  taskAct: (id: number, step: number, prompt?: string) => send<{ context_chars?: number; start_from?: string; sources?: string[]; workspace?: string }>('POST', `/api/tasks/${id}/act`, { step, prompt }),
  taskSuggest: () => send<{ started: boolean }>('POST', '/api/tasks/suggest', {}),
  taskDocuments: (id: number) => get<TaskDocs>(`/api/tasks/${id}/documents`),
  // a meeting's suggestions as proposed steps (assist/tasks.py propose_from_meeting / propose_from_brief)
  meetingSteps: (mid: string) => get<TaskNode[]>(`/api/meetings/${encodeURIComponent(mid)}/steps`),
  prepSteps: (event: string) => get<TaskNode[]>(`/api/prep/${encodeURIComponent(event)}/steps`),
  taskLinked: (id: number) => get<TaskLinked[]>(`/api/tasks/${id}/linked`),
  taskDocSet: (id: number, doc: string, op: 'pin' | 'unpin' | 'hide' | 'unhide') => send<{ ok: boolean }>('POST', `/api/tasks/${id}/documents`, { doc, op }),
  taskOutlook: (id: number, body: { step: number; to: string[]; cc: string[]; subject: string; body: string }) => send<{ id: string; web_link: string | null }>('POST', `/api/tasks/${id}/outlook`, body),
  taskPropose: (body: { mail?: number; meeting?: string; ask?: string }) => send<{ job: string }>('POST', '/api/tasks/propose', body),
  taskJob: (job: string) => get<TaskJob>(`/api/tasks/jobs/${job}`),
  // the task proposed in the background for an email waiting on Sam (assist/tasks.py preplan), or the task saved from it
  taskProposal: (mail: number) => get<MailTaskProposal>(`/api/mail/${mail}/task-proposal`),
  taskProposalDismiss: (mail: number) => send<{ ok: boolean }>('POST', `/api/mail/${mail}/task-proposal/dismiss`, {}),
  todo: () => get<TodoList>('/api/todo'),
  todoAct: async (id: string, step: number, prompt?: string) => {
    const r = await fetch(`/api/todo/${encodeURIComponent(id)}/act`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ step, prompt }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() as Promise<ActResult>
  },
  chat: () => get<Record<string, ChatFull>>('/api/chat'),
  // Ask SleePO (components/Chat.tsx). Asking returns at once with the answer's job; the answer runs on the server on its own
  // (assist/chat.py start) and the page fetches what it has said since event `after` (Sam, 25 Nov 2026: answers in parallel).
  chatStart: (b: { message: string; thread: string | null; page: { path: string; title: string; context?: { kind: string; ref: string } } | null }) =>
    post<{ thread: string; job: string }>('/api/chat', b),
  chatLive: (job: string, after: number) => get<ChatLive>(`/api/chat/live/${job}?after=${after}`),
  chatStopJob: (job: string) => post<{ stopped: boolean }>(`/api/chat/live/${job}/stop`),
  chatPageContext: (path: string) => get<{ context: PageCtx | null }>(`/api/chat/page-context?path=${encodeURIComponent(path)}`),
  chatContext: (kind: string, ref: string) => get<{ context: PageCtx | null }>(`/api/chat/context?kind=${encodeURIComponent(kind)}&ref=${encodeURIComponent(ref)}`),
  chatContextPreview: (kind: string, ref: string) => get<{ preview: ChipPreview | null }>(`/api/chat/context/preview?kind=${encodeURIComponent(kind)}&ref=${encodeURIComponent(ref)}`),
  chatThreads: <T,>() => get<T[]>('/api/chat/threads'),
  chatSuggestions: <T,>() => get<T>('/api/chat/suggestions'),
  loopsRecent: <T,>(closedDays: number) => get<T>(`/api/loops?closed_days=${closedDays}`),
  chatThread: <T,>(tid: string) => get<{ turns: T[]; drafts?: Record<string, ChatDraftSaved>; live?: string | null }>(`/api/chat/threads/${tid}`),   // live: the job answering in it now
  // an email the chat wrote, as Sam edits it (assist/chat.py save_draft), and as a draft in his Outlook (a new email)
  chatDraftSave: (tid: string, body: { key: string; mail: number | null; to: string; cc: string; subject: string; body: string; kind?: 'teams' | 'slack'; item?: number }) => post<ChatDraftSaved>(`/api/chat/threads/${tid}/drafts`, body),
  chatDraftOutlook: (tid: string, body: { key: string; to: string[]; cc: string[]; subject: string; body: string }) => post<{ id: string; web_link: string | null }>(`/api/chat/threads/${tid}/drafts/outlook`, body),
  chatDelete: (tid: string) => send<{ ok: boolean }>('DELETE', `/api/chat/threads/${tid}`, undefined),
  chatStop: (run: string) => post<{ ok: boolean }>(`/api/chat/stop/${run}`),
  chatHandoff: (tid: string, ask: string) => post<{ files: string[] }>(`/api/chat/threads/${tid}/handoff`, { ask }),
  chatFileOpen: (tid: string, name: string, reveal: boolean) => post<{ ok: boolean }>(`/api/chat/threads/${tid}/files/open`, { name, reveal }),
  // steps on the Mac the chat asked to do, each allowed first (assist/desktop.py, components/ChatDesktop.tsx)
  chatDesktop: (tid: string) => get<{ requests: DesktopReq[] }>(`/api/chat/threads/${tid}/desktop`),
  chatDesktopDecide: (id: string, approve: boolean, steps?: number[]) => post<DesktopReq>(`/api/chat/desktop/${id}/decide`, { approve, steps }),
  chatDesktopShow: (id: string, step: number, n = 0) => post<{ ok: boolean }>(`/api/chat/desktop/${id}/show`, { step, n }),
  // a change the chat proposed, applied on Sam's click: an open item, an action, or a refresh
  loopPatch: (id: number, b: { status: string; snooze_until: string | null; note: string | null }) => send<unknown>('PATCH', `/api/loops/${id}`, b),
  todoPatch: (id: string, b: { status: string; snooze_until: string | null }) => send<unknown>('PATCH', `/api/todo/${encodeURIComponent(id)}`, b),
  runRefresh: async (mode: 'mail' | 'sync' | 'full') => {
    const r = await fetch(mode === 'mail' ? '/api/refresh-mail' : `/refresh?mode=${mode}`, { method: 'POST' })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? (r.status === 409 ? 'a refresh is already running' : r.statusText))
    return r.json() as Promise<unknown>
  },
  items: (source: 'teams' | 'slack') => get<MsgItem[]>(`/api/items?source=${source}&limit=5000`),
  mail: (folder: 'inbox' | 'sent') => get<MailItem[]>(`/api/mail?folder=${folder}`),
  mailOne: (id: number) => get<MailFull>(`/api/mail/${id}`),
  mailConversation: (id: number) => get<{ messages: ThreadMsg[] }>(`/api/mail/${id}/conversation`),
  documents: () => get<DocItem[]>('/api/documents'),
  documentFolder: async (id: string, initiatives: string[]) => { const r = await fetch(`/api/documents/${id}/folder`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ initiatives }) }); if (!r.ok) throw new Error(await r.text()); return r.json() },
  documentCard: (id: string) => get<{ card: { doc_id: string; title: string; kind: string; summary: string; facts: string[]; decisions: string[]; people: string[]; orgs: string[]
    initiatives: { slug: string; c: number; why: string }[]; doc_date: string | null; is_current: number | null; versions: number | null; sensitivity: string; other_versions?: string[] } | null; office_embed: string | null }>(`/api/documents/${encodeURIComponent(id)}/card`),
  prep: () => get<PrepItem[]>('/api/prep'),
  // page layouts Sam arranges (the Today widgets), kept in the settings table so every browser shows the same page
  uiGet: <T,>(key: string) => get<{ value: T | null }>(`/api/ui/${key}`),
  uiPut: async (key: string, value: unknown) => { const r = await fetch(`/api/ui/${key}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) }); if (!r.ok) throw new Error(`${r.status} saving the layout`) },
  prepWindow: (days: number) => get<PrepItem[]>(`/api/prep?days=${days}`),
  prepBrief: (eventId: string) => get<{ brief: PrepItem['brief'] }>(`/api/prep/${encodeURIComponent(eventId)}`),
  followup: (mid: string) => get<FollowupStatus>(`/api/meetings/${encodeURIComponent(mid)}/followup`),
  followups: () => get<FollowupList>('/api/followups'),
  followupRun: async (mid: string, notes = '') => { const r = await fetch(`/api/meetings/${encodeURIComponent(mid)}/followup`, notes ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ notes }) } : { method: 'POST' }); if (!r.ok) throw new Error(await r.text()); return r.json() as Promise<{ started: boolean }> },
  prepRun: async (eventId: string, notes = '') => { const r = await fetch(`/api/prep/${encodeURIComponent(eventId)}`, notes ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ notes }) } : { method: 'POST' }); if (!r.ok) throw new Error(await r.text()); return r.json() as Promise<{ started: boolean }> },
  transcript: (id: string) => get<Transcript>(`/api/meetings/${encodeURIComponent(id)}/transcript`),
  meetingShots: (id: string) => get<{ shots: Shot[] }>(`/api/meetings/${encodeURIComponent(id)}/shots`),
  claudeOpen: async (body: { prompt: string; app: 'cowork' | 'chat'; doc?: string; label?: string }) => {
    const r = await fetch('/api/claude/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    if (!r.ok) throw new Error(await r.text()); return r.json() as Promise<{ ok: boolean; attached: string | null; workspace: string | null }>
  },
  replyInbox: () => get<InboxItem[]>('/api/replies/inbox'),
  // Sam's own call: add an email to Needs reply or remove it (loops.mark_reply); it wins over the rule everywhere
  // save the draft into Outlook, in the email's own thread, and get its link (assist/outlook_drafts.py; never sends)
  replyOutlook: (id: number, body: string, mode: string, add: string[]) => post<{ web_link: string | null; updated: boolean }>(`/api/replies/${id}/outlook`, { body, mode, add }),
  mailOutlookLink: (id: number) => get<{ web_link: string }>(`/api/mail/${id}/outlook-link`),
  // the tasks an email's thread, a message or meeting notes belong to (assist/task_links.py), and Sam linking or unlinking one
  itemTasks: (id: number) => get<{ linked: ItemTask[]; open: { id: number; title: string; status: string; area: string | null; initiative: string | null }[] }>(`/api/items/${id}/tasks`),
  itemTaskLink: (id: number, task_id: number, on: boolean) => post<{ ok: boolean; linked: ItemTask[] }>(`/api/items/${id}/tasks`, { task_id, on }),
  replyNeeds: (id: number, needs: boolean) => post<{ ok: boolean; loop: number }>(`/api/replies/${id}/needs`, { needs }),
  // mail only, from Apple Mail on this Mac (seconds): the Inbox page's refresh button
  // Meetings › Refresh runs in the background on the server (assist/calrefresh.py, 23 Oct 2026), so a server restart cannot
  // cut it off: start it (or join the run already going) and follow it until it ends; a check that fails while the server
  // restarts is retried
  calendarRefreshState: () => get<CalRefreshState>('/api/refresh-calendar'),
  calendarRefresh: async () => {
    let st = await post<CalRefreshState>('/api/refresh-calendar')
    const t0 = Date.now()
    let fails = 0
    while (st.running && Date.now() - t0 < 5 * 60_000) {
      await new Promise((r) => setTimeout(r, 2000))
      try { st = await get<CalRefreshState>('/api/refresh-calendar'); fails = 0 } catch (e) { if (++fails > 5) throw e }
    }
    if (st.running) throw new Error('The refresh is taking too long. It carries on in the background.')
    if (!st.ok) throw new Error(st.error || 'The refresh failed.')
    return st
  },
  mailRefreshStatus: () => get<{ running: boolean; last: string | null }>('/api/refresh-mail'),
  // Teams and Slack pulled now (the Messages page's Refresh): a connector run in the background, minutes; poll the status
  messagesRefresh: () => post<MsgRefresh>('/api/refresh-messages'),
  messagesRefreshStatus: () => get<MsgRefresh>('/api/refresh-messages'),
  mailRefresh: async () => { const r = await fetch('/api/refresh-mail', { method: 'POST' }); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() as Promise<{ ok: boolean; secs: number; new: { inbox?: number; sent?: number }; last: string | null; mail_running: boolean; loops_ok: boolean; read?: number; unread?: number }> },
  // current: the draft on screen, to revise with the instructions as feedback (assist/replies.py REVISE) instead of writing anew
  // current: the draft on screen, to revise; base: the last text SleePO wrote (the rest is Sam's own wording); history: his earlier asks
  replyGenerate: async (item_id: number, instructions: string, mode: 'reply' | 'replyall' | 'forward' | 'followup' = 'reply', add: string[] = [], length = 3, current = '', base = '', history: string[] = []) => {
    const r = await fetch('/api/replies/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_id, instructions, mode, add, length, current, base, history }) })
    if (!r.ok) throw new Error(await r.text()); return (await r.json()) as { job: string }
  },
  replyAttachments: (id: number) => get<ReplyAttachment[]>(`/api/replies/${id}/attachments`),
  // a file Sam adds to an email (a linked document SleePO cannot open): its text is read like an attachment's
  mailAddFile: async (item_id: number, name: string, data: string) => {
    const r = await fetch(`/api/mail/${item_id}/files`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, data }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { ok: boolean; id: number }
  },
  mailRemoveFile: async (item_id: number, att: number) => {
    const r = await fetch(`/api/mail/${item_id}/files/${att}`, { method: 'DELETE' })
    if (!r.ok) throw new Error(r.statusText); return (await r.json()) as { ok: boolean }
  },
  // continue a draft in Ask SleePO (assist/replies.py to_chat): returns the conversation to open
  replyChat: async (item_id: number, b: { body: string; notes: string; ask: string; mode: string; length: number }) => {
    const r = await fetch(`/api/replies/${item_id}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { thread: string }
  },
  replyJob: (job: string) => get<ReplyJob>(`/api/replies/jobs/${job}`),
  // Inbox › Drafts (assist/new_mail.py)
  drafts: () => get<DraftsData>('/api/drafts'),
  actions: () => get<ActionsData>('/api/actions'),   // the Actions page (assist/actions_view.py)
  draftNew: (b: { to?: string[]; cc?: string[]; subject?: string; body?: string; ask?: string }) => send<SleepoDraft>('POST', '/api/drafts', b),
  draftEdit: (id: number, b: { to?: string[]; cc?: string[]; subject?: string; body?: string; ask?: string; status?: 'draft' | 'discarded' }) => send<SleepoDraft>('PATCH', `/api/drafts/${id}`, b),
  draftWrite: (id: number, b: { ask: string; length?: number; fresh?: boolean; base?: string; history?: string[] }) => send<{ job: string }>('POST', `/api/drafts/${id}/write`, b),
  draftWriteStep: (stepId: number, index: number, b: { ask: string; length?: number; fresh?: boolean; base?: string; history?: string[] }) => send<{ job: string }>('POST', `/api/drafts/step/${stepId}/${index}/write`, b),
  draftJob: (job: string) => get<DraftJob>(`/api/drafts/jobs/${job}`),
  draftOutlook: (id: number) => send<{ id: string; web_link: string | null }>('POST', `/api/drafts/${id}/outlook`, {}),
  draftChat: (b: { to: string[]; cc: string[]; subject: string; body: string; notes?: string; ask?: string; draft?: number }) => send<{ thread: string }>('POST', '/api/drafts/chat', b),
  draftFromOutlook: (key: string) => send<{ item_id?: number; draft?: number }>('POST', `/api/drafts/from-outlook/${encodeURIComponent(key)}`, {}),
  draftsSuggest: () => send<{ started: boolean }>('POST', '/api/drafts/suggest', {}),
  draftsExclude: (step: number, index: number, undo = false) => send<{ ok: boolean }>('POST', `/api/drafts/step/${step}/${index}/exclude`, { undo }),
  draftResolve: (names: string[]) => send<{ addresses: string[]; unknown: string[] }>('POST', '/api/drafts/resolve', { names }),
  // People › Companies (assist/companies.py)
  companies: () => get<{ companies: CompanyRow[]; labels: Record<string, string> }>('/api/companies'),
  company: (id: number) => get<CompanyPage>(`/api/companies/${id}`),
  companySearch: (q: string) => get<{ id: number; name: string; kind: string | null; company: string }[]>(`/api/companies/search?q=${encodeURIComponent(q)}`),
  companyRelation: async (id: number, relation: string | null) => {
    const r = await fetch(`/api/companies/${id}/relation`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ relation }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() as Promise<{ ok: boolean }>
  },
  companyName: async (id: number, name: string) => {
    const r = await fetch(`/api/companies/${id}/name`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() as Promise<{ ok: boolean }>
  },
  companyMerge: async (id: number, into: number | null) => {
    const r = await fetch(`/api/companies/${id}/merge`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ into }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() as Promise<{ ok: boolean }>
  },
  // dictation with FluidVoice (assist/dictation.py): the server presses its shortcut once, to start or stop
  dictate: async () => {
    const r = await fetch('/api/dictate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText)
    return (await r.json()) as { ok: boolean; need?: 'accessibility' | 'install'; message?: string; shortcut: string }
  },
  // the blanks in a draft as questions, then filled from Sam's answers (assist/fill_in.py); poll both with fillJob
  fillQuestions: async (b: { kind: 'email' | 'chat'; draft: string; item_id?: number; ids?: number[]; app?: 'teams' | 'slack'; ask?: string; tid?: string | null }) => {
    const r = await fetch('/api/fill/questions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { job: string }
  },
  fillAnswers: async (b: { kind: 'email' | 'chat'; draft: string; app?: 'teams' | 'slack'; answers: { question: string; fills: string[]; answer: string[] }[] }) => {
    const r = await fetch('/api/fill/answers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { job: string }
  },
  fillJob: (job: string) => get<FillJob>(`/api/replies/jobs/${job}`),
  // write only the selected part of a draft again (assist/rewrite_part.py); poll with rewriteJob
  rewritePart: async (b: RewriteCtx & { draft: string; start: number; end: number; ask: string }) => {
    const r = await fetch('/api/rewrite-part', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { job: string }
  },
  rewriteJob: (job: string) => get<ReplyJob & { part: string }>(`/api/replies/jobs/${job}`),
  // a call in progress (assist/live_call.py): the Granola transcript so far, polled; a question about it is a job
  live: (event?: string, note?: string) => get<LiveState>(`/api/live?${new URLSearchParams({ ...(event ? { event } : {}), ...(note ? { note } : {}) })}`),
  liveAsk: (b: { question: string; note: string; event?: string; history: { q: string; a: string }[] }) => post<{ job: string }>('/api/live/ask', b),
  liveNow: () => get<{ note: LiveNote | null; event: string | null }>('/api/live/now'),
  liveJob: (job: string) => get<ReplyJob & { answer: string }>(`/api/replies/jobs/${job}`),
  // a Teams or Slack reply in Sam's chat voice (assist/chat_reply.py), from the conversation the Messages page shows; poll with replyJob
  messagesDraft: async (b: { ids: number[]; app: 'teams' | 'slack'; person?: string; instructions: string; length: number }) => {
    const r = await fetch('/api/messages/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { job: string }
  },
  // the recommended reply SleePO wrote in the background for an email waiting on Sam (assist/replies.py predraft)
  replyPredraft: (id: number) => get<{ predraft: Predraft | null }>(`/api/replies/${id}/predraft`),
  // the reply Sam is working on for an email, kept across leaving it (assist/reply_working.py): Use in reply, or his edits
  replyWorking: (id: number) => get<{ working: { body: string; mode: string | null; source: 'chat' | 'edit'; updated_at: string } | null }>(`/api/replies/${id}/working`),
  replyWorkingPut: async (id: number, w: { body: string; mode?: string | null; source: 'chat' | 'edit' }) => {
    const r = await fetch(`/api/replies/${id}/working`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(w) })
    if (!r.ok) throw new Error(await r.text()); return r.json() as Promise<{ ok: boolean }> },
  // a deck, document or workbook that answers an email: SleePO plans it, Claude Cowork builds it (assist/deliverables.py)
  deliverablePlan: async (item_id: number, ask: string, format: string | null) => {
    const r = await fetch(`/api/mail/${item_id}/deliverable/plan`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ask, format }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { job: string }
  },
  deliverableJob: (job: string) => get<DeliverableJob>(`/api/deliverables/jobs/${job}`),
  deliverableOpen: async (item_id: number, plan: DeliverablePlan) => {
    const r = await fetch(`/api/mail/${item_id}/deliverable/open`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plan) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json() as Promise<ActResult>
  },
  deliverableChat: async (item_id: number, plan: DeliverablePlan & { ask: string }) => {
    const r = await fetch(`/api/mail/${item_id}/deliverable/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plan) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { thread: string }
  },
  // reviewing a file shared in Teams (assist/file_review.py); nothing is sent
  review: (att: number) => get<ReviewState>(`/api/reviews/${att}`),
  reviewStart: (att: number, ask: string) => send<{ job: string }>('POST', `/api/reviews/${att}`, { ask }),
  reviewJob: (job: string) => get<ReviewJob>(`/api/reviews/jobs/${job}`),
  reviewDecide: (att: number, b: { decisions?: Record<string, boolean>; replace?: Record<string, string> }) => send<ReviewRecord>('PATCH', `/api/reviews/${att}`, b),
  reviewFile: (att: number, name: string, data: string) => send<{ ok: boolean }>('POST', `/api/reviews/${att}/file`, { name, data }),
  reviewMake: (att: number) => send<NonNullable<ReviewRecord['output']>>('POST', `/api/reviews/${att}/make`, {}),
  reviewOpen: (att: number, reveal = false) => send<{ ok: boolean }>('POST', `/api/reviews/${att}/open?reveal=${reveal ? 1 : 0}`, {}),
  reviewReply: (att: number) => get<{ instructions: string }>(`/api/reviews/${att}/reply`),
  reviewChat: (att: number) => send<{ thread: string; job: string | null; new: boolean }>('POST', `/api/reviews/${att}/chat`, {}),   // its Ask SleePO conversation
  reviewEdits: (att: number, edits: { where?: string; what?: string; find: string; replace: string }[]) => send<{ ids: string[] }>('POST', `/api/reviews/${att}/edits`, { edits }),
  messageLink: (item: number) => get<{ app: 'teams' | 'slack'; link: string | null; conversation: string | null; author: string | null }>(`/api/messages/${item}/link`),
  // a Teams or Slack message opened in Ask SleePO (assist/message_chat.py): its conversation, and the message card's data
  messageChat: (item: number) => send<{ thread: string; new: boolean }>('POST', `/api/messages/${item}/chat`, {}),
  message: (item: number) => get<MessageCard>(`/api/messages/${item}`),
  // the latest conversations Sam reads, each with its newest message in a line (Today's Messages widget; assist/chatsync.py latest)
  messagesRecent: () => get<{ conversations: RecentConv[] }>('/api/messages/recent'),
  // a briefing on the situation around an email, and the chat that continues from it (assist/briefing.py)
  briefing: (item_id: number) => get<{ briefing: BriefingRecord | null }>(`/api/mail/${item_id}/briefing`),
  briefingStart: async (item_id: number, ask: string) => {
    const r = await fetch(`/api/mail/${item_id}/briefing`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ask }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { job: string }
  },
  briefingJob: (job: string) => get<BriefingJob>(`/api/briefings/jobs/${job}`),
  briefingChat: async (item_id: number) => {
    const r = await fetch(`/api/mail/${item_id}/briefing/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return (await r.json()) as { thread: string; new: boolean }
  },
  search: (q: string, limit = 60) => get<SearchResult>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  suggest: (q: string) => get<{ query: string; results: SearchHit[]; total: number }>(`/api/search/suggest?q=${encodeURIComponent(q)}`),
  graph: () => get<{ nodes: GNode[]; edges: GEdge[]; me?: string; unlinked?: Partial<Record<GNode['type'], number>> }>('/api/graph'),
  calendar: () => get<{ events: CalEvent[]; pulled: string; stats: Record<string, number> & { unrecorded_skipped?: Record<string, number> } }>('/api/calendar'),
  meetings: () => get<Meeting[]>('/api/meetings'),
  sources: () => get<{ systems: System[]; coverage: Coverage; sync: { digested: number; last_run: string | null; log: string }; stream_counts: Record<string, number>; gaps: SourceGap[]; pulls: Record<string, SourcePulls> }>('/api/sources'),
  stream: (sid: string) => get<StreamTable[]>(`/api/streams/${encodeURIComponent(sid)}`),
  docs: () => get<Doc[]>('/api/docs'),
  souls: () => get<Souls>('/api/souls'),
  doc: (id: string) => get<Doc>(`/api/docs/${encodeURI(id)}`),
  setCommitment: async (id: string, status: 'open' | 'done' | 'dropped') => {
    const r = await fetch(`/api/commitments/${id.replace(/^t-/, '')}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) })
    if (!r.ok) throw new Error('update failed')
    return r.json()
  },
  refresh: async (mode: 'sync' | 'full') => (await fetch(`/refresh?mode=${mode}`, { method: 'POST' })).json(),
  status: () => get<RefreshStatus>('/status'),
  connections: () => get<Connections>('/api/connections'),
  connectionsCheck: () => post<Connections>('/api/connections/check'),
  connectionsOpen: (what: string) => post<{ ok: boolean }>('/api/connections/open', { what }),
  connectionsLogin: (key: string) => post<ConnLogin>('/api/connections/login', { key }),
  graphChanges: (kind: GraphKind, id: number) => get<GraphChanges>(`/api/graph-memory/changes/${kind}/${id}`),
}
