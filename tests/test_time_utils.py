import pandas as pd
import pytest

from workflow_dashboard.time_utils import dashboard_timestamp, parse_source_time_series


@pytest.mark.parametrize(
    'source,expected',
    [
        ('2026-07-22T12:00:00-04:00', '2026-07-22T16:00:00Z'),
        ('2026-07-22T16:00:00Z', '2026-07-22T16:00:00Z'),
        ('2026-07-22T12:00:00', '2026-07-22T16:00:00Z'),
        ('2026-01-22T12:00:00', '2026-01-22T17:00:00Z'),
        ('2026-03-08T02:30:00', '2026-03-08T07:00:00Z'),
        ('2026-11-01T01:30:00', '2026-11-01T06:30:00Z'),
        (None, None),
        ('', None),
        ('not a date', None),
        ('2026-02-30T12:00:00', None),
        ('0001-01-01T00:00:00', None),
        ('0001-01-01T00:00:00Z', None),
    ],
)
def test_source_dates_preserve_utc_normalization_and_eastern_display(source, expected):
    actual = parse_source_time_series(pd.Series([source])).iloc[0]
    if expected is None:
        assert pd.isna(actual)
    else:
        expected = pd.Timestamp(expected)
        assert actual == expected
        assert dashboard_timestamp(actual) == expected.tz_convert('America/New_York')
        assert str(dashboard_timestamp(actual).tzinfo) == 'America/New_York'
