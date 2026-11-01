import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

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

const PALETTE = ["#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4"];

export default function MapView({ layers }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const addedRef = useRef(new Set());
  const colorIdx = useRef(0);
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

  // Sync layer descriptors onto the map whenever the list changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      for (const layer of layers) {
        if (addedRef.current.has(layer.id)) continue;
        addedRef.current.add(layer.id);
        const color = PALETTE[colorIdx.current++ % PALETTE.length];

        if (layer.kind === "wms-raster") {
          map.addSource(layer.id, { type: "raster", tiles: [layer.tile_url], tileSize: 256 });
          map.addLayer({ id: layer.id, type: "raster", source: layer.id, paint: { "raster-opacity": 0.75 } });
          continue;
        }

        // GeoJSON vector layer.
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

        if (layer.bounds) {
          const [minx, miny, maxx, maxy] = layer.bounds;
          map.fitBounds([[minx, miny], [maxx, maxy]], { padding: 60, maxZoom: 15, duration: 800 });
        }
      }
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [layers]);

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
