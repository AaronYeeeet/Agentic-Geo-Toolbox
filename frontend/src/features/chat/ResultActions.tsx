import { Crosshair, Eye, EyeOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fitToBBox } from '@/map/camera'
import { useLayerStore } from '@/store/layerStore'

const button =
  'inline-flex items-center gap-1.5 rounded-md border border-rule bg-paper px-2.5 py-1 text-[12.5px] font-medium text-ink-2 transition-colors hover:border-water/40 hover:text-water-ink'

/** Result actions under an answer: zoom to the result layers and show or hide them. */
export function ResultActions({ layerIds }: { layerIds: string[] }) {
  const { t } = useTranslation()
  const overlays = useLayerStore((s) => s.overlays).filter((o) => layerIds.includes(o.id))
  const updateOverlay = useLayerStore((s) => s.updateOverlay)
  if (overlays.length === 0) return null

  const visible = overlays.every((o) => o.visible)
  const boxes = overlays.flatMap((o) => (o.bbox ? [o.bbox] : []))

  return (
    <div className="flex flex-wrap gap-1.5">
      {boxes.length > 0 && (
        <button
          type="button"
          className={button}
          onClick={() =>
            fitToBBox([
              Math.min(...boxes.map((b) => b[0])),
              Math.min(...boxes.map((b) => b[1])),
              Math.max(...boxes.map((b) => b[2])),
              Math.max(...boxes.map((b) => b[3])),
            ])
          }
        >
          <Crosshair className="size-3.5" aria-hidden />
          {t('chat.zoomToResults')}
        </button>
      )}
      <button
        type="button"
        className={button}
        onClick={() => overlays.forEach((o) => updateOverlay(o.id, { visible: !visible }))}
      >
        {visible ? <EyeOff className="size-3.5" aria-hidden /> : <Eye className="size-3.5" aria-hidden />}
        {visible ? t('chat.hideLayer') : t('chat.showLayer')}
      </button>
    </div>
  )
}
