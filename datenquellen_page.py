"""
Streamlit-Seite "Datenquellen": Katalog aller freien Quellen, eine Quelle direkt ausprobieren (ohne LLM)
und Selbsttest aller Quellen. Ergebnisse landen wie beim Agenten in output/ergebnisse/<Zeit>_datenquelle_.../.
"""
import json
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import datenquellen
import geo_tools
import impact_tools


def _zeige_ergebnis(res):
    q = res["quelle"]
    st.success(f"{q['name']} · {q['anbieter']} · Stand {q.get('stand')} · {res.get('sekunden')} s")
    files = res.get("files") or {}
    karten = [p for p in files.values() if str(p).endswith(".geojson") and os.path.exists(p)]
    bilder = [p for p in files.values() if str(p).lower().endswith((".png", ".jpg", ".jpeg")) and os.path.exists(p)]
    if karten:
        components.html(geo_tools.map_html(karten), height=480)
    for b in bilder:
        st.image(b, caption=os.path.basename(b), width=520)
    st.json(res.get("zusammenfassung"), expanded=2)
    if files:
        st.caption("Dateien: " + ", ".join(os.path.basename(p) for p in files.values()) +
                   f" · Ordner {os.path.basename(geo_tools.run_dir())} (Seite Ergebnisse)")
    st.caption(f"Lizenz: {q['lizenz']} · {q.get('url', '')}")


def page():
    st.title("📚 Freie Datenquellen")
    st.caption(f"{len(datenquellen.QUELLEN)} Quellen ohne API-Key. Der Agent ruft sie mit dem Werkzeug "
               "datenquelle_abfragen auf, hier lassen sie sich direkt durchsehen und ausprobieren. "
               "Rasterdaten (Satellit, Landbedeckung, Wärmeinsel) liest GDAL aus der QGIS-Installation.")
    tab_kat, tab_test, tab_alle = st.tabs(["Katalog", "Ausprobieren", "Selbsttest"])

    with tab_kat:
        c1, c2 = st.columns([1, 2])
        kat = c1.selectbox("Kategorie", ["alle"] + datenquellen.KATEGORIEN)
        such = c2.text_input("Suche", placeholder="z.B. Lärm, Bäume, Unfall, Hitze")
        rows = datenquellen.katalog(None if kat == "alle" else kat, such or None)
        st.dataframe(pd.DataFrame([{
            "Kategorie": r["kategorie"], "ID": r["id"], "Name": r["name"], "Anbieter": r["anbieter"],
            "Lizenz": r["lizenz"], "Art": r["art"], "Parameter": ", ".join(r["parameter"]),
            "Beschreibung": r["beschreibung"], "Link": datenquellen.QUELLEN[r["id"]]["url"]} for r in rows]),
            hide_index=True, width="stretch", height=560, column_config={"Link": st.column_config.LinkColumn()})
        st.caption("Art: punkt = Wert am Ort, umkreis = Daten im Radius (Karte), global = ohne Ort, "
                   "suche = Kataloge und beliebige Dienste/Dateien.")

    with tab_test:
        ids = list(datenquellen.QUELLEN)
        qid = st.selectbox("Quelle", ids, format_func=lambda i: f"{datenquellen.QUELLEN[i]['name']}  ({i})")
        q = datenquellen.QUELLEN[qid]
        st.caption(q["beschreibung"])
        c1, c2 = st.columns([3, 1])
        ort = c1.text_input("Ort (Suche über geocode)", value="Luisenplatz, Darmstadt",
                            help="Adresse, Platz oder Kreuzung 'Straße A / Straße B, Stadt'")
        radius = c2.number_input("Radius (m)", min_value=10, max_value=int(q["max_radius"]), value=int(q["radius"]),
                                 step=50, disabled=q["art"] != "umkreis", key=f"radius_{qid}")
        par = st.text_area("Parameter (JSON)", value=json.dumps(datenquellen.TEST_PARAMETER.get(qid, {}), ensure_ascii=False),
                           key=f"par_{qid}", height=68,
                           help="\n".join(f"{k}: {v}" for k, v in q["parameter"].items()) or "Diese Quelle hat keine Parameter.")
        if q["parameter"]:
            st.caption("Parameter: " + " · ".join(f"**{k}**: {v}" for k, v in q["parameter"].items()))
        if st.button("Abfragen", type="primary"):
            try:
                lat = lon = None
                if q["art"] != "global" and ort.strip():
                    g = impact_tools.geocode(ort)
                    if not g:
                        raise ValueError(f"Ort '{ort}' nicht gefunden.")
                    lat, lon = g["lat"], g["lon"]
                geo_tools.new_run(f"datenquelle {qid}")
                with st.spinner(f"Frage {q['name']} ab ..."):
                    st.session_state.dq_result = datenquellen.abfragen(qid, lat, lon, radius, json.loads(par or "{}"))
            except Exception as err:
                st.session_state.dq_result = None
                st.error(f"{type(err).__name__}: {err}")
        if st.session_state.get("dq_result"):
            _zeige_ergebnis(st.session_state.dq_result)

    with tab_alle:
        st.write(f"Ruft alle {len(datenquellen.QUELLEN)} Quellen am Luisenplatz Darmstadt auf (6 gleichzeitig). "
                 "Dauert ca. 1-2 Minuten, beim allerersten Mal länger (Unfallatlas, KOSTRA, Klimaraster werden geladen).")
        if st.button("Selbsttest starten"):
            with st.spinner("Teste alle Datenquellen ..."):
                st.session_state.dq_selbsttest = datenquellen.selbsttest()
        res = st.session_state.get("dq_selbsttest")
        if res:
            ok = sum(r["ok"] for r in res)
            (st.success if ok == len(res) else st.warning)(f"{ok} von {len(res)} Quellen funktionieren.")
            st.dataframe(pd.DataFrame([{"": "✅" if r["ok"] else "❌", "Quelle": r["quelle"], "Sekunden": r["sekunden"],
                                        "Ergebnis / Fehler": r["info"]} for r in res]),
                         hide_index=True, width="stretch", height=600)
