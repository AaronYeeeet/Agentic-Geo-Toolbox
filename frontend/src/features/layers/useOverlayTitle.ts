import { useTranslation } from 'react-i18next'
import type { Overlay } from '@/store/layerStore'

/** Display title of an overlay in the UI language: i18n key, registry title, or its own title. */
export function useOverlayTitle() {
  const { t, i18n } = useTranslation()
  return (o: Overlay) =>
    o.titleKey ? t(o.titleKey) : o.titleI18n ? o.titleI18n[i18n.language === 'de' ? 'de' : 'en'] : o.title
}
