"""
Annahmen der eigenen Analyse-Werkzeuge: zentral beschrieben, vom Agenten anpassbar, im Ergebnis als Tabelle.

Jedes Werkzeug definiert ein dict  {schlüssel: {"wert": ..., "einheit": "...", "info": "..."}}.
  werte, tabelle = annahmen.anwenden(DEFAULTS, overrides)
    -> werte:   {schlüssel: wert} mit den Änderungen des Agenten
    -> tabelle: [{"annahme", "wert", "einheit", "standard", "geaendert"}] fürs Ergebnis (Agent zeigt sie als Tabelle)
  annahmen.schema(DEFAULTS) -> JSON-Schema für den Parameter "annahmen" des Werkzeugs
Werte dürfen Zahlen, Texte oder dicts von Zahlen sein (z.B. Abflussbeiwert je Bodenart); bei dicts reicht es,
einzelne Einträge zu ändern.
"""
import copy


def anwenden(defaults, overrides=None):
    overrides = overrides or {}
    unbekannt = [k for k in overrides if k not in defaults]
    if unbekannt:
        raise ValueError(f"Unbekannte Annahme(n): {', '.join(unbekannt)}. Erlaubt: {', '.join(defaults)}")
    werte, tabelle = {}, []
    for key, spec in defaults.items():
        std = spec["wert"]
        val = copy.deepcopy(std)
        if key in overrides and overrides[key] is not None:
            new = overrides[key]
            if isinstance(std, dict):
                if not isinstance(new, dict):
                    raise ValueError(f"Annahme '{key}' erwartet Einträge {list(std)}, z.B. {{\"{next(iter(std))}\": ...}}")
                falsch = [k for k in new if k not in std]
                if falsch:
                    raise ValueError(f"Annahme '{key}': unbekannte Einträge {falsch}. Erlaubt: {list(std)}")
                val.update({k: float(v) for k, v in new.items()})
            elif isinstance(std, bool):  # auch "false"/"nein" als Text richtig lesen
                val = new if isinstance(new, bool) else str(new).strip().lower() in ("1", "true", "ja", "yes", "wahr")
            elif isinstance(std, (int, float)):
                val = type(std)(float(new)) if isinstance(std, int) and float(new).is_integer() else float(new)
            else:
                val = new
        werte[key] = val
        tabelle.append({"annahme": spec["info"], "schluessel": key, "wert": val, "einheit": spec.get("einheit", ""),
                        **({"standard": std} if val != std else {}), "geaendert": val != std,
                        "wichtig": bool(spec.get("wichtig"))})
    return werte, tabelle


def wichtig(defaults, *keys):
    """Annahmen markieren, die der Agent in seiner Antwort-Tabelle immer zeigen soll."""
    for k in keys:
        defaults[k]["wichtig"] = True


def _typ(v):
    if isinstance(v, bool):
        return {"type": "boolean"}
    if isinstance(v, (int, float)):
        return {"type": "number"}
    if isinstance(v, dict):
        return {"type": "object", "properties": {k: {"type": "number"} for k in v}}
    return {"type": "string"}


def schema(defaults):
    """JSON-Schema für den Werkzeug-Parameter 'annahmen' (alle Schlüssel optional, Beschreibung mit Standardwert)."""
    props = {}
    for key, spec in defaults.items():
        p = _typ(spec["wert"])
        p["description"] = f"{spec['info']} [{spec.get('einheit', '')}], Standard {spec['wert']}"
        props[key] = p
    return {"type": "object", "properties": props,
            "description": "Optional: Annahmen ändern (nur die genannten, Rest bleibt Standard). "
                           "Ergebnis enthält immer die Tabelle 'annahmen'."}
