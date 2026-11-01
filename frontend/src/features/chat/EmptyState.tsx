import { EvCharger, Plane, Ruler, School } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '@/store/chatStore'

const EXAMPLES = [
  { key: 'charging', icon: EvCharger },
  { key: 'schools', icon: School },
  { key: 'area', icon: Ruler },
  { key: 'flyTo', icon: Plane },
] as const

/** Empty chat: a short intro and four example prompts in the UI language. */
export function EmptyState({ onSent }: { onSent?: () => void }) {
  const { t } = useTranslation()
  const send = useChatStore((s) => s.send)
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5" data-testid="chat-empty">
      <p className="max-w-prose text-[14.5px] leading-relaxed text-ink-2">{t('chat.intro')}</p>
      <ul className="mt-4 space-y-1.5">
        {EXAMPLES.map(({ key, icon: Icon }) => {
          const prompt = t(`chat.examples.${key}`)
          return (
            <li key={key}>
              <button
                type="button"
                onClick={() => {
                  void send(prompt)
                  onSent?.()
                }}
                className="group flex w-full items-start gap-3 rounded-lg border border-rule bg-paper px-3 py-2.5 text-left text-[14px] text-ink transition-colors hover:border-water/40 hover:bg-water-wash"
              >
                <Icon className="mt-0.5 size-4 shrink-0 text-ink-3 group-hover:text-water" aria-hidden />
                <span>{prompt}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
