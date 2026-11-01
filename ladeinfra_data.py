"""
Datenquellen für die Ladesäulen-Analyse, ausgeschnitten auf die lokale Region (LOCAL_OSM_BBOX, Standard Darmstadt).

Einmalig herunterladen (je wenige Sekunden) nach data/:
  data/zensus/Zensus2022_Bevoelkerungszahl.zip                      Einwohner je 100-m-Zelle
  data/zensus/Gebaeude_nach_Anzahl_der_Wohnungen_im_Gebaeude.zip    Ein-/Mehrfamilienhäuser je Zelle
  data/zensus/Eigentuemerquote_in_Gitterzellen.zip                  Anteil Eigentümer-Haushalte je Zelle
      Quelle: Statistisches Bundesamt, Zensus 2022 (https://www.zensus2022.de), Datenlizenz Deutschland 2.0
  data/bnetza/Ladesaeulenregister.csv                               öffentliche Ladepunkte
      Quelle: Bundesnetzagentur, Ladesäulenregister (https://www.bundesnetzagentur.de/ladeinfrastruktur), CC BY 4.0
(download() erledigt das; danach prepare() bzw. automatisch beim ersten load(), ca. 30 s.)
"""
import csv
import hashlib
import io
import os
import pickle
import time
import urllib.request
import zipfile

import numpy as np
from pyproj import Transformer

import local_osm

HERE = os.path.dirname(os.path.abspath(__file__))
ZENSUS_DIR = os.path.join(HERE, "data", "zensus")
BNETZA_CSV = os.path.join(HERE, "data", "bnetza", "Ladesaeulenregister.csv")
ZENSUS_URL = "https://www.destatis.de/static/DE/zensus/gitterdaten/"
ZENSUS_FILES = {
    "bev": "Zensus2022_Bevoelkerungszahl.zip",
    "geb": "Gebaeude_nach_Anzahl_der_Wohnungen_im_Gebaeude.zip",
    "eig": "Eigentuemerquote_in_Gitterzellen.zip",
}
BNETZA_URL = ("https://data.bundesnetzagentur.de/Bundesnetzagentur/DE/Fachthemen/ElektrizitaetundGas/"
              "E-Mobilitaet/Ladesaeulenregister_BNetzA_2026-09-01.csv")
STAND = {"zensus": "Zensus 2022 (Stichtag 15.05.2022)", "bnetza": "Ladesäulenregister BNetzA, Stand 01.09.2026"}

TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
_DATA = None


def _pkl_path():
    key = hashlib.sha1(f"{local_osm.REGION}".encode()).hexdigest()[:10]
    return os.path.join(HERE, "data", f"ladeinfra_{key}.pkl")


def download():
    """Fehlende Rohdateien laden (Zensus ca. 55 MB, Ladesäulenregister ca. 55 MB)."""
    os.makedirs(ZENSUS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(BNETZA_CSV), exist_ok=True)
    todo = [(ZENSUS_URL + f, os.path.join(ZENSUS_DIR, f)) for f in ZENSUS_FILES.values()] + [(BNETZA_URL, BNETZA_CSV)]
    for url, path in todo:
        if not os.path.exists(path):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 uni-qgis-prototype"})
            with urllib.request.urlopen(req, timeout=300) as r, open(path + ".tmp", "wb") as f:
                f.write(r.read())
            os.replace(path + ".tmp", path)


def _num(v):
    v = (v or "").strip().replace(".", "").replace(",", ".") if v and v.count(",") == 1 else (v or "").strip()
    try:
        return float(v)
    except ValueError:
        return 0.0 if v in ("–", "-", "") else np.nan


def _zensus_rows(key, box):
    """Zeilen der 100-m-Tabelle im Gebiet box (x0, y0, x1, y1 in EPSG:3035)."""
    z = zipfile.ZipFile(os.path.join(ZENSUS_DIR, ZENSUS_FILES[key]))
    name = next(i.filename for i in z.infolist() if "100m" in i.filename and i.filename.endswith(".csv"))
    with z.open(name) as fh:
        reader = csv.reader(io.TextIOWrapper(fh, encoding="utf-8-sig"), delimiter=";")
        header = next(reader)
        x0, y0, x1, y1 = box
        for row in reader:
            x, y = int(row[1]), int(row[2])
            if x0 <= x <= x1 and y0 <= y <= y1:
                yield header, row


def prepare():
    """Zensus-Raster und Ladesäulenregister auf die Region zuschneiden und kompakt speichern."""
    download()
    start = time.time()
    s, w, n, e = local_osm.REGION
    xs, ys = TO_3035.transform([w, e, w, e], [s, s, n, n])
    box = (min(xs) - 100, min(ys) - 100, max(xs) + 100, max(ys) + 100)

    cells = {}
    for _, row in _zensus_rows("bev", box):
        cells[row[0]] = {"x": int(row[1]), "y": int(row[2]), "einwohner": _num(row[3])}
    for header, row in _zensus_rows("geb", box):
        c = cells.setdefault(row[0], {"x": int(row[1]), "y": int(row[2]), "einwohner": 0.0})
        c.update({h: _num(v) for h, v in zip(header[3:], row[3:])})
    for _, row in _zensus_rows("eig", box):
        if row[0] in cells:
            cells[row[0]]["eigentuemerquote"] = _num(row[3]) / 100

    stations = []
    with open(BNETZA_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        header = None
        for row in reader:
            if header is None:
                if row and row[0].startswith("Ladeeinrichtungs-ID"):
                    header = row
                continue
            if len(row) < 17:
                continue
            try:
                lat, lon = float(row[15].replace(",", ".")), float(row[16].replace(",", "."))
            except ValueError:
                continue
            if not (s <= lat <= n and w <= lon <= e):
                continue
            stations.append({
                "id": row[0], "betreiber": row[1], "status": row[3], "art": row[4],
                "ladepunkte": int(_num(row[5]) or 1), "kw": _num(row[6]), "seit": row[7],
                "adresse": f"{row[8]} {row[9]}, {row[11]} {row[12]}".strip(), "lat": lat, "lon": lon})

    keys = sorted(cells)
    cols = ["einwohner", "Insgesamt_Gebaeude", "1_Wohnung", "2_Wohnungen", "3bis6_Wohnungen",
            "7bis12_Wohnungen", "13undmehr_Wohnungen", "eigentuemerquote"]
    data = {
        "region": local_osm.REGION,
        "x": np.array([cells[k]["x"] for k in keys], np.int32),
        "y": np.array([cells[k]["y"] for k in keys], np.int32),
        **{c: np.array([cells[k].get(c, np.nan if c == "eigentuemerquote" else 0.0) for k in keys]) for c in cols},
        "stations": stations,
    }
    with open(_pkl_path(), "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Ladeinfrastruktur-Daten: {len(keys)} Zensus-Zellen, {len(stations)} Ladeeinrichtungen (BNetzA), "
          f"{time.time() - start:.0f}s -> {_pkl_path()}")
    return data


def available():
    return os.path.exists(_pkl_path()) or all(
        os.path.exists(os.path.join(ZENSUS_DIR, f)) for f in ZENSUS_FILES.values()) and os.path.exists(BNETZA_CSV)


def load():
    global _DATA
    if _DATA is None:
        if os.path.exists(_pkl_path()):
            with open(_pkl_path(), "rb") as f:
                _DATA = pickle.load(f)
        else:
            _DATA = prepare()
    return _DATA


if __name__ == "__main__":
    prepare()
