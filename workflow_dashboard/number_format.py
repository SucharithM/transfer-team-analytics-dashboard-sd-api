"""Consistent numeric formatting for manager-facing outputs."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd


ONE_DECIMAL = Decimal("0.1")


def round_one_decimal(value: Any) -> float | None:
    """Round a scalar to one decimal with decimal half-up semantics."""

    if value is None or pd.isna(value):
        return None
    return float(Decimal(str(value)).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP))


def format_one_decimal(
    value: Any, *, suffix: str = "", missing: str = "-"
) -> str:
    """Format a scalar to one decimal using the shared presentation policy."""

    rounded = round_one_decimal(value)
    if rounded is None:
        return missing
    return f"{rounded:.1f}{suffix}"
