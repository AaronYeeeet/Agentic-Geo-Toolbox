import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { safeStorage } from '@/lib/storage'
import de from './de.json'
import en from './en.json'

export type Language = 'en' | 'de'
export const LANGUAGES: Language[] = ['en', 'de']
const STORAGE_KEY = 'geo-toolbox.lang'

/** English by default; a stored choice wins. */
export function initialLanguage(): Language {
  return safeStorage.get(STORAGE_KEY) === 'de' ? 'de' : 'en'
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, de: { translation: de } },
  lng: initialLanguage(),
  fallbackLng: 'en',
  supportedLngs: LANGUAGES,
  interpolation: { escapeValue: false },
  initAsync: false,
})

document.documentElement.lang = i18n.language
i18n.on('languageChanged', (language) => {
  document.documentElement.lang = language
  safeStorage.set(STORAGE_KEY, language)
})

export function currentLanguage(): Language {
  return i18n.language === 'de' ? 'de' : 'en'
}

export function setLanguage(language: Language): void {
  void i18n.changeLanguage(language)
}

export default i18n
