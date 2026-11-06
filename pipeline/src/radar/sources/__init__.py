"""Job-board source adapters."""

from __future__ import annotations

from radar.sources.arbeitnow import ArbeitnowSource
from radar.sources.ashby import AshbySource
from radar.sources.base import JobFields, Source, SourceJob
from radar.sources.greenhouse import GreenhouseSource
from radar.sources.hackernews import HackerNewsSource
from radar.sources.himalayas import HimalayasSource
from radar.sources.jobicy import JobicySource
from radar.sources.lever import LeverSource
from radar.sources.remoteok import RemoteOKSource
from radar.sources.remotive import RemotiveSource

# Order matters for dedupe: the first source to see a job keeps the canonical copy, so
# public job boards come before company ATS boards and Hacker News.
ALL_SOURCES: list[Source] = [
    RemotiveSource(),
    RemoteOKSource(),
    ArbeitnowSource(),
    JobicySource(),
    HimalayasSource(),
    GreenhouseSource(),
    AshbySource(),
    LeverSource(),
    HackerNewsSource(),
]

_BY_NAME: dict[str, Source] = {s.name: s for s in ALL_SOURCES}


def get_source(name: str) -> Source:
    try:
        return _BY_NAME[name]
    except KeyError:
        known = ", ".join(sorted(_BY_NAME))
        raise KeyError(f"unknown source {name!r} (known: {known})") from None


__all__ = ["ALL_SOURCES", "JobFields", "Source", "SourceJob", "get_source"]
