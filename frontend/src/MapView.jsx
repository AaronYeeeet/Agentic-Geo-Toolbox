import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { colorFor } from "./colors";

// Self-contained base style using OpenStreetMap raster tiles (no API key needed).
const BASE_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

function fitTo(map, boundsList) {
  const valid = boundsList.filter(Boolean);
  if (!valid.length) return;
  const [minx, miny, maxx, maxy] = valid.reduce((a, b) => [
    Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]);
  map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, maxZoom: 15, duration: 800 });
}

// layers: descriptors of the open chat (with `visible`).
// focus: { ids: [...], nonce } — zoom to these layers whenever nonce changes.
export default function MapView({ layers, focus }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const addedRef = useRef(new Set());
  const loadedRef = useRef(false);
  const [glError, setGlError] = useState(null);

  // Initialise the map once. WebGL may be unavailable (hardware acceleration
  // disabled, headless/VM, etc.) — catch it so the rest of the UI keeps working.
  useEffect(() => {
    let map;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: BASE_STYLE,
        center: [8.65, 49.87], // Darmstadt, Hessen
        zoom: 10,
      });
      map.on("error", (e) => console.warn("MapLibre error:", e?.error || e));
      map.once("load", () => { loadedRef.current = true; });
      map.addControl(new maplibregl.NavigationControl(), "top-right");
      mapRef.current = map;
    } catch (err) {
      console.error("Map init failed (WebGL unavailable?):", err);
      setGlError(err);
    }
    return () => {
      if (map) map.remove();
    };
  }, []);

  // Run `fn` now if the map has loaded, otherwise once it has. (Not
  // isStyleLoaded(): that is false while a GeoJSON source is still parsing,
  // and "load" fires only once, so the change would be lost.)
  const whenReady = (fn) => {
    const map = mapRef.current;
    if (!map) return;
    if (loadedRef.current) fn(map);
    else map.once("load", () => fn(map));
  };

  // Sync layer descriptors onto the map: add new, remove deleted, apply visibility.
  useEffect(() => {
    whenReady((map) => {
      const wanted = new Set(layers.map((l) => l.id));
      for (const id of [...addedRef.current]) {
        if (wanted.has(id)) continue;
        if (map.getLayer(id)) map.removeLayer(id);
        if (map.getSource(id)) map.removeSource(id);
        addedRef.current.delete(id);
      }

      for (const layer of layers) {
        if (layer.kind !== "wms-raster" && !layer.geojson) continue; // geometry still loading
        if (!addedRef.current.has(layer.id)) {
          addedRef.current.add(layer.id);
          const color = colorFor(layer.id);
          if (layer.kind === "wms-raster") {
            map.addSource(layer.id, { type: "raster", tiles: [layer.tile_url], tileSize: 256 });
            map.addLayer({ id: layer.id, type: "raster", source: layer.id, paint: { "raster-opacity": 0.75 } });
          } else {
            map.addSource(layer.id, { type: "geojson", data: layer.geojson });
            if (layer.geometry_type === "polygon") {
              map.addLayer({ id: layer.id, type: "fill", source: layer.id,
                paint: { "fill-color": color, "fill-opacity": 0.35, "fill-outline-color": color } });
            } else if (layer.geometry_type === "line") {
              map.addLayer({ id: layer.id, type: "line", source: layer.id,
                paint: { "line-color": color, "line-width": 2.5 } });
            } else {
              map.addLayer({ id: layer.id, type: "circle", source: layer.id,
                paint: { "circle-color": color, "circle-radius": 5, "circle-stroke-width": 1,
                  "circle-stroke-color": "#fff" } });
            }
          }
        }
        map.setLayoutProperty(layer.id, "visibility", layer.visible === false ? "none" : "visible");
      }
    });
  }, [layers]);

  useEffect(() => {
    if (!focus) return;
    whenReady((map) => {
      fitTo(map, layers.filter((l) => focus.ids.includes(l.id)).map((l) => l.bounds));
    });
  }, [focus?.nonce]);

  if (glError) {
    return (
      <div className="map map-fallback">
        <div>
          <h2>🗺️ Karte nicht verfügbar</h2>
          <p>
            Der Browser konnte kein <strong>WebGL</strong> initialisieren, das MapLibre GL
            benötigt. Chat und Datenverarbeitung funktionieren trotzdem.
          </p>
          <p>
            Aktiviere die Hardware-Beschleunigung im Browser (siehe <code>chrome://gpu</code>)
            und lade neu.
          </p>
        </div>
      </div>
    );
  }

  return <div ref={containerRef} className="map" />;
}
