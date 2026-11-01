import { FileUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'

export function DropOverlay() {
  const { t } = useTranslation()
  return (
    <div className="pointer-events-none absolute inset-3 z-50 grid place-items-center rounded-xl border-2 border-dashed border-water bg-water/10">
      <div className="float-panel flex items-center gap-3 px-5 py-4">
        <FileUp className="size-6 text-water" aria-hidden />
        <div>
          <p className="font-heading text-[15px] font-semibold text-ink">{t('upload.dropTitle')}</p>
          <p className="text-[13px] text-ink-3">{t('upload.dropFormats')}</p>
        </div>
      </div>
    </div>
  )
}
