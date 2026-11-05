"""Viewport-aware help shared by report cards and the print action."""

TOOLTIP_STYLES = """
    #dashboard-tooltip-layer { position: fixed; inset: 0; z-index: 1000; pointer-events: none; }
    #dashboard-tooltip-layer .floating-tooltip {
      position: fixed; inset: auto; min-width: 0; max-width: calc(100vw - 24px);
      box-sizing: border-box; overflow: auto; overflow-wrap: anywhere;
      overscroll-behavior: contain; white-space: normal; transform: none;
      opacity: 0; visibility: hidden; pointer-events: none;
      transition: opacity 120ms ease, visibility 120ms ease;
    }
    #dashboard-tooltip-layer .floating-tooltip.is-open {
      opacity: 1; visibility: visible; pointer-events: auto;
    }
    .tooltips-ready .pdf-export-hint::after { display: none; }
    @media (prefers-reduced-motion: reduce) {
      #dashboard-tooltip-layer .floating-tooltip { transition: none; }
    }
    @media print { #dashboard-tooltip-layer { display: none !important; } }
"""


TOOLTIP_SCRIPT = """
  <script>
    (() => {
      const layer = document.createElement('div');
      layer.id = 'dashboard-tooltip-layer';
      document.body.append(layer);
      let active = null;
      let showTimer, hideTimer, positionFrame;
      const hide = () => {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        if (active) active.tip.classList.remove('is-open');
        active = null;
      };
      const position = () => {
        if (!active) return;
        const { trigger, tip, width } = active;
        const scrollTop = tip.scrollTop;
        const viewport = window.visualViewport;
        const leftEdge = (viewport ? viewport.offsetLeft : 0) + 12;
        const topEdge = (viewport ? viewport.offsetTop : 0) + 12;
        const rightEdge = leftEdge + (viewport ? viewport.width : innerWidth) - 24;
        const bottomEdge = topEdge + (viewport ? viewport.height : innerHeight) - 24;
        const rect = trigger.getBoundingClientRect();
        if (trigger.disabled || !trigger.getClientRects().length ||
            rect.bottom <= topEdge - 12 || rect.top >= bottomEdge + 12 ||
            rect.right <= leftEdge - 12 || rect.left >= rightEdge + 12) {
          hide(); return;
        }
        tip.style.width = Math.max(0, Math.min(width, rightEdge - leftEdge)) + 'px';
        tip.style.maxHeight = Math.max(0, bottomEdge - topEdge) + 'px';
        const height = tip.getBoundingClientRect().height;
        const below = bottomEdge - rect.bottom - 8;
        const above = rect.top - topEdge - 8;
        const useBelow = height <= below || (height > above && below >= above);
        tip.dataset.placement = useBelow ? 'bottom' : 'top';
        tip.style.maxHeight = Math.max(0, useBelow ? below : above) + 'px';
        const size = tip.getBoundingClientRect();
        tip.style.left = Math.max(leftEdge, Math.min(rect.left, rightEdge - size.width)) + 'px';
        tip.style.top = Math.max(topEdge, Math.min(
          useBelow ? rect.bottom + 8 : rect.top - 8 - size.height,
          bottomEdge - size.height
        )) + 'px';
        tip.tabIndex = tip.scrollHeight > tip.clientHeight + 1 ? 0 : -1;
        tip.scrollTop = scrollTop;
      };
      const schedulePosition = () => {
        cancelAnimationFrame(positionFrame);
        positionFrame = requestAnimationFrame(position);
      };
      const engaged = record => record.trigger.matches(':hover') || record.tip.matches(':hover') ||
        document.activeElement === record.trigger || record.tip.contains(document.activeElement);
      const open = record => {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        if (record.dismissed || record.trigger.disabled) return;
        if (active !== record) hide();
        active = record;
        position();
        if (active === record) record.tip.classList.add('is-open');
      };
      const scheduleHide = record => {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        hideTimer = setTimeout(() => {
          if (!engaged(record)) {
            record.dismissed = false;
            if (active === record) hide();
          }
        }, 100);
      };
      document.querySelectorAll('.info-button, #save-pdf').forEach(trigger => {
        const tip = document.getElementById(trigger.getAttribute('aria-describedby'));
        if (!tip) return;
        const record = { trigger, tip, width: trigger.id === 'save-pdf' ? 280 : 360,
          dismissed: false, touch: false, touchWasOpen: false };
        tip.classList.add('floating-tooltip');
        layer.append(tip); // Keep the original ID and aria-describedby relationship.
        trigger.addEventListener('pointerenter', event => {
          if (event.pointerType === 'touch') return;
          clearTimeout(hideTimer);
          clearTimeout(showTimer);
          showTimer = setTimeout(() => open(record), 150);
        });
        trigger.addEventListener('pointerleave', () => {
          if (document.activeElement !== trigger) record.dismissed = false;
          scheduleHide(record);
        });
        trigger.addEventListener('focus', () => {
          if (!record.touch) open(record);
        });
        trigger.addEventListener('blur', () => {
          if (!trigger.matches(':hover')) record.dismissed = false;
          scheduleHide(record);
        });
        trigger.addEventListener('pointerdown', event => {
          record.touch = event.pointerType === 'touch';
          record.touchWasOpen = active === record;
        });
        trigger.addEventListener('click', () => {
          if (!record.touch) return;
          record.touch = false;
          if (record.touchWasOpen) { record.dismissed = true; hide(); }
          else { record.dismissed = false; open(record); }
        });
        tip.addEventListener('pointerenter', () => clearTimeout(hideTimer));
        tip.addEventListener('pointerleave', () => scheduleHide(record));
        tip.addEventListener('focusin', () => clearTimeout(hideTimer));
        tip.addEventListener('focusout', () => scheduleHide(record));
      });
      document.body.classList.add('tooltips-ready');
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
          if (active) active.dismissed = true;
          hide();
        }
      });
      document.addEventListener('pointerdown', event => {
        if (active && !active.trigger.contains(event.target) && !active.tip.contains(event.target)) hide();
      }, true);
      document.addEventListener('scroll', event => {
        if (!active || !active.tip.contains(event.target)) schedulePosition();
      }, true);
      window.addEventListener('resize', schedulePosition);
      if (window.visualViewport) {
        visualViewport.addEventListener('resize', schedulePosition);
        visualViewport.addEventListener('scroll', schedulePosition);
      }
      document.fonts.ready.then(schedulePosition);
      document.addEventListener('dashboard-panel-change', hide);
      document.addEventListener('dashboard-prepare-print', hide);
      window.addEventListener('beforeprint', hide);
      new MutationObserver(() => {
        if (active && active.trigger.disabled) hide();
      }).observe(document.getElementById('save-pdf'), { attributes: true, attributeFilter: ['disabled'] });
    })();
  </script>
"""
