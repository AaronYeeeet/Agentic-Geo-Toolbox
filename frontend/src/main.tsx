import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import './index.css'
import './i18n'
import { executeMapAction } from './map/actions'
import { setMapActionHandler } from './store/chatStore'
import App from './App'

// MapLibre v6 in a bundler: point it at the worker once, before any map is created.
setWorkerUrl(workerUrl)
// Map actions from the agent stream are executed on the map.
setMapActionHandler(executeMapAction)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
