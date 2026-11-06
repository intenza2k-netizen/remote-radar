"""Canonical remote-region names backed by ``regions.yaml``.

The extraction model writes ``remote_regions`` as free strings, so one posting market shows up
as "US", "USA", "United States" or a list of state codes, "Czech Republic" and "Czechia", and
"AMER" next to "Americas". :func:`normalize_regions` maps a posting's list to canonical names
so the published region filter has one entry per place. The mapping is deliberately flat: no
region implies another ("US" is not "Americas", "Germany" is not "EU").

* aliases (``regions:`` in the YAML) are matched ignoring case, accents, dots, hyphens, ``&``
  versus ``and`` and a leading "The";
* US states collapse into "United States". Full state names always do; two-letter codes (many
  of which are also ISO country codes: IN, IL, CA, DE ...) only when the posting lists at
  least two distinct states, as in ``["AL", "AZ", "IL", "IN", ...]``. A lone "CA" or "IN" is
  read as Canada or India; "Georgia" stays the country unless the posting lists other states;
* anything else is kept as written (all-lowercase values are title-cased), so country names
  that have one spelling need no entry.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = ["REGIONS_PATH", "US", "WORLDWIDE", "normalize_region", "normalize_regions"]

REGIONS_PATH = Path(__file__).with_name("regions.yaml")
US = "United States"
WORLDWIDE = "worldwide"  # lower-case on purpose: the extraction schema and the matcher use it
_SMALL_WORDS = frozenset({"and", "of", "the", "de", "da", "del", "la", "on", "in"})


@dataclass(frozen=True)
class _Registry:
    by_key: dict[str, str]  # loose key -> canonical name
    state_names: frozenset[str]  # keys of unambiguous full state names
    ambiguous_names: frozenset[str]  # keys of names that are also another place
    state_codes: frozenset[str]  # upper-case two-letter codes


def region_key(text: str) -> str:
    """Matching key: accents, case, dots, hyphens/underscores, "&" and a leading "the" ignored."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).casefold()
    t = t.replace("&", " and ").replace(".", "")
    t = re.sub(r"[\s_\-–—]+", " ", t).strip()
    return re.sub(r"^the ", "", t)


def _load(path: Path = REGIONS_PATH) -> _Registry:
    """Parse and validate the YAML. Raises ``ValueError`` on any inconsistency."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by_key: dict[str, str] = {}

    def register(alias: object, canonical: str) -> None:
        if not isinstance(alias, str) or not region_key(alias):
            raise ValueError(f"region alias {alias!r} for {canonical!r} must be a non-empty string")
        key = region_key(alias)
        if by_key.get(key, canonical) != canonical:
            raise ValueError(f"alias {alias!r} maps to {by_key[key]!r} and {canonical!r}")
        by_key[key] = canonical

    for canonical, aliases in (data.get("regions") or {}).items():
        canonical = str(canonical)
        register(canonical, canonical)
        for alias in aliases or []:
            register(alias, canonical)

    states = data.get("us_states") or {}
    names = frozenset(region_key(str(n)) for n in states.get("names") or [])
    ambiguous = frozenset(region_key(str(n)) for n in states.get("ambiguous_names") or [])
    codes = frozenset(str(c) for c in states.get("codes") or [])
    for code in codes:
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise ValueError(f"US state code {code!r} must be two upper-case letters")
    for key in names | ambiguous:
        if key in by_key and by_key[key] != US:
            raise ValueError(f"state name {key!r} is also a region alias of {by_key[key]!r}")
    return _Registry(by_key, names, ambiguous, codes)


@lru_cache(maxsize=1)
def _registry() -> _Registry:
    return _load()


def _tidy(text: str) -> str:
    """Whitespace-collapsed, "The " stripped, all-lowercase values title-cased."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^the\s+(?=\S)", "", cleaned, flags=re.IGNORECASE)
    if cleaned == cleaned.lower() and any(ch.isalpha() for ch in cleaned):
        words = cleaned.split(" ")
        cleaned = " ".join(
            w if (i and w in _SMALL_WORDS) else w[:1].upper() + w[1:] for i, w in enumerate(words)
        )
    return cleaned


def normalize_region(raw: str) -> str | None:
    """Canonical name for one value read on its own (no list context), or ``None`` if empty.

    Two-letter state codes are not recognised here: they need the rest of the posting's list
    (see :func:`normalize_regions`)."""
    if not isinstance(raw, str):
        return None
    text = re.sub(r"\s+", " ", raw).strip()
    key = region_key(text)
    if not key:
        return None
    reg = _registry()
    if key in reg.by_key:
        return reg.by_key[key]
    if key in reg.state_names:
        return US
    return _tidy(text)


def normalize_regions(raws: Iterable[str] | None) -> list[str]:
    """Canonical, de-duplicated regions for one posting, first-seen order preserved."""
    values = [r.strip() for r in raws or [] if isinstance(r, str) and r.strip()]
    reg = _registry()
    # Is this posting a list of US states? Counts distinct state codes and unambiguous names.
    states_listed = {v for v in values if v in reg.state_codes} | {
        region_key(v) for v in values if region_key(v) in reg.state_names
    }
    state_list = len(states_listed) >= 2

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if state_list and (value in reg.state_codes or region_key(value) in reg.ambiguous_names):
            name: str | None = US
        else:
            name = normalize_region(value)
        if name is None or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        out.append(name)
    return out
