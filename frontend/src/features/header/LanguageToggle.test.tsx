import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useTranslation } from 'react-i18next'
import { afterEach, expect, test } from 'vitest'
import i18n from '@/i18n'
import { LanguageToggle } from './LanguageToggle'

function Probe() {
  const { t } = useTranslation()
  return <p>{t('chat.title')}</p>
}

afterEach(async () => {
  await i18n.changeLanguage('en')
  window.localStorage.clear()
})

test('switching to German translates the UI, sets <html lang> and persists the choice', async () => {
  render(
    <>
      <LanguageToggle />
      <Probe />
    </>,
  )
  expect(screen.getByText('Geo assistant')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('radio', { name: 'Deutsch' }))

  expect(screen.getByText('Geo-Assistent')).toBeInTheDocument()
  expect(document.documentElement.lang).toBe('de')
  expect(window.localStorage.getItem('geo-toolbox.lang')).toBe('de')
  expect(screen.getByRole('radio', { name: 'Deutsch' })).toHaveAttribute('aria-checked', 'true')
})
