// The user's profile (16 Nov 2026, DESIGN-PERSONALISATION.md): who "me" is, their names, time zone and sign-off, from
// /api/meta (assist/profile.py on the server). Nothing in the app names a person; every "is this me?" check is here.
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type Profile = {
  full_name: string; first_name: string; emails: string[]; aliases: string[]; names: string[]; speaker_label: string
  role: string; role_short: string; pronouns: string; timezone: string; locale: string; signoff: string; spelling: string
  second_timezone: string; second_timezone_label: string; manager: string; meeting_days: string; meeting_hours: string
  plan_file: string; plan_title: string; role_soul_file: string; manager_pronouns: string
}
export type Org = { name: string; domains: string[]; crm_regions: string[]; roadmap_owner: string }

const EMPTY: Profile = {
  full_name: '', first_name: '', emails: [], aliases: [], names: [], speaker_label: '', role: '', role_short: '', pronouns: '',
  timezone: '', locale: 'en-GB', signoff: '', spelling: 'British', second_timezone: '', second_timezone_label: '', manager: '',
  meeting_days: '', meeting_hours: '', plan_file: '', plan_title: '', role_soul_file: '', manager_pronouns: '',
}
const NO_ORG: Org = { name: '', domains: [], crm_regions: [], roadmap_owner: '' }
let current: Profile = EMPTY
let currentOrg: Org = NO_ORG

/** Set at boot from /api/meta (main.tsx), so code outside components can ask too. */
export function setProfile(p?: Partial<Profile> | null, o?: Partial<Org> | null) {
  current = { ...EMPTY, ...(p ?? {}) }
  currentOrg = { ...NO_ORG, ...(o ?? {}) }
}
export const profile = () => current
export const org = () => currentOrg

/** The profile in a component (follows /api/meta when it changes). */
export function useProfile(): Profile {
  const q = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 60_000 })
  return q.data?.profile ? { ...EMPTY, ...q.data.profile } : current
}
export function useOrg(): Org {
  const q = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 60_000 })
  return q.data?.org ? { ...NO_ORG, ...q.data.org } : currentOrg
}

const locals = (p: Profile) => p.emails.map((e) => e.toLowerCase().split('@')[0]).filter(Boolean)
const fullNames = (p: Profile) => p.names.filter((n) => n.includes(' '))
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
// an address part as a word of its own: "milo" is not inside "alexander"
const hasLocal = (x: string, l: string) => new RegExp(`(^|[^\\w.+-])${esc(l)}(?![\\w-])`).test(x)

/** True when a name, speaker label or address is the user's: one of their names exactly, or their address in it. */
export function isMe(s?: string | null, p: Profile = current): boolean {
  const x = (s ?? '').trim().toLowerCase()
  if (!x) return false
  return p.names.includes(x) || locals(p).some((l) => hasLocal(x, l) && x.includes(`${l}@`))
}

/** True when the user's full name or address appears anywhere in s ("Sam Doe <sam.doe@…>", "From Sam Doe"). */
export function mentionsMe(s?: string | null, p: Profile = current): boolean {
  const x = (s ?? '').toLowerCase()
  return !!x && (fullNames(p).some((n) => x.includes(n)) || locals(p).some((l) => hasLocal(x, l)))
}

/** ", Sam" after a greeting, or nothing. */
export const hi = (p: Profile = current) => (p.first_name ? `, ${p.first_name}` : '')
/** The plan document's path under memory/ ("context/v2mom-2026-final.md") and its name. */
export const planDoc = (p: Profile = current): [string, string] => [(p.plan_file || 'memory/context/plan.md').replace(/^memory\//, ''), p.plan_title || 'Plan']
/** The user's name for an avatar or a label, never empty. */
export const myName = (p: Profile = current) => p.full_name || 'Me'
/** How the user signs an email ("-Sam"). */
export const signoff = (p: Profile = current) => p.signoff || (p.first_name ? `-${p.first_name}` : '')
