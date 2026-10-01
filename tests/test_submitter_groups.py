"""Staff inventory must reconcile while preserving meaningful submitter groups."""
import pandas as pd

from workflow_dashboard.analytics import (
    _submitted_by_date_activity,
    _team_member_counts,
    build_analytics,
)
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.dashboard_content import action_bucket_labels
from workflow_dashboard.dashboard_html import _category_color, _donut_chart, _age_idle_action_matrix_chart
from workflow_dashboard.history import build_metric_definition, store_snapshot, load_history
from .test_analytics_cohorts import GENERATED_AT, sample_cases


def test_submitter_groups_include_others_and_missing_without_losing_cases():
    df = pd.DataFrame({'owner': [' Team, Member ', 'team,  member', 'Outside A',
                                 'Outside B', None, '', '   ', pd.NA]})
    table = _team_member_counts(df, ('Team, Member', 'Zero, Member'))
    assert table.set_index('owner')['count'].to_dict() == {
        'Team, Member': 2, 'Zero, Member': 0, 'Others': 2, 'Not recorded': 4}
    assert table['count'].sum() == len(df)
    assert _team_member_counts(df.drop(columns='owner'), ()).set_index('owner')['count'].to_dict() == {
        'Others': 0, 'Not recorded': 8}


def test_dated_staff_groups_include_all_eligible_dates_and_zero_fill_members():
    date = GENERATED_AT - pd.Timedelta(days=1)
    df = pd.DataFrame({'owner': ['Team', 'Outside', None, 'Outside', 'Outside'],
                       'submitted_at': [date, date, date, pd.NaT, GENERATED_AT + pd.Timedelta(days=1)]})
    table = _submitted_by_date_activity(df, ('Team', 'Zero'), GENERATED_AT)
    assert table.groupby('owner')['count'].sum().to_dict() == {
        'Team': 1, 'Zero': 0, 'Others': 1, 'Not recorded': 1}
    assert table['count'].sum() == 3
    assert len(table['submitted_date'].unique()) == 1


def test_group_colors_are_fixed_and_keep_named_staff_colors():
    order = DashboardConfig().team_members
    assert _category_color('Others', 'staff', category_order=order) == '#475569'
    assert _category_color('Not recorded', 'staff', category_order=order) == '#737373'
    assert _category_color('Staff Member E', 'staff', category_order=order) == '#F48FB1'
    table = _team_member_counts(pd.DataFrame({'owner': ['External', None, order[0]]}), order)
    chart = _donut_chart(table, 'owner', 'count', 'Staff', color_dimension='staff', category_order=order)
    colors = dict(zip(chart.data[0].customdata, chart.data[0].marker.colors))
    assert colors['Others'] == '#475569'
    assert colors['Not recorded'] == '#737373'
    assert sum(chart.data[0].values) == 3


def test_new_staff_definition_round_trips_groups_without_mixing_old_series(tmp_path):
    df = sample_cases()
    df.loc[df.index[0], 'owner'] = None
    config = DashboardConfig()
    analytics = build_analytics(df, config=config, generated_at=GENERATED_AT)
    definition = build_metric_definition(config, df, source='fixture')
    assert definition.metric_definition_version == 9
    assert 'roster_plus_others_and_not_recorded' in definition.definition_json
    db = tmp_path / 'history.sqlite'
    store_snapshot(db, analytics, definition, source='fixture')
    _, owners, _ = load_history(db, source='fixture', definition_hash=definition.definition_hash)
    assert {'Others', 'Not recorded'}.issubset(set(owners.owner))
    assert owners.in_the_works_count.sum() == len(analytics.in_the_works)
    old_hash = build_metric_definition(config, df, source='fixture', metric_definition_version=8).definition_hash
    old_history, _, _ = load_history(db, source='fixture', definition_hash=old_hash)
    assert old_history.empty


def test_action_day_labels_match_nondefault_threshold_in_plot_and_hover():
    analytics = build_analytics(sample_cases(), config=DashboardConfig(backlog_age_days=8), generated_at=GENERATED_AT)
    chart = _age_idle_action_matrix_chart(analytics.chart_tables['age_idle_action_matrix'])
    labels = action_bucket_labels(8)
    assert labels['young_active'] == 'Up to 8 Days · Active'
    assert labels['backlog_stale'] == 'Over 8 Days · Idle'
    annotations = [a.text for a in chart.layout.annotations]
    assert any('Up to 8 Days · Active' in label for label in annotations)
    assert any('Over 8 Days · Idle' in label for label in annotations)
    for trace in chart.data:
        for row in trace.customdata:
            assert row[6] == labels[row[5]]
