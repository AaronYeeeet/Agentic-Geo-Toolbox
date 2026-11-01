import { type PointerEvent, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chatStore'
import { useLayerStore } from '@/store/layerStore'
import { useSelectionStore } from '@/store/selectionStore'
import { type SheetSnap, useUiStore } from '@/store/uiStore'
import { ChatPanel } from './ChatPanel'

const ORDER: SheetSnap[] = ['peek', 'half', 'full']

function useViewportHeight() {
  const [height, setHeight] = useState(() => window.innerHeight)
  useEffect(() => {
    const update = () => setHeight(window.innerHeight)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  return height
}

/**
 * The chat below 768 px: a non-modal bottom sheet with snap points peek (composer only), half
 * and full. The map stays usable above it; bottom map controls follow its height through `--sheet-offset`.
 */
export function BottomSheet() {
  const { t } = useTranslation()
  const snap = useUiStore((s) => s.sheetSnap)
  const setSnap = useUiStore((s) => s.setSheetSnap)
  const viewport = useViewportHeight()
  const hasSelection = useSelectionStore((s) => Boolean(s.selection))
  const excluded = useChatStore((s) => s.excludedUploads)
  const hasUploads = useLayerStore((s) => s.overlays.some((o) => o.group === 'mydata' && !excluded.includes(o.id)))
  const peek = 124 + (hasSelection || hasUploads ? 36 : 0)
  const heights: Record<SheetSnap, number> = { peek, half: Math.round(viewport * 0.5), full: Math.round(viewport - 64) }

  const [drag, setDrag] = useState<{ startY: number; startHeight: number; height: number } | null>(null)
  const dragged = useRef(false)
  const height = drag?.height ?? heights[snap]

  useEffect(() => {
    document.documentElement.style.setProperty('--sheet-offset', `${Math.min(height, heights.half)}px`)
  }, [height, heights.half])
  useEffect(() => () => document.documentElement.style.setProperty('--sheet-offset', '0px'), [])

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture?.(event.pointerId)
    dragged.current = false
    setDrag({ startY: event.clientY, startHeight: height, height })
  }
  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (!drag) return
    const delta = drag.startY - event.clientY
    if (Math.abs(delta) > 4) dragged.current = true
    setDrag({ ...drag, height: Math.min(heights.full, Math.max(heights.peek, drag.startHeight + delta)) })
  }
  const onPointerUp = () => {
    if (!drag) return
    if (dragged.current) {
      const nearest = ORDER.reduce((best, s) => (Math.abs(heights[s] - drag.height) < Math.abs(heights[best] - drag.height) ? s : best))
      setSnap(nearest)
    }
    setDrag(null)
  }

  return (
    <section
      aria-label={t('chat.title')}
      data-testid="bottom-sheet"
      data-snap={snap}
      style={{ height }}
      className={cn(
        'fixed inset-x-0 bottom-0 z-30 flex flex-col overflow-hidden rounded-t-2xl border-t border-rule bg-paper shadow-[0_-10px_30px_-12px_rgb(18_32_46/0.35)]',
        !drag && 'transition-[height] duration-300 ease-out',
      )}
    >
      <button
        type="button"
        aria-label={t('chat.sheetHandle')}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onClick={() => {
          if (dragged.current) return
          setSnap(ORDER[(ORDER.indexOf(snap) + 1) % ORDER.length])
        }}
        className="flex h-6 shrink-0 cursor-grab touch-none items-center justify-center active:cursor-grabbing"
      >
        <span aria-hidden className="h-1.5 w-10 rounded-full bg-fog-2" />
      </button>
      <div className="min-h-0 flex-1">
        <ChatPanel variant="sheet" compact={snap === 'peek'} onSent={() => snap === 'peek' && setSnap('half')} />
      </div>
    </section>
  )
}
