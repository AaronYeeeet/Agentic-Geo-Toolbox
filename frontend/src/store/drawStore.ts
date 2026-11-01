import { create } from 'zustand'

export type DrawTool = 'rectangle' | 'polygon' | 'feature'

interface DrawState {
  /** The active selection tool, or null when the map is in normal navigation. */
  tool: DrawTool | null
  setTool: (tool: DrawTool | null) => void
}

export const useDrawStore = create<DrawState>()((set) => ({
  tool: null,
  setTool: (tool) => set({ tool }),
}))
