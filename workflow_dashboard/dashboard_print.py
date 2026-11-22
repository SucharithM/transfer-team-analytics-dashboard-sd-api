"""Offline, on-demand printing support for the standalone dashboard."""

from . import dashboard_content as content


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
        const yearButtons = document.querySelectorAll('[data-trend-year]');
        const messages = MESSAGES;
        let busy = false;
        let snapshots = [];

        const restore = () => {
          document.body.classList.remove("pdf-prepared");
          snapshots.forEach(image => image.remove());
          snapshots = [];
          busy = false;
          button.disabled = false;
          yearButtons.forEach(item => { item.disabled = false; });
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
          yearButtons.forEach(item => { item.disabled = true; });
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
