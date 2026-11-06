"""Shared machinery for the applicant-tracking-system (ATS) job-board sources.

Greenhouse, Ashby and Lever all publish every opening of a company through a public,
unauthenticated JSON endpoint meant for embedding career pages. The sources built on this
module walk a curated list of company boards (``ats_companies.yaml``), one GET per board,
sequentially, and keep only the remote jobs.

Two conventions differ from the single-feed sources:

* The company name comes from the YAML list (Lever does not carry one at all), so ``fetch``
  adds one extra key, ``_radar = {"board", "company"}``, to each payload. Everything else in the
  payload is exactly what the API returned.
* ``external_id`` is namespaced ``"{board token}/{job id}"`` because job ids are only unique
  within a board (Lever and Ashby use bare UUIDs, Greenhouse integers).
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml

from radar.sources.base import SourceJob, as_str, dedupe_jobs, get_json

log = logging.getLogger(__name__)

YAML_PATH = Path(__file__).with_name("ats_companies.yaml")
ATS_NAMES = ("greenhouse", "ashby", "lever")

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# ------------------------------------------------------------------------- board list


@dataclass(frozen=True)
class Board:
    ats: str
    token: str
    company: str
    careers_url: str


def parse_boards(data: Any) -> list[Board]:
    """Validate the decoded YAML and return the boards. Raises ``ValueError`` on any problem."""
    if not isinstance(data, list):
        raise ValueError("ats_companies.yaml: expected a list of board entries")
    boards: list[Board] = []
    seen: set[tuple[str, str]] = set()
    for i, entry in enumerate(data):
        where = f"ats_companies.yaml entry {i}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where}: expected a mapping")
        missing = {"ats", "token", "company", "careers_url"} - set(entry)
        if missing:
            raise ValueError(f"{where}: missing {sorted(missing)}")
        extra = set(entry) - {"ats", "token", "company", "careers_url"}
        if extra:
            raise ValueError(f"{where}: unknown keys {sorted(extra)}")
        values = {k: entry[k] for k in ("ats", "token", "company", "careers_url")}
        if not all(isinstance(v, str) and v.strip() for v in values.values()):
            raise ValueError(f"{where}: every value must be a non-empty string")
        ats, token, company, url = (values[k].strip() for k in values)
        if ats not in ATS_NAMES:
            raise ValueError(f"{where}: ats must be one of {ATS_NAMES}, got {ats!r}")
        if not _TOKEN_RE.match(token):
            raise ValueError(f"{where}: invalid token {token!r}")
        if not url.startswith("https://"):
            raise ValueError(f"{where}: careers_url must be https, got {url!r}")
        if (ats, token) in seen:
            raise ValueError(f"{where}: duplicate board {ats}/{token}")
        seen.add((ats, token))
        boards.append(Board(ats, token, company, url))
    return boards


def load_boards(path: Path = YAML_PATH) -> list[Board]:
    return parse_boards(yaml.safe_load(path.read_text(encoding="utf-8")))


# Loaded and validated once, when the first ATS module is imported.
ALL_BOARDS: list[Board] = load_boards()


def boards_for(ats: str) -> list[Board]:
    return [b for b in ALL_BOARDS if b.ats == ats]


# ------------------------------------------------------------------------- text helpers

REMOTE_RE = re.compile(r"\b(?:remote|anywhere)\b", re.IGNORECASE)
_NOT_REMOTE_RE = re.compile(r"\b(?:not|non|no)[\s-]+remote\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def mentions_remote(text: Any) -> bool:
    """True if ``text`` says remote/anywhere (and does not say "not remote")."""
    if not isinstance(text, str) or _NOT_REMOTE_RE.search(text):
        return False
    return bool(REMOTE_RE.search(text))


def plain_text(markup: str) -> str:
    """Cheap HTML-to-text for salary sniffing only (the real conversion happens later)."""
    text = html.unescape(markup)  # entity-escaped HTML -> HTML
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)  # entities that were escaped twice (&amp;mdash;)
    return _WS.sub(" ", text).strip()


_CUR = (
    r"(?:(?:USD|CAD|EUR|GBP|AUD|CHF|SEK|PLN|NZD)\s*)?"
    r"(?:US|CA|AU|NZ|C|A)?[$£€]\s?"
)
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_RANGE_RE = re.compile(
    rf"(?P<match>{_CUR}{_NUM}\s?[kK]?"
    r"\s*(?:-|–|—|to)\s*"
    rf"(?:{_CUR})?{_NUM}\s?[kK]?"
    r"(?:\s?(?:USD|CAD|EUR|GBP|AUD|CHF|SEK|PLN|NZD)\b)?"
    r"(?:\s*(?:/|per\s+|a\s+)\s*(?:yr|year|hour|hr|month|mo|annum)\b|\s+annually\b)?)"
    r"(?P<after>.{0,12})",
    re.DOTALL,
)
_PAY_CONTEXT_RE = re.compile(
    r"salary|compensation|\bpay\b|base|range|annual|hourly|\bOTE\b|\brate\b|per year|per hour"
    "|\U0001f4b0",  # the money-bag emoji some companies put in front of the range
    re.IGNORECASE,
)
_MAGNITUDE_RE = re.compile(r"^\s*(?:million|billion|[mb]\b)", re.IGNORECASE)


def extract_salary_snippet(text: str | None, *, require_context: bool = True) -> str | None:
    """Return a short salary range found in free text, e.g. ``"$164,200 — $229,990 USD"``.

    Only clear "amount - amount" ranges count. With ``require_context`` a pay-related word
    (salary, compensation, base, range, ...) must appear shortly before the range, which keeps
    funding rounds and revenue figures out.
    """
    if not text:
        return None
    for m in _RANGE_RE.finditer(text):
        if _MAGNITUDE_RE.match(m.group("after")):
            continue
        if require_context:
            window = text[max(0, m.start() - 250) : m.start()]
            if not _PAY_CONTEXT_RE.search(window):
                continue
        return _WS.sub(" ", m.group("match")).strip()[:120]
    return None


# ------------------------------------------------------------------------- base source


@dataclass
class BoardResult:
    token: str
    ok: bool
    open_jobs: int = 0
    remote_jobs: int = 0
    error: str | None = None


class BoardSource:
    """Base class: subclasses set the class attributes and implement the hooks."""

    ats: str = ""
    name: str = ""
    display_name: str = ""
    homepage: str = ""
    scope: Literal["broad", "targeted"] = "broad"
    api_url: str = ""  # contains "{token}"
    api_params: dict[str, str] = {}

    def __init__(self, boards: list[Board] | None = None) -> None:
        self.boards: list[Board] = list(boards) if boards is not None else boards_for(self.ats)
        self.last_report: list[BoardResult] = []

    # hooks -------------------------------------------------------------------------
    def extract_jobs(self, data: Any) -> list[Any]:
        raise NotImplementedError

    def is_remote(self, job: dict) -> bool:
        raise NotImplementedError

    # shared ------------------------------------------------------------------------
    def fetch(self, client: httpx.Client) -> list[SourceJob]:
        jobs: list[SourceJob] = []
        report: list[BoardResult] = []
        for board in self.boards:
            url = self.api_url.format(token=board.token)
            try:
                rows = self.extract_jobs(get_json(client, url, params=dict(self.api_params)))
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("%s board %s failed: %s", self.name, board.token, exc)
                report.append(BoardResult(board.token, False, error=f"{type(exc).__name__}: {exc}"))
                continue
            result = BoardResult(board.token, True, open_jobs=len(rows))
            for row in rows:
                if not isinstance(row, dict):
                    continue
                job_id = as_str(row.get("id"))
                if not job_id or not self.is_remote(row):
                    continue
                payload = {**row, "_radar": {"board": board.token, "company": board.company}}
                jobs.append(SourceJob(self.name, f"{board.token}/{job_id}", payload))
                result.remote_jobs += 1
            report.append(result)
        self.last_report = report
        failed = [r for r in report if not r.ok]
        if failed:
            log.warning(
                "%s: %d of %d boards failed (%s)",
                self.name,
                len(failed),
                len(report),
                ", ".join(r.token for r in failed),
            )
        if report and len(failed) == len(report):
            raise RuntimeError(f"{self.display_name}: all {len(report)} boards failed")
        return dedupe_jobs(jobs)


def radar_meta(payload: dict) -> dict:
    meta = payload.get("_radar")
    return meta if isinstance(meta, dict) else {}
