"""
Freie Datenquellen für den Geo-Agenten: ein Katalog, eine Abfrage-Funktion.

Jede Quelle ist eine kleine Funktion, die einen offenen Dienst OHNE API-Key abfragt und
  - eine kurze Zusammenfassung für das LLM liefert (mit Anbieter, Lizenz, Stand) und
  - wo sinnvoll GeoJSON-Dateien (EPSG:4326) für make_map / QGIS in den Ergebnisordner der Frage schreibt.
Rasterdaten (Satellitenbilder, ESA WorldCover, Wärmeinsel-Karten) liest GDAL aus der QGIS-Installation direkt
aus dem Netz (geo_tools.gdal), WFS-Dienste lädt ogr2ogr. Es wird nichts modelliert: die Quellen liefern Daten.

  katalog(kategorie=None, suche=None)               -> Liste der Quellen mit Parametern
  abfragen(quelle, lat, lon, radius_m, parameter)   -> {"quelle": {...}, "zusammenfassung": ..., "files": {...}}
  python datenquellen.py test [quelle ...]          -> alle (oder einzelne) Quellen am Luisenplatz Darmstadt testen
  python datenquellen.py liste                      -> Katalog als Markdown-Tabelle
"""
import datetime
import gzip
import hashlib
import html
import io
import json
import math
import os
import re
import sys
import time
import uuid
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
import shapely
from shapely.geometry import Point, box, mapping, shape

import geo_tools
import local_osm

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(geo_tools.CACHE_DIR, "datenquellen")
UA = {"User-Agent": "Geo-Agent TU Darmstadt (Lehrprojekt uni-qgis-prototype)"}
HLNUG = "https://geodienste-umwelt.hessen.de/arcgis/rest/services"
CDC = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/"

TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
FROM_3035 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
TO_31467 = Transformer.from_crs("EPSG:4326", "EPSG:31467", always_xy=True)
TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)

RAMP_HITZE = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]
RAMP_GRUEN = ["#f7fcf5", "#c7e9c0", "#74c476", "#238b45", "#00441b"]
RAMP_VERSIEGELT = ["#fff5eb", "#fdd0a2", "#fd8d3c", "#d94801", "#7f2704"]
RAMP_BLAU = ["#eff3ff", "#9ecae1", "#4292c6", "#08519c", "#08306b"]
RAMP_LILA = ["#fcfbfd", "#dadaeb", "#9e9ac8", "#6a51a3", "#3f007d"]
PALETTE = ["#1f78b4", "#33a02c", "#e31a1c", "#ff7f00", "#6a3d9a", "#b15928", "#a6cee3", "#b2df8a", "#fb9a99",
           "#fdbf6f", "#cab2d6", "#ffff99"]

QUELLEN = {}


def quelle(id, name, kategorie, anbieter, lizenz, url, beschreibung, art="umkreis", radius=500, max_radius=5000,
           parameter=None):
    """Registriert eine Datenquelle. art: punkt (lat/lon), umkreis (lat/lon + radius_m), global, suche."""
    def deco(fn):
        QUELLEN[id] = {"id": id, "name": name, "kategorie": kategorie, "anbieter": anbieter, "lizenz": lizenz,
                       "url": url, "beschreibung": beschreibung, "art": art, "radius": radius,
                       "max_radius": max_radius, "parameter": parameter or {}, "fn": fn}
        return fn
    return deco


# =====================================================================================================
# Hilfsfunktionen
# =====================================================================================================
def _http(url, params=None, body=None, timeout=20, cache_h=0, fmt="json", headers=None):
    """GET (oder POST mit JSON-Body) mit Datei-Cache. fmt: json | text | bytes."""
    key = hashlib.sha1(json.dumps([url, params, body], sort_keys=True, default=str).encode()).hexdigest()[:24]
    path = os.path.join(CACHE, key + {"json": ".json", "text": ".txt", "bytes": ".bin"}[fmt])
    if cache_h and os.path.exists(path) and time.time() - os.path.getmtime(path) < cache_h * 3600:
        with open(path, "rb") as f:
            raw = f.read()
    else:
        h = {**UA, **(headers or {})}
        if body is not None:
            r = requests.post(url, params=params, json=body, headers=h, timeout=timeout)
        else:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"{url.split('?')[0]} antwortet mit HTTP {r.status_code}: {r.text[:200]}")
        raw = r.content
        if fmt == "json":
            json.loads(raw.decode("utf-8-sig", errors="replace"))  # kaputte Antwort nicht cachen
        if cache_h:
            os.makedirs(CACHE, exist_ok=True)
            tmp = f"{path}.{uuid.uuid4().hex[:6]}.tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
            try:
                os.replace(tmp, path)
            except OSError:
                os.remove(tmp)
    if fmt == "bytes":
        return raw
    text = raw.decode("utf-8-sig", errors="replace")
    return json.loads(text) if fmt == "json" else text


def _tmp(ext):
    os.makedirs(os.path.join(CACHE, "tmp"), exist_ok=True)
    return os.path.join(CACHE, "tmp", uuid.uuid4().hex + ext)


def _rm(*paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def _parallel(fn, items, n=8):
    """fn auf alle items anwenden (Threads). Fehler kommen als Exception-Objekt zurück."""
    def safe(x):
        try:
            return fn(x)
        except Exception as err:
            return err
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(safe, items))


def _liste(v, typ=str):
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, str):
        v = v.strip()
        v = json.loads(v) if v.startswith("[") else [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, (list, tuple)):
        v = [v]
    return [typ(x) for x in v]


def _bbox(lat, lon, r):
    dlat = r / 111320.0
    dlon = r / (111320.0 * math.cos(math.radians(lat)))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def _dist(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _rows(block, rename=None):
    """Open-Meteo-Block {"time": [...], "x": [...]} -> Liste von Zeilen."""
    rename = rename or {}
    keys = list(block)
    return [{rename.get(k, k): v for k, v in zip(keys, vals)} for vals in zip(*(block[k] for k in keys))]


def _popup(title, props):
    rows = "".join(f"<tr><td><b>{html.escape(str(k))}</b></td><td>{html.escape(str(v))}</td></tr>"
                   for k, v in props.items() if v not in (None, "", [], {}) and not str(k).startswith("_"))
    return f"<b>{html.escape(str(title))}</b><table>{rows}</table>"


def _pt(lon, lat, props, title=None, color=None):
    p = dict(props)
    p["name"] = str(title or p.get("name") or "")
    p["_popup"] = _popup(p["name"], props)
    if color:
        p["_style"] = {"fillColor": color}
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": p}


def _save(name, features):
    path = geo_tools.out_path(name if name.endswith(".geojson") else name + ".geojson")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)
    return path


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _ramp(v, lo, hi, colors):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "#999999"
    t = min(max((v - lo) / ((hi - lo) or 1), 0.0), 1.0) * (len(colors) - 1)
    i = min(int(t), len(colors) - 2)
    f = t - i
    a, b = _hex(colors[i]), _hex(colors[i + 1])
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def _style(color, opacity=0.5, weight=1):
    return {"color": color, "fillColor": color, "fillOpacity": opacity, "weight": weight}


def _attrs(d):
    """Technische Felder (OBJECTID, Shape ...) weglassen."""
    return {k: v for k, v in (d or {}).items()
            if v not in (None, "", "Null", " ") and not str(k).startswith("_")
            and not re.match(r"(?i)^(objectid|fid|shape|globalid|st_area|st_length|id$|gml_id)", str(k))}


def _geom(f):
    try:
        g = shape(f["geometry"])
        return g if g.is_valid else g.buffer(0)
    except Exception:
        return None


def _to3035(g):
    return shapely.transform(g, lambda c: np.column_stack(TO_3035.transform(c[:, 0], c[:, 1])))


def _area_m2(g):
    return _to3035(g).area


def _clip(features, bbox):
    s, w, n, e = bbox
    b = box(w, s, e, n)
    out = []
    for f in features:
        g = _geom(f)
        if g is None:
            continue
        if g.geom_type in ("Point", "MultiPoint"):
            if g.intersects(b):
                out.append(f)
            continue
        g2 = g.intersection(b)
        if not g2.is_empty:
            out.append({**f, "geometry": mapping(g2)})
    return out


def _flaechen(features, key_fn, lat, lon, bbox):
    """Flächenanteil je Klasse im Ausschnitt (Prozent) und Klassen am Punkt."""
    s, w, n, e = bbox
    b = box(w, s, e, n)
    total = _area_m2(b)
    pt = Point(lon, lat)
    shares, am_punkt = {}, []
    for f in features:
        g = _geom(f)
        if g is None:
            continue
        k = key_fn(f.get("properties") or {})
        if g.geom_type in ("Polygon", "MultiPolygon"):
            shares[k] = shares.get(k, 0.0) + _area_m2(g.intersection(b))
        if g.buffer(0.00002).contains(pt) and k not in am_punkt:
            am_punkt.append(k)
    anteile = {str(k): round(100 * v / total, 1) for k, v in sorted(shares.items(), key=lambda kv: -kv[1]) if v > 0}
    return anteile, am_punkt


def _first(props, *patterns):
    """Ersten Wert, dessen Feldname zu einem Muster passt (z.B. 'NAME')."""
    for pat in patterns:
        for k, v in props.items():
            if re.search(pat, str(k), re.I) and v not in (None, "", " "):
                return v
    return None


def _asc_value(text, x, y):
    """Wert einer ESRI-ASCII-Rasterdatei am Punkt (x, y in der Projektion der Datei)."""
    lines = text.splitlines()
    hdr, i = {}, 0
    while i < len(lines) and lines[i].split() and lines[i].split()[0][0].isalpha():
        k, v = lines[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    nc, nr, cs = int(hdr["ncols"]), int(hdr["nrows"]), hdr["cellsize"]
    x0 = hdr["xllcorner"] if "xllcorner" in hdr else hdr["xllcenter"] - cs / 2
    y0 = hdr["yllcorner"] if "yllcorner" in hdr else hdr["yllcenter"] - cs / 2
    col, row = int((x - x0) // cs), nr - 1 - int((y - y0) // cs)
    if not (0 <= col < nc and 0 <= row < nr):
        return None
    data = [ln for ln in lines[i:] if ln.strip()]
    if len(data) == nr:
        val = float(data[row].split()[col])
    else:
        val = float(" ".join(data).split()[row * nc + col])
    nd = hdr.get("nodata_value")
    return None if nd is not None and abs(val - nd) < 1e-6 else val


def _gdal_area(src, lat, lon, r, res, resampling="near"):
    """Rasterausschnitt um den Punkt mit GDAL (aus QGIS) lesen, in EPSG:3035 mit Zellgröße res.
    -> (array, x_links, y_oben, zellgröße); Zeilen von Nord nach Süd, NaN = keine Daten."""
    x, y = TO_3035.transform(lon, lat)
    n = max(2, int(math.ceil(2 * r / res)))
    half = n * res / 2
    tif, xyz = _tmp(".tif"), _tmp(".xyz")
    try:
        geo_tools.gdal("gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:3035", "-te", x - half, y - half, x + half,
                       y + half, "-ts", n, n, "-r", resampling, "-ot", "Float32", "-dstnodata", "-9999", src, tif)
        geo_tools.gdal("gdal_translate", "-q", "-of", "XYZ", tif, xyz)
        d = np.loadtxt(xyz, ndmin=2)
    finally:
        _rm(tif, xyz, tif + ".aux.xml")
    a = d[:, 2].reshape(n, n)
    a[a == -9999] = np.nan
    return a, x - half, y + half, 2 * half / n


def _grid(a, x0, ytop, res, color_fn, label, einheit="", fmt="{:.0f}", max_side=60, mode=False, namen=None, min_wert=None):
    """Raster (EPSG:3035) als GeoJSON-Kacheln für die Karte, bei Bedarf zusammengefasst (Mittel bzw. häufigste Klasse).
    min_wert: kleinere Werte nicht zeichnen (z.B. 0 % Bäume), damit der Kartenhintergrund sichtbar bleibt."""
    k = max(1, math.ceil(max(a.shape) / max_side))
    if k > 1:
        H, W = math.ceil(a.shape[0] / k) * k, math.ceil(a.shape[1] / k) * k
        pad = np.full((H, W), np.nan)
        pad[:a.shape[0], :a.shape[1]] = a
        b = pad.reshape(H // k, k, W // k, k).transpose(0, 2, 1, 3).reshape(H // k, W // k, k * k)
        if mode:
            agg = np.full(b.shape[:2], np.nan)
            for i in range(b.shape[0]):
                for j in range(b.shape[1]):
                    v = b[i, j][~np.isnan(b[i, j])]
                    if v.size:
                        u, c = np.unique(v, return_counts=True)
                        agg[i, j] = u[c.argmax()]
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                agg = np.nanmean(b, axis=2)
        a, res = agg, res * k
    rows, cols = np.nonzero(~np.isnan(a) & (a >= min_wert if min_wert is not None else True))
    xs, ys = x0 + cols * res, ytop - rows * res
    corners = [FROM_3035.transform(xs + dx, ys - dy) for dx, dy in ((0, 0), (res, 0), (res, res), (0, res))]
    feats = []
    for i in range(len(rows)):
        v = float(a[rows[i], cols[i]])
        ring = [[round(float(corners[c][0][i]), 6), round(float(corners[c][1][i]), 6)] for c in (0, 1, 2, 3, 0)]
        txt = namen.get(int(v), str(v)) if namen else f"{fmt.format(v)} {einheit}".strip()
        col = color_fn(v)
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {label: round(v, 3), "name": txt, "_popup": f"{label}: {txt}",
                                     "_style": {"color": col, "fillColor": col, "fillOpacity": 0.6, "weight": 0}}})
    return feats


def _stat(a):
    v = a[~np.isnan(a)]
    if not v.size:
        return {}
    return {"mittel": round(float(v.mean()), 2), "min": round(float(v.min()), 2), "max": round(float(v.max()), 2),
            "p10": round(float(np.percentile(v, 10)), 2), "p90": round(float(np.percentile(v, 90)), 2)}


def _mitte(a):
    v = a[a.shape[0] // 2, a.shape[1] // 2]
    return None if np.isnan(v) else round(float(v), 2)


def _abdeckung(a):
    return round(100 * float((~np.isnan(a)).mean()), 1)


def _lokalzeit(iso):
    try:
        from zoneinfo import ZoneInfo
        t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return t.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m. %H:%M")
    except Exception:
        return iso


def _sommer_jahr():
    heute = datetime.date.today()
    return heute.year if heute.month >= 10 else heute.year - 1


# ---------- ArcGIS-REST (HLNUG & Co.) ----------
def _arc_query(mapserver, layer, bbox, max_n=2000, where="1=1"):
    s, w, n, e = bbox
    params = {"geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "where": where, "outFields": "*", "returnGeometry": "true",
              "resultRecordCount": max_n, "maxAllowableOffset": 0.00002, "geometryPrecision": 6, "f": "geojson"}
    j = _http(f"{mapserver}/{layer}/query", params, cache_h=24 * 7, timeout=30)
    if "error" in j:  # manche Ebenen können kein resultRecordCount
        params.pop("resultRecordCount")
        j = _http(f"{mapserver}/{layer}/query", params, cache_h=24 * 7, timeout=30)
    if "error" in j:
        raise RuntimeError(f"ArcGIS-Abfrage {mapserver}/{layer}: {j['error']}")
    return j.get("features", [])


def _arc_identify(mapserver, lat, lon, layers, tol=2, timeout=30):
    j = _http(f"{mapserver}/identify", {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": 4326,
        "layers": "all:" + ",".join(map(str, layers)), "tolerance": tol,
        "mapExtent": f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}", "imageDisplay": "400,400,96",
        "returnGeometry": "false", "f": "json"}, cache_h=24 * 7, timeout=timeout)
    if "error" in j:
        raise RuntimeError(f"ArcGIS-Identify {mapserver}: {j['error']}")
    return j.get("results", [])


def _arc_layers(mapserver):
    return _http(f"{mapserver}/layers", {"f": "json"}, cache_h=24 * 30, timeout=30).get("layers", [])


def _arc_legende(mapserver, layer):
    """{wert: beschriftung} aus der Darstellung der Ebene (Unique Values)."""
    try:
        j = _http(f"{mapserver}/{layer}", {"f": "json"}, cache_h=24 * 30)
        rend = (j.get("drawingInfo") or {}).get("renderer") or {}
        return {str(u.get("value")): u.get("label") for u in rend.get("uniqueValueInfos", [])}
    except Exception:
        return {}


def _arc_ebenen(mapserver, ebenen, bbox, lat, lon, prefix, key_fn=None):
    """Mehrere Flächenebenen abfragen, zuschneiden, einfärben, als eine GeoJSON-Datei speichern.
    ebenen: {layer_id: beschriftung}. -> (zusammenfassung, files)"""
    res = _parallel(lambda lid: _arc_query(mapserver, lid, bbox), list(ebenen), 3)
    feats, fehler, je_art = [], [], {}
    for (lid, label), r in zip(ebenen.items(), res):
        if isinstance(r, Exception):
            fehler.append(f"{label}: {r}")
            continue
        color = PALETTE[len(je_art) % len(PALETTE)]
        names = []
        for f in _clip(r, bbox):
            props = _attrs(f.get("properties"))
            nm = (key_fn(props) if key_fn else None) or _first(props, r"^name", r"name", r"bez", r"titel") or label
            names.append(str(nm))
            f["properties"] = {**props, "art": label, "name": str(nm), "_popup": _popup(f"{label}: {nm}", props),
                               "_style": _style(color, 0.35, 2)}
            feats.append(f)
        je_art[label] = sorted(set(names))
    zus = {"im_umkreis": {k: v[:15] for k, v in je_art.items() if v}, "nicht_vorhanden": [k for k, v in je_art.items() if not v]}
    if feats:
        anteile, am_punkt = _flaechen(feats, lambda p: f"{p['art']}: {p['name']}", lat, lon, bbox)
        zus["am_punkt"] = am_punkt or "keine"
        zus["flaechenanteil_im_ausschnitt_pct"] = dict(list(anteile.items())[:15])
    if fehler:
        zus["fehler"] = fehler
    return zus, ({prefix: _save(prefix, feats)} if feats else {})


def _vg250(lat, lon, ebene="gem"):
    """Verwaltungseinheit (BKG VG250) am Punkt: Eigenschaften + Geometrie."""
    d = 0.0005
    j = _http("https://sgx.geodatenzentrum.de/wfs_vg250", {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": f"vg250:vg250_{ebene}",
        "bbox": f"{lat - d},{lon - d},{lat + d},{lon + d},urn:ogc:def:crs:EPSG::4326", "outputFormat": "application/json",
        "srsName": "urn:ogc:def:crs:EPSG::4326", "count": 10}, cache_h=24 * 30)
    pt = Point(lon, lat)
    feats = j.get("features", [])
    for f in feats:
        g = _geom(f)
        if g is not None and g.contains(pt) and str((f["properties"] or {}).get("gf", 4)) == "4":
            return f
    for f in feats:
        g = _geom(f)
        if g is not None and g.contains(pt):
            return f
    if not feats:
        raise ValueError("Punkt liegt in keiner deutschen Verwaltungseinheit (VG250).")
    return feats[0]


# =====================================================================================================
# Wetter & Klima
# =====================================================================================================
K_WETTER = "Wetter & Klima"


@quelle("wetter_aktuell", "Aktuelles Wetter (DWD-Station)", K_WETTER, "Deutscher Wetterdienst über Bright Sky",
        "DWD Open Data (CC BY 4.0)", "https://brightsky.dev",
        "Messwerte der nächsten DWD-Station: Temperatur, Niederschlag, Wind, Feuchte, Bewölkung.", art="punkt")
def wetter_aktuell(lat, lon, r, p):
    j = _http("https://api.brightsky.dev/current_weather", {"lat": lat, "lon": lon}, cache_h=0.2)
    w, src = j["weather"], (j.get("sources") or [{}])[0]
    keep = ["timestamp", "condition", "temperature", "precipitation_10", "precipitation_60", "relative_humidity",
            "wind_speed_10", "wind_gust_speed_10", "cloud_cover", "pressure_msl", "sunshine_60", "visibility"]
    return {"zusammenfassung": {"station": src.get("station_name"),
                                "abstand_km": round((src.get("distance") or 0) / 1000, 1),
                                **{k: w.get(k) for k in keep if w.get(k) is not None},
                                "einheiten": "°C, mm, %, km/h, hPa, min, m"},
            "stand": w.get("timestamp")}


@quelle("wetter_vorhersage", "Wettervorhersage (Open-Meteo, DWD ICON u.a.)", K_WETTER, "Open-Meteo",
        "CC BY 4.0", "https://open-meteo.com",
        "Tageswerte der nächsten Tage: Höchst-/Tiefstwert, Niederschlag, Regenwahrscheinlichkeit, Böen, UV, Sonne.",
        art="punkt", parameter={"tage": "Anzahl Tage 1-16 (Standard 3)"})
def wetter_vorhersage(lat, lon, r, p):
    tage = max(1, min(16, int(p.get("tage") or 3)))
    j = _http("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "Europe/Berlin", "forecast_days": tage,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
                 "wind_gusts_10m_max,uv_index_max,sunshine_duration"}, cache_h=1)
    rows = _rows(j["daily"], {"time": "datum", "temperature_2m_max": "tmax_c", "temperature_2m_min": "tmin_c",
                              "precipitation_sum": "niederschlag_mm", "precipitation_probability_max": "regen_wahrsch_pct",
                              "wind_gusts_10m_max": "boeen_kmh", "uv_index_max": "uv_index",
                              "sunshine_duration": "sonnenstunden"})
    for row in rows:
        row["sonnenstunden"] = round((row["sonnenstunden"] or 0) / 3600, 1)
    return {"zusammenfassung": {"tage": rows}, "stand": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}


@quelle("wetter_historisch", "Wetter der Vergangenheit (ERA5-Reanalyse)", K_WETTER, "Open-Meteo / Copernicus ERA5",
        "CC BY 4.0", "https://open-meteo.com/en/docs/historical-weather-api",
        "Tageswerte seit 1940 ausgewertet je Jahr: heiße Tage, Sommertage, Tropennächte, Frosttage, Niederschlag, Extreme.",
        art="punkt", parameter={"von": "Startdatum JJJJ-MM-TT (Standard vor 10 Jahren)",
                                "bis": "Enddatum (Standard Ende letztes Jahr)"})
def wetter_historisch(lat, lon, r, p):
    heute = datetime.date.today()
    von, bis = p.get("von") or f"{heute.year - 10}-01-01", p.get("bis") or f"{heute.year - 1}-12-31"
    if int(bis[:4]) - int(von[:4]) > 45:
        raise ValueError("Höchstens 45 Jahre auf einmal.")
    j = _http("https://archive-api.open-meteo.com/v1/archive", {
        "latitude": lat, "longitude": lon, "start_date": von, "end_date": bis, "timezone": "Europe/Berlin",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"}, cache_h=24 * 30, timeout=60)
    d = j["daily"]
    years, hot, wet = {}, (None, -99), (None, -1)
    for t, tx, tn, pr in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"], d["precipitation_sum"]):
        y = years.setdefault(t[:4], {"heisse_tage": 0, "sommertage": 0, "tropennaechte": 0, "frosttage": 0,
                                     "niederschlag_mm": 0.0, "max_tagesniederschlag_mm": 0.0})
        if tx is not None:
            y["heisse_tage"] += tx >= 30
            y["sommertage"] += tx >= 25
            hot = (t, tx) if tx > hot[1] else hot
        if tn is not None:
            y["tropennaechte"] += tn >= 20
            y["frosttage"] += tn < 0
        if pr is not None:
            y["niederschlag_mm"] = round(y["niederschlag_mm"] + pr, 1)
            y["max_tagesniederschlag_mm"] = max(y["max_tagesniederschlag_mm"], pr)
            wet = (t, pr) if pr > wet[1] else wet
    je_jahr = [{"jahr": k, **v} for k, v in years.items()]
    return {"zusammenfassung": {
        "zeitraum": f"{von} bis {bis}", "datengrundlage": "ERA5/ERA5-Land-Reanalyse (Raster ca. 9-25 km, keine Stadtmessung)",
        "mittel_heisse_tage_pro_jahr": round(np.mean([v["heisse_tage"] for v in years.values()]), 1),
        "mittel_tropennaechte_pro_jahr": round(np.mean([v["tropennaechte"] for v in years.values()]), 1),
        "heissester_tag": {"datum": hot[0], "tmax_c": hot[1]},
        "nassester_tag": {"datum": wet[0], "niederschlag_mm": wet[1]}, "je_jahr": je_jahr},
        "stand": bis}


@quelle("klima_projektion", "Klimaprojektion bis 2050 (CMIP6)", K_WETTER, "Open-Meteo / CMIP6 HighResMIP",
        "CC BY 4.0", "https://open-meteo.com/en/docs/climate-api",
        "Vergleich 1991-2020 mit der Zukunft (bis 2050) aus mehreren Klimamodellen: heiße Tage, Tropennächte, Starkregentage.",
        art="punkt", parameter={"zukunft": "Zeitraum, z.B. '2031-2050' (Standard, max. bis 2050)",
                                "modelle": "Liste, Standard EC_Earth3P_HR, MPI_ESM1_2_XR, CMCC_CM2_VHR4"})
def klima_projektion(lat, lon, r, p):
    modelle = _liste(p.get("modelle")) or ["EC_Earth3P_HR", "MPI_ESM1_2_XR", "CMCC_CM2_VHR4"]
    z1, z2 = (int(x) for x in str(p.get("zukunft") or "2031-2050").split("-"))
    z2 = min(z2, 2050)
    j = _http("https://climate-api.open-meteo.com/v1/climate", {
        "latitude": lat, "longitude": lon, "start_date": "1991-01-01", "end_date": f"{z2}-12-31",
        "models": ",".join(modelle), "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"},
        cache_h=24 * 30, timeout=90)
    d = j["daily"]
    years = np.array([int(t[:4]) for t in d["time"]])
    months = np.array([int(t[5:7]) for t in d["time"]])

    def col(var, m):
        v = d.get(f"{var}_{m}", d.get(var) if len(modelle) == 1 else None)
        return np.array([np.nan if x is None else x for x in v], float) if v is not None else None

    def kennz(sel, tx, tn, pr):
        ny = len(set(years[sel]))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return {"heisse_tage_pro_jahr": round(float(np.nansum(tx[sel] >= 30)) / ny, 1),
                    "sommertage_pro_jahr": round(float(np.nansum(tx[sel] >= 25)) / ny, 1),
                    "tropennaechte_pro_jahr": round(float(np.nansum(tn[sel] >= 20)) / ny, 1),
                    "tmax_sommer_mittel_c": round(float(np.nanmean(tx[sel & np.isin(months, [6, 7, 8])])), 1),
                    "starkregentage_20mm_pro_jahr": round(float(np.nansum(pr[sel] >= 20)) / ny, 2),
                    "niederschlag_mm_pro_jahr": round(float(np.nansum(pr[sel])) / ny)}
    ref, fut = (years >= 1991) & (years <= 2020), (years >= z1) & (years <= z2)
    out = {}
    for m in modelle:
        tx, tn, pr = col("temperature_2m_max", m), col("temperature_2m_min", m), col("precipitation_sum", m)
        if tx is None:
            continue
        out[m] = {"1991-2020": kennz(ref, tx, tn, pr), f"{z1}-{z2}": kennz(fut, tx, tn, pr)}
    if not out:
        raise RuntimeError("Keine Modelldaten erhalten.")
    mittel = {per: {k: round(float(np.mean([out[m][per][k] for m in out])), 1) for k in next(iter(out.values()))[per]}
              for per in ("1991-2020", f"{z1}-{z2}")}
    return {"zusammenfassung": {"modellmittel": mittel, "je_modell": out,
                                "hinweis": "Globale Klimamodelle, ca. 10-50 km Raster, auf Punkt heruntergerechnet. "
                                           "Aussagekräftig ist die Änderung, nicht der absolute Wert."}}


@quelle("unwetterwarnungen", "Amtliche Wetterwarnungen (DWD)", K_WETTER, "Deutscher Wetterdienst über Bright Sky",
        "DWD Open Data (CC BY 4.0)", "https://brightsky.dev",
        "Aktuelle DWD-Warnungen für die Gemeinde (Gewitter, Starkregen, Hitze, Sturm, Glätte ...).", art="punkt")
def unwetterwarnungen(lat, lon, r, p):
    j = _http("https://api.brightsky.dev/alerts", {"lat": lat, "lon": lon}, cache_h=0.1)
    al = [{"ereignis": a.get("event_de"), "titel": a.get("headline_de"), "stufe": a.get("severity"),
           "beginn": a.get("onset"), "ende": a.get("expires"), "text": (a.get("description_de") or "")[:300]}
          for a in j.get("alerts", [])]
    return {"zusammenfassung": {"warngebiet": (j.get("location") or {}).get("name"), "anzahl": len(al),
                                "warnungen": al or "keine aktuellen Warnungen"},
            "stand": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}


@quelle("nina_warnungen", "Bevölkerungswarnungen NINA (BBK)", K_WETTER, "Bundesamt für Bevölkerungsschutz (NINA)",
        "Datenlizenz Deutschland", "https://warnung.bund.de",
        "Aktuelle Warnungen für den Landkreis/die kreisfreie Stadt: Katastrophenschutz, Polizei, Hochwasser, Wetter.",
        art="punkt")
def nina_warnungen(lat, lon, r, p):
    props = {k.lower(): v for k, v in _vg250(lat, lon)["properties"].items()}
    ars = str(props.get("ars") or props.get("rs"))
    kreis = ars[:5] + "0000000"
    j = _http(f"https://warnung.bund.de/api31/dashboard/{kreis}.json", cache_h=0.1)
    items = []
    for it in j or []:
        d = (it.get("payload") or {}).get("data") or {}
        items.append({"titel": (it.get("i18nTitle") or {}).get("de") or d.get("headline"), "schwere": d.get("severity"),
                      "typ": d.get("msgType"), "quelle": d.get("provider"), "gesendet": it.get("sent")})
    return {"zusammenfassung": {"gebiet": props.get("gen"), "regionalschluessel_kreis": kreis,
                                "anzahl": len(items), "warnungen": items or "keine aktuellen Warnungen"}}


@quelle("regenradar", "Regenradar (DWD RADOLAN)", K_WETTER, "Deutscher Wetterdienst über Bright Sky",
        "DWD Open Data (CC BY 4.0)", "https://brightsky.dev",
        "Niederschlag der letzten 2 Stunden und Kurzfrist-Vorhersage aus dem Radar (1 km), am Punkt und im Umkreis.",
        radius=5000, max_radius=25000)
def regenradar(lat, lon, r, p):
    j = _http("https://api.brightsky.dev/radar", {"lat": lat, "lon": lon, "distance": int(max(r, 1000)),
                                                  "format": "plain"}, cache_h=0.05)
    pos = j["latlon_position"]
    cx, cy = int(pos["x"]), int(pos["y"])
    now = datetime.datetime.now(datetime.timezone.utc)
    reihe, vergangen, zukunft, maxi = [], 0.0, 0.0, 0.0
    for fr in j["radar"]:
        a = np.array(fr["precipitation_5"], float) / 100.0  # mm je 5 Minuten
        punkt = float(a[cy, cx]) if 0 <= cy < a.shape[0] and 0 <= cx < a.shape[1] else float("nan")
        t = datetime.datetime.fromisoformat(fr["timestamp"])
        if t <= now:
            vergangen += punkt
            maxi = max(maxi, float(a.max()) * 12)
        else:
            zukunft += punkt
        reihe.append({"zeit": _lokalzeit(fr["timestamp"]), "mm_h_am_punkt": round(punkt * 12, 2),
                      "max_mm_h_im_umkreis": round(float(a.max()) * 12, 2), "vorhersage": t > now})
    return {"zusammenfassung": {"niederschlag_vergangen_mm_am_punkt": round(vergangen, 2),
                                "niederschlag_vorhersage_mm_am_punkt": round(zukunft, 2),
                                "max_intensitaet_mm_h_im_umkreis": round(maxi, 1), "zeitreihe": reihe[::2]},
            "stand": j["radar"][-1]["timestamp"] if j["radar"] else None}


KOSTRA = CDC + "return_periods/precipitation/KOSTRA/KOSTRA_DWD_2020/asc/"
KOSTRA_DAUERN = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 540, 720, 1080, 1440, 2880, 4320, 5760, 7200,
                 8640, 10080]
KOSTRA_T = [1, 2, 3, 5, 10, 20, 30, 50, 100]


@quelle("kostra_starkregen", "Starkregen-Bemessungswerte KOSTRA-DWD-2020", K_WETTER, "Deutscher Wetterdienst",
        "DWD Open Data (CC BY 4.0)", "https://www.dwd.de/kostra",
        "Amtliche Regenmengen (mm) je Dauer (5 min bis 7 Tage) und Wiederkehrzeit (1 bis 100 Jahre), Raster 5 km.",
        art="punkt", parameter={"dauern_min": "Liste der Dauerstufen in Minuten (Standard 15, 60, 180, 360, 720, 1440)"})
def kostra_starkregen(lat, lon, r, p):
    dauern = _liste(p.get("dauern_min"), int) or [15, 60, 180, 360, 720, 1440]
    falsch = [d for d in dauern if d not in KOSTRA_DAUERN]
    if falsch:
        raise ValueError(f"Dauerstufen {falsch} gibt es nicht. Erlaubt: {KOSTRA_DAUERN}")
    x, y = TO_3035.transform(lon, lat)

    def eine(d):
        z = zipfile.ZipFile(io.BytesIO(_http(f"{KOSTRA}StatRR_KOSTRA-DWD-2020_D{d:05d}_ASC.zip", fmt="bytes",
                                             cache_h=24 * 365, timeout=60)))
        row = {"dauer": f"{d} min" if d < 60 else f"{d / 60:g} h"}
        for T in KOSTRA_T:
            v = _asc_value(z.read(f"Hn_KOSTRA-DWD-2020_D{d:05d}_T{T:03d}.asc").decode("latin1"), x, y)
            row[f"T{T}_mm"] = None if v is None else round(v, 1)
        return row
    rows = _parallel(eine, dauern, 6)
    err = [str(r_) for r_ in rows if isinstance(r_, Exception)]
    if err and len(err) == len(rows):
        raise RuntimeError(err[0])
    return {"zusammenfassung": {
        "tabelle_mm": [r_ for r_ in rows if not isinstance(r_, Exception)],
        "erklaerung": "T100_mm = Regenmenge, die in dieser Dauer im Mittel einmal in 100 Jahren erreicht oder "
                      "überschritten wird (T1 jährlich ... T100 hundertjährlich).",
        "rasterzelle": "5 x 5 km (EPSG:3035)"}, "stand": "KOSTRA-DWD-2020"}


DWD_GROESSEN = {
    "heisse_tage": ("hot_days", "Tage", 1, "Tage mit Höchsttemperatur ≥ 30 °C"),
    "sommertage": ("summer_days", "Tage", 1, "Tage mit Höchsttemperatur ≥ 25 °C"),
    "frosttage": ("frost_days", "Tage", 1, "Tage mit Tiefsttemperatur < 0 °C"),
    "eistage": ("ice_days", "Tage", 1, "Tage mit Höchsttemperatur < 0 °C"),
    "regentage_10mm": ("precipGE10mm_days", "Tage", 1, "Tage mit ≥ 10 mm Niederschlag"),
    "regentage_20mm": ("precipGE20mm_days", "Tage", 1, "Tage mit ≥ 20 mm Niederschlag"),
    "regentage_30mm": ("precipGE30mm_days", "Tage", 1, "Tage mit ≥ 30 mm Niederschlag"),
    "niederschlag": ("precipitation", "mm", 1, "Jahresniederschlag"),
    "temperatur_mittel": ("air_temperature_mean", "°C", 0.1, "Jahresmitteltemperatur"),
    "temperatur_max": ("air_temperature_max", "°C", 0.1, "Mittel der Tageshöchsttemperaturen"),
    "sonnenscheindauer": ("sunshine_duration", "h", 1, "Sonnenstunden im Jahr"),
    "trockenheitsindex": ("drought_index", "", 1, "Trockenheitsindex nach de Martonne"),
}


@quelle("dwd_klimaraster", "Klimaraster Deutschland 1 km (DWD, jährlich)", K_WETTER, "Deutscher Wetterdienst (CDC)",
        "DWD Open Data (CC BY 4.0)", "https://opendata.dwd.de/climate_environment/CDC/grids_germany/",
        "Gemessene Jahreswerte am Ort (1-km-Raster aus Stationen): heiße Tage, Sommertage, Frost, Starkregentage, "
        "Niederschlag, Temperatur, Sonne; mit Mittel 1961-1990 und 1991-2020 und Trend.",
        art="punkt", parameter={"groessen": f"Liste aus {list(DWD_GROESSEN)} (Standard heisse_tage, sommertage, niederschlag)",
                                "von_jahr": "Standard: 10 Jahre zurück", "bis_jahr": "Standard: letztes verfügbares Jahr"})
def dwd_klimaraster(lat, lon, r, p):
    groessen = _liste(p.get("groessen")) or ["heisse_tage", "sommertage", "niederschlag"]
    falsch = [g for g in groessen if g not in DWD_GROESSEN]
    if falsch:
        raise ValueError(f"Unbekannte Größe(n) {falsch}. Erlaubt: {list(DWD_GROESSEN)}")
    x, y = TO_31467.transform(lon, lat)

    def dateien(var, multi=False):
        url = f"{CDC}{'multi_annual' if multi else 'annual'}/{var}/"
        names = re.findall(r'href="([^"]+\.asc\.gz)"', _http(url, fmt="text", cache_h=24))
        pat = r"_(\d{4}-\d{4})_17\.asc\.gz$" if multi else r"_(\d{4})_?17\.asc\.gz$"
        return {m.group(1): url + n for n in names for m in [re.search(pat, n)] if m}

    def wert(url, scale):
        v = _asc_value(gzip.decompress(_http(url, fmt="bytes", cache_h=24 * 365, timeout=60)).decode("latin1"), x, y)
        return None if v is None else round(v * scale, 2)

    out = {}
    for g in groessen:
        var, einheit, scale, info = DWD_GROESSEN[g]
        jahre = dateien(var)
        bis = int(p.get("bis_jahr") or max(jahre))
        von = int(p.get("von_jahr") or bis - 9)
        if bis - von > 39:
            raise ValueError("Höchstens 40 Jahre je Größe.")
        wanted = [str(j_) for j_ in range(von, bis + 1) if str(j_) in jahre]
        vals = _parallel(lambda j_: wert(jahre[j_], scale), wanted, 8)
        reihe = {j_: v for j_, v in zip(wanted, vals) if not isinstance(v, Exception)}
        ref = {}
        try:
            multi = dateien(var, True)
            for per in ("1961-1990", "1991-2020"):
                if per in multi:
                    ref[per] = wert(multi[per], scale)
        except Exception:
            pass
        xs = [int(k) for k, v in reihe.items() if v is not None]
        ys = [v for v in reihe.values() if v is not None]
        trend = round(float(np.polyfit(xs, ys, 1)[0]) * 10, 2) if len(xs) >= 5 else None
        out[g] = {"beschreibung": info, "einheit": einheit, "je_jahr": reihe,
                  "mittel_zeitraum": round(float(np.mean(ys)), 2) if ys else None,
                  "referenz_mittel": ref, "trend_pro_jahrzehnt": trend}
    return {"zusammenfassung": {"groessen": out, "rasterzelle": "1 x 1 km, aus DWD-Stationen interpoliert"}}


UHI_GROESSEN = {"waermeinsel_tagmax_mittel": ("uhi_daymax_mean", "K", "mittlere Wärmeinsel-Intensität (Tageshöchsttemperatur, Stadt minus Umland)"),
                "waermeinsel_tagmax_max": ("uhi_daymax_max", "K", "maximale Wärmeinsel-Intensität im Jahr"),
                "zusaetzliche_tropennaechte": ("tropical_nights_diff", "Nächte", "zusätzliche Tropennächte (≥ 20 °C) durch die Stadt")}


@quelle("stadtklima_waermeinsel", "Städtische Wärmeinsel (DWD UHI-MAP)", K_WETTER, "Deutscher Wetterdienst (Projekt UHI-MAP)",
        "DWD Open Data (CC BY 4.0)", "https://opendata.dwd.de/climate_environment/CDC/grids_germany/annual/Project_UHI-MAP/",
        "Wie viel wärmer es am Ort durch die Bebauung ist als im Umland (Kelvin) und zusätzliche Tropennächte, je Jahr, ca. 1 km.",
        art="punkt", parameter={"jahre": "Liste (Standard: die letzten 5 verfügbaren)"})
def stadtklima_waermeinsel(lat, lon, r, p):
    base = CDC + "annual/Project_UHI-MAP/"
    out, wunsch = {}, _liste(p.get("jahre"), str)
    for g, (var, einheit, info) in UHI_GROESSEN.items():
        names = re.findall(r'href="([^"]+\.nc)"', _http(base + var + "/", fmt="text", cache_h=24))
        jahre = {}
        for n in names:  # neuere Landnutzung (clc2018) bevorzugen
            m = re.search(r"_clc(\d{4})_.*_p1y_(\d{4})-01-01\.nc$", n)
            if m and (m.group(2) not in jahre or m.group(1) > jahre[m.group(2)][0]):
                jahre[m.group(2)] = (m.group(1), n)
        auswahl = wunsch or sorted(jahre)[-5:]

        def wert(jahr):
            path = os.path.join(CACHE, "uhi", jahre[jahr][1])
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(_http(base + var + "/" + jahre[jahr][1], fmt="bytes", timeout=60))
            txt = geo_tools.gdal("gdallocationinfo", "-wgs84", path, lon, lat, timeout=30)
            m = re.search(r"Descaled Value:\s*([-\d.eE+]+)", txt) or re.search(r"Value:\s*([-\d.eE+]+)", txt)
            return round(float(m.group(1)), 2) if m else None
        vals = _parallel(wert, [j_ for j_ in auswahl if j_ in jahre], 5)
        out[g] = {"beschreibung": info, "einheit": einheit,
                  "je_jahr": {j_: (None if isinstance(v, Exception) else v) for j_, v in zip(auswahl, vals)}}
    return {"zusammenfassung": {"groessen": out, "hinweis": "Modellierte Rasterkarte (ca. 1 km), zeigt den Effekt "
                                                           "der Stadt im Vergleich zum unbebauten Umland."}}


DWD_KARTEN = {"sommertage_1971_2000": "Summerdays_annual_map_normals_1971_30",
              "frosttage_1971_2000": "Frostdays_annual_map_normals_1971_30",
              "schneetage_1971_2000": "Snowdays_annual_map_normals_1971_30",
              "sonnenscheindauer_h_1971_2000": "SDMS_17_1971_30",
              "globalstrahlung_kwh_m2_1981_2010": "SISMM_annual_map_normals_1981_30",
              "wind_10m_m_s": "BRD_1km_winddaten_10m", "wind_80m_m_s": "BRD_1km_winddaten_80m",
              "niederschlag_mm_1961_1990": "RSMS_17_1961_30", "temperatur_mittel_1961_1990": "TAMM_17_1961_30"}


@quelle("dwd_klimakarten", "Klima-Referenzkarten (DWD GeoServer)", K_WETTER, "Deutscher Wetterdienst",
        "DWD Open Data (CC BY 4.0)", "https://maps.dwd.de",
        "Langjährige Mittel am Ort: Sommer-/Frost-/Schneetage, Sonnenscheindauer, Globalstrahlung, Wind in 10 und 80 m.",
        art="punkt")
def dwd_klimakarten(lat, lon, r, p):
    def gfi(layer):
        j = _http("https://maps.dwd.de/geoserver/dwd/wms", {
            "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo", "layers": f"dwd:{layer}",
            "query_layers": f"dwd:{layer}", "crs": "EPSG:4326", "styles": "",
            "bbox": f"{lat - 0.01},{lon - 0.01},{lat + 0.01},{lon + 0.01}", "width": 101, "height": 101,
            "i": 50, "j": 50, "info_format": "application/json"}, cache_h=24 * 30)
        props = (j.get("features") or [{}])[0].get("properties") or {}
        return next(iter(props.values()), None)
    vals = _parallel(gfi, list(DWD_KARTEN.values()), 9)
    return {"zusammenfassung": {k: (None if isinstance(v, Exception) else v) for k, v in zip(DWD_KARTEN, vals)}}


# =====================================================================================================
# Luft & Gesundheit
# =====================================================================================================
K_LUFT = "Luft & Gesundheit"


@quelle("luft_messstationen", "Luftqualität an amtlichen Messstationen (UBA)", K_LUFT, "Umweltbundesamt",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://www.umweltbundesamt.de/daten/luft/luftdaten",
        "Nächste Messstationen der Länder mit aktuellen Stundenwerten für NO2, Feinstaub PM10/PM2.5 und Ozon.",
        radius=15000, max_radius=60000)
def luft_messstationen(lat, lon, r, p):
    st = _http("https://www.umweltbundesamt.de/api/air_data/v3/stations/json", {"lang": "de", "index": "id"},
               cache_h=24, timeout=30)
    I = {n: i for i, n in enumerate(st["indices"])}
    near = []
    for sid, row in st["data"].items():
        try:
            la, lo = float(row[I["station latitude"]]), float(row[I["station longitude"]])
        except (TypeError, ValueError):
            continue
        if row[I["station active to"]]:
            continue
        dd = _dist(lat, lon, la, lo)
        if dd <= r:
            near.append((dd, sid, row, la, lo))
    near = sorted(near)[:6]
    comps = {"PM10": 1, "NO2": 5, "O3": 3, "PM2.5": 9}
    heute = datetime.date.today()

    def messung(args):
        sid, cid = args
        j = _http("https://www.umweltbundesamt.de/api/air_data/v3/measures/json", {
            "date_from": str(heute - datetime.timedelta(days=1)), "time_from": 1, "date_to": str(heute), "time_to": 24,
            "station": sid, "component": cid, "scope": 2}, cache_h=0.5)
        werte = (j.get("data") or {}).get(str(sid)) or {}
        for t in sorted(werte, reverse=True):
            if werte[t][2] is not None:
                return t, werte[t][2]
        return None
    jobs = [(s_[1], c) for s_ in near for c in comps.values()]
    res = dict(zip(jobs, _parallel(messung, jobs, 8)))
    stationen, feats = [], []
    for dd, sid, row, la, lo in near:
        werte = {}
        for name, cid in comps.items():
            v = res.get((sid, cid))
            if v and not isinstance(v, Exception):
                werte[name] = {"wert_ug_m3": v[1], "zeit": v[0]}
        s_ = {"station": row[I["station name"]], "typ": f"{row[I['station setting name']]} / {row[I['station type name']]}",
              "abstand_km": round(dd / 1000, 1), "messwerte": werte or "keine aktuellen Werte"}
        stationen.append(s_)
        feats.append(_pt(lo, la, {**{k: v["wert_ug_m3"] for k, v in werte.items()}, "typ": s_["typ"]},
                         s_["station"], "#6a3d9a"))
    stationen.sort(key=lambda s_: isinstance(s_["messwerte"], str))
    return {"zusammenfassung": {"stationen": stationen or f"keine aktive Station im Umkreis von {r / 1000:.0f} km",
                                "grenzwerte_hinweis": "NO2 Jahresmittel 40 µg/m³ (ab 2030: 20), PM10 Tagesmittel 50, "
                                                      "Ozon Informationsschwelle 180 (1h)"},
            "files": {"luft_messstationen": _save("luft_messstationen", feats)} if feats else {}}


@quelle("luft_modell", "Luftqualität und Pollen (Modell CAMS)", K_LUFT, "Open-Meteo / Copernicus CAMS",
        "CC BY 4.0", "https://open-meteo.com/en/docs/air-quality-api",
        "Modellwerte am Ort: Europäischer Luftqualitätsindex, PM10, PM2.5, NO2, Ozon, Pollen (Erle, Birke, Gräser ...).",
        art="punkt")
def luft_modell(lat, lon, r, p):
    j = _http("https://air-quality-api.open-meteo.com/v1/air-quality", {
        "latitude": lat, "longitude": lon, "timezone": "Europe/Berlin", "forecast_days": 2,
        "current": "european_aqi,pm10,pm2_5,nitrogen_dioxide,ozone",
        "hourly": "pm10,pm2_5,nitrogen_dioxide,ozone,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,ragweed_pollen"},
        cache_h=1)
    h = j["hourly"]
    maxi = {k: max((v for v in vals[:24] if v is not None), default=None) for k, vals in h.items() if k != "time"}
    return {"zusammenfassung": {"aktuell": j.get("current"), "max_naechste_24h": maxi,
                                "einheiten": "µg/m³, Pollen Körner/m³", "raster": "ca. 10 km (Modell, keine Messung)"}}


@quelle("buergersensoren_luft", "Bürger-Luftsensoren (sensor.community)", K_LUFT, "sensor.community (Luftdaten.info)",
        "ODbL 1.0", "https://sensor.community",
        "Feinstaub- und Temperatursensoren von Bürger:innen im Umkreis (5-Minuten-Werte, nicht kalibriert).",
        radius=2000, max_radius=10000)
def buergersensoren_luft(lat, lon, r, p):
    j = _http(f"https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{max(r, 500) / 1000:.1f}",
              cache_h=0.1, timeout=25)
    orte = {}
    for s_ in j:
        loc = s_["location"]
        o = orte.setdefault(loc["id"], {"lat": float(loc["latitude"]), "lon": float(loc["longitude"]), "werte": {}})
        for v in s_["sensordatavalues"]:
            name = {"P1": "pm10", "P2": "pm2_5"}.get(v["value_type"], v["value_type"])
            try:
                o["werte"][name] = float(v["value"])
            except (TypeError, ValueError):
                pass
    feats = [_pt(o["lon"], o["lat"], o["werte"], f"Sensor {k}", "#ff7f00") for k, o in orte.items()]
    stat = {}
    for g in ("pm10", "pm2_5", "temperature", "humidity"):
        v = [o["werte"][g] for o in orte.values() if g in o["werte"]]
        if v:
            stat[g] = {"anzahl": len(v), "median": round(float(np.median(v)), 1), "min": min(v), "max": max(v)}
    return {"zusammenfassung": {"standorte": len(orte), "werte": stat or "keine Sensoren im Umkreis",
                                "einheiten": "µg/m³, °C, %"},
            "files": {"buergersensoren": _save("buergersensoren_luft", feats)} if feats else {}}


@quelle("opensensemap", "senseBox-Messstationen (openSenseMap)", K_LUFT, "openSenseMap (Uni Münster / re:edu)",
        "PDDL 1.0", "https://opensensemap.org",
        "Offene Umweltsensoren (Temperatur, Feuchte, Feinstaub, Lärm ...) mit letztem Messwert, nur aktive (< 48 h).",
        radius=3000, max_radius=20000)
def opensensemap(lat, lon, r, p):
    j = _http("https://api.opensensemap.org/boxes", {"near": f"{lon},{lat}", "maxDistance": int(r),
                                                     "full": "true", "format": "json"}, cache_h=0.25, timeout=30)
    grenze = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    feats, boxen = [], []
    for b in j:
        werte = {}
        for s_ in b.get("sensors", []):
            lm = s_.get("lastMeasurement") or {}
            try:
                if lm.get("value") is not None and datetime.datetime.fromisoformat(lm["createdAt"].replace("Z", "+00:00")) > grenze:
                    werte[f"{s_.get('title')} [{s_.get('unit')}]"] = float(lm["value"])
            except (KeyError, ValueError):
                pass
        if not werte:
            continue
        lo, la = b["currentLocation"]["coordinates"][:2]
        boxen.append({"name": b.get("name"), "abstand_m": round(_dist(lat, lon, la, lo)), "werte": werte})
        feats.append(_pt(lo, la, werte, b.get("name"), "#00a0a0"))
    return {"zusammenfassung": {"aktive_boxen": len(boxen), "boxen": sorted(boxen, key=lambda x: x["abstand_m"])[:15]},
            "files": {"opensensemap": _save("opensensemap", feats)} if feats else {}}


@quelle("pollenflug", "Pollenflug-Gefahrenindex (DWD)", K_LUFT, "Deutscher Wetterdienst", "DWD Open Data (CC BY 4.0)",
        "https://opendata.dwd.de/climate_environment/health/alerts/",
        "Pollenbelastung heute/morgen/übermorgen je Pollenart für eine DWD-Teilregion.", art="punkt",
        parameter={"region": "Teilregion, Standard 'Rhein-Main' (z.B. 'Nordhessen')"})
def pollenflug(lat, lon, r, p):
    j = _http("https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json", cache_h=3)
    lg = j.get("legend", {})
    text = {lg[k]: lg.get(k + "_desc") for k in lg if re.fullmatch(r"id\d+", k)}
    region = (p.get("region") or "Rhein-Main").lower()
    c = next((c for c in j["content"] if region in (c.get("partregion_name") or c.get("region_name") or "").lower()), None)
    if c is None:
        raise ValueError("Region nicht gefunden. Verfügbar: " +
                         ", ".join(sorted({c.get('partregion_name') or c['region_name'] for c in j['content']})))
    pollen = {art: {t: text.get(v, v) for t, v in werte.items()} for art, werte in c["Pollen"].items()}
    return {"zusammenfassung": {"region": f"{c['region_name']} / {c.get('partregion_name')}", "pollen": pollen},
            "stand": j.get("last_update")}


UV_STAEDTE = {"Frankfurt/Main": (50.11, 8.68), "Würzburg": (49.79, 9.95), "Kassel": (51.31, 9.48),
              "Stuttgart": (48.78, 9.18), "Bonn": (50.73, 7.10), "Düsseldorf": (51.23, 6.78), "Hahn": (49.95, 7.26),
              "Weinbiet": (49.38, 8.12), "Nürnberg": (49.45, 11.08), "München": (48.14, 11.58),
              "Freiburg": (47.99, 7.85), "Konstanz": (47.66, 9.18), "Ulm": (48.40, 9.99), "Regensburg": (49.01, 12.10),
              "Berlin": (52.52, 13.40), "Hamburg": (53.55, 9.99), "Hannover": (52.37, 9.73), "Leipzig": (51.34, 12.37),
              "Dresden": (51.05, 13.74), "Magdeburg": (52.13, 11.62), "Bremen": (53.08, 8.80), "Kiel": (54.32, 10.14),
              "Rostock": (54.09, 12.10), "Osnabrück": (52.28, 8.05), "Weimar": (50.98, 11.33), "Cottbus": (51.76, 14.33),
              "Kahler Asten": (51.18, 8.49), "Großer Arber": (49.11, 13.13), "Zugspitze": (47.42, 10.98),
              "Wernigerode": (51.83, 10.79), "Neubrandenburg": (53.56, 13.26), "Waren": (53.52, 12.68),
              "Seehausen": (52.89, 11.73), "Norderney": (53.71, 7.15), "List auf Sylt": (55.02, 8.43),
              "Sankt Peter-Ording": (54.31, 8.64), "Arkona": (54.68, 13.43), "Marienleuchte": (54.50, 11.24)}


@quelle("uv_index", "UV-Index-Vorhersage (DWD)", K_LUFT, "Deutscher Wetterdienst", "DWD Open Data (CC BY 4.0)",
        "https://opendata.dwd.de/climate_environment/health/alerts/",
        "UV-Index heute, morgen, übermorgen für die nächstgelegene DWD-Vorhersagestadt.", art="punkt")
def uv_index(lat, lon, r, p):
    j = _http("https://opendata.dwd.de/climate_environment/health/alerts/uvi.json", cache_h=3)
    staedte = {c["city"]: c for c in j["content"]}
    best = min((s_ for s_ in staedte if s_ in UV_STAEDTE), key=lambda s_: _dist(lat, lon, *UV_STAEDTE[s_]))
    return {"zusammenfassung": {"stadt": best, "abstand_km": round(_dist(lat, lon, *UV_STAEDTE[best]) / 1000),
                                "uv_index": staedte[best]["forecast"],
                                "skala": "0-2 niedrig, 3-5 mäßig, 6-7 hoch, 8-10 sehr hoch, 11+ extrem"},
            "stand": j.get("last_update")}


# =====================================================================================================
# Wasser
# =====================================================================================================
K_WASSER = "Wasser & Hochwasser"


@quelle("pegel", "Wasserstände an Bundeswasserstraßen (PEGELONLINE)", K_WASSER, "Wasserstraßen- und Schifffahrtsverwaltung des Bundes",
        "Datenlizenz Deutschland – Zero 2.0", "https://www.pegelonline.wsv.de",
        "Pegel im Umkreis mit aktuellem Wasserstand (cm), Abfluss und Einordnung (niedrig/normal/hoch).",
        radius=30000, max_radius=100000)
def pegel(lat, lon, r, p):
    j = _http("https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json", {
        "latitude": lat, "longitude": lon, "radius": round(r / 1000, 1), "includeTimeseries": "true",
        "includeCurrentMeasurement": "true"}, cache_h=0.25)
    out, feats = [], []
    for s_ in j:
        ts = {t["shortname"]: t for t in s_.get("timeseries", [])}
        w = (ts.get("W") or {}).get("currentMeasurement") or {}
        q = (ts.get("Q") or {}).get("currentMeasurement") or {}
        e = {"pegel": s_["longname"], "gewaesser": s_["water"]["longname"],
             "abstand_km": round(_dist(lat, lon, s_["latitude"], s_["longitude"]) / 1000, 1),
             "wasserstand_cm": w.get("value"), "zustand": w.get("stateMnwMhw"), "zeit": w.get("timestamp"),
             "abfluss_m3_s": q.get("value")}
        out.append(e)
        if s_.get("latitude"):
            feats.append(_pt(s_["longitude"], s_["latitude"], e, s_["longname"], "#08519c"))
    return {"zusammenfassung": {"pegel": sorted(out, key=lambda x: x["abstand_km"]) or "kein Pegel im Umkreis"},
            "files": {"pegel": _save("pegel", feats)} if feats else {}}


@quelle("abfluss_vorhersage", "Abfluss-Vorhersage Flüsse (GloFAS)", K_WASSER, "Open-Meteo / Copernicus GloFAS",
        "CC BY 4.0", "https://open-meteo.com/en/docs/flood-api",
        "Abfluss des nächsten größeren Flusses (m³/s): letzte 7 Tage und 2 Wochen Vorhersage, mit langjährigem Mittel.",
        art="punkt")
def abfluss_vorhersage(lat, lon, r, p):
    j = _http("https://flood-api.open-meteo.com/v1/flood", {
        "latitude": lat, "longitude": lon, "daily": "river_discharge,river_discharge_mean,river_discharge_max",
        "past_days": 7, "forecast_days": 14}, cache_h=3)
    rows = _rows(j["daily"], {"time": "datum", "river_discharge": "abfluss_m3_s",
                              "river_discharge_mean": "mittel_m3_s", "river_discharge_max": "max_ensemble_m3_s"})
    peak = max(rows, key=lambda x: x["abfluss_m3_s"] or 0)
    return {"zusammenfassung": {"rasterpunkt": [j.get("latitude"), j.get("longitude")], "hoechster_wert": peak,
                                "tage": rows, "hinweis": "Raster 5 km: für kleine Bäche nicht aussagekräftig."}}


@quelle("hlnug_hochwasser", "Hochwasser-Gefahrenkarten Hessen (HQ10/HQ100/HQextrem)", K_WASSER,
        "Hessisches Landesamt für Naturschutz, Umwelt und Geologie (HLNUG)", "Datenlizenz Deutschland – Namensnennung 2.0",
        "https://www.hlnug.de/themen/wasser/hochwasser",
        "Überflutungsflächen für häufiges, seltenes und extremes Hochwasser und festgesetzte Überschwemmungsgebiete.")
def hlnug_hochwasser(lat, lon, r, p):
    ms = f"{HLNUG}/hwrm/hwrm/MapServer"
    ebenen = {26: "HQextrem (sehr selten)", 25: "HQ100 (ca. alle 100 Jahre)", 24: "HQ10 (ca. alle 10 Jahre)",
              1: "Überschwemmungsgebiet festgesetzt", 2: "Überschwemmungsgebiet (Arbeitskarte)"}
    zus, files = _arc_ebenen(ms, ebenen, _bbox(lat, lon, r), lat, lon, "hochwasser_flaechen", key_fn=lambda pr: None)
    try:
        hits = _arc_identify(f"{HLNUG}/hwrm/gefahrenkarten/MapServer", lat, lon, [1, 2, 3, 5, 6, 7, 9, 10, 11], timeout=20)
        tiefen = [h_["layerName"] for h_ in hits
                  if str((h_.get("attributes") or {}).get("Pixel Value", (h_.get("attributes") or {}).get("Classify.Pixelwert", ""))).lower() not in ("nodata", "")]
        zus["ueberflutungstiefe_klassen_am_punkt"] = tiefen or "keine"
    except Exception as err:
        zus["ueberflutungstiefe_klassen_am_punkt"] = f"nicht abrufbar ({err})"
    return {"zusammenfassung": zus, "files": files}


@quelle("hlnug_starkregen", "Starkregen-Hinweiskarte Hessen", K_WASSER, "HLNUG (mit DWD)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://www.hlnug.de/themen/klimawandel-und-anpassung/projekte/klimprax-projekte/klimprax-starkregen",
        "Starkregen-Hinweis-Index und Vulnerabilität (1-km-Raster) sowie Fließpfade bei Starkregen.")
def hlnug_starkregen(lat, lon, r, p):
    ms = f"{HLNUG}/klima/starkregenviewer/MapServer"
    bb = _bbox(lat, lon, r)
    idx, vul, fp = _parallel(lambda lid: _arc_query(ms, lid, bb, max_n=3000), [1, 0, 2], 3)
    zus, files = {}, {}
    for name, feats, feld, prefix in (("starkregen_hinweis_index", idx, "SH_INDEX", "starkregen_hinweisindex"),
                                      ("vulnerabilitaets_index", vul, "V_Index", "starkregen_vulnerabilitaet")):
        if isinstance(feats, Exception):
            zus[name] = f"nicht abrufbar ({feats})"
            continue
        feats = _clip(feats, bb)
        for f in feats:
            v = (f["properties"] or {}).get(feld)
            f["properties"] = {name: v, "name": f"{name}: {v}", "_popup": f"{name}: {v}",
                               "_style": _style(_ramp(v or 0, 1, 5, RAMP_BLAU), 0.45, 1)}
        anteile, am_punkt = _flaechen(feats, lambda pr: pr.get(name), lat, lon, bb)
        zus[name] = {"am_punkt": am_punkt, "flaechenanteil_pct": anteile}
        if feats:
            files[prefix] = _save(prefix, feats)
    if isinstance(fp, Exception):
        zus["fliesspfade"] = f"nicht abrufbar ({fp})"
    else:
        fp = _clip(fp, bb)
        laenge = sum(_to3035(_geom(f)).length for f in fp if _geom(f) is not None)
        for f in fp:
            f["properties"] = {"name": "Fließpfad bei Starkregen", "_style": {"color": "#1f78b4", "weight": 2}}
        zus["fliesspfade"] = {"anzahl_abschnitte": len(fp), "laenge_m": round(laenge)}
        if fp:
            files["fliesspfade"] = _save("starkregen_fliesspfade", fp)
    zus["legende"] = "Index 1 = gering ... 4/5 = sehr hoch (Hinweis auf Gefährdung bzw. Verletzlichkeit, 1-km-Raster)"
    return {"zusammenfassung": zus, "files": files}


# =====================================================================================================
# Hitze & Stadtklima (Hessen)
# =====================================================================================================
@quelle("hlnug_hitze", "Hitzeviewer Hessen (Oberflächentemperatur, Hotspots)", K_WETTER, "HLNUG",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://www.hlnug.de/themen/klimawandel-und-anpassung/hitze",
        "Maximale Landoberflächentemperatur (Satellit), Hot/Cold Spots, Hitzebelastungs-Index und Hitzebelastung im Sommer.")
def hlnug_hitze(lat, lon, r, p):
    ms = f"{HLNUG}/klima/hitzeviewer/MapServer"
    bb = _bbox(lat, lon, r)
    lst, hs, hbi, mhb = _parallel(lambda lid: _arc_query(ms, lid, bb, max_n=3000), [0, 4, 5, 1], 4)
    zus, files = {}, {}
    sets = (("landoberflaechentemperatur_c", lst, lambda pr: pr.get("GRIDCODE"), lambda v: _ramp(v or 0, 25, 50, RAMP_HITZE), "hitze_oberflaechentemperatur"),
            ("hot_cold_spots", hs, lambda pr: pr.get("KLASSE"), lambda v: "#d7191c" if "wärmer" in str(v) else "#2c7bb6", "hitze_hotspots"),
            ("hitzebelastungs_index", hbi, lambda pr: pr.get("KLASSE") or pr.get("HITZEBELASTUNG"),
             lambda v: PALETTE[hash(str(v)) % len(PALETTE)], "hitze_belastungsindex"),
            ("hitzebelastung_sommer", mhb, lambda pr: pr.get("KLASSE"), None, None))
    for name, feats, key, color, prefix in sets:
        if isinstance(feats, Exception):
            zus[name] = f"nicht abrufbar ({feats})"
            continue
        feats = _clip(feats, bb)
        for f in feats:
            v = key(f["properties"] or {})
            f["properties"] = {name: v, "name": f"{name}: {v}", "_popup": f"{name}: {v}",
                               **({"_style": _style(color(v), 0.5, 0)} if color else {})}
        anteile, am_punkt = _flaechen(feats, lambda pr: pr.get(name), lat, lon, bb)
        zus[name] = {"am_punkt": am_punkt, "flaechenanteil_pct": anteile}
        if feats and prefix:
            files[prefix] = _save(prefix, feats)
    zus["hinweis"] = "Landoberflächentemperatur = Oberfläche aus Satellitendaten an heißen Tagen (nicht Lufttemperatur)."
    return {"zusammenfassung": zus, "files": files}


# =====================================================================================================
# Lärm, Natur, Boden, Geologie (Hessen)
# =====================================================================================================
K_UMWELT = "Natur, Boden & Lärm"


@quelle("hlnug_laerm", "Lärmkartierung Hessen (Straße, Schiene, Industrie, Flug)", K_UMWELT, "HLNUG",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://www.hlnug.de/themen/laerm/laermkartierung",
        "Amtliche Lärmpegel LDEN (Tag-Abend-Nacht) und LNight am Punkt aus der EU-Umgebungslärmkartierung 2017 und 2022.",
        art="punkt")
def hlnug_laerm(lat, lon, r, p):
    ms = f"{HLNUG}/laerm/umgebungslaerm/MapServer"
    layers = _arc_layers(ms)
    by_id = {l_["id"]: l_ for l_ in layers}

    def pfad(l_):
        teile = [l_["name"]]
        while l_.get("parentLayer"):
            l_ = by_id.get(l_["parentLayer"]["id"], {})
            if not l_:
                break
            teile.append(l_["name"])
        return " / ".join(reversed(teile))
    kand = [l_["id"] for l_ in layers if l_.get("type") == "Raster Layer"
            and re.search(r"2017|2022", pfad(l_)) and re.search(r"LDEN|LNight|Lärmpegel|Tagespegel|Nachtpegel|Gesamtlärm", l_["name"], re.I)
            and not re.search(r"Isophone|Kennziffer|Gebäude|Einwohner|ruhige", l_["name"], re.I)]
    pakete = [kand[i:i + 12] for i in range(0, len(kand), 12)]
    hits = [h_ for r_ in _parallel(lambda ids: _arc_identify(ms, lat, lon, ids, tol=1, timeout=30), pakete, 4)
            if not isinstance(r_, Exception) for h_ in r_]
    werte = []
    for h_ in hits:
        a = h_.get("attributes") or {}
        v = a.get("Classify.Pixelwert") or a.get("Pixel Value") or _first(_attrs(a), r"pegel|db|klasse|lden|lnight|wert")
        if v is None or str(v).lower() == "nodata":
            continue
        try:
            v = round(float(v), 1)
        except (TypeError, ValueError):
            pass
        werte.append({"kartierung": pfad(by_id.get(h_["layerId"], {"name": h_["layerName"]})), "wert_db": v})
    werte.sort(key=lambda w_: w_["kartierung"], reverse=True)  # neueste Kartierung zuerst
    return {"zusammenfassung": {"pegel_am_punkt": werte or "Punkt liegt außerhalb der kartierten Lärmbänder (< ca. 55 dB LDEN / 50 dB LNight oder nicht kartiert)",
                                "richtwerte": "Gesundheitsrisiko ab ca. 65 dB(A) LDEN bzw. 55 dB(A) LNight (Lärmaktionsplanung Hessen)"}}


@quelle("hlnug_schutzgebiete", "Schutzgebiete Hessen (NSG, LSG, FFH, Vogelschutz, Naturdenkmale)", K_UMWELT, "HLNUG (NATUREG)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://natureg.hessen.de",
        "Naturschutz-, Landschaftsschutz-, FFH- und Vogelschutzgebiete, Naturdenkmale, Naturparke im Umkreis.")
def hlnug_schutzgebiete(lat, lon, r, p):
    ebenen = {1: "Naturschutzgebiet", 5: "Landschaftsschutzgebiet", 4: "FFH-Gebiet", 3: "Vogelschutzgebiet",
              0: "Naturdenkmal", 6: "Naturpark", 2: "Nationalpark"}
    zus, files = _arc_ebenen(f"{HLNUG}/natureg/schutzgebiete/MapServer", ebenen, _bbox(lat, lon, r), lat, lon, "schutzgebiete_hessen")
    return {"zusammenfassung": zus, "files": files}


@quelle("hlnug_wasserschutz", "Trinkwasser- und Heilquellenschutzgebiete Hessen", K_UMWELT, "HLNUG (GruSchu)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://gruschu.hessen.de",
        "Wasserschutzgebiete mit Schutzzonen (I, II, III) – wichtig für Bauvorhaben und Versickerung.")
def hlnug_wasserschutz(lat, lon, r, p):
    ebenen = {8: "Trinkwasserschutzgebiet (flurstücksgenau)", 9: "Trinkwasserschutzgebiet (sonstige)",
              7: "Trinkwasserschutzgebiet (TK25)", 3: "Heilquellenschutzgebiet (flurstücksgenau)",
              4: "Heilquellenschutzgebiet (sonstige)", 2: "Heilquellenschutzgebiet (TK25)"}

    def key(pr):
        zone = _first(pr, r"zone")
        nm = _first(pr, r"^name", r"name", r"bez")
        return " ".join(str(x) for x in (nm, f"Zone {zone}" if zone else None) if x) or None
    zus, files = _arc_ebenen(f"{HLNUG}/gruschu/gruschu_wsg/MapServer", ebenen, _bbox(lat, lon, r), lat, lon,
                             "wasserschutzgebiete", key_fn=key)
    return {"zusammenfassung": zus, "files": files}


@quelle("hlnug_biotope", "Geschützte Biotope und Lebensraumtypen Hessen", K_UMWELT, "HLNUG (Hessische Biotopkartierung)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://natureg.hessen.de",
        "Gesetzlich geschützte Biotope, FFH-Lebensraumtypen, Streuobst und Gehölze aus Luftbildern.")
def hlnug_biotope(lat, lon, r, p):
    ebenen = {8: "Gesetzlich geschütztes Biotop", 0: "FFH-Lebensraumtyp", 1: "Sonstiges Biotop",
              6: "Streuobst/Gehölz (Luftbild)"}
    zus, files = _arc_ebenen(f"{HLNUG}/natureg/biotope_lebensraeume/MapServer", ebenen, _bbox(lat, lon, r), lat, lon,
                             "biotope", key_fn=lambda pr: _first(pr, r"biotop.*(name|typ|bez)", r"lrt", r"typ", r"bez"))
    return {"zusammenfassung": zus, "files": files}


@quelle("hlnug_boden", "Bodendaten Hessen (BFD50)", K_UMWELT, "HLNUG (Bodenflächendaten 1:50.000)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://bodenviewer.hessen.de",
        "Boden am Punkt: Bodenhauptgruppe, Feldkapazität, nutzbare Feldkapazität (Wasserspeicher), Ertragspotenzial, "
        "Nitratrückhalt; dazu Karte der Bodenhauptgruppen.")
def hlnug_boden(lat, lon, r, p):
    ms = f"{HLNUG}/boden/bfd50/MapServer"
    hits = _arc_identify(ms, lat, lon, [1, 2, 3, 4, 5, 6], tol=1)
    am_punkt = {h_["layerName"].replace("BFD50_", ""): _attrs(h_.get("attributes")) for h_ in hits}
    bb = _bbox(lat, lon, r)
    feats = _clip(_arc_query(ms, 1, bb), bb)
    for f in feats:
        pr = _attrs(f["properties"])
        nm = _first(pr, r"haupt", r"text", r"bez", r"name") or "Boden"
        f["properties"] = {**pr, "name": str(nm), "_popup": _popup(nm, pr),
                           "_style": _style(PALETTE[hash(str(nm)) % len(PALETTE)], 0.4, 1)}
    return {"zusammenfassung": {"am_punkt": am_punkt or "keine Bodendaten (z.B. Siedlungsfläche nicht kartiert)",
                                "bodenhauptgruppen_im_umkreis": sorted({f["properties"]["name"] for f in feats})[:15]},
            "files": {"boden": _save("boden_hauptgruppen", feats)} if feats else {}}


@quelle("hlnug_geologie", "Geologie und Geogefahren Hessen", K_UMWELT, "HLNUG (Geologischer Dienst)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://geologie.hessen.de",
        "Geologische Einheit (GK25), Erdbebenzone, rutschungsanfällige und setzungsempfindliche Schichten, Karst, Erdfälle.",
        art="punkt")
def hlnug_geologie(lat, lon, r, p):
    jobs = [(f"{HLNUG}/geologie/gk25/MapServer", [22]),
            (f"{HLNUG}/geologie/geogefahren/MapServer", [4, 7, 16, 18, 21])]
    res = _parallel(lambda a: _arc_identify(a[0], lat, lon, a[1], tol=1), jobs, 2)
    out = {}
    for r_ in res:
        if isinstance(r_, Exception):
            out.setdefault("fehler", []).append(str(r_))
            continue
        for h_ in r_:
            out[h_["layerName"]] = _attrs(h_.get("attributes"))
    return {"zusammenfassung": {"am_punkt": out or "keine Einträge (keine bekannten Geogefahren am Punkt)"}}


@quelle("hlnug_radon", "Radonpotenzial (HLNUG / BfS)", K_UMWELT, "HLNUG / Bundesamt für Strahlenschutz",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://www.hlnug.de/themen/geologie/radon",
        "Radonpotenzial und Bodenluft-Prognose am Punkt (wichtig für Neubauten).", art="punkt")
def hlnug_radon(lat, lon, r, p):
    hits = _arc_identify(f"{HLNUG}/geologie/radon/MapServer", lat, lon, [19, 21, 22], tol=1)
    return {"zusammenfassung": {"am_punkt": {h_["layerName"]: _attrs(h_.get("attributes")) for h_ in hits} or "keine Daten"}}


BFN_EBENEN = {"Naturschutzgebiete": "Naturschutzgebiet", "Landschaftsschutzgebiete": "Landschaftsschutzgebiet",
              "Fauna_Flora_Habitat_Gebiete": "FFH-Gebiet", "Vogelschutzgebiete": "Vogelschutzgebiet",
              "Nationalparke": "Nationalpark", "Naturparke": "Naturpark", "Biosphaerenreservate": "Biosphärenreservat"}


@quelle("schutzgebiete_bund", "Schutzgebiete Deutschland (BfN, über ogr2ogr)", K_UMWELT, "Bundesamt für Naturschutz",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://geodienste.bfn.de",
        "Bundesweite Schutzgebiete (NSG, LSG, FFH, Vogelschutz, Nationalparke, Naturparke) aus dem BfN-WFS, "
        "geladen mit GDAL/ogr2ogr aus QGIS.", radius=1000, max_radius=10000)
def schutzgebiete_bund(lat, lon, r, p):
    s, w, n, e = _bbox(lat, lon, r)

    def lade(layer):
        out = _tmp(".geojson")
        try:
            geo_tools.gdal("ogr2ogr", "-f", "GeoJSON", out, "WFS:https://geodienste.bfn.de/ogc/wfs/schutzgebiet",
                           f"schutzgebiet:{layer}", "-spat", w, s, e, n, "-spat_srs", "EPSG:4326", "-t_srs", "EPSG:4326",
                           "-nlt", "PROMOTE_TO_MULTI", timeout=60)
            with open(out, encoding="utf-8") as f:
                return json.load(f)["features"]
        finally:
            _rm(out)
    res = _parallel(lade, list(BFN_EBENEN), 4)
    feats, je_art, fehler = [], {}, []
    for (layer, label), r_ in zip(BFN_EBENEN.items(), res):
        if isinstance(r_, Exception):
            fehler.append(f"{label}: {str(r_)[:150]}")
            continue
        color = PALETTE[len(je_art) % len(PALETTE)]
        names = []
        for f in _clip(r_, (s, w, n, e)):
            pr = _attrs(f["properties"])
            nm = str(_first(pr, r"^name$", r"name") or label)
            names.append(nm)
            f["properties"] = {**pr, "art": label, "name": nm, "_popup": _popup(f"{label}: {nm}", pr),
                               "_style": _style(color, 0.3, 2)}
            feats.append(f)
        je_art[label] = sorted(set(names))
    if len(fehler) == len(BFN_EBENEN):
        raise RuntimeError("BfN-WFS nicht erreichbar (z.B. Wartung). Für Hessen hlnug_schutzgebiete nutzen. "
                           f"Meldung: {fehler[0][:200]}")
    zus = {"im_umkreis": {k: v[:15] for k, v in je_art.items() if v}, "nicht_vorhanden": [k for k, v in je_art.items() if not v]}
    if feats:
        anteile, am_punkt = _flaechen(feats, lambda pr: f"{pr['art']}: {pr['name']}", lat, lon, (s, w, n, e))
        zus.update(am_punkt=am_punkt or "keine", flaechenanteil_im_ausschnitt_pct=dict(list(anteile.items())[:15]))
    if fehler:
        zus["fehler"] = fehler
    return {"zusammenfassung": zus, "files": {"schutzgebiete_bund": _save("schutzgebiete_bund", feats)} if feats else {}}


@quelle("gbif_arten", "Artenfunde (GBIF, inkl. iNaturalist, Vogelbeobachtungen)", K_UMWELT, "Global Biodiversity Information Facility",
        "je Datensatz CC0 / CC BY / CC BY-NC", "https://www.gbif.org",
        "Beobachtete Tier- und Pflanzenarten im Umkreis seit einem Jahr: häufigste Arten, Rote-Liste-Kategorie (IUCN), Fundpunkte.",
        parameter={"ab_jahr": "Standard 2015"})
def gbif_arten(lat, lon, r, p):
    s, w, n, e = _bbox(lat, lon, r)
    wkt = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
    ab = int(p.get("ab_jahr") or 2015)
    j = _http("https://api.gbif.org/v1/occurrence/search", {
        "geometry": wkt, "year": f"{ab},{datetime.date.today().year}", "limit": 300, "hasCoordinate": "true",
        "hasGeospatialIssue": "false", "facet": "speciesKey", "speciesKey.facetLimit": 20}, cache_h=24, timeout=40)
    namen = {}
    for o in j["results"]:
        if o.get("speciesKey"):
            namen[str(o["speciesKey"])] = (o.get("species"), o.get("class"), o.get("iucnRedListCategory"))
    top = (j.get("facets") or [{}])[0].get("counts", [])

    def de_name(key):
        v = _http(f"https://api.gbif.org/v1/species/{key}/vernacularNames", {"limit": 100}, cache_h=24 * 90)
        return next((x["vernacularName"] for x in v.get("results", []) if x.get("language") == "deu"), None)

    def info(key):
        if key not in namen:
            sp = _http(f"https://api.gbif.org/v1/species/{key}", cache_h=24 * 90)
            namen[key] = (sp.get("canonicalName"), sp.get("class"), None)
        return key
    _parallel(info, [c["name"] for c in top], 8)
    de = dict(zip([c["name"] for c in top], _parallel(de_name, [c["name"] for c in top], 8)))
    arten = [{"art": namen.get(c["name"], (c["name"],))[0], "deutsch": None if isinstance(de.get(c["name"]), Exception) else de.get(c["name"]),
              "klasse": namen.get(c["name"], (None, None))[1], "funde": c["count"]} for c in top]
    gefaehrdet = sorted({f"{o.get('species')} ({o.get('iucnRedListCategory')})" for o in j["results"]
                         if o.get("iucnRedListCategory") in ("NT", "VU", "EN", "CR")})
    feats = [_pt(o["decimalLongitude"], o["decimalLatitude"],
                 {"art": o.get("species"), "klasse": o.get("class"), "datum": (o.get("eventDate") or "")[:10],
                  "iucn": o.get("iucnRedListCategory"), "quelle": o.get("datasetName") or o.get("basisOfRecord")},
                 o.get("species") or o.get("scientificName"), "#33a02c") for o in j["results"] if o.get("decimalLatitude")]
    klassen = {}
    for o in j["results"]:
        klassen[o.get("class") or "?"] = klassen.get(o.get("class") or "?", 0) + 1
    return {"zusammenfassung": {"funde_gesamt": j["count"], "zeitraum": f"seit {ab}", "haeufigste_arten": arten,
                                "klassen_in_stichprobe": klassen, "iucn_gefaehrdet_oder_vorwarnliste": gefaehrdet or "keine",
                                "hinweis": "Zufallsfunde von Beobachter:innen, keine systematische Kartierung; "
                                           "Rote Liste Deutschland/Hessen kann abweichen."},
            "files": {"artenfunde": _save("artenfunde", feats)} if feats else {}}


# =====================================================================================================
# Bevölkerung, Verwaltung & Energie
# =====================================================================================================
K_BEV = "Bevölkerung, Verwaltung & Energie"


@quelle("verwaltungseinheit", "Gemeinde, Kreis, Land am Punkt (BKG VG250)", K_BEV,
        "Bundesamt für Kartographie und Geodäsie", "Datenlizenz Deutschland – Namensnennung 2.0 (© GeoBasis-DE / BKG)",
        "https://gdz.bkg.bund.de", "Name, Gemeindeschlüssel (AGS/ARS) und Grenze der Gemeinde, dazu Kreis und Land.",
        art="punkt")
def verwaltungseinheit(lat, lon, r, p):
    res = _parallel(lambda eb: _vg250(lat, lon, eb), ["gem", "krs", "lan"], 3)
    out, feats = {}, []
    for eb, f in zip(("gemeinde", "kreis", "land"), res):
        if isinstance(f, Exception):
            out[eb] = str(f)
            continue
        pr = {k.lower(): v for k, v in f["properties"].items()}
        out[eb] = {k: pr.get(k) for k in ("gen", "bez", "ags", "ars", "ewz", "nuts") if pr.get(k) is not None}
        if eb == "gemeinde":
            g = _geom(f).simplify(0.0003)
            feats.append({"type": "Feature", "geometry": mapping(g),
                          "properties": {"name": pr.get("gen"), "_popup": _popup(pr.get("gen"), out[eb]),
                                         "_style": {"color": "#555555", "fillOpacity": 0.02, "weight": 2}}})
    return {"zusammenfassung": out, "files": {"gemeinde": _save("gemeindegrenze", feats)} if feats else {}}


def _zensus_daten(lat, lon):
    import ladeinfra_data
    s, w, n, e = local_osm.REGION
    if not (s <= lat <= n and w <= lon <= e):
        raise ValueError(f"Zensus- und Ladesäulen-Daten liegen lokal nur für die Region {local_osm.REGION} vor "
                         "(LOCAL_OSM_BBOX in .env).")
    return ladeinfra_data.load()


@quelle("zensus2022", "Zensus 2022 – Einwohner und Gebäude im 100-m-Raster", K_BEV, "Statistisches Bundesamt (Destatis)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://www.zensus2022.de",
        "Einwohner, Gebäude nach Zahl der Wohnungen (Ein-/Mehrfamilienhäuser) und Eigentümerquote im Umkreis, als 100-m-Karte.")
def zensus2022(lat, lon, r, p):
    import ladeinfra_data
    d = _zensus_daten(lat, lon)
    x0, y0 = TO_3035.transform(lon, lat)
    near = np.hypot(d["x"] - x0, d["y"] - y0) <= r
    ew = d["einwohner"][near]
    geb = d["Insgesamt_Gebaeude"][near]
    mfh = d["3bis6_Wohnungen"][near] + d["7bis12_Wohnungen"][near] + d["13undmehr_Wohnungen"][near]
    eq = d["eigentuemerquote"][near]
    ok = ~np.isnan(eq) & (ew > 0)
    xs, ys = d["x"][near], d["y"][near]
    vmax = float(np.percentile(ew[ew > 0], 95)) if (ew > 0).any() else 1
    feats = []
    for x, y, v, g, q in zip(xs, ys, ew, geb, eq):
        if v <= 0 and g <= 0:
            continue
        ring = [FROM_3035.transform(x + dx, y + dy) for dx, dy in ((-50, -50), (50, -50), (50, 50), (-50, 50), (-50, -50))]
        props = {"einwohner": int(v), "gebaeude": int(g), "eigentuemerquote": None if np.isnan(q) else round(float(q), 2)}
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[round(a, 6), round(b, 6)] for a, b in ring]]},
                      "properties": {**props, "name": f"{int(v)} Einwohner", "_popup": _popup("Zensus-Zelle 100 m", props),
                                     "_style": _style(_ramp(float(v), 0, vmax, RAMP_LILA), 0.6, 0)}})
    return {"zusammenfassung": {
        "einwohner": int(ew.sum()), "flaeche_km2": round(math.pi * r * r / 1e6, 2),
        "einwohner_pro_km2": round(float(ew.sum()) / (math.pi * r * r / 1e6)), "gebaeude_mit_wohnraum": int(geb.sum()),
        "anteil_mehrfamilienhaeuser_pct": round(100 * float(mfh.sum()) / max(float(geb.sum()), 1), 1),
        "eigentuemerquote_mittel": round(float(np.average(eq[ok], weights=ew[ok])), 2) if ok.any() else None,
        "hinweis": "Werte < 3 sind im Zensus aus Datenschutzgründen geheim gehalten und hier als 0 gezählt."},
        "stand": ladeinfra_data.STAND["zensus"], "files": {"zensus": _save("zensus_100m", feats)} if feats else {}}


@quelle("ladesaeulen_register", "Öffentliche Ladesäulen (Ladesäulenregister BNetzA)", K_BEV, "Bundesnetzagentur",
        "CC BY 4.0", "https://www.bundesnetzagentur.de/ladeinfrastruktur",
        "Gemeldete öffentliche Ladepunkte im Umkreis mit Leistung, AC/DC, Betreiber und Inbetriebnahme.", radius=1000)
def ladesaeulen_register(lat, lon, r, p):
    import ladeinfra_data
    d = _zensus_daten(lat, lon)
    near = [s_ for s_ in d["stations"] if _dist(lat, lon, s_["lat"], s_["lon"]) <= r]
    feats = [_pt(s_["lon"], s_["lat"], {"betreiber": s_["betreiber"], "ladepunkte": s_["ladepunkte"], "kw": s_["kw"],
                                         "art": s_["art"], "seit": s_["seit"], "adresse": s_["adresse"]},
                 s_["betreiber"], "#d7191c" if s_["art"].startswith("Schnell") else "#2a7de1") for s_ in near]
    betr = {}
    for s_ in near:
        betr[s_["betreiber"]] = betr.get(s_["betreiber"], 0) + s_["ladepunkte"]
    return {"zusammenfassung": {
        "ladeeinrichtungen": len(near), "ladepunkte": sum(s_["ladepunkte"] for s_ in near),
        "schnelllader": sum(1 for s_ in near if s_["art"].startswith("Schnell")),
        "leistung_kw_summe": round(sum(s_["kw"] or 0 for s_ in near)),
        "groesste_betreiber": dict(sorted(betr.items(), key=lambda kv: -kv[1])[:8])},
        "stand": ladeinfra_data.STAND["bnetza"], "files": {"ladesaeulen": _save("ladesaeulen_register", feats)} if feats else {}}


MASTR = "https://www.marktstammdatenregister.de/MaStR/Einheit/EinheitJson/GetErweiterteOeffentlicheEinheitStromerzeugung"


@quelle("marktstammdaten", "Stromerzeuger und Speicher (Marktstammdatenregister)", K_BEV, "Bundesnetzagentur (MaStR)",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://www.marktstammdatenregister.de",
        "Alle Stromerzeugungsanlagen der Gemeinde (PV, Wind, Biomasse, Speicher, BHKW ...) nach Energieträger, "
        "größere Anlagen mit Standort im Umkreis.", radius=1000, max_radius=20000)
def marktstammdaten(lat, lon, r, p):
    pr = {k.lower(): v for k, v in _vg250(lat, lon)["properties"].items()}
    ags = pr["ags"]

    def seite(i):
        return _http(MASTR, {"sort": "Bruttoleistung-desc", "page": i, "pageSize": 5000, "group": "",
                             "filter": f"Gemeindeschlüssel~eq~'{ags}'"}, cache_h=24 * 7, timeout=90)
    erste = seite(1)
    total = erste.get("Total", 0)
    seiten = min(math.ceil(total / 5000), 4)
    daten = list(erste["Data"])
    for r_ in _parallel(seite, list(range(2, seiten + 1)), 3):
        if not isinstance(r_, Exception):
            daten += r_["Data"]
    je = {}
    for u in daten:
        if u.get("BetriebsStatusName") != "In Betrieb":
            continue
        e = je.setdefault(u.get("EnergietraegerName") or "?", {"anzahl": 0, "leistung_kw": 0.0})
        e["anzahl"] += 1
        e["leistung_kw"] += u.get("Bruttoleistung") or 0

    def datum(v):
        m = re.search(r"-?\d+", str(v or ""))
        return str(datetime.date(1970, 1, 1) + datetime.timedelta(milliseconds=int(m.group()))) if m else None
    nah = [u for u in daten if u.get("Breitengrad") and _dist(lat, lon, u["Breitengrad"], u["Laengengrad"]) <= r]
    feats = [_pt(u["Laengengrad"], u["Breitengrad"], {
        "energietraeger": u.get("EnergietraegerName"), "leistung_kw": u.get("Bruttoleistung"),
        "status": u.get("BetriebsStatusName"), "inbetriebnahme": datum(u.get("InbetriebnahmeDatum")),
        "betreiber": u.get("AnlagenbetreiberName"), "strasse": u.get("Strasse")}, u.get("EinheitName"),
        PALETTE[hash(u.get("EnergietraegerName")) % len(PALETTE)]) for u in nah]
    return {"zusammenfassung": {
        "gemeinde": pr.get("gen"), "einheiten_gesamt": total, "ausgewertet": len(daten),
        "in_betrieb_je_energietraeger": {k: {"anzahl": v["anzahl"], "leistung_mw": round(v["leistung_kw"] / 1000, 2)}
                                         for k, v in sorted(je.items(), key=lambda kv: -kv[1]["leistung_kw"])},
        "anlagen_mit_standort_im_umkreis": len(nah),
        "groesste_im_umkreis": [{"name": u.get("EinheitName"), "energietraeger": u.get("EnergietraegerName"),
                                 "kw": u.get("Bruttoleistung"), "abstand_m": round(_dist(lat, lon, u["Breitengrad"], u["Laengengrad"]))}
                                for u in nah[:10]],
        "hinweis": "Kleine Anlagen (z.B. private PV) haben aus Datenschutzgründen keinen genauen Standort."},
        "files": {"stromerzeuger": _save("stromerzeuger_mastr", feats)} if feats else {}}


SMARD = {4068: "Photovoltaik", 4067: "Wind an Land", 1225: "Wind auf See", 4066: "Biomasse", 1226: "Wasserkraft",
         1228: "Sonstige Erneuerbare", 1223: "Braunkohle", 4069: "Steinkohle", 4071: "Erdgas", 4070: "Pumpspeicher",
         1227: "Sonstige Konventionelle", 1224: "Kernenergie"}


@quelle("strommix", "Strommix Deutschland letzte 7 Tage (SMARD)", K_BEV, "Bundesnetzagentur (SMARD)", "CC BY 4.0",
        "https://www.smard.de", "Stromerzeugung nach Energieträger, Anteil Erneuerbarer, Verbrauch und Börsenstrompreis.",
        art="global")
def strommix(lat, lon, r, p):
    def serie(f):
        ts = _http(f"https://www.smard.de/app/chart_data/{f}/DE/index_hour.json", cache_h=6)["timestamps"][-2:]
        werte = {}
        for t in ts:
            for a, b in _http(f"https://www.smard.de/app/chart_data/{f}/DE/{f}_DE_hour_{t}.json", cache_h=3)["series"]:
                if b is not None:
                    werte[a] = b
        return werte
    ids = list(SMARD) + [410, 4169]
    res = dict(zip(ids, _parallel(serie, ids, 8)))
    last = res[410] if not isinstance(res[410], Exception) else {}
    stunden = sorted(last)[-168:]
    erz = {SMARD[f]: round(sum(res[f].get(t, 0) for t in stunden) / 1000) for f in SMARD if not isinstance(res[f], Exception)}
    summe = sum(erz.values()) or 1
    ee = sum(v for k, v in erz.items() if k in ("Photovoltaik", "Wind an Land", "Wind auf See", "Biomasse", "Wasserkraft", "Sonstige Erneuerbare"))
    preis = [res[4169][t] for t in stunden if not isinstance(res[4169], Exception) and t in res[4169]]
    return {"zusammenfassung": {
        "zeitraum": f"{datetime.datetime.fromtimestamp(stunden[0] / 1000):%d.%m.%Y %H:%M} bis "
                    f"{datetime.datetime.fromtimestamp(stunden[-1] / 1000):%d.%m.%Y %H:%M}" if stunden else None,
        "erzeugung_gwh": dict(sorted(erz.items(), key=lambda kv: -kv[1])),
        "anteil_erneuerbar_pct": round(100 * ee / summe, 1),
        "verbrauch_gwh": round(sum(last[t] for t in stunden) / 1000),
        "boersenpreis_mittel_eur_mwh": round(float(np.mean(preis)), 1) if preis else None}}


# =====================================================================================================
# Fernerkundung & Landbedeckung
# =====================================================================================================
K_FERN = "Satellit & Landbedeckung"


def _eea(service, lat, lon, r, res=10):
    n = int(min(max(2 * r / res, 10), 400))
    x, y = TO_3035.transform(lon, lat)
    raw = _http(f"https://image.discomap.eea.europa.eu/arcgis/rest/services/GioLandPublic/{service}/ImageServer/exportImage", {
        "bbox": f"{x - r},{y - r},{x + r},{y + r}", "bboxSR": 3035, "imageSR": 3035, "size": f"{n},{n}",
        "format": "tiff", "pixelType": "U8", "interpolation": "RSP_NearestNeighbor",
        "noDataInterpretation": "esriNoDataMatchAny", "f": "image"}, fmt="bytes", cache_h=24 * 90, timeout=40)
    if raw[:1] == b"{":
        raise RuntimeError(f"EEA-Bilddienst: {raw[:200]!r}")
    a = np.asarray(Image.open(io.BytesIO(raw)), dtype=float)
    a[a > 100] = np.nan
    return a, x - r, y + r, 2 * r / n


@quelle("copernicus_versiegelung", "Versiegelungsgrad 10 m (Copernicus HRL)", K_FERN,
        "Europäische Umweltagentur / Copernicus Land Monitoring Service", "frei (Copernicus, © EU)",
        "https://land.copernicus.eu/en/products/high-resolution-layer-imperviousness",
        "Anteil versiegelter Fläche je 10-m-Zelle (0-100 %, Stand 2018) als Karte und Kennzahlen.", max_radius=3000)
def copernicus_versiegelung(lat, lon, r, p):
    a, x0, yt, res = _eea("HRL_ImperviousnessDensity_2018", lat, lon, r)
    v = a[~np.isnan(a)]
    feats = _grid(a, x0, yt, res, lambda x: _ramp(x, 0, 100, RAMP_VERSIEGELT), "versiegelung_pct", "%", min_wert=1)
    return {"zusammenfassung": {
        "versiegelung_mittel_pct": round(float(v.mean()), 1) if v.size else None, "am_punkt_pct": _mitte(a),
        "anteil_stark_versiegelt_ab_80pct": round(100 * float((v >= 80).mean()), 1) if v.size else None,
        "anteil_unversiegelt_pct": round(100 * float((v == 0).mean()), 1) if v.size else None,
        "zellgroesse_m": round(res, 1)}, "stand": "2018",
        "files": {"versiegelung": _save("versiegelung_copernicus", feats)}}


@quelle("copernicus_baumbedeckung", "Baumbedeckung 10 m (Copernicus HRL)", K_FERN,
        "Europäische Umweltagentur / Copernicus Land Monitoring Service", "frei (Copernicus, © EU)",
        "https://land.copernicus.eu/en/products/high-resolution-layer-tree-cover-density",
        "Kronenbedeckung je 10-m-Zelle (0-100 %, Stand 2018) – erfasst auch Bäume, die in OSM fehlen.", max_radius=3000)
def copernicus_baumbedeckung(lat, lon, r, p):
    a, x0, yt, res = _eea("HRL_TreeCoverDensity_2018", lat, lon, r)
    v = a[~np.isnan(a)]
    feats = _grid(a, x0, yt, res, lambda x: _ramp(x, 0, 100, RAMP_GRUEN), "baumbedeckung_pct", "%", min_wert=1)
    return {"zusammenfassung": {
        "kronenbedeckung_mittel_pct": round(float(v.mean()), 1) if v.size else None, "am_punkt_pct": _mitte(a),
        "anteil_flaeche_mit_baeumen_pct": round(100 * float((v > 10).mean()), 1) if v.size else None,
        "zellgroesse_m": round(res, 1)}, "stand": "2018",
        "files": {"baumbedeckung": _save("baumbedeckung_copernicus", feats)}}


WORLDCOVER = {10: ("Bäume", "#006400"), 20: ("Gebüsch", "#ffbb22"), 30: ("Grünland", "#ffff4c"), 40: ("Acker", "#f096ff"),
              50: ("Bebaut", "#fa0000"), 60: ("Kahl/spärlich", "#b4b4b4"), 70: ("Schnee/Eis", "#f0f0f0"),
              80: ("Wasser", "#0064c8"), 90: ("Feuchtgebiet", "#0096a0"), 95: ("Mangroven", "#00cf75"),
              100: ("Moos/Flechten", "#fae6a0")}


@quelle("esa_worldcover", "Landbedeckung 10 m (ESA WorldCover 2021, über GDAL)", K_FERN, "Europäische Weltraumorganisation (ESA)",
        "CC BY 4.0", "https://esa-worldcover.org",
        "Landbedeckungsklassen (Bäume, Grünland, Acker, bebaut, Wasser ...) mit Flächenanteilen; direkt per GDAL aus der Cloud.",
        max_radius=3000)
def esa_worldcover(lat, lon, r, p):
    la3, lo3 = math.floor(lat / 3) * 3, math.floor(lon / 3) * 3
    tile = f"{'N' if la3 >= 0 else 'S'}{abs(la3):02d}{'E' if lo3 >= 0 else 'W'}{abs(lo3):03d}"
    src = f"/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
    a, x0, yt, res = _gdal_area(src, lat, lon, r, 10, "near")
    a[a == 0] = np.nan
    v = a[~np.isnan(a)]
    u, c = np.unique(v, return_counts=True)
    anteile = {WORLDCOVER.get(int(k), (str(k),))[0]: round(100 * n / v.size, 1) for k, n in sorted(zip(u, c), key=lambda t: -t[1])}
    feats = _grid(a, x0, yt, res, lambda x: WORLDCOVER.get(int(x), ("", "#999999"))[1], "klasse", mode=True,
                  namen={k: n for k, (n, _) in WORLDCOVER.items()})
    return {"zusammenfassung": {"anteile_pct": anteile, "am_punkt": WORLDCOVER.get(int(_mitte(a) or 0), ("?",))[0]},
            "stand": "2021", "files": {"landbedeckung": _save("landbedeckung_worldcover", feats)}}


@quelle("sentinel2_ndvi", "Vegetation aus Sentinel-2 (NDVI, über GDAL)", K_FERN, "ESA Copernicus Sentinel-2 über Element 84 Earth Search (AWS)",
        "frei (Copernicus Sentinel-Daten)", "https://earth-search.aws.element84.com",
        "Vegetationsindex NDVI (10 m) aus der wolkenärmsten Sommeraufnahme: Grünanteil, versiegelte/kahle Flächen.",
        max_radius=3000, parameter={"von": "Startdatum (Standard 1. Mai des letzten Sommers)", "bis": "Enddatum (Standard 30. Sept.)",
                                    "max_wolken": "maximale Bewölkung in % (Standard 20)"})
def sentinel2_ndvi(lat, lon, r, p):
    jahr = _sommer_jahr()
    von, bis = p.get("von") or f"{jahr}-05-01", p.get("bis") or f"{jahr}-09-30"
    s, w, n, e = _bbox(lat, lon, r)
    j = _http("https://earth-search.aws.element84.com/v1/search", body={
        "collections": ["sentinel-2-l2a"], "bbox": [w, s, e, n], "datetime": f"{von}T00:00:00Z/{bis}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": float(p.get("max_wolken") or 20)}}, "limit": 5,
        "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}]}, cache_h=24, timeout=30)
    if not j.get("features"):
        raise RuntimeError(f"Keine Sentinel-2-Aufnahme {von} bis {bis} mit wenig Wolken gefunden.")
    best = None
    for f in j["features"]:  # erste Szene, die das Gebiet ganz abdeckt
        bands = {}
        for b in ("red", "nir"):
            asset = f["assets"][b]
            rb = (asset.get("raster:bands") or [{}])[0]
            arr, x0, yt, res = _gdal_area("/vsicurl/" + asset["href"], lat, lon, r, 10, "near")
            arr[arr == 0] = np.nan
            bands[b] = arr * rb.get("scale", 0.0001) + rb.get("offset", 0)
        if _abdeckung(bands["red"]) > 90 or best is None:
            best = (f, bands, x0, yt, res)
        if _abdeckung(bands["red"]) > 90:
            break
    f, bands, x0, yt, res = best
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ndvi = (bands["nir"] - bands["red"]) / (bands["nir"] + bands["red"])
    ndvi[~((bands["nir"] > 0) & (bands["red"] > 0) & (np.abs(ndvi) <= 1))] = np.nan
    v = ndvi[~np.isnan(ndvi)]
    feats = _grid(ndvi, x0, yt, res, lambda x: _ramp(x, 0, 0.8, ["#a50026", "#fdae61", "#ffffbf", "#a6d96a", "#006837"]),
                  "ndvi", fmt="{:.2f}")
    return {"zusammenfassung": {
        "aufnahme": f["id"], "datum": f["properties"]["datetime"][:10], "bewoelkung_pct": round(f["properties"].get("eo:cloud_cover", 0), 1),
        "ndvi": _stat(ndvi), "am_punkt": _mitte(ndvi),
        "anteil_dichte_vegetation_ndvi_ueber_0_5_pct": round(100 * float((v > 0.5).mean()), 1) if v.size else None,
        "anteil_kaum_vegetation_ndvi_unter_0_2_pct": round(100 * float((v < 0.2).mean()), 1) if v.size else None,
        "abdeckung_pct": _abdeckung(ndvi), "erklaerung": "NDVI: < 0,2 versiegelt/kahl/Wasser, 0,2-0,5 lückig, > 0,5 dichte Vegetation"},
        "stand": f["properties"]["datetime"][:10], "files": {"ndvi": _save("ndvi_sentinel2", feats)}}


@quelle("landsat_oberflaechentemperatur", "Oberflächentemperatur aus Landsat (über GDAL)", K_FERN,
        "USGS/NASA Landsat 8/9 über Microsoft Planetary Computer", "gemeinfrei (USGS)", "https://planetarycomputer.microsoft.com",
        "Gemessene Oberflächentemperatur (°C, 30 m) an einem klaren Sommertag (Überflug ca. 10:30 Uhr): Hitzeinseln sichtbar.",
        radius=1000, max_radius=5000, parameter={"von": "Startdatum (Standard 1. Juni des letzten Sommers)",
                                                 "bis": "Enddatum (Standard 31. August)", "max_wolken": "Standard 10 %"})
def landsat_oberflaechentemperatur(lat, lon, r, p):
    jahr = _sommer_jahr()
    von, bis = p.get("von") or f"{jahr}-06-01", p.get("bis") or f"{jahr}-08-31"
    s, w, n, e = _bbox(lat, lon, r)
    j = _http("https://planetarycomputer.microsoft.com/api/stac/v1/search", body={
        "collections": ["landsat-c2-l2"], "bbox": [w, s, e, n], "datetime": f"{von}/{bis}", "limit": 20,
        "query": {"eo:cloud_cover": {"lt": float(p.get("max_wolken") or 10)}, "platform": {"in": ["landsat-8", "landsat-9"]}}},
        cache_h=24, timeout=30)
    feats = sorted(j.get("features", []), key=lambda f: f["properties"].get("eo:cloud_cover", 100))
    if not feats:
        raise RuntimeError(f"Keine Landsat-Aufnahme {von} bis {bis} mit wenig Wolken gefunden.")
    token = _http("https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2", cache_h=0.3)["token"]
    for f in feats[:3]:
        asset = f["assets"]["lwir11"]
        rb = (asset.get("raster:bands") or [{}])[0]
        a, x0, yt, res = _gdal_area("/vsicurl/" + asset["href"] + "?" + token, lat, lon, r, 30, "near")
        a[a == 0] = np.nan
        if _abdeckung(a) > 80:
            break
    lst = a * rb.get("scale", 0.00341802) + rb.get("offset", 149.0) - 273.15
    st = _stat(lst)
    tiles = _grid(lst, x0, yt, res, lambda x: _ramp(x, st.get("p10", 20), st.get("max", 45), RAMP_HITZE),
                  "oberflaechentemperatur_c", "°C", "{:.1f}")
    return {"zusammenfassung": {
        "aufnahme": f["id"], "datum": f["properties"]["datetime"][:10],
        "bewoelkung_szene_pct": f["properties"].get("eo:cloud_cover"), "oberflaechentemperatur_c": st,
        "am_punkt_c": _mitte(lst), "abdeckung_pct": _abdeckung(lst),
        "hinweis": "Oberflächen- (nicht Luft-)temperatur; Dächer/Asphalt sind mittags oft 15-25 K heißer als Wiesen und Wald."},
        "stand": f["properties"]["datetime"][:10], "files": {"oberflaechentemperatur": _save("oberflaechentemperatur_landsat", tiles)}}


@quelle("gelaendehoehe", "Geländehöhe (Copernicus DEM / EU-DEM)", K_FERN, "Open-Meteo (Copernicus DEM 90 m), OpenTopoData (EU-DEM 25 m)",
        "frei (Copernicus) / CC BY 4.0", "https://open-meteo.com/en/docs/elevation-api",
        "Höhe am Punkt und auf einem 7x7-Raster im Umkreis: Hoch- und Tiefpunkte, Höhenunterschied.", radius=300, max_radius=3000)
def gelaendehoehe(lat, lon, r, p):
    s, w, n, e = _bbox(lat, lon, r)
    pts = [(lat, lon)] + [(s + (n - s) * i / 6, w + (e - w) * k / 6) for i in range(7) for k in range(7)]
    j = _http("https://api.open-meteo.com/v1/elevation", {"latitude": ",".join(f"{a:.5f}" for a, _ in pts),
                                                          "longitude": ",".join(f"{b:.5f}" for _, b in pts)}, cache_h=24 * 365)
    h = j["elevation"]
    feats = [_pt(b, a, {"hoehe_m": z}, f"{z:.0f} m", _ramp(z, min(h), max(h), ["#1a9850", "#fee08b", "#d73027"]))
             for (a, b), z in zip(pts[1:], h[1:])]
    eudem = None
    try:
        eudem = _http("https://api.opentopodata.org/v1/eudem25m", {"locations": f"{lat},{lon}"}, cache_h=24 * 365,
                      timeout=10)["results"][0]["elevation"]
    except Exception:
        pass
    i_lo, i_hi = int(np.argmin(h[1:])) + 1, int(np.argmax(h[1:])) + 1
    return {"zusammenfassung": {"hoehe_am_punkt_m": h[0], "hoehe_eudem25_m": None if eudem is None else round(eudem, 1),
                                "min_m": min(h[1:]), "max_m": max(h[1:]), "hoehenunterschied_m": round(max(h[1:]) - min(h[1:]), 1),
                                "tiefster_punkt": {"lat": round(pts[i_lo][0], 5), "lon": round(pts[i_lo][1], 5)},
                                "hoechster_punkt": {"lat": round(pts[i_hi][0], 5), "lon": round(pts[i_hi][1], 5)},
                                "hinweis": "Grobes Höhenmodell (90 m). Für Fließwege das Werkzeug starkregen (DGM1 Hessen, 1 m) nutzen."},
            "files": {"hoehenpunkte": _save("gelaendehoehe", feats)}}


HESSEN_WMS = {"luftbild": ("https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows", "he_dop_rgb", "image/jpeg"),
              "liegenschaftskarte": ("https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-maps.ows", "he_alk", "image/png"),
              "topokarte": ("https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-maps.ows", "he_dtk25", "image/png")}


@quelle("karte_hessen", "Luftbild / Liegenschaftskarte Hessen (HVBG)", K_FERN, "Hessische Verwaltung für Bodenmanagement und Geoinformation",
        "Datenlizenz Deutschland – Zero 2.0", "https://www.gds.hessen.de",
        "Speichert einen Bildausschnitt (Luftbild 20 cm, Liegenschaftskarte ALKIS oder topografische Karte). "
        "Luftbild und ALKIS gibt es auch als Hintergrund in jeder Karte.", radius=300, max_radius=2000,
        parameter={"ebene": "luftbild (Standard), liegenschaftskarte oder topokarte"})
def karte_hessen(lat, lon, r, p):
    ebene = p.get("ebene") or "luftbild"
    if ebene not in HESSEN_WMS:
        raise ValueError(f"ebene muss eine von {list(HESSEN_WMS)} sein")
    url, layer, fmt = HESSEN_WMS[ebene]
    x, y = TO_25832.transform(lon, lat)
    px = int(min(2000, max(400, 2 * r / 0.5)))
    raw = _http(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": layer, "STYLES": "",
                      "CRS": "EPSG:25832", "BBOX": f"{x - r},{y - r},{x + r},{y + r}", "WIDTH": px, "HEIGHT": px,
                      "FORMAT": fmt}, fmt="bytes", cache_h=24 * 30, timeout=60)
    if raw[:5] in (b"<?xml", b"<Serv"):
        raise RuntimeError(raw[:300].decode("utf-8", "replace"))
    path = geo_tools.out_path(f"{ebene}_hessen.{'jpg' if 'jpeg' in fmt else 'png'}")
    with open(path, "wb") as f:
        f.write(raw)
    return {"zusammenfassung": {"bild": os.path.basename(path), "ausschnitt_m": round(2 * r), "pixel": px,
                                "wms": url, "ebene": layer},
            "files": {"bild": path}}


# =====================================================================================================
# Mobilität & Verkehr
# =====================================================================================================
K_MOB = "Mobilität & Verkehr"
MODUS_FARBE = {"BUS": "#1f78b4", "TRAM": "#6a3d9a", "SUBWAY": "#ff7f00", "FERRY": "#00a0a0"}


def _haltestellen(lat, lon, r):
    s, w, n, e = _bbox(lat, lon, r)
    j = _http("https://api.transitous.org/api/v1/map/stops", {"min": f"{s},{w}", "max": f"{n},{e}"}, cache_h=24)
    stops = {}
    for st in j:
        d = _dist(lat, lon, st["lat"], st["lon"])
        if d > r:
            continue
        g = stops.setdefault(st["name"], {"name": st["name"], "lat": st["lat"], "lon": st["lon"], "abstand_m": d,
                                          "verkehrsmittel": set(), "ids": []})
        g["verkehrsmittel"].update(st.get("modes") or [])
        g["ids"].append(st["stopId"])
        if d < g["abstand_m"]:
            g.update(lat=st["lat"], lon=st["lon"], abstand_m=d)
    return sorted(stops.values(), key=lambda x: x["abstand_m"])


@quelle("oepnv_haltestellen", "ÖPNV-Haltestellen (Transitous, DELFI-Fahrpläne)", K_MOB, "Transitous (MOTIS) mit Fahrplänen von DELFI u.a.",
        "Fahrplandaten je Verbund (meist CC BY 4.0 / DL-DE)", "https://transitous.org",
        "Haltestellen im Umkreis mit Verkehrsmitteln (Bus, Tram, S-Bahn, Zug) und Abstand.", max_radius=3000)
def oepnv_haltestellen(lat, lon, r, p):
    stops = _haltestellen(lat, lon, r)
    feats, mittel = [], {}
    for s_ in stops:
        modes = sorted(s_["verkehrsmittel"])
        for m in modes:
            mittel[m] = mittel.get(m, 0) + 1
        main = next((m for m in ("RAIL", "HIGHSPEED_RAIL", "REGIONAL_RAIL", "SUBURBAN", "SUBWAY", "TRAM", "BUS") if m in modes), None)
        color = "#e31a1c" if main and "RAIL" in main or main == "SUBURBAN" else MODUS_FARBE.get(main, "#666666")
        feats.append(_pt(s_["lon"], s_["lat"], {"verkehrsmittel": ", ".join(modes), "abstand_m": round(s_["abstand_m"]),
                                                "steige": len(s_["ids"])}, s_["name"], color))
    return {"zusammenfassung": {"haltestellen": len(stops), "je_verkehrsmittel": mittel,
                                "naechste": [{"name": s_["name"], "abstand_m": round(s_["abstand_m"]),
                                              "verkehrsmittel": sorted(s_["verkehrsmittel"])} for s_ in stops[:12]]},
            "files": {"haltestellen": _save("oepnv_haltestellen", feats)} if feats else {}}


@quelle("oepnv_abfahrten", "Nächste Abfahrten (Transitous, mit Echtzeit)", K_MOB, "Transitous (MOTIS)",
        "Fahrplandaten je Verbund (meist CC BY 4.0 / DL-DE)", "https://transitous.org",
        "Abfahrten an der nächstgelegenen Haltestelle (oder einer genannten) mit Linie, Ziel und Verspätung.", art="punkt",
        parameter={"haltestelle": "Name (optional, sonst die nächste)", "anzahl": "Standard 15"})
def oepnv_abfahrten(lat, lon, r, p):
    stops = _haltestellen(lat, lon, 800)
    if p.get("haltestelle"):
        stops = [s_ for s_ in stops if p["haltestelle"].lower() in s_["name"].lower()] or stops
    if not stops:
        raise ValueError("Keine Haltestelle in 800 m gefunden.")
    halt = stops[0]
    n = int(p.get("anzahl") or 15)

    def abf(sid):
        return _http("https://api.transitous.org/api/v1/stoptimes", {"stopId": sid, "n": n}, cache_h=0.03).get("stopTimes", [])
    alle = []
    for r_ in _parallel(abf, halt["ids"][:6], 6):
        if not isinstance(r_, Exception):
            alle += r_
    out, seen = [], set()
    for t in sorted(alle, key=lambda t: t["place"].get("departure") or ""):
        pl = t["place"]
        key = (t.get("routeShortName"), pl.get("scheduledDeparture"), t.get("headsign"))
        if key in seen:
            continue
        seen.add(key)
        verz = None
        try:
            verz = round((datetime.datetime.fromisoformat(pl["departure"].replace("Z", "+00:00")) -
                          datetime.datetime.fromisoformat(pl["scheduledDeparture"].replace("Z", "+00:00"))).total_seconds() / 60)
        except (KeyError, TypeError, ValueError):
            pass
        out.append({"zeit": _lokalzeit(pl.get("departure") or ""), "linie": t.get("routeShortName"), "ziel": t.get("headsign"),
                    "verkehrsmittel": t.get("mode"), "steig": pl.get("track"),
                    "verspaetung_min": verz if t.get("realTime") else "keine Echtzeit"})
    return {"zusammenfassung": {"haltestelle": halt["name"], "abstand_m": round(halt["abstand_m"]), "abfahrten": out[:n]}}


VALHALLA = "https://valhalla1.openstreetmap.de"
MODUS = {"zu_fuss": "pedestrian", "fahrrad": "bicycle", "auto": "auto"}


@quelle("erreichbarkeit", "Erreichbarkeit / Isochronen (Valhalla, OSM)", K_MOB, "FOSSGIS e.V. (Valhalla-Server, OpenStreetMap-Daten)",
        "ODbL (OSM-Daten), faire Nutzung", "https://valhalla1.openstreetmap.de",
        "Flächen, die in x Minuten zu Fuß, mit dem Rad oder dem Auto erreichbar sind (für Einzugsgebiete, Versorgung).",
        art="punkt", parameter={"modus": "zu_fuss (Standard), fahrrad, auto", "minuten": "Liste, Standard [5, 10, 15]"})
def erreichbarkeit(lat, lon, r, p):
    modus = p.get("modus") or "zu_fuss"
    if modus not in MODUS:
        raise ValueError(f"modus muss einer von {list(MODUS)} sein")
    minuten = sorted(_liste(p.get("minuten"), float) or [5, 10, 15])[:4]
    j = _http(f"{VALHALLA}/isochrone", {"json": json.dumps({
        "locations": [{"lat": lat, "lon": lon}], "costing": MODUS[modus],
        "contours": [{"time": m} for m in minuten], "polygons": True}, separators=(",", ":"))}, cache_h=24 * 7, timeout=40)
    feats, flaechen = [], {}
    for f in sorted(j["features"], key=lambda f: -f["properties"]["contour"]):
        m = f["properties"]["contour"]
        a = round(_area_m2(_geom(f)) / 1e6, 2)
        flaechen[f"{m:g} min"] = a
        c = _ramp(m, minuten[0], minuten[-1] + 0.01, ["#1a9850", "#fee08b", "#d73027"])
        f["properties"] = {"minuten": m, "flaeche_km2": a, "name": f"{m:g} min {modus}", "_popup": f"{m:g} min {modus}: {a} km²",
                           "_style": _style(c, 0.25, 2)}
        feats.append(f)
    return {"zusammenfassung": {"modus": modus, "flaeche_km2_je_zeit": flaechen,
                                "tipp": "Mit zensus2022 oder QGIS (Schnitt mit Zensus-Zellen) lässt sich die erreichbare Bevölkerung zählen."},
            "files": {"isochronen": _save(f"erreichbarkeit_{modus}", feats)}}


def _polyline6(s):
    coords, idx, lat, lon = [], 0, 0, 0
    while idx < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[idx]) - 63
                idx += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += d
            else:
                lon += d
        coords.append([lon / 1e6, lat / 1e6])
    return coords


@quelle("route", "Route und Fahrzeit (Valhalla, OSM)", K_MOB, "FOSSGIS e.V. (Valhalla-Server, OpenStreetMap-Daten)",
        "ODbL (OSM-Daten), faire Nutzung", "https://valhalla1.openstreetmap.de",
        "Weg von lat/lon zu einem Ziel zu Fuß, mit dem Rad oder dem Auto: Länge, Zeit, Wegbeschreibung, Linie für die Karte.",
        art="punkt", parameter={"ziel_lat": "Breite des Ziels (Pflicht)", "ziel_lon": "Länge des Ziels (Pflicht)",
                                "modus": "zu_fuss, fahrrad, auto (Standard)"})
def route(lat, lon, r, p):
    if p.get("ziel_lat") is None or p.get("ziel_lon") is None:
        raise ValueError("Parameter ziel_lat und ziel_lon fehlen (Ziel vorher mit geocode bestimmen).")
    modus = p.get("modus") or "auto"
    j = _http(f"{VALHALLA}/route", {"json": json.dumps({
        "locations": [{"lat": lat, "lon": lon}, {"lat": float(p["ziel_lat"]), "lon": float(p["ziel_lon"])}],
        "costing": MODUS.get(modus, "auto"), "directions_options": {"units": "kilometers", "language": "de-DE"}},
        separators=(",", ":"))},
        cache_h=24, timeout=40)
    trip = j["trip"]
    coords = [c for leg in trip["legs"] for c in _polyline6(leg["shape"])]
    schritte = [m["instruction"] for leg in trip["legs"] for m in leg.get("maneuvers", [])]
    feat = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"name": f"Route {modus}", "_style": {"color": "#e31a1c", "weight": 4}}}
    return {"zusammenfassung": {"modus": modus, "laenge_km": round(trip["summary"]["length"], 2),
                                "dauer_min": round(trip["summary"]["time"] / 60, 1), "wegbeschreibung": schritte[:20]},
            "files": {"route": _save(f"route_{modus}", [feat])}}


AUTOBAHN_ARTEN = {"roadworks": "Baustelle", "closure": "Sperrung", "warning": "Verkehrsmeldung",
                  "electric_charging_station": "Ladestation", "parking_lorry": "Lkw-Parkplatz", "webcam": "Webcam"}


@quelle("autobahn", "Autobahn: Baustellen, Sperrungen, Meldungen (Autobahn GmbH)", K_MOB, "Die Autobahn GmbH des Bundes",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://verkehr.autobahn.de",
        "Aktuelle Baustellen, Sperrungen und Verkehrsmeldungen (auch Lkw-Parkplätze, Ladestationen) im Umkreis.",
        radius=20000, max_radius=100000,
        parameter={"autobahnen": "Liste, Standard A5, A67, A672, A661, A3, A60, A66, A6, A659 (Rhein-Main/Neckar)",
                   "arten": f"Liste aus {list(AUTOBAHN_ARTEN)} (Standard roadworks, closure, warning)"})
def autobahn(lat, lon, r, p):
    roads = _liste(p.get("autobahnen")) or ["A5", "A67", "A672", "A661", "A3", "A60", "A66", "A6", "A659"]
    arten = _liste(p.get("arten")) or ["roadworks", "closure", "warning"]
    jobs = [(rd, a) for rd in roads for a in arten if a in AUTOBAHN_ARTEN]
    res = _parallel(lambda ja: _http(f"https://verkehr.autobahn.de/o/autobahn/{ja[0]}/services/{ja[1]}", cache_h=0.25,
                                     timeout=25).get(ja[1], []), jobs, 8)
    items, feats, seen = [], [], set()
    for (rd, a), lst in zip(jobs, res):
        if isinstance(lst, Exception):
            continue
        for it in lst:
            c = it.get("coordinate") or {}
            try:
                la, lo = float(c["lat"]), float(c["long"])
            except (KeyError, TypeError, ValueError):
                continue
            d = _dist(lat, lon, la, lo)
            if d > r or it.get("identifier") in seen:
                continue
            seen.add(it.get("identifier"))
            e = {"art": AUTOBAHN_ARTEN[a], "titel": it.get("title"), "richtung": (it.get("subtitle") or "").strip(),
                 "gesperrt": it.get("isBlocked") == "true", "abstand_km": round(d / 1000, 1),
                 "details": " ".join(x for x in it.get("description", []) if x)[:250]}
            items.append(e)
            feats.append(_pt(lo, la, e, it.get("title"), "#e31a1c" if e["gesperrt"] else "#ff7f00"))
    je = {}
    for e in items:
        je[e["art"]] = je.get(e["art"], 0) + 1
    return {"zusammenfassung": {"anzahl_je_art": je, "meldungen": sorted(items, key=lambda x: x["abstand_km"])[:20]},
            "files": {"autobahn": _save("autobahn_meldungen", feats)} if feats else {}}


@quelle("bikesharing", "Leihräder (CityBikes: Call a Bike, nextbike ...)", K_MOB, "CityBikes API", "CityBikes-Nutzungsbedingungen (frei, Namensnennung)",
        "https://citybik.es", "Leihrad-Stationen im Umkreis mit freien Rädern und Stellplätzen.", radius=1000, max_radius=10000)
def bikesharing(lat, lon, r, p):
    nets = _http("https://api.citybik.es/v2/networks", {"fields": "id,name,location"}, cache_h=24 * 7)["networks"]
    nah = [n_ for n_ in nets if _dist(lat, lon, n_["location"]["latitude"], n_["location"]["longitude"]) < 30000 + r]
    feats, stationen = [], []
    for res in _parallel(lambda n_: _http(f"https://api.citybik.es/v2/networks/{n_['id']}", cache_h=0.1)["network"], nah, 6):
        if isinstance(res, Exception):
            continue
        for s_ in res.get("stations", []):
            d = _dist(lat, lon, s_["latitude"], s_["longitude"])
            if d <= r:
                e = {"netz": res.get("name"), "freie_raeder": s_.get("free_bikes"), "freie_plaetze": s_.get("empty_slots"),
                     "abstand_m": round(d)}
                stationen.append({"station": s_["name"], **e})
                feats.append(_pt(s_["longitude"], s_["latitude"], e, s_["name"], "#33a02c"))
    return {"zusammenfassung": {"stationen": len(stationen), "freie_raeder_summe": sum(s_["freie_raeder"] or 0 for s_ in stationen),
                                "naechste": sorted(stationen, key=lambda x: x["abstand_m"])[:12]},
            "files": {"leihraeder": _save("leihraeder", feats)} if feats else {}}


UNFALL = "https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/"
UNFALL_KAT = {1: "mit Getöteten", 2: "mit Schwerverletzten", 3: "mit Leichtverletzten"}
UNFALL_ART = {1: "Zusammenstoß mit anfahrendem/haltendem Fahrzeug", 2: "Zusammenstoß mit vorausfahrendem/wartendem Fahrzeug",
              3: "Zusammenstoß seitlich in gleicher Richtung", 4: "Zusammenstoß mit entgegenkommendem Fahrzeug",
              5: "Zusammenstoß mit einbiegendem/kreuzendem Fahrzeug", 6: "Zusammenstoß mit Fußgänger",
              7: "Aufprall auf Hindernis auf der Fahrbahn", 8: "Abkommen nach rechts", 9: "Abkommen nach links", 0: "Unfall anderer Art"}
UNFALL_TYP = {1: "Fahrunfall", 2: "Abbiegeunfall", 3: "Einbiegen/Kreuzen", 4: "Überschreiten (Fußgänger)",
              5: "ruhender Verkehr", 6: "Längsverkehr", 7: "sonstiger Unfall"}


def _unfall_jahr(jahr):
    path = os.path.join(DATA, "unfallatlas", f"unfallorte_{jahr}.npz")
    if os.path.exists(path):
        return dict(np.load(path))
    listing = _http(UNFALL, cache_h=24)
    files = [f["name"] for d in listing.get("datasets", []) for f in d.get("files", [])
             if re.search(rf"{jahr}.*CSV\.zip$", f["name"], re.I)]
    if not files:
        raise ValueError(f"Kein Unfallatlas für {jahr}.")
    z = zipfile.ZipFile(io.BytesIO(_http(UNFALL + files[0], fmt="bytes", timeout=180)))
    name = next(n for n in z.namelist() if n.lower().endswith((".csv", ".txt")))
    raw = z.read(name)
    text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    head = [h.strip().strip('"').lower() for h in lines[0].split(";")]
    idx = {h: i for i, h in enumerate(head)}

    def col(*names):
        return next((idx[n] for n in names if n in idx), None)
    cols = {"lon": col("xgcswgs84"), "lat": col("ygcswgs84"), "monat": col("umonat"), "stunde": col("ustunde"),
            "wochentag": col("uwochentag"), "kat": col("ukategorie"), "art": col("uart"), "typ": col("utyp1"),
            "licht": col("ulichtverh"), "rad": col("istrad"), "pkw": col("istpkw"), "fuss": col("istfuss"),
            "krad": col("istkrad"), "gkfz": col("istgkfz"), "sonst": col("istsonstige", "istsonstig")}
    out = {k: [] for k in cols}
    for ln in lines[1:]:
        f = ln.split(";")
        try:
            row = {k: (float(f[i].strip('"').replace(",", ".")) if i is not None else 0.0) for k, i in cols.items()}
        except (ValueError, IndexError):
            continue
        for k, v in row.items():
            out[k].append(v)
    data = {k: np.array(v, np.float64 if k in ("lat", "lon") else np.int16) for k, v in out.items()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez_compressed(path, **data)
    return data


@quelle("unfallatlas", "Verkehrsunfälle mit Verletzten (Unfallatlas)", K_MOB, "Statistische Ämter des Bundes und der Länder",
        "Datenlizenz Deutschland – Namensnennung 2.0", "https://unfallatlas.statistikportal.de",
        "Punktgenaue Unfälle mit Personenschaden: Anzahl je Jahr und Schwere, Beteiligte (Rad, Fuß, Pkw ...), "
        "Unfallarten, Häufungsstellen. Erster Aufruf lädt ca. 13 MB je Jahr.",
        parameter={"jahre": "Liste, Standard die letzten 3 verfügbaren Jahre"})
def unfallatlas(lat, lon, r, p):
    jahre = _liste(p.get("jahre"), int)
    if not jahre:
        listing = _http(UNFALL, cache_h=24)
        alle = sorted({int(m.group(1)) for d in listing.get("datasets", []) for m in [re.search(r"(\d{4})", d.get("name", ""))] if m})
        jahre = alle[-3:]
    s, w, n, e = _bbox(lat, lon, r)
    je_jahr, feats, sel = {}, [], []
    for jahr in jahre:
        d = _unfall_jahr(jahr)
        m = (d["lat"] >= s) & (d["lat"] <= n) & (d["lon"] >= w) & (d["lon"] <= e)
        ids = np.nonzero(m)[0]
        ids = [i for i in ids if _dist(lat, lon, d["lat"][i], d["lon"][i]) <= r]
        je_jahr[jahr] = len(ids)
        for i in ids:
            row = {k: (float(v[i]) if k in ("lat", "lon") else int(v[i])) for k, v in d.items()}
            row["jahr"] = jahr
            sel.append(row)
    zaehl = lambda key, namen: {namen.get(k, k): v for k, v in sorted(
        {x[key]: sum(1 for y in sel if y[key] == x[key]) for x in sel}.items(), key=lambda kv: -kv[1])}
    beteiligt = {name: sum(1 for x in sel if x[k]) for k, name in
                 (("rad", "Fahrrad"), ("fuss", "Fußgänger"), ("pkw", "Pkw"), ("krad", "Motorrad"), ("gkfz", "Lkw/Güterkraftfahrzeug"), ("sonst", "sonstige"))}
    zellen = {}
    for x in sel:  # Häufungsstellen: 50-m-Raster
        k = (round(x["lat"] / 0.00045), round(x["lon"] / 0.0007))
        zellen.setdefault(k, []).append(x)
    hot = sorted(zellen.values(), key=len, reverse=True)[:5]
    for x in sel:
        feats.append(_pt(x["lon"], x["lat"], {"jahr": x["jahr"], "monat": x["monat"], "stunde": x["stunde"],
                                              "schwere": UNFALL_KAT.get(x["kat"]), "art": UNFALL_ART.get(x["art"]),
                                              "typ": UNFALL_TYP.get(x["typ"]), "rad": bool(x["rad"]), "fuss": bool(x["fuss"])},
                         UNFALL_KAT.get(x["kat"]), {1: "#000000", 2: "#e31a1c", 3: "#fd8d3c"}.get(x["kat"])))
    return {"zusammenfassung": {
        "unfaelle_je_jahr": je_jahr, "je_schwere": zaehl("kat", UNFALL_KAT), "beteiligte": beteiligt,
        "unfallarten": dict(list(zaehl("art", UNFALL_ART).items())[:6]), "unfalltypen": zaehl("typ", UNFALL_TYP),
        "haeufungsstellen_50m": [{"unfaelle": len(c), "lat": round(float(np.mean([x["lat"] for x in c])), 5),
                                  "lon": round(float(np.mean([x["lon"] for x in c])), 5)} for c in hot if len(c) > 1],
        "hinweis": "Nur Unfälle mit Personenschaden (keine Blechschäden)."},
        "files": {"unfaelle": _save("unfaelle", feats)} if feats else {}}


# =====================================================================================================
# Wissen & Orte
# =====================================================================================================
K_WISSEN = "Wissen & Orte"


@quelle("wikipedia", "Wikipedia-Artikel in der Nähe", K_WISSEN, "Wikimedia Foundation", "CC BY-SA 4.0",
        "https://de.wikipedia.org", "Artikel zu Orten im Umkreis (Gebäude, Plätze, Denkmäler, Geschichte) mit Kurztext.",
        radius=1000, max_radius=10000, parameter={"sprache": "de (Standard) oder en"})
def wikipedia(lat, lon, r, p):
    lang = p.get("sprache") or "de"
    api = f"https://{lang}.wikipedia.org/w/api.php"
    geo = _http(api, {"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": int(min(r, 10000)),
                      "gslimit": 50, "format": "json"}, cache_h=24 * 7)["query"]["geosearch"]
    ids = [str(g["pageid"]) for g in geo[:20]]
    ext = {}
    if ids:
        pages = _http(api, {"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "exsentences": 2,
                            "exlimit": 20, "pageids": "|".join(ids), "format": "json"}, cache_h=24 * 7)["query"]["pages"]
        ext = {k: v.get("extract", "") for k, v in pages.items()}
    arts, feats = [], []
    for g in geo:
        e = {"titel": g["title"], "abstand_m": round(g["dist"]), "text": ext.get(str(g["pageid"]), "")[:250],
             "url": f"https://{lang}.wikipedia.org/?curid={g['pageid']}"}
        arts.append(e)
        feats.append(_pt(g["lon"], g["lat"], e, g["title"], "#444444"))
    return {"zusammenfassung": {"artikel": arts[:25], "anzahl": len(arts)},
            "files": {"wikipedia": _save("wikipedia_artikel", feats)} if feats else {}}


@quelle("wikidata", "Wikidata-Objekte und Kulturdenkmäler", K_WISSEN, "Wikimedia Foundation (Wikidata)", "CC0",
        "https://www.wikidata.org", "Objekte mit Koordinaten im Umkreis mit Typ (Schule, Kirche, Brunnen ...) und Denkmalstatus.",
        radius=500, max_radius=3000)
def wikidata(lat, lon, r, p):
    q = f"""SELECT ?item ?itemLabel ?typLabel ?denkmalLabel ?coord ?dist WHERE {{
      SERVICE wikibase:around {{ ?item wdt:P625 ?coord . bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
        bd:serviceParam wikibase:radius "{r / 1000:.3f}" . bd:serviceParam wikibase:distance ?dist . }}
      OPTIONAL {{ ?item wdt:P31 ?typ . }} OPTIONAL {{ ?item wdt:P1435 ?denkmal . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,en". }} }} ORDER BY ?dist LIMIT 600"""
    j = _http("https://query.wikidata.org/sparql", {"query": q, "format": "json"}, cache_h=24 * 7, timeout=40,
              headers={"Accept": "application/sparql-results+json"})
    items = {}
    for b in j["results"]["bindings"]:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        it = items.setdefault(qid, {"name": b.get("itemLabel", {}).get("value", qid), "typen": set(), "denkmal": set(),
                                    "abstand_m": round(float(b["dist"]["value"]) * 1000), "coord": b["coord"]["value"]})
        if "typLabel" in b:
            it["typen"].add(b["typLabel"]["value"])
        if "denkmalLabel" in b:
            it["denkmal"].add(b["denkmalLabel"]["value"])
    feats, typen = [], {}
    for qid, it in items.items():
        m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", it["coord"])
        for t in it["typen"]:
            typen[t] = typen.get(t, 0) + 1
        if m:
            e = {"typ": ", ".join(sorted(it["typen"])), "denkmal": ", ".join(sorted(it["denkmal"])),
                 "abstand_m": it["abstand_m"], "wikidata": f"https://www.wikidata.org/wiki/{qid}"}
            feats.append(_pt(float(m.group(1)), float(m.group(2)), e, it["name"], "#b15928" if it["denkmal"] else "#888888"))
    denkmal = [f"{it['name']} ({', '.join(sorted(it['denkmal']))})" for it in items.values() if it["denkmal"]]
    return {"zusammenfassung": {"objekte": len(items), "haeufigste_typen": dict(sorted(typen.items(), key=lambda kv: -kv[1])[:15]),
                                "denkmaeler": denkmal[:25] or "keine mit Denkmalstatus in Wikidata"},
            "files": {"wikidata": _save("wikidata_objekte", feats)} if feats else {}}


# =====================================================================================================
# Kataloge & generische Dienste (WFS, ArcGIS, WMS, Dateien)
# =====================================================================================================
K_KAT = "Kataloge & beliebige Dienste"


def _datei_laden(url, lat=None, lon=None, r=None):
    if not re.match(r"^https?://", str(url or "")):
        raise ValueError("url muss mit http:// oder https:// beginnen")
    raw = _http(url, fmt="bytes", cache_h=24, timeout=90)
    if len(raw) > 60e6:
        raise ValueError("Datei größer als 60 MB.")
    name = re.sub(r"[^\w.\-]", "_", os.path.basename(url.split("?")[0])) or "download"
    ext = os.path.splitext(name)[1].lower()
    info = {"datei": name, "groesse_kb": round(len(raw) / 1024)}
    files = {}

    def geojson(data, base):
        feats = data.get("features", [])
        keys = sorted({k for f in feats[:200] for k in (f.get("properties") or {})})
        files[base] = _save(base, feats)
        return {"objekte": len(feats), "geometrie": sorted({(f.get("geometry") or {}).get("type") for f in feats[:200]} - {None}),
                "felder": keys[:40], "beispiel": (feats[0].get("properties") if feats else None)}

    def csv_text(text, base):
        import csv as csvmod
        try:
            dialect = csvmod.Sniffer().sniff(text[:5000], delimiters=";,\t|")
            delim = dialect.delimiter
        except csvmod.Error:
            delim = ";"
        rows = list(csvmod.reader(io.StringIO(text), delimiter=delim))
        head, body = rows[0], rows[1:]
        path = geo_tools.out_path(base + ".csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            csvmod.writer(f, delimiter=";").writerows(rows)
        files[base + "_csv"] = path
        res = {"zeilen": len(body), "spalten": head[:50], "beispiel": body[:3]}
        low = [h.lower().strip() for h in head]
        la = next((i for i, h in enumerate(low) if h in ("lat", "latitude", "breite", "breitengrad", "y_wgs84", "wgs84_lat", "geo_lat")), None)
        lo = next((i for i, h in enumerate(low) if h in ("lon", "lng", "long", "longitude", "laenge", "laengengrad", "längengrad", "x_wgs84", "wgs84_lon", "geo_lon")), None)
        if la is not None and lo is not None:
            feats = []
            for row in body:
                try:
                    feats.append(_pt(float(row[lo].replace(",", ".")), float(row[la].replace(",", ".")), dict(zip(head, row)), row[0]))
                except (ValueError, IndexError):
                    pass
            if feats:
                files[base] = _save(base, feats)
                res["punkte_als_geojson"] = len(feats)
        return res
    base = os.path.splitext(name)[0][:40]
    if ext in (".geojson", ".json") and b"FeatureCollection" in raw[:5000]:
        info.update(geojson(json.loads(raw.decode("utf-8-sig")), base))
    elif ext in (".csv", ".txt"):
        text = raw.decode("utf-8-sig") if raw[:3] == b"\xef\xbb\xbf" else raw.decode("utf-8", errors="replace")
        if text.count("�") > 5:
            text = raw.decode("latin1")
        info.update(csv_text(text, base))
    elif ext == ".zip":
        zpath = _tmp(".zip")
        with open(zpath, "wb") as f:
            f.write(raw)
        try:
            z = zipfile.ZipFile(zpath)
            info["inhalt"] = z.namelist()[:40]
            for inner in z.namelist()[:200]:
                low, b2 = inner.lower(), re.sub(r"[^\w\-]", "_", os.path.splitext(os.path.basename(inner))[0])[:40]
                if low.endswith(".shp") or (low.endswith((".geojson", ".gpkg", ".kml", ".gml"))):
                    out = geo_tools.out_path(b2 + ".geojson")
                    geo_tools.gdal("ogr2ogr", "-f", "GeoJSON", "-t_srs", "EPSG:4326", out, f"/vsizip/{zpath}/{inner}", timeout=120)
                    files[b2] = out
                elif low.endswith(".csv") and len(files) < 6:
                    info.setdefault("csv", {})[inner] = csv_text(z.read(inner).decode("utf-8-sig", errors="replace"), b2)
        finally:
            _rm(zpath)
        info["umgewandelt"] = [os.path.basename(v) for v in files.values()]
    else:
        path = geo_tools.out_path(name)
        with open(path, "wb") as f:
            f.write(raw)
        files["datei"] = path
        info["hinweis"] = "Unbekanntes Format: Datei gespeichert, ggf. mit QGIS (run_qgis_algorithm) weiterverarbeiten."
    return {"zusammenfassung": info, "files": files}


@quelle("datei_laden", "Beliebige offene Datei laden (CSV, GeoJSON, ZIP mit Shapefile)", K_KAT, "je nach Quelle", "je nach Datensatz",
        "", "Lädt eine Datei per URL (z.B. aus opendata_darmstadt oder govdata), wandelt Shapefiles/CSV mit Koordinaten in GeoJSON.",
        art="suche", parameter={"url": "Download-Adresse (Pflicht)"})
def datei_laden(lat, lon, r, p):
    return _datei_laden(p.get("url"), lat, lon, r)


def _html_text(s, n=250):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()[:n]


@quelle("opendata_darmstadt", "Open-Data-Portal Darmstadt", K_KAT, "Wissenschaftsstadt Darmstadt", "je Datensatz (meist DL-DE BY 2.0)",
        "https://opendata.darmstadt.de",
        "Städtische Datensätze: Verkehrszählungen der Ampeln (Rohdaten), statistische Bezirke, Bevölkerung, Wohnungen, Sozialatlas, Klima.",
        art="suche", parameter={"suche": "Stichwort, z.B. 'verkehr' oder 'bezirke' (leer = alle Datensätze)",
                                "datensatz": "Name eines Datensatzes für alle Dateien", "url": "Datei direkt laden"})
def opendata_darmstadt(lat, lon, r, p):
    if p.get("url"):
        return _datei_laden(p["url"], lat, lon, r)
    api = "https://opendata.darmstadt.de/api/3/action/"
    namen = _http(api + "package_list", cache_h=24)["result"]
    if p.get("datensatz"):
        treffer = [p["datensatz"]]
    else:
        worte = [w_ for w_ in re.split(r"\W+", (p.get("suche") or "").lower()) if w_]
        treffer = [n_ for n_ in namen if all(w_ in n_.lower() for w_ in worte)] if worte else namen
    def show(n_):
        d = _http(api + "package_show", {"id": n_}, cache_h=24)["result"]
        d = d[0] if isinstance(d, list) else d
        return {"datensatz": d["name"], "titel": d.get("title"), "beschreibung": _html_text(d.get("notes"), 200),
                "lizenz": d.get("license_title"), "dateien": [{"format": x.get("format"), "name": x.get("name"), "url": x.get("url")}
                                                               for x in d.get("resources", [])[:8 if not p.get("datensatz") else 60]],
                "anzahl_dateien": len(d.get("resources", []))}
    res = [x for x in _parallel(show, treffer[:12], 6) if not isinstance(x, Exception)]
    return {"zusammenfassung": {"treffer": len(treffer), "datensaetze": res,
                                "alle_namen": namen if not res else None,
                                "weiter": "Datei laden mit parameter {\"url\": ...}"}}


@quelle("govdata", "GovData – Datenportal für Deutschland", K_KAT, "GovData (Bund, Länder, Kommunen)", "je Datensatz",
        "https://www.govdata.de", "Suche in über 100.000 offenen Datensätzen von Bund, Ländern und Kommunen mit Download-Adressen.",
        art="suche", parameter={"suche": "Suchbegriffe (Pflicht), z.B. 'Darmstadt Bäume'", "url": "Datei direkt laden"})
def govdata(lat, lon, r, p):
    if p.get("url"):
        return _datei_laden(p["url"], lat, lon, r)
    if not p.get("suche"):
        raise ValueError("Parameter suche fehlt.")
    j = _http("https://www.govdata.de/ckan/api/3/action/package_search", {"q": p["suche"], "rows": 10}, cache_h=24)["result"]
    out = [{"titel": d.get("title"), "herausgeber": (d.get("organization") or {}).get("title"),
            "beschreibung": _html_text(d.get("notes"), 200), "lizenz": d.get("license_title") or d.get("license_id"),
            "dateien": [{"format": x.get("format"), "url": x.get("url")} for x in d.get("resources", [])[:5]]}
           for d in j["results"]]
    return {"zusammenfassung": {"treffer_gesamt": j["count"], "datensaetze": out}}


@quelle("geoportal_hessen", "Geoportal Hessen – Kartendienste suchen", K_KAT, "Geoportal Hessen (Mapbender)", "je Dienst",
        "https://www.geoportal.hessen.de", "Sucht WMS/WFS-Dienste von Land und Kommunen (Bebauungspläne, Bodenrichtwerte, Fachkarten ...).",
        art="suche", parameter={"suche": "Suchbegriff (Pflicht)", "typ": "wms (Standard) oder wfs"})
def geoportal_hessen(lat, lon, r, p):
    typ = p.get("typ") or "wms"
    if not p.get("suche"):
        raise ValueError("Parameter suche fehlt.")
    j = _http("https://www.geoportal.hessen.de/mapbender/php/mod_callMetadata.php", {
        "searchText": p["suche"], "searchResources": typ, "outputFormat": "json", "resultTarget": "web"}, cache_h=24)
    srv = (j.get(typ) or {}).get("srv", [])
    out = []
    for s_ in srv[:10]:
        if not s_.get("title"):
            continue
        cap = next((v for k, v in s_.items() if "capabilities" in k.lower() and v), None)
        lay = s_.get("layer") or s_.get("ftype") or []
        out.append({"titel": s_.get("title"), "beschreibung": _html_text(s_.get("abstract"), 180),
                    "capabilities_url": cap, "offen": s_.get("isopen"),
                    "ebenen": [x.get("name") or x.get("title") for x in lay[:6] if isinstance(x, dict)]})
    return {"zusammenfassung": {"dienste": out or "keine Treffer",
                                "weiter": "Mit wms_abfrage (Punktabfrage) oder wfs_abfrage (Objekte laden) nutzen."}}


@quelle("wfs_abfrage", "Beliebigen WFS-Dienst laden (über ogr2ogr)", K_KAT, "je nach Dienst", "je nach Dienst", "",
        "Lädt Objekte eines WFS im Umkreis als GeoJSON (GDAL/ogr2ogr aus QGIS). Ohne layer: Liste der Ebenen.",
        radius=1000, max_radius=20000, parameter={"url": "WFS-Adresse (Pflicht)", "layer": "Ebenen-Name (ohne = Liste)"})
def wfs_abfrage(lat, lon, r, p):
    url = p.get("url")
    if not url:
        raise ValueError("Parameter url fehlt.")
    src = "WFS:" + url
    if not p.get("layer"):
        txt = geo_tools.gdal("ogrinfo", "-ro", "-q", src, timeout=60)
        return {"zusammenfassung": {"ebenen": re.findall(r"^\d+: (\S+)", txt, re.M)[:80],
                                    "weiter": "erneut mit parameter layer aufrufen"}}
    if lat is None:
        raise ValueError("lat/lon fehlen.")
    s, w, n, e = _bbox(lat, lon, r)
    base = re.sub(r"[^\w]", "_", p["layer"].split(":")[-1])[:40]
    out = geo_tools.out_path(base + ".geojson")
    geo_tools.gdal("ogr2ogr", "-f", "GeoJSON", out, src, p["layer"], "-spat", w, s, e, n, "-spat_srs", "EPSG:4326",
                   "-t_srs", "EPSG:4326", "-limit", 5000, timeout=120)
    with open(out, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    if not feats:  # manche Server verstehen den Filter des GDAL-Treibers nicht: BBOX direkt anfragen
        raw = _http(url.split("?")[0], {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": p["layer"],
                                        "bbox": f"{s},{w},{n},{e},urn:ogc:def:crs:EPSG::4326", "count": 5000,
                                        "srsName": "urn:ogc:def:crs:EPSG::4326"}, fmt="bytes", cache_h=24, timeout=90)
        tmp = _tmp(".json" if raw.lstrip()[:1] == b"{" else ".gml")
        with open(tmp, "wb") as f:
            f.write(raw)
        try:
            _rm(out)
            geo_tools.gdal("ogr2ogr", "-f", "GeoJSON", "-t_srs", "EPSG:4326", out, tmp, timeout=120)
        finally:
            _rm(tmp, tmp[:-4] + ".gfs")
        with open(out, encoding="utf-8") as f:
            feats = json.load(f)["features"]
    return {"zusammenfassung": {"objekte": len(feats), "felder": sorted({k for f in feats[:100] for k in (f.get("properties") or {})})[:40],
                                "beispiel": feats[0]["properties"] if feats else None}, "files": {base: out}}


@quelle("arcgis_abfrage", "Beliebigen ArcGIS-REST-Dienst abfragen", K_KAT, "je nach Dienst", "je nach Dienst", "",
        "Objekte einer Ebene eines ArcGIS-MapServers/FeatureServers im Umkreis als GeoJSON (z.B. weitere HLNUG-Fachkarten). "
        "Ohne layer: Liste der Ebenen.", radius=1000, max_radius=10000,
        parameter={"url": "…/MapServer oder …/FeatureServer (Pflicht)", "layer": "Ebenen-Nummer (ohne = Liste)"})
def arcgis_abfrage(lat, lon, r, p):
    url = (p.get("url") or "").rstrip("/")
    m = re.match(r"^(.*/(?:MapServer|FeatureServer))(?:/(\d+))?$", url)
    if not m:
        raise ValueError("url muss auf /MapServer oder /FeatureServer enden, z.B. "
                         f"{HLNUG}/natureg/schutzgebiete/MapServer (Übersicht: {HLNUG})")
    base, layer = m.group(1), p.get("layer", m.group(2))
    if layer in (None, ""):
        return {"zusammenfassung": {"ebenen": [{"id": l_["id"], "name": l_["name"], "typ": l_.get("type")} for l_ in _arc_layers(base)][:120]}}
    if lat is None:
        raise ValueError("lat/lon fehlen.")
    bb = _bbox(lat, lon, r)
    feats = _clip(_arc_query(base, int(layer), bb), bb)
    for f in feats:
        pr = _attrs(f["properties"])
        nm = _first(pr, r"^name", r"name", r"bez", r"klasse", r"typ") or f"Ebene {layer}"
        f["properties"] = {**pr, "name": str(nm), "_popup": _popup(nm, pr)}
    fn = f"arcgis_{base.split('/services/')[-1].replace('/MapServer', '').replace('/', '_')}_{layer}"[:60]
    return {"zusammenfassung": {"objekte": len(feats), "felder": sorted({k for f in feats[:100] for k in f["properties"] if not k.startswith("_")})[:40],
                                "werte": sorted({f["properties"]["name"] for f in feats})[:25]},
            "files": {"ergebnis": _save(fn, feats)} if feats else {}}


@quelle("wms_abfrage", "Beliebigen WMS-Dienst am Punkt abfragen (GetFeatureInfo)", K_KAT, "je nach Dienst", "je nach Dienst", "",
        "Fragt den Wert einer WMS-Ebene am Punkt ab (z.B. aus geoportal_hessen gefundene Fachkarten).", art="punkt",
        parameter={"url": "WMS-Adresse (Pflicht)", "layer": "Ebenen-Name (Pflicht)"})
def wms_abfrage(lat, lon, r, p):
    if not p.get("url") or not p.get("layer"):
        raise ValueError("Parameter url und layer fehlen.")
    base = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": p["layer"], "QUERY_LAYERS": p["layer"],
            "CRS": "EPSG:4326", "STYLES": "", "BBOX": f"{lat - 0.001},{lon - 0.001},{lat + 0.001},{lon + 0.001}",
            "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50, "FEATURE_COUNT": 10}
    letzte = None
    for fmt in ("application/json", "application/geo+json", "text/plain", "text/html", "text/xml"):
        try:
            txt = _http(p["url"], {**base, "INFO_FORMAT": fmt}, fmt="text", cache_h=24, timeout=25)
        except Exception as err:
            letzte = err
            continue
        if "ServiceException" in txt or "ExceptionReport" in txt:
            letzte = _html_text(txt, 300)
            continue
        if fmt.startswith("application"):
            try:
                feats = json.loads(txt).get("features", [])
                return {"zusammenfassung": {"treffer": [_attrs(f.get("properties")) for f in feats][:10] or "keine Objekte am Punkt"}}
            except ValueError:
                continue
        return {"zusammenfassung": {"antwort": _html_text(txt, 1500) or "leer", "format": fmt}}
    raise RuntimeError(f"Keine Antwort im unterstützten Format: {letzte}")


# =====================================================================================================
# Katalog und Abfrage (für den Agenten)
# =====================================================================================================
KATEGORIEN = [K_WETTER, K_LUFT, K_WASSER, K_UMWELT, K_BEV, K_FERN, K_MOB, K_WISSEN, K_KAT]


def katalog(kategorie=None, suche=None):
    out = []
    for q in QUELLEN.values():
        if kategorie and kategorie.lower() not in q["kategorie"].lower():
            continue
        text = " ".join(str(q[k]) for k in ("id", "name", "beschreibung", "anbieter", "kategorie")).lower()
        if suche and not all(w_ in text for w_ in suche.lower().split()):
            continue
        out.append({k: q[k] for k in ("id", "name", "kategorie", "anbieter", "lizenz", "art", "beschreibung", "parameter")} |
                   ({"radius_standard_m": q["radius"], "radius_max_m": q["max_radius"]} if q["art"] == "umkreis" else {}))
    return out


def katalog_text():
    """Kompakter Katalog für den Systemprompt."""
    zeilen = []
    for kat in KATEGORIEN:
        zeilen.append(f"{kat}:")
        for q in QUELLEN.values():
            if q["kategorie"] != kat:
                continue
            par = f" [Parameter: {', '.join(q['parameter'])}]" if q["parameter"] else ""
            rad = f" (Umkreis, Standard {q['radius']} m)" if q["art"] == "umkreis" else ""
            zeilen.append(f"- {q['id']}: {q['beschreibung']}{rad}{par}")
    return "\n".join(zeilen)


def _kuerzen(obj, n_list=30, n_str=700, tiefe=0):
    if isinstance(obj, dict):
        return {k: (v if k == "files" else _kuerzen(v, n_list, n_str, tiefe + 1)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        out = [_kuerzen(v, n_list, n_str, tiefe + 1) for v in list(obj)[:n_list]]
        if len(obj) > n_list:
            out.append(f"... und {len(obj) - n_list} weitere")
        return out
    if isinstance(obj, str) and len(obj) > n_str:
        return obj[:n_str] + " …"
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else round(float(obj), 3)
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def abfragen(quelle, lat=None, lon=None, radius_m=None, parameter=None):
    """Datenquelle abfragen. -> dict mit quelle (Metadaten), zusammenfassung, files (GeoJSON-Pfade), sekunden."""
    if quelle not in QUELLEN:
        raise ValueError(f"Unbekannte Datenquelle '{quelle}'. Verfügbar: {', '.join(QUELLEN)}")
    q = QUELLEN[quelle]
    p = parameter or {}
    if isinstance(p, str):
        p = json.loads(p) if p.strip() else {}
    if q["art"] in ("punkt", "umkreis") and (lat is None or lon is None):
        raise ValueError("lat und lon fehlen: den Ort vorher mit geocode bestimmen.")
    r = max(10.0, min(float(radius_m or q["radius"]), float(q["max_radius"])))
    start = time.time()
    res = q["fn"](None if lat is None else float(lat), None if lon is None else float(lon), r, p)
    out = {"quelle": {"id": q["id"], "name": q["name"], "anbieter": q["anbieter"], "lizenz": q["lizenz"], "url": q["url"],
                      "stand": res.pop("stand", None) or datetime.date.today().isoformat()}}
    if q["art"] == "umkreis":
        out["radius_m"] = round(r)
        if radius_m and float(radius_m) > q["max_radius"]:
            out["hinweis_radius"] = f"Radius auf {q['max_radius']} m begrenzt."
    out.update(res)
    out.setdefault("files", {})
    out["sekunden"] = round(time.time() - start, 1)
    return _kuerzen(out)


# ---------- Selbsttest ----------
TEST_PUNKT = (49.8728, 8.6512)  # Luisenplatz Darmstadt
TEST_PARAMETER = {
    "route": {"ziel_lat": 49.8749, "ziel_lon": 8.6569, "modus": "zu_fuss"},
    "datei_laden": {"url": "https://opendata.darmstadt.de/sites/default/files/DA_ST_Bezirke.geojson"},
    "opendata_darmstadt": {"suche": "bezirke"},
    "govdata": {"suche": "Darmstadt Verkehr"},
    "geoportal_hessen": {"suche": "Starkregen"},
    "wfs_abfrage": {"url": "https://sgx.geodatenzentrum.de/wfs_vg250", "layer": "vg250:vg250_gem"},
    "arcgis_abfrage": {"url": f"{HLNUG}/klima/hitzeviewer/MapServer", "layer": 4},
    "wms_abfrage": {"url": "https://maps.dwd.de/geoserver/dwd/wms", "layer": "dwd:Summerdays_annual_map_normals_1971_30"},
    "unfallatlas": {"jahre": [2024]},
    "dwd_klimaraster": {"groessen": ["heisse_tage", "temperatur_mittel"], "von_jahr": 2021},
    "stadtklima_waermeinsel": {"jahre": ["2023", "2024"]},
}


def selbsttest(lat=TEST_PUNKT[0], lon=TEST_PUNKT[1], quellen=None, parallel=6, timeout=150):
    """Alle Quellen kurz aufrufen. -> [{"quelle", "ok", "sekunden", "info"}]"""
    geo_tools.new_run("datenquellen_selbsttest")
    ids = quellen or list(QUELLEN)

    def eins(qid):
        t = time.time()
        try:
            res = abfragen(qid, lat, lon, None, TEST_PARAMETER.get(qid))
            return {"quelle": qid, "ok": True, "sekunden": round(time.time() - t, 1),
                    "info": json.dumps(res.get("zusammenfassung"), ensure_ascii=False)[:160], "dateien": len(res.get("files", {}))}
        except Exception as err:
            return {"quelle": qid, "ok": False, "sekunden": round(time.time() - t, 1), "info": f"{type(err).__name__}: {err}"[:300]}
    with ThreadPoolExecutor(parallel) as ex:
        futs = [ex.submit(eins, q) for q in ids]
        out = []
        for qid, fut in zip(ids, futs):
            try:
                out.append(fut.result(timeout=timeout))
            except Exception as err:
                out.append({"quelle": qid, "ok": False, "sekunden": timeout, "info": f"Zeitüberschreitung/Fehler: {err}"})
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "liste"
    if cmd == "test":
        res = selbsttest(quellen=sys.argv[2:] or None)
        for r_ in res:
            print(f"{'OK ' if r_['ok'] else 'ERR'} {r_['sekunden']:6.1f}s  {r_['quelle']:32} {r_['info']}")
        print(f"\n{sum(r_['ok'] for r_ in res)}/{len(res)} Quellen OK. Dateien: {geo_tools.run_dir()}")
    elif cmd == "liste":
        print("| Kategorie | ID | Name | Anbieter | Lizenz |\n|---|---|---|---|---|")
        for q in QUELLEN.values():
            print(f"| {q['kategorie']} | `{q['id']}` | {q['name']} | {q['anbieter']} | {q['lizenz']} |")
    else:
        lat, lon = (float(sys.argv[3]), float(sys.argv[4])) if len(sys.argv) > 4 else TEST_PUNKT
        print(json.dumps(abfragen(cmd, lat, lon, float(sys.argv[5]) if len(sys.argv) > 5 else None,
                                  json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].startswith("{") else None),
                         ensure_ascii=False, indent=1)[:4000])
