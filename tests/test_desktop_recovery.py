"""Exercise native-dialog orchestration and recovery without signing anyone in."""
import sqlite3
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_dashboard import desktop
from workflow_dashboard.browser_auth import BrowserAuthError
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.desktop import DesktopState
from workflow_dashboard.desktop_preferences import load_output_directory, save_output_directory
from workflow_dashboard.normalization import WorkflowPopulationError, normalize_records, select_workflow_population


WORKFLOW = "Example  Transcript Evaluation Form"
REAL_FETCH_AND_GENERATE = desktop.fetch_and_generate


class Variable:
    def __init__(self, value=""):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Widget:
    def __init__(self, root=None, **kwargs):
        self.options = kwargs
        self.running = False
        self.visible = True
        self.handlers = {}
        self.content = ""
    def pack(self, **kwargs):
        self.visible = True
    def grid(self, **kwargs):
        self.visible = True
    def grid_remove(self):
        self.visible = False
    def columnconfigure(self, *args, **kwargs):
        pass
    def winfo_reqheight(self):
        return self.options.get("requested_height", 460)
    def configure(self, **kwargs):
        self.options.update(kwargs)
    def bind(self, event, callback):
        self.handlers[event] = callback
    def start(self, interval):
        self.running = True
        self.options["value"] = 57
    def stop(self):
        self.running = False
    def focus_set(self):
        pass
    def delete(self, *args):
        self.content = ""
    def insert(self, index, value):
        self.content = value
    def get(self, *args):
        return self.content
    def current(self, index=None):
        if index is not None:
            self.selected_index = index
        return getattr(self, 'selected_index', 0)
    def set(self, *args):
        pass
    def yview(self, *args):
        pass
    def invoke(self):
        assert self.visible and self.options.get("state") != "disabled"
        self.options["command"]()


class Root:
    def __init__(self):
        self.pending = []
        self.destroyed = False
        self.protocols = {}
        self.handlers = {}
        self.clipboard = ""
    def title(self, value):
        pass
    def geometry(self, value):
        pass
    def minsize(self, *args):
        self.minimum_size = args
    def update_idletasks(self):
        pass
    def after(self, delay, callback):
        self.pending.append(callback)
    def tick(self):
        self.pending.pop(0)()
    def protocol(self, name, callback):
        self.protocols[name] = callback
    def bind(self, event, callback):
        self.handlers[event] = callback
    def destroy(self):
        self.destroyed = True
    def clipboard_clear(self):
        self.clipboard = ""
    def clipboard_append(self, value):
        self.clipboard += value
    def mainloop(self):
        self.looped = True


@pytest.fixture
def harness(monkeypatch, tmp_path):
    selections, dialogs, workers, launches, widgets = [], [], [], [], []
    def choose(**kwargs):
        dialogs.append(kwargs)
        return selections.pop(0)
    def make(*args, **kwargs):
        widget = Widget(*args, **kwargs)
        widgets.append(widget)
        return widget
    fake_tk = SimpleNamespace(
        Tk=Root, StringVar=Variable, Text=make, TclError=RuntimeError,
        Toplevel=lambda parent: Root(),
        ttk=SimpleNamespace(Frame=make, Label=make, Progressbar=make, Button=make, Combobox=make, Scrollbar=make),
        filedialog=SimpleNamespace(askdirectory=choose),
        messagebox=SimpleNamespace(showerror=lambda *args, **kwargs: pytest.fail("invalid settings")),
    )
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
    class Thread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args
        def start(self):
            (launches if self.target.__name__ == "perform" else workers).append(self)
        def run(self):
            self.target(*self.args)
    monkeypatch.setattr(desktop, "threading", SimpleNamespace(
        Thread=Thread, Event=threading.Event, Lock=threading.Lock,
    ))
    app_data = tmp_path / "app"
    monkeypatch.setattr(desktop, "application_directory", lambda: app_data)
    config = DashboardConfig(
        workflow_filter=WORKFLOW, output_dir=app_data / "outputs",
        history_db_path=app_data / "history" / "workflow_history.sqlite",
    )
    root = Root()
    app = desktop.DesktopApp(root, config)
    chosen = tmp_path / "Exports with spaces — 学生"
    chosen.mkdir()
    dated = chosen / "2026-10-01_Thursday"
    result = {"records": 4314, "outputs": {
        "html": str(dated / "dashboard.html"), "excel": str(dated / "dashboard.xlsx"),
        "csv": str(dated / "records.csv"), "history_db": str(config.history_db_path),
    }}
    def success(*args, **kwargs):
        kwargs["progress"]("fetching")
        kwargs["progress"]("generating")
        dated.mkdir(exist_ok=True)
        Path(result["outputs"]["html"]).write_text("<html>Test</html>")
        return result
    monkeypatch.setattr(desktop, "fetch_and_generate", success)
    return SimpleNamespace(
        app=app, root=root, config=config, chosen=chosen, result=result,
        selections=selections, dialogs=dialogs, workers=workers, launches=launches,
        widgets=widgets, app_data=app_data, fake_tk=fake_tk,
    )


def complete(harness):
    harness.workers.pop(0).run()
    harness.root.tick()


def test_no_picker_and_dialog_cancellation_restores_previous_screen(harness):
    app = harness.app
    assert not any("values" in widget.options for widget in harness.widgets)
    assert not app.bar.visible and not app.cancel_button.visible
    harness.selections.append("")
    app.generate_button.invoke()
    assert app.state == DesktopState.READY
    assert app.status.get() == "Ready to generate your dashboard."
    assert not harness.workers
    assert not app.preferences_file.exists()
    assert not app.config.history_db_path.exists()
    assert harness.dialogs[0]["mustexist"] is True


@pytest.mark.parametrize("platform_name", ["nt", "posix"])
def test_success_saves_folder_and_opens_exact_last_result_off_ui_thread(monkeypatch, harness, platform_name):
    app = harness.app
    harness.selections.append(str(harness.chosen))
    app.generate_button.invoke()
    assert app.state == DesktopState.CHECKING and app.bar.running
    assert len(harness.workers) == 1
    complete(harness)
    assert app.state == DesktopState.SUCCESS
    assert "4,314 records" in app.status.get()
    assert not app.bar.running and not app.bar.visible and app.bar.options["value"] == 0
    assert not app.cancel_button.visible
    assert app.generate_button.options["text"] == "Generate Again"
    assert app.path_view.content == str(Path(harness.result["outputs"]["html"]).parent)
    assert load_output_directory(app.preferences_file) == harness.chosen
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda path: opened.append(path) or True)
    assert opened == [] and len(harness.launches) == 1
    harness.launches.pop(0).run()
    assert opened == [Path(harness.result["outputs"]["html"]).as_uri()]
    folders = []
    # Replace the module reference, not the shared os.name: pathlib must keep
    # using the host platform while both folder-launch branches are exercised.
    monkeypatch.setattr(desktop, "os", SimpleNamespace(
        name=platform_name, startfile=lambda path: folders.append([path]),
    ))
    monkeypatch.setattr(desktop.subprocess, "run", lambda args, **kwargs: folders.append(args) or SimpleNamespace(returncode=0))
    app.folder_button.invoke()
    assert folders == []
    harness.launches.pop(0).run()
    assert len(folders) == 1
    assert folders[0][-1] == str(Path(harness.result["outputs"]["html"]).parent)
    if platform_name == "nt":
        assert len(folders[0]) == 1
    else:
        assert folders[0][0] == ("open" if sys.platform == "darwin" else "xdg-open")
    app.close()
    assert harness.root.destroyed


def test_every_run_prompts_at_remembered_root_and_restart_restores_it(harness):
    app = harness.app
    harness.selections.append(str(harness.chosen))
    app.generate()
    complete(harness)
    harness.selections.append("")
    app.generate()
    assert harness.dialogs[-1]["initialdir"] == str(harness.chosen)
    assert app.state == DesktopState.SUCCESS
    assert app.last_result is harness.result
    new_app = desktop.DesktopApp(Root(), harness.config)
    assert new_app.destination == harness.chosen
    harness.selections.append("")
    new_app.generate()
    assert harness.dialogs[-1]["initialdir"] == str(harness.chosen)
    assert new_app.dashboard_button.options["state"] == "disabled"
    assert new_app.folder_button.options["state"] == "normal"


def test_unavailable_remembered_folder_requires_a_new_selection(monkeypatch, harness):
    stale = harness.chosen / "removed"
    save_output_directory(harness.app.preferences_file, stale)
    app = desktop.DesktopApp(Root(), harness.config)
    assert app.destination == stale
    harness.selections.append("")
    app.generate()
    assert harness.dialogs[-1]["initialdir"] != str(stale)
    assert not harness.workers
    assert load_output_directory(app.preferences_file) == stale


@pytest.mark.parametrize("failure", ["missing", "unwritable"])
def test_bad_destination_never_authenticates_or_commits_history(monkeypatch, harness, failure):
    app = harness.app
    selected = harness.chosen if failure == "unwritable" else harness.chosen / "missing"
    harness.selections.append(str(selected))
    monkeypatch.setattr(desktop, "fetch_and_generate", lambda *args, **kwargs: pytest.fail("authentication started"))
    if failure == "unwritable":
        def deny(*args):
            raise PermissionError("synthetic-private-secret")
        monkeypatch.setattr(desktop, "validate_output_directory", deny)
    app.generate()
    complete(harness)
    assert app.state == DesktopState.ERROR
    assert "accessible folder" in app.status.get()
    assert "synthetic-private-secret" not in app.status.get()
    assert not app.bar.visible and not app.cancel_button.visible
    assert not app.preferences_file.exists()
    assert not app.config.history_db_path.exists()


def test_chooser_failure_recovers_without_starting_a_worker(monkeypatch, harness):
    def fail(**kwargs):
        raise RuntimeError("synthetic-private-secret")
    monkeypatch.setattr(harness.fake_tk.filedialog, "askdirectory", fail)
    harness.app.generate()
    assert harness.app.state == DesktopState.ERROR
    assert "folder chooser" in harness.app.status.get()
    assert "synthetic-private-secret" not in harness.app.status.get()
    assert harness.app.generate_button.options["state"] == "normal"
    assert not harness.workers and not harness.app.bar.visible


def test_selected_destination_changes_exports_only(monkeypatch, harness):
    received = []
    def run(config, **kwargs):
        received.append(config)
        return harness.result
    monkeypatch.setattr(desktop, "fetch_and_generate", run)
    harness.selections.append(str(harness.chosen))
    harness.app.generate()
    complete(harness)
    assert received[0].output_dir == harness.chosen
    assert received[0].history_db_path == harness.config.history_db_path
    assert received[0].workflow_filter == WORKFLOW
    assert received[0].api_token is None
    assert harness.app.config.output_dir == harness.config.output_dir


def test_close_during_preflight_stops_before_authentication(monkeypatch, harness):
    monkeypatch.setattr(desktop, "fetch_and_generate", lambda *args, **kwargs: pytest.fail("authentication started"))
    harness.selections.append(str(harness.chosen))
    harness.app.generate()
    harness.app.close()
    assert not harness.root.destroyed and harness.app.cancel.is_set()
    complete(harness)
    assert harness.root.destroyed
    assert load_output_directory(harness.app.preferences_file) == harness.chosen


def test_preference_save_failure_allows_run_with_separate_warning(monkeypatch, harness):
    def deny(*args):
        raise PermissionError("synthetic-private-secret")
    monkeypatch.setattr(desktop, "save_output_directory", deny)
    harness.selections.append(str(harness.chosen))
    harness.app.generate()
    complete(harness)
    assert harness.app.state == DesktopState.SUCCESS
    assert "could not be remembered" in harness.app.notice.get()
    assert "Dashboard ready" in harness.app.status.get()
    assert "synthetic-private-secret" not in harness.app.notice.get()


@pytest.mark.parametrize("code", ["expired", "forbidden", "integrity", "timeout", "closed", "cancelled"])
def test_auth_failure_resets_controls_remembers_validated_path_and_retries_fresh(monkeypatch, harness, code):
    calls = []
    def fail(*args, **kwargs):
        calls.append("fresh fetch")
        raise BrowserAuthError(code)
    monkeypatch.setattr(desktop, "fetch_and_generate", fail)
    harness.selections.extend([str(harness.chosen), str(harness.chosen)])
    for _ in range(2):
        harness.app.generate()
        complete(harness)
        assert not harness.app.bar.visible and not harness.app.cancel_button.visible
        assert harness.app.generate_button.options["state"] == "normal"
        assert load_output_directory(harness.app.preferences_file) == harness.chosen
    assert calls == ["fresh fetch", "fresh fetch"]
    assert not harness.app.config.history_db_path.exists()


def test_missing_fixed_workflow_publishes_nothing_and_never_offers_choices(monkeypatch, harness):
    app = harness.app
    fetched = {"records": [{"packageID": "other", "workflowName": "Other Workflow"}],
               "fetch": {"pagination_validated": True}}
    calls = []
    monkeypatch.setattr(desktop, "fetch_and_generate", REAL_FETCH_AND_GENERATE)
    def fetch(*args, **kwargs):
        calls.append("fetch")
        return fetched
    monkeypatch.setattr(desktop, "browser_fetch", fetch)
    harness.selections.extend([str(harness.chosen), str(harness.chosen)])
    for _ in range(2):
        app.generate()
        complete(harness)
        assert app.state == DesktopState.ERROR
        assert "workflow is unavailable" in app.status.get()
        assert not hasattr(app, "cached_fetch")
    assert calls == ["fetch", "fetch"]
    assert not list(harness.chosen.iterdir())
    assert not app.config.history_db_path.exists()


def test_cancellation_waits_for_terminal_event_and_does_not_regress_progress(monkeypatch, harness):
    app = harness.app
    def fetch(config, **kwargs):
        harness.root.tick()
        assert app.state == DesktopState.SIGNIN and app.cancel_button.visible
        app.cancel_button.invoke()
        assert app.state == DesktopState.CANCELLING
        assert app.cancel.is_set()
        assert app.cancel_button.options["state"] == "disabled"
        assert app.bar.running
        assert app.generate_button.options["state"] == "disabled"
        kwargs["progress"]("fetching")
        harness.root.tick()
        assert app.state == DesktopState.CANCELLING
        assert "Cancelling" in app.status.get()
        raise BrowserAuthError("cancelled")
    monkeypatch.setattr(desktop, "fetch_and_generate", fetch)
    harness.selections.append(str(harness.chosen))
    app.generate()
    complete(harness)
    assert app.state == DesktopState.CANCELLED
    assert not app.bar.visible and not app.cancel_button.visible
    assert load_output_directory(app.preferences_file) == harness.chosen


def test_cancel_render_handoff_and_close_wait_for_publication(monkeypatch, harness):
    app = harness.app
    def generate(config, **kwargs):
        harness.root.tick()
        assert app.state == DesktopState.SIGNIN
        kwargs["progress"]("generating")  # Tk has not yet received this transition.
        app.cancel_run()
        assert app.state == DesktopState.GENERATING
        assert not app.cancel.is_set() and not app.cancel_button.visible
        app.close()
        assert not app.cancel.is_set() and not harness.root.destroyed
        assert "Finishing" in app.status.get()
        return harness.result
    monkeypatch.setattr(desktop, "fetch_and_generate", generate)
    harness.selections.append(str(harness.chosen))
    app.generate()
    complete(harness)
    assert harness.root.destroyed
    assert not harness.launches


def test_cancel_wins_before_generation_handoff(monkeypatch, harness):
    app = harness.app
    def generate(config, **kwargs):
        harness.root.tick()
        app.cancel_run()
        kwargs["progress"]("generating")
        pytest.fail("rendering began after cancellation")
    monkeypatch.setattr(desktop, "fetch_and_generate", generate)
    harness.selections.append(str(harness.chosen))
    app.generate()
    complete(harness)
    assert app.state == DesktopState.CANCELLED and not app.rendering.is_set()


def test_close_during_signin_cancels_and_waits_for_worker(monkeypatch, harness):
    app = harness.app
    def fetch(config, **kwargs):
        harness.root.tick()
        app.close()
        assert app.cancel.is_set() and not harness.root.destroyed
        raise BrowserAuthError("cancelled")
    monkeypatch.setattr(desktop, "fetch_and_generate", fetch)
    harness.selections.append(str(harness.chosen))
    app.generate()
    complete(harness)
    assert harness.root.destroyed


def test_old_notices_and_results_cannot_overwrite_new_run(monkeypatch, harness):
    app = harness.app
    harness.selections.append(str(harness.chosen))
    app.generate()
    complete(harness)
    old_run = app.run_id
    harness.selections.append(str(harness.chosen))
    app.generate()
    app.events.put((old_run, "notice", "old opening failure"))
    app.events.put((old_run, "error", "old generation failure"))
    app.events.put((old_run, "done", harness.result))
    harness.root.tick()
    assert app.state == DesktopState.CHECKING
    assert "old" not in app.notice.get()
    assert app.status.get() == "Checking the selected folder…"
    app.generate()  # Ignore repeated clicks/shortcuts while busy.
    assert len(harness.workers) == 1 and len(harness.dialogs) == 2
    complete(harness)


def test_opening_failure_keeps_success_and_can_be_retried(monkeypatch, harness):
    monkeypatch.setattr(desktop.webbrowser, "open", lambda *args: False)
    harness.selections.append(str(harness.chosen))
    harness.app.generate()
    complete(harness)
    harness.launches.pop(0).run()
    harness.root.tick()
    assert harness.app.state == DesktopState.SUCCESS
    assert "Dashboard ready" in harness.app.status.get()
    assert "Could not open" in harness.app.notice.get()
    assert harness.app.dashboard_button.options["state"] == "normal"
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda path: opened.append(path) or True)
    harness.app.dashboard_button.invoke()
    harness.launches.pop(0).run()
    assert opened
    assert harness.app.notice.get() == ""


def test_escape_cancels_only_cancellable_stages_and_path_can_be_copied(harness):
    app = harness.app
    harness.root.handlers["<Escape>"](None)
    assert not app.cancel.is_set()
    app.set_display_path(harness.chosen)
    app.copy_path()
    assert harness.root.clipboard == str(harness.chosen)
    assert app.path_view.options["state"] == "disabled"


def test_window_minimum_height_follows_measured_content(harness):
    app = harness.app
    app.content_frame.options["requested_height"] = 560
    app.resize(SimpleNamespace(width=620))
    assert harness.root.minimum_size == (620, 560)
    assert all(widget.options["wraplength"] == 572 for widget in app.wrapping_labels)


def test_resize_events_during_measurement_do_not_reenter_layout(monkeypatch, harness):
    app = harness.app
    updates = []
    def idle():
        updates.append("update")
        app.resize(SimpleNamespace(width=620))
    monkeypatch.setattr(harness.root, "update_idletasks", idle)
    app.content_frame.options["requested_height"] = 560
    app.fit_content()
    assert updates == ["update"]
    assert not app.fitting_content
    assert harness.root.minimum_size == (620, 560)


def test_preflight_and_fetch_run_off_tk_thread(monkeypatch, harness):
    from workflow_dashboard.desktop_preferences import validate_output_directory
    main_thread = threading.get_ident()
    thread_ids = []
    real_threads = []
    class Thread(threading.Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            real_threads.append(self)
    monkeypatch.setattr(desktop, "threading", SimpleNamespace(Thread=Thread, Event=threading.Event, Lock=threading.Lock))
    def validate(path):
        thread_ids.append(threading.get_ident())
        return validate_output_directory(path)
    def fetch(*args, **kwargs):
        thread_ids.append(threading.get_ident())
        return harness.result
    monkeypatch.setattr(desktop, "validate_output_directory", validate)
    monkeypatch.setattr(desktop, "fetch_and_generate", fetch)
    harness.selections.append(str(harness.chosen))
    harness.app.generate()
    real_threads[0].join(timeout=5)
    assert not real_threads[0].is_alive()
    assert len(thread_ids) == 2 and all(value != main_thread for value in thread_ids)
    assert harness.app.state == DesktopState.CHECKING  # UI changes await delivery on Tk.
    harness.root.tick()
    for thread in real_threads:
        thread.join(timeout=5)


def test_workflow_spacing_is_preserved_and_missing_filter_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "application_directory", lambda: tmp_path)
    # Test exact matching with synthetic settings, independently of the user's
    # customized bundled preset used to build their executable.
    settings = tmp_path / "settings.toml"
    settings.write_text(f'workflow_filter = "{WORKFLOW}"\n', encoding="utf-8")
    config = desktop.desktop_config()
    records = [{"packageID": "one", "workflowName": WORKFLOW}]
    normalized = normalize_records(records, config)
    assert len(select_workflow_population(normalized, config)) == 1
    with pytest.raises(WorkflowPopulationError):
        select_workflow_population(normalized, replace(config, workflow_filter="Example Transcript Evaluation Form"))
    settings.write_text('dashboard_title = "Title"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="one workflow"):
        desktop.desktop_config(settings)


def test_changing_destination_preserves_history_and_complete_export_sets(monkeypatch, tmp_path):
    from workflow_dashboard.generation import generate_dashboard
    config = DashboardConfig(
        workflow_filter=WORKFLOW, output_dir=tmp_path / "first",
        history_db_path=tmp_path / "app" / "history.sqlite",
    )
    record = {
        "packageID": "case-one", "workflowName": WORKFLOW, "stepName": "End",
        "status": "Completed", "submissionDate": "2026-09-29T09:00:00",
        "lastActivityDate": "2026-09-30T10:00:00", "submittedBy": "Fixture Worker",
    }
    first = generate_dashboard(config, [record], {"pagination_validated": True})
    second = generate_dashboard(replace(config, output_dir=tmp_path / "second"), [record], {"pagination_validated": True})
    assert first["definition_hash"] == second["definition_hash"]
    assert first["outputs"]["history_db"] == second["outputs"]["history_db"]
    for result in (first, second):
        assert result["records"] == 1
        for name in ("html", "excel", "csv"):
            path = Path(result["outputs"][name])
            assert path.is_file() and path.stat().st_size > 0
    with sqlite3.connect(config.history_db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshot_metrics").fetchone()[0] == 2
