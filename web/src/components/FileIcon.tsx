// A file's own app icon (Sam, 30 Oct 2026: "where it says PPT, have the actual PowerPoint logo ... use iconography"): the
// PowerPoint, Word, Excel, Visio, PDF, HTML… mark, picked by the file's extension, else by the type Teams shares it as. The marks
// are files in assets/filetypes, bundled with the app (nothing is fetched): vscode-icons' file-type set (MIT, LICENSE there),
// and Visio's 2019 logo from Wikimedia Commons, which vscode-icons lacks, padded to the same 32-unit grid. A file of any other
// type gets the fallback (the plain document icon unless the caller passes its own).
import type { ReactNode } from 'react'
import { FileText } from 'lucide-react'
import { cn } from '@/lib/util'

const SVG = import.meta.glob<string>('../assets/filetypes/*.svg', { eager: true, query: '?url', import: 'default' })

const KINDS: [string, string, string[]][] = [
  ['powerpoint', 'PowerPoint', ['ppt', 'pptx', 'pptm', 'pot', 'potx', 'pps', 'ppsx']],
  ['word', 'Word', ['doc', 'docx', 'docm', 'dot', 'dotx', 'rtf']],
  ['excel', 'Excel', ['xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx']],
  ['visio', 'Visio', ['vsd', 'vsdx', 'vsdm', 'vss', 'vssx', 'vst', 'vstx']],
  ['pdf', 'PDF', ['pdf']],
  ['html', 'HTML', ['html', 'htm', 'mht', 'mhtml']],
  ['markdown', 'Markdown', ['md', 'markdown']],
  ['csv', 'CSV', ['csv', 'tsv']],
  ['text', 'Text', ['txt', 'log']],
  ['image', 'Image', ['png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'svg', 'bmp', 'tif', 'tiff']],
  ['video', 'Video', ['mp4', 'mov', 'm4v', 'webm', 'avi']],
  ['zip', 'Archive', ['zip', '7z', 'rar', 'gz', 'tgz']],
  ['outlook', 'Email', ['eml', 'msg']],
  ['onenote', 'OneNote', ['one']],
  ['json', 'JSON', ['json']],
  ['xml', 'XML', ['xml', 'bpmn']],
]
const BY_EXT = Object.fromEntries(KINDS.flatMap(([k, , exts]) => exts.map((e) => [e, k])))
const LABEL = Object.fromEntries(KINDS.map(([k, l]) => [k, l]))
const SHARE: Record<string, string> = { 'PowerPoint file': 'powerpoint', 'Word file': 'word', 'Excel file': 'excel', 'Visio file': 'visio', PDF: 'pdf' }

/** 'powerpoint' for "Q3 review.pptx" (or a Teams "PowerPoint file"); undefined for a type with no icon. */
const fileKind =(name: string, share?: string) => BY_EXT[name.match(/\.(\w{1,5})$/)?.[1]?.toLowerCase() ?? ''] ?? (share ? SHARE[share] : undefined)

/** size: as for the line icon it stands in for. The marks carry a little padding, so the image is drawn 2 px larger and pulled
 *  in a pixel each side: it takes the same room, and the text beside it lines up with the rows that keep a line icon. */
export function FileIcon({ name, share, size = 14, className, fallback }: { name: string; share?: string; size?: number; className?: string; fallback?: ReactNode }) {
  const k = fileKind(name, share)
  if (!k) return fallback ?? <FileText size={size} aria-hidden className={cn('shrink-0 text-ink3', className)} />
  const px = size + 2
  return <img src={SVG[`../assets/filetypes/${k}.svg`]} alt={LABEL[k]} width={px} height={px} draggable={false} className={cn('-m-px shrink-0', className)} style={{ width: px, height: px }} />
}
