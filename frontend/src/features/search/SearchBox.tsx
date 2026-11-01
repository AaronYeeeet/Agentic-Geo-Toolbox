import {
  Building2,
  Landmark,
  Loader2,
  MapPin,
  Search,
  SquareDashedMousePointer,
  TrainFront,
  Trees,
  X,
} from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { START_VIEW } from '@/map/config'
import { fitToBBox } from '@/map/camera'
import { getMap } from '@/map/mapRef'
import { useSelectionStore } from '@/store/selectionStore'
import { type SearchResult, searchPhoton, selectionFromResult } from './photon'

const MIN_CHARS = 3
const DEBOUNCE_MS = 300

function KindIcon({ kind }: { kind: string }) {
  const Icon = /station|railway|halt|tram/.test(kind)
    ? TrainFront
    : /park|forest|wood|garden|nature|water/.test(kind)
      ? Trees
      : /worship|cathedral|church|museum|castle|monument|attraction|historic/.test(kind)
        ? Landmark
        : /building|office|university|school|college|hospital|commercial/.test(kind)
          ? Building2
          : MapPin
  return <Icon className="size-4 shrink-0 text-ink-3" aria-hidden />
}

function flyToResult(result: SearchResult) {
  const map = getMap()
  if (!map) return
  if (!result.bbox || !fitToBBox(result.bbox)) map.flyTo({ center: result.center, zoom: 16.5, duration: 1200 })
}

type Status = 'idle' | 'loading' | 'done' | 'error'

/** Place search, top-left: Photon autocomplete in the UI language, biased to the view. */
export function SearchBox({ className }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const listId = useId()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [status, setStatus] = useState<Status>('idle')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [chosen, setChosen] = useState<string | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const trimmed = query.trim()
  const searchable = trimmed.length >= MIN_CHARS && trimmed !== chosen

  useEffect(() => {
    if (!searchable) return
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setStatus('loading')
      setOpen(true)
      try {
        const map = getMap()
        const center = map?.getCenter()
        const found = await searchPhoton(trimmed, {
          lang: i18n.language === 'de' ? 'de' : 'en',
          center: center ? [center.lng, center.lat] : START_VIEW.center,
          zoom: map?.getZoom() ?? 12,
          signal: controller.signal,
        })
        setResults(found)
        setActive(-1)
        setStatus('done')
      } catch {
        if (!controller.signal.aborted) setStatus('error')
      }
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [trimmed, searchable, i18n.language])

  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [])

  const close = (name?: string) => {
    if (name) {
      setChosen(name)
      setQuery(name)
    }
    setOpen(false)
    setActive(-1)
  }

  const choose = (result: SearchResult) => {
    flyToResult(result)
    close(result.name)
  }

  const selectResultArea = (result: SearchResult) => {
    const selection = selectionFromResult(result)
    useSelectionStore.getState().setSelection(selection)
    const ring = (selection.geometry as GeoJSON.Polygon).coordinates[0]
    const lngs = ring.map((c) => c[0])
    const lats = ring.map((c) => c[1])
    fitToBBox([Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)])
    close(result.name)
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' && results.length) {
      event.preventDefault()
      setOpen(true)
      setActive((i) => (i + 1) % results.length)
    } else if (event.key === 'ArrowUp' && results.length) {
      event.preventDefault()
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1))
    } else if (event.key === 'Enter' && open && results.length) {
      event.preventDefault()
      choose(results[Math.max(active, 0)])
    } else if (event.key === 'Escape') {
      if (open) close()
      else setQuery('')
    }
  }

  const showList = open && searchable && status !== 'idle'
  const optionId = (index: number) => `${listId}-option-${index}`

  return (
    <div ref={root} className={cn('pointer-events-auto relative w-full sm:w-[22.5rem]', className)} data-testid="search-box">
      <div className="float-panel flex h-11 items-center gap-2 px-3 focus-within:border-water/50">
        <Search className="size-[18px] shrink-0 text-ink-3" aria-hidden />
        <input
          role="combobox"
          aria-label={t('search.label')}
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? optionId(active) : undefined}
          value={query}
          placeholder={t('search.placeholder')}
          onChange={(event) => {
            setChosen(null)
            setQuery(event.target.value)
          }}
          onFocus={() => results.length > 0 && searchable && setOpen(true)}
          onKeyDown={onKeyDown}
          className="h-full min-w-0 flex-1 bg-transparent text-[14.5px] text-ink outline-none placeholder:text-ink-3"
          spellCheck={false}
          autoComplete="off"
        />
        {status === 'loading' && searchable && (
          <Loader2 className="size-4 shrink-0 animate-spin text-ink-3" aria-label={t('search.loading')} />
        )}
        {query && (
          <button
            type="button"
            aria-label={t('search.clear')}
            onClick={() => {
              setChosen(null)
              setQuery('')
              setResults([])
              setStatus('idle')
            }}
            className="grid size-7 place-items-center rounded-md text-ink-3 hover:bg-fog hover:text-ink"
          >
            <X className="size-4" aria-hidden />
          </button>
        )}
      </div>

      {showList && (
        <div className="float-panel absolute inset-x-0 top-[calc(100%+6px)] z-30 overflow-hidden">
          <ul id={listId} role="listbox" aria-label={t('search.label')} className="max-h-80 overflow-y-auto py-1">
            {status === 'done' &&
              results.map((result, index) => (
                <li key={result.id} role="presentation" className={cn('flex items-center pr-1', index === active && 'bg-water-wash')}>
                  <div
                    id={optionId(index)}
                    role="option"
                    aria-selected={index === active}
                    onPointerDown={(event) => event.preventDefault()}
                    onClick={() => choose(result)}
                    onMouseEnter={() => setActive(index)}
                    className="flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 py-2 pl-3"
                  >
                    <KindIcon kind={result.kind} />
                    <span className="min-w-0">
                      <span className="block truncate text-[14px] font-medium text-ink">{result.name}</span>
                      {result.detail && <span className="block truncate text-xs text-ink-3">{result.detail}</span>}
                    </span>
                  </div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label={t('search.useAsSelection')}
                        onClick={() => selectResultArea(result)}
                        className="grid size-8 shrink-0 place-items-center rounded-md text-ink-3 hover:bg-overprint-wash hover:text-overprint"
                      >
                        <SquareDashedMousePointer className="size-4" aria-hidden />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="right">{t('search.useAsSelection')}</TooltipContent>
                  </Tooltip>
                </li>
              ))}
            {status === 'done' && results.length === 0 && (
              <li className="px-3 py-2.5 text-[13px] text-ink-3">{t('search.noResults')}</li>
            )}
            {status === 'error' && <li className="px-3 py-2.5 text-[13px] text-danger">{t('search.error')}</li>}
            {status === 'loading' && results.length === 0 && (
              <li className="px-3 py-2.5 text-[13px] text-ink-3">{t('search.loading')}</li>
            )}
          </ul>
          <p className="border-t border-rule px-3 py-1.5 text-[11px] text-ink-3">{t('search.attribution')}</p>
        </div>
      )}
    </div>
  )
}
