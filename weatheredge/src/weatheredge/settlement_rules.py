"""Canonical Polymarket Cape Town temperature settlement rules.

This module deliberately separates market-rule truth from meteorological
observations. Rules are versioned because the Cape Town market changed its
primary resolution source during 2026.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Optional


@dataclass(frozen=True)
class SettlementRule:
    version: str
    provider: str
    station: str
    primary_url: str
    fallback_url: Optional[str]
    fallback_deadline_et: Optional[str]
    precision_c: int
    revision_cutoff: str


WU_DAILY = SettlementRule(
    version="wu_daily_observations",
    provider="Weather Underground",
    station="Cape Town International Airport",
    primary_url="https://www.wunderground.com/history/daily/za/matroosfontein/FACT",
    fallback_url=None,
    fallback_deadline_et=None,
    precision_c=1,
    revision_cutoff="first datapoint for following date on resolution source",
)

NOAA_FACT = SettlementRule(
    version="noaa_fact_timeseries",
    provider="NOAA",
    station="Cape Town International Airport (FACT)",
    primary_url="https://www.weather.gov/wrh/timeseries?site=fact",
    fallback_url="https://www.wunderground.com/history/daily/za/matroosfontein/FACT",
    fallback_deadline_et="23:59 ET on following calendar day",
    precision_c=1,
    revision_cutoff="first datapoint for following date, or fallback deadline, whichever comes first",
)


def rule_for_date(market_date: str) -> SettlementRule:
    """Return the verified rule family for a market date.

    The exact transition date must be populated from the market's own rules
    before a historical row is classified. Do not infer it from observation
    data. The caller should supply/verify per-market rules.
    """
    raise ValueError(
        "Per-market rule verification is required; do not infer settlement "
        "source from the weather observations."
    )


def bucket_contains(temp_c: float, bucket_label: str) -> bool:
    """Conservative bucket matcher for labels such as '22°C' or '25°C or higher'."""
    label = bucket_label.strip().replace("°C", "").replace(" C", "").strip()
    if label.lower().startswith("or below"):
        return False
    if "or higher" in label.lower():
        low = float(label.split()[0])
        return temp_c >= low
    return abs(temp_c - float(label)) < 1e-9


def rules_hash(rule: SettlementRule) -> str:
    payload = "|".join(
        [
            rule.version,
            rule.provider,
            rule.station,
            rule.primary_url,
            rule.fallback_url or "",
            rule.fallback_deadline_et or "",
            str(rule.precision_c),
            rule.revision_cutoff,
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()
