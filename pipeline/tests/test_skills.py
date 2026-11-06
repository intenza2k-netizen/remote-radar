"""Tests for radar.skills (canonicalisation + aliases.yaml integrity)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from radar.skills import SkillInfo, normalize_skill, normalize_skills, skill_info
from radar.skills.normalize import CATEGORIES, _load_registry, _registry

# Raw tags taken from the Remotive / Remote OK / Arbeitnow samples, plus the required forms.
SKILL_CASES = [
    # --- required punctuation / spelling variants ---
    ("react.js", "react"),
    ("reactjs", "react"),
    ("React JS", "react"),
    ("node.js", "nodejs"),
    ("nodejs", "nodejs"),
    ("Node", "nodejs"),
    ("c#", "csharp"),
    ("C Sharp", "csharp"),
    ("c++", "cpp"),
    ("C plus plus", "cpp"),
    ("go", "go"),
    ("golang", "go"),
    ("postgres", "postgresql"),
    ("PostgreSQL", "postgresql"),
    ("k8s", "kubernetes"),
    ("gcp", "gcp"),
    ("Google Cloud", "gcp"),
    ("aws", "aws"),
    ("Amazon Web Services", "aws"),
    ("ms excel", "excel"),
    ("Microsoft Excel", "excel"),
    ("ml", "machine-learning"),
    ("machine learning", "machine-learning"),
    # --- real tags from the samples ---
    ("Typescript ", "typescript"),  # trailing space in Remote OK data
    ("angular ", "angular"),
    ("AWS", "aws"),
    ("next.js", "nextjs"),
    ("ruby/rails", "ruby-on-rails"),
    ("ror", "ruby-on-rails"),
    ("Linux/Unix", "linux"),
    ("AI/ML", "machine-learning"),
    ("UI/UX", "ui-ux-design"),
    ("sys admin", "system-administration"),
    ("infosec", "cybersecurity"),
    ("quality assurance", "software-testing"),
    ("PyTorch", "pytorch"),
    ("mongo", "mongodb"),
    ("Microsoft 365", "microsoft-365"),
    ("G Suite", "google-workspace"),
    ("google sheets", "google-sheets"),
    ("data science", "data-science"),
    ("web dev", "web-development"),
    ("front end", "frontend"),
    ("full stack", "fullstack"),
    ("customer support", "customer-support"),
    ("SAP/ERP Consulting", "sap"),
    ("artificial intelligence", "ai"),
    ("javascript", "javascript"),
    (".Net", "dotnet"),
    ("ES6", "javascript"),
    ("SOLID", "design-patterns"),
    ("Power BI", "power-bi"),
    ("powerbi", "power-bi"),
    ("dbt", "dbt"),
    ("llms", "llm"),
    ("RAG", "rag"),
    # --- version suffix fallback ---
    ("Angular 17", "angular"),
    ("python 3.11", "python"),
    ("java 17", "java"),
    # --- punctuation and entity noise ---
    ("  #Python,  ", "python"),
    ("Node.js.", "nodejs"),
    ("R&amp;D", None),  # dropped department tag
    # --- unknown skills keep a slug ---
    ("Some New Tool", "some-new-tool"),
    ("Foo++", "foopp"),
    ("Bar#", "barsharp"),
    ("Hello  World", "hello-world"),
    ("Sondage", "sondage"),
]


@pytest.mark.parametrize(("raw", "expected"), SKILL_CASES)
def test_normalize_skill(raw, expected):
    assert normalize_skill(raw) == expected


DROPPED = [
    # soft skills / filler
    "communication",
    "Teamwork",
    "problem solving",
    "self-motivated",
    "team player",
    "English",
    "detail oriented",
    "fast learner",
    # junk tags seen in the data
    "dev",
    "senior",
    "exec",
    "digital nomad",
    "engineer",
    "Remote",
    "full time",
    "high school or equivalent",
    "Directors",
    "Chief Executives",
]


@pytest.mark.parametrize("raw", DROPPED)
def test_dropped(raw):
    assert normalize_skill(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "---",
        "x" * 41,
        "this is far too many words",  # 6 words
        "Graphic Arts and Communication Design",  # 5 words
        "4112.4251",  # no letters
        "中文",  # nothing survives ASCII slugging
    ],
)
def test_rejected_shapes(raw):
    assert normalize_skill(raw) is None


def test_four_words_is_the_limit():
    assert normalize_skill("one two three four") == "one-two-three-four"
    assert normalize_skill("one two three four five") is None


def test_normalize_skills_dedupes_and_preserves_order():
    raws = ["Python", "react.js", "teamwork", "python3", "ReactJS", "k8s", "", "Go", "golang"]
    assert normalize_skills(raws) == ["python", "react", "kubernetes", "go"]


def test_normalize_skills_empty():
    assert normalize_skills([]) == []


def test_skill_info_known():
    assert skill_info("python") == SkillInfo("python", "Python", "language")
    assert skill_info("csharp") == SkillInfo("csharp", "C#", "language")
    assert skill_info("kubernetes").category == "devops"
    assert skill_info("snowflake").category == "data"
    assert skill_info("postgresql").category == "database"
    assert skill_info("aws").category == "cloud"
    assert skill_info("pytorch").category == "ai_ml"
    assert skill_info("figma").category == "design"
    assert skill_info("salesforce").category == "business"
    assert skill_info("react").category == "framework"


def test_skill_info_unknown_slug():
    info = skill_info("some-new-tool")
    assert info == SkillInfo("some-new-tool", "Some New Tool", "other")


# --------------------------------------------------------------------------------------
# aliases.yaml integrity
# --------------------------------------------------------------------------------------

ALIASES_PATH = Path(__file__).resolve().parents[1] / "src" / "radar" / "skills" / "aliases.yaml"
RAW = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8"))


def test_vocabulary_size_and_categories():
    skills = RAW["skills"]
    assert len(skills) >= 250
    assert {spec["category"] for spec in skills.values()} <= CATEGORIES
    # every category from PLAN.md is used
    assert {spec["category"] for spec in skills.values()} >= CATEGORIES - {"other"}


def test_every_alias_round_trips_to_its_canonical():
    failures = []
    for slug, spec in RAW["skills"].items():
        for alias in [slug, spec["display"], *(spec.get("aliases") or [])]:
            got = normalize_skill(alias)
            if got != slug:
                failures.append(f"{alias!r}: expected {slug!r}, got {got!r}")
    assert not failures, "\n".join(failures)


def test_drop_entries_return_none():
    failures = [d for d in RAW["drop"] if normalize_skill(d) is not None]
    assert not failures, failures


def test_registry_is_cached():
    assert _registry() is _registry()


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "aliases.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_rejects_alias_mapped_to_two_canonicals(tmp_path):
    path = _write(
        tmp_path,
        "skills:\n"
        "  react: {display: React, category: framework, aliases: [shared]}\n"
        "  vue: {display: Vue, category: framework, aliases: ['Sh-ared']}\n"
        "drop: []\n",
    )
    with pytest.raises(ValueError, match="two canonicals"):
        _load_registry(path)


def test_load_rejects_unknown_category(tmp_path):
    path = _write(tmp_path, "skills:\n  x: {display: X, category: bogus, aliases: []}\ndrop: []\n")
    with pytest.raises(ValueError, match="category"):
        _load_registry(path)


def test_load_rejects_drop_entry_that_is_a_skill(tmp_path):
    path = _write(
        tmp_path,
        "skills:\n  python: {display: Python, category: language, aliases: [py]}\ndrop: [py]\n",
    )
    with pytest.raises(ValueError, match="also a skill alias"):
        _load_registry(path)


def test_load_rejects_non_string_alias(tmp_path):
    # YAML parses a bare `no` as the boolean False - exactly the typo this guard exists for.
    path = _write(
        tmp_path,
        "skills:\n  norway: {display: Norway, category: other, aliases: [no]}\ndrop: []\n",
    )
    with pytest.raises(ValueError, match="must be a string"):
        _load_registry(path)


# --------------------------------------------------------------------------------------
# Competing products must never share a canonical (they would inflate "% of jobs" numbers)
# --------------------------------------------------------------------------------------

COMPETITOR_PAIRS = [
    ("jenkins", "circleci"),
    ("jenkins", "teamcity"),
    ("jenkins", "travis ci"),
    ("datadog", "new relic"),
    ("datadog", "dynatrace"),
    ("datadog", "appdynamics"),
    ("helm", "argocd"),
    ("helm", "flux"),
    ("helm", "gitops"),
    ("terraform", "pulumi"),
    ("pulumi", "cloudformation"),
    ("pulumi", "bicep"),
    ("slack", "microsoft teams"),
    ("slack", "zoom"),
    ("slack", "discord"),
    ("asana", "trello"),
    ("asana", "clickup"),
    ("asana", "monday.com"),
    ("zapier", "make.com"),
    ("zapier", "n8n"),
    ("outreach", "salesloft"),
    ("outreach", "zoominfo"),
    ("outreach", "gong"),
    ("mailchimp", "klaviyo"),
    ("mailchimp", "braze"),
    ("semrush", "ahrefs"),
    ("figma", "sketch"),
    ("figma", "adobe xd"),
    ("figma", "miro"),
    ("blender", "maya"),
    ("blender", "zbrush"),
    ("premiere pro", "final cut pro"),
    ("premiere pro", "davinci resolve"),
    ("tensorflow", "keras"),
    ("tensorflow", "jax"),
    ("pytorch", "tensorflow"),
    ("scikit-learn", "xgboost"),
    ("scikit-learn", "lightgbm"),
    ("langchain", "llamaindex"),
    ("openai", "whisper"),
    ("llm", "claude"),
    ("llm", "gemini"),
    ("llm", "llama"),
    ("claude", "openai"),
    ("nodejs", "express"),
    ("deno", "bun"),
    ("git", "svn"),
    ("nginx", "apache"),
    ("nginx", "haproxy"),
    ("elasticsearch", "opensearch"),
    ("rabbitmq", "sqs"),
    ("rabbitmq", "celery"),
    ("rabbitmq", "nats"),
    ("stripe", "paypal"),
    ("stripe", "adyen"),
    ("webflow", "wix"),
    ("webflow", "squarespace"),
    ("webflow", "drupal"),
    ("workday", "adp"),
    ("workday", "bamboohr"),
    ("workday", "rippling"),
    ("netsuite", "dynamics 365"),
    ("netsuite", "odoo"),
    ("quickbooks", "xero"),
    ("active directory", "okta"),
    ("active directory", "windows server"),
    ("active directory", "intune"),
    ("siem", "crowdstrike"),
    ("databricks", "delta lake"),
    ("code review", "tech lead"),
    ("tech lead", "engineering management"),
    ("content writing", "technical writing"),
    ("people management", "hr"),
    ("concurrency", "cuda"),
    ("robotics", "iot"),
    ("robotics", "pcb design"),
    ("data visualization", "matplotlib"),
    ("data visualization", "plotly"),
    ("data visualization", "d3"),
    ("mlops", "mlflow"),
    ("mlops", "sagemaker"),
    ("mlops", "kubeflow"),
    ("test automation", "selenium"),
    ("test automation", "cypress"),
    ("test automation", "playwright"),
    ("test automation", "pytest"),
    ("vector database", "pinecone"),
    ("vector database", "weaviate"),
    ("etl", "informatica"),
    ("etl", "talend"),
    ("hadoop", "hive"),
    ("kafka", "kinesis"),
    ("trino", "presto"),
    ("looker", "looker studio"),
    ("product analytics", "mixpanel"),
    ("paid advertising", "google ads"),
    ("paid advertising", "meta ads"),
    ("crm", "salesforce"),
    ("crm", "hubspot"),
    ("crm", "pipedrive"),
    ("marketing automation", "marketo"),
    ("kubernetes", "openshift"),
    ("docker", "kubernetes"),
    ("vercel", "netlify"),
    ("gitlab ci", "github actions"),
    ("sales", "sales engineering"),
]


@pytest.mark.parametrize(
    ("a", "b"), COMPETITOR_PAIRS, ids=[f"{a}|{b}" for a, b in COMPETITOR_PAIRS]
)
def test_competing_products_stay_distinct(a, b):
    slug_a, slug_b = normalize_skill(a), normalize_skill(b)
    assert slug_a is not None
    assert slug_b is not None
    assert slug_a != slug_b


def test_hr_is_human_resources_not_people_management():
    # Deliberate: "hr" is the HR function, not line/people management.
    assert normalize_skill("HR") == "human-resources"
    assert normalize_skill("people management") == "people-management"
