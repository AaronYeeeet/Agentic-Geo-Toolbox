import { useTranslation } from 'react-i18next'
import { TooltipProvider } from '@/components/ui/tooltip'
import { BottomSheet } from '@/features/chat/BottomSheet'
import { ChatDock, ChatFab } from '@/features/chat/ChatDock'
import { DrawToolbar } from '@/features/draw/DrawToolbar'
import { LanguageToggle } from '@/features/header/LanguageToggle'
import { LayerPanel } from '@/features/layers/LayerPanel'
import { LayersButton } from '@/features/layers/LayersButton'
import { useRegistryOverlays } from '@/features/layers/registryOverlays'
import { AerialHint } from '@/features/map/AerialHint'
import { BasemapNotice } from '@/features/map/BasemapNotice'
import { BasemapSwitcher } from '@/features/map/BasemapSwitcher'
import { NavControls } from '@/features/map/NavControls'
import { Notices } from '@/features/notices/Notices'
import { SearchBox } from '@/features/search/SearchBox'
import { DropOverlay } from '@/features/uploads/DropOverlay'
import { useFileDrop } from '@/features/uploads/useFileDrop'
import { useIsMobile } from '@/hooks/useIsMobile'
import { MapView } from '@/map/MapView'
import { useUiStore } from '@/store/uiStore'

/** The map with its floating controls: search top-left, tools left, layers and language top-right. */
function MapArea({ mobile = false }: { mobile?: boolean }) {
  const { t } = useTranslation()
  const layerPanelOpen = useUiStore((s) => s.layerPanelOpen)
  const chatOpen = useUiStore((s) => s.chatOpen)
  useRegistryOverlays()
  return (
    <main className="relative h-full w-full min-w-0 overflow-hidden" aria-label={t('map.label')}>
      <MapView />
      <div className="pointer-events-none absolute inset-x-3 top-3 z-10 flex items-start justify-between gap-2">
        <div className="pointer-events-none flex min-w-0 flex-1 flex-col gap-2 sm:flex-none" data-slot="top-left">
          <SearchBox />
          <DrawToolbar />
        </div>
        <div className="pointer-events-auto flex items-start gap-2" data-slot="top-right">
          <LayersButton />
          <LanguageToggle />
        </div>
      </div>
      {layerPanelOpen && (
        <div className="absolute top-16 right-3 z-20 flex max-h-[calc(100%-var(--sheet-offset)-20rem)] min-h-48 max-w-[calc(100%-1.5rem)]">
          <LayerPanel />
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-0 top-16 z-10 flex flex-col items-center gap-2 px-3">
        <AerialHint />
        <BasemapNotice />
      </div>
      <div
        className={
          mobile
            ? 'absolute bottom-[calc(var(--sheet-offset)+40px)] left-3 z-10'
            : 'absolute bottom-[calc(var(--sheet-offset)+12px)] left-3 z-10'
        }
      >
        <BasemapSwitcher />
      </div>
      <div
        className={
          mobile
            ? 'absolute right-3 bottom-[calc(var(--sheet-offset)+84px)] z-10'
            : chatOpen
              ? 'absolute right-3 bottom-16 z-10'
              : 'absolute right-3 bottom-[112px] z-10'
        }
      >
        <NavControls />
      </div>
      {!mobile && <ChatFab />}
      <Notices />
    </main>
  )
}

export default function App() {
  const isMobile = useIsMobile()
  // Files can be dropped anywhere in the app (map, chat, sheet); the browser never opens them instead.
  const { dragging, handlers } = useFileDrop()

  return (
    <TooltipProvider delayDuration={300}>
      <div className="relative h-dvh w-dvw overflow-hidden bg-fog" data-testid="app-root" {...handlers}>
        {dragging && <DropOverlay />}
        {isMobile ? (
          <>
            <MapArea mobile />
            <BottomSheet />
          </>
        ) : (
          <ChatDock map={<MapArea />} />
        )}
      </div>
    </TooltipProvider>
  )
}
