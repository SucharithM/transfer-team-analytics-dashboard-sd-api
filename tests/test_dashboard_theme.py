"""Browser checks for CSS variables, gradient hooks, and column proportions."""

import pandas as pd
import pytest
from playwright.sync_api import expect

from workflow_dashboard import theme
from workflow_dashboard.dashboard_html import _table_html

from .test_dashboard_pdf import _open, _report, browser, page  # noqa: F401


@pytest.mark.parametrize("width", [1440, 390])
def test_background_hooks_accept_live_variable_gradients(page, tmp_path, width):
    page.set_viewport_size({"width": width, "height": 1000})
    _open(page, _report(tmp_path / "gradient.html"))
    page.evaluate("""() => {
      const root = document.documentElement.style;
      root.setProperty('--primary', '#a12345');
      root.setProperty('--featured-background', 'linear-gradient(125deg, var(--primary), var(--category-2))');
      root.setProperty('--card-background', 'linear-gradient(45deg, var(--surface), var(--primary-soft))');
    }""")
    card = page.locator('.kpi[data-kpi="in_the_works"]')
    assert "rgb(161, 35, 69)" in card.evaluate("e => getComputedStyle(e).backgroundImage")
    assert "linear-gradient" in page.locator('.overview-charts .chart-container').first.evaluate("e => getComputedStyle(e).backgroundImage")
    page.evaluate("document.documentElement.style.setProperty('--primary', '#654321')")
    assert "rgb(101, 67, 33)" in card.evaluate("e => getComputedStyle(e).backgroundImage")
    page.locator('#tab-operations-panel').click()
    for plot in page.locator('#case-metrics-panel .donut-layout').all():
        assert plot.evaluate("""layout => {
          const chart = layout.querySelector('.js-plotly-plot');
          const probe = document.createElement('span');
          layout.append(probe);
          const colors = chart.data[0].marker.colors;
          const matches = [...layout.querySelectorAll('.category-swatch')].every((swatch, i) => {
            probe.style.color = colors[i];
            return getComputedStyle(swatch).backgroundColor === getComputedStyle(probe).color;
          });
          probe.remove();
          return matches;
        }""")


def test_observation_column_widths_and_print_ratios_come_from_css(page, tmp_path):
    _open(page, _report(tmp_path / "columns.html"))
    page.locator('#tab-exceptions-panel').click()
    # A subset must use only its included columns when calculating widths.
    markup = _table_html(pd.DataFrame({"step_name": ["Review"], "status": ["Needs Review"]}))
    page.locator('#problem-rows-table .table-scroll').evaluate('(e, html) => e.innerHTML = html', markup)
    table = page.locator('.observation-table')
    expect(table).to_have_css('width', f'{theme.number("column-step-name") + theme.number("column-status"):g}px')
    expect(table.locator('col[data-field="step_name"]')).to_have_css('width', f'{theme.number("column-step-name"):g}px')
    expect(table.locator('col[data-field="status"]')).to_have_css('width', f'{theme.number("column-status"):g}px')
    page.evaluate("document.documentElement.style.setProperty('--column-step-name', '480')")
    expect(table).to_have_css('width', f'{480 + theme.number("column-status"):g}px')
    page.emulate_media(media='print')
    widths = table.locator('col').evaluate_all('cols => cols.map(c => c.getBoundingClientRect().width)')
    assert widths[0] / widths[1] == pytest.approx(480 / theme.number("column-status"), abs=0.02)


def test_donut_caption_keeps_its_theme_font_in_chart_exports(page, tmp_path):
    _open(page, _report(tmp_path / "caption.html"))
    page.locator('#tab-operations-panel').click()
    size = page.evaluate("""async () => {
      const image = await Plotly.toImage('plot-aging-by-step', {format: 'svg', width: 600, height: 380});
      const svg = new DOMParser().parseFromString(decodeURIComponent(image.split(',')[1]), 'image/svg+xml');
      return [...svg.querySelectorAll('text')].find(t => t.textContent === 'Overall median').style.fontSize;
    }""")
    assert size == f'{theme.number("chart-font-size"):g}px'
