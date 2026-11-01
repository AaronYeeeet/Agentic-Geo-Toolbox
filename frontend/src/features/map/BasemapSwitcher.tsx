import { LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { BASEMAPS } from '@/map/basemaps'
import { type BasemapId, useMapStore } from '@/store/mapStore'

/** Small previews of the basemaps of Darmstadt (generated from the real styles by e2e/thumbnails.spec.ts). */
function Thumb({ id, className }: { id: BasemapId; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('block size-12 rounded-md border border-black/10 bg-fog bg-cover bg-center', className)}
      style={{ backgroundImage: `url(/basemaps/${id}.jpg)` }}
    />
  )
}

/** Basemap picker, bottom-left: the current basemap as one tile that opens a row of all five. */
export function BasemapSwitcher() {
  const { t } = useTranslation()
  const basemap = useMapStore((s) => s.basemap)
  const setBasemap = useMapStore((s) => s.setBasemap)
  const loading = useMapStore((s) => s.styleLoading)
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!open) {
    return (
      <div ref={root} className="float-panel p-1">
        <button
          type="button"
          aria-expanded={false}
          aria-label={`${t('basemap.choose')}: ${t(`basemap.${basemap}`)}`}
          onClick={() => setOpen(true)}
          className="group flex flex-col items-center gap-1 rounded-md p-1 hover:bg-fog"
          data-testid="basemap-switcher"
        >
          <span className="relative">
            <Thumb id={basemap} />
            {loading && (
              <span className="absolute inset-0 grid place-items-center rounded-md bg-white/60">
                <LoaderCircle className="size-5 animate-spin text-water" aria-hidden />
              </span>
            )}
          </span>
          <span className="font-condensed text-xs font-semibold text-ink-2 group-hover:text-ink">
            {t(`basemap.${basemap}`)}
          </span>
        </button>
      </div>
    )
  }

  return (
    <div ref={root} role="radiogroup" aria-label={t('basemap.label')} className="float-panel flex gap-1 p-1">
      {BASEMAPS.map(({ id }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={basemap === id}
          title={t(`basemap.${id}Hint`)}
          onClick={() => {
            setBasemap(id)
            setOpen(false)
          }}
          className={cn(
            'flex flex-col items-center gap-1 rounded-md p-1 hover:bg-fog',
            basemap === id && 'bg-water-wash hover:bg-water-wash',
          )}
          data-testid={`basemap-${id}`}
        >
          <Thumb id={id} className={cn(basemap === id && 'ring-2 ring-water ring-offset-1')} />
          <span
            className={cn('font-condensed text-xs font-semibold', basemap === id ? 'text-water-ink' : 'text-ink-2')}
          >
            {t(`basemap.${id}`)}
          </span>
        </button>
      ))}
    </div>
  )
}
