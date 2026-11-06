"""Skill canonicalisation backed by ``aliases.yaml``.

``normalize_skill("React.js")`` -> ``"react"``; unknown skills get a stable slug; vague or
role-like tags ("teamwork", "senior", "digital nomad") return ``None``.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = [
    "CATEGORIES",
    "SkillInfo",
    "is_known_skill",
    "normalize_skill",
    "normalize_skills",
    "skill_info",
]

CATEGORIES = frozenset(
    {
        "language",
        "framework",
        "cloud",
        "data",
        "devops",
        "database",
        "ai_ml",
        "tool",
        "design",
        "business",
        "other",
    }
)
MAX_CHARS = 40
MAX_WORDS = 4

_ALIASES_PATH = Path(__file__).with_name("aliases.yaml")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class SkillInfo:
    slug: str
    display: str
    category: str


@dataclass(frozen=True)
class _Registry:
    infos: dict[str, SkillInfo]
    by_key: dict[str, str]  # loose key -> canonical slug
    drop_keys: frozenset[str]


def _loose_key(text: str) -> str:
    """Matching key that ignores case, spaces, dots, hyphens and slashes.

    "React.js", "react js", "ReactJS" -> "reactjs"; "C#" -> "c#"; "C++" -> "c++";
    ".NET" -> "dotnet"; "CI/CD" -> "cicd"; "R&D" -> "randd".
    """
    t = unicodedata.normalize("NFKC", text).strip().lower()
    t = re.sub(r"^\.(?=[a-z])", "dot", t)
    t = t.replace("&", "and")
    return re.sub(r"[^a-z0-9+#]", "", t)


def _load_registry(path: Path = _ALIASES_PATH) -> _Registry:
    """Parse and validate the YAML. Raises ``ValueError`` on any inconsistency."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_skills = data.get("skills") or {}
    raw_drop = data.get("drop") or []

    infos: dict[str, SkillInfo] = {}
    by_key: dict[str, str] = {}
    owner_of: dict[str, str] = {}

    def register(key_source: object, slug: str, what: str) -> None:
        if not isinstance(key_source, str):
            raise ValueError(f"{what} for '{slug}' must be a string, got {key_source!r}")
        key = _loose_key(key_source)
        if not key:
            raise ValueError(f"{what} {key_source!r} for '{slug}' normalises to an empty key")
        if key in by_key and by_key[key] != slug:
            raise ValueError(
                f"alias {key_source!r} maps to two canonicals: "
                f"'{by_key[key]}' (via {owner_of[key]!r}) and '{slug}'"
            )
        by_key[key] = slug
        owner_of.setdefault(key, key_source)

    for raw_slug, spec in raw_skills.items():
        slug = str(raw_slug)
        if not _SLUG_RE.match(slug):
            raise ValueError(f"invalid canonical slug {slug!r}")
        if slug in infos:
            raise ValueError(f"duplicate canonical slug {slug!r}")
        spec = spec or {}
        display = spec.get("display")
        category = spec.get("category", "other")
        if not isinstance(display, str) or not display:
            raise ValueError(f"skill '{slug}' needs a display name")
        if category not in CATEGORIES:
            raise ValueError(f"skill '{slug}' has unknown category {category!r}")
        infos[slug] = SkillInfo(slug=slug, display=display, category=category)
        register(slug, slug, "slug")
        register(display, slug, "display")
        for alias in spec.get("aliases") or []:
            register(alias, slug, "alias")

    drop_keys: set[str] = set()
    for item in raw_drop:
        if not isinstance(item, str):
            raise ValueError(f"drop entry must be a string, got {item!r}")
        key = _loose_key(item)
        if key in by_key:
            raise ValueError(f"drop entry {item!r} is also a skill alias of '{by_key[key]}'")
        drop_keys.add(key)
    return _Registry(infos=infos, by_key=by_key, drop_keys=frozenset(drop_keys))


@lru_cache(maxsize=1)
def _registry() -> _Registry:
    return _load_registry()


# Characters trimmed from both ends of a raw tag. "+" and "#" are deliberately absent so
# "c++" and "c#" survive; a leading "." is kept for ".net".
_EDGE = " \t\r\n\"'`,;:!?()[]{}*•|\\/-–—_<>~"
_VERSION_SUFFIX_RE = re.compile(r"\s+v?\d+(?:\.\d+)*[a-z]?$")


def _clean(raw: str) -> str:
    """Unescape, NFKC, lowercase, collapse spaces and trim edge punctuation."""
    text = html.unescape(raw)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"\s+", " ", text).strip()
    text = text.lstrip("#@" + _EDGE)
    return text.rstrip(_EDGE + ".")


def _slugify(text: str) -> str | None:
    """Slug for a skill that is not in the vocabulary.

    ``++`` -> ``pp``, ``#`` -> ``sharp``, other ``+`` -> ``-plus``; everything else that is
    not a letter or digit becomes a hyphen. Returns ``None`` when no letters remain.
    """
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.encode("ascii", "ignore").decode("ascii").lower()
    t = t.replace("++", "pp").replace("#", "sharp").replace("+", "-plus")
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if not t or not re.search(r"[a-z]", t):
        return None
    return t


def normalize_skill(raw: str | None) -> str | None:
    """Return the canonical skill slug for a raw tag, or ``None`` if it is not a skill.

    Steps: unescape/lowercase/trim; reject empty, > 40 chars or > 4 words; look the loose key
    up in the alias table (``react.js`` == ``reactjs`` == ``React JS``); drop vague or
    role-like tags; retry without a trailing version number ("angular 17"); otherwise return a
    slug of the cleaned text (spaces -> hyphens, ``++`` -> ``pp``, ``#`` -> ``sharp``).
    """
    if not raw or not isinstance(raw, str):
        return None
    text = _clean(raw)
    if not text or len(text) > MAX_CHARS or len(text.split()) > MAX_WORDS:
        return None

    reg = _registry()
    key = _loose_key(text)
    if not key:
        return None
    if key in reg.by_key:
        return reg.by_key[key]
    if key in reg.drop_keys:
        return None

    stripped = _VERSION_SUFFIX_RE.sub("", text)
    if stripped != text:
        skey = _loose_key(stripped)
        if skey in reg.by_key:
            return reg.by_key[skey]
        if skey in reg.drop_keys:
            return None
    return _slugify(text)


def normalize_skills(raws: Iterable[str | None]) -> list[str]:
    """Normalise many raw tags; drops ``None`` results and duplicates, keeps first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in raws or []:
        slug = normalize_skill(raw) if isinstance(raw, str) else None
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def is_known_skill(slug: str) -> bool:
    """True when ``slug`` is a canonical skill of ``aliases.yaml``."""
    return slug in _registry().infos


def skill_info(slug: str) -> SkillInfo:
    """Display name and category for a slug. Unknown slugs get a title-cased name, ``other``.

    This plain title-casing is also what the embedding passages use, so it must stay stable
    (a change re-embeds every job); the published names come from
    :func:`radar.skills.pick_display`, which prefers the spelling seen in postings."""
    info = _registry().infos.get(slug)
    if info is not None:
        return info
    display = " ".join(part for part in slug.replace("_", "-").split("-") if part).title()
    return SkillInfo(slug=slug, display=display or slug, category="other")
