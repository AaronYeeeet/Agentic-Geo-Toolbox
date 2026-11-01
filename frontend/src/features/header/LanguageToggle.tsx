import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { LANGUAGES, type Language, setLanguage } from '@/i18n'

/** EN/DE switch: a two-option radio group styled as a segmented control. */
export function LanguageToggle({ className }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const active: Language = i18n.language === 'de' ? 'de' : 'en'

  return (
    <div
      role="radiogroup"
      aria-label={t('language.label')}
      className={cn('float-panel flex h-10 items-center gap-0.5 p-1', className)}
    >
      {LANGUAGES.map((language) => (
        <button
          key={language}
          type="button"
          role="radio"
          aria-checked={active === language}
          aria-label={t(`language.${language}`)}
          onClick={() => setLanguage(language)}
          className={cn(
            'h-full min-w-9 rounded-md px-2 font-condensed text-[13px] font-semibold tracking-wide transition-colors',
            active === language ? 'bg-ink text-white' : 'text-ink-2 hover:bg-fog',
          )}
        >
          {language.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
