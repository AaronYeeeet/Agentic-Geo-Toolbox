import { Minus, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MapButton, PanelDivider } from '@/components/MapButton'
import { useMap } from '@/map/mapRef'
import { useMapStore } from '@/store/mapStore'

/** North needle that turns with the map; red tip north, as on a compass. */
function NorthNeedle({ bearing, pitch }: { bearing: number; pitch: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      style={{ transform: `rotateX(${pitch * 0.6}deg) rotate(${-bearing}deg)` }}
      className="transition-transform duration-75"
    >
      <path d="M12 2.5 16 12h-8z" fill="#b42318" />
      <path d="M12 21.5 8 12h8z" fill="currentColor" opacity="0.55" />
    </svg>
  )
}

/** Zoom, compass reset and the 2D/3D toggle. */
export function NavControls() {
  const { t } = useTranslation()
  const map = useMap()
  const viewMode = useMapStore((s) => s.viewMode)
  const setViewMode = useMapStore((s) => s.setViewMode)
  const [camera, setCamera] = useState({ bearing: 0, pitch: 0 })

  useEffect(() => {
    if (!map) return
    const update = () => setCamera({ bearing: map.getBearing(), pitch: map.getPitch() })
    update()
    map.on('rotate', update)
    map.on('pitch', update)
    return () => {
      map.off('rotate', update)
      map.off('pitch', update)
    }
  }, [map])

  const resetNorth = () => {
    if (!map) return
    // In 3D keep the tilt and only turn north; in 2D also flatten.
    if (viewMode === '3d') map.resetNorth({ duration: 500 })
    else map.resetNorthPitch({ duration: 500 })
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="float-panel flex flex-col overflow-hidden">
        <MapButton label={t('map.zoomIn')} side="left" onClick={() => map?.zoomIn()}>
          <Plus />
        </MapButton>
        <PanelDivider />
        <MapButton label={t('map.zoomOut')} side="left" onClick={() => map?.zoomOut()}>
          <Minus />
        </MapButton>
        <PanelDivider />
        <MapButton label={t('map.resetNorth')} side="left" onClick={resetNorth}>
          <NorthNeedle bearing={camera.bearing} pitch={camera.pitch} />
        </MapButton>
      </div>
      <div className="float-panel overflow-hidden">
        <MapButton
          label={viewMode === '3d' ? t('map.to2d') : t('map.to3d')}
          side="left"
          aria-label={t('map.view3d')}
          pressed={viewMode === '3d'}
          onClick={() => setViewMode(viewMode === '3d' ? '2d' : '3d')}
          className="font-condensed text-[13px] font-semibold"
          data-testid="view-mode-toggle"
        >
          {t('map.mode3d')}
        </MapButton>
      </div>
    </div>
  )
}
