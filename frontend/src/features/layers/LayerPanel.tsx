import { Crosshair, Trash2, X } from 'lucide-react'
import { Slider as SliderPrimitive } from 'radix-ui'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { fitToBBox } from '@/map/camera'
import { type Overlay, type OverlayGroup, useLayerStore } from '@/store/layerStore'
import { useUiStore } from '@/store/uiStore'
import { useOverlayTitle } from './useOverlayTitle'

const GROUPS: OverlayGroup[] = ['terrain', 'buildings', 'aerial', 'mydata', 'results']

/** Legend swatch: shape follows the geometry, hatching marks demo data. */
function Swatch({ overlay }: { overlay: Overlay }) {
  const style = { '--swatch': overlay.color ?? '#1f5f8b' } as CSSProperties
  const base = 'size-4 shrink-0 border border-black/10'
  if (overlay.kind === 'terrain') return <span aria-hidden className={cn(base, 'rounded-sm bg-gradient-to-br from-[#9cc28a] via-[#d9c59a] to-[#a9876b]')} />
  if (overlay.kind === 'hillshade') return <span aria-hidden className={cn(base, 'rounded-sm bg-gradient-to-br from-white via-[#b8bfc6] to-[#4d5966]')} />
  if (overlay.kind === 'buildings' || overlay.kind === 'lod2') {
    return <span aria-hidden className={cn(base, 'rounded-sm bg-gradient-to-b from-[#ece9e3] to-[#c3beb4]')} />
  }
  if (overlay.kind === 'wms') return <span aria-hidden className={cn(base, 'rounded-sm bg-[conic-gradient(#8aa58a_0_25%,#c9bfa6_0_50%,#9aa9b4_0_75%,#d8d2c4_0)]')} />
  const types = overlay.geometryTypes ?? []
  const isPoint = types.length > 0 && types.every((g) => g.includes('Point'))
  const isLine = types.length > 0 && types.every((g) => g.includes('LineString'))
  if (isLine) return <span aria-hidden className="h-1 w-4 shrink-0 rounded-full" style={{ background: overlay.color }} />
  return (
    <span
      aria-hidden
      style={style}
      className={cn(base, isPoint ? 'rounded-full' : 'rounded-sm', overlay.demo ? 'swatch-demo' : 'bg-[var(--swatch)]')}
    />
  )
}

function IconAction({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          onClick={onClick}
          className="grid size-7 place-items-center rounded-md text-ink-3 hover:bg-fog hover:text-ink [&_svg]:size-4"
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

function LayerRow({ overlay }: { overlay: Overlay }) {
  const { t } = useTranslation()
  const title = useOverlayTitle()(overlay)
  const { updateOverlay, removeOverlay } = useLayerStore()
  const meta = [
    overlay.featureCount != null ? t('layers.features', { count: overlay.featureCount }) : null,
    overlay.disabled ? t('layers.lod2Planned') : null,
    overlay.attribution ?? null,
  ].filter(Boolean)

  return (
    <li className="px-3 py-2">
      <div className="flex items-center gap-2.5">
        <Swatch overlay={overlay} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className={cn('truncate text-[13.5px] font-medium', overlay.disabled ? 'text-ink-2' : 'text-ink')}>{title}</span>
            {overlay.demo && (
              <span className="shrink-0 rounded-sm bg-overprint-wash px-1.5 py-px font-condensed text-[11px] font-semibold text-overprint">
                {t('layers.demo')}
              </span>
            )}
          </div>
          {meta.length > 0 && <p className="truncate text-xs text-ink-3">{meta.join(', ')}</p>}
        </div>
        {overlay.bbox && (
          <IconAction label={t('layers.zoomTo', { title })} onClick={() => fitToBBox(overlay.bbox!)}>
            <Crosshair />
          </IconAction>
        )}
        {overlay.removable && (
          <IconAction label={t('layers.remove', { title })} onClick={() => removeOverlay(overlay.id)}>
            <Trash2 />
          </IconAction>
        )}
        <Switch
          checked={overlay.visible}
          disabled={overlay.disabled}
          aria-label={t('layers.show', { title })}
          onCheckedChange={(visible) => updateOverlay(overlay.id, { visible })}
        />
      </div>
      {overlay.visible && !overlay.disabled && overlay.kind !== 'terrain' && (
        <SliderPrimitive.Root
          className="relative mt-2 ml-6.5 flex h-4 w-[calc(100%-1.625rem)] touch-none items-center select-none"
          min={0}
          max={100}
          step={5}
          value={[Math.round(overlay.opacity * 100)]}
          onValueChange={([value]) => updateOverlay(overlay.id, { opacity: value / 100 })}
        >
          <SliderPrimitive.Track className="relative h-1 grow rounded-full bg-fog-2">
            <SliderPrimitive.Range className="absolute h-full rounded-full bg-water/70" />
          </SliderPrimitive.Track>
          <SliderPrimitive.Thumb
            aria-label={t('layers.opacity', { title })}
            className="block size-3.5 rounded-full border border-water bg-white shadow-sm focus-visible:ring-3 focus-visible:ring-water/30"
          />
        </SliderPrimitive.Root>
      )}
    </li>
  )
}

/** Overlays by group: toggle, opacity, legend swatch, attribution, zoom-to and remove. */
export function LayerPanel() {
  const { t } = useTranslation()
  const overlays = useLayerStore((s) => s.overlays)
  const close = () => useUiStore.getState().setLayerPanelOpen(false)

  return (
    <div className="float-panel flex max-h-full w-80 flex-col overflow-hidden" data-testid="layer-panel">
      <div className="flex items-center justify-between border-b border-rule py-2 pr-1.5 pl-3">
        <h2 className="font-heading text-[15px] font-semibold text-ink">{t('layers.title')}</h2>
        <IconAction label={t('layers.close')} onClick={close}>
          <X />
        </IconAction>
      </div>
      <div className="overflow-y-auto overscroll-contain pb-1">
        {GROUPS.map((group) => {
          const items = overlays.filter((o) => o.group === group)
          const heading = t(`layers.groups.${group}`)
          return (
            <section key={group} aria-label={heading} className="border-b border-rule/70 last:border-b-0">
              <h3 className="px-3 pt-2.5 pb-0.5 font-condensed text-[12.5px] font-semibold text-ink-2">{heading}</h3>
              {items.length > 0 ? (
                <ul>
                  {items.map((overlay) => (
                    <LayerRow key={overlay.id} overlay={overlay} />
                  ))}
                </ul>
              ) : (
                <p className="px-3 pt-1 pb-2.5 text-xs text-ink-3">{t(`layers.empty.${group}`)}</p>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
