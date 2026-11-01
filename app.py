"""
Streamlit-Oberfläche für den Geo-Agenten.

Start (im Terminal, im Projektordner):
    .venv\\Scripts\\streamlit run app.py
Öffnet sich im Browser unter http://localhost:8501
Drei Seiten (links): Chat, Ergebnisse (alle Karten/Dateien, ein Ordner pro Frage) und Datenquellen
(Katalog aller freien Quellen, einzeln ausprobieren, Selbsttest).
Schalter "Eigene Analyse-Skills" in der Seitenleiste: aus = Modus "Nur Datenquellen" (nur offene Daten + QGIS).
Chats werden nach jeder Antwort in output/chats/ gespeichert (Verlauf + LLM-Kontext), die Chat-ID steht
in der URL (?chat=...): Neuladen oder Neustart öffnet denselben Chat, alte Chats links in der Seitenleiste.
"""
import json
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import chat_store
import datenquellen
import datenquellen_page
import ergebnisse_page
import agent as agent_mod
from agent import create_agent

st.set_page_config(page_title="Geo-Agent", page_icon="🗺️", layout="wide")


def render_steps(events, container):
    """Denkprozess, Werkzeug-Aufrufe und Zeiten anzeigen."""
    for ev in events:
        t = ev["type"]
        if t == "thought":
            container.info(ev["text"], icon="💭")
        elif t == "llm_time":
            container.caption(f"LLM: {ev['seconds']:.1f}s")
        elif t == "tool_call":
            container.markdown(f"🔧 **{ev['name']}**")
            container.code(json.dumps(ev["args"], ensure_ascii=False, indent=2), language="json")
        elif t == "tool_result":
            err = ev["result"].get("error")
            if err:
                container.error(f"Fehler nach {ev['seconds']:.1f}s: {err}")
            else:
                container.caption(f"fertig in {ev['seconds']:.1f}s")
                container.code(json.dumps(ev["result"], ensure_ascii=False)[:1500], language="json")
        elif t == "retry":
            container.warning(f"{ev['code']} (überlastet/Limit), neuer Versuch in {ev['wait']}s")


def render_answer(events, run_dir=None):
    for ev in events:
        if ev["type"] == "text":
            st.markdown(ev["text"])
        elif ev["type"] in ("error", "info"):
            st.error(ev["text"])
    # Bilder aus Datenquellen (z.B. Luftbild Hessen)
    for ev in events:
        res = ev["result"].get("result") if ev["type"] == "tool_result" else None
        for name in (res.get("files") or {}).values() if isinstance(res, dict) else []:
            path = os.path.join(run_dir or "", name)
            if name.lower().endswith((".png", ".jpg", ".jpeg")) and os.path.exists(path):
                st.image(path, caption=name, width=520)
    # Genutzte Datenquellen (direkt aus den Ergebnissen, nicht vom Modell abgeschrieben)
    quellen = {}
    for ev in events:
        res = ev["result"].get("result") if ev["type"] == "tool_result" else None
        if isinstance(res, dict) and isinstance(res.get("quelle"), dict):
            q = res["quelle"]
            quellen[q["id"]] = {"Quelle": q["name"], "Anbieter": q["anbieter"], "Stand": q.get("stand", ""),
                                "Lizenz": q["lizenz"], "Link": q.get("url", "")}
    if quellen:
        with st.expander(f"📚 Genutzte Datenquellen ({len(quellen)})"):
            st.dataframe(pd.DataFrame(quellen.values()), hide_index=True, width="stretch",
                         column_config={"Link": st.column_config.LinkColumn("Link")})
    # Karte anzeigen, falls der Agent eine erzeugt hat
    for ev in events:
        if ev["type"] == "tool_result" and "map" in ev["result"].get("result", {}):
            path = ev["result"]["result"]["map"]
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    components.html(f.read(), height=520)
                st.caption(path)
    # Alle Annahmen der Werkzeuge vollständig (direkt aus dem Ergebnis, nicht vom Modell abgeschrieben)
    for ev in events:
        res = ev["result"].get("result") if ev["type"] == "tool_result" else None
        if isinstance(res, dict) and res.get("annahmen"):
            rows = res["annahmen"]
            n_changed = sum(r.get("geaendert", False) for r in rows)
            with st.expander(f"📋 Alle Annahmen: {ev['name']} ({len(rows)}, davon {n_changed} geändert)"):
                fmt = lambda v: ", ".join(f"{k}: {x:g}" if isinstance(x, (int, float)) else f"{k}: {x}"
                                          for k, x in v.items()) if isinstance(v, dict) else str(v)
                st.dataframe(pd.DataFrame([{
                    "Annahme": r["annahme"], "Wert": fmt(r["wert"]), "Einheit": r.get("einheit", ""),
                    "Standard": fmt(r["standard"]) if "standard" in r else "", "geändert": "✏️" if r.get("geaendert") else "",
                    "Name (für Änderungen)": r.get("schluessel", "")} for r in rows]), hide_index=True, width="stretch")


@st.cache_data(ttl=3600, show_spinner="Lade Modellliste …")
def _model_choices():
    return agent_mod.model_choices()


def _start_chat(chat_id=None):
    """Neuen Agenten anlegen und optional einen gespeicherten Chat (Verlauf + LLM-Kontext) laden.
    Ein gespeicherter Chat läuft mit seinem ursprünglichen Modell weiter, wenn es noch wählbar ist."""
    choice = st.session_state.get("model_choice") or agent_mod.default_choice()
    skills = st.session_state.get("skills", True)
    data = chat_store.load(chat_id) if chat_store.exists(chat_id) else None
    if data:
        state = data.get("llm_state") or {}
        own = f"{state.get('provider')}:{state.get('model')}"
        if own in dict(_model_choices()):
            choice = own
        skills = data.get("skills", True)  # gespeicherter Chat behält seinen Modus
    agent = create_agent(choice, skills=skills)
    turns, note = [], None
    if data:
        turns = data.get("turns", [])
        note = chat_store.restore(agent, data)
    else:
        chat_id = None
    st.session_state.update(agent=agent, history=turns, chat_id=chat_id, restore_note=note, model_choice=choice,
                            skills=skills)
    if chat_id:
        st.query_params["chat"] = chat_id  # steht in der URL: Neuladen der Seite öffnet denselben Chat
    elif "chat" in st.query_params:
        del st.query_params["chat"]


def _switch_model(choice):
    """Modell wechseln, ohne den Chat zu verlieren: neuer Agent bekommt Fragen + Antworten als Kontext."""
    old = st.session_state.agent
    try:
        agent = create_agent(choice, skills=old.skills)
    except ValueError as err:
        st.session_state.restore_note = str(err)
        return
    turns = st.session_state.history
    note = chat_store.restore(agent, {"turns": turns, "llm_state": old.export_state(), "model": old.label})
    st.session_state.update(agent=agent, model_choice=choice,
                            restore_note=f"Modell gewechselt auf {agent.label}." + (f" {note}" if turns else ""))
    if st.session_state.chat_id:
        chat_store.save(st.session_state.chat_id, agent, turns)


def chat_page():
    # ---------- Zustand ----------
    wanted = st.query_params.get("chat")
    if "agent" not in st.session_state or (wanted and wanted != st.session_state.get("chat_id")):
        try:
            _start_chat(wanted)
        except ValueError as err:
            st.error(f"{err} Danach Streamlit neu starten.")
            st.stop()
    elif st.session_state.chat_id and not wanted:  # z.B. nach Wechsel von der Ergebnisse-Seite
        st.query_params["chat"] = st.session_state.chat_id
    agent = st.session_state.agent

    # ---------- Seitenleiste ----------
    with st.sidebar:
        st.header("🗺️ Geo-Agent")
        choices = dict(_model_choices())
        if agent.choice not in choices:  # z.B. Modell aus .env, das gerade nicht in der Gratis-Liste steht
            choices = {agent.choice: agent.label, **choices}
        keys = list(choices)
        picked = st.selectbox("Modell", keys, index=keys.index(agent.choice), format_func=choices.get,
                              help="Google-Modelle (GEMINI_API_KEY) und alle kostenlosen OpenRouter-Modelle mit "
                                   "Werkzeug-Unterstützung (Liste live von OpenRouter, täglich aktualisiert). "
                                   "Ein Wechsel mitten im Chat übernimmt die bisherigen Fragen und Antworten.")
        if picked != agent.choice:
            _switch_model(picked)
            st.rerun()
        skills = st.toggle(
            "🧩 Eigene Analyse-Skills", value=agent.skills,
            help="An: zusätzlich die selbst gebauten Werkzeuge hitze, starkregen, ladesaeulen, traffic_impact, "
                 "construction_noise (rechnen mit Annahmen).\n\nAus: Modus 'Nur Datenquellen' - der Agent antwortet "
                 f"nur mit den {len(datenquellen.QUELLEN)} freien Datenquellen, OpenStreetMap und bestehenden "
                 "QGIS-Algorithmen. Gilt für diesen Chat, der Verlauf bleibt erhalten.")
        if skills != agent.skills:
            agent.set_skills(skills)
            st.session_state.skills = skills
            st.session_state.restore_note = ("Modus: eigene Analyse-Skills + Datenquellen." if skills else
                                             "Modus: Nur Datenquellen (ohne eigene Analyse-Skills, Antworten nur aus "
                                             "offenen Daten und QGIS-Werkzeugen).")
            if st.session_state.chat_id:
                chat_store.save(st.session_state.chat_id, agent, st.session_state.history)
            st.rerun()
        st.caption(("Skills + " if agent.skills else "Nur ") + f"{len(datenquellen.QUELLEN)} Datenquellen · "
                   "Liste: Seite **Datenquellen**")
        show_steps = st.toggle("Denkprozess & Werkzeuge zeigen", value=True)
        if st.button("➕ Neuer Chat", width="stretch"):
            _start_chat(None)
            st.rerun()

        chats = chat_store.list_chats(50)
        if chats:
            def chat_button(c):
                current = c["id"] == st.session_state.chat_id
                title = c["title"] if len(c["title"]) <= 45 else c["title"][:44] + "…"
                if st.button(title, key=f"chat_{c['id']}", width="stretch", type="primary" if current else "tertiary",
                             help=f"{c['updated']} · {c['turns']} Fragen · {c['model']}"):
                    if not current:
                        _start_chat(c["id"])
                        st.rerun()

            st.markdown("**💬 Gespeicherte Chats**")
            for c in chats[:3]:  # die neuesten drei immer sichtbar
                chat_button(c)
            if len(chats) > 3:
                older = chats[3:]
                # aufgeklappt lassen, wenn der aktuelle Chat darin liegt
                open_ = any(c["id"] == st.session_state.chat_id for c in older)
                with st.expander(f"Ältere Chats ({len(older)})", expanded=open_):
                    for c in older:
                        chat_button(c)
            if st.session_state.chat_id:
                cur = next((c for c in chats if c["id"] == st.session_state.chat_id), None)
                col1, col2 = st.columns(2)
                with col1.popover("✏️ Name", width="stretch", help="Chat umbenennen"):
                    new = st.text_input("Neuer Name", value=cur["title"] if cur else "", max_chars=120,
                                        help="Leer lassen = wieder die erste Frage als Name")
                    if st.button("Speichern", type="primary"):
                        chat_store.rename(st.session_state.chat_id, new)
                        st.rerun()
                with col2.popover("🗑️ Löschen", width="stretch"):
                    st.caption("Löscht nur den gespeicherten Chat. Die Ergebnisordner bleiben erhalten.")
                    if st.button("Endgültig löschen"):
                        chat_store.delete(st.session_state.chat_id)
                        _start_chat(None)
                        st.rerun()
        st.divider()
        if os.path.exists(agent.log_path):
            with open(agent.log_path, encoding="utf-8") as f:
                st.download_button("Protokoll herunterladen (.md)", f.read(),
                                   file_name=os.path.basename(agent.log_path))
        st.caption(f"Protokoll: {agent.log_path}")
        st.divider()
        st.markdown("**Beispiele**\n- Was bedeutet eine Baustelle an der Kreuzung Rheinstraße / Neckarstraße in "
                    "Darmstadt für Verkehr und Lärm? Es wird abgerissen.\n"
                    "- Was passiert bei Starkregen, wenn wir im Herrngarten Darmstadt 5000 m² pflastern?\n"
                    "- Wird es wärmer, wenn wir im Herrngarten Darmstadt die Bäume fällen?\n"
                    "- Wo könnten in Darmstadt-Mitte E-Ladesäulen sinnvoll sein?\n"
                    "- Wo rund um die TU Darmstadt fehlen Ladesäulen?\n"
                    "- Welche Schulen in Darmstadt-Mitte haben keinen Spielplatz im Umkreis von 300 m?\n\n"
                    "**Gut für 'Nur Datenquellen'**\n"
                    "- Wie heiß wird es im Sommer am Luisenplatz Darmstadt und wie viel Grün gibt es dort?\n"
                    "- Wie gefährdet ist das Martinsviertel Darmstadt bei Starkregen?\n"
                    "- Welche Unfälle mit Radfahrenden gab es rund um den Darmstädter Hauptbahnhof?\n"
                    "- Was muss ich beim Bauen am Oberfeld Darmstadt beachten (Schutzgebiete, Boden, Wasser, Arten)?\n"
                    "- Wie gut ist die TU-Lichtwiese mit Bus, Bahn und Leihrad erreichbar?")

    # ---------- Verlauf ----------
    if st.session_state.get("restore_note"):
        st.info(st.session_state.restore_note, icon="ℹ️")
    for turn in st.session_state.history:
        with st.chat_message("user"):
            st.markdown(turn["prompt"])
        with st.chat_message("assistant"):
            if show_steps:
                with st.expander("Denkprozess & Werkzeuge"):
                    render_steps(turn["events"], st)
            render_answer(turn["events"], turn.get("run_dir"))
            if turn.get("run_dir") and os.path.isdir(turn["run_dir"]):
                st.caption(f"📁 Dateien: Seite **Ergebnisse**, Ordner `{os.path.basename(turn['run_dir'])}`")

    # ---------- Neue Frage ----------
    prompt = st.chat_input("Frag etwas, z.B. 'Wo in Darmstadt fehlen Ladesäulen?'")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            events = []
            with st.status("Agent arbeitet ...", expanded=show_steps) as status:
                for ev in agent.ask(prompt):
                    events.append(ev)
                    if ev["type"] == "tool_call":
                        status.update(label=f"Agent arbeitet ... ({ev['name']})")
                    if show_steps:
                        render_steps([ev], st)
                failed = any(e["type"] == "error" for e in events)
                status.update(label="Fehler" if failed else "Fertig", state="error" if failed else "complete",
                              expanded=False)
            render_answer(events, agent.run_dir)
        # Nach jeder Antwort speichern: Chat übersteht Neuladen und Neustart
        st.session_state.history.append({"prompt": prompt, "events": events, "run_dir": agent.run_dir})
        if not st.session_state.chat_id:
            st.session_state.chat_id = chat_store.new_id()
            st.query_params["chat"] = st.session_state.chat_id
        chat_store.save(st.session_state.chat_id, agent, st.session_state.history)
        st.rerun()  # Seitenleiste mit dem (neuen) gespeicherten Chat aktualisieren


st.navigation([
    st.Page(chat_page, title="Chat", icon="💬", default=True),
    st.Page(ergebnisse_page.page, title="Ergebnisse", icon="🗂️", url_path="ergebnisse"),
    st.Page(datenquellen_page.page, title="Datenquellen", icon="📚", url_path="datenquellen"),
]).run()
