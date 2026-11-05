"""Keep window startup independent of the browser and reporting stack."""
import subprocess
import sys
from pathlib import Path


def test_desktop_startup_defers_browser_and_reporting_imports():
    subprocess.run(
        [sys.executable, "-c", """
import sys
from pathlib import Path
from workflow_dashboard import desktop

desktop.desktop_config(Path(desktop.__file__).with_name("desktop_settings.toml.example"))
session = desktop.DiagnosticSession("msedge")
session.begin(0)
session.finish(0, "success")
heavy = {"pandas", "numpy", "plotly", "openpyxl", "requests", "playwright"}
assert not heavy.intersection(sys.modules), heavy.intersection(sys.modules)
"""],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )
