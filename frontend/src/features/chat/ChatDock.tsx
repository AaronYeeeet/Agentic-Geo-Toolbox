import { MessageSquareText } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Group, Panel, type PanelImperativeHandle, Separator } from 'react-resizable-panels'
import { cn } from '@/lib/utils'
import { CHAT_EXPANDED_SIZE, CHAT_MAX_SIZE, CHAT_MIN_PX, useUiStore } from '@/store/uiStore'
import { ChatPanel } from './ChatPanel'

/**
 * Desktop layout: the map and the chat docked right. The chat resizes by its handle (320 px to
 * 70 %), widens to about 60 %, collapses to a floating button; width and open state persist.
 */
export function ChatDock({ map }: { map: ReactNode }) {
  const { t } = useTranslation()
  const chat = useRef<PanelImperativeHandle>(null)
  const chatOpen = useUiStore((s) => s.chatOpen)
  const expanded = useUiStore((s) => s.chatExpanded)
  // Sizes at mount only: later changes go through the panel's imperative API.
  const [initial] = useState(() => useUiStore.getState())

  useEffect(() => {
    const panel = chat.current
    if (!panel) return
    if (chatOpen && panel.isCollapsed()) panel.expand()
    if (!chatOpen && !panel.isCollapsed()) panel.collapse()
  }, [chatOpen])

  useEffect(() => {
    const panel = chat.current
    if (!panel || panel.isCollapsed()) return
    panel.resize(`${expanded ? CHAT_EXPANDED_SIZE : useUiStore.getState().chatSize}%`)
  }, [expanded])

  const defaultSize = initial.chatOpen ? `${initial.chatExpanded ? CHAT_EXPANDED_SIZE : initial.chatSize}%` : '0%'

  return (
    <Group orientation="horizontal" className="h-dvh w-dvw bg-fog">
      <Panel id="map-area" minSize="30%">
        {map}
      </Panel>
      <Separator
        aria-label={t('chat.resize')}
        className={cn(
          'group relative w-px bg-rule outline-none transition-colors hover:bg-water data-[separator=active]:bg-water',
          'after:absolute after:inset-y-0 after:-right-1.5 after:-left-1.5 after:content-[""]',
          !chatOpen && 'pointer-events-none opacity-0',
        )}
      >
        <span
          aria-hidden
          className="absolute top-1/2 left-1/2 z-10 h-10 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-rule bg-paper opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
        />
      </Separator>
      <Panel
        id="chat-area"
        panelRef={chat}
        defaultSize={defaultSize}
        minSize={`${CHAT_MIN_PX}px`}
        maxSize={`${CHAT_MAX_SIZE}%`}
        collapsible
        collapsedSize="0%"
        onResize={(size) => {
          const ui = useUiStore.getState()
          const open = size.asPercentage > 0.5
          if (open !== ui.chatOpen) ui.setChatOpen(open)
          if (!open) return
          const percent = Math.round(size.asPercentage)
          if (ui.chatExpanded && Math.abs(percent - CHAT_EXPANDED_SIZE) > 2) ui.setChatExpanded(false)
          if (!ui.chatExpanded && percent !== ui.chatSize) ui.setChatSize(percent)
        }}
      >
        <ChatPanel variant="dock" />
      </Panel>
    </Group>
  )
}

/** The floating button that brings the collapsed chat back. */
export function ChatFab() {
  const { t } = useTranslation()
  const chatOpen = useUiStore((s) => s.chatOpen)
  const setChatOpen = useUiStore((s) => s.setChatOpen)
  if (chatOpen) return null
  return (
    <button
      type="button"
      onClick={() => setChatOpen(true)}
      aria-label={t('chat.open')}
      className="float-panel absolute right-3 bottom-[52px] z-20 flex h-11 items-center gap-2 bg-water pr-4 pl-3.5 text-[14px] font-medium text-white hover:bg-water-ink"
      data-testid="chat-fab"
    >
      <MessageSquareText className="size-[18px]" aria-hidden />
      {t('chat.title')}
    </button>
  )
}
