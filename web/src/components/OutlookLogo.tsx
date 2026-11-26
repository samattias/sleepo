// Outlook's own logo for the Open in Outlook buttons (Sam, 28 Oct 2026), from the app logos /api/meta serves
import { useQuery } from '@tanstack/react-query'
import { Mail } from 'lucide-react'
import { api } from '@/lib/api'

export function OutlookLogo({ size = 14 }: { size?: number }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 300_000 })
  const uri = meta.data?.logos?.outlook
  return uri ? <img src={uri} alt="" aria-hidden width={size} height={size} className="shrink-0" style={{ width: size, height: size }} /> : <Mail size={size} aria-hidden />
}
