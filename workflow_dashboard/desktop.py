"""Small manager-facing desktop launcher; the UI never receives credentials."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tomllib
import webbrowser
from dataclasses import replace
from enum import Enum
from pathlib import Path

from .browser_auth import BrowserAuthError, browser_fetch
from .config import DashboardConfig, is_secure_api_url
from .desktop_preferences import (
    initial_output_directory,
    load_output_directory,
    save_output_directory,
    validate_output_directory,
)
from .generation import generate_dashboard
from .normalization import WorkflowPopulationError


def application_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "WorkflowTransferDashboard"


def desktop_config(settings_path: Path | None = None) -> DashboardConfig:
    root = application_directory()
    local_settings = root / "settings.toml"
    settings = settings_path or (local_settings if local_settings.exists() else Path(__file__).with_name("desktop_settings.toml"))
    with settings.open("rb") as file:
        values = tomllib.load(file)
    data_directory = values.pop("data_directory", None)
    if data_directory is not None:
        if not isinstance(data_directory, str) or not Path(data_directory).is_absolute():
            raise ValueError("The local data directory must be an absolute path")
        root = Path(data_directory)
    allowed = {"api_url", "dashboard_title", "workflow_filter", "api_take", "status_filters", "team_members",
               "backlog_age_days", "stale_idle_days", "old_age_days", "request_timeout_seconds",
               "minimum_wait_completeness", "minimum_idle_completeness", "minimum_completion_completeness"}
    if set(values) - allowed:
        raise ValueError("Settings contain unsupported fields. Use only the fields in desktop_settings.toml.")
    for name in ("team_members", "status_filters"):
        if name in values:
            if not isinstance(values[name], list) or not all(isinstance(v, str) for v in values[name]):
                raise ValueError(f"{name} must be a list of names")
            values[name] = tuple(values[name])
    for name in ("api_take", "request_timeout_seconds", "stale_idle_days", "old_age_days"):
        if name in values and (type(values[name]) is not int or values[name] < 1):
            raise ValueError(f"{name} must be a positive integer")
    for name in ("dashboard_title", "workflow_filter"):
        if name in values and (not isinstance(values[name], str) or not values[name].strip()):
            raise ValueError(f"{name} must be nonempty text")
    if not values.get("workflow_filter"):
        raise ValueError("Desktop settings must identify one workflow")
    if "api_url" in values and not is_secure_api_url(values["api_url"]):
        raise ValueError("Settings must use an HTTPS API endpoint without credentials, query parameters, or fragments")
    return DashboardConfig(**values, output_dir=root / "outputs", history_db_path=root / "history" / "workflow_history.sqlite",
                           headers={"Accept": "application/json", "User-Agent": "workflow-operations-dashboard/0.1"})


def fetch_and_generate(config, *, channel="msedge", cancel=None, progress=None):
    """Rendering cannot start until browser_fetch has reaped its credential worker."""
    fetched = browser_fetch(config, channel=channel, cancel=cancel, progress=progress)
    if cancel is not None and cancel.is_set():
        raise BrowserAuthError("cancelled")
    if progress is not None:
        progress("generating")
    return generate_dashboard(replace(config, api_token=None), fetched["records"], fetched["fetch"], source="api")


class DesktopState(Enum):
    READY = "ready"
    CHOOSING = "choosing"
    CHECKING = "checking"
    SIGNIN = "signin"
    FETCHING = "fetching"
    GENERATING = "generating"
    CANCELLING = "cancelling"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


ACTIVE_STATES = {
    DesktopState.CHOOSING, DesktopState.CHECKING, DesktopState.SIGNIN,
    DesktopState.FETCHING, DesktopState.GENERATING, DesktopState.CANCELLING,
}
STAGE_STATES = {
    "signin": DesktopState.SIGNIN,
    "fetching": DesktopState.FETCHING,
    "generating": DesktopState.GENERATING,
}
STAGE_MESSAGES = {
    DesktopState.SIGNIN: (
        "Complete Microsoft sign-in and MFA in the browser window.\n"
        "If sign-in is finished, open your eTrieve workflow dashboard there."
    ),
    DesktopState.FETCHING: "Fetching and checking workflow records. You can stay in this window.",
    DesktopState.GENERATING: "Creating dashboard files…",
}


class DesktopApp:
    """Tk stays on the main thread; workers deliver only safe, run-scoped events."""

    def __init__(self, root, config, *, channel="msedge"):
        import tkinter as tk
        from tkinter import filedialog, ttk

        self.root, self.config, self.channel = root, config, channel
        self.filedialog = filedialog
        self.preferences_file = config.history_db_path.parent.parent / "preferences.json"
        self.destination = load_output_directory(self.preferences_file)
        self.last_result = None
        self.state = DesktopState.READY
        self.closing = False
        self.run_id = 0
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.rendering = threading.Event()
        self.handoff_lock = threading.Lock()
        self.preference_warning = ""
        self.open_warning = ""
        self.fitting_content = False
        self.status = tk.StringVar(value="Ready to generate your dashboard.")
        self.notice = tk.StringVar(value="")

        root.title("Workflow Transfer Dashboard")
        root.geometry("680x480")
        root.minsize(620, 460)
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        self.content_frame = frame
        self.wrapping_labels = []

        def label(text=None, **kwargs):
            widget = ttk.Label(frame, text=text, wraplength=620, **kwargs)
            self.wrapping_labels.append(widget)
            return widget

        label("Transfer Credit Dashboard", font=("TkDefaultFont", 17, "bold")).grid(row=0, column=0, sticky="w")
        label("Choose a folder, then sign in with Microsoft.\n"
              "Your dashboard, workbook, and CSV will be saved together.").grid(
            row=1, column=0, sticky="w", pady=(8, 16))
        label("Output folder").grid(row=2, column=0, sticky="w")
        self.path_view = tk.Text(
            frame, height=2, wrap="char", relief="flat", borderwidth=0,
            font="TkDefaultFont", padx=6, pady=6, takefocus=True,
        )
        self.path_view.grid(row=3, column=0, sticky="ew", pady=(4, 14))
        self.set_display_path(self.destination)
        self.path_view.bind("<Command-c>" if sys.platform == "darwin" else "<Control-c>", self.copy_path)

        stages = ttk.Frame(frame)
        stages.grid(row=4, column=0, sticky="ew")
        self.stage_labels = []
        for column, text in enumerate(("1. Sign in", "2. Fetch records", "3. Create dashboard")):
            stages.columnconfigure(column, weight=1)
            widget = ttk.Label(stages, text=text)
            widget.grid(row=0, column=column, sticky="w")
            self.stage_labels.append(widget)
        label(textvariable=self.status).grid(row=5, column=0, sticky="w", pady=(10, 6))
        self.bar = ttk.Progressbar(frame, mode="indeterminate", value=0)
        self.bar.grid(row=6, column=0, sticky="ew", pady=(4, 10))
        self.bar.grid_remove()

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, sticky="w", pady=(6, 8))
        self.generate_button = ttk.Button(buttons, text="Generate Dashboard", command=self.generate)
        self.generate_button.grid(row=0, column=0, padx=(0, 8))
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.cancel_run)
        self.cancel_button.grid(row=0, column=1)
        self.cancel_button.grid_remove()
        results = ttk.Frame(frame)
        results.grid(row=8, column=0, sticky="w", pady=(0, 4))
        self.dashboard_button = ttk.Button(results, text="Open Dashboard", command=self.open_dashboard)
        self.dashboard_button.grid(row=0, column=0, padx=(0, 8))
        self.folder_button = ttk.Button(results, text="Open Output Folder", command=self.open_folder)
        self.folder_button.grid(row=0, column=1)
        label(textvariable=self.notice).grid(row=9, column=0, sticky="w", pady=(4, 4))
        label("Sign-in credentials are not saved.").grid(row=10, column=0, sticky="w", pady=(8, 0))
        frame.bind("<Configure>", self.resize)
        root.bind("<Escape>", lambda event: self.cancel_run())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_controls()
        self.generate_button.focus_set()
        root.after(100, self.poll)

    @property
    def active(self):
        return self.state in ACTIVE_STATES

    def resize(self, event):
        for label in self.wrapping_labels:
            label.configure(wraplength=max(200, event.width - 48))
        self.fit_content()

    def fit_content(self):
        # Native font sizes and wrapped warnings vary across macOS and Windows.
        # Let Tk measure the content instead of clipping it at a fixed height.
        if self.fitting_content:
            return
        self.fitting_content = True
        try:
            self.root.update_idletasks()
            self.root.minsize(620, max(460, self.content_frame.winfo_reqheight()))
        finally:
            self.fitting_content = False

    def set_display_path(self, path):
        self.path_view.configure(state="normal")
        self.path_view.delete("1.0", "end")
        self.path_view.insert("1.0", str(path) if path else "Choose a folder when you generate.")
        self.path_view.configure(state="disabled")

    def copy_path(self, event=None):
        import tkinter as tk
        try:
            selected = self.path_view.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)
        return "break"

    def refresh_controls(self):
        self.generate_button.configure(
            state="disabled" if self.active or self.closing else "normal",
            text="Generate Again" if self.last_result else "Generate Dashboard",
        )
        show_cancel = self.state in {DesktopState.SIGNIN, DesktopState.FETCHING, DesktopState.CANCELLING}
        if show_cancel:
            self.cancel_button.grid()
            self.cancel_button.configure(
                text="Cancelling…" if self.state == DesktopState.CANCELLING else "Cancel",
                state="disabled" if self.closing or self.state == DesktopState.CANCELLING else "normal",
            )
        else:
            self.cancel_button.grid_remove()
        if self.active and self.state != DesktopState.CHOOSING:
            self.bar.grid()
            self.bar.start(12)
        else:
            self.bar.stop()
            self.bar.configure(value=0)
            self.bar.grid_remove()
        for index, widget in enumerate(self.stage_labels):
            current = {
                DesktopState.SIGNIN: 0, DesktopState.FETCHING: 1, DesktopState.GENERATING: 2,
            }.get(self.state)
            widget.configure(font=("TkDefaultFont", 10, "bold" if index == current else "normal"))
        self.dashboard_button.configure(state="normal" if self.last_result and not self.closing else "disabled")
        self.folder_button.configure(state="normal" if (self.last_result or self.destination) and not self.closing else "disabled")
        self.fit_content()

    def refresh_notice(self):
        self.notice.set("\n".join(value for value in (self.preference_warning, self.open_warning) if value))
        self.fit_content()

    def generate(self):
        if self.active or self.closing:
            return
        previous_state = self.state
        self.run_id += 1  # Also invalidate old file-opening notifications while the dialog is open.
        run_id = self.run_id
        self.cancel = threading.Event()
        self.rendering = threading.Event()
        self.state = DesktopState.CHOOSING
        self.refresh_controls()
        try:
            initial = initial_output_directory(self.destination)
            selection = self.filedialog.askdirectory(
                parent=self.root, title="Choose a folder for your dashboard files",
                initialdir=str(initial), mustexist=True,
            )
        except Exception:
            self.state = DesktopState.ERROR
            self.status.set("Could not open the folder chooser. Click Generate Dashboard to try again.")
            self.refresh_controls()
            if self.closing:
                self.root.destroy()
            return
        if self.closing:
            self.root.destroy()
            return
        if not selection:
            self.state = previous_state
            self.refresh_controls()
            self.generate_button.focus_set()
            return
        self.preference_warning = self.open_warning = ""
        self.refresh_notice()
        self.state = DesktopState.CHECKING
        self.status.set("Checking the selected folder…")
        self.refresh_controls()
        threading.Thread(
            target=self.work, args=(run_id, Path(selection), self.cancel, self.rendering), daemon=False,
        ).start()

    def work(self, run_id, selection, cancel, rendering):
        def send(kind, value):
            self.events.put((run_id, kind, value))

        try:
            directory = validate_output_directory(selection)
        except Exception:
            send("error", "Cannot save files in that folder. Click Generate Dashboard and choose an accessible folder.")
            return
        remembered = True
        try:
            save_output_directory(self.preferences_file, directory)
        except Exception:
            remembered = False
        send("prepared", (directory, remembered))
        if cancel.is_set():
            send("cancelled", str(BrowserAuthError("cancelled")))
            return
        previous_stage = None

        def progress(value):
            nonlocal previous_stage
            if value == "generating":
                # Serialize the cancel/render handoff, including the short interval
                # before Tk receives the generation-stage event.
                with self.handoff_lock:
                    if cancel.is_set():
                        raise BrowserAuthError("cancelled")
                    rendering.set()
            if value != previous_stage:
                send("progress", value)
                previous_stage = value

        try:
            progress("signin")
            result = fetch_and_generate(
                replace(self.config, output_dir=directory), channel=self.channel,
                cancel=cancel, progress=progress,
            )
            send("done", result)
        except WorkflowPopulationError:
            send("error", "The transcript evaluation workflow is unavailable. Check your eTrieve access "
                 "or contact the dashboard administrator. No files were created.")
        except BrowserAuthError as error:
            send("cancelled" if error.code == "cancelled" else "error", str(error))
        except Exception:
            send("error", "Could not create the dashboard files. Check output folder access "
                 "or contact the dashboard administrator, then try again.")

    def cancel_run(self):
        if self.closing or self.state not in {DesktopState.SIGNIN, DesktopState.FETCHING}:
            return
        with self.handoff_lock:
            if self.rendering.is_set():
                self.state = DesktopState.GENERATING
                self.status.set(STAGE_MESSAGES[self.state])
            else:
                self.cancel.set()
                self.state = DesktopState.CANCELLING
                self.status.set("Cancelling… Closing sign-in and fetching safely.")
        self.refresh_controls()

    def publish_notice(self, action, message):
        run_id = self.run_id
        self.open_warning = ""
        self.refresh_notice()

        def perform():
            try:
                failed = action() is False
            except Exception:
                failed = True
            if failed:
                self.events.put((run_id, "notice", message))

        threading.Thread(target=perform, daemon=True).start()

    def open_dashboard(self):
        if self.last_result is None or self.closing:
            return
        path = Path(self.last_result["outputs"]["html"])
        self.publish_notice(
            lambda: path.is_file() and webbrowser.open(path.resolve().as_uri()),
            "Could not open the dashboard in your browser. Use Open Output Folder to find the HTML file.",
        )

    def open_folder(self):
        if self.closing:
            return
        directory = Path(self.last_result["outputs"]["html"]).parent if self.last_result else self.destination
        if directory is None:
            return

        def open_it():
            if not directory.is_dir():
                return False
            if os.name == "nt":
                os.startfile(str(directory))
            else:
                # Wait off Tk's thread so an unsuccessful launcher is reported too.
                return subprocess.run(
                    ["open" if sys.platform == "darwin" else "xdg-open", str(directory)],
                    check=False, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                ).returncode == 0

        self.publish_notice(open_it, "Could not open the output folder. Check that it is still available.")

    def poll(self):
        # Reschedule first and bound each batch to keep clicks/window closure responsive.
        self.root.after(100, self.poll)
        for _ in range(32):
            try:
                run_id, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if run_id != self.run_id:
                continue
            if kind == "notice":
                if not self.closing:
                    self.open_warning = value
                    self.refresh_notice()
                continue
            if kind == "prepared":
                self.destination, remembered = value
                if not self.closing:
                    self.set_display_path(self.destination)
                    self.preference_warning = "" if remembered else (
                        "This folder will be used this time, but could not be remembered for next time."
                    )
                    self.refresh_notice()
                    self.refresh_controls()
                continue
            if kind == "progress":
                if self.closing or self.state == DesktopState.CANCELLING:
                    continue
                next_state = STAGE_STATES.get(value)
                if next_state is not None:
                    self.state = next_state
                    self.status.set(STAGE_MESSAGES[self.state])
                    self.refresh_controls()
                continue
            if self.closing:
                self.root.destroy()
                return
            if kind == "done":
                self.state = DesktopState.SUCCESS
                self.last_result = value
                self.set_display_path(Path(value["outputs"]["html"]).parent)
                self.status.set(f"Dashboard ready — {value['records']:,} records.\n"
                                "Your dashboard, workbook, and CSV are saved in the folder above.")
                self.refresh_controls()
                self.open_dashboard()
            else:
                self.state = DesktopState.CANCELLED if kind == "cancelled" else DesktopState.ERROR
                self.status.set(value)
                self.refresh_controls()
            self.generate_button.focus_set()

    def close(self):
        if self.closing:
            return
        if not self.active:
            self.root.destroy()
            return
        self.closing = True
        with self.handoff_lock:
            if self.rendering.is_set():
                self.status.set("Finishing dashboard files before closing…")
            else:
                self.cancel.set()
                self.status.set("Closing safely…")
        self.refresh_controls()


def launch_desktop(*, settings_path=None, channel="msedge") -> int:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    try:
        config = desktop_config(settings_path)
    except Exception:
        messagebox.showerror("Settings", "Could not load dashboard settings. Check the nonsecret settings.toml file.", parent=root)
        root.destroy()
        return 2
    DesktopApp(root, config, channel=channel)
    root.mainloop()
    return 0
