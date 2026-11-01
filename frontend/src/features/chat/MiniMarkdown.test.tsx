import { render } from '@testing-library/react'
import { expect, test } from 'vitest'
import { MiniMarkdown } from './MiniMarkdown'

test('renders paragraphs, bullet lists and bold without interpreting HTML', () => {
  const { container } = render(
    <MiniMarkdown text={'I found **6 schools**:\n- Demo school 1\n- Demo school 2\n\nThese are <b>demo</b> data.'} />,
  )

  expect(container.querySelectorAll('p')).toHaveLength(2)
  expect(container.querySelector('strong')?.textContent).toBe('6 schools')
  expect([...container.querySelectorAll('li')].map((li) => li.textContent)).toEqual(['Demo school 1', 'Demo school 2'])
  expect(container.querySelector('b')).toBeNull()
  expect(container.textContent).toContain('<b>demo</b>')
})

test('an unfinished bold marker while streaming stays plain text', () => {
  const { container } = render(<MiniMarkdown text="The area covers **0.4" />)

  expect(container.textContent).toBe('The area covers **0.4')
})
