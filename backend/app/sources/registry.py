"""Data-source registry: one YAML file lists every source with license, attribution,
coverage and verification status. Adding a state or dataset means adding an entry, not code."""

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.protocol.models import BBox

DEFAULT_REGISTRY = Path(__file__).with_name("registry.yaml")

SourceType = Literal["vector-style", "raster-xyz", "raster-dem", "pmtiles", "wms", "wmts", "3dtiles", "geocoder", "api"]
SourceStatus = Literal["verified", "needs-proxy", "rejected", "candidate", "later"]


class RegistryError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Title(_Model):
    en: str
    de: str

    def __getitem__(self, lang: str) -> str:
        return self.de if lang == "de" else self.en


class License(_Model):
    name: str
    url: str


class Coverage(_Model):
    name: str
    bbox: BBox


class Source(_Model):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: Title
    provider: str
    type: SourceType
    url: str
    homepage: str | None = None  # human-readable product page for source chips
    layers: list[str] = Field(default_factory=list)
    format: str | None = None
    minzoom: int | None = None
    maxzoom: int | None = None
    license: License
    attribution: str
    coverage: Coverage
    cors: bool | None = None
    epsg3857: bool | None = None
    usage: str = ""
    key_required: bool = False
    status: SourceStatus
    checked: date | None = None
    used_for: list[str] = Field(default_factory=list)
    notes: str = ""


def registry_path() -> Path:
    return Path(os.environ.get("SOURCE_REGISTRY", DEFAULT_REGISTRY))


@lru_cache(maxsize=8)
def _load(path: Path, mtime: float) -> tuple[Source, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise RegistryError(f"{path}: expected a list of sources")
    sources: list[Source] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        label = entry.get("id", f"#{index}") if isinstance(entry, dict) else f"#{index}"
        try:
            source = Source.model_validate(entry)
        except ValidationError as exc:
            raise RegistryError(f"invalid registry entry {label}: {exc}") from exc
        if source.id in seen:
            raise RegistryError(f"duplicate registry id {source.id}")
        seen.add(source.id)
        sources.append(source)
    return tuple(sources)


def load_registry(path: Path | None = None) -> list[Source]:
    """Load and validate the registry. Cached per file and modification time."""
    path = path or registry_path()
    return list(_load(path, path.stat().st_mtime))
