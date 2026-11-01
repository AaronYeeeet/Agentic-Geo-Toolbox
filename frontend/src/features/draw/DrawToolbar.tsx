import { Eraser, MousePointerClick, Pentagon, RectangleHorizontal, Scan } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { MapButton, PanelDivider } from '@/components/MapButton'
import { getMap } from '@/map/mapRef'
import { type DrawTool, useDrawStore } from '@/store/drawStore'
import { useSelectionStore } from '@/store/selectionStore'
import { selectionFromBounds } from './selection'

const TOOLS: { tool: DrawTool; icon: typeof Pentagon }[] = [
  { tool: 'rectangle', icon: RectangleHorizontal },
  { tool: 'polygon', icon: Pentagon },
  { tool: 'feature', icon: MousePointerClick },
]

/** Selection tools, left: rectangle, polygon, pick a feature, current view, clear. */
export function DrawToolbar() {
  const { t } = useTranslation()
  const tool = useDrawStore((s) => s.tool)
  const setTool = useDrawStore((s) => s.setTool)
  const selection = useSelectionStore((s) => s.selection)
  const { setSelection, clearSelection } = useSelectionStore.getState()

  const selectView = () => {
    const bounds = getMap()?.getBounds()
    if (!bounds) return
    setTool(null)
    setSelection(selectionFromBounds([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]))
  }

  return (
    <div className="pointer-events-none flex items-start gap-2">
      <div role="toolbar" aria-label={t('draw.toolbar')} aria-orientation="vertical" className="float-panel pointer-events-auto flex flex-col overflow-hidden" data-testid="draw-toolbar">
        {TOOLS.map(({ tool: id, icon: Icon }) => (
          <MapButton
            key={id}
            label={t(`draw.${id}`)}
            pressed={tool === id}
            onClick={() => setTool(tool === id ? null : id)}
            data-testid={`draw-${id}`}
          >
            <Icon />
          </MapButton>
        ))}
        <MapButton label={t('draw.view')} onClick={selectView} data-testid="draw-view">
          <Scan />
        </MapButton>
        <PanelDivider />
        <MapButton
          label={t('draw.clear')}
          disabled={!selection && !tool}
          onClick={() => {
            setTool(null)
            clearSelection()
          }}
          data-testid="draw-clear"
        >
          <Eraser />
        </MapButton>
      </div>
      {tool && (
        <p role="status" className="float-panel pointer-events-auto max-w-56 px-3 py-2 text-[13px] leading-snug text-ink-2">
          {t(`draw.hint.${tool}`)}
        </p>
      )}
    </div>
  )
}
