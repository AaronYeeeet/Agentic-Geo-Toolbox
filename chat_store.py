"""
Gespeicherte Chats: eine JSON-Datei pro Chat in output/chats/, damit Chats Neustarts überleben.

Gespeichert wird
  - der sichtbare Verlauf (Fragen, Denkprozess, Werkzeuge, Antworten, Ergebnisordner) und
  - der LLM-Kontext (agent.export_state()), damit das Modell nach dem Laden weiß, worum es ging.
Bei Modellwechsel (andere Einstellung in .env) wird der Kontext nur als Text (Fragen + Antworten) übernommen.
"""
import json
import os
import time

import geo_tools

CHAT_DIR = os.path.join(geo_tools.OUT, "chats")


def new_id():
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def _path(chat_id):
    return os.path.join(CHAT_DIR, f"{chat_id}.json")


def exists(chat_id):
    return bool(chat_id) and os.path.exists(_path(chat_id))


def save(chat_id, agent, turns):
    """Chat speichern (erst in eine Hilfsdatei, dann umbenennen: bei Absturz bleibt die alte Version heil)."""
    os.makedirs(CHAT_DIR, exist_ok=True)
    old = load(chat_id) if exists(chat_id) else {}
    try:
        state = agent.export_state()
    except Exception as err:  # Kontext nicht speicherbar -> beim Laden Notlösung über den Text
        state = {"error": str(err)}
    data = {
        "id": chat_id,
        "title": (turns[0]["prompt"] if turns else "Neuer Chat")[:120],
        "created": old.get("created") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": agent.label,
        "turns": turns,
        "llm_state": state,
    }
    tmp = _path(chat_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    os.replace(tmp, _path(chat_id))
    return _path(chat_id)


def load(chat_id):
    with open(_path(chat_id), encoding="utf-8") as f:
        return json.load(f)


def list_chats(limit=50):
    """[{id, title, updated, turns}] - zuletzt benutzte zuerst."""
    if not os.path.isdir(CHAT_DIR):
        return []
    chats = []
    for name in os.listdir(CHAT_DIR):
        if not name.endswith(".json"):
            continue
        try:
            d = load(name[:-5])
        except (OSError, json.JSONDecodeError):
            continue
        chats.append({"id": d["id"], "title": d.get("title", d["id"]), "updated": d.get("updated", ""),
                      "turns": len(d.get("turns", [])), "model": d.get("model", "")})
    return sorted(chats, key=lambda c: c["updated"], reverse=True)[:limit]


def delete(chat_id):
    if exists(chat_id):
        os.remove(_path(chat_id))


def restore(agent, data):
    """LLM-Kontext in den (neuen) Agenten laden. Gibt einen Hinweistext zurück, falls nur teilweise möglich."""
    turns = data.get("turns", [])
    state = data.get("llm_state") or {}
    if not turns:
        return None
    same_model = state.get("model") == getattr(agent, "model", None) and "error" not in state
    if same_model:
        try:
            agent.import_state(state)
            return None
        except Exception as err:
            note = f"Gesprächskontext konnte nicht vollständig geladen werden ({err})."
    else:
        note = f"Der Chat stammt von einem anderen Modell ({data.get('model')})."
    agent.import_transcript(turns)
    return note + " Das Modell kennt die bisherigen Fragen und Antworten, aber nicht die Werkzeug-Details."
