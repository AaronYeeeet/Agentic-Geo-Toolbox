import { type DragEvent, useEffect, useRef, useState } from 'react'
import { addUploads } from './addUploads'

const hasFiles = (event: { dataTransfer?: DataTransfer | null }) =>
  Array.from(event.dataTransfer?.types ?? []).includes('Files')

/** Drag-and-drop of files onto the map. Returns the drop handlers and state. */
export function useFileDrop() {
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0)

  // Outside the app root a dropped file would make the browser open it and lose the session.
  useEffect(() => {
    const guard = (event: globalThis.DragEvent) => {
      if (hasFiles(event)) event.preventDefault()
    }
    window.addEventListener('dragover', guard)
    window.addEventListener('drop', guard)
    return () => {
      window.removeEventListener('dragover', guard)
      window.removeEventListener('drop', guard)
    }
  }, [])

  const handlers = {
    onDragEnter: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      depth.current += 1
      setDragging(true)
    },
    onDragOver: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
    },
    onDragLeave: () => {
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) setDragging(false)
    },
    onDrop: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      depth.current = 0
      setDragging(false)
      void addUploads(Array.from(event.dataTransfer.files))
    },
  }
  return { dragging, handlers }
}
