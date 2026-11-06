"""Job-board source adapters."""

from __future__ import annotations

from radar.sources.arbeitnow import ArbeitnowSource
from radar.sources.base import JobFields, Source, SourceJob
from radar.sources.jobicy import JobicySource
from radar.sources.remoteok import RemoteOKSource
from radar.sources.remotive import RemotiveSource

ALL_SOURCES: list[Source] = [
    RemotiveSource(),
    RemoteOKSource(),
    ArbeitnowSource(),
    JobicySource(),
]

_BY_NAME: dict[str, Source] = {s.name: s for s in ALL_SOURCES}


def get_source(name: str) -> Source:
    try:
        return _BY_NAME[name]
    except KeyError:
        known = ", ".join(sorted(_BY_NAME))
        raise KeyError(f"unknown source {name!r} (known: {known})") from None


__all__ = ["ALL_SOURCES", "JobFields", "Source", "SourceJob", "get_source"]
