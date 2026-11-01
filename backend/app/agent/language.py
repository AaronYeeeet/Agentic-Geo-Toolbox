"""Tiny language detector for the agent: English, German, or "other".

Scores stop words and domain words per language plus character hints (umlauts, Romance accents). No external
library, deterministic, good enough for routing a reply language. Returns None when the text carries no
language evidence at all (a bare place name), so the caller falls back to the UI language without a warning.
"""

import re
from typing import Literal

DetectedLanguage = Literal["en", "de", "other"]

_WORD = re.compile(r"[^\W\d_]+")

# Words that exist in both English and German ("in", "an", "was", ...) are left out on purpose.
_EN = frozenset(
    """
    about aerial all and any are area areas available be big build can cathedral charger chargers charging
    could data do does ev far find fly for from go green have has hello here hey hi how image is it large
    me much my near new no of on or over parking please satellite school schools selected show space thank
    thanks the there these this to view what where which with within would you zoom
    """.split()
)
_DE = frozenset(
    """
    alle allen aller auf bereich bitte daten danke das davon dem den der des diese diesem dieser dieses du
    ein eine einem einen einer es flieg fliege für gebiet gibt groß gross grünfläche haben hallo hat hier
    hin ich im ist kann kein keine können könnten laden ladesäule ladesäulen luftbild markierten mein meine
    mich mir mit moin nach neue neuen parkplatz parkplätze schule schulen servus sind strasse straße über
    umkreis und viel viele von welche welcher welches wie wo zeig zeige zu zum zur
    """.split()
)
# Frequent words of other European languages (French, Spanish, Italian, Dutch, Portuguese).
_OTHER = frozenset(
    """
    avec bonjour bornes cette ciao con dans de della deze des di dit donde dónde dove een estão est esta et
    gebied gli grazias gracias hay het hola hoe il laadpalen le les où onde olá per pour quel quelle qué
    recharge scholen scuole sono sont sur une questa waar wat welke zijn zona zone écoles escolas escuelas
    """.split()
)
_UMLAUT = re.compile(r"[äöüß]")
_ROMANCE = re.compile(r"[éèêàâçñáíóúòìùãõ¿¡]")


def detect_language(text: str) -> DetectedLanguage | None:
    lowered = text.lower()
    words = [w for w in _WORD.findall(lowered) if len(w) > 1]
    en = sum(w in _EN for w in words)
    de = sum(w in _DE for w in words) + (1 if _UMLAUT.search(lowered) else 0)
    other = sum(w in _OTHER for w in words) + (2 if _ROMANCE.search(lowered) else 0)

    best = max(en, de)
    if other > best:
        return "other"
    if best == 0 or en == de:
        return None
    return "en" if en > de else "de"
