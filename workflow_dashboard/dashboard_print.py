"""Offline, on-demand printing support for the standalone dashboard."""

from . import dashboard_content as content

PRINT_STYLES = """
    .pdf-export { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
    .pdf-export-control { position: relative; flex: 0 0 auto; }
    .pdf-export button {
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      width: 144px; min-height: 40px; padding: 8px 12px;
      background: var(--surface); border: 1px solid var(--border-strong);
      border-radius: 8px; color: var(--text); cursor: pointer; font: inherit;
      font-size: 13px; font-weight: 600; line-height: 1.3;
    }
    .pdf-export button:hover:not(:disabled) { background: var(--surface-muted); }
    .pdf-export button:focus-visible { outline: 3px solid var(--primary); outline-offset: 3px; }
    .pdf-export button:disabled { cursor: wait; color: var(--muted); }
    .pdf-printer-icon { flex: 0 0 auto; }
    .pdf-spinner {
      display: none; width: 16px; height: 16px; flex: 0 0 auto;
      border: 2px solid var(--border-strong); border-top-color: currentColor;
      border-radius: 50%; animation: pdf-spin 1s linear infinite;
    }
    .pdf-export.is-preparing .pdf-printer-icon { display: none; }
    .pdf-export.is-preparing .pdf-spinner { display: inline-block; }
    @keyframes pdf-spin { to { transform: rotate(360deg); } }
    .pdf-export-hint {
      position: absolute; right: 0; bottom: calc(100% + 8px); z-index: 25;
      width: 280px; max-width: calc(100vw - 72px); padding: 10px 12px;
      background: var(--text); color: var(--surface); border-radius: 8px;
      font-size: 13px; line-height: 1.4; text-align: left;
      visibility: hidden; opacity: 0;
    }
    .pdf-export-hint::after { content: ""; position: absolute; top: 100%; left: 0; right: 0; height: 8px; }
    .pdf-export-control:not(.tooltip-dismissed):hover .pdf-export-hint,
    .pdf-export-control:not(.tooltip-dismissed):focus-within .pdf-export-hint {
      visibility: visible; opacity: 1;
    }
    .pdf-export.is-preparing .pdf-export-hint { visibility: hidden; opacity: 0; }
    .dashboard-header .pdf-export-status { font-size: 13px; line-height: 1.4; margin: 0; max-width: 330px; }
    .pdf-export-status:not(.is-error) {
      position: absolute; width: 1px; height: 1px; overflow: hidden;
      clip-path: inset(50%); white-space: nowrap;
    }
    .dashboard-header .pdf-export-status.is-error { color: #a32d38; }
    .pdf-export-status:empty { display: none; }
    .pdf-chart { display: none; }
    @media (pointer: coarse) { .pdf-export button { min-height: 44px; } }
    @media (prefers-reduced-motion: reduce) { .pdf-spinner { animation: none; } }
    @page { size: letter landscape; margin: 10mm; }
    @media print {
      html, body { background: white; overflow: visible; }
      body { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      .dashboard-shell { max-width: none; padding: 0; }
      .tabs-ready .dashboard-tabbar { display: none; }
      .tabs-ready [data-tab-panel][hidden] { display: block !important; }
      .dashboard-tabs { margin-top: 0; }
      .tabs-ready .dashboard-tabs, .tabs-ready [data-tab-panel="sections"] { min-height: 0 !important; }
      .tab-panels { height: auto !important; min-height: 0 !important; }
      [data-tab-panel] { opacity: 1 !important; }
      .dashboard-tabs [data-tab-panel] { scroll-margin-top: 0; }
      .dashboard-header, .legend-card, .kpi, .chart-container, .table-container {
        box-shadow: none; background: white; border-radius: 0;
      }
      .dashboard-header { padding: 5mm; }
      .header-top { flex-direction: row; }
      h1 { font-size: 24px; }
      .dashboard-section { margin-top: 6mm; }
      .dashboard-section:not(.workflow-legend) { break-before: page; }
      .section-heading, .card-heading, .action-drilldown-heading {
        break-inside: avoid; break-after: avoid;
      }
      .section-title { font-size: 20px; }
      .legend-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .kpi { min-height: 0; break-inside: avoid; }
      .current-open-grid, .trend-grid, .chart-stack, .case-metrics-grid, .aging-grid { display: block; }
      .dashboard-tabs .chart-container { break-inside: avoid; margin: 0 0 5mm !important; padding: 4mm; }
      .chart-container-wide .card-heading { position: static; }
      .chart-container-wide .js-plotly-plot { min-width: 0; max-width: 100%; }
      .pdf-prepared .chart-container .js-plotly-plot { display: none; }
      .pdf-prepared .pdf-chart {
        display: block; width: 100%; height: auto; max-height: 130mm;
        object-fit: contain; break-inside: avoid; break-before: avoid;
      }
      .chart-container, .table-container, .current-open-grid .chart-container-wide,
      .aging-grid .chart-container-wide,
      .table-scroll, .action-drilldown-scroll {
        overflow: visible; max-height: none; min-width: 0;
      }
      .table-container, .action-matrix-card { break-inside: auto; }
      .action-matrix-coverage { break-after: avoid; }
      .dashboard-tabs .table-container { padding: 4mm; }
      #problem-rows-table .table-scroll { max-height: none; overflow: visible; }
      .data-table, .evaluation-type-table, .action-drilldown-table {
        min-width: 0; width: 100%; table-layout: fixed;
        border-collapse: collapse; font-size: 9pt;
      }
      .data-table th, .data-table td, .evaluation-type-table th,
      .evaluation-type-table td, .evaluation-type-name, .metric-cell {
        min-width: 0; white-space: normal; overflow-wrap: anywhere;
        padding: 5px; font-size: 9pt; position: static;
      }
      .metric-cell strong { font-size: 9pt; }
      #problem-rows-table .observation-table { width: 100%; min-width: 0; }
      .observation-table col { width: var(--print-width); }
      #problem-rows-table th {
        white-space: normal; word-break: normal; overflow-wrap: normal;
      }
      #problem-rows-table th[data-field="status"],
      #problem-rows-table th[data-field="owner"] { white-space: nowrap; }
      #problem-rows-table .observation-chip { font-size: 9pt; padding: 3px 4px; }
      #problem-rows-table .observation-chip:not(.workflow-chip) { display: inline-block; }
      #problem-rows-table .observation-chip svg { vertical-align: text-bottom; margin-right: 4px; }
      .action-drilldown-table th:nth-child(1) { width: 17%; }
      .action-drilldown-table th:nth-child(2) { width: 35%; }
      .action-drilldown-table th:nth-child(3) { width: 10%; }
      .action-drilldown-table th:nth-child(4) { width: 15%; }
      .action-drilldown-table th:nth-child(5) { width: 23%; }
      thead { display: table-header-group; }
      tr { break-inside: avoid; }
      .table-card-header { break-after: avoid; }
      .pdf-export, .help-control, .modebar, .hoverlayer,
      .action-drilldown-clear, .jump-to-top, .kpi-link { display: none !important; }
      .action-matrix-drilldown[hidden] { display: none; }
      .donut-layout { grid-template-columns: 360px minmax(0, 1fr); gap: 16px; }
      .donut-plot { width: 100%; }
      .chart-category-list { break-inside: avoid; }
      .category-toggle { color: #172033; font-size: 10pt; padding: 5px; }
      .risk-plot-scroll { overflow: visible; }
      .donut-plot > div, .risk-plot-scroll > div { height: auto !important; }
      .risk-chart-frame { display: inline-block; width: 100%; break-inside: avoid; }
      .risk-chart-frame .pdf-chart { max-height: 110mm; }
      .action-matrix-controls { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .page-footer { display: none; }
    }
"""


def export_script(json_for_script) -> str:
    """Keep status copy escaped exactly like other inline dashboard scripts."""
    messages = json_for_script(
        {
            "ready": content.PAGE.save_pdf,
            "preparing": content.PAGE.preparing_pdf,
            "error": content.PAGE.pdf_error,
        }
    )
    return """
    <script>
      (() => {
        const button = document.getElementById("save-pdf");
        const status = document.getElementById("pdf-export-status");
        const label = button.querySelector(".pdf-button-label");
        const exportControl = button.closest(".pdf-export");
        const messages = MESSAGES;
        let busy = false;
        let snapshots = [];

        const restore = () => {
          document.body.classList.remove("pdf-prepared");
          snapshots.forEach(image => image.remove());
          snapshots = [];
          busy = false;
          button.disabled = false;
          button.removeAttribute("aria-busy");
          exportControl.classList.remove("is-preparing");
          label.textContent = messages.ready;
          status.classList.remove("is-error");
          status.textContent = "";
        };
        window.addEventListener("afterprint", () => {
          if (document.body.classList.contains("pdf-prepared")) {
            restore();
            button.focus({ preventScroll: true });
          }
        });

        const waitForCharts = plots => new Promise((resolve, reject) => {
          const ready = () => plots.every(plot => plot.dataset.pdfReady === "true");
          if (ready()) { resolve(); return; }
          const check = () => {
            if (ready()) { cleanup(); resolve(); }
          };
          const timer = window.setTimeout(() => {
            cleanup(); reject(new Error("Charts not ready"));
          }, 30000);
          const cleanup = () => {
            window.clearTimeout(timer);
            document.removeEventListener("dashboard-chart-ready", check);
          };
          document.addEventListener("dashboard-chart-ready", check);
        });

        button.addEventListener("click", async () => {
          if (busy) return;
          busy = true;
          button.disabled = true;
          button.setAttribute("aria-busy", "true");
          exportControl.classList.add("is-preparing");
          label.textContent = messages.preparing;
          status.classList.remove("is-error");
          status.textContent = messages.preparing;
          try {
            const preparation = { pending: [] };
            document.dispatchEvent(new CustomEvent('dashboard-prepare-print', { detail: preparation }));
            await Promise.all(preparation.pending);
            const plots = Array.from(document.querySelectorAll(".chart-container .js-plotly-plot"));
            await waitForCharts(plots);
            await document.fonts.ready;
            for (const plot of plots) {
              const image = new Image();
              image.className = "pdf-chart";
              image.alt = plot.closest(".chart-container").getAttribute("aria-label") || "";
              image.src = await Plotly.toImage(plot, {
                format: "svg", width: plot.closest(".donut-plot") ? 420 : 1000, height: plot._fullLayout.height,
              });
              await image.decode();
              snapshots.push(image);
              plot.after(image);
            }
            document.body.classList.add("pdf-prepared");
            status.textContent = "";
            window.print();
          } catch (error) {
            restore();
            status.classList.add("is-error");
            status.textContent = messages.error;
            button.focus({ preventScroll: true });
          }
        });
      })();
    </script>
    """.replace("MESSAGES", messages)
