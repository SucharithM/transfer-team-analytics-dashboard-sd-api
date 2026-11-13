"""Font consistency for dashboard text and Plotly's separate font defaults."""

import pytest

from .test_dashboard_pdf import _open, _report, browser, page  # noqa: F401


@pytest.mark.parametrize('scenario', ['sample', 'empty'])
@pytest.mark.parametrize('width', [1440, 390])
def test_dashboard_text_and_chart_tooltips_share_the_body_font(page, tmp_path, scenario, width):
    page.set_viewport_size({'width': width, 'height': 1000})
    _open(page, _report(tmp_path / 'fonts.html', scenario))
    mismatches = page.evaluate('''() => {
      const family = getComputedStyle(document.body).fontFamily;
      const normalize = font => font.replaceAll('"', '');
      const mismatches = [];
      const check = (label, font) => {
        if (normalize(font) !== normalize(family)) mismatches.push({label, font});
      };
      for (const element of document.querySelectorAll('body *')) {
        if (['SCRIPT', 'STYLE'].includes(element.tagName)) continue;
        if ([...element.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim()))
          check(element.textContent.slice(0, 80), getComputedStyle(element).fontFamily);
      }
      for (const plot of document.querySelectorAll('.js-plotly-plot')) {
        check(plot.id, plot._fullLayout.font.family);
        for (const trace of plot._fullData) check(plot.id + ' hover', trace.hoverlabel.font.family);
        for (const annotation of plot._fullLayout.annotations) check(plot.id + ' annotation', annotation.font.family);
        for (const button of plot.querySelectorAll('.modebar-btn'))
          check(button.dataset.title, getComputedStyle(button, '::after').fontFamily);
        if (plot._fullData[0]?.type === 'bar') Plotly.Fx.hover(plot, [{curveNumber: 0, pointNumber: 0}]);
        for (const text of plot.querySelectorAll('.hoverlayer text, .hoverlayer tspan'))
          check(plot.id + ' rendered hover', getComputedStyle(text).fontFamily);
        Plotly.Fx.unhover(plot);
      }
      return mismatches;
    }''')
    assert mismatches == []
