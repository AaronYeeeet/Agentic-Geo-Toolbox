"""
Streamlit-Seite "Ergebnisse": alle Ergebnisordner durchblättern, Karten ansehen, GeoJSON-Ebenen
frei kombinieren, Dateien herunterladen oder im Explorer / in QGIS öffnen.
Wird von app.py eingebunden (Navigation links).
"""
import json
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import geo_tools

MAP_EXT = (".html",)
LAYER_EXT = (".geojson",)
OTHER_EXT = (".gpkg", ".csv", ".json", ".tif", ".tiff", ".shp")


def _folders():
    """Ergebnisordner, neueste zuerst."""
    root = geo_tools.RESULTS_DIR
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, d) for d in sorted(os.listdir(root), reverse=True)
            if os.path.isdir(os.path.join(root, d))]


def _title(folder):
    """'2026-11-01 11:39 · Was passiert bei Starkregen ...' aus frage.md bzw. Ordnernamen."""
    name = os.path.basename(folder)
    when = f"{name[:10]} {name[11:13]}:{name[14:16]}" if name[:4].isdigit() and len(name) > 16 else ""
    md = os.path.join(folder, "frage.md")
    if os.path.exists(md):
        with open(md, encoding="utf-8") as f:
            first = f.readline().lstrip("# ").strip()
        return f"{when} · {first[:90]}" if when else first[:90]
    return f"{when} · {name[20:]}" if when else name


def _open(path):
    """Datei/Ordner mit dem Standardprogramm öffnen (Windows: Explorer, QGIS für .gpkg/.geojson, falls verknüpft)."""
    try:
        os.startfile(path)  # nur Windows, läuft auf dem eigenen Rechner
    except Exception as err:
        st.error(f"Konnte nicht öffnen: {err}")


def _feature_table(path):
    with open(path, encoding="utf-8") as f:
        feats = json.load(f).get("features", [])
    rows = [{k: v for k, v in (ft.get("properties") or {}).items() if not k.startswith("_")} for ft in feats]
    return len(feats), pd.DataFrame(rows)


def page():
    st.title("🗂️ Ergebnisse")
    folders = _folders()
    if not folders:
        st.info("Noch keine Ergebnisse. Stell im Chat eine Frage, dann erscheint hier ein Ordner pro Frage.")
        return
    st.caption(f"Ordner: `{geo_tools.RESULTS_DIR}` · ein Unterordner pro Frage")

    labels = {f: _title(f) for f in folders}
    folder = st.selectbox("Frage / Ergebnisordner", folders, format_func=labels.get)
    files = sorted(os.listdir(folder))
    maps = [f for f in files if f.lower().endswith(MAP_EXT)]
    layers = [f for f in files if f.lower().endswith(LAYER_EXT)]
    others = [f for f in files if f.lower().endswith(OTHER_EXT)]

    c1, c2 = st.columns([1, 4])
    if c1.button("📂 Ordner öffnen"):
        _open(folder)
    c2.caption(f"{len(maps)} Karten · {len(layers)} GeoJSON · {len(others)} weitere Dateien")

    md = os.path.join(folder, "frage.md")
    if os.path.exists(md):
        with st.expander("Frage, Antwort und Werkzeuge", expanded=False):
            with open(md, encoding="utf-8") as f:
                st.markdown(f.read())

    tab_map, tab_layers, tab_files = st.tabs(["🗺️ Karten", "🧩 Ebenen kombinieren", "📄 Dateien"])

    with tab_map:
        if not maps:
            st.info("In diesem Ordner gibt es keine fertige Karte. Unter 'Ebenen kombinieren' lässt sich eine bauen.")
        else:
            chosen = st.radio("Karte", maps, horizontal=True, label_visibility="collapsed")
            path = os.path.join(folder, chosen)
            with open(path, encoding="utf-8") as f:
                html = f.read()
            components.html(html, height=620)
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ Karte herunterladen", html, file_name=chosen, mime="text/html")
            if d2.button("🌐 Im Standard-Browser öffnen", key="open_map"):
                _open(path)

    with tab_layers:
        if not layers:
            st.info("Keine GeoJSON-Dateien in diesem Ordner.")
        else:
            st.caption("Ebenen auswählen; die erste wird zuunterst gezeichnet. Klick auf ein Objekt zeigt Details.")
            chosen = st.multiselect("Ebenen", layers, default=layers[:6])
            if chosen:
                components.html(geo_tools.map_html([os.path.join(folder, f) for f in chosen]), height=620)
            pick = st.selectbox("Attribute anzeigen", ["–"] + layers)
            if pick != "–":
                n, df = _feature_table(os.path.join(folder, pick))
                st.caption(f"{n} Objekte")
                st.dataframe(df, width="stretch", height=300)

    with tab_files:
        for name in files:
            path = os.path.join(folder, name)
            col1, col2, col3 = st.columns([5, 1, 1])
            col1.markdown(f"`{name}` · {os.path.getsize(path) / 1024:.0f} KB")
            with open(path, "rb") as f:
                col2.download_button("⬇️", f.read(), file_name=name, key=f"dl_{name}")
            if col3.button("Öffnen", key=f"open_{name}", help="Mit dem Standardprogramm öffnen (z.B. QGIS)"):
                _open(path)
