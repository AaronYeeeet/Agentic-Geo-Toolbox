from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.sources.registry import DEFAULT_REGISTRY, RegistryError, load_registry

VALID_ENTRY = """
- id: hessen-dop20
  title: { en: "Aerial imagery Hessen (DOP20)", de: "Luftbild Hessen (DOP20)" }
  provider: "HVBG"
  type: wms
  url: "https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows"
  layers: [he_dop20_rgb]
  license: { name: "DL-DE Zero 2.0", url: "https://www.govdata.de/dl-de/zero-2-0" }
  attribution: "© HVBG"
  coverage: { name: "Hessen", bbox: [7.77, 49.39, 10.24, 51.66] }
  cors: true
  epsg3857: true
  usage: "fair use"
  key_required: false
  status: verified
  checked: 2026-11-01
  used_for: [basemap-aerial]
"""

CANDIDATE_ENTRY = """
- id: nominatim
  title: { en: "Nominatim geocoder", de: "Nominatim-Geocoder" }
  provider: "OpenStreetMap Foundation"
  type: geocoder
  url: "https://nominatim.openstreetmap.org/search"
  license: { name: "ODbL 1.0", url: "https://opendatacommons.org/licenses/odbl/" }
  attribution: "© OpenStreetMap contributors"
  coverage: { name: "World", bbox: [-180, -90, 180, 90] }
  status: later
  used_for: [geocoding]
"""


def write_registry(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_registry_parses_entries(tmp_path):
    sources = load_registry(write_registry(tmp_path, VALID_ENTRY + CANDIDATE_ENTRY))

    assert [s.id for s in sources] == ["hessen-dop20", "nominatim"]
    assert sources[0].title.de == "Luftbild Hessen (DOP20)"
    assert sources[0].coverage.bbox == (7.77, 49.39, 10.24, 51.66)
    assert sources[1].layers == []


def test_entry_without_attribution_is_rejected_with_its_id(tmp_path):
    broken = VALID_ENTRY.replace('  attribution: "© HVBG"\n', "")

    with pytest.raises(RegistryError, match="hessen-dop20"):
        load_registry(write_registry(tmp_path, broken))


def test_duplicate_ids_are_rejected(tmp_path):
    with pytest.raises(RegistryError, match="duplicate"):
        load_registry(write_registry(tmp_path, VALID_ENTRY + VALID_ENTRY))


def test_sources_endpoint_lists_every_registry_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_REGISTRY", str(write_registry(tmp_path, VALID_ENTRY + CANDIDATE_ENTRY)))
    client = TestClient(create_app())

    response = client.get("/api/sources")

    assert response.status_code == 200
    assert [s["id"] for s in response.json()["sources"]] == ["hessen-dop20", "nominatim"]


def test_sources_endpoint_filters_by_status(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_REGISTRY", str(write_registry(tmp_path, VALID_ENTRY + CANDIDATE_ENTRY)))
    client = TestClient(create_app())

    response = client.get("/api/sources", params={"status": "verified"})

    assert [s["id"] for s in response.json()["sources"]] == ["hessen-dop20"]


def test_the_real_registry_validates():
    sources = {s.id: s for s in load_registry(DEFAULT_REGISTRY)}

    # Sources the frontend relies on are verified.
    for required in ("openfreemap-liberty", "photon-komoot", "hessen-dop20", "mapterhorn-terrain"):
        assert sources[required].status == "verified", required
    # Verified sources the browser loads directly answer with CORS; every entry has a check date and attribution.
    for source in sources.values():
        assert source.checked is not None, source.id
        assert source.attribution.strip(), source.id
        if source.status == "verified" and source.type not in ("geocoder", "api"):
            assert source.cors is True, source.id
        if source.type == "wms" and source.status == "verified":
            assert source.epsg3857 is True, source.id
    # No key, account or payment anywhere.
    assert not any(s.key_required for s in sources.values())
