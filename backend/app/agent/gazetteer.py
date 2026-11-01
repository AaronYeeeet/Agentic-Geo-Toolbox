"""A small local gazetteer so the mock agent can fly to places without any external call.

Coordinates come from OpenStreetMap (via Photon lookups). A geocoding tool (Nominatim) can replace it later.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    name: str
    lon: float
    lat: float
    zoom: float
    aliases: tuple[str, ...]


PLACES: tuple[Place, ...] = (
    Place("Fraunhofer IGD, Darmstadt", 8.65989, 49.87425, 17, ("fraunhofer igd", "igd")),
    Place("TU Darmstadt", 8.6566, 49.8749, 16, ("tu darmstadt", "technische universität darmstadt")),
    Place("Darmstadt", 8.6512, 49.8728, 13, ("darmstadt",)),
    Place("Kölner Dom", 6.9583, 50.9413, 16.5, ("kölner dom", "koelner dom", "cologne cathedral")),
    Place("Köln", 6.9603, 50.9375, 12, ("köln", "koeln", "cologne")),
    Place("Berlin", 13.4050, 52.5200, 11, ("berlin",)),
    Place("München", 11.5755, 48.1374, 12, ("münchen", "muenchen", "munich")),
    Place("Frankfurt am Main", 8.6820, 50.1106, 12, ("frankfurt",)),
    Place("Hamburg", 9.9920, 53.5503, 11, ("hamburg",)),
    Place("Wiesbaden", 8.2398, 50.0782, 12, ("wiesbaden",)),
    Place("Mainz", 8.2473, 49.9929, 12, ("mainz",)),
    Place("Kassel", 9.4797, 51.3127, 12, ("kassel",)),
    Place("Düsseldorf", 6.7735, 51.2277, 12, ("düsseldorf", "duesseldorf", "dusseldorf")),
    Place("Stuttgart", 9.1829, 48.7758, 12, ("stuttgart",)),
    Place("Nürnberg", 11.0767, 49.4521, 12, ("nürnberg", "nuernberg", "nuremberg")),
)

_ALIASES = sorted(((alias, place) for place in PLACES for alias in place.aliases), key=lambda x: -len(x[0]))

_COMMAND = re.compile(
    r"\b(?:show me|fly (?:to|over)|go to|take me to|zoom to|zeig(?:e)? mir|flieg(?:e)? (?:zu(?:m|r)?|nach|über)"
    r"|geh(?:e)? (?:zu(?:m|r)?|nach))\s+(?:the\s+|das\s+|den\s+|die\s+|dem\s+)?(?P<place>[^,.!?;]+)",
    re.IGNORECASE,
)
_TAIL = re.compile(r"\s+(?:and|und|then|dann|with|mit)\b.*$", re.IGNORECASE)


def find_place(text: str) -> Place | None:
    """Longest alias wins, so "Fraunhofer IGD in Darmstadt" resolves to the IGD, not the city."""
    lowered = text.lower()
    for alias, place in _ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return place
    return None


def place_query(text: str) -> str:
    """The place phrase after a fly-to command, for messages ("Fly to Atlantis and ..." -> "Atlantis")."""
    match = _COMMAND.search(text)
    if not match:
        return ""
    return _TAIL.sub("", match.group("place")).strip()


def known_place_names() -> list[str]:
    return [place.name for place in PLACES]
