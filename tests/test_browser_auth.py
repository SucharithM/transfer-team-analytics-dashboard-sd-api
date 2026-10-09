import json
import multiprocessing
import os
import sys
import threading
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from workflow_dashboard import browser_auth as auth
from workflow_dashboard import desktop
from workflow_dashboard.api_client import PaginationIntegrityError, WorkflowApiClient
from workflow_dashboard.config import DashboardConfig, DEFAULT_API_URL, load_config
from workflow_dashboard.generation import generate_dashboard

TOKEN = "synthetic-private-bearer-123456789"


class Pipe:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send(self, value):
        self.messages.append(value)

    def close(self):
        self.closed = True


def request(url=DEFAULT_API_URL, method="GET", header=None):
    return SimpleNamespace(url=url, method=method, header_value=lambda name: header)


@pytest.mark.parametrize(
    "url",
    [
        "http://tenant.example.test/flow/api/user-dashboard/packages",
        DEFAULT_API_URL + "/extra",
        DEFAULT_API_URL.replace("tenant.example.test", "tenant.example.test.evil.test"),
        DEFAULT_API_URL.replace("tenant.example.test", "evil.test"),
        DEFAULT_API_URL.replace(".test/", ".test:444/"),
        DEFAULT_API_URL.replace("https://", "https://user:pass@"),
        DEFAULT_API_URL + "#fragment",
        "https://login.microsoftonline.com/oauth/token",
    ],
)
def test_only_exact_trusted_endpoint_is_observed(url):
    assert auth.bearer_from_request(request(url, header=f"Bearer {TOKEN}")) is None


@pytest.mark.parametrize(
    "header", [None, "", "Basic secret", "Bearer", "Bearer one two"]
)
def test_invalid_authorization_is_ignored(header):
    assert auth.bearer_from_request(request(header=header)) is None


def test_capture_reads_only_authorization_header():
    assert (
        auth.bearer_from_request(
            request(DEFAULT_API_URL + "?offset=0", header=f"bEaReR {TOKEN}")
        )
        == TOKEN
    )
    assert (
        auth.bearer_from_request(request(method="POST", header=f"Bearer {TOKEN}"))
        is None
    )


def test_nonsecret_configuration_never_imports_credentials_into_environment(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("WORKFLOW_API_TOKEN", raising=False)
    monkeypatch.delenv("ETRIEVE_API_TOKEN", raising=False)
    monkeypatch.delenv("WORKFLOW_DASHBOARD_TITLE", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        f"WORKFLOW_API_TOKEN={TOKEN}\nWORKFLOW_DASHBOARD_TITLE=Configured title\n"
    )
    config = load_config(env_file=env)
    assert config.api_token is None
    assert config.dashboard_title == "Configured title"
    assert "WORKFLOW_API_TOKEN" not in os.environ
    legacy = load_config(env_file=env, include_credentials=True)
    assert legacy.api_token == TOKEN
    assert TOKEN not in repr(legacy)
    assert "WORKFLOW_API_TOKEN" not in os.environ


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


def install_fake_browser(
    monkeypatch,
    *,
    capture=True,
    closed=False,
    events=(),
    navigation_error=None,
    cleanup_error=None,
    clock=None,
    event_greenlets=False,
    launch_options=None,
):
    lifecycle = []
    callback = None
    if closed and clock is None:
        clock = Clock()
    if clock is not None:
        monkeypatch.setattr(auth, "time", SimpleNamespace(monotonic=clock.monotonic))

    def emitter(**kwargs):
        handlers = {}
        obj = SimpleNamespace(**kwargs)

        def on(event, handler):
            if event_greenlets:
                from greenlet import greenlet

                original = handler
                handler = lambda *args: greenlet(original).switch(*args)
            handlers.setdefault(event, []).append(handler)

        obj.on = on
        obj.emit = lambda event, *args: [
            handler(*args) for handler in handlers.get(event, [])
        ]
        return obj

    page = emitter()
    context = emitter(pages=[page])
    pending_events = list(events)
    register = context.on

    def on(event, handler):
        nonlocal callback
        register(event, handler)
        if event == "request":
            callback = lambda request: context.emit("request", request)

    def goto(url, **kwargs):
        assert url == "https://tenant.example.test"
        assert kwargs["wait_until"] == "commit"
        if navigation_error is not None:
            raise navigation_error
        if capture:
            callback(request(header=f"Bearer {TOKEN}"))
        elif closed:
            context.pages.clear()

    context.on = on

    def new_page():
        context.emit("page", page)
        return page

    context.new_page = new_page

    def close_context():
        lifecycle.append("context_closed")
        page.emit("close")
        context.emit("close")
        if cleanup_error is not None:
            raise cleanup_error

    context.close = close_context

    class Event:
        def __init__(self, predicate, timeout):
            self.predicate = predicate
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            if clock is not None:
                clock.now += self.timeout / 1000
            if pending_events:
                event = pending_events.pop(0)(context, callback)
                if self.predicate(event):
                    return
            raise PlaywrightTimeoutError("synthetic event timeout")

    def expect_event(name, *, predicate, timeout):
        assert name == "request" and 0 < timeout <= 100
        return Event(predicate, timeout)

    context.expect_event = expect_event
    page.goto = goto
    page.wait_for_timeout = lambda milliseconds: pytest.fail(
        "Sign-in wait must not depend on a particular page"
    )

    page.wait_for_timeout = lambda milliseconds: pytest.fail(
        "Sign-in wait must not depend on a particular page"
    )

    def close_browser():
        lifecycle.append("browser_closed")
        browser.emit("disconnected")

    browser = emitter(
        new_context=lambda **kwargs: context,
        close=close_browser,
        is_connected=lambda: True,
    )
        lifecycle.append("browser_closed")
        browser.emit("disconnected")

    browser = emitter(
        new_context=lambda **kwargs: context,
        close=close_browser,
        is_connected=lambda: True,
    )
    context.browser = browser

    def launch(**kwargs):
        if launch_options is not None:
            launch_options.append(kwargs)
        return browser

    class Manager:
        def __enter__(self):
            return SimpleNamespace(
                chromium=SimpleNamespace(launch=launch)
            )

        def __exit__(self, *args):
            lifecycle.append("driver_stopped")

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(
            sync_playwright=Manager,
            Error=PlaywrightError,
            TimeoutError=PlaywrightTimeoutError,
        ),
    )
            lifecycle.append("driver_stopped")

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(
            sync_playwright=Manager,
            Error=PlaywrightError,
            TimeoutError=PlaywrightTimeoutError,
        ),
    )
    return lifecycle


def test_browser_closes_before_fetch_and_credentials_never_leave_worker(monkeypatch):
    lifecycle = install_fake_browser(monkeypatch)

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"total": 1, "records": [{"packageID": "case-one"}]}

        def close(self):
            lifecycle.append("response_closed")

    def get(url, **kwargs):
        assert lifecycle == ["context_closed", "browser_closed", "driver_stopped"]
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert kwargs["allow_redirects"] is False
        return Response()

    monkeypatch.setattr(requests, "get", get)
    messages = []
    result = auth._fetch_with_browser(
        DashboardConfig(),
        messages.append,
        threading.Event(),
        channel="msedge",
        inspect_only=False,
        sign_in_timeout=600,
    )
    assert result["fetch"]["pagination_validated"]
    assert result["records"] == [{"packageID": "case-one"}]
    assert TOKEN not in json.dumps([messages, result])
    assert lifecycle[-1] == "response_closed"


def test_mfa_tab_replacement_retains_exact_endpoint_capture_and_closes_before_fetch(
    monkeypatch,
):
    def unrelated_request(context, observe):
        event = request(
            "https://login.microsoftonline.com/oauth/token", header=f"Bearer {TOKEN}"
        )
        observe(event)
        return event

    def replace_login_tab(context, observe):
        context.pages = [SimpleNamespace()]  # No original login page survives.
        event = request(DEFAULT_API_URL + "?offset=0", header=f"Bearer {TOKEN}")
        observe(event)
        return event

    lifecycle = install_fake_browser(
        monkeypatch, capture=False, events=[unrelated_request, replace_login_tab]
    )

    def fetch(self):
        assert lifecycle == ["context_closed", "browser_closed", "driver_stopped"]
        return [{"packageID": "demo-after-mfa"}], {"pagination_validated": True}

    monkeypatch.setattr(WorkflowApiClient, "fetch_all_records", fetch)
    progress = []
    result = auth._fetch_with_browser(
        DashboardConfig(),
        progress.append,
        threading.Event(),
        channel="msedge",
        inspect_only=False,
        sign_in_timeout=600,
    )
    assert result["records"] == [{"packageID": "demo-after-mfa"}]
    assert progress == [("progress", "signin"), ("progress", "fetching")]
    assert TOKEN not in json.dumps([result, progress])


@pytest.mark.parametrize(
    "stage, expected",
    [
        ("navigation", "navigation"),
        ("wait", "signin"),
        ("closed", "closed"),
        ("cleanup", "browser_cleanup"),
    ],
)
def test_browser_stage_errors_are_fixed_and_never_forward_raw_exceptions(
    monkeypatch, capsys, stage, expected
):
    def fail_wait(context, observe):
        if stage == "closed":
            context.pages.clear()
            context.emit("close")
        raise PlaywrightError(TOKEN)

    lifecycle = install_fake_browser(
        monkeypatch,
        capture=stage == "cleanup",
        events=[fail_wait] if stage in ("wait", "closed") else [],
        navigation_error=PlaywrightError(TOKEN) if stage == "navigation" else None,
        cleanup_error=PlaywrightError(TOKEN) if stage == "cleanup" else None,
    )
    monkeypatch.setattr(auth.os, "setsid", lambda: None, raising=False)
    monkeypatch.setattr(
        WorkflowApiClient,
        "fetch_all_records",
        lambda self: pytest.fail("Fetching must not start"),
    )
    pipe = Pipe()
    ready = threading.Event()
    ready.set()
    auth._worker(
        DashboardConfig(), pipe, threading.Event(), ready, "msedge", False, 600
    )
    assert pipe.messages == [("progress", "signin"), ("error", expected)]
    assert lifecycle == ["context_closed", "browser_closed", "driver_stopped"]
    assert pipe.closed
    assert TOKEN not in repr(pipe.messages)
    assert TOKEN not in str(auth.BrowserAuthError(expected))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_cancellation_during_mfa_event_wait_remains_responsive(monkeypatch):
    cancelled = threading.Event()

    def cancel_wait(context, observe):
        cancelled.set()

    lifecycle = install_fake_browser(monkeypatch, capture=False, events=[cancel_wait])
    with pytest.raises(auth.BrowserAuthError) as error:
        auth._fetch_with_browser(
            DashboardConfig(),
            lambda message: None,
            cancelled,
            channel="msedge",
            inspect_only=False,
            sign_in_timeout=600,
        )
    assert error.value.code == "cancelled"
    assert lifecycle == ["context_closed", "browser_closed", "driver_stopped"]


def test_api_echo_of_token_is_rejected(monkeypatch):
    install_fake_browser(monkeypatch)
    monkeypatch.setattr(
        WorkflowApiClient,
        "fetch_all_records",
        lambda self: ([{"packageID": "one", "echo": TOKEN}], {}),
    )
    with pytest.raises(auth.BrowserAuthError) as error:
        auth._fetch_with_browser(
            DashboardConfig(),
            lambda value: None,
            threading.Event(),
            channel="msedge",
            inspect_only=False,
            sign_in_timeout=600,
        )
    assert error.value.code == "containment"
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("failure", ["timeout", "closed", "cancelled"])
def test_signin_failure_always_closes_browser(monkeypatch, failure):
    lifecycle = install_fake_browser(
        monkeypatch, capture=False, closed=failure == "closed"
    )
    cancel = threading.Event()
    if failure == "cancelled":
        cancel.set()
    with pytest.raises(auth.BrowserAuthError) as error:
        auth._fetch_with_browser(
            DashboardConfig(),
            lambda value: None,
            cancel,
            channel="msedge",
            inspect_only=False,
            sign_in_timeout=0 if failure == "timeout" else 600,
        )
    assert error.value.code == failure
    assert lifecycle == ["context_closed", "browser_closed", "driver_stopped"]


@pytest.mark.parametrize(
    "status, expected", [(401, "expired"), (403, "forbidden"), (500, "network")]
)
def test_credential_bearing_http_exceptions_are_not_forwarded(
    monkeypatch, status, expected
):
    monkeypatch.setattr(auth.os, "setsid", lambda: None, raising=False)

    def fail(*args, **kwargs):
        raise requests.HTTPError(TOKEN, response=SimpleNamespace(status_code=status))

    monkeypatch.setattr(auth, "_fetch_with_browser", fail)
    pipe = Pipe()
    ready = threading.Event()
    ready.set()
    auth._worker(
        DashboardConfig(), pipe, threading.Event(), ready, "msedge", False, 600
    )
    assert pipe.messages == [("error", expected)]
    assert pipe.closed
    assert TOKEN not in repr(pipe.messages)


@pytest.mark.parametrize(
    "exception, expected",
    [
        (requests.ConnectionError(TOKEN), "network"),
        (PaginationIntegrityError(TOKEN), "integrity"),
        (ValueError(TOKEN), "integrity"),
        (RuntimeError(TOKEN), "browser"),
    ],
)
def test_worker_errors_use_fixed_messages(monkeypatch, exception, expected):
    monkeypatch.setattr(auth.os, "setsid", lambda: None, raising=False)

    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(auth, "_fetch_with_browser", fail)
    pipe = Pipe()
    ready = threading.Event()
    ready.set()
    auth._worker(
        DashboardConfig(), pipe, threading.Event(), ready, "msedge", False, 600
    )
    assert pipe.messages == [("error", expected)]
    assert TOKEN not in str(auth.BrowserAuthError(expected))


# Top-level targets are importable by real spawned processes on Windows and macOS.
def success_worker(config, pipe, cancel, ready, channel, inspect_only, timeout):
    if os.name != "nt":
        os.setsid()
    ready.wait(10)
    pipe.send(
        (
            "result",
            {
                "pid": os.getpid(),
                "credential_free": config.api_token is None,
                "headers": config.headers,
            },
        )
    )
    pipe.close()
    time.sleep(0.25)  # Closing the pipe alone must not unblock rendering.


def waiting_worker(config, pipe, cancel, ready, channel, inspect_only, timeout):
    if os.name != "nt":
        os.setsid()
    ready.wait(10)
    pipe.send(("progress", "signin"))
    while True:
        time.sleep(0.1)


def failed_worker(config, pipe, cancel, ready, channel, inspect_only, timeout):
    if os.name != "nt":
        os.setsid()
    ready.wait(10)
    pipe.close()  # Simulate abrupt exit without a result.


def test_real_spawn_is_reaped_before_result_is_returned(monkeypatch):
    monkeypatch.setattr(auth, "_worker", success_worker)
    start = time.monotonic()
    result = auth.browser_fetch(
        DashboardConfig(
            api_token=TOKEN,
            headers={"Authorization": TOKEN, "Accept": "application/json"},
        )
    )
    assert time.monotonic() - start >= 0.25
    assert result["credential_free"]
    assert result["headers"] == {"Accept": "application/json"}
    assert TOKEN not in json.dumps(result)
    assert not any(
        child.pid == result["pid"] for child in multiprocessing.active_children()
    )


def test_cancel_reaps_real_worker(monkeypatch):
    monkeypatch.setattr(auth, "_worker", waiting_worker)
    cancelled = threading.Event()
    with pytest.raises(auth.BrowserAuthError) as error:
        auth.browser_fetch(
            DashboardConfig(), cancel=cancelled, progress=lambda stage: cancelled.set()
        )
    assert error.value.code == "cancelled"
    assert not multiprocessing.active_children()


def test_worker_without_result_aborts(monkeypatch):
    monkeypatch.setattr(auth, "_worker", failed_worker)
    with pytest.raises(auth.BrowserAuthError) as error:
        auth.browser_fetch(DashboardConfig())
    assert error.value.code == "worker"
    assert not multiprocessing.active_children()


def test_no_publication_when_fetch_fails(monkeypatch, tmp_path):
    config = DashboardConfig(
        output_dir=tmp_path / "outputs", history_db_path=tmp_path / "history.sqlite"
    )

    def fail(*args, **kwargs):
        raise auth.BrowserAuthError("expired")

    monkeypatch.setattr(desktop, "browser_fetch", fail)
    monkeypatch.setattr(
        desktop,
        "generate_dashboard",
        lambda *args, **kwargs: pytest.fail("rendering started"),
    )
    with pytest.raises(auth.BrowserAuthError):
        desktop.fetch_and_generate(config)
    assert list(tmp_path.iterdir()) == []


def test_service_rejects_credentials_before_writing_files(tmp_path):
    with pytest.raises(ValueError, match="credential-free"):
        generate_dashboard(
            DashboardConfig(api_token=TOKEN, output_dir=tmp_path), [], {}
        )
    assert list(tmp_path.iterdir()) == []


def test_desktop_settings_cannot_load_credentials(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text(f'api_token = "{TOKEN}"\n')
    with pytest.raises(ValueError) as error:
        desktop.desktop_config(settings)
    assert TOKEN not in str(error.value)


def test_desktop_paths_are_local_and_default_preset_is_nonsecret(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "application_directory", lambda: tmp_path)
    monkeypatch.setenv("WORKFLOW_API_TOKEN", TOKEN)
    config = desktop.desktop_config()
    # The bundled nonsecret preset may be customized before a Windows build.
    preset = tomllib.loads(
        Path(desktop.__file__)
        .with_name("desktop_settings.toml")
        .read_text(encoding="utf-8")
    )
    root = Path(preset.get("data_directory", tmp_path))
    assert config.api_token is None
    assert config.output_dir == root / "outputs"
    assert config.history_db_path == root / "history" / "workflow_history.sqlite"
    assert config.workflow_filter == preset["workflow_filter"]


def result_then_crash_worker(
    config, pipe, cancel, ready, channel, inspect_only, timeout
):
    if os.name != "nt":
        os.setsid()
    ready.wait(10)
    pipe.send(("result", {"records": [], "fetch": {}}))
    pipe.close()
    time.sleep(0.25)  # The pipe can close before the process exit is observable.
    raise SystemExit(4)


def test_result_from_worker_with_failed_exit_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "_worker", result_then_crash_worker)
    with pytest.raises(auth.BrowserAuthError) as error:
        auth.browser_fetch(DashboardConfig())
    assert error.value.code == "worker"
    assert not multiprocessing.active_children()


@pytest.mark.parametrize(
    "target, expected",
    [
        (success_worker, None),
        (result_then_crash_worker, "worker"),
    ],
)
def test_terminal_result_does_not_poll_closed_windows_pipe(
    monkeypatch, target, expected
):
    real_context = multiprocessing.get_context("spawn")

    class Receive:
        terminal_received = False

        def poll(self, timeout=0):
            if self.terminal_received:
                # Windows PeekNamedPipe raises after the worker closes its end.
                raise BrokenPipeError("synthetic closed Windows pipe")
            return receive.poll(timeout)

        def recv(self):
            value = receive.recv()
            self.terminal_received = value[0] in ("result", "error")
            return value

        def close(self):
            receive.close()

    receive, send = real_context.Pipe(duplex=False)
    context = SimpleNamespace(
        Event=real_context.Event,
        Process=real_context.Process,
        Pipe=lambda **kwargs: (Receive(), send),
    )
    monkeypatch.setattr(auth, "mp", SimpleNamespace(get_context=lambda method: context))
    monkeypatch.setattr(auth, "_worker", target)
    start = time.monotonic()
    if expected is None:
        result = auth.browser_fetch(DashboardConfig())
        assert time.monotonic() - start >= 0.25
        assert not any(
            child.pid == result["pid"] for child in multiprocessing.active_children()
        )
    else:
        with pytest.raises(auth.BrowserAuthError) as error:
            auth.browser_fetch(DashboardConfig())
        assert error.value.code == expected
    assert not multiprocessing.active_children()


@pytest.mark.parametrize("operation", ["poll", "recv"])
def test_pipe_failure_before_result_is_worker_failure(monkeypatch, operation):
    real_context = multiprocessing.get_context("spawn")
    receive, send = real_context.Pipe(duplex=False)

    def fail(*args):
        raise BrokenPipeError("synthetic-private-pipe-error")

    wrapped = SimpleNamespace(
        poll=fail if operation == "poll" else lambda *args: True,
        recv=fail,
        close=receive.close,
    )
    context = SimpleNamespace(
        Event=real_context.Event,
        Process=real_context.Process,
        Pipe=lambda **kwargs: (wrapped, send),
    )
    monkeypatch.setattr(auth, "mp", SimpleNamespace(get_context=lambda method: context))
    monkeypatch.setattr(auth, "_worker", waiting_worker)
    with pytest.raises(auth.BrowserAuthError) as error:
        auth.browser_fetch(DashboardConfig())
    assert error.value.code == "worker"
    assert "synthetic-private" not in str(error.value)
    assert not multiprocessing.active_children()


def test_supervision_failure_remains_policy_failure_and_reaps_worker(monkeypatch):
    def deny(pid):
        raise OSError("synthetic-private-policy-error")

    monkeypatch.setattr(
        auth, "ProcessGuard", lambda: SimpleNamespace(attach=deny, close=lambda: None)
    )
    monkeypatch.setattr(auth, "_worker", waiting_worker)
    with pytest.raises(auth.BrowserAuthError) as error:
        auth.browser_fetch(DashboardConfig())
    assert error.value.code == "policy"
    assert "synthetic-private" not in str(error.value)
    assert not multiprocessing.active_children()


def test_parent_failure_still_reaps_worker(monkeypatch):
    monkeypatch.setattr(auth, "_worker", waiting_worker)

    def broken_progress(stage):
        raise RuntimeError("UI closed")

    with pytest.raises(RuntimeError, match="UI closed"):
        auth.browser_fetch(DashboardConfig(), progress=broken_progress)
    assert not multiprocessing.active_children()


def test_render_follows_completed_fetch_and_cancel_does_not_render(monkeypatch):
    events = []
    config = DashboardConfig()

    def fetch(*args, **kwargs):
        events.append("worker_reaped")
        return {"records": [], "fetch": {}}

    def render(*args, **kwargs):
        assert events == ["worker_reaped", "generating"]
        return {"outputs": {}}

    monkeypatch.setattr(desktop, "browser_fetch", fetch)
    monkeypatch.setattr(desktop, "generate_dashboard", render)
    desktop.fetch_and_generate(config, progress=events.append)
    events.clear()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(auth.BrowserAuthError):
        desktop.fetch_and_generate(config, cancel=cancelled)
    assert events == ["worker_reaped"]


def test_redirect_is_rejected_and_response_closed(monkeypatch):
    from workflow_dashboard.api_client import ApiConfigurationError

    closed = []
    response = SimpleNamespace(status_code=302, close=lambda: closed.append(True))

    def get(*args, **kwargs):
        assert kwargs["allow_redirects"] is False
        return response

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ApiConfigurationError, match="redirected"):
        WorkflowApiClient(DashboardConfig(), bearer_token=TOKEN).fetch_page()
    assert closed == [True]


def test_browser_mode_rejects_credentials_in_configured_url():
    with pytest.raises(auth.BrowserAuthError) as error:
        auth.browser_fetch(
            DashboardConfig(api_url=DEFAULT_API_URL + "?access_token=" + TOKEN)
        )
    assert error.value.code == "endpoint"
    assert TOKEN not in str(error.value)


def test_cli_defaults_to_browser_and_fixture_does_not_launch_it(
    monkeypatch, tmp_path, capsys
):
    from workflow_dashboard import __main__ as cli

    assert cli.build_parser().parse_args(["run", "--source", "api"]).auth == "browser"
    assert (
        cli.build_parser().parse_args(["run", "--source", "api", "--auth", "env"]).auth
        == "env"
    )
    fixture = tmp_path / "fixture.json"
    fixture.write_text('{"total": 0, "records": []}')
    monkeypatch.setattr(
        cli, "browser_fetch", lambda *args, **kwargs: pytest.fail("browser launched")
    )
    assert cli.main(["inspect", "--fixture-path", str(fixture)]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "fixture"


def test_generated_artifacts_and_history_contain_no_bearer(monkeypatch, tmp_path):
    install_fake_browser(monkeypatch)
    case = {
        "packageID": "case-one",
        "workflowName": "Workflow A",
        "stepName": "End",
        "status": "Completed",
        "submissionDate": "2026-09-29T09:00:00",
        "lastActivityDate": "2026-09-30T10:00:00",
        "submittedBy": "Fixture Worker",
    }

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"total": 1, "records": [case]}

        def close(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    config = DashboardConfig(
        workflow_filter="Workflow A",
        output_dir=tmp_path / "outputs",
        history_db_path=tmp_path / "history.sqlite",
    )
    fetched = auth._fetch_with_browser(
        config,
        lambda value: None,
        threading.Event(),
        channel="msedge",
        inspect_only=False,
        sign_in_timeout=600,
    )
    result = generate_dashboard(config, fetched["records"], fetched["fetch"])
    assert result["records"] == 1
    assert set(result["outputs"]) == {"html", "excel", "csv", "history_db"}
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes()
    assert TOKEN not in json.dumps(result)


def test_broken_result_pipe_does_not_print_credential_bearing_exception(
    monkeypatch, capsys
):
    monkeypatch.setattr(auth.os, "setsid", lambda: None, raising=False)

    def fail(*args, **kwargs):
        raise requests.HTTPError(TOKEN, response=SimpleNamespace(status_code=401))

    monkeypatch.setattr(auth, "_fetch_with_browser", fail)

    class BrokenPipe(Pipe):
        def send(self, value):
            raise BrokenPipeError("parent exited")

    pipe = BrokenPipe()
    ready = threading.Event()
    ready.set()
    auth._worker(
        DashboardConfig(), pipe, threading.Event(), ready, "msedge", False, 600
    )
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert pipe.closed


@pytest.mark.parametrize("replacement_at", [2.1, 9.9])
def test_empty_tab_gap_allows_replacement_until_ten_seconds(
    monkeypatch, replacement_at
):
    clock = Clock()

    def replace(context, observe):
        # Delivery happens near the end of the grace period, after a real gap.
        clock.now = replacement_at
        page = SimpleNamespace(on=lambda *args: None)
        context.pages = [page]
        context.emit("page", page)
        event = request(header=f"Bearer {TOKEN}")
        observe(event)
        return event

    lifecycle = install_fake_browser(
        monkeypatch, capture=False, closed=True, events=[replace], clock=clock
    )

    def fetch(self):
        assert lifecycle == ["context_closed", "browser_closed", "driver_stopped"]
        return [], {"pagination_validated": True}

    monkeypatch.setattr(WorkflowApiClient, "fetch_all_records", fetch)
    result = auth._fetch_with_browser(
        DashboardConfig(),
        lambda _: None,
        threading.Event(),
        channel="msedge",
        inspect_only=False,
        sign_in_timeout=600,
    )
    assert result["fetch"]["pagination_validated"]
    assert clock.now == replacement_at


@pytest.mark.parametrize(
    "timeout, expected, elapsed", [(600, "closed", 10), (3, "timeout", 3)]
)
def test_empty_tab_wait_is_bounded_by_grace_and_signin_deadline(
    monkeypatch, timeout, expected, elapsed
):
    clock = Clock()
    install_fake_browser(monkeypatch, capture=False, closed=True, clock=clock)
    with pytest.raises(auth.BrowserAuthError) as error:
        auth._fetch_with_browser(
            DashboardConfig(),
            lambda _: None,
            threading.Event(),
            channel="msedge",
            inspect_only=False,
            sign_in_timeout=timeout,
        )
    assert error.value.code == expected
    assert clock.now == pytest.approx(elapsed)


@pytest.mark.parametrize("event", ["disconnect", "context_close", "cancel"])
def test_empty_tab_wait_stops_promptly_on_terminal_event(monkeypatch, event):
    clock = Clock()
    cancel = threading.Event()

    def stop(context, observe):
        if event == "cancel":
            cancel.set()
        elif event == "disconnect":
            context.browser.emit("disconnected")
        else:
            context.emit("close")

    install_fake_browser(
        monkeypatch, capture=False, closed=True, clock=clock, events=[stop]
    )
    with pytest.raises(auth.BrowserAuthError) as error:
        auth._fetch_with_browser(
            DashboardConfig(),
            lambda _: None,
            cancel,
            channel="msedge",
            inspect_only=False,
            sign_in_timeout=600,
        )
    assert error.value.code == ("cancelled" if event == "cancel" else "closed")
    assert clock.now == pytest.approx(0.1)


def test_replacement_page_resets_empty_tab_grace(monkeypatch):
    clock = Clock()

    def replace(context, observe):
        clock.now = 9
        page = SimpleNamespace(on=lambda *args: None)
        context.pages = [page]
        context.emit("page", page)

    def close_replacement(context, observe):
        context.pages.clear()

    install_fake_browser(
        monkeypatch,
        capture=False,
        closed=True,
        clock=clock,
        events=[replace, close_replacement],
    )
    with pytest.raises(auth.BrowserAuthError) as error:
        auth._fetch_with_browser(
            DashboardConfig(),
            lambda _: None,
            threading.Event(),
            channel="msedge",
            inspect_only=False,
            sign_in_timeout=600,
        )
    assert error.value.code == "closed"
    assert clock.now == pytest.approx(19.1)


@pytest.mark.parametrize("channel", ["msedge", "chrome"])
def test_edge_signin_restores_automation_launch_flag(monkeypatch, channel):
    launches = []
    lifecycle = install_fake_browser(monkeypatch, launch_options=launches)

    def fetch(self):
        assert lifecycle == ["context_closed", "browser_closed", "driver_stopped"]
        return [], {"pagination_validated": True}

    monkeypatch.setattr(WorkflowApiClient, "fetch_all_records", fetch)
    result = auth._fetch_with_browser(
        DashboardConfig(), lambda _: None, threading.Event(),
        channel=channel, inspect_only=False, sign_in_timeout=600,
    )
    expected = {"channel": channel, "headless": False}
    if channel == "msedge":
        expected["args"] = ["--enable-automation"]
    assert launches == [expected]
    assert result["fetch"]["pagination_validated"]
