import { describe, expect, test } from 'vitest'
import { detectLatLon, MAX_UPLOAD_BYTES, parseUpload, UploadError } from './parse'

const file = (name: string, text: string) => new File([text], name)

async function expectUploadError(promise: Promise<unknown>, key: string) {
  await expect(promise).rejects.toBeInstanceOf(UploadError)
  await expect(promise).rejects.toMatchObject({ key })
}

describe('detectLatLon', () => {
  test.each([
    [['name', 'lat', 'lon'], { lat: 'lat', lon: 'lon' }],
    [['Latitude', 'Longitude'], { lat: 'Latitude', lon: 'Longitude' }],
    [['Name', 'Breite', 'Länge'], { lat: 'Breite', lon: 'Länge' }],
    [['id', 'y', 'x'], { lat: 'y', lon: 'x' }],
    [['lng', 'lat'], { lat: 'lat', lon: 'lng' }],
  ])('%j', (headers, expected) => {
    expect(detectLatLon(headers)).toEqual(expected)
  })

  test('returns null without coordinate columns', () => {
    expect(detectLatLon(['name', 'address'])).toBeNull()
  })
})

describe('parseUpload', () => {
  test('GeoJSON FeatureCollection, Feature and bare geometry', async () => {
    const fc = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [8.65, 49.87] }, properties: { name: 'A' } }] }
    const fromFc = await parseUpload(file('parks.geojson', JSON.stringify(fc)))
    expect(fromFc).toMatchObject({ format: 'GeoJSON', featureCount: 1, geometryTypes: ['Point'] })
    expect(fromFc.bbox).toEqual([8.65, 49.87, 8.65, 49.87])

    const fromFeature = await parseUpload(file('one.json', JSON.stringify(fc.features[0])))
    expect(fromFeature.featureCount).toBe(1)

    const fromGeometry = await parseUpload(file('poly.geojson', JSON.stringify({ type: 'Polygon', coordinates: [[[8.6, 49.8], [8.7, 49.8], [8.7, 49.9], [8.6, 49.8]]] })))
    expect(fromGeometry.geometryTypes).toEqual(['Polygon'])
  })

  test('CSV with lat/lon columns', async () => {
    const parsed = await parseUpload(file('stations.csv', 'name,lat,lon\nA,49.87,8.65\nB,49.88,8.66\n'))

    expect(parsed).toMatchObject({ format: 'CSV', featureCount: 2, geometryTypes: ['Point'] })
    expect(parsed.featureCollection.features[0].properties).toEqual({ name: 'A' })
    expect(parsed.featureCollection.features[1].geometry).toEqual({ type: 'Point', coordinates: [8.66, 49.88] })
  })

  test('German Excel CSV: semicolons, decimal commas, Breite/Länge', async () => {
    const parsed = await parseUpload(file('Ladepunkte.csv', 'Name;Breite;Länge;Leistung\nIGD;49,87425;8,65989;22\nLuisenplatz;49,8728;8,6512;50\n'))

    expect(parsed.featureCount).toBe(2)
    expect(parsed.featureCollection.features[0].geometry).toEqual({ type: 'Point', coordinates: [8.65989, 49.87425] })
    expect(parsed.featureCollection.features[0].properties).toEqual({ Name: 'IGD', Leistung: '22' })
  })

  test('German Excel CSV saved in Windows-1252 (Excel\'s default) is read correctly', async () => {
    const text = 'Name;Breite;Länge\nIGD;49,87425;8,65989\n'
    const cp1252 = Uint8Array.from([...text].map((c) => c.charCodeAt(0)))

    const parsed = await parseUpload(new File([cp1252], 'ladepunkte.csv'))

    expect(parsed.featureCount).toBe(1)
    expect(parsed.featureCollection.features[0].properties).toEqual({ Name: 'IGD' })
  })

  test('projected coordinates (e.g. EPSG:25832 from QGIS) are rejected with a hint to export WGS84', async () => {
    const utm = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [475600, 5524600] }, properties: {} }] }
    await expectUploadError(parseUpload(file('utm.geojson', JSON.stringify(utm))), 'upload.errors.projected')
    await expectUploadError(parseUpload(file('utm.csv', 'name,x,y\nA,475600,5524600\n')), 'upload.errors.projected')
  })

  test('KML multi-part placemarks (MultiGeometry) are kept, one feature per part', async () => {
    const ring = (x: number) => `<Polygon><outerBoundaryIs><LinearRing><coordinates>${x},49.80 ${x + 0.01},49.80 ${x + 0.01},49.81 ${x},49.80</coordinates></LinearRing></outerBoundaryIs></Polygon>`
    const kml = `<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>Exklave</name><MultiGeometry>${ring(8.6)}${ring(8.7)}</MultiGeometry></Placemark></Document></kml>`

    const parsed = await parseUpload(file('gemeinde.kml', kml))

    expect(parsed).toMatchObject({ featureCount: 2, geometryTypes: ['Polygon'] })
    expect(parsed.featureCollection.features.map((f) => f.properties?.name)).toEqual(['Exklave', 'Exklave'])
  })

  test('CSV without coordinate columns explains how to name them', async () => {
    await expectUploadError(parseUpload(file('addresses.csv', 'name,street\nA,Main St\n')), 'upload.errors.noCoordinates')
  })

  test('KML and GPX', async () => {
    const kml = '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>IGD</name><Point><coordinates>8.65989,49.87425,0</coordinates></Point></Placemark></Document></kml>'
    expect(await parseUpload(file('places.kml', kml))).toMatchObject({ format: 'KML', featureCount: 1, geometryTypes: ['Point'] })

    const gpx = '<?xml version="1.0"?><gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Walk</name><trkseg><trkpt lat="49.87" lon="8.65"></trkpt><trkpt lat="49.88" lon="8.66"></trkpt></trkseg></trk></gpx>'
    expect(await parseUpload(file('walk.gpx', gpx))).toMatchObject({ format: 'GPX', featureCount: 1, geometryTypes: ['LineString'] })
  })

  test('rejects files over 10 MB, unsupported formats, invalid JSON and empty data', async () => {
    const big = file('big.geojson', '{}')
    Object.defineProperty(big, 'size', { value: MAX_UPLOAD_BYTES + 1 })
    await expectUploadError(parseUpload(big), 'upload.errors.tooLarge')
    await expectUploadError(parseUpload(file('data.shp', 'x')), 'upload.errors.unsupported')
    await expectUploadError(parseUpload(file('broken.geojson', '{"type": "Feature"')), 'upload.errors.invalid')
    await expectUploadError(parseUpload(file('empty.geojson', '{"type":"FeatureCollection","features":[]}')), 'upload.errors.empty')
    await expectUploadError(parseUpload(file('empty.kml', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')), 'upload.errors.empty')
  })
})
