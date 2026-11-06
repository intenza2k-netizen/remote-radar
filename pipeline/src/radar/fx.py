"""Static, dated FX table used to express every published salary in USD.

The rates are rounded approximations, not market data: the snapshot compares salaries
across postings, it does not need to price a currency trade. They change slowly enough
that refreshing the table by hand every few months is acceptable. Update ``FX_AS_OF`` and
the values together.
"""

from __future__ import annotations

FX_AS_OF = "2026-11-01"

# USD per one unit of the currency.
USD_PER_UNIT: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.16,
    "GBP": 1.31,
    "CAD": 0.72,
    "AUD": 0.65,
    "NZD": 0.59,
    "CHF": 1.24,
    "SEK": 0.105,
    "NOK": 0.099,
    "DKK": 0.155,
    "PLN": 0.27,
    "CZK": 0.045,
    "HUF": 0.0029,
    "RON": 0.23,
    "BGN": 0.59,
    "RSD": 0.0099,
    "UAH": 0.024,
    "TRY": 0.023,
    "ILS": 0.27,
    "AED": 0.2723,
    "ZAR": 0.057,
    "INR": 0.0113,
    "SGD": 0.77,
    "HKD": 0.128,
    "JPY": 0.0066,
    "KRW": 0.00072,
    "PHP": 0.017,
    "BRL": 0.18,
    "MXN": 0.054,
    "ARS": 0.0007,
    "CLP": 0.00105,
    "COP": 0.00026,
}


def usd_rate(currency: str | None) -> float | None:
    """USD per unit of ``currency`` (ISO 4217, case-insensitive), or ``None`` if unknown."""
    if not currency:
        return None
    return USD_PER_UNIT.get(currency.strip().upper())


def to_usd(amount: float | None, currency: str | None) -> float | None:
    """Convert ``amount`` to USD; ``None`` when the amount is missing or the currency unknown."""
    if amount is None:
        return None
    rate = usd_rate(currency)
    if rate is None:
        return None
    return float(amount) * rate
