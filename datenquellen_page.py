"""
Streamlit-Seite "Datenquellen":
  - Doku: alle freien Quellen gruppiert (Thema, Anbieter, Anbindung oder Art) mit Links, Dienst-Adressen,
    Parametern, Aufrufbeispielen (Agent, Python, Kommandozeile) und einer echten Beispielantwort,
  - Ausprobieren: eine Quelle an einem beliebigen Ort abfragen (ohne LLM, mit Karte),
  - Selbsttest: alle Quellen aufrufen; speichert die Antworten als Beispiele für die Doku.
Ergebnisse landen wie beim Agenten in output/ergebnisse/<Zeit>_datenquelle_.../.
"""
import json
import os
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import datenquellen as dq
import datenquellen_alle_page
import datenquellen_doku as doku
import geo_tools
import impact_tools

def _badge(farbe, text):
    return f":{farbe}-badge[{str(text).replace('[', '(').replace(']', ')')}]"


# =====================================================================================================
# Doku
# =====================================================================================================
def _intro():
    n = len(dq.QUELLEN)
    bsp = dq.beispiele()
    karten = sum(bool((b.get("antwort") or {}).get("files")) for b in bsp.values())
    ok = sum("antwort" in b and not b.get("letzter_fehler") for b in bsp.values())
    with st.container(horizontal=True):
        st.metric("Datenquellen", n, border=True)
        st.metric("Themen", len(dq.KATEGORIEN), border=True)
        st.metric("liefern Kartendaten", karten, border=True, help="GeoJSON oder Bild im Beispiel am Luisenplatz")
        st.metric("im letzten Test erreichbar", f"{ok} / {n}", border=True,
                  help="Stand der gespeicherten Beispiele, neu prüfen im Tab Selbsttest")

    with st.expander("So funktioniert ein Aufruf (für alle Quellen gleich)", icon=":material/info:"):
        links, rechts = st.columns(2, gap="medium")
        with links:
            st.markdown("**Aufruf:** Der Agent nutzt **ein** Werkzeug für alle Quellen, `datenquelle_abfragen`. "
                        "Den Ort bestimmt er vorher mit `geocode`.")
            st.code(json.dumps({"quelle": "hlnug_laerm", "lat": 49.8728, "lon": 8.6512}, indent=2), language="json")
            st.markdown("| Argument | Bedeutung |\n|---|---|\n"
                        "| `quelle` | ID aus dieser Liste (Pflicht) |\n"
                        "| `lat`, `lon` | Ort in WGS84, bei Punkt- und Umkreis-Quellen Pflicht |\n"
                        "| `radius_m` | nur bei Umkreis-Quellen, sonst ignoriert; wird auf das Maximum begrenzt |\n"
                        "| `parameter` | quellenspezifisch, siehe jeweilige Quelle |")
            st.markdown("**Arten:** " + " · ".join(f"{s} **{name}**: {text}" for s, name, text in doku.ART_INFO.values()))
        with rechts:
            st.markdown("**Antwort:** bei allen Quellen gleich aufgebaut.")
            st.code('{\n'
                    '  "quelle": {"id", "name", "anbieter", "lizenz", "url", "stand"},\n'
                    '  "radius_m": 500,          // nur bei Umkreis-Quellen\n'
                    '  "zusammenfassung": {...}, // die Daten, kompakt für das LLM\n'
                    '  "files": {"name": "….geojson"},  // Karte für make_map / QGIS\n'
                    '  "sekunden": 1.2\n'
                    '}', language="js")
            st.markdown("- `files`: GeoJSON in EPSG:4326 im Ergebnisordner der Frage, mit Farben und Popups. "
                        "Rasterdaten kommen als eingefärbte Kacheln (höchstens 60 × 60), Luftbilder als JPG.\n"
                        "- `stand`: Datum der Daten (z.B. Messzeitpunkt, Satellitenszene, Kartierjahr).\n"
                        "- Unter jeder Antwort im Chat zeigt die App die genutzten Quellen mit Lizenz und Link.\n"
                        "- **Ohne Agent:** in Python `datenquellen.abfragen(...)`, auf der Kommandozeile "
                        "`datenquellen.py test <quelle>` oder hier im Tab *Ausprobieren*.")


def _uebersicht(gruppen, gruppierung):
    """Kacheln je Gruppe mit Sprunglink."""
    cols = st.columns(3)
    for i, (g, ids) in enumerate(gruppen.items()):
        symbol, info = doku.gruppen_info(gruppierung, g)
        with cols[i % 3].container(border=True, height="stretch"):
            st.markdown(f"**[{symbol} {g}](#{doku.slug(g)})** &nbsp;{_badge('gray', len(ids))}")
            st.caption(info or ", ".join(dq.QUELLEN[q]["name"] for q in ids))


# Gleiche Spaltenbreiten in allen Gruppen-Tabellen, lange IDs dürfen umbrechen
TABELLE_CSS = """<style>
[class*="st-key-dokutab_"] table { table-layout: fixed; width: 100%; }
[class*="st-key-dokutab_"] th:nth-child(1) { width: 20%; }
[class*="st-key-dokutab_"] th:nth-child(2) { width: 15%; }
[class*="st-key-dokutab_"] th:nth-child(3) { width: 22%; }
[class*="st-key-dokutab_"] th:nth-child(4) { width: 23%; }
[class*="st-key-dokutab_"] th:nth-child(5) { width: 8%; }
[class*="st-key-dokutab_"] th:nth-child(6) { width: 12%; }
[class*="st-key-dokutab_"] td code { word-break: break-all; }
</style>"""


def _tabelle(gruppe, ids):
    """Kompakte Tabelle einer Gruppe: eine Zeile je Quelle, ohne eigene Scrollleiste, Text bricht um."""
    zeilen = []
    for qid in ids:
        q = dq.QUELLEN[qid]
        kurz, worte = dq.kurzinfo(qid)
        symbol, art_name, _ = doku.ART_INFO[q["art"]]
        anbieter = doku.anbieter_kurz(q["anbieter"])
        zeilen.append({
            "Quelle": f"**{q['name']}**",
            "ID": f"`{qid}`",
            "Beschreibung": kurz,
            "Wofür / liefert": " ".join(_badge("gray", w) for w in worte),
            "Art": f"{symbol} {art_name}",
            "Anbieter": f"[{anbieter}]({q['url']})" if q["url"] else anbieter,
        })
    with st.container(key=f"dokutab_{doku.slug(gruppe)}"):
        st.table(pd.DataFrame(zeilen), hide_index=True, border="horizontal")


def _quelle_doku(qid, bsp, offen=False):
    q = dq.QUELLEN[qid]
    symbol, art_name, art_text = doku.ART_INFO[q["art"]]
    anb, endp = doku.technik(qid)
    with st.expander(f"**{q['name']}**  ·  `{qid}`", icon=symbol, expanded=offen):
        st.markdown(q["beschreibung"])
        worte = dq.kurzinfo(qid)[1]
        if worte:
            st.markdown("**Wofür / liefert:** " + " ".join(_badge("gray", w) for w in worte))
        badges = [_badge("blue", f"{symbol} {art_name}")]
        if q["art"] == "umkreis":
            badges.append(_badge("blue", f"Radius {q['radius']} m, max. {q['max_radius']} m"))
        badges += [_badge("violet", dq.ANBINDUNGEN[anb]), _badge("green", q["lizenz"])]
        st.markdown(" ".join(badges))

        zeilen = [f"**Anbieter:** {q['anbieter']}"]
        if q["url"]:
            host = urlparse(q["url"]).netloc.removeprefix("www.")
            zeilen.append(f"**Webseite / Doku:** [{host}]({q['url']})")
        if endp:
            zeilen.append("**Dienst-Adresse" + ("n" if len(endp) > 1 else "") + ":** " +
                          " · ".join(f"`{e}`" for e in endp))
        elif q["art"] == "suche" or qid.endswith("_abfrage"):
            zeilen.append("**Dienst-Adresse:** kommt als Parameter `url`")
        st.markdown("  \n".join(zeilen))

        if q["parameter"]:
            beispiel = dq.TEST_PARAMETER.get(qid, {})
            mit_bsp = any(k in beispiel for k in q["parameter"])
            st.markdown("**Parameter** (alle optional, außer wo „Pflicht“ steht)\n\n| Name | Bedeutung |" +
                        (" Beispiel |\n|---|---|---|\n" if mit_bsp else "\n|---|---|\n") + "\n".join(
                            f"| `{k}` | {str(v).replace('|', '/')} |" +
                            (f" {'`' + json.dumps(beispiel[k], ensure_ascii=False) + '`' if k in beispiel else ''} |"
                             if mit_bsp else "")
                            for k, v in q["parameter"].items()))

        aufruf = (bsp or {}).get("aufruf") or dq.beispiel_aufruf(qid)
        t_agent, t_py, t_cli = st.tabs(["Aufruf durch den Agenten", "Python", "Kommandozeile"])
        with t_agent:
            st.code(json.dumps(aufruf, ensure_ascii=False, indent=2), language="json")
            st.caption("Argumente für das Werkzeug `datenquelle_abfragen`.")
        with t_py:
            st.code(doku.python_aufruf(aufruf), language="python")
        with t_cli:
            st.code(f".venv\\Scripts\\python datenquellen.py test {qid}", language="bash")
            st.caption("Ruft die Quelle mit den Beispielwerten am Luisenplatz Darmstadt auf. "
                       f"`datenquellen.py beispiele {qid}` speichert die Antwort zusätzlich als Beispiel für diese Seite.")

        antwort = (bsp or {}).get("antwort")
        if antwort:
            sek = antwort.get("sekunden") or 0
            st.markdown(f"**Antwort** &nbsp; Beispiel vom {doku.datum(bsp['datum'])} am Luisenplatz Darmstadt, " +
                        (f"{sek} s" if sek >= 0.2 else "aus dem Zwischenspeicher"))
            text = json.dumps(doku.kurz(antwort), ensure_ascii=False, indent=2)
            st.code(text, language="json", height=420 if text.count("\n") > 22 else "content")
            if antwort.get("files"):
                st.caption("Dateien: " + ", ".join(f"`{v}`" for v in antwort["files"].values()) +
                           " · GeoJSON-Dateien gehen direkt an make_map oder an QGIS-Algorithmen.")
            if bsp.get("letzter_fehler"):
                st.caption(f"⚠️ Letzter Test am {doku.datum(bsp['letzter_fehler']['datum'])} fehlgeschlagen: "
                           f"{bsp['letzter_fehler']['fehler']}")
        elif bsp and bsp.get("fehler"):
            st.warning(f"Beim letzten Test ({doku.datum(bsp['datum'])}) nicht erreichbar: {bsp['fehler']}")
        else:
            st.info("Noch keine Beispielantwort gespeichert. Tab *Selbsttest* ausführen.")

        key = f"live_{qid}"
        if st.button("Jetzt live abfragen", key=f"btn_{key}", icon=":material/play_arrow:",
                     help="Ruft die Quelle jetzt mit dem Beispielaufruf oben auf und zeigt Karte und Antwort."):
            try:
                geo_tools.new_run(f"datenquelle {qid}")
                with st.spinner(f"Frage {q['name']} ab …"):
                    st.session_state[key] = dq.abfragen(**aufruf)
            except Exception as err:
                st.session_state[key] = {"fehler": f"{type(err).__name__}: {err}"}
        if st.session_state.get(key):
            if "fehler" in st.session_state[key]:
                st.error(st.session_state[key]["fehler"])
            else:
                _zeige_ergebnis(st.session_state[key])


DOWNLOADS = [  # (Format, Beschriftung, Symbol, wofür)
    ("md", "Markdown (.md)", ":material/description:",
     "Tabelle je Gruppe und je Quelle Beschreibung, Links, Dienst-Adressen und Parameter. "
     "Für GitHub, Obsidian oder den Bericht."),
    ("html", "HTML-Seite (.html)", ":material/language:",
     "Dieselbe Doku als eigenständige Seite: im Browser öffnen oder weitergeben."),
    ("pdf", "PDF (.pdf)", ":material/picture_as_pdf:",
     "Dieselbe Doku als A4-PDF, je Gruppe eine neue Seite. Edge oder Chrome erzeugt sie ohne Fenster, "
     "das dauert ein paar Sekunden."),
    ("csv", "Tabelle für Excel (.csv)", ":material/table:",
     "Eine Zeile je Quelle mit allen Feldern. Semikolon-getrennt, öffnet direkt in Excel."),
    ("json", "JSON (.json)", ":material/data_object:",
     "Maschinenlesbar mit allen Feldern, z.B. für Skripte."),
]


def _downloads(gruppierung):
    """Download-Knöpfe; die Dateien werden erst beim Klick erzeugt."""
    st.caption(f"Alle {len(dq.QUELLEN)} Quellen ohne Beispiele, unabhängig von der Suche. Markdown, HTML und PDF "
               f"sind nach **{gruppierung}** gruppiert.")
    for fmt, label, icon, hilfe in DOWNLOADS:
        _, mime, fn = doku.EXPORTE[fmt]
        ohne_browser = fmt == "pdf" and not doku.browser_pfad()
        st.download_button(label, data=lambda fn=fn: fn(gruppierung), file_name=doku.dateiname(fmt), mime=mime,
                           icon=icon, width="stretch", on_click="ignore", key=f"dl_{fmt}", disabled=ohne_browser,
                           help="Kein Edge oder Chrome gefunden (Pfad über PDF_BROWSER setzen)." if ohne_browser else hilfe)


def _doku():
    _intro()
    bsp = dq.beispiele()
    st.html(TABELLE_CSS)
    c1, c2, c3, c4 = st.columns([5, 4, 3, 2], vertical_alignment="bottom")
    such = c1.text_input("Suche", placeholder="Suchen, z.B. Lärm, Bäume, Unfall, Hitze, DWD, WFS …",
                         icon=":material/search:")
    gruppierung = c2.segmented_control("Gruppieren nach", doku.GRUPPIERUNGEN, default="Thema",
                                       required=True, width="stretch")
    ansicht = c3.segmented_control("Ansicht", ["Tabelle", "Details"], default="Tabelle", required=True, width="stretch",
                                   help="Tabelle: eine Zeile je Quelle. Details: je Quelle Links, Dienst-Adressen, "
                                        "Parameter, Aufrufbeispiele, Beispielantwort und Live-Abfrage.")
    with c4.popover("Export", icon=":material/download:", width="stretch"):
        _downloads(gruppierung)
    gruppen = doku.gruppen(gruppierung, such)
    treffer = sum(len(v) for v in gruppen.values())
    if not treffer:
        st.info("Keine Quelle passt zur Suche.")
        return
    if such:
        st.caption(f"{treffer} von {len(dq.QUELLEN)} Quellen passen zu „{such}“.")
    _uebersicht(gruppen, gruppierung)
    for g, ids in gruppen.items():
        symbol, info = doku.gruppen_info(gruppierung, g)
        st.subheader(f"{symbol} {g}", anchor=doku.slug(g), divider="gray")
        if info:
            st.caption(info)
        if ansicht == "Tabelle":
            _tabelle(g, ids)
        else:
            for qid in ids:
                _quelle_doku(qid, bsp.get(qid), offen=treffer <= 2)
    if ansicht == "Tabelle":
        st.caption("Aufrufbeispiele, Dienst-Adressen und Beispielantworten je Quelle: Ansicht **Details**.")


# =====================================================================================================
# Ausprobieren und Selbsttest
# =====================================================================================================
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


def _ausprobieren():
    ids = list(dq.QUELLEN)
    qid = st.selectbox("Quelle", ids, format_func=lambda i: f"{dq.QUELLEN[i]['name']}  ({i})")
    q = dq.QUELLEN[qid]
    worte = dq.kurzinfo(qid)[1]
    st.caption(q["beschreibung"] + (" · " + ", ".join(worte) if worte else ""))
    c1, c2 = st.columns([3, 1])
    ort = c1.text_input("Ort (Suche über geocode)", value="Luisenplatz, Darmstadt",
                        help="Adresse, Platz oder Kreuzung 'Straße A / Straße B, Stadt'")
    radius = c2.number_input("Radius (m)", min_value=10, max_value=int(q["max_radius"]), value=int(q["radius"]),
                             step=50, disabled=q["art"] != "umkreis", key=f"radius_{qid}")
    par = st.text_area("Parameter (JSON)", value=json.dumps(dq.TEST_PARAMETER.get(qid, {}), ensure_ascii=False),
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
                st.session_state.dq_result = dq.abfragen(qid, lat, lon, radius, json.loads(par or "{}"))
        except Exception as err:
            st.session_state.dq_result = None
            st.error(f"{type(err).__name__}: {err}")
    if st.session_state.get("dq_result"):
        _zeige_ergebnis(st.session_state.dq_result)


def _selbsttest():
    st.write(f"Ruft alle {len(dq.QUELLEN)} Quellen am Luisenplatz Darmstadt auf (6 gleichzeitig). "
             "Dauert ca. 1-2 Minuten, beim allerersten Mal länger (Unfallatlas, KOSTRA, Klimaraster werden geladen).")
    speichern = st.checkbox("Antworten als Beispiele für die Doku speichern", value=True,
                            help=f"Schreibt {os.path.relpath(dq.BEISPIELE_DATEI, dq.HERE)}. Schlägt eine Quelle fehl, "
                                 "bleibt ihr letztes gutes Beispiel stehen.")
    if st.button("Selbsttest starten"):
        with st.spinner("Teste alle Datenquellen ..."):
            st.session_state.dq_selbsttest = dq.selbsttest(beispiele_speichern=speichern)
    res = st.session_state.get("dq_selbsttest")
    if res:
        ok = sum(r["ok"] for r in res)
        (st.success if ok == len(res) else st.warning)(f"{ok} von {len(res)} Quellen funktionieren.")
        st.dataframe(pd.DataFrame([{"": "✅" if r["ok"] else "❌", "Quelle": r["quelle"], "Sekunden": r["sekunden"],
                                    "Ergebnis / Fehler": r["info"]} for r in res]),
                     hide_index=True, width="stretch", height="content",  # keine zweite Scrollleiste
                     column_config={"": st.column_config.TextColumn(width=40),
                                    "Quelle": st.column_config.TextColumn(width=230),
                                    "Sekunden": st.column_config.NumberColumn(width=80, format="%.1f"),
                                    "Ergebnis / Fehler": st.column_config.TextColumn(width="large")})


def page():
    st.title("📚 Freie Datenquellen")
    st.caption(f"{len(dq.QUELLEN)} offene Quellen ohne API-Key. Der Agent ruft sie mit dem Werkzeug "
               "datenquelle_abfragen auf. Hier sind alle dokumentiert und lassen sich direkt ausprobieren.")
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        st.markdown("🔀 **Datenquellen aller drei Prototypen**: Gesamtmenge aus den Branches von Aaron, Lorenz und "
                    "Ritvik, mit Schnittmengen und wie jeder sie nutzt.", width="stretch")
        st.page_link(datenquellen_alle_page.SEITE, label="Vergleich öffnen", icon=":material/arrow_forward:")
    tab_doku, tab_test, tab_alle = st.tabs(["📖 Doku", "🧪 Ausprobieren", "✅ Selbsttest"])
    with tab_doku:
        _doku()
    with tab_test:
        _ausprobieren()
    with tab_alle:
        _selbsttest()
