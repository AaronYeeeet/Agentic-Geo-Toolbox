import { Maximize2, Minimize2, PanelRightClose, RotateCcw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useChatStore } from '@/store/chatStore'
import { useUiStore } from '@/store/uiStore'
import { Composer } from './Composer'
import { EmptyState } from './EmptyState'
import { MessageList } from './Messages'

function HeaderButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          disabled={disabled}
          onClick={onClick}
          className="grid size-8 place-items-center rounded-md text-ink-3 transition-colors hover:bg-fog hover:text-ink disabled:pointer-events-none disabled:opacity-35 [&_svg]:size-[17px]"
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

/**
 * The assistant panel. `dock` (desktop) has widen and hide controls; `sheet` (phones) lives in the bottom sheet,
 * where `compact` shows only the composer (peek state).
 */
export function ChatPanel({ variant, compact = false, onSent }: { variant: 'dock' | 'sheet'; compact?: boolean; onSent?: () => void }) {
  const { t } = useTranslation()
  const messages = useChatStore((s) => s.messages)
  const reset = useChatStore((s) => s.reset)
  const expanded = useUiStore((s) => s.chatExpanded)
  const { setChatExpanded, setChatOpen } = useUiStore.getState()

  return (
    <section aria-label={t('chat.title')} className="flex h-full min-h-0 flex-col bg-paper" data-testid="chat-panel">
      {!compact && (
        <header className="flex h-13 shrink-0 items-center gap-2 border-b border-rule pr-2 pl-4">
          <h2 className="font-heading text-[16px] font-semibold text-ink">{t('chat.title')}</h2>
          <Tooltip>
            <TooltipTrigger asChild>
              <span tabIndex={0} className="rounded-sm bg-fog px-1.5 py-0.5 font-condensed text-[11.5px] font-semibold text-ink-2">
                {t('chat.demoBadge')}
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom">{t('chat.demoHint')}</TooltipContent>
          </Tooltip>
          <div className="ml-auto flex items-center gap-0.5">
            <HeaderButton label={t('chat.newChat')} onClick={reset} disabled={messages.length === 0}>
              <RotateCcw />
            </HeaderButton>
            {variant === 'dock' && (
              <>
                <HeaderButton label={expanded ? t('chat.narrow') : t('chat.widen')} onClick={() => setChatExpanded(!expanded)}>
                  {expanded ? <Minimize2 /> : <Maximize2 />}
                </HeaderButton>
                <HeaderButton label={t('chat.collapse')} onClick={() => setChatOpen(false)}>
                  <PanelRightClose />
                </HeaderButton>
              </>
            )}
          </div>
        </header>
      )}
      {!compact && (messages.length > 0 ? <MessageList messages={messages} /> : <EmptyState onSent={onSent} />)}
      <Composer onSent={onSent} />
    </section>
  )
}
