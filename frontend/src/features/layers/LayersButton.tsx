import { Layers } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { useUiStore } from '@/store/uiStore'

/** Opens the layer panel (top-right). Shows the label from tablet width up, the icon alone on phones. */
export function LayersButton() {
  const { t } = useTranslation()
  const open = useUiStore((s) => s.layerPanelOpen)
  const setOpen = useUiStore((s) => s.setLayerPanelOpen)

  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={open ? t('layers.close') : t('layers.open')}
      onClick={() => setOpen(!open)}
      className={cn(
        'float-panel flex h-10 items-center gap-2 px-3 text-[13.5px] font-medium text-ink-2 transition-colors hover:text-ink',
        open && 'border-water/40 bg-water-wash text-water-ink hover:text-water-ink',
      )}
      data-testid="layers-button"
    >
      <Layers className="size-[18px]" aria-hidden />
      <span className="hidden sm:inline">{t('layers.title')}</span>
    </button>
  )
}
