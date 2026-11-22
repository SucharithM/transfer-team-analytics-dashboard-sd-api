"""One stylesheet drives report presentation and the non-CSS renderers."""

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_dashboard import theme

from .test_analytics_cohorts import build_sample_analytics, sample_cases
from .test_dashboard_pdf import _report
from .test_outputs import _history_frames


def test_report_embeds_the_stylesheet_and_has_no_authored_inline_styles(tmp_path):
    markup = _report(tmp_path / "theme.html").read_text(encoding="utf-8")
    assert f"<style>\n{theme.STYLESHEET}\n  </style>" in markup
    assert '<link rel="stylesheet"' not in markup
    # Plotly generates its own styles; application markup only supplies data/classes.
    package = Path(theme.__file__).parent
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\bstyle\s*=", node.value), path.name


def test_editing_the_css_updates_chart_and_workbook_styles(tmp_path):
    package = tmp_path / "workflow_dashboard"
    shutil.copytree(Path(theme.__file__).parent, package, ignore=shutil.ignore_patterns("__pycache__"))
    path = package / "styles.css"
    css = path.read_text(encoding="utf-8")
    for token, replacement in {
        "primary": "#a12345", "category-1": "var(--primary)", "font-ui": "Arial",
        "chart-font-size": "16", "workbook-font-size": "12",
    }.items():
        css = re.sub(rf"(--{token}:)[^;]+;", rf"\1 {replacement};", css)
    path.write_text(css, encoding="utf-8")
    subprocess.run([sys.executable, "-c", """
import pandas as pd
from openpyxl import Workbook
from workflow_dashboard.dashboard_html import _bar_chart, _category_color
from workflow_dashboard.excel_export import _style_sheet, _write_dataframe
from workflow_dashboard.theme import STYLESHEET, value

data = pd.DataFrame({'status': ['In Progress'], 'count': [1]})
chart = _bar_chart(data, 'status', 'count', 'Status', 'Count', color_dimension='status')
assert chart.data[0].marker.color[0] == '#a12345'
assert chart.layout.font.family.startswith('Arial,')
assert chart.layout.font.size == 16
assert _category_color('Other (2 statuses)', 'status') == value('category-3')
assert '--primary: #a12345;' in STYLESHEET
sheet = Workbook().active
_write_dataframe(sheet, data)
_style_sheet(sheet)
assert sheet['A1'].fill.fgColor.rgb == '00A12345'
assert sheet['A2'].font.name == 'Arial'
assert sheet['A2'].font.sz == 12
"""], cwd=tmp_path, check=True)


def test_invalid_shared_tokens_fail_with_a_useful_error(monkeypatch):
    monkeypatch.setattr(theme, "_TOKENS", {"a": "var(--b)", "b": "var(--a)", "rgb": "rgb(0, 0, 0)"})
    with pytest.raises(ValueError, match="Circular theme reference"):
        theme.value("a")
    with pytest.raises(ValueError, match="Missing theme token: --missing"):
        theme.value("missing")
    with pytest.raises(ValueError, match="six-digit hex"):
        theme.excel_color("rgb")


def test_workbook_has_no_implicit_font_for_visible_cells(tmp_path):
    from openpyxl import load_workbook
    from workflow_dashboard.excel_export import export_workbook

    analytics = build_sample_analytics()
    history, owners = _history_frames(analytics)
    path = export_workbook(
        df=sample_cases(), analytics=analytics, history=history,
        owner_history=owners, output_path=tmp_path / "theme.xlsx",
    )
    workbook = load_workbook(path)
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                if cell.value is not None:
                    assert cell.font.name == theme.value("workbook-font-family"), (sheet.title, cell.coordinate)
    workbook.close()
