import { create } from 'zustand'

export interface Notice {
  id: number
  kind: 'info' | 'error'
  text: string
}

interface NoticeState {
  notices: Notice[]
  push: (kind: Notice['kind'], text: string, timeoutMs?: number) => void
  dismiss: (id: number) => void
}

let nextId = 1

/** Short-lived messages (upload added, upload failed). Errors stay longer than confirmations. */
export const useNoticeStore = create<NoticeState>()((set, get) => ({
  notices: [],
  push: (kind, text, timeoutMs = kind === 'error' ? 9000 : 4000) => {
    const id = nextId++
    set({ notices: [...get().notices.slice(-2), { id, kind, text }] })
    setTimeout(() => get().dismiss(id), timeoutMs)
  },
  dismiss: (id) => set({ notices: get().notices.filter((n) => n.id !== id) }),
}))
