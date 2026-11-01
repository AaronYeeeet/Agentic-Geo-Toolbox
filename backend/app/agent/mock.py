"""Scripted mock agent.

Recognises a few intents by keyword (EN/DE), emits realistic tool steps with short delays, generates demo
features inside the selection (or the viewport), and replies in the language of the question. It makes no
external calls; the only real data it reads is the local source registry and the selection's geometry.
"""

import asyncio
import logging
import random
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.agent.demo_data import demo_points, demo_polygons, seed_for
from app.agent.gazetteer import find_place, known_place_names, place_query
from app.agent.geo import GEOD, ResolvedArea, feature_collection_bbox, resolve_area
from app.agent.intents import Intent, detect_intent, wants_aerial
from app.agent.language import detect_language
from app.agent.texts import SCHOOL_TYPES, Lang, fmt_area, fmt_length, fmt_percent, t
from app.protocol.models import (
    AddGeojsonLayer,
    AgentEvent,
    ChatRequest,
    Done,
    ErrorEvent,
    FitBounds,
    FlyTo,
    HighlightFeatures,
    RunStart,
    SetBasemap,
    SourceItem,
    Sources,
    TextDelta,
    ToolEnd,
    ToolStart,
)
from app.sources.registry import RegistryError, Source, load_registry

logger = logging.getLogger(__name__)

COLORS = {"charging": "#7c3aed", "schools": "#2563eb", "green": "#16a34a"}
OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright"
BNETZA_URL = "https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/start.html"

_delay_rng = random.Random()


@dataclass(frozen=True)
class _Run:
    run_id: str
    question: str
    lang: Lang
    other_language: bool
    intent: Intent
    area: ResolvedArea

    @property
    def seed(self) -> int:
        return seed_for(self.intent + self.lang, self.area.geometry)

    def layer_id(self, name: str) -> str:
        return f"result-{name}-{self.run_id[:8]}"


class _Step:
    """One tool step: emits tool_start, then tool_end with the measured duration."""

    def __init__(self, name: str, label: str) -> None:
        self.id = uuid4().hex[:12]
        self.name = name
        self.label = label
        self._started = time.perf_counter()

    def start(self) -> AgentEvent:
        self._started = time.perf_counter()
        return AgentEvent("tool_start", ToolStart(id=self.id, name=self.name, label=self.label))

    def end(self, summary: str, status: str = "ok") -> AgentEvent:
        duration_ms = int((time.perf_counter() - self._started) * 1000)
        return AgentEvent("tool_end", ToolEnd(id=self.id, status=status, summary=summary, duration_ms=duration_ms))


def _chunks(text: str, words_per_chunk: int = 3) -> list[str]:
    tokens = re.findall(r"\S+\s*|\s+", text)
    return ["".join(tokens[i : i + words_per_chunk]) for i in range(0, len(tokens), words_per_chunk)]


def _rounded(bbox: tuple[float, ...]) -> tuple[float, float, float, float]:
    west, south, east, north = (round(v, 6) for v in bbox)
    return west, south, east, north


def _bbox_intersects(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _registry() -> list[Source]:
    try:
        return load_registry()
    except (FileNotFoundError, RegistryError):
        logger.warning("source registry unavailable", exc_info=True)
        return []


class MockAgent:
    def __init__(self, fast: bool = False) -> None:
        self.fast = fast

    async def run(self, request: ChatRequest) -> AsyncIterator[AgentEvent]:
        question = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
        detected = detect_language(question)
        lang: Lang = detected if detected in ("en", "de") else request.context.ui_language
        run = _Run(
            run_id=uuid4().hex,
            question=question,
            lang=lang,
            other_language=detected == "other",
            intent=detect_intent(question),
            area=resolve_area(request.context),
        )
        yield AgentEvent("run_start", RunStart(run_id=run.run_id))
        handler = getattr(self, f"_{run.intent}")
        async for event in handler(run):
            yield event
        yield AgentEvent("done", Done())

    # --- helpers --------------------------------------------------------------------------------

    async def _pause(self, low: float = 0.25, high: float = 0.7) -> None:
        await asyncio.sleep(0 if self.fast else _delay_rng.uniform(low, high))

    async def _reply(self, run: _Run, text: str) -> AsyncIterator[AgentEvent]:
        if run.other_language:
            text = f"{t(run.lang, 'note.other_language')}\n\n{text}"
        for chunk in _chunks(text):
            yield AgentEvent("text_delta", TextDelta(text=chunk))
            await self._pause(0.02, 0.04)

    async def _area_step(self, run: _Run) -> AsyncIterator[AgentEvent]:
        step = _Step("resolve_area", t(run.lang, f"tool.area.{run.area.source}"))
        yield step.start()
        await self._pause(0.2, 0.4)
        kind = run.area.kind or run.area.source
        kind_label = t(run.lang, f"kind.{kind}") if f"kind.{kind}" in _KIND_KEYS else kind
        yield step.end(f"{fmt_area(run.area.area_m2, run.lang)} ({kind_label})")

    def _where(self, run: _Run, prefix: str = "where") -> str:
        return t(run.lang, f"{prefix}.{run.area.source}", area=fmt_area(run.area.area_m2, run.lang))

    @staticmethod
    def _sources(items: list[tuple[str, str, str]]) -> AgentEvent:
        return AgentEvent("sources", Sources(items=[SourceItem(title=a, url=b, license=c) for a, b, c in items]))

    # --- intents --------------------------------------------------------------------------------

    async def _charging(self, run: _Run) -> AsyncIterator[AgentEvent]:
        async for event in self._area_step(run):
            yield event

        step = _Step("osm_features", t(run.lang, "tool.osm_parking"))
        yield step.start()
        await self._pause()
        parking = demo_polygons(
            run.area.geometry,
            7,
            run.seed,
            id_prefix="parking",
            name=t(run.lang, "name.parking"),
            properties=lambda i, rng: {
                "capacity": rng.randint(20, 180),
                "nearest_charger_m": rng.randint(320, 1400),
                "score": rng.randint(55, 96),
            },
        )
        features = parking["features"]
        yield step.end(t(run.lang, "summary.osm_parking", n=len(features)))

        step = _Step("charging_points", t(run.lang, "tool.charging_points"))
        yield step.start()
        await self._pause()
        yield step.end(t(run.lang, "summary.charging_points", n=random.Random(run.seed).randint(1, 4)))

        step = _Step("rank_sites", t(run.lang, "tool.rank_sites"))
        yield step.start()
        await self._pause(0.2, 0.4)
        ranked = sorted(features, key=lambda f: -f["properties"]["score"])
        yield step.end(t(run.lang, "summary.rank_sites", n=len(ranked)))

        if not ranked:
            # A selection smaller than any parking lot: say so instead of emitting an empty layer.
            async for event in self._reply(run, t(run.lang, "reply.charging_none", where=self._where(run))):
                yield event
            yield self._sources([(t(run.lang, "source.osm"), OSM_COPYRIGHT, "ODbL 1.0")])
            return

        layer_id = run.layer_id("charging")
        yield AgentEvent(
            "map_action",
            AddGeojsonLayer(
                id=layer_id,
                title=t(run.lang, "layer.charging"),
                geojson=parking,
                color=COLORS["charging"],
                kind="demo",
            ),
        )
        yield AgentEvent("map_action", FitBounds(bbox=_rounded(feature_collection_bbox(parking))))
        top = ranked[:3]
        yield AgentEvent(
            "map_action",
            HighlightFeatures(layer_id=layer_id, feature_ids=[f["properties"]["id"] for f in top]),
        )

        items = "\n".join(
            t(
                run.lang,
                "item.parking",
                name=f["properties"]["name"],
                area=fmt_area(f["properties"]["area_m2"], run.lang),
                cars=f["properties"]["capacity"],
                score=f["properties"]["score"],
            )
            for f in top
        )
        async for event in self._reply(
            run, t(run.lang, "reply.charging", n=len(features), where=self._where(run), items=items)
        ):
            yield event
        yield self._sources(
            [
                (t(run.lang, "source.osm"), OSM_COPYRIGHT, "ODbL 1.0"),
                (t(run.lang, "source.bnetza"), BNETZA_URL, "CC BY 4.0"),
            ]
        )

    async def _schools(self, run: _Run) -> AsyncIterator[AgentEvent]:
        async for event in self._area_step(run):
            yield event

        step = _Step("osm_features", t(run.lang, "tool.osm_schools"))
        yield step.start()
        await self._pause()
        types = SCHOOL_TYPES[run.lang]
        schools = demo_points(
            run.area.geometry,
            6,
            run.seed,
            id_prefix="school",
            name=t(run.lang, "name.school"),
            properties=lambda i, rng: {
                "school_type": types[i % len(types)],
                "pupils": rng.randint(180, 1100),
            },
        )
        features = schools["features"]
        yield step.end(t(run.lang, "summary.osm_schools", n=len(features)))

        yield AgentEvent(
            "map_action",
            AddGeojsonLayer(
                id=run.layer_id("schools"),
                title=t(run.lang, "layer.schools"),
                geojson=schools,
                color=COLORS["schools"],
                kind="demo",
            ),
        )
        yield AgentEvent("map_action", FitBounds(bbox=_rounded(feature_collection_bbox(schools))))

        items = "\n".join(
            t(
                run.lang,
                "item.school",
                name=f["properties"]["name"],
                type=f["properties"]["school_type"],
                pupils=f["properties"]["pupils"],
            )
            for f in features
        )
        async for event in self._reply(
            run, t(run.lang, "reply.schools", n=len(features), where=self._where(run), items=items)
        ):
            yield event
        yield self._sources([(t(run.lang, "source.osm"), OSM_COPYRIGHT, "ODbL 1.0")])

    async def _area(self, run: _Run) -> AsyncIterator[AgentEvent]:
        async for event in self._area_step(run):
            yield event

        step = _Step("area_stats", t(run.lang, "tool.area_stats"))
        yield step.start()
        await self._pause(0.2, 0.4)
        _, perimeter = GEOD.geometry_area_perimeter(run.area.geometry)
        area_text = fmt_area(run.area.area_m2, run.lang)
        perimeter_text = fmt_length(abs(perimeter), run.lang)
        yield step.end(t(run.lang, "summary.area_stats", area=area_text, perimeter=perimeter_text))

        step = _Step("land_cover", t(run.lang, "tool.land_cover"))
        yield step.start()
        await self._pause()
        green = demo_polygons(run.area.geometry, 5, run.seed, id_prefix="green", name=t(run.lang, "name.green"))
        green_m2 = sum(f["properties"]["area_m2"] for f in green["features"])
        share = min(0.95, green_m2 / run.area.area_m2) if run.area.area_m2 else 0.0
        share_text = fmt_percent(share, run.lang)
        n = len(green["features"])
        yield step.end(t(run.lang, "summary.land_cover", share=share_text, n=n))

        yield AgentEvent(
            "map_action",
            AddGeojsonLayer(
                id=run.layer_id("green"),
                title=t(run.lang, "layer.green"),
                geojson=green,
                color=COLORS["green"],
                kind="demo",
            ),
        )
        yield AgentEvent("map_action", FitBounds(bbox=_rounded(run.area.geometry.bounds)))

        text = t(
            run.lang,
            "reply.area",
            area=area_text,
            perimeter=perimeter_text,
            share=share_text,
            n=n,
            source=t(run.lang, f"from.{run.area.source}"),
        )
        async for event in self._reply(run, text):
            yield event
        yield self._sources(
            [
                (
                    t(run.lang, "source.geodesic"),
                    "https://pyproj4.github.io/pyproj/stable/api/geod.html",
                    "MIT",
                ),
                (
                    t(run.lang, "source.land_cover"),
                    "https://land.copernicus.eu/en/products/corine-land-cover",
                    "Copernicus (free and open)",
                ),
            ]
        )

    async def _fly_to(self, run: _Run) -> AsyncIterator[AgentEvent]:
        place = find_place(run.question)
        query = place_query(run.question) or (place.name if place else "")
        aerial = wants_aerial(run.question)
        sources: list[tuple[str, str, str]] = []
        parts: list[str] = []

        if query or place:
            step = _Step("geocode", t(run.lang, "tool.geocode", place=query or place.name))
            yield step.start()
            await self._pause()
            if place:
                yield step.end(f"{place.name} ({place.lat:.4f}, {place.lon:.4f})")
                yield AgentEvent("map_action", FlyTo(center=(place.lon, place.lat), zoom=place.zoom))
                sources.append((t(run.lang, "source.gazetteer"), OSM_COPYRIGHT, "ODbL 1.0"))
                parts.append(t(run.lang, "reply.fly_to", name=place.name))
            else:
                yield step.end(t(run.lang, "summary.geocode_missing"))
                names = ", ".join(known_place_names()[:8])
                parts.append(t(run.lang, "reply.fly_to_unknown", place=query, names=names))

        if aerial and (place or not query):
            step = _Step("set_basemap", t(run.lang, "tool.aerial"))
            yield step.start()
            await self._pause(0.2, 0.4)
            covering = self._aerial_sources_at(place) if place else []
            yield step.end(covering[0].title[run.lang] if covering else t(run.lang, "summary.aerial_uncovered"))
            yield AgentEvent("map_action", SetBasemap(id="aerial"))
            if place and covering:
                source = covering[0]
                parts.append(t(run.lang, "reply.aerial_covered", source=source.title[run.lang]))
                sources.append((source.title[run.lang], source.homepage or source.license.url, source.license.name))
            elif place:
                parts.append(t(run.lang, "reply.aerial_uncovered"))
            else:
                parts.append(t(run.lang, "reply.aerial_only"))

        if not parts:
            parts.append(t(run.lang, "reply.fly_to_noplace"))
        async for event in self._reply(run, "".join(parts).strip()):
            yield event
        if sources:
            yield self._sources(sources)

    def _aerial_sources_at(self, place: Any) -> list[Source]:
        return [
            s
            for s in _registry()
            if "basemap-aerial" in s.used_for
            and s.status in ("verified", "needs-proxy")
            and s.coverage.bbox[0] <= place.lon <= s.coverage.bbox[2]
            and s.coverage.bbox[1] <= place.lat <= s.coverage.bbox[3]
            and s.coverage.name != "World"
        ]

    async def _data(self, run: _Run) -> AsyncIterator[AgentEvent]:
        async for event in self._area_step(run):
            yield event

        step = _Step("list_data_sources", t(run.lang, "tool.list_sources"))
        yield step.start()
        await self._pause()
        bounds = run.area.geometry.bounds
        matching = [
            s
            for s in _registry()
            if s.status in ("verified", "needs-proxy") and _bbox_intersects(s.coverage.bbox, bounds)
        ]
        yield step.end(t(run.lang, "summary.list_sources", n=len(matching)))

        where = self._where(run, "subject")
        if not matching:
            async for event in self._reply(run, t(run.lang, "reply.data_none", where=where)):
                yield event
            return
        groups: dict[str, list[str]] = {}
        for source in matching:
            groups.setdefault(_group_of(source), []).append(source.title[run.lang])
        items = "\n".join(
            t(run.lang, "item.group", group=t(run.lang, f"group.{group}"), titles=", ".join(titles))
            for group, titles in sorted(groups.items(), key=lambda g: _GROUP_ORDER.index(g[0]))
        )
        async for event in self._reply(run, t(run.lang, "reply.data", n=len(matching), where=where, items=items)):
            yield event
        yield self._sources([(s.title[run.lang], s.homepage or s.license.url, s.license.name) for s in matching])

    async def _error_demo(self, run: _Run) -> AsyncIterator[AgentEvent]:
        async for event in self._area_step(run):
            yield event
        step = _Step("osm_features", t(run.lang, "tool.overpass"))
        yield step.start()
        await self._pause(0.5, 0.9)
        yield step.end(t(run.lang, "summary.overpass_busy"), status="error")
        yield AgentEvent("error", ErrorEvent(message=t(run.lang, "error.overpass_busy"), retryable=True))

    async def _help(self, run: _Run) -> AsyncIterator[AgentEvent]:
        async for event in self._reply(run, t(run.lang, "reply.help")):
            yield event


_KIND_KEYS = {f"kind.{k}" for k in ("polygon", "rectangle", "feature", "view", "search")}
_GROUP_ORDER = ["basemap", "aerial", "terrain", "buildings", "search", "other"]


def _group_of(source: Source) -> str:
    roles = " ".join(source.used_for)
    if "aerial" in roles:
        return "aerial"
    if "basemap" in roles:
        return "basemap"
    if "terrain" in roles or "hillshade" in roles:
        return "terrain"
    if "building" in roles:
        return "buildings"
    if "search" in roles or "geocod" in roles:
        return "search"
    return "other"
