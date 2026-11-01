import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { zustandStorage } from '@/lib/storage'

export type SheetSnap = 'peek' | 'half' | 'full'

/** Chat dock sizes in percent of the window width (min 320 px, max 70 %, expanded about 60 %). */
export const CHAT_DEFAULT_SIZE = 30
export const CHAT_EXPANDED_SIZE = 60
export const CHAT_MAX_SIZE = 70
export const CHAT_MIN_PX = 320

interface UiState {
  chatOpen: boolean
  chatSize: number
  chatExpanded: boolean
  sheetSnap: SheetSnap
  layerPanelOpen: boolean
  setChatOpen: (open: boolean) => void
  setChatSize: (size: number) => void
  setChatExpanded: (expanded: boolean) => void
  setSheetSnap: (snap: SheetSnap) => void
  setLayerPanelOpen: (open: boolean) => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      chatOpen: true,
      chatSize: CHAT_DEFAULT_SIZE,
      chatExpanded: false,
      sheetSnap: 'peek',
      layerPanelOpen: false,
      setChatOpen: (chatOpen) => set({ chatOpen }),
      setChatSize: (chatSize) => set({ chatSize }),
      setChatExpanded: (chatExpanded) => set({ chatExpanded }),
      setSheetSnap: (sheetSnap) => set({ sheetSnap }),
      setLayerPanelOpen: (layerPanelOpen) => set({ layerPanelOpen }),
    }),
    {
      name: 'geo-toolbox.ui',
      storage: createJSONStorage(() => zustandStorage),
      partialize: ({ chatOpen, chatSize, chatExpanded }) => ({ chatOpen, chatSize, chatExpanded }),
    },
  ),
)
