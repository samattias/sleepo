// The Claude app's own icon (public/claude-desktop.png, taken from Claude.app), for anything that opens or continues in
// Claude Desktop, so those actions read as "Claude" at a glance rather than as SleePO's own assistant.
import { cn } from '@/lib/util'

export function ClaudeMark({ size = 14, className }: { size?: number; className?: string }) {
  return <img src="/claude-desktop.png" width={size} height={size} alt="" aria-hidden draggable={false} className={cn('shrink-0 select-none', className)} />
}
