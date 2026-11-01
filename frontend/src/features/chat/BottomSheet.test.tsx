import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useChatStore } from '@/store/chatStore'
import { useUiStore } from '@/store/uiStore'
import { BottomSheet } from './BottomSheet'

const renderSheet = () =>
  render(
    <TooltipProvider>
      <BottomSheet />
    </TooltipProvider>,
  )

beforeEach(() => {
  useUiStore.setState({ sheetSnap: 'peek' })
  useChatStore.getState().reset()
  useChatStore.setState({ send: vi.fn(async () => {}) })
})

test('the handle cycles peek, half and full, and peek shows only the composer', async () => {
  renderSheet()
  const sheet = screen.getByTestId('bottom-sheet')
  const handle = screen.getByRole('button', { name: 'Drag to resize the chat' })
  expect(sheet).toHaveAttribute('data-snap', 'peek')
  expect(screen.queryByTestId('chat-empty')).not.toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Ask about this area' })).toBeInTheDocument()

  await userEvent.click(handle)
  expect(sheet).toHaveAttribute('data-snap', 'half')
  expect(screen.getByTestId('chat-empty')).toBeInTheDocument()

  await userEvent.click(handle)
  expect(sheet).toHaveAttribute('data-snap', 'full')
  await userEvent.click(handle)
  expect(sheet).toHaveAttribute('data-snap', 'peek')
})

test('sending a question from the peek state opens the sheet to half height', async () => {
  renderSheet()

  await userEvent.type(screen.getByRole('textbox', { name: 'Ask about this area' }), 'Hello{Enter}')

  expect(screen.getByTestId('bottom-sheet')).toHaveAttribute('data-snap', 'half')
})
