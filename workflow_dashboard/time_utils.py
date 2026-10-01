"""Timezone helpers for storage, calculations, and dashboard display."""

from __future__ import annotations

from typing import Any

import pandas as pd

DASHBOARD_TIMEZONE = "America/New_York"


def dashboard_timestamp(value: Any) -> pd.Timestamp:
    """Return a timestamp in the dashboard eastern timezone.

    Internal timestamps are UTC. A naive value passed here is therefore treated as
    UTC before it is converted for display.
    """

    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert(DASHBOARD_TIMEZONE)


def dashboard_time_series(series: pd.Series) -> pd.Series:
    """Convert an internal timestamp series to timezone-aware eastern time."""

    timestamps = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
    return timestamps.dt.tz_convert(DASHBOARD_TIMEZONE)


def parse_source_time_series(series: pd.Series) -> pd.Series:
    """Parse source timestamps into UTC, assuming unzoned API values are eastern time."""

    def parse_value(value: Any) -> pd.Timestamp:
        if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
            return pd.NaT
        timestamp = pd.to_datetime(value, errors="coerce")
        if pd.isna(timestamp):
            return pd.NaT
        timestamp = pd.Timestamp(timestamp)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(
                DASHBOARD_TIMEZONE,
                ambiguous=False,
                nonexistent="shift_forward",
            )
        return timestamp.tz_convert("UTC")

    return pd.to_datetime(series.map(parse_value), errors="coerce", utc=True)
