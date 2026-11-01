import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { SourceChips } from './SourceChips'

test('only http(s) sources become links; anything else is shown as plain text', () => {
  render(
    <SourceChips
      sources={[
        { title: 'OpenStreetMap', url: 'https://www.openstreetmap.org/copyright', license: 'ODbL 1.0' },
        { title: 'Suspicious', url: 'javascript:alert(1)', license: 'none' },
      ]}
    />,
  )

  expect(screen.getByRole('link', { name: /OpenStreetMap/ })).toHaveAttribute('href', 'https://www.openstreetmap.org/copyright')
  expect(screen.queryByRole('link', { name: /Suspicious/ })).toBeNull()
  expect(screen.getByText('Suspicious')).toBeInTheDocument()
})
