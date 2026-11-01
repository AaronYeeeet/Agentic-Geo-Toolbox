import { ArrowUp, FileText, Paperclip, Square, X } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { SelectionChip } from '@/features/draw/SelectionChip'
import { addUploads } from '@/features/uploads/addUploads'
import { UPLOAD_ACCEPT } from '@/features/uploads/parse'
import { useChatStore } from '@/store/chatStore'
import { useLayerStore } from '@/store/layerStore'
import { useSelectionStore } from '@/store/selectionStore'

/** Removable context chips: the selection and every upload still in the context. */
function ContextChips() {
  const { t } = useTranslation()
  const selection = useSelectionStore((s) => s.selection)
  const excluded = useChatStore((s) => s.excludedUploads)
  const exclude = useChatStore((s) => s.excludeUpload)
  const uploads = useLayerStore((s) => s.overlays).filter((o) => o.group === 'mydata' && !excluded.includes(o.id))
  if (!selection && uploads.length === 0) return null
  return (
    <div role="group" aria-label={t('chat.context')} className="mb-2 flex flex-wrap gap-1.5">
      <SelectionChip />
      {uploads.map((upload) => {
        const text = t('chat.upload', { name: upload.title, count: upload.featureCount ?? 0 })
        return (
          <span key={upload.id} className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-md border border-rule bg-fog pr-1 pl-2 text-[12.5px] font-medium text-ink">
            <FileText className="size-3.5 shrink-0" style={{ color: upload.color }} aria-hidden />
            <span className="truncate">{text}</span>
            <button
              type="button"
              aria-label={t('chat.removeContext', { name: text })}
              onClick={() => exclude(upload.id)}
              className="grid size-5 shrink-0 place-items-center rounded text-ink-3 hover:bg-white hover:text-ink"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </span>
        )
      })}
    </div>
  )
}

/** Question input: Enter sends, Shift+Enter adds a line, Stop while streaming, paperclip for uploads. */
export function Composer({ onSent }: { onSent?: () => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const streaming = useChatStore((s) => s.streaming)
  const send = useChatStore((s) => s.send)
  const stop = useChatStore((s) => s.stop)
  const input = useRef<HTMLTextAreaElement>(null)
  const files = useRef<HTMLInputElement>(null)

  useLayoutEffect(() => {
    const el = input.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 148)}px`
  }, [text])

  const submit = () => {
    const question = text.trim()
    if (!question || streaming) return
    setText('')
    void send(question)
    onSent?.()
  }

  return (
    <div className="border-t border-rule bg-paper px-3 pt-2.5 pb-3" data-testid="composer">
      <ContextChips />
      <div className="rounded-xl border border-rule bg-paper transition-colors focus-within:border-water/60 focus-within:ring-3 focus-within:ring-water/10">
        <textarea
          ref={input}
          rows={1}
          value={text}
          aria-label={t('chat.placeholder')}
          placeholder={t('chat.placeholder')}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              submit()
            }
          }}
          className="block max-h-37 w-full resize-none bg-transparent px-3 pt-2.5 pb-1 text-[14.5px] leading-snug text-ink outline-none placeholder:text-ink-3"
        />
        <div className="flex items-center justify-between px-1.5 pb-1.5">
          <button
            type="button"
            aria-label={t('upload.attach')}
            title={t('upload.attach')}
            onClick={() => files.current?.click()}
            className="grid size-8 place-items-center rounded-lg text-ink-3 hover:bg-fog hover:text-ink"
          >
            <Paperclip className="size-[18px]" aria-hidden />
          </button>
          <input
            ref={files}
            type="file"
            multiple
            hidden
            accept={UPLOAD_ACCEPT}
            onChange={(event) => {
              void addUploads(Array.from(event.target.files ?? []))
              event.target.value = ''
            }}
            data-testid="upload-input"
          />
          {streaming ? (
            <button
              type="button"
              aria-label={t('chat.stop')}
              onClick={stop}
              className="grid size-8 place-items-center rounded-lg bg-ink text-white hover:bg-ink-2"
            >
              <Square className="size-3.5 fill-current" aria-hidden />
            </button>
          ) : (
            <button
              type="button"
              aria-label={t('chat.send')}
              disabled={!text.trim()}
              onClick={submit}
              className="grid size-8 place-items-center rounded-lg bg-water text-white transition-colors hover:bg-water-ink disabled:bg-fog-2 disabled:text-ink-3"
            >
              <ArrowUp className="size-[18px]" aria-hidden />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
