// SleePO mark: a sleeping face on the volt square. Same drawing as public/favicon.svg.
// animate (Sam, 22 Oct 2026: a loading indicator that is "fun and playful"): the face breathes, the mouth snores and the Zs drift
// up and fade one after another, with a third little z. Keyframes in index.css (sleepo-*); still with reduced motion.
import { useEffect, useState } from 'react'

export function Logo({ size = 28, className, animate = false }: { size?: number; className?: string; animate?: boolean }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} className={[animate ? 'sleepo-anim' : '', className].filter(Boolean).join(' ') || undefined} aria-hidden>
      <g className="sl-face">
        <rect width="32" height="32" fill="var(--accent)" />
        <path d="M6.5 18.5q3.25 3.4 6.5 0M19 18.5q3.25 3.4 6.5 0" fill="none" stroke="#0a0a0a" strokeWidth="2.6" strokeLinecap="round" />
        <path className="sl-mouth" d="M13.5 24.5q2.5 1.6 5 0" fill="none" stroke="#0a0a0a" strokeWidth="2" strokeLinecap="round" />
      </g>
      <path className="sl-z1" d="M20.5 4.5h5.5l-5.5 6h5.5" fill="none" stroke="#0a0a0a" strokeWidth="2.2" strokeLinecap="square" />
      <path className="sl-z2" d="M15 6.5h3l-3 3.2h3" fill="none" stroke="#0a0a0a" strokeWidth="1.6" strokeLinecap="square" />
      {animate && <path className="sl-z3" d="M10.5 9h2l-2 2.2h2" fill="none" stroke="#0a0a0a" strokeWidth="1.2" strokeLinecap="square" />}
    </svg>
  )
}

const LINES = ['Waking up', 'Rubbing its eyes', 'Gathering everything', 'Nearly there']

// The app's loading state: the mark, animated, over a line that changes every couple of seconds (or a fixed label)
export function SleepyLoader({ label, size = 44, className }: { label?: string; size?: number; className?: string }) {
  const [i, setI] = useState(0)
  useEffect(() => { if (label) return; const t = setInterval(() => setI((x) => Math.min(x + 1, LINES.length - 1)), 2200); return () => clearInterval(t) }, [label])
  return (
    <div role="status" aria-live="polite" className={['flex flex-col items-center justify-center gap-3 py-10', className].filter(Boolean).join(' ')}>
      <Logo size={size} animate />
      <span className="text-[13px] text-ink2">{label ?? LINES[i]}…</span>
    </div>
  )
}
