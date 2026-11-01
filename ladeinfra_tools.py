"""
Ladesäulen-Standortanalyse (Stufe 1, grobe Abschätzung): "Wo könnten E-Ladesäulen sinnvoll sein?"
Methode, Annahmen und Grenzen: docs/ladesaeulen.md

  ladesaeulen(lat, lon, ...) -> Bedarf (Zensus), Bestand (BNetzA + OSM), Verkehr (Fahrten-Simulation auf dem
                                Straßennetz), Stromnetz (Trafostationen aus OSM) und die besten Standorte

Ablauf:
  1. Bedarf je 100-m-Zelle: Einwohner x Pkw je Einwohner x E-Auto-Anteil x Anteil "muss öffentlich laden"
     (höher in Mehrfamilienhäusern, niedriger bei Eigentümern) x kWh je E-Auto und Tag; dazu Ziel-Laden an
     Supermärkten, Uni, Kliniken, Freizeit (POIs aus OSM)
  2. Versorgung je Ort mit der 2-Step-Floating-Catchment-Methode (2SFCA): Ladeangebot im Einzugsbereich
     (AC 400 m Fußweg, DC 2 km) geteilt durch den Bedarf, der darauf zugreift
  3. Verkehr: Fahrten Wohnen -> Ziele und Durchgangsverkehr auf dem Straßennetz (kürzeste Wege) -> Belastung je Straße
  4. Stromnetz: Abstand zur nächsten Trafostation / zum Umspannwerk (OSM), grobe Anschlusskosten und Zusatzlast
  5. Standorte (öffentliche Parkplätze + Straßenrand in Zellen mit großer Lücke) bewerten, schrittweise auswählen;
     nach jeder Wahl wird die Versorgung neu gerechnet (keine Häufung an einer Stelle)
"""
import math
import random

import networkx as nx
import numpy as np
import osmnx as ox
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, mapping

import impact_tools
import ladeinfra_data
import local_osm
from impact_tools import TO_UTM, TO_WGS, _edge_name, _out, _write_geojson

FROM_3035 = Transformer.from_crs("EPSG:3035", "EPSG:25832", always_xy=True)

# ---------- Annahmen (Größenordnungen; in docs/ladesaeulen.md begründet) ----------
PKW_JE_EINWOHNER = 0.45     # Darmstadt grob (Deutschland ca. 0,58; Uni-Stadt eher weniger)
KWH_JE_EAUTO_TAG = 6.4      # 13.000 km/Jahr x 0,18 kWh/km / 365
OEFFENTLICH_EFH = 0.10      # Anteil öffentliches Laden bei Ein-/Zweifamilienhaus (meist eigene Wallbox)
OEFFENTLICH_MFH = 0.60      # bei Mehrfamilienhaus (oft kein eigener Stellplatz)
ZIEL_ANTEIL = 0.15          # zusätzlicher Bedarf beim Einkaufen, Arbeiten, Freizeit (Anteil am Gesamtbedarf)
AUSLASTUNG = {"AC": 0.15, "DC": 0.10}   # Ziel-Auslastung öffentlicher Ladepunkte über 24 h
EINZUG_M = {"AC": 400, "DC": 2000}       # Einzugsbereich: zu Fuß (AC) bzw. kurzer Umweg (DC)
AC_KW, DC_KW = 11, 150                   # Leistung je neuem Ladepunkt
GLEICHZEITIGKEIT = {"AC": 0.5, "DC": 0.8}
TIEFBAU_EUR_JE_M = 150                   # Kabel + Tiefbau innerorts, grob
POI_GEWICHT = {
    ("shop", "supermarket"): 3, ("shop", "mall"): 4, ("shop", "department_store"): 3, ("shop", "doityourself"): 2,
    ("amenity", "university"): 4, ("amenity", "college"): 2, ("amenity", "hospital"): 3, ("amenity", "townhall"): 1,
    ("amenity", "cinema"): 1.5, ("amenity", "theatre"): 1, ("amenity", "restaurant"): 0.4, ("amenity", "cafe"): 0.2,
    ("leisure", "sports_centre"): 1.5, ("leisure", "stadium"): 2, ("leisure", "swimming_pool"): 1.5,
    ("leisure", "fitness_centre"): 1, ("tourism", "hotel"): 2, ("amenity", "parking", "park_ride"): 3,
}
MAIN_ROADS = {"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link"}
ANNAHMEN = {
    "pkw_je_einwohner": PKW_JE_EINWOHNER, "kwh_je_e_auto_und_tag": KWH_JE_EAUTO_TAG,
    "oeffentlich_laden_anteil": f"{OEFFENTLICH_EFH:.0%} (Ein-/Zweifamilienhaus) bis {OEFFENTLICH_MFH:.0%} (Mehrfamilienhaus), Eigentümer weniger",
    "ziel_laden_anteil": ZIEL_ANTEIL, "auslastung_ladepunkte": AUSLASTUNG,
    "einzugsbereich_m": EINZUG_M, "neue_ladepunkte_kw": {"AC": AC_KW, "DC": DC_KW},
}


def _w(d, r):
    """Gewicht nach Entfernung: 1 direkt daneben, linear bis 0 am Rand des Einzugsbereichs."""
    return np.clip(1 - d / r, 0, None)


def _dist(ax, ay, bx, by):
    return np.hypot(ax[:, None] - bx[None, :], ay[:, None] - by[None, :])


def _poi_weight(tags):
    for key, w in POI_GEWICHT.items():
        if len(key) == 3:
            if tags.get(key[0]) == key[1] and tags.get(key[2]) == "yes":
                return w
        elif tags.get(key[0]) == key[1]:
            return w
    if tags.get("office"):
        return 0.3  # Arbeitsplätze
    return 0


def _station_supply(kw, dc):
    return kw * 24 * AUSLASTUNG["DC" if dc else "AC"]


def ladesaeulen(lat, lon, radius_m=1500, e_auto_anteil=0.15, anzahl=10, prefix="ladesaeulen"):
    """Ladesäulen-Standorte im Umkreis radius_m um lat/lon für ein Szenario mit e_auto_anteil E-Autos am Pkw-Bestand."""
    warnings = []
    x0, y0 = TO_UTM.transform(lon, lat)
    pad = radius_m + EINZUG_M["DC"]
    dlat = pad / 111320
    dlon = pad / (111320 * math.cos(math.radians(lat)))
    bbox = (lat - dlat, lon - dlon, lat + dlat, lon + dlon)
    if not local_osm.covers((lat - radius_m / 111320, lon - radius_m / (111320 * math.cos(math.radians(lat))),
                             lat + radius_m / 111320, lon + radius_m / (111320 * math.cos(math.radians(lat))))):
        raise ValueError(f"Ort liegt außerhalb der vorbereiteten Region {local_osm.REGION} (Zensus/BNetzA/OSM lokal). "
                         "LOCAL_OSM_BBOX in .env anpassen und Daten neu vorbereiten.")
    data = ladeinfra_data.load()

    # ---------- 1. Bedarf: Wohnen (Zensus) ----------
    cx, cy = FROM_3035.transform(data["x"].astype(float), data["y"].astype(float))
    cx, cy = np.asarray(cx), np.asarray(cy)
    near = np.hypot(cx - x0, cy - y0) <= radius_m + EINZUG_M["AC"]
    cx, cy = cx[near], cy[near]
    pop = data["einwohner"][near]
    g1, g2 = data["1_Wohnung"][near], data["2_Wohnungen"][near]
    g36, g712, g13 = data["3bis6_Wohnungen"][near], data["7bis12_Wohnungen"][near], data["13undmehr_Wohnungen"][near]
    whg_mfh = 4.5 * g36 + 9.5 * g712 + 20 * g13
    whg = g1 + 2 * g2 + whg_mfh
    mfh = np.where(whg > 0, whg_mfh / np.maximum(whg, 1), 0.5)
    owner = data["eigentuemerquote"][near]
    owner = np.where(np.isnan(owner), np.nanmedian(owner) if np.isfinite(owner).any() else 0.5, owner)
    p_pub = np.clip((OEFFENTLICH_EFH + (OEFFENTLICH_MFH - OEFFENTLICH_EFH) * mfh) * (1.2 - 0.4 * owner), 0, 0.9)
    evs = pop * PKW_JE_EINWOHNER * e_auto_anteil
    d_res = evs * p_pub * KWH_JE_EAUTO_TAG

    # ---------- 1b. Bedarf: Ziele (POIs) + Objekte für Netz/Parken/Bestand aus OSM ----------
    pois, parks, power, osm_chargers = [], [], [], []
    s, w, n, e = bbox
    for la, lo, typ, oid, tags in local_osm.load()["objects"]:
        if not (s <= la <= n and w <= lo <= e):
            continue
        if tags.get("power") in ("substation", "transformer"):
            power.append((la, lo, tags))
        if tags.get("amenity") == "charging_station":
            osm_chargers.append((la, lo, tags))
        if tags.get("amenity") == "parking" and tags.get("access") not in ("private", "no", "permit", "delivery") \
                and tags.get("parking") != "underground":
            parks.append((la, lo, tags))
        wgt = _poi_weight(tags)
        if wgt:
            pois.append((la, lo, wgt, tags))
    px, py = (np.asarray(v) for v in TO_UTM.transform([p[1] for p in pois] or [lon], [p[0] for p in pois] or [lat]))
    pw = np.array([p[2] for p in pois]) if pois else np.zeros(1)
    pin = np.hypot(px - x0, py - y0) <= radius_m + EINZUG_M["AC"]
    total_ev_kwh = float((evs * KWH_JE_EAUTO_TAG).sum())
    d_poi = np.where(pin, pw, 0) / max(float(pw[pin].sum()), 1e-9) * total_ev_kwh * ZIEL_ANTEIL
    # alle Bedarfspunkte zusammen
    dx, dy = np.concatenate([cx, px]), np.concatenate([cy, py])
    demand = np.concatenate([d_res, d_poi])

    # ---------- 2. Bestand: BNetzA (amtlich) + OSM (nur wo BNetzA nichts kennt) ----------
    stations = []
    for st in data["stations"]:
        if s <= st["lat"] <= n and w <= st["lon"] <= e:
            dc = st["art"].startswith("Schnell") or st["kw"] >= 50
            stations.append({**st, "dc": dc, "quelle": "BNetzA"})
    bx, by = (np.asarray(v) for v in TO_UTM.transform([t["lon"] for t in stations] or [0], [t["lat"] for t in stations] or [0]))
    for la, lo, tags in osm_chargers:
        ox_, oy_ = TO_UTM.transform(lo, la)
        if stations and np.hypot(bx - ox_, by - oy_).min() < 50:
            continue
        try:
            pts = int(tags.get("capacity", "2"))
        except ValueError:
            pts = 2
        stations.append({"betreiber": tags.get("operator", "?"), "adresse": tags.get("name", ""), "ladepunkte": pts,
                         "kw": 11.0 * pts, "dc": False, "lat": la, "lon": lo, "quelle": "OSM", "art": "Normalladeeinrichtung"})
    sx, sy = (np.asarray(v) for v in TO_UTM.transform([t["lon"] for t in stations] or [0], [t["lat"] for t in stations] or [0]))
    sdc = np.array([t["dc"] for t in stations], bool) if stations else np.zeros(0, bool)
    supply = np.array([_station_supply(t["kw"], t["dc"]) for t in stations]) if stations else np.zeros(0)

    def coverage(sx, sy, sdc, supply):
        """2SFCA: Versorgungsgrad je Bedarfspunkt (1 = Bedarf gedeckt)."""
        acc = np.zeros(len(demand))
        for typ, mask in (("AC", ~sdc), ("DC", sdc)):
            if not mask.any():
                continue
            wgt = _w(_dist(sx[mask], sy[mask], dx, dy), EINZUG_M[typ])        # Stationen x Bedarf
            ratio = supply[mask] / np.maximum(wgt @ demand, 1e-9)              # Angebot je erreichbarem Bedarf
            acc += wgt.T @ ratio * (0.5 if typ == "DC" else 1.0)               # DC zählt fürs Wohnen nur halb
        return acc

    cov = coverage(sx, sy, sdc, supply)
    deficit = demand * np.clip(1 - cov, 0, 1)
    in_area = np.hypot(dx - x0, dy - y0) <= radius_m

    # ---------- 3. Verkehr: Fahrten-Simulation auf dem Straßennetz ----------
    G = ox.project_graph(impact_tools._load_graph(lat, lon, radius_m), to_crs="EPSG:25832")
    nodes = list(G.nodes)
    nx_, ny_ = np.array([G.nodes[k]["x"] for k in nodes]), np.array([G.nodes[k]["y"] for k in nodes])

    def nearest_node(xs, ys):
        out = []
        for i in range(0, len(xs), 500):
            out += list(np.argmin(_dist(np.asarray(xs[i:i + 500]), np.asarray(ys[i:i + 500]), nx_, ny_), axis=1))
        return [nodes[j] for j in out]

    rng = random.Random(42)
    res_nodes = nearest_node(cx, cy)
    poi_nodes = nearest_node(px, py) if pois else []
    rim = [k for k, xx, yy in zip(nodes, nx_, ny_) if math.hypot(xx - x0, yy - y0) > 0.8 * radius_m]
    flow = {}
    n_trips = 0
    origins = rng.choices(range(len(res_nodes)), weights=np.maximum(pop, 0) + 1e-6, k=90)
    dest_pool = poi_nodes + res_nodes
    dest_w = list(pw * 3 if pois else []) + list(np.maximum(pop, 0) * 0.02 + 1e-6)
    for i, oi in enumerate(origins + [None] * 40):
        src = res_nodes[oi] if oi is not None else rng.choice(rim)   # 40 Startpunkte am Rand = Durchgangsverkehr
        try:
            pred, _ = nx.dijkstra_predecessor_and_distance(G, src, weight="length")
        except nx.NetworkXError:
            continue
        targets = rng.choices(dest_pool, weights=dest_w, k=12) if oi is not None else rng.sample(rim, min(12, len(rim)))
        for t in targets:
            if t not in pred or t == src:
                continue
            p = [t]
            while p[-1] != src:          # Weg rückwärts über die Vorgänger zusammensetzen
                p.append(pred[p[-1]][0])
            p.reverse()
            n_trips += 1
            for u, v in zip(p[:-1], p[1:]):
                flow[(u, v)] = flow.get((u, v), 0) + 1
    edges = ox.graph_to_gdfs(G, nodes=False)
    eflow, egeom, ename, emain = [], [], [], []
    for (u, v, k), row in edges.iterrows():
        f = flow.get((u, v), 0) + flow.get((v, u), 0)
        eflow.append(f)
        egeom.append(row.geometry)
        ename.append(_edge_name(row))
        hw = row.get("highway")
        emain.append(any(h in MAIN_ROADS for h in (hw if isinstance(hw, list) else [hw])))
    eflow = np.array(eflow, float)
    fmax = max(float(np.percentile(eflow[eflow > 0], 98)) if (eflow > 0).any() else 1, 1)
    etree = shapely.STRtree(egeom)

    def street_name(x, y):
        return ename[int(etree.nearest(Point(x, y)))]

    def traffic_at(x, y, r=50):
        idx = etree.query(Point(x, y).buffer(r))
        if not len(idx):
            return 0.0, False
        return float(min(1, eflow[idx].max() / fmax)), bool(np.array(emain)[idx].any())

    # ---------- 4. Stromnetz (Lage der Stationen aus OSM) ----------
    gx, gy = (np.asarray(v) for v in TO_UTM.transform([p[1] for p in power] or [lon], [p[0] for p in power] or [lat]))

    def grid_at(x, y):
        if not power:
            return 9999.0, None
        d = np.hypot(gx - x, gy - y)
        j = int(np.argmin(d))
        return float(d[j]), j

    # ---------- 5. Kandidaten bewerten und schrittweise auswählen ----------
    cands = []
    for la, lo, tags in parks:
        x, y = TO_UTM.transform(lo, la)
        if math.hypot(x - x0, y - y0) > radius_m:
            continue
        try:
            cap = int(tags.get("capacity", ""))
        except ValueError:
            cap = {"multi-storey": 200, "surface": 25, "street_side": 8, "lane": 8}.get(tags.get("parking", "surface"), 20)
        cands.append({"x": x, "y": y, "art": "Parkplatz", "name": tags.get("name") or "", "stellplaetze": cap,
                      "kunden": tags.get("access") == "customers"})
    for i in np.argsort(-deficit * in_area)[:40]:   # Straßenrand (Laternenladen) in Zellen mit großer Lücke
        if i < len(cx) and deficit[i] > 0:
            cands.append({"x": float(dx[i]), "y": float(dy[i]), "art": "Straßenrand", "name": "", "stellplaetze": 6,
                          "kunden": False})
    if not cands:
        raise ValueError("Keine geeigneten Flächen im Gebiet gefunden.")
    kx, ky = np.array([c["x"] for c in cands]), np.array([c["y"] for c in cands])
    for c in cands:
        c["verkehr"], c["hauptstrasse"] = traffic_at(c["x"], c["y"])
        c["netz_m"], c["netz_idx"] = grid_at(c["x"], c["y"])
        c["strasse"] = street_name(c["x"], c["y"])
    w_ac = _w(_dist(kx, ky, dx, dy), EINZUG_M["AC"])        # Kandidaten x Bedarfspunkte
    w_dc = _w(_dist(kx, ky, dx, dy), EINZUG_M["DC"])

    chosen, picked = [], set()
    max_dc = max(1, anzahl // 4)   # Innenstadt braucht vor allem Normalladen; Schnellladen nur an wenigen Knoten
    deficit_now = deficit.copy()
    luecke0 = max(float((w_ac @ deficit).max()), 1e-9)
    luecke0_dc = max(float((w_dc @ deficit).max()), 1e-9)
    for _ in range(anzahl):
        lac, ldc = w_ac @ deficit_now / luecke0, w_dc @ deficit_now / luecke0_dc
        best, best_score = None, -1
        for j, c in enumerate(cands):
            if j in picked or any(math.hypot(c["x"] - o["x"], c["y"] - o["y"]) < 250 for o in chosen):
                continue
            netz_ac = float(np.clip(1 - (c["netz_m"] - 150) / 450, 0, 1))
            netz_dc = float(np.clip(1 - (c["netz_m"] - 100) / 900, 0, 1))
            groesse = min(1.0, c["stellplaetze"] / 50)
            s_ac = 0.55 * lac[j] + 0.2 * netz_ac + 0.15 * groesse + 0.1 * c["verkehr"]
            dc_ok = c["hauptstrasse"] and c["art"] == "Parkplatz" and sum(o["typ"] == "DC" for o in chosen) < max_dc
            s_dc = (0.4 * c["verkehr"] + 0.3 * netz_dc + 0.2 * ldc[j] + 0.1 * groesse) if dc_ok else 0
            typ, score = ("DC", s_dc) if s_dc > s_ac else ("AC", s_ac)
            if score > best_score:
                best, best_score = (j, typ, {"luecke": float(lac[j] if typ == "AC" else ldc[j]),
                                             "netz": netz_ac if typ == "AC" else netz_dc,
                                             "groesse": groesse, "verkehr": c["verkehr"]}), score
        if best is None or best_score <= 0.05:
            break
        j, typ, parts = best
        c = cands[j]
        local = float((w_ac[j] if typ == "AC" else w_dc[j]) @ deficit_now)
        per_point = _station_supply(AC_KW if typ == "AC" else DC_KW, typ == "DC")
        points = int(np.clip(round(local / per_point), 2, 10 if typ == "AC" else 4))
        new_supply = points * per_point
        # Simulation: neuer Standort deckt Bedarf in seinem Einzugsbereich -> Lücke dort kleiner
        wcol = (w_ac if typ == "AC" else w_dc)[j]
        served = np.minimum(deficit_now, wcol * deficit_now / max(float(wcol @ deficit_now), 1e-9) * new_supply)
        deficit_now = deficit_now - served
        picked.add(j)
        dist_grid = c["netz_m"]
        gruende = []
        if parts["luecke"] > 0.5:
            gruende.append("große Versorgungslücke in der Umgebung")
        elif parts["luecke"] > 0.2:
            gruende.append("mittlere Versorgungslücke")
        if c["verkehr"] > 0.5:
            gruende.append("viel Verkehr (Simulation)" + (" an Hauptstraße" if c["hauptstrasse"] else ""))
        if dist_grid < 200:
            gruende.append(f"Trafostation nur {round(dist_grid)} m entfernt")
        if c["kunden"]:
            gruende.append("Kundenparkplatz (Laden beim Einkaufen)")
        if c["stellplaetze"] >= 50:
            gruende.append(f"großer Parkplatz (ca. {c['stellplaetze']} Stellplätze)")
        chosen.append({**c, "typ": typ, "score": best_score, "ladepunkte": points, "parts": parts,
                       "gedeckt_kwh_tag": float(served[in_area].sum()), "gruende": gruende,
                       "anschluss_kosten_eur": round(dist_grid * TIEFBAU_EUR_JE_M, -3) if dist_grid < 9999 else None,
                       "spitzenlast_kw": round(points * (AC_KW if typ == "AC" else DC_KW) * GLEICHZEITIGKEIT[typ])})

    # ---------- Ergebnisse: Karte ----------
    def cell_poly(x3035, y3035):
        xs_, ys_ = FROM_3035.transform([x3035 - 50, x3035 + 50, x3035 + 50, x3035 - 50],
                                       [y3035 - 50, y3035 - 50, y3035 + 50, y3035 + 50])
        lo_, la_ = TO_WGS.transform(xs_, ys_)
        return Polygon(list(zip(lo_, la_)))

    x3035, y3035 = data["x"][near], data["y"][near]
    cell_def = deficit[:len(cx)]
    cell_cov = cov[:len(cx)]
    colors = [(1.0, "#7f0000"), (0.5, "#d7301f"), (0.2, "#fc8d59"), (0.05, "#fdcc8a")]
    bedarf_feats = []
    for i in np.nonzero((cell_def >= 0.05) & (np.hypot(cx - x0, cy - y0) <= radius_m))[0]:
        col = next(c for t, c in colors if cell_def[i] >= t)
        bedarf_feats.append({"type": "Feature", "geometry": mapping(cell_poly(x3035[i], y3035[i])), "properties": {
            "name": "Versorgungslücke", "_style": {"color": col, "fillColor": col, "fillOpacity": 0.45, "weight": 0},
            "_popup": f"<b>Fehlender Ladebedarf ca. {cell_def[i]:.1f} kWh/Tag</b><br>{int(pop[i])} Einwohner, "
                      f"ca. {evs[i]:.0f} E-Autos, {mfh[i]:.0%} Wohnungen in Mehrfamilienhäusern<br>"
                      f"Versorgungsgrad heute {min(cell_cov[i], 9.99):.0%}"}})

    verkehr_feats = []
    top = eflow >= np.percentile(eflow[eflow > 0], 70) if (eflow > 0).any() else np.zeros(len(eflow), bool)
    for f_, g_, nm in zip(eflow[top], np.array(egeom, dtype=object)[top], np.array(ename, dtype=object)[top]):
        verkehr_feats.append({"type": "Feature", "geometry": mapping(shapely.transform(
            g_, lambda c: np.column_stack(TO_WGS.transform(c[:, 0], c[:, 1])))), "properties": {
            "name": nm, "_style": {"color": "#6a51a3", "weight": 1 + round(6 * min(1, f_ / fmax)), "opacity": 0.6},
            "_popup": f"<b>{nm}</b><br>{int(f_)} von {n_trips} simulierten Fahrten"}})

    netz_feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]}, "properties": {
        "name": t.get("name") or "Trafostation", "_style": {"radius": 5, "fillColor": "#ffd700", "color": "#333", "weight": 1},
        "_popup": f"<b>{t.get('name') or ('Umspannwerk' if t.get('substation') in ('distribution', 'transmission') else 'Trafostation')}</b>"
                  f"<br>OSM: power={t.get('power')} {t.get('substation', '')} {t.get('voltage', '')}"}}
        for (la, lo, t), xx, yy in zip(power, gx, gy) if math.hypot(xx - x0, yy - y0) <= radius_m + 300]

    bestand_feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]}, "properties": {
        "name": t["betreiber"], "_style": {"radius": 6, "fillColor": "#0570b0" if t["dc"] else "#41ab5d",
                                           "color": "#fff", "weight": 1},
        "_popup": f"<b>{'Schnellladen' if t['dc'] else 'Normalladen'}</b> ({t['quelle']})<br>{t['betreiber']}<br>"
                  f"{t['adresse']}<br>{t['ladepunkte']} Ladepunkte, {t['kw']:.0f} kW"}} for t, xx, yy in zip(stations, sx, sy) if math.hypot(xx - x0, yy - y0) <= radius_m + 300]

    standort_feats, top_list = [], []
    for rank, c in enumerate(chosen, 1):
        lo_, la_ = TO_WGS.transform(c["x"], c["y"])
        typ_txt = "AC-Normalladen" if c["typ"] == "AC" else "DC-Schnellladen"
        where = (c["name"] + ", " if c["name"] else "") + f"{c['art']} bei {c['strasse']}"
        standort_feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo_, la_]}, "properties": {
            "name": f"{rank}. {where}", "_style": {"radius": 12, "fillColor": "#e31a1c", "color": "#000", "weight": 2},
            "_popup": f"<b>{rank}. {where}</b><br>{typ_txt}: {c['ladepunkte']} Ladepunkte<br>Bewertung {c['score']:.2f} "
                      f"(Lücke {c['parts']['luecke']:.2f}, Netz {c['parts']['netz']:.2f}, Verkehr {c['verkehr']:.2f}, "
                      f"Größe {c['parts']['groesse']:.2f})<br>" + "<br>".join(c["gruende"]) +
                      f"<br>Nächste Trafostation ca. {round(c['netz_m'])} m"}})
        top_list.append({"rang": rank, "ort": where, "typ": typ_txt, "ladepunkte": c["ladepunkte"],
                         "bewertung": round(c["score"], 2), "gruende": c["gruende"],
                         "naechste_trafostation_m": round(c["netz_m"]) if c["netz_m"] < 9999 else None,
                         "anschluss_kosten_grob_eur": c["anschluss_kosten_eur"],
                         "zusaetzliche_spitzenlast_kw": c["spitzenlast_kw"],
                         "deckt_bedarf_kwh_tag": round(c["gedeckt_kwh_tag"])})

    # Zusatzlast je Trafostation (mehrere Standorte an derselben Station)
    last = {}
    for c in chosen:
        if c["netz_idx"] is not None:
            last[c["netz_idx"]] = last.get(c["netz_idx"], 0) + c["spitzenlast_kw"]
    trafo_last = sorted(({"station": power[k][2].get("name") or f"Trafostation bei {street_name(gx[k], gy[k])}",
                          "zusaetzliche_spitzenlast_kw": v} for k, v in last.items()),
                        key=lambda t: -t["zusaetzliche_spitzenlast_kw"])[:5]

    files = {
        "bedarf": _write_geojson(_out(f"{prefix}_bedarf.geojson"), bedarf_feats),
        "verkehr": _write_geojson(_out(f"{prefix}_verkehr.geojson"), verkehr_feats),
        "netz": _write_geojson(_out(f"{prefix}_netz.geojson"), netz_feats),
        "bestand": _write_geojson(_out(f"{prefix}_bestand.geojson"), bestand_feats),
        "standorte": _write_geojson(_out(f"{prefix}_standorte.geojson"), standort_feats),
    }
    in_st = np.hypot(sx - x0, sy - y0) <= radius_m if len(stations) else np.zeros(0, bool)
    demand_area, deficit_area = float(demand[in_area].sum()), float(deficit[in_area].sum())
    if len(power) < 20:
        warnings.append(f"Nur {len(power)} Trafostationen/Umspannwerke in OSM: Netzbewertung sehr unsicher.")
    return {
        "files": files,
        "szenario": {
            "e_auto_anteil": e_auto_anteil, "einwohner": int(pop[np.hypot(cx - x0, cy - y0) <= radius_m].sum()),
            "e_autos": int(evs[np.hypot(cx - x0, cy - y0) <= radius_m].sum()),
            "oeffentlicher_ladebedarf_kwh_tag": round(demand_area),
            "davon_ziel_laden_kwh_tag": round(float(d_poi[pin & (np.hypot(px - x0, py - y0) <= radius_m)].sum())),
            "bestand_ladepunkte": int(sum(t["ladepunkte"] for t, m in zip(stations, in_st) if m)),
            "bestand_davon_schnellladen": int(sum(t["ladepunkte"] for t, m in zip(stations, in_st) if m and t["dc"])),
            "nicht_gedeckt_kwh_tag": round(deficit_area),
            "fehlende_ladepunkte_ac_aequivalent": round(deficit_area / _station_supply(AC_KW, False)),
            "vorschlaege_decken_kwh_tag": round(sum(c["gedeckt_kwh_tag"] for c in chosen)),
        },
        "standorte": top_list,
        "trafostationen_mit_zusatzlast": trafo_last,
        "verkehr_simulation": f"{n_trips} simulierte Fahrten (Wohnen -> Ziele und Durchgangsverkehr, kürzester Weg)",
        "annahmen": ANNAHMEN,
        "datenquellen": [ladeinfra_data.STAND["zensus"] + ": Einwohner, Gebäude nach Wohnungen, Eigentümerquote (100 m)",
                         ladeinfra_data.STAND["bnetza"] + f" ({sum(1 for t in stations if t['quelle'] == 'BNetzA')} Einrichtungen im Umfeld), ergänzt um OSM",
                         f"OSM lokal (Stand {local_osm.stand()}): Parkplätze, Ziele, Straßennetz, {len(power)} Trafostationen/Umspannwerke"],
        "warnungen": warnings,
        "hinweis": "Grobe Abschätzung mit Annahmen, keine Planung: keine echten Netzkapazitäten (nur Lage der "
                   "Stationen aus OSM, unvollständig), Verkehr nur als Simulation ohne echte Zählungen, Flächen "
                   "nicht auf Verfügbarkeit/Eigentum geprüft.",
    }
