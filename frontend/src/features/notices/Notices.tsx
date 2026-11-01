import { CircleAlert, CircleCheck, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { useNoticeStore } from '@/store/noticeStore'

/** Confirmations and errors (uploads), bottom centre of the map. Errors are announced as alerts. */
export function Notices() {
  const { t } = useTranslation()
  const notices = useNoticeStore((s) => s.notices)
  const dismiss = useNoticeStore((s) => s.dismiss)
  if (notices.length === 0) return null
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-[calc(var(--sheet-offset)+16px)] z-30 flex flex-col items-center gap-2 px-3">
      {notices.map((notice) => (
        <div
          key={notice.id}
          role={notice.kind === 'error' ? 'alert' : 'status'}
          className={cn(
            'float-panel pointer-events-auto flex max-w-md items-start gap-2 py-2 pr-1.5 pl-3 text-[13px] text-ink',
            notice.kind === 'error' && 'border-danger/30 bg-danger-wash',
          )}
        >
          {notice.kind === 'error' ? (
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
          ) : (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
          )}
          <span className="py-px">{notice.text}</span>
          <button
            type="button"
            aria-label={t('common.close')}
            onClick={() => dismiss(notice.id)}
            className="grid size-6 shrink-0 place-items-center rounded text-ink-3 hover:bg-black/5 hover:text-ink"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
      ))}
    </div>
  )
}
