// Dictate with FluidVoice (Sam, 22 Oct 2026): a microphone in every box where Sam talks to the AI. FluidVoice has no link or
// script to start it, only its shortcut (Fn), and a page cannot press keys outside the browser; so a click focuses the box and
// asks the SleePO server on this Mac to press the shortcut once (assist/dictation.py). FluidVoice records and pastes what he
// says into the box; a second click (or Fn) stops it. The first time, macOS asks to allow SleePO under Accessibility.
// Without a target, the button dictates into the text box of the nearest element marked data-dictate.
import { useEffect, useRef, useState, type RefObject } from 'react'
import { Mic } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/util'

type Field = HTMLTextAreaElement | HTMLInputElement
export function DictateButton({ target, className, size = 15 }: { target?: RefObject<Field | null>; className?: string; size?: number }) {
  const me = useRef<HTMLButtonElement>(null)
  const [on, setOn] = useState(false)
  const [note, setNote] = useState('')
  const field = (): Field | null => target?.current ?? (me.current?.closest('[data-dictate]')?.querySelector('textarea, input') as Field | null) ?? null
  useEffect(() => {   // what FluidVoice pastes into the box means it has finished
    if (!on) return
    const f = field(), start = f?.value ?? ''
    const check = () => { if ((field()?.value ?? '') !== start) setOn(false) }
    f?.addEventListener('input', check)
    const t = setInterval(check, 800), stop = setTimeout(() => setOn(false), 120_000)
    return () => { f?.removeEventListener('input', check); clearInterval(t); clearTimeout(stop) }
  }, [on]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!note) return; const t = setTimeout(() => setNote(''), 12_000); return () => clearTimeout(t) }, [note])
  const click = async () => {
    const f = field()
    if (f) { f.focus(); const n = f.value.length; try { f.setSelectionRange(n, n) } catch { /* some inputs have no caret */ } }
    try {
      const r = await api.dictate()
      if (r.ok) { setOn(!on); setNote('') } else setNote(r.message || 'FluidVoice could not be started.')
    } catch (e) { setNote(e instanceof Error ? e.message : String(e)) }
    field()?.focus()   // FluidVoice pastes into whatever has focus: the box
  }
  return (
    <span className="relative inline-flex shrink-0">
      <button ref={me} type="button" onMouseDown={(e) => e.preventDefault()} onClick={click} aria-pressed={on}
        aria-label={on ? 'Stop dictating' : 'Dictate with FluidVoice'} title={on ? 'Listening: click again (or press Fn) to stop' : 'Dictate with FluidVoice (Fn)'}
        className={cn('relative grid size-7 place-items-center rounded-full transition-colors', on ? 'bg-hot text-white' : 'text-ink2 hover:bg-panel2 hover:text-ink', className)}>
        {on && <span aria-hidden className="absolute inset-0 animate-ping rounded-full bg-hot/40" />}
        <Mic size={size} aria-hidden className="relative" />
      </button>
      {note && <span role="status" className="absolute bottom-full right-0 z-40 mb-1.5 w-72 rounded-lg border border-line bg-panel p-2.5 text-left text-[12px] leading-snug text-ink shadow-lg">{note}</span>}
    </span>
  )
}
