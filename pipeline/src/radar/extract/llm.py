"""LLM extraction backends: Claude API and local Ollama behind one ``Extractor`` protocol."""

from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import anthropic
import httpx
import ollama
from pydantic import ValidationError

from radar.config import CLAUDE_MODEL, OLLAMA_MODEL, PROMPT_VERSION
from radar.extract.schema import ExtractedJob, extraction_json_schema

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"
MAX_DESCRIPTION_CHARS = 6000
CLAUDE_MAX_TOKENS = 4096  # JSON is ~300 tokens; the rest is headroom for adaptive thinking.
OLLAMA_NUM_CTX = 8192

# USD per million tokens. Source: the claude-api skill model table (cached 2026-10-06),
# checked 2026-11-06. Cache reads are 0.1x the input rate and 5-minute cache writes are
# 1.25x (skill: shared/prompt-caching.md). Update here when Anthropic changes prices.
CLAUDE_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.40, "cache_write": 5.00},
}

_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)


@dataclass
class JobInput:
    title: str
    company: str
    location: str | None
    description_text: str
    salary_text: str | None
    source_tags: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    backend: str
    model: str
    prompt_version: str
    ok: bool
    data: ExtractedJob | None
    error: str | None
    raw_output: str | None
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None


class Extractor(Protocol):
    backend: str
    model: str

    def extract(self, job: JobInput) -> ExtractionResult: ...


class MissingApiKeyError(RuntimeError):
    """ANTHROPIC_API_KEY is not set (configuration error, not a model-output problem)."""


# --------------------------------------------------------------------------- prompt helpers


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def truncate_description(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """Cut ``text`` to about ``limit`` characters on a paragraph (else line/word) boundary."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    floor = limit // 2
    for sep in ("\n\n", "\n", ". ", " "):
        idx = head.rfind(sep)
        if idx >= floor:
            head = head[: idx + (1 if sep == ". " else 0)]
            break
    return head.rstrip() + "\n[description truncated]"


def build_user_message(job: JobInput) -> str:
    lines = [
        f"Title: {job.title.strip()}",
        f"Company: {job.company.strip()}",
        f"Location: {(job.location or 'not stated').strip()}",
        f"Salary: {(job.salary_text or 'not stated').strip()}",
        f"Source tags: {', '.join(job.source_tags) if job.source_tags else 'none'}",
        "Description:",
        truncate_description(job.description_text or ""),
    ]
    return "\n".join(lines)


def parse_model_output(raw: str) -> ExtractedJob:
    """Parse model text into ``ExtractedJob``; raises ValueError describing the problem."""
    text = _THINK_RE.sub("", raw or "").strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in the reply")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    try:
        return ExtractedJob.model_validate(obj)
    except ValidationError as exc:
        parts = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]]
        raise ValueError("schema validation failed: " + "; ".join(parts)) from exc


# --------------------------------------------------------------------------- base class


@dataclass
class _Completion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class _BaseExtractor(ABC):
    backend: str
    model: str

    def __init__(self, prompt_version: str = PROMPT_VERSION) -> None:
        self.prompt_version = prompt_version
        self.system_prompt = load_system_prompt()
        self.schema = extraction_json_schema()

    @abstractmethod
    def _complete(self, messages: list[dict[str, str]]) -> _Completion:
        """One model call. Raises for configuration errors, returns text otherwise."""

    @abstractmethod
    def _transport_errors(self) -> tuple[type[BaseException], ...]:
        """Exceptions that mean 'this call failed' (not misconfiguration)."""

    def extract(self, job: JobInput) -> ExtractionResult:
        started = time.perf_counter()
        messages: list[dict[str, str]] = [{"role": "user", "content": build_user_message(job)}]
        in_tok: int | None = None
        out_tok: int | None = None
        cost: float | None = None
        raw: str | None = None
        error: str | None = None
        data: ExtractedJob | None = None

        for attempt in range(2):
            try:
                comp = self._complete(messages)
            except self._transport_errors() as exc:
                error = f"{type(exc).__name__}: {exc}"
                break
            raw = comp.text
            in_tok = _add(in_tok, comp.input_tokens)
            out_tok = _add(out_tok, comp.output_tokens)
            cost = _add(cost, comp.cost_usd)
            try:
                data = parse_model_output(raw)
                error = None
                break
            except ValueError as exc:
                error = str(exc)
                if attempt == 0:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": raw.strip() or "(empty reply)"},
                        {
                            "role": "user",
                            "content": (
                                f"That reply was not valid: {error}. Reply again with only one "
                                "JSON object that matches the schema exactly."
                            ),
                        },
                    ]

        return ExtractionResult(
            backend=self.backend,
            model=self.model,
            prompt_version=self.prompt_version,
            ok=data is not None,
            data=data,
            error=None if data is not None else (error or "unknown error")[:500],
            raw_output=raw,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
        )


def _add(a: Any, b: Any) -> Any:
    if b is None:
        return a
    return b if a is None else a + b


# --------------------------------------------------------------------------- Claude


def claude_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Cost in USD, or None if the model has no entry in ``CLAUDE_PRICING``.

    ``input_tokens`` is the uncached remainder, as reported by the API.
    """
    rates = CLAUDE_PRICING.get(model)
    if rates is None:
        return None
    return (
        input_tokens * rates["input"]
        + output_tokens * rates["output"]
        + cache_read_tokens * rates["cache_read"]
        + cache_write_tokens * rates["cache_write"]
    ) / 1_000_000


class ClaudeExtractor(_BaseExtractor):
    backend = "claude"

    def __init__(
        self,
        model: str | None = None,
        client: anthropic.Anthropic | None = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        super().__init__(prompt_version)
        self.model = model or CLAUDE_MODEL
        if client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise MissingApiKeyError(
                    "ANTHROPIC_API_KEY is not set. Export it (or use --backend ollama)."
                )
            client = anthropic.Anthropic(api_key=api_key)
        self._client = client

    def _transport_errors(self) -> tuple[type[BaseException], ...]:
        # Auth / permission / bad-request / not-found are configuration problems and propagate.
        return (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        )

    def _complete(self, messages: list[dict[str, str]]) -> _Completion:
        # Decisions, per the claude-api skill (checked 2026-11-06):
        # - Structured output via output_config.format (json_schema). Forced tool_choice is a
        #   400 on Sonnet 5.5, and structured outputs guarantee schema-shaped JSON anyway.
        # - No temperature: Sonnet 5.5 rejects non-default sampling params, and every model
        #   rejects temperature from 2026-10-21. Reproducibility is not guaranteed at API level.
        # - effort "low": extraction needs no deep reasoning; thinking is on by default
        #   on this model and bills as output tokens.
        # - Prompt caching on the system prompt: ~1.2k tokens, above the 512-token minimum for
        #   Sonnet 5.5, and identical on every call. Reads cost 0.1x. Writes cost 1.25x once
        #   per 5-minute window, so it pays off for any batch of more than a couple of jobs.
        response = self._client.messages.create(
            model=self.model,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": self.schema},
            },
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        in_uncached = usage.input_tokens or 0
        out = usage.output_tokens or 0
        return _Completion(
            text=text,
            input_tokens=in_uncached + cache_read + cache_write,
            output_tokens=out,
            cost_usd=claude_cost_usd(self.model, in_uncached, out, cache_read, cache_write),
        )


# --------------------------------------------------------------------------- Ollama


class OllamaExtractor(_BaseExtractor):
    backend = "ollama"

    def __init__(
        self,
        model: str | None = None,
        client: ollama.Client | None = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        super().__init__(prompt_version)
        self.model = model or OLLAMA_MODEL
        if client is None:
            client = ollama.Client(host=os.environ.get("OLLAMA_HOST") or None, timeout=300)
        self._client = client

    def _transport_errors(self) -> tuple[type[BaseException], ...]:
        return (httpx.TimeoutException, ollama.ResponseError)

    def _complete(self, messages: list[dict[str, str]]) -> _Completion:
        try:
            response = self._client.chat(
                model=self.model,
                messages=[{"role": "system", "content": self.system_prompt}, *messages],
                format=self.schema,
                # Thinking models (gemma4, qwen3) default to thinking: ~10x the output tokens and
                # latency, and the reasoning can leak into content. Extraction doesn't need it.
                think=False,
                options={"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
            )
        except ollama.ResponseError as exc:
            if exc.status_code == 404:  # model not pulled: configuration, not a bad reply
                raise RuntimeError(
                    f"Ollama model {self.model!r} not found. Run: ollama pull {self.model}"
                ) from exc
            raise
        except ConnectionError as exc:
            raise RuntimeError(
                "Cannot reach the Ollama server. Start it (ollama serve) or set OLLAMA_HOST."
            ) from exc
        message = response.message
        text = message.content or ""
        if not text.strip():
            # Some thinking models put the answer in the thinking field when content is empty.
            text = getattr(message, "thinking", None) or ""
        return _Completion(
            text=text,
            input_tokens=getattr(response, "prompt_eval_count", None),
            output_tokens=getattr(response, "eval_count", None),
            cost_usd=0.0,
        )


# --------------------------------------------------------------------------- factory


def get_extractor(backend: Literal["claude", "ollama"], model: str | None = None) -> Extractor:
    if backend == "claude":
        return ClaudeExtractor(model=model)
    if backend == "ollama":
        return OllamaExtractor(model=model)
    raise ValueError(f"unknown backend {backend!r}; expected 'claude' or 'ollama'")
