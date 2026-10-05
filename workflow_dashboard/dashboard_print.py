"""Offline, on-demand printing support for the standalone dashboard."""

from . import dashboard_content as content


PRINT_STYLES = """
    .pdf-export { display: grid; gap: 5px; justify-items: end; }
    .pdf-export button {
      background: var(--primary); border: 1px solid var(--primary-dark);
      border-radius: 7px; color: white; cursor: pointer; font: inherit;
      font-size: 14px; font-weight: 600; padding: 9px 16px;
    }
    .pdf-export button:hover:not(:disabled) { background: var(--primary-dark); }
    .pdf-export button:focus-visible { outline: 3px solid var(--primary); outline-offset: 3px; }
    .pdf-export button:disabled { cursor: wait; opacity: 0.65; }
    .pdf-export p { font-size: 12px; margin: 0; }
    .pdf-export-status:empty { display: none; }
    .pdf-chart { display: none; }
    @page { size: letter landscape; margin: 10mm; }
    @media print {
      html, body { background: white; overflow: visible; }
      body { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      .dashboard-shell { max-width: none; padding: 0; }
      .dashboard-header, .legend-card, .kpi, .chart-container, .table-container {
        box-shadow: none; background: white; border-radius: 0;
      }
      .dashboard-header { padding: 5mm; }
      .header-top { flex-direction: row; }
      .header-meta { align-items: flex-end; text-align: right; }
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
      .current-open-grid, .trend-grid, .chart-stack { display: block; }
      .chart-container { break-inside: avoid; margin: 0 0 5mm !important; padding: 4mm; }
      .chart-container-wide .card-heading { position: static; }
      .chart-container-wide .js-plotly-plot { min-width: 0; max-width: 100%; }
      .pdf-prepared .chart-container .js-plotly-plot { display: none; }
      .pdf-prepared .pdf-chart {
        display: block; width: 100%; height: auto; max-height: 130mm;
        object-fit: contain; break-inside: avoid; break-before: avoid;
      }
      .chart-container, .table-container, .current-open-grid .chart-container-wide,
      .table-scroll, .action-drilldown-scroll {
        overflow: visible; max-height: none; min-width: 0;
      }
      .table-container, .action-matrix-card { break-inside: auto; }
      .action-matrix-coverage { break-after: avoid; }
      .table-container { padding: 4mm; }
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
      #problem-rows-table th:nth-child(1) { width: 14%; }
      #problem-rows-table th:nth-child(2) { width: 9%; }
      #problem-rows-table th:nth-child(3) { width: 14%; }
      #problem-rows-table th:nth-child(4) { width: 17%; }
      #problem-rows-table th:nth-child(5) { width: 7%; }
      #problem-rows-table th:nth-child(6) { width: 9%; }
      #problem-rows-table th:nth-child(7) { width: 5%; }
      #problem-rows-table th:nth-child(8) { width: 7%; }
      #problem-rows-table th:nth-child(9), #problem-rows-table th:nth-child(10) { width: 9%; }
      .action-drilldown-table th:nth-child(1) { width: 17%; }
      .action-drilldown-table th:nth-child(2) { width: 35%; }
      .action-drilldown-table th:nth-child(3) { width: 10%; }
      .action-drilldown-table th:nth-child(4) { width: 15%; }
      .action-drilldown-table th:nth-child(5) { width: 23%; }
      thead { display: table-header-group; }
      tr { break-inside: avoid; }
      .table-card-header { break-after: avoid; }
      .pdf-export, .help-control, .modebar, .hoverlayer, .action-matrix-controls,
      .action-drilldown-clear, .jump-to-top, .kpi-link { display: none !important; }
      .action-matrix-drilldown[hidden] { display: none; }
      .page-footer { display: none; }
    }
"""


def export_script(json_for_script) -> str:
    """Keep status copy escaped exactly like other inline dashboard scripts."""
    messages = json_for_script({
        "preparing": content.PAGE.preparing_pdf,
        "error": content.PAGE.pdf_error,
    })
    return """
    <script>
      (() => {
        const button = document.getElementById("save-pdf");
        const status = document.getElementById("pdf-export-status");
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
          status.textContent = "";
        };
        window.addEventListener("afterprint", () => {
          if (document.body.classList.contains("pdf-prepared")) restore();
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
          status.textContent = messages.preparing;
          try {
            const plots = Array.from(document.querySelectorAll(".chart-container .js-plotly-plot"));
            await waitForCharts(plots);
            await document.fonts.ready;
            for (const plot of plots) {
              const image = new Image();
              image.className = "pdf-chart";
              image.alt = plot.closest(".chart-container").getAttribute("aria-label") || "";
              image.src = await Plotly.toImage(plot, {
                format: "svg", width: 1000, height: plot._fullLayout.height,
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
            status.textContent = messages.error;
          }
        });
      })();
    </script>
    """.replace("MESSAGES", messages)
