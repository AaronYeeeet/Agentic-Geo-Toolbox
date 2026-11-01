import { BookOpen } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { SourceItem } from '@/api/protocol'
import { isHttpUrl } from '@/lib/safe'

/** Sources under an answer: title, link and license, opening in a new tab. */
export function SourceChips({ sources }: { sources: SourceItem[] }) {
  const { t } = useTranslation()
  if (sources.length === 0) return null
  return (
    <ul aria-label={t('chat.sources')} className="flex flex-wrap gap-1.5">
      {sources.map((source) => {
        const body = (
          <>
            <BookOpen className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate font-medium">{source.title}</span>
            <span aria-hidden className="h-3 w-px shrink-0 bg-rule" />
            <span className="shrink-0 text-ink-3">{source.license}</span>
          </>
        )
        const chip = 'inline-flex max-w-full items-center gap-1.5 rounded-md border border-rule bg-fog/60 px-2 py-1 text-[12px] text-ink-2'
        return (
          <li key={`${source.title}-${source.url}`}>
            {/* Source URLs come from the agent stream: only http(s) becomes a link. */}
            {isHttpUrl(source.url) ? (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`${chip} transition-colors hover:border-water/40 hover:bg-water-wash hover:text-water-ink`}
              >
                {body}
              </a>
            ) : (
              <span className={chip}>{body}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}
