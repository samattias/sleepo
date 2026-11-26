// Polls /api/agents: fast while anything runs, slow when idle. Shared by the sidebar spinners and the Agents page.
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useAgents() {
  return useQuery({ queryKey: ['agents'], queryFn: api.agents, refetchInterval: (q) => (q.state.data?.running.length ? 3000 : 15000), refetchIntervalInBackground: false })
}
