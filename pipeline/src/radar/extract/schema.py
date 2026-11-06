"""Extraction schema shared by every backend.

``ExtractedJob`` is the strict record produced for each posting. Field descriptions are part
of the JSON schema sent to the model, so they double as prompt text.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_SKILLS = 25

RoleCategory = Literal[
    "software_engineering",
    "data",
    "devops_sre",
    "product",
    "design",
    "marketing",
    "sales",
    "support",
    "management",
    "other",
]
Seniority = Literal["intern", "junior", "mid", "senior", "lead", "principal", "unspecified"]
SalaryPeriod = Literal["year", "month", "hour"]
EmploymentType = Literal["full_time", "part_time", "contract", "unspecified"]


class ExtractedJob(BaseModel):
    """Structured fields extracted from one remote job posting."""

    role_category: RoleCategory = Field(
        description=(
            "Primary function of the role. software_engineering: building application or "
            "systems software (frontend, backend, mobile, embedded, QA automation). data: data "
            "analysis, analytics engineering, data engineering, data science, ML/AI research or "
            "engineering. devops_sre: infrastructure, cloud, platform, SRE, security "
            "operations. product: product management or ownership. design: UX/UI/graphic "
            "design. marketing: growth, content, SEO, community. sales: sales, account "
            "management, business development. support: customer support/success, technical "
            "support. management: people or engineering management with no hands-on focus. "
            "other: anything else. Tie-break by the main day-to-day work, not the industry."
        )
    )
    seniority: Seniority = Field(
        description=(
            "Seniority level. Decide from title words first (intern, junior, senior, lead, "
            "staff/principal), then from required years of experience (0-2 junior, 3-5 mid, "
            "6+ senior). Use 'unspecified' when unclear; never guess."
        )
    )
    skills: list[str] = Field(
        description=(
            "Concrete technologies, tools, languages, platforms and domain skills that the "
            "posting requires or prefers, in short canonical lowercase form (for example "
            "'python', 'postgresql', 'react', 'dbt', 'machine learning'). No soft skills, no "
            "job titles, no seniority words. Maximum 25."
        )
    )
    salary_min: float | None = Field(
        default=None,
        description="Lower bound of the salary as a plain number, only if explicitly stated.",
    )
    salary_max: float | None = Field(
        default=None,
        description="Upper bound of the salary as a plain number, only if explicitly stated.",
    )
    salary_currency: str | None = Field(
        default=None,
        description="ISO 4217 currency code of the stated salary (USD, EUR, GBP). Null if none.",
    )
    salary_period: SalaryPeriod | None = Field(
        default=None,
        description="Period the salary refers to: year, month or hour. Null if no salary.",
    )
    employment_type: EmploymentType = Field(
        description="full_time, part_time or contract; 'unspecified' if not stated."
    )
    remote_regions: list[str] = Field(
        description=(
            "Regions the candidate may be located in, as short names: 'worldwide', 'US', "
            "'EU', 'UK', 'Canada', 'LATAM', 'APAC', or country names. Empty list if the "
            "posting does not say."
        )
    )
    years_experience_min: int | None = Field(
        default=None,
        description="Minimum years of professional experience required, if stated. Else null.",
    )
    requires_degree: bool | None = Field(
        default=None,
        description="True if a university degree is required, false if explicitly not "
        "required, null if not mentioned.",
    )

    @field_validator("skills", mode="before")
    @classmethod
    def _clean_skills(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            skill = " ".join(item.strip().lower().split())
            if not skill or skill in seen:
                continue
            seen.add(skill)
            cleaned.append(skill)
        return cleaned[:MAX_SKILLS]

    @field_validator("remote_regions", mode="before")
    @classmethod
    def _clean_regions(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            region = item.strip()
            if not region or region.lower() in seen:
                continue
            seen.add(region.lower())
            cleaned.append(region)
        return cleaned

    @field_validator("salary_currency", mode="before")
    @classmethod
    def _clean_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().upper()
            return value or None
        return value

    @model_validator(mode="after")
    def _order_salary(self) -> ExtractedJob:
        lo, hi = self.salary_min, self.salary_max
        if lo is not None and hi is not None and lo > hi:
            self.salary_min, self.salary_max = hi, lo
        return self


def _simplify(node: Any, defs: dict[str, Any]) -> Any:
    """Inline $ref, drop titles/defaults, and make objects closed."""
    if isinstance(node, list):
        return [_simplify(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _simplify(defs[node["$ref"].split("/")[-1]], defs)
    out: dict[str, Any] = {}
    for key, val in node.items():
        if key in {"title", "default", "$defs"}:
            continue
        out[key] = _simplify(val, defs)
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


def extraction_json_schema() -> dict[str, Any]:
    """JSON schema accepted by both Claude (output_config.format) and Ollama (format=).

    Pydantic emits ``$defs`` and ``default``; both are inlined/removed. Every property is
    marked required (nullable fields use ``anyOf`` with ``null``, which both backends accept),
    and no numeric constraints are emitted because Claude's structured outputs reject them.
    """
    raw = ExtractedJob.model_json_schema()
    return _simplify(raw, raw.get("$defs", {}))
