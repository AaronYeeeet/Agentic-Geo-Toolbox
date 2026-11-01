// Map overlay: all layers of the open chat, toggle visibility, zoom, delete.
import { useState } from "react";
import { colorFor } from "./colors";

export default function LayerPanel({ layers, onToggle, onZoom, onDelete }) {
  const [collapsed, setCollapsed] = useState(false);
  if (layers.length === 0) return null;
  const visible = layers.filter((l) => l.visible !== false).length;

  return (
    <div className="layer-panel">
      <button className="layer-head" onClick={() => setCollapsed(!collapsed)}>
        <strong>Layer</strong>
        <span className="step-meta">{visible}/{layers.length} sichtbar {collapsed ? "▸" : "▾"}</span>
      </button>
      {!collapsed && (
        <div className="layer-list">
          {layers.map((l) => (
            <div key={l.id} className={`layer-row${l.visible === false ? " hidden" : ""}`}>
              <input type="checkbox" checked={l.visible !== false}
                onChange={() => onToggle(l.id, l.visible === false)} title="ein-/ausblenden" />
              {l.kind === "wms-raster"
                ? <span className="swatch raster" title="WMS-Rasterbild" />
                : <span className={`swatch ${l.geometry_type}`} style={{ background: colorFor(l.id) }} />}
              <span className="layer-name" title={`${l.name} · ${l.id} · Quelle: ${l.source}`}>{l.name}</span>
              <span className="step-meta" title={l.loadError || ""}>
                {l.loadError ? "⚠️"
                  : l.kind === "wms-raster" ? "WMS"
                    : l.visible !== false && !l.geojson ? <span className="spinner" />
                      : l.feature_count}
              </span>
              <button title="Hinzoomen" disabled={!l.bounds} onClick={() => onZoom(l.id)}>⌖</button>
              <button title="Löschen" onClick={() => {
                if (confirm(`Layer „${l.name}“ löschen?`)) onDelete(l.id);
              }}>✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
