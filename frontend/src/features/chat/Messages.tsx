import { CircleAlert, RotateCcw } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { type AssistantMessage, type ChatMessage, useChatStore } from '@/store/chatStore'
import { MiniMarkdown } from './MiniMarkdown'
import { ResultActions } from './ResultActions'
import { SourceChips } from './SourceChips'
import { ToolSteps } from './ToolSteps'

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-fog-2/80 px-3.5 py-2 text-[14.5px] whitespace-pre-line text-ink">
        {text}
      </p>
    </div>
  )
}

function Answer({ message }: { message: AssistantMessage }) {
  const { t } = useTranslation()
  const retry = useChatStore((s) => s.retry)
  const streaming = message.status === 'streaming'
  return (
    <article className="space-y-2.5" aria-busy={streaming} data-testid="assistant-message">
      <ToolSteps steps={message.steps} />
      {(message.text || (streaming && message.steps.length === 0)) && (
        <div className="space-y-2 text-[14.5px] leading-relaxed text-ink">
          <MiniMarkdown text={message.text} />
          {streaming && <span aria-hidden className="inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-water/60" />}
        </div>
      )}
      {message.resultLayerIds.length > 0 && <ResultActions layerIds={message.resultLayerIds} />}
      <SourceChips sources={message.sources} />
      {message.status === 'stopped' && <p className="text-[12.5px] text-ink-3 italic">{t('chat.stopped')}</p>}
      {message.status === 'error' && message.error && (
        <div role="alert" className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-wash px-3 py-2 text-[13px] text-ink">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
          <div className="min-w-0 flex-1">
            <p>{message.error.message}</p>
            {message.error.retryable && (
              <button
                type="button"
                onClick={() => void retry(message.id)}
                className="mt-1.5 inline-flex items-center gap-1.5 rounded-md border border-rule bg-paper px-2 py-1 text-[12.5px] font-medium text-ink-2 hover:text-ink"
              >
                <RotateCcw className="size-3.5" aria-hidden />
                {t('chat.retry')}
              </button>
            )}
          </div>
        </div>
      )}
    </article>
  )
}

/** The conversation; follows new content while the reader is at the bottom. */
export function MessageList({ messages }: { messages: ChatMessage[] }) {
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  useEffect(() => {
    const el = scroller.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [messages])

  return (
    <div
      ref={scroller}
      onScroll={(event) => {
        const el = event.currentTarget
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
      }}
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4"
      data-testid="message-list"
    >
      <div className="space-y-5">
        {messages.map((message) =>
          message.role === 'user' ? <UserBubble key={message.id} text={message.text} /> : <Answer key={message.id} message={message} />,
        )}
      </div>
    </div>
  )
}
