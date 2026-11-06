"""Where remote jobs can be done from (``geo.json``, PLAN.md section 6).

"Remote" often means "remote within one country or region". For a job seeker outside the US the
useful question is therefore not how many remote postings exist but how many are **open to
them**. This module answers it for every location the postings or the membership lists mention.

The rule (one implementation here, one in ``web/src/lib/geo.ts``, tied together by
``web/src/lib/geo.fixtures.json``): a posting is *open to* location L when its canonical
``remote_regions`` contain

* ``worldwide``; or
* L itself; or
* a macro region that contains L, where the macro lists come from the ``memberships:`` block of
  ``regions.yaml`` (EU, EEA, Europe, EMEA contain Estonia). When L is itself a macro region the
  posting must cover *all* of it: ``Europe`` is open to Europe, to EMEA and to worldwide, but not
  to a posting that lists only Germany and France.

``worldwide`` is not counted for the comprehensively sanctioned places listed under
``memberships.sanctioned`` (Cuba, Iran, North Korea, Syria ...): only a posting that names them
opens to them.

Postings without any region are *unknown* and never count as open: the extraction found no
statement either way. Only the listed (active) postings are scored, because that is what the site
shows; ``region_mix`` describes the whole 8-week window.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from radar.regions import REGION_GROUPS, REGIONS_PATH, US, WORLDWIDE, normalize_region, region_group
from radar.skills import skill_info

if TYPE_CHECKING:
    from radar.aggregate import JobRecord

__all__ = [
    "Memberships",
    "compute_geo",
    "is_open_to",
    "load_memberships",
    "memberships",
    "open_via",
]

MIN_SALARY_N = 5  # same floor as every published salary statistic (aggregate.MIN_SALARY_N)
MIN_SKILL_JOBS = 3  # a skill must appear in this many open data jobs to be listed
TOP_SKILLS = 8
DATA_ROLE = "data"


# --------------------------------------------------------------------------- memberships


@dataclass(frozen=True)
class Memberships:
    """Validated ``memberships:`` block: known countries and flat macro -> countries lists."""

    countries: frozenset[str]
    macros: dict[str, frozenset[str]]
    # Comprehensively sanctioned places: "worldwide" does not open a posting to them.
    sanctioned: frozenset[str] = frozenset()

    def as_lists(self) -> dict[str, list[str]]:
        """The published form: macro -> sorted countries."""
        return {name: sorted(members) for name, members in sorted(self.macros.items())}


def _canonical(name: object, where: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{where}: {name!r} must be a non-empty string")
    if normalize_region(name) != name:
        raise ValueError(
            f"{where}: {name!r} is not a canonical region name ({normalize_region(name)!r})"
        )
    if name == WORLDWIDE:
        raise ValueError(f"{where}: {WORLDWIDE!r} cannot be a country or a macro region")
    return name


def load_memberships(path: Path = REGIONS_PATH) -> Memberships:
    """Parse and validate ``memberships:``. Raises ``ValueError`` on any inconsistency:
    non-canonical or duplicate names, a macro member that is neither a known country nor a macro,
    a macro that is empty, lists itself or is part of a cycle, or a macro named like a country."""
    block = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("memberships")
    if not isinstance(block, dict):
        raise ValueError("regions.yaml has no memberships: block")

    countries: set[str] = set()
    for raw in block.get("countries") or []:
        name = _canonical(raw, "memberships.countries")
        if name in countries:
            raise ValueError(f"memberships.countries: {name!r} is listed twice")
        countries.add(name)
    if not countries:
        raise ValueError("memberships.countries is empty")

    raw_macros = block.get("macros")
    if not isinstance(raw_macros, dict) or not raw_macros:
        raise ValueError("memberships.macros is empty")
    declared: dict[str, list[str]] = {}
    for macro, members in raw_macros.items():
        macro = _canonical(macro, "memberships.macros")
        if macro in countries:
            raise ValueError(f"memberships.macros: {macro!r} is also a country")
        if not isinstance(members, list) or not members:
            raise ValueError(f"memberships.macros.{macro}: needs a non-empty list")
        names = [_canonical(m, f"memberships.macros.{macro}") for m in members]
        if len(set(names)) != len(names):
            dupes = sorted(n for n, c in Counter(names).items() if c > 1)
            raise ValueError(f"memberships.macros.{macro}: duplicate members {dupes}")
        declared[macro] = names

    flat: dict[str, frozenset[str]] = {}

    def expand(macro: str, trail: tuple[str, ...]) -> frozenset[str]:
        if macro in flat:
            return flat[macro]
        if macro in trail:
            raise ValueError(f"memberships.macros: cycle {' -> '.join((*trail, macro))}")
        out: set[str] = set()
        for member in declared[macro]:
            if member in countries:
                out.add(member)
            elif member in declared:
                out |= expand(member, (*trail, macro))
            else:
                raise ValueError(
                    f"memberships.macros.{macro}: {member!r} is neither a known country nor a macro"
                )
        flat[macro] = frozenset(out)
        return flat[macro]

    for macro in declared:
        expand(macro, ())
    sanctioned = [_canonical(c, "memberships.sanctioned") for c in block.get("sanctioned") or []]
    if len(set(sanctioned)) != len(sanctioned):
        raise ValueError("memberships.sanctioned: duplicate entries")
    unknown = sorted(c for c in sanctioned if c not in countries)
    if unknown:
        raise ValueError(f"memberships.sanctioned: {unknown} are not known countries")
    return Memberships(frozenset(countries), flat, frozenset(sanctioned))


@lru_cache(maxsize=1)
def memberships() -> Memberships:
    return load_memberships()


# --------------------------------------------------------------------------- the rule


def open_via(
    regions: Iterable[str] | None,
    location: str,
    macros: Mapping[str, Collection[str]],
    sanctioned: Collection[str] = (),
) -> str | None:
    """How a posting with canonical ``regions`` is open to ``location``: ``"worldwide"`` when it
    lists worldwide, ``"explicit"`` when it names the location or a macro covering it, ``None``
    when it is not open (including a posting without regions). ``worldwide`` does not open a
    posting to a ``sanctioned`` location; only naming it (or a macro containing it) does."""
    values = list(regions or [])
    if location not in sanctioned and any(r.casefold() == WORLDWIDE for r in values):
        return "worldwide"
    target = macros.get(location)  # None when the location is a country
    for region in values:
        if region == location:
            return "explicit"
        covering = macros.get(region)
        if covering is None:
            continue
        if target is None:
            if location in covering:
                return "explicit"
        elif set(target) <= set(covering):
            return "explicit"
    return None


def is_open_to(
    regions: Iterable[str] | None,
    location: str,
    macros: Mapping[str, Collection[str]],
    sanctioned: Collection[str] = (),
) -> bool:
    """The "open to" rule; see the module docstring."""
    return open_via(regions, location, macros, sanctioned) is not None


# --------------------------------------------------------------------------- document


def _median(values: list[float]) -> int | None:
    return round(statistics.median(values)) if len(values) >= MIN_SALARY_N else None


def _location_row(
    location: str,
    kind: str,
    open_jobs: Sequence[tuple[JobRecord, str]],
    n_listed: int,
    names: Mapping[str, str],
) -> dict[str, Any]:
    recs = [rec for rec, _ in open_jobs]
    data_recs = [rec for rec in recs if rec.role == DATA_ROLE]
    pay = [rec.salary.annual_usd_mid for rec in recs if rec.salary is not None]
    skill_counts = Counter(slug for rec in data_recs for slug in rec.skills)
    top = sorted(
        ((slug, c) for slug, c in skill_counts.items() if c >= MIN_SKILL_JOBS),
        key=lambda kv: (-kv[1], kv[0]),
    )[:TOP_SKILLS]
    worldwide = sum(1 for _, via in open_jobs if via == "worldwide")
    return {
        "location": location,
        "kind": kind,
        "open_jobs": len(recs),
        "open_share": round(len(recs) / n_listed, 4) if n_listed else 0.0,
        "data_jobs": len(data_recs),
        "worldwide_jobs": worldwide,
        "explicit_jobs": len(recs) - worldwide,
        "median_salary_usd": _median(pay),
        "salary_n": len(pay),
        "top_skills": [
            {
                "slug": slug,
                "name": names.get(slug) or skill_info(slug).display,
                "share": round(c / len(data_recs), 4),
            }
            for slug, c in top
        ],
        "by_role": dict(
            sorted(Counter(rec.role for rec in recs).items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    }


def _region_mix(population: Sequence[JobRecord]) -> list[dict[str, Any]]:
    by_group: dict[str, list[JobRecord]] = {}
    for rec in population:
        by_group.setdefault(region_group(rec.remote_regions), []).append(rec)
    order = {g: i for i, g in enumerate(REGION_GROUPS)}
    rows = [
        {
            "group": group,
            "n": len(recs),
            "share": round(len(recs) / len(population), 4),
            "median_salary_usd": _median(
                [r.salary.annual_usd_mid for r in recs if r.salary is not None]
            ),
        }
        for group, recs in by_group.items()
    ]
    rows.sort(key=lambda r: (-r["n"], order.get(r["group"], len(order))))
    return rows


def _summary(listed: Sequence[JobRecord]) -> dict[str, int]:
    """Whole-snapshot counts behind the page's lead sentence (listed postings only)."""

    def both(pred) -> tuple[int, int]:
        hit = [r for r in listed if pred(r)]
        return len(hit), sum(1 for r in hit if r.role == DATA_ROLE)

    worldwide = both(lambda r: any(x.casefold() == WORLDWIDE for x in r.remote_regions))
    us_only = both(lambda r: bool(r.remote_regions) and set(r.remote_regions) == {US})
    unknown = both(lambda r: not r.remote_regions)
    return {
        "listed_jobs": len(listed),
        "data_jobs": sum(1 for r in listed if r.role == DATA_ROLE),
        "worldwide_jobs": worldwide[0],
        "worldwide_data_jobs": worldwide[1],
        "us_only_jobs": us_only[0],
        "us_only_data_jobs": us_only[1],
        "unknown_jobs": unknown[0],
        "unknown_data_jobs": unknown[1],
    }


def compute_geo(
    population: Sequence[JobRecord],
    listed: Sequence[JobRecord],
    *,
    names: Mapping[str, str] | None = None,
    members: Memberships | None = None,
) -> dict[str, Any]:
    """Return the ``geo.json`` document (PLAN.md section 6).

    ``listed`` (active postings, what the site lists) is scored by the open-to rule;
    ``population`` (the 8-week window) feeds ``region_mix``. ``unmapped`` lists region strings
    in the listed postings that are neither a country nor a macro region of ``regions.yaml``
    (``TMEA``, a typo): they open nothing but are shown so they can be fixed."""
    names = names or {}
    members = members or memberships()
    macros = members.macros

    listed_seen: Counter[str] = Counter()
    for rec in listed:
        listed_seen.update(set(rec.remote_regions))
    # Rows: the macro regions, every country some listed posting names directly, and every
    # European country (EU, EEA and the rest of Europe are the site's home audience). Other
    # countries would only show the worldwide postings, so they are not listed; the rule still
    # answers for any country (``is_open_to``).
    europe = macros.get("Europe", frozenset())
    countries = sorted(c for c in members.countries if c in listed_seen or c in europe)

    n_listed = len(listed)
    rows: list[dict[str, Any]] = []
    for location, kind in [(c, "country") for c in countries] + [
        (m, "macro") for m in sorted(macros)
    ]:
        scored: list[tuple[JobRecord, str]] = []
        for rec in listed:
            via = open_via(rec.remote_regions, location, macros, members.sanctioned)
            if via is not None:
                scored.append((rec, via))
        rows.append(_location_row(location, kind, scored, n_listed, names))
    rows.sort(key=lambda r: (-r["data_jobs"], -r["open_jobs"], r["location"]))

    unmapped = [
        {"region": region, "n": n}
        for region, n in sorted(listed_seen.items(), key=lambda kv: (-kv[1], kv[0]))
        if region.casefold() != WORLDWIDE
        and region not in members.countries
        and region not in macros
    ]

    return {
        "version": 1,
        "memberships": members.as_lists(),
        "macros": sorted(macros),
        "sanctioned": sorted(members.sanctioned),
        "by_location": rows,
        "region_mix": _region_mix(population) if population else [],
        "unknown_jobs": sum(1 for rec in listed if not rec.remote_regions),
        "summary": _summary(listed),
        "unmapped": unmapped,
    }
