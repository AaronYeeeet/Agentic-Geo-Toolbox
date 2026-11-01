import i18n from '@/i18n'
import { fitToBBox } from '@/map/camera'
import { useLayerStore } from '@/store/layerStore'
import { useNoticeStore } from '@/store/noticeStore'
import { parseUpload, UploadError } from './parse'

/** Distinct, saturated colours that read on vector basemaps and aerial imagery alike. */
const UPLOAD_COLORS = ['#0f766e', '#b45309', '#6d28d9', '#be123c', '#0369a1', '#4d7c0f']

/** Parses each file, adds it as a "My data" layer (and thereby as chat context) and zooms to it. */
export async function addUploads(files: File[]): Promise<void> {
  const notify = useNoticeStore.getState().push
  for (const file of files) {
    try {
      const parsed = await parseUpload(file)
      const { overlays, addOverlay } = useLayerStore.getState()
      const index = overlays.filter((o) => o.group === 'mydata').length
      addOverlay({
        id: `upload-${Date.now().toString(36)}-${index}`,
        group: 'mydata',
        kind: 'geojson',
        title: parsed.name,
        visible: true,
        opacity: 1,
        color: UPLOAD_COLORS[index % UPLOAD_COLORS.length],
        removable: true,
        data: parsed.featureCollection,
        bbox: parsed.bbox,
        featureCount: parsed.featureCount,
        geometryTypes: parsed.geometryTypes,
        upload: { format: parsed.format, sampleProperties: parsed.sampleProperties },
      })
      fitToBBox(parsed.bbox, 16)
      notify('info', i18n.t('upload.added', { name: parsed.name, count: parsed.featureCount }))
    } catch (error) {
      const text =
        error instanceof UploadError
          ? i18n.t(error.key, error.params)
          : i18n.t('upload.errors.invalid', { name: file.name, format: 'GeoJSON, CSV, KML, GPX' })
      notify('error', text)
    }
  }
}
