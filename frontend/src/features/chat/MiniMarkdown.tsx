import { Fragment, type ReactNode } from 'react'

/** `**bold**` inside a line; an unfinished marker (still streaming) stays plain text. */
function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  const pattern = /\*\*([^*]+)\*\*/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push(text.slice(last, match.index))
    parts.push(<strong key={match.index} className="font-semibold text-ink">{match[1]}</strong>)
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

/**
 * The light Markdown the agent emits: paragraphs, `- ` bullet lines and bold. Rendered as React
 * elements, never as HTML, so text from the stream cannot inject markup.
 */
export function MiniMarkdown({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/)
  return (
    <>
      {blocks.map((block, index) => {
        const lines = block.split('\n')
        const items = lines.filter((line) => line.startsWith('- '))
        const prose = lines.filter((line) => !line.startsWith('- '))
        return (
          <Fragment key={index}>
            {prose.length > 0 && prose.some(Boolean) && (
              <p className="whitespace-pre-line">
                {prose.map((line, i) => (
                  <Fragment key={i}>
                    {i > 0 && '\n'}
                    {inline(line)}
                  </Fragment>
                ))}
              </p>
            )}
            {items.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-5 marker:text-ink-3">
                {items.map((line, i) => (
                  <li key={i}>{inline(line.slice(2))}</li>
                ))}
              </ul>
            )}
          </Fragment>
        )
      })}
    </>
  )
}
