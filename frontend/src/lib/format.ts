export type Lang = 'en' | 'de'

const locale = (lang: Lang) => (lang === 'de' ? 'de-DE' : 'en-US')

/** m² below 0.1 km², else km² with 2, 1 or 0 decimals. Same rule as the backend (app/agent/texts.py). */
export function formatArea(m2: number, lang: Lang): string {
  if (m2 < 100_000) {
    return `${new Intl.NumberFormat(locale(lang), { maximumFractionDigits: 0 }).format(m2)} m²`
  }
  const km2 = m2 / 1_000_000
  const digits = km2 < 10 ? 2 : km2 < 100 ? 1 : 0
  return `${new Intl.NumberFormat(locale(lang), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(km2)} km²`
}
