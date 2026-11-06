"""Tests for radar.normalize (HTML, salary, title/company cleanup, annualize)."""

from __future__ import annotations

import pytest

from radar.normalize import (
    SalaryParse,
    annualize,
    clean_company,
    clean_title,
    html_to_text,
    parse_salary_text,
)

# --------------------------------------------------------------------------------------
# parse_salary_text
# --------------------------------------------------------------------------------------

SALARY_CASES = [
    # --- strings seen in the Remotive sample ---
    ("$20k -$35k", (20000, 35000, "USD", "year")),
    ("$170k - $200k", (170000, 200000, "USD", "year")),
    ("70K-80K", (70000, 80000, None, "year")),
    ("$35,3k- $52k", (35300, 52000, "USD", "year")),  # decimal comma before k
    ("OTE $25k - $35k", (25000, 35000, "USD", "year")),
    ("$3.5k–$5k/month", (3500, 5000, "USD", "month")),  # en dash, explicit period
    # --- common formats ---
    ("$50,000 - $70,000", (50000, 70000, "USD", "year")),
    ("€60.000–80.000", (60000, 80000, "EUR", "year")),  # European thousands dots
    ("80-100k EUR", (80000, 100000, "EUR", "year")),  # unit on the upper bound only
    ("USD 120k+", (120000, None, "USD", "year")),
    ("£45k", (45000, 45000, "GBP", "year")),
    ("$40/hr", (40, 40, "USD", "hour")),
    ("$25 - $35 per hour", (25, 35, "USD", "hour")),
    ("5000 USD/month", (5000, 5000, "USD", "month")),
    ("up to $90k", (None, 90000, "USD", "year")),
    ("€45,000—€55,000", (45000, 55000, "EUR", "year")),  # em dash
    ("$80,000 - $100,000 a year", (80000, 100000, "USD", "year")),
    ("4.000 - 5.000 € pro Monat", (4000, 5000, "EUR", "month")),
    ("C$90k-110k", (90000, 110000, "CAD", "year")),
    ("AU$ 120k - 150k p.a.", (120000, 150000, "AUD", "year")),
    ("₹ 12,00,000", (1200000, 1200000, "INR", "year")),
    ("$50k to $70k", (50000, 70000, "USD", "year")),
    ("from $50k", (50000, None, "USD", "year")),
    ("$70k-$50k", (50000, 70000, "USD", "year")),  # reversed -> swapped
    ("USD120k", (120000, 120000, "USD", "year")),
    ("1.234,56 €", (1234.56, 1234.56, "EUR", "month")),  # EU decimal comma
    # --- period inferred from magnitude: <300 hour, <20000 month, else year ---
    ("$45", (45, 45, "USD", "hour")),
    ("€3500", (3500, 3500, "EUR", "month")),
    ("$20000", (20000, 20000, "USD", "year")),
]


@pytest.mark.parametrize(("text", "expected"), SALARY_CASES)
def test_parse_salary_text(text, expected):
    lo, hi, currency, period = expected
    assert parse_salary_text(text) == SalaryParse(
        min=None if lo is None else float(lo),
        max=None if hi is None else float(hi),
        currency=currency,
        period=period,
    )


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "Competitive",
        "DOE",
        "Negotiable",
        "$1000 per task",  # piece rate cannot be annualised
        "£350 per day",
        "10% commission",
        "5 years of experience",
        "401k match",
        "$",
        "TBD",
    ],
)
def test_parse_salary_text_rejects_non_salaries(text):
    assert parse_salary_text(text) is None


def test_parse_salary_text_ignores_trailing_numbers_in_noise():
    result = parse_salary_text("$120k - $150k plus 10% bonus, 25 days holiday")
    assert result == SalaryParse(120000.0, 150000.0, "USD", "year")


# --------------------------------------------------------------------------------------
# annualize
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "period", "expected"),
    [
        (40, "hour", 83200.0),
        (5000, "month", 60000.0),
        (90000, "year", 90000.0),
        (90000, None, 90000.0),
        (None, "year", None),
        (None, None, None),
        (100000, "yearly", 100000.0),  # Jobicy spelling
        (30, "HOURLY", 62400.0),
        (10, "week", None),  # unsupported period
    ],
)
def test_annualize(amount, period, expected):
    assert annualize(amount, period) == expected


# --------------------------------------------------------------------------------------
# clean_title / clean_company
# --------------------------------------------------------------------------------------

TITLE_CASES = [
    ("Senior Backend Engineer (m/w/d)", "Senior Backend Engineer"),
    ("Senior Customer Success Manager (m/f/x)", "Senior Customer Success Manager"),
    ("Senior Applied AI Engineer, AI Platform (f/m/d)", "Senior Applied AI Engineer, AI Platform"),
    ("Backend Developer:in .NET / C# (m/w/d)", "Backend Developer:in .NET / C#"),
    ("Senior People Partner (all genders)", "Senior People Partner"),
    ("(Senior) Product Designer (m/f/d)", "(Senior) Product Designer"),
    (
        "Technical Account Manager (m/w/d) B2B MCPTT / Mobilfunk",
        "Technical Account Manager B2B MCPTT / Mobilfunk",
    ),
    ("Ingénieur Hydrogéologue F/H", "Ingénieur Hydrogéologue"),
    ("Stagiaire Marketing & Communication (H/F)", "Stagiaire Marketing & Communication"),
    ("Senior IT Consultant*", "Senior IT Consultant"),
    ("Client Support &amp; Travel Booking Online", "Client Support & Travel Booking Online"),
    ("  Data   Engineer   ", "Data Engineer"),
    ("DevOps Engineer (f/m/d) -", "DevOps Engineer"),
    (
        "Oracle Fusion Cloud Lead â\u0080\u0094 Logistics & Supply Chain Management",
        "Oracle Fusion Cloud Lead — Logistics & Supply Chain Management",
    ),
    ("Product Manager - Security", "Product Manager - Security"),  # real suffix is kept
    ("Account Executive (w/m/*)", "Account Executive"),
    ("", ""),
]


@pytest.mark.parametrize(("raw", "expected"), TITLE_CASES)
def test_clean_title(raw, expected):
    assert clean_title(raw) == expected


def test_clean_title_none_safe():
    assert clean_title(None) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Coalition Technologies ", "Coalition Technologies"),
        ("  Fluence   International, Inc.", "Fluence International, Inc."),
        ("Smith &amp; Sons", "Smith & Sons"),
        ("Concircle Ã\u0096sterreich GmbH", "Concircle Österreich GmbH"),
        ("", ""),
    ],
)
def test_clean_company(raw, expected):
    assert clean_company(raw) == expected


# --------------------------------------------------------------------------------------
# html_to_text
# --------------------------------------------------------------------------------------

ARBEITNOW_ESCAPED = (
    "&lt;div class=&quot;page&quot;&gt;\n&lt;div class=&quot;column&quot;&gt;\n"
    "&lt;p&gt;You don&#39;t want another role where someone else owns the architecture.&lt;/p&gt;\n"
    "&lt;p&gt;&lt;strong&gt;Location:&lt;/strong&gt; Central Berlin&lt;/p&gt;\n"
    "&lt;h3&gt;&amp;nbsp;&lt;/h3&gt;\n&lt;h3&gt;Your responsibilities&lt;/h3&gt;\n"
    "&lt;ul&gt;\n&lt;li&gt;Own the backend&lt;/li&gt;\n"
    "&lt;li&gt;Build AI-first features&lt;/li&gt;\n&lt;/ul&gt;\n"
    "&lt;/div&gt;\n&lt;/div&gt;"
    # Arbeitnow appends real markup after the escaped body:
    '<p>Find <a href="https://www.arbeitnow.com">Jobs in Germany</a> on Arbeitnow</p>'
)

HTML_CASES = [
    # (id, input, expected)
    ("none", None, ""),
    ("empty", "", ""),
    ("whitespace-only", "  \n\t ", ""),
    ("plain-text", "Just some text &amp; more", "Just some text & more"),
    (
        "paragraphs",
        "<p>First paragraph.</p><p>Second   paragraph.</p>",
        "First paragraph.\n\nSecond paragraph.",
    ),
    (
        "br-and-inline",
        "<p>Line one<br>Line two <b>bold</b> <i>it</i></p>",
        "Line one\nLine two bold it",
    ),
    (
        "list-items",
        "<p>Requirements</p><ul><li>Python</li><li>SQL</li><li>dbt</li></ul><p>Done</p>",
        "Requirements\n\n- Python\n- SQL\n- dbt\n\nDone",
    ),
    (
        "script-and-style-dropped",
        "<style>p {color: red}</style><p>Hello</p><script>alert('x')</script><p>World</p>",
        "Hello\n\nWorld",
    ),
    (
        "remoteok-inline-styles",
        '<p style="min-height:1.5em"><strong>ABOUT CIVILGRID</strong></p>'
        '<p style="min-height:1.5em">Teams at PG&amp;E use it.</p><p style="min-height:1.5em"></p>'
        '<p style="min-height:1.5em"><br></p><ul><li style="x"><p>Build things</p></li></ul>',
        "ABOUT CIVILGRID\n\nTeams at PG&E use it.\n\n- Build things",
    ),
    (
        "headings-and-nbsp",
        "<h2>About us</h2><p>&nbsp;</p><h3>Role</h3><div>Text&nbsp;here</div>",
        "About us\n\nRole\n\nText here",
    ),
    (
        "nested-lists",
        "<ul><li>Backend<ul><li>Python</li><li>Go</li></ul></li><li>Data</li></ul>",
        "- Backend\n- Python\n- Go\n- Data",
    ),
    (
        "empty-list-item-skipped",
        "<ul><li></li><li>Real item</li></ul>",
        "- Real item",
    ),
    (
        "arbeitnow-escaped-with-real-footer",
        ARBEITNOW_ESCAPED,
        "You don't want another role where someone else owns the architecture.\n\n"
        "Location: Central Berlin\n\nYour responsibilities\n\n- Own the backend\n"
        "- Build AI-first features\n\nFind Jobs in Germany on Arbeitnow",
    ),
    (
        "literal-code-sample-in-real-html-is-kept",
        "<p>Use the &lt;div&gt; tag</p><p>and more</p>",
        "Use the <div> tag\n\nand more",
    ),
    (
        "comment-dropped",
        "<p>Hi</p><!-- hidden --><p>There</p>",
        "Hi\n\nThere",
    ),
    ("mojibake-repaired", "<p>Cloud Lead â\u0080\u0094 Logistics</p>", "Cloud Lead — Logistics"),
]


@pytest.mark.parametrize(("case_id", "raw", "expected"), HTML_CASES, ids=[c[0] for c in HTML_CASES])
def test_html_to_text(case_id, raw, expected):
    assert html_to_text(raw) == expected


def test_html_to_text_collapses_blank_lines_and_spaces():
    out = html_to_text("<div><div><p>a</p></div></div><p>​</p><p>   </p><p>b   c</p>")
    assert out == "a\n\nb c"
    assert "\n\n\n" not in out


_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADh"
    + "gGAWjR9awAAAABJRU5ErkJggg=="
)
_LONG_B64 = "QUJD" * 80  # 320 chars, no whitespace


@pytest.mark.parametrize(
    ("case_id", "raw", "expected"),
    [
        (
            "img-src-data-uri",
            f'<p>Intro</p><img src="data:image/png;base64,{_B64}" alt="logo"><p>Outro</p>',
            "Intro\n\nOutro",
        ),
        (
            "data-uri-as-text",
            f"<p>Logo: data:image/jpeg;base64,{_B64} end</p>",
            "Logo: end",
        ),
        (
            "css-background-data-uri",
            f'<div style="background:url(data:image/gif;base64,{_B64})"><p>Hello</p></div>',
            "Hello",
        ),
        (
            "bare-base64-run-as-text",
            f"<p>Before</p><p>{_LONG_B64}</p><p>After</p>",
            "Before\n\nAfter",
        ),
        (
            "escaped-html-with-data-uri",
            f"&lt;p&gt;Hi&lt;/p&gt;&lt;img src=&quot;data:image/png;base64,{_B64}&quot;&gt;"
            "&lt;p&gt;There&lt;/p&gt;",
            "Hi\n\nThere",
        ),
        (
            "short-token-and-normal-long-words-kept",
            "<p>Token abc123XYZ and pneumonoultramicroscopicsilicovolcanoconiosis</p>",
            "Token abc123XYZ and pneumonoultramicroscopicsilicovolcanoconiosis",
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and len(v) < 40 else None,
)
def test_html_to_text_strips_inline_images(case_id, raw, expected):
    out = html_to_text(raw)
    assert out == expected
    assert "base64" not in out
