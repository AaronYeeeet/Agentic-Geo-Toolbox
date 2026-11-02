"""
Streamlit-Seite "Datenquellen aller Prototypen" (Link auf der Seite Datenquellen, nicht in der Navigation):
Gesamtmenge der Quellen aus den drei Prototyp-Branches (Aaron, Lorenz, Ritvik), Schnittmengen als Venn-Diagramm
und eine Tabelle mit Anmerkung, wie jeder Branch die Quelle nutzt. Daten und Exporte: datenquellen_alle.py
"""
import pandas as pd
import streamlit as st

import datenquellen_alle as da
import datenquellen_doku as doku

# Gleiche Spaltenbreiten in allen Tabellen, lange Texte brechen um
TABELLE_CSS = """<style>
[class*="st-key-alletab_"] table { table-layout: fixed; width: 100%; }
[class*="st-key-alletab_"] th:nth-child(1) { width: 22%; }
[class*="st-key-alletab_"] th:nth-child(2) { width: 14%; }
[class*="st-key-alletab_"] th:nth-child(3),
[class*="st-key-alletab_"] th:nth-child(4),
[class*="st-key-alletab_"] th:nth-child(5) { width: 7%; text-align: center; }
[class*="st-key-alletab_"] td:nth-child(3),
[class*="st-key-alletab_"] td:nth-child(4),
[class*="st-key-alletab_"] td:nth-child(5) { text-align: center; }
[class*="st-key-alletab_"] td code { overflow-wrap: anywhere; }
</style>"""

DOWNLOADS = [  # (Format, Beschriftung, Symbol, wofür) - wie auf der Seite Datenquellen
    ("md", "Markdown (.md)", ":material/description:",
     "Wie die Doku: alle Kategorien als Tabellen, dann jede Quelle mit Beschreibung, Anbieter, Lizenz und "
     "Dienst-Adresse."),
    ("html", "HTML-Seite (.html)", ":material/language:",
     "Dieselbe Doku als eigenständige Seite: im Browser öffnen oder weitergeben."),
    ("pdf", "PDF (.pdf)", ":material/picture_as_pdf:",
     "Dieselbe Doku als A4-PDF, je Kategorie eine neue Seite. Edge oder Chrome erzeugt sie ohne Fenster, "
     "das dauert ein paar Sekunden."),
    ("csv", "Tabelle für Excel (.csv)", ":material/table:",
     "Eine Zeile je Quelle mit allen Feldern. Semikolon-getrennt, öffnet direkt in Excel."),
    ("json", "JSON (.json)", ":material/data_object:",
     "Maschinenlesbar: alle Quellen mit allen Feldern, z.B. für Skripte."),
]


def _status(row, b):
    if b not in row["nutzung"]:
        return "–"
    return da.STATUS[row["nutzung"][b][0]][0]


def _tabelle(key, rows):
    zeilen = []
    for r in rows:
        name = f"**{r['name']}**"
        zeilen.append({
            "Quelle": f"[{name}]({r['url']})" if r["url"] else name,
            "Anbieter": r["anbieter"],
            **{v["person"]: _status(r, b) for b, v in da.BRANCHES.items()},
            "Anmerkung": " · ".join(f"**{da.BRANCHES[b]['kurz']}:** {r['nutzung'][b][1]}"
                                    for b in da.BRANCHES if b in r["nutzung"]),
        })
    with st.container(key=f"alletab_{doku.slug(key)}"):
        st.table(pd.DataFrame(zeilen), hide_index=True, border="horizontal")


def _passt(row, such):
    text = " ".join([row["id"], row["name"], row["thema"], row["anbieter"], row["dienst"]] +
                    [t for _, t in row["nutzung"].values()]).lower()
    return all(w in text for w in such.lower().split())


def _filter_optionen(rows, nur_aktiv):
    """Auswahl 'Bereich': (Beschriftung, Test je Branch-Kombination)."""
    opt = [("Alle", lambda c: True),
           ("In allen drei", lambda c: len(c) == 3),
           ("In mindestens zwei", lambda c: len(c) >= 2),
           ("Nur in einem", lambda c: len(c) == 1)]
    opt += [(f"Genutzt von {v['person']}", lambda c, b=b: b in c) for b, v in da.BRANCHES.items()]
    opt += [(da.bereich_titel(c), lambda c, k=c: c == k) for c in da.bereiche() if len(c) < 3]
    return [(f"{name} ({sum(test(da.genutzt(r, nur_aktiv)) for r in rows)})", test) for name, test in opt]


def _downloads(gruppierung, nur_aktiv, n):
    """Download-Knöpfe; die Dateien werden erst beim Klick erzeugt."""
    st.caption(f"Alle {n} Quellen, unabhängig von Suche und Bereich" + (", nur aktiv genutzte" if nur_aktiv else "") +
               ". Nur die Quellen selbst wie in der Doku, ohne Vergleich der Prototypen, nach Thema gruppiert.")
    for fmt, label, icon, hilfe in DOWNLOADS:
        _, mime, fn = da.EXPORTE[fmt]
        ohne_browser = fmt == "pdf" and not doku.browser_pfad()
        st.download_button(label, data=lambda fn=fn: fn(gruppierung, nur_aktiv), file_name=da.dateiname(fmt, nur_aktiv),
                           mime=mime, icon=icon, width="stretch", on_click="ignore", key=f"alle_dl_{fmt}",
                           disabled=ohne_browser,
                           help="Kein Edge oder Chrome gefunden (Pfad über PDF_BROWSER setzen)." if ohne_browser else hilfe)


def page():
    import datenquellen_page  # hier statt oben: datenquellen_page importiert dieses Modul für den Link
    st.page_link(st.Page(datenquellen_page.page, title="Datenquellen", icon="📚", url_path="datenquellen"),
                 label="Zurück zu den Datenquellen", icon=":material/arrow_back:")
    st.title("🔀 Datenquellen aller Prototypen")
    st.caption(f"Gesamtmenge aller Quellen aus den drei Prototyp-Branches, mit Schnittmengen und wie jeder Branch "
               f"sie nutzt. Code, Prompts, Konfiguration und Doku aller Branches gescannt am {da.STAND}.")

    nur_aktiv = st.toggle("Nur aktiv genutzte Quellen zählen", value=False,
                          help="Aus: zählt auch Quellen, die nur vorbereitet (z.B. Registry-Kandidat) oder nur als "
                               "Quelle von Demo-Daten genannt sind. An: nur, was ein Prototyp wirklich abruft.")
    rows = [r for r in da.zeilen() if da.genutzt(r, nur_aktiv)]
    sm = da.schnittmengen(rows, nur_aktiv)

    with st.container(horizontal=True):
        st.metric("Quellen gesamt", len(rows), border=True, help="Vereinigung aller drei Branches")
        st.metric("in allen drei", len(sm[tuple(da.BRANCHES)]), border=True)
        st.metric("in genau zwei", sum(len(v) for c, v in sm.items() if len(c) == 2), border=True)
        st.metric("nur in einem", sum(len(v) for c, v in sm.items() if len(c) == 1), border=True)

    links, rechts = st.columns([2, 3], gap="large", vertical_alignment="center")
    with links:
        # st.html filtert SVG heraus, Markdown mit HTML nicht
        st.markdown(f'<div class="venn">\n{da.venn_svg(sm)}\n</div>', unsafe_allow_html=True)
    with rechts:
        st.markdown("**Schnittmengen**")
        st.table(pd.DataFrame([{
            "Bereich": da.bereich_name(c),
            "Anzahl": len(v),
            "Quellen": ", ".join(r["name"] for r in v) if 0 < len(v) <= 7 else ("–" if not v else "siehe Tabelle"),
        } for c, v in sm.items()]), hide_index=True, border="horizontal")

    cols = st.columns(3)
    for col, (b, v) in zip(cols, da.BRANCHES.items()):
        n = sum(b in da.genutzt(r, nur_aktiv) for r in rows)
        with col.container(border=True, height="stretch"):
            st.markdown(f"**:material/person: {v['person']}** &nbsp; `{v['branch']}`")
            st.caption(f"{v['technik']} · Stand {v['stand']}")
            st.markdown(f"**{n}** Quellen, davon **{len(sm[(b,)])}** nur hier")
            st.caption(v["text"])

    st.caption("**Stufen:** " + " · ".join(f"{s} **{n}**: {t}" for s, n, t in da.STATUS.values()) +
               " · – nicht genutzt")

    st.html(TABELLE_CSS)
    c1, c2, c3, c4 = st.columns([4, 4, 3, 2], vertical_alignment="bottom")
    such = c1.text_input("Suche", placeholder="Suchen, z.B. Luftbild, OSM, WMS, Ladesäulen …", icon=":material/search:")
    optionen = _filter_optionen(rows, nur_aktiv)
    wahl = c2.selectbox("Bereich", range(len(optionen)), format_func=lambda i: optionen[i][0])
    gruppierung = c3.segmented_control("Gruppieren nach", da.GRUPPIERUNGEN, default="Thema",
                                       required=True, width="stretch")
    with c4.popover("Export", icon=":material/download:", width="stretch"):
        _downloads(gruppierung, nur_aktiv, len(rows))

    test = optionen[wahl][1]
    treffer = [r for r in rows if test(da.genutzt(r, nur_aktiv)) and (not such or _passt(r, such))]
    if not treffer:
        st.info("Keine Quelle passt zu Suche und Bereich.")
        return
    if len(treffer) < len(rows):
        st.caption(f"{len(treffer)} von {len(rows)} Quellen.")
    for titel, symbol, info, liste in da.gruppen(gruppierung, treffer, nur_aktiv):
        st.subheader(f"{symbol} {titel} &nbsp; :gray-badge[{len(liste)}]", anchor=doku.slug(titel), divider="gray")
        if info:
            st.caption(info)
        _tabelle(titel, liste)


SEITE = st.Page(page, title="Datenquellen aller Prototypen", icon="🔀", url_path="datenquellen-alle",
                visibility="hidden")
