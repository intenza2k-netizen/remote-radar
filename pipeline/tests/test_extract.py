"""Extraction layer tests. No network: both SDK clients are replaced by fakes."""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from radar.config import CLAUDE_MODEL, OLLAMA_MODEL, PROMPT_VERSION
from radar.extract import ExtractedJob, JobInput, get_extractor
from radar.extract.llm import (
    CLAUDE_PRICING,
    ClaudeExtractor,
    MissingApiKeyError,
    OllamaExtractor,
    build_user_message,
    claude_cost_usd,
    load_system_prompt,
    parse_model_output,
    truncate_description,
)
from radar.extract.schema import extraction_json_schema

GOOD = {
    "role_category": "data",
    "seniority": "senior",
    "skills": ["python", "sql", "dbt"],
    "salary_min": 140000,
    "salary_max": 170000,
    "salary_currency": "USD",
    "salary_period": "year",
    "employment_type": "full_time",
    "remote_regions": ["worldwide"],
    "years_experience_min": 5,
    "requires_degree": None,
}
GOOD_JSON = json.dumps(GOOD)


def make_job(**overrides) -> JobInput:
    base = {
        "title": "Senior Data Engineer",
        "company": "Acme",
        "location": "Worldwide",
        "description_text": "Build pipelines in Python and SQL.",
        "salary_text": "$140k-$170k",
        "source_tags": ["python", "sql"],
    }
    base.update(overrides)
    return JobInput(**base)


# ------------------------------------------------------------------ fakes


class FakeAnthropic:
    """Minimal stand-in for anthropic.Anthropic with a scripted queue of replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        text, usage = reply if isinstance(reply, tuple) else (reply, {})
        u = {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        u.update(usage)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(**u),
            stop_reason="end_turn",
        )


class FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        content = self.replies.pop(0)
        return SimpleNamespace(
            message=SimpleNamespace(content=content, thinking=None),
            prompt_eval_count=1500,
            eval_count=120,
        )


# ------------------------------------------------------------------ schema


def test_validator_normalises_skills():
    raw = dict(GOOD, skills=["  Python ", "SQL", "python", "", "  ", "React  Native", 5, "sql"])
    job = ExtractedJob.model_validate(raw)
    assert job.skills == ["python", "sql", "react native"]


def test_validator_caps_skills_at_25():
    raw = dict(GOOD, skills=[f"skill{i}" for i in range(40)])
    assert len(ExtractedJob.model_validate(raw).skills) == 25


def test_validator_currency_and_salary_order():
    raw = dict(GOOD, salary_min=170000, salary_max=140000, salary_currency=" usd ")
    job = ExtractedJob.model_validate(raw)
    assert job.salary_currency == "USD"
    assert (job.salary_min, job.salary_max) == (140000, 170000)


def test_blank_currency_becomes_none():
    assert ExtractedJob.model_validate(dict(GOOD, salary_currency="  ")).salary_currency is None


def test_validator_rejects_bad_enum():
    with pytest.raises(ValueError):
        ExtractedJob.model_validate(dict(GOOD, seniority="wizard"))


def test_json_schema_is_flat_and_closed():
    schema = extraction_json_schema()
    text = json.dumps(schema)
    for banned in ("$ref", "$defs", '"title"', '"default"'):
        assert banned not in text
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == set(ExtractedJob.model_fields)
    assert {"type": "null"} in schema["properties"]["salary_min"]["anyOf"]
    assert schema["properties"]["seniority"]["enum"][-1] == "unspecified"
    assert schema["properties"]["skills"]["items"] == {"type": "string"}


# ------------------------------------------------------------------ prompt + input


def test_system_prompt_loads_and_mentions_key_rules():
    prompt = load_system_prompt()
    assert "unspecified" in prompt and "worldwide" in prompt and "soft skills" in prompt


def test_truncate_description_short_text_unchanged():
    assert truncate_description("hello\n\nworld", 100) == "hello\n\nworld"


def test_truncate_description_cuts_on_paragraph():
    paras = [f"para{i} " + "x" * 90 for i in range(100)]
    out = truncate_description("\n\n".join(paras), 6000)
    body = out.removesuffix("\n[description truncated]")
    assert len(body) <= 6000
    assert out.endswith("[description truncated]")
    assert body.split("\n\n")[-1] in paras  # no paragraph cut in half


def test_truncate_description_falls_back_to_word_boundary():
    out = truncate_description("word " * 5000, 100)
    assert out.startswith("word") and "wor\n" not in out
    assert len(out) < 140


def test_build_user_message_contains_fields_and_truncates():
    msg = build_user_message(
        make_job(description_text="a" * 20000 + " tail", location=None, salary_text=None)
    )
    assert "Title: Senior Data Engineer" in msg
    assert "Location: not stated" in msg and "Salary: not stated" in msg
    assert "Source tags: python, sql" in msg
    assert len(msg) < 6300 and "[description truncated]" in msg


@pytest.mark.parametrize(
    "raw",
    [
        GOOD_JSON,
        f"```json\n{GOOD_JSON}\n```",
        f"<think>maybe {{ not json }}</think>\n{GOOD_JSON}",
        f"Here you go: {GOOD_JSON} Hope that helps!",
    ],
)
def test_parse_model_output_tolerates_wrapping(raw):
    assert parse_model_output(raw).seniority == "senior"


@pytest.mark.parametrize("raw", ["", "no json here", "{not json", "[1,2]", '{"seniority": "x"}'])
def test_parse_model_output_rejects_garbage(raw):
    with pytest.raises(ValueError):
        parse_model_output(raw)


# ------------------------------------------------------------------ cost


def test_cost_math_plain():
    # 1000 in * $2/M + 500 out * $10/M
    assert claude_cost_usd("claude-sonnet-5-5", 1000, 500) == pytest.approx(0.002 + 0.005)


def test_cost_math_with_cache():
    cost = claude_cost_usd(
        "claude-sonnet-5-5", 100, 200, cache_read_tokens=1000, cache_write_tokens=1000
    )
    expected = (100 * 2.0 + 200 * 10.0 + 1000 * 0.20 + 1000 * 2.50) / 1e6
    assert cost == pytest.approx(expected)


def test_cost_unknown_model_is_none():
    assert claude_cost_usd("claude-future-9", 10, 10) is None


def test_configured_model_has_pricing():
    assert CLAUDE_MODEL in CLAUDE_PRICING


# ------------------------------------------------------------------ Claude backend


def test_claude_happy_path_request_and_accounting():
    client = FakeAnthropic([(GOOD_JSON, {"cache_read_input_tokens": 1200, "input_tokens": 300})])
    result = ClaudeExtractor(client=client).extract(make_job())

    assert result.ok and result.error is None
    assert result.data is not None and result.data.skills == ["python", "sql", "dbt"]
    assert (result.backend, result.model, result.prompt_version) == (
        "claude",
        CLAUDE_MODEL,
        PROMPT_VERSION,
    )
    assert result.input_tokens == 1500 and result.output_tokens == 200
    assert result.cost_usd == pytest.approx((300 * 2.0 + 200 * 10.0 + 1200 * 0.20) / 1e6)
    assert result.latency_ms >= 0 and result.raw_output == GOOD_JSON

    call = client.calls[0]
    assert call["model"] == CLAUDE_MODEL
    assert "temperature" not in call  # rejected by Sonnet 5.5 / all models after 2026-10-21
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"] == extraction_json_schema()
    assert call["messages"][0]["role"] == "user"


def test_claude_custom_model():
    client = FakeAnthropic([GOOD_JSON])
    result = ClaudeExtractor(model="claude-haiku-5-5", client=client).extract(make_job())
    assert result.model == "claude-haiku-5-5" and client.calls[0]["model"] == "claude-haiku-5-5"


def test_claude_retry_then_success():
    client = FakeAnthropic(["not json at all", GOOD_JSON])
    result = ClaudeExtractor(client=client).extract(make_job())

    assert result.ok and len(client.calls) == 2
    retry = client.calls[1]["messages"]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]
    assert retry[1]["content"] == "not json at all"
    assert "not valid" in retry[2]["content"]
    assert result.input_tokens == 2000 and result.output_tokens == 400  # both attempts counted
    assert result.cost_usd == pytest.approx(2 * (1000 * 2.0 + 200 * 10.0) / 1e6)


def test_claude_retry_then_failure():
    bad = json.dumps(dict(GOOD, seniority="wizard"))
    client = FakeAnthropic(["garbage", bad])
    result = ClaudeExtractor(client=client).extract(make_job())

    assert not result.ok and result.data is None
    assert len(client.calls) == 2  # exactly one retry
    assert result.raw_output == bad
    assert result.error and "seniority" in result.error


def test_claude_transport_error_returns_not_ok():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = FakeAnthropic([anthropic.APIConnectionError(request=req)])
    result = ClaudeExtractor(client=client).extract(make_job())
    assert not result.ok and "APIConnectionError" in (result.error or "")
    assert result.raw_output is None


def test_claude_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
        ClaudeExtractor()
    with pytest.raises(MissingApiKeyError):
        get_extractor("claude")


def test_claude_builds_real_client_when_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    ext = get_extractor("claude")
    assert ext.backend == "claude" and ext.model == CLAUDE_MODEL


# ------------------------------------------------------------------ Ollama backend


def test_ollama_happy_path():
    client = FakeOllama([GOOD_JSON])
    result = OllamaExtractor(client=client).extract(make_job())

    assert result.ok and result.data is not None and result.data.role_category == "data"
    assert (result.backend, result.model) == ("ollama", OLLAMA_MODEL)
    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (1500, 120, 0.0)

    call = client.calls[0]
    assert call["format"] == extraction_json_schema()
    assert call["options"] == {"temperature": 0, "num_ctx": 8192}
    assert call["think"] is False
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][1]["role"] == "user"


def test_ollama_handles_thinking_and_fences():
    client = FakeOllama([f"<think>hmm</think>\n```json\n{GOOD_JSON}\n```"])
    assert OllamaExtractor(client=client).extract(make_job()).ok


def test_ollama_retry_then_success():
    client = FakeOllama(['{"role_category": "data"', GOOD_JSON])
    result = OllamaExtractor(client=client).extract(make_job())
    assert result.ok and len(client.calls) == 2
    assert result.input_tokens == 3000 and result.cost_usd == 0.0


def test_ollama_retry_then_failure():
    client = FakeOllama(["nope", ""])
    result = OllamaExtractor(client=client).extract(make_job())
    assert not result.ok and result.data is None and len(client.calls) == 2
    assert result.error and result.raw_output == ""


def test_get_extractor_ollama_and_unknown():
    ext = get_extractor("ollama", model="qwen3:32b")
    assert (ext.backend, ext.model) == ("ollama", "qwen3:32b")
    with pytest.raises(ValueError):
        get_extractor("openai")  # type: ignore[arg-type]
