"""Keyword intents of the mock agent, English and German."""

import re
from typing import Literal

Intent = Literal["charging", "schools", "area", "fly_to", "data", "error_demo", "help"]

# Checked in order: the first match wins ("Show me all schools" is about schools, not a fly-to).
_INTENT_PATTERNS: list[tuple[Intent, re.Pattern[str]]] = [
    (
        "error_demo",
        re.compile(r"\bsimulate (an )?error\b|\bfehler simulieren\b|\bsimuliere (einen )?fehler\b"),
    ),
    (
        "charging",
        re.compile(
            r"\bcharg(er|ers|ing)\b|\bev\b|\bladesäule\w*|\bladestation\w*|\bladepunkt\w*|\blad(en|e)\b"
            r"|\bparking\b|\bparkpl(a|ä)tz\w*|\be-?auto\w*|\belektroauto\w*"
        ),
    ),
    ("schools", re.compile(r"\bschools?\b|\bschul(e|en)\b|\bgrundschul\w*|\bgymnasi\w*")),
    (
        "area",
        re.compile(
            r"\bhow (large|big)\b|\barea size\b|\bsize of\b|\bwie gro(ß|ss)\b|\bfläche\w*"
            r"|\bgreen ?spaces?\b|\bgrünfläche\w*"
        ),
    ),
    ("data", re.compile(r"\bdata\b|\bdatasets?\b|\bdaten\w*|\bsources?\b|\bquellen\b")),
    (
        "fly_to",
        re.compile(
            r"\bshow me\b|\bfly (to|over)\b|\bgo to\b|\btake me to\b|\bzoom to\b|\bzeig(e)? mir\b"
            r"|\bflieg(e)? (zu|zum|zur|nach|über)\b|\bgeh(e)? (zu|zum|nach)\b"
        ),
    ),
]

_AERIAL = re.compile(r"\baerial\b|\bsatellite\b|\bimagery\b|\bluftbild\w*|\borthophoto\w*|\bsatellit\w*|\bdop\b")


def detect_intent(text: str) -> Intent:
    lowered = text.lower()
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(lowered):
            return intent
    return "help"


def wants_aerial(text: str) -> bool:
    return _AERIAL.search(text.lower()) is not None
