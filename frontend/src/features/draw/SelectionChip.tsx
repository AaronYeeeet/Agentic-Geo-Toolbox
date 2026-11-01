import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatArea } from '@/lib/format'
import { useSelectionStore } from '@/store/selectionStore'

/**
 * The active selection as a context chip. Same magenta dashed outline as the selection on the map, so the link
 * between the drawn area and the question is visible.
 */
export function SelectionChip() {
  const { t, i18n } = useTranslation()
  const selection = useSelectionStore((s) => s.selection)
  const clear = useSelectionStore((s) => s.clearSelection)
  if (!selection) return null

  const { kind, area_m2: area, label } = selection.properties
  const detail = area > 0 ? formatArea(area, i18n.language === 'de' ? 'de' : 'en') : (label ?? '')
  const kindLabel = t(`draw.kind.${kind}`)
  const text = detail ? t('chat.selection', { kind: kindLabel, area: detail }) : kindLabel

  return (
    <span
      className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-md border-[1.5px] border-dashed border-overprint bg-overprint-wash pr-1 pl-2 text-[12.5px] font-medium text-ink"
      data-testid="selection-chip"
    >
      <span aria-hidden className="size-2 shrink-0 rounded-[2px] bg-overprint" />
      <span className="truncate tabular-nums">{text}</span>
      <button
        type="button"
        aria-label={t('chat.removeContext', { name: text })}
        onClick={clear}
        className="grid size-5 shrink-0 place-items-center rounded text-ink-3 hover:bg-white/70 hover:text-ink"
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </span>
  )
}
