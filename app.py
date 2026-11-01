"""
Streamlit-Oberfläche für den Geo-Agenten.

Start (im Terminal, im Projektordner):
    .venv\\Scripts\\streamlit run app.py
Öffnet sich im Browser unter http://localhost:8501
Zwei Seiten (links): Chat und Ergebnisse (alle Karten/Dateien, ein Ordner pro Frage).
"""
import json
import os

import streamlit as st
import streamlit.components.v1 as components

import ergebnisse_page
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


def render_answer(events):
    for ev in events:
        if ev["type"] == "text":
            st.markdown(ev["text"])
        elif ev["type"] in ("error", "info"):
            st.error(ev["text"])
    # Karte anzeigen, falls der Agent eine erzeugt hat
    for ev in events:
        if ev["type"] == "tool_result" and "map" in ev["result"].get("result", {}):
            path = ev["result"]["result"]["map"]
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    components.html(f.read(), height=520)
                st.caption(path)


def chat_page():
    # ---------- Zustand ----------
    if "agent" not in st.session_state:
        try:
            st.session_state.agent = create_agent()
        except ValueError as err:
            st.error(f"{err} Danach Streamlit neu starten.")
            st.stop()
        st.session_state.history = []  # [{"prompt": str, "events": [...]}]
    agent = st.session_state.agent

    # ---------- Seitenleiste ----------
    with st.sidebar:
        st.header("🗺️ Geo-Agent")
        st.caption(f"Modell: `{agent.label}`")
        show_steps = st.toggle("Denkprozess & Werkzeuge zeigen", value=True)
        if st.button("Neuer Chat"):
            del st.session_state["agent"]
            st.rerun()
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
                    "- Wo rund um die TU Darmstadt fehlen Ladesäulen?\n"
                    "- Welche Schulen in Darmstadt-Mitte haben keinen Spielplatz im Umkreis von 300 m?")

    # ---------- Verlauf ----------
    for turn in st.session_state.history:
        with st.chat_message("user"):
            st.markdown(turn["prompt"])
        with st.chat_message("assistant"):
            if show_steps:
                with st.expander("Denkprozess & Werkzeuge"):
                    render_steps(turn["events"], st)
            render_answer(turn["events"])

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
            render_answer(events)
            st.caption(f"📁 Alle Dateien dieser Frage: Seite **Ergebnisse** (Ordner `{os.path.basename(agent.run_dir)}`)")
        st.session_state.history.append({"prompt": prompt, "events": events})


st.navigation([
    st.Page(chat_page, title="Chat", icon="💬", default=True),
    st.Page(ergebnisse_page.page, title="Ergebnisse", icon="🗂️", url_path="ergebnisse"),
]).run()
