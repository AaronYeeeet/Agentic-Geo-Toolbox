import { ImageOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useSourcesStore } from '@/api/sources'
import { aerialCoverageAt } from '@/map/basemaps'
import { useMapStore } from '@/store/mapStore'

/** Outside the covered states the aerial basemap says so instead of failing silently. */
export function AerialHint() {
  const { t } = useTranslation()
  const basemap = useMapStore((s) => s.basemap)
  const view = useMapStore((s) => s.view)
  const { sources, status } = useSourcesStore()

  if (basemap !== 'aerial' || !view) return null
  let message: string | null = null
  if (status === 'error') message = t('map.aerialUnavailable')
  else if (status === 'ready' && aerialCoverageAt(sources, view.center[0], view.center[1]).length === 0) {
    message = t('map.aerialNoCoverage')
  }
  if (!message) return null

  return (
    <div
      role="status"
      className="float-panel pointer-events-auto flex max-w-md items-start gap-2 px-3 py-2 text-[13px] text-ink"
      data-testid="aerial-hint"
    >
      <ImageOff className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <span>{message}</span>
    </div>
  )
}
