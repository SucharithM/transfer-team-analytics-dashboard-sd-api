"""Progressively enhanced, offline navigation for dashboard sections."""

import html


def tab_bar(group: str, label: str, tabs: tuple[tuple[str, str], ...]) -> str:
    """Keep navigation labels separate from the unchanged report headings."""
    links = "".join(
        f'<a id="tab-{html.escape(target)}" href="#{html.escape(target)}">'
        f"{html.escape(title)}</a>"
        for target, title in tabs
    )
    return (
        f'<div class="dashboard-tabbar" data-tab-list="{html.escape(group)}" '
        f'aria-label="{html.escape(label)}">{links}</div>'
    )


NAVIGATION_STYLES = """
    .dashboard-tabs { --primary-tabs-height: 37px; margin-top: 12px; }
    .tabs-ready .dashboard-tabs { overflow-anchor: none; }
    .tab-panels { display: flow-root; overflow-anchor: none; }
    .dashboard-tabbar { display: none; }
    .tabs-ready .dashboard-tabbar {
      display: flex; gap: 4px; overflow-x: auto; background: var(--surface);
      border-bottom: 1px solid var(--border); padding: 2px 4px;
      position: sticky; top: var(--primary-tabs-height); z-index: 12;
      scrollbar-width: thin; scroll-margin-top: var(--primary-tabs-height);
    }
    .tabs-ready [data-tab-list="sections"] {
      top: 0; z-index: 15; scroll-margin-top: 0;
      box-shadow: 0 3px 10px rgba(34, 49, 73, 0.07);
    }
    .dashboard-tabbar a {
      display: flex; align-items: flex-end; flex: 0 0 auto;
      min-height: 34px; padding: 4px 12px; border-radius: 6px;
      color: var(--muted); font-size: 13px; font-weight: 600;
      text-decoration: none; white-space: nowrap;
      transition: color 120ms ease, background-color 120ms ease;
    }
    .dashboard-tabbar a:hover { background: var(--surface-muted); color: var(--text); }
    .dashboard-tabbar a[aria-selected="true"] {
      color: var(--primary-dark); background: var(--primary-soft);
      box-shadow: inset 0 -2px var(--primary);
    }
    .dashboard-tabbar a:focus-visible, [data-tab-panel]:focus-visible {
      outline: 3px solid var(--primary); outline-offset: -3px;
    }
    [data-tab-panel] { scroll-margin-top: calc(var(--primary-tabs-height) + 12px); }
    [data-tab-panel="operations"], [data-tab-panel="staff"] {
      scroll-margin-top: calc(var(--primary-tabs-height) + 72px);
    }
    [data-tab-panel]:not(.dashboard-section) { margin-top: 8px; }
    .tabs-ready [data-tab-panel][hidden] { display: none; }
    .tabs-ready .table-container, .tabs-ready .action-matrix-controls,
    .tabs-ready .action-matrix-drilldown {
      scroll-margin-top: calc(var(--primary-tabs-height) + 72px);
    }
    .dashboard-tabs .dashboard-section { margin-top: 8px; }
    .dashboard-tabs .chart-container { padding: 15px 16px 10px; margin-bottom: 12px; }
    .dashboard-tabs .table-container { padding: 15px 16px 16px; }
    .case-metrics-grid, .aging-grid { display: grid; gap: 12px; grid-template-columns: 1fr; }
    .case-metrics-grid .chart-container, .aging-grid .chart-container { margin-bottom: 0; }
    .aging-grid .chart-container-wide { overflow-x: auto; }
    #problem-rows-table .table-scroll { max-height: 420px; overflow: auto; }
    @media (pointer: coarse) {
      .dashboard-tabbar a { min-height: 44px; }
    }
    @media (prefers-reduced-motion: reduce) {
      .dashboard-tabbar a { transition: none; }
    }
"""


NAVIGATION_SCRIPT = """
  <script>
    (() => {
      const guide = document.querySelector('.legend-card');
      const guideToggle = guide.querySelector('.legend-toggle');
      const guideContent = document.getElementById(guideToggle.getAttribute('aria-controls'));
      const setGuideExpanded = expanded => {
        guideToggle.setAttribute('aria-expanded', String(expanded));
        guideToggle.querySelector('span').textContent = expanded ? 'Hide guide' : 'Show guide';
        guideContent.classList.toggle('is-collapsed', !expanded);
      };
      setGuideExpanded(false);
      guideToggle.hidden = false;
      // Enable transitions only after the initial collapsed layout is established.
      guideContent.getBoundingClientRect();
      guide.classList.add('guide-ready');
      guideToggle.addEventListener('click', () => {
        document.dispatchEvent(new Event('dashboard-panel-change'));
        setGuideExpanded(guideToggle.getAttribute('aria-expanded') !== 'true');
      });
      const finishGuide = () => guide.getAnimations({ subtree: true }).forEach(animation => animation.finish());
      document.addEventListener('dashboard-prepare-print', finishGuide);
      window.addEventListener('beforeprint', finishGuide);
      const shell = document.querySelector('.dashboard-tabs');
      const plots = Array.from(document.querySelectorAll('.chart-container .js-plotly-plot'));
      const reportLabels = new Map(Array.from(shell.querySelectorAll('[data-tab-panel]'),
        panel => [panel, panel.getAttribute('aria-labelledby')]));
      let initialized = false;
      const initialize = () => {
        if (initialized || !plots.every(plot => plot.dataset.pdfReady === 'true')) return;
        initialized = true;
        const groups = new Map();
        let revision = 0;
        let animations = [];
        let pending = Promise.resolve();
        let historyFrame;
        const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
        const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
        const finish = () => {
          revision++;
          animations.forEach(animation => animation.cancel());
          animations = [];
          groups.forEach(group => { group.host.style.height = ''; });
          reportLabels.forEach((_, panel) => { panel.style.opacity = ''; });
          shell.style.minHeight = '';
        };
        const resizeVisible = () => Promise.all(plots.filter(plot => plot.getClientRects().length)
          .map(plot => Plotly.Plots.resize(plot).catch(() => {})));
        const select = panel => {
          const group = groups.get(panel.dataset.tabPanel);
          group.panels.forEach((item, index) => {
            const selected = item === panel;
            item.hidden = !selected;
            group.links[index].setAttribute('aria-selected', String(selected));
            group.links[index].tabIndex = selected ? 0 : -1;
          });
        };
        const ancestors = target => {
          const panels = [];
          let panel = target.closest('[data-tab-panel]');
          while (panel) {
            panels.unshift(panel);
            panel = panel.parentElement.closest('[data-tab-panel]');
          }
          return panels;
        };
        const scrollSmoothly = async (top, token, animate) => {
          const from = scrollY;
          const destination = Math.max(0, top);
          if (!animate || reducedMotion() || Math.abs(destination - from) < 1) {
            if (token === revision) window.scrollTo({ top: destination, behavior: 'instant' });
            return;
          }
          const start = performance.now();
          while (token === revision) {
            const elapsed = Math.min(1, (performance.now() - start) / 220);
            window.scrollTo({ top: from + (destination - from) * (1 - (1 - elapsed) ** 3), behavior: 'instant' });
            if (elapsed >= 1) break;
            await frame();
          }
        };
        const animateSelection = async (target, options = {}) => {
          const sizes = new Map(Array.from(groups.values(), group => [group, group.host.getBoundingClientRect().height]));
          // Retain document space before cancelling a previous, partially finished switch.
          const reserve = Math.max(shell.getBoundingClientRect().height,
            scrollY + innerHeight - (shell.getBoundingClientRect().top + scrollY));
          finish();
          const token = revision;
          shell.style.minHeight = reserve + 'px';
          groups.forEach(group => {
            if (sizes.get(group)) group.host.style.height = sizes.get(group) + 'px';
          });
          document.dispatchEvent(new Event('dashboard-panel-change'));
          const panels = ancestors(target);
          panels.forEach(select);
          const panel = panels[panels.length - 1];
          if (!panel) { finish(); return; }
          const animate = options.animate !== false && !reducedMotion();
          if (animate) panel.style.opacity = '0';
          await frame();
          if (token !== revision) return;
          await resizeVisible();
          if (token !== revision) return;
          // Measure nested groups first so parent height includes the final chart sizes.
          const visible = Array.from(groups.values()).filter(group => group.host.getClientRects().length).reverse();
          const targets = new Map();
          visible.forEach(group => {
            group.host.style.height = '';
            targets.set(group, group.host.getBoundingClientRect().height);
          });
          visible.forEach(group => { group.host.style.height = (sizes.get(group) || targets.get(group)) + 'px'; });
          const group = groups.get(panel.dataset.tabPanel);
          const barBottom = group.list.getBoundingClientRect().bottom;
          const rect = target.getBoundingClientRect();
          // Normal switches never scroll. Only retrieve content above a sticky bar,
          // or deliberately navigate to a deep-link/drilldown target.
          if (options.scroll || rect.top < barBottom - 1) {
            const offset = Number.parseFloat(getComputedStyle(target).scrollMarginTop) || barBottom + 12;
            const top = options.scroll ? scrollY + rect.top - offset : scrollY + panel.getBoundingClientRect().top - barBottom - 12;
            // Scroll and fade together while the outgoing height still guards against clamping.
            const scrolling = scrollSmoothly(top, token, animate);
            if (animate) {
              panel.style.opacity = '';
              const fade = panel.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: 'ease-out' });
              animations.push(fade);
            }
            await scrolling;
          }
          if (token !== revision) return;
          panel.style.opacity = '';
          if (animate) {
            if (!animations.length) animations.push(panel.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: 'ease-out' }));
            visible.forEach(item => {
              const from = sizes.get(item) || targets.get(item);
              item.host.style.height = targets.get(item) + 'px';
              if (Math.abs(from - targets.get(item)) > 1) animations.push(item.host.animate(
                [{ height: from + 'px' }, { height: targets.get(item) + 'px' }],
                { duration: 220, easing: 'cubic-bezier(0.2, 0, 0, 1)' }
              ));
            });
            await Promise.all(animations.map(animation => animation.finished.catch(() => {})));
          }
          if (token !== revision) return;
          groups.forEach(item => { item.host.style.height = ''; });
          // A short panel may no longer support the current scroll position.
          // Measure its final document height, then settle before releasing space.
          const currentY = scrollY;
          const reservation = shell.style.minHeight;
          shell.style.minHeight = '';
          const finalMaxY = Math.max(0, document.documentElement.scrollHeight - innerHeight);
          shell.style.minHeight = reservation;
          window.scrollTo({top: currentY, behavior: 'instant'});
          if (currentY > finalMaxY) await scrollSmoothly(finalMaxY, token, animate);
          if (token !== revision) return;
          shell.style.minHeight = '';
          animations = [];
          if (options.focus) {
            target.tabIndex = -1;
            target.focus({ preventScroll: true });
          }
        };
        const activate = (target, options) => {
          pending = animateSelection(target, options).catch(() => { finish(); });
          return pending;
        };
        const targetForHash = () => {
          try { return document.getElementById(decodeURIComponent(location.hash.slice(1))); }
          catch (_) { return null; }
        };
        const showHorizontalTab = (group, link) => {
          const listRect = group.list.getBoundingClientRect();
          const rect = link.getBoundingClientRect();
          const delta = rect.left < listRect.left ? rect.left - listRect.left :
            rect.right > listRect.right ? rect.right - listRect.right : 0;
          if (delta) group.list.scrollTo({ left: group.list.scrollLeft + delta, behavior: reducedMotion() ? 'instant' : 'smooth' });
        };
        try {
          shell.querySelectorAll('[data-tab-list]').forEach(list => {
            const key = list.dataset.tabList;
            const links = Array.from(list.querySelectorAll('a'));
            const panels = links.map(link => document.getElementById(link.hash.slice(1)));
            const host = document.createElement('div');
            host.className = 'tab-panels';
            host.dataset.panelHost = key;
            list.after(host);
            panels.forEach(panel => host.append(panel));
            groups.set(key, { list, links, panels, host });
            list.setAttribute('role', 'tablist');
            links.forEach((link, index) => {
              link.setAttribute('role', 'tab');
              link.setAttribute('aria-controls', panels[index].id);
              panels[index].setAttribute('role', 'tabpanel');
              panels[index].setAttribute('aria-labelledby', link.id);
              panels[index].tabIndex = 0;
            });
          });
          groups.forEach(group => {
            select(group.panels[0]);
            group.list.addEventListener('click', event => {
              const link = event.target.closest('a');
              if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              const panel = document.getElementById(link.hash.slice(1));
              if (link.getAttribute('aria-selected') === 'true') return;
              link.focus({ preventScroll: true });
              activate(panel);
              const nested = panel.querySelector('[data-tab-panel]:not([hidden])');
              const hash = '#' + (nested || panel).id;
              if (location.hash !== hash) history.pushState(null, '', hash);
              showHorizontalTab(group, link);
            });
            group.list.addEventListener('keydown', event => {
              const index = group.links.indexOf(document.activeElement);
              if (index < 0) return;
              let next;
              if (event.key === 'ArrowRight') next = (index + 1) % group.links.length;
              else if (event.key === 'ArrowLeft') next = (index - 1 + group.links.length) % group.links.length;
              else if (event.key === 'Home') next = 0;
              else if (event.key === 'End') next = group.links.length - 1;
              else if (event.key === ' ' || event.key === 'Enter') {
                event.preventDefault(); group.links[index].click(); return;
              } else return;
              event.preventDefault();
              group.links[next].focus({ preventScroll: true });
              showHorizontalTab(group, group.links[next]);
            });
          });
          document.addEventListener('click', event => {
            if (!document.body.classList.contains('tabs-ready')) return;
            const link = event.target.closest('a[href^="#"]');
            if (!link || event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            let target;
            try { target = document.getElementById(decodeURIComponent(link.hash.slice(1))); }
            catch (_) { return; }
            if (!target || !target.closest('[data-tab-panel]')) return;
            event.preventDefault();
            activate(target, { scroll: true, focus: true });
            if (location.hash !== link.hash) history.pushState(null, '', link.hash);
          });
          const navigateHistory = () => {
            cancelAnimationFrame(historyFrame);
            historyFrame = requestAnimationFrame(() => {
              if (!document.body.classList.contains('tabs-ready')) return;
              const target = targetForHash();
              if (target && target.closest('[data-tab-panel]')) activate(target, { scroll: true });
              else if (!location.hash) {
                groups.forEach(group => select(group.panels[0]));
                activate(groups.get('sections').panels[0]);
              }
            });
          };
          window.addEventListener('popstate', navigateHistory);
          window.addEventListener('hashchange', navigateHistory);
          const primary = groups.get('sections').list;
          const measure = () => shell.style.setProperty('--primary-tabs-height', primary.offsetHeight + 'px');
          document.body.classList.add('tabs-ready');
          measure();
          new ResizeObserver(() => { measure(); resizeVisible(); }).observe(primary);
          // History alignment is handled here, without a competing browser jump.
          history.scrollRestoration = 'manual';
          // User scrolling takes precedence over an automatic alignment in progress.
          window.addEventListener('wheel', finish, { passive: true });
          window.addEventListener('touchmove', finish, { passive: true });
          document.addEventListener('keydown', event => {
            if (!event.defaultPrevented && ['PageDown', 'PageUp', 'ArrowDown', 'ArrowUp', 'Home', 'End', ' '].includes(event.key)
                && !event.target.closest('[data-tab-list]')) finish();
          });
          window.addEventListener('resize', () => { finish(); resizeVisible(); });
          guideToggle.addEventListener('click', finish);
          matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', finish);
          document.addEventListener('dashboard-prepare-print', event => {
            finish();
            event.detail.pending.push(resizeVisible());
          });
          window.addEventListener('beforeprint', finish);
          window.addEventListener('afterprint', () => { finish(); resizeVisible(); });
          const target = targetForHash();
          if (target && target.closest('[data-tab-panel]')) activate(target, { scroll: true, animate: false });
          else resizeVisible();
          document.removeEventListener('dashboard-chart-ready', initialize);
        } catch (_) {
          finish();
          document.body.classList.remove('tabs-ready');
          reportLabels.forEach((label, panel) => {
            panel.hidden = false;
            panel.removeAttribute('role');
            panel.removeAttribute('tabindex');
            if (label) panel.setAttribute('aria-labelledby', label);
            else panel.removeAttribute('aria-labelledby');
          });
          document.removeEventListener('dashboard-chart-ready', initialize);
        }
      };
      document.addEventListener('dashboard-chart-ready', initialize);
      initialize();
    })();
  </script>
"""
