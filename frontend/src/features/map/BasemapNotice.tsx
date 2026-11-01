import { CloudOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useMapStore } from '@/store/mapStore'

/** Says when a basemap provider is unreachable and a fallback style stands in. */
export function BasemapNotice() {
  const { t } = useTranslation()
  const fallback = useMapStore((s) => s.basemapFallback)
  if (!fallback) return null
  return (
    <div
      role="status"
      className="float-panel pointer-events-auto flex max-w-md items-start gap-2 px-3 py-2 text-[13px] text-ink"
      data-testid="basemap-notice"
    >
      <CloudOff className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <span>{t('basemap.fallback')}</span>
    </div>
  )
}
