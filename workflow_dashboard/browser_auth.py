"""Ephemeral browser authentication. Credentials never cross the worker pipe."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from dataclasses import replace
from typing import Callable
from urllib.parse import urlsplit

import requests

from .api_client import (
    ApiConfigurationError,
    ApiCredentialDisclosureError,
    PaginationIntegrityError,
    WorkflowApiClient,
    inspect_payload,
)
from .config import DashboardConfig, DEFAULT_API_URL, is_secure_api_url
from .process_guard import ProcessGuard
from .diagnostics import (
    capture,
    emit,
    bind_emitter,
    enabled,
    operation,
    validate_event,
    accept_worker_event,
    MAX_EVENTS,
)

SIGN_IN_TIMEOUT = 600
EMPTY_TAB_GRACE_SECONDS = 10
EMPTY_TAB_GRACE_SECONDS = 10
MESSAGES = {
    "cancelled": "Generation cancelled. No dashboard was created.",
    "timeout": "Sign-in timed out. Click Generate Dashboard to try again.",
    "closed": "The browser session ended before workflow access was available. Start again to sign in.",
    "expired": "Your eTrieve session expired. Sign in again; fetching will restart from the beginning.",
    "forbidden": "Your account cannot access these workflow records. Contact your eTrieve administrator.",
    "network": "Cannot reach the workflow API. Check your network and try again.",
    "integrity": "The API returned incomplete or malformed records. Nothing was generated; try again.",
    "browser": "Cannot complete browser sign-in. Check that the selected browser is installed and workplace policy permits automation.",
    "navigation": "The sign-in page could not open. Check the configured tenant URL and your network, then try again.",
    "signin": "The browser session failed while waiting for workflow access after sign-in. Start again and complete MFA in the app's separate browser window.",
    "browser_cleanup": "The sign-in browser did not close safely. Nothing was generated; start again to try a fresh sign-in.",
    "dependency": "Browser sign-in requires Playwright. Install the application dependencies.",
    "endpoint": "Browser sign-in supports only the configured HTTPS workflow packages endpoint.",
    "redirect": "The workflow API redirected to sign-in. Start a fresh session and try again.",
    "containment": "The API response contained authentication material and was rejected.",
    "worker": "The authentication worker did not finish safely. Nothing was generated; try again.",
    "policy": "Cannot safely supervise the sign-in browser on this device. Contact your administrator.",
}


class BrowserAuthError(ApiConfigurationError):
    def __init__(self, code: str):
        self.code = code if code in MESSAGES else "worker"
        super().__init__(MESSAGES[self.code])


def is_packages_request(url: str, *, api_url: str = DEFAULT_API_URL) -> bool:
    """Match the exact trusted endpoint, not suffixes or lookalike hosts."""
    try:
        if not is_secure_api_url(api_url):
            return False
        actual, expected = urlsplit(url), urlsplit(api_url)
        return (
            actual.scheme == "https"
            and actual.hostname == expected.hostname
            and actual.port in (None, 443)
            and actual.path == expected.path
            and actual.username is None
            and actual.password is None
            and not actual.fragment
        )
    except ValueError:
        return False


def bearer_from_request(request, *, api_url: str = DEFAULT_API_URL) -> str | None:
    if request.method != "GET" or not is_packages_request(request.url, api_url=api_url):
        return None
    header = request.header_value("authorization")
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].casefold() != "bearer":
        return None
    return parts[1]


def _fetch_with_browser(
    config, send, cancel, *, channel, inspect_only, sign_in_timeout
):
    try:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )
    except ImportError:
        raise BrowserAuthError("dependency") from None
    token = None
    client = None
    context_closed = False
    disconnected = False
    cleanup_started = False
    empty_since = None
    emit_callback = bind_emitter()

    def lifecycle(code):
        emit_callback(code, closure_phase="cleanup" if cleanup_started else "signin")

    def on_disconnect(*_):
        nonlocal disconnected
        disconnected = True
        lifecycle("browser.disconnected")

    def on_context_close(*_):
        nonlocal context_closed
        context_closed = True
        lifecycle("browser.context.closed")

    def on_page(page):
        nonlocal empty_since
        empty_since = None
        lifecycle("browser.page.opened")
        page.on("close", lambda *_: lifecycle("browser.page.closed"))
        page.on("crash", lambda *_: lifecycle("browser.page.crashed"))

    def closure_reason():
        if disconnected or not browser.is_connected():
            return "disconnected"
        if context_closed:
            return "context_closed"
        return None

    def close_browser_resource(resource):
        nonlocal cleanup_started
        cleanup_started = True
        name = "browser.context_close" if resource is context else "browser.close"
        try:
            with operation(name):
                resource.close()
        except PlaywrightError:
            raise BrowserAuthError("browser_cleanup") from None

    try:
        send(("progress", "signin"))
        with sync_playwright() as playwright:
            with operation("browser.launch"):
                browser = playwright.chromium.launch(channel=channel, headless=False)
            version = getattr(browser, "version", None)
            if type(version) is str:
                emit("browser.version", browser_version=version)
            context = None
            try:
                browser.on("disconnected", on_disconnect)
                with operation("browser.context"):
                    context = browser.new_context(accept_downloads=False)
                try:

                    def observe(request):
                        nonlocal token
                        if token is None:
                            token = bearer_from_request(request, api_url=config.api_url)
                            if token is not None:
                                emit_callback("credential.observed")

                    context.on("request", observe)
                    context.on("close", on_context_close)
                    context.on("page", on_page)
                    page = context.new_page()
                    deadline = time.monotonic() + sign_in_timeout
                    endpoint = urlsplit(config.api_url)
                    login_url = f"https://{endpoint.netloc}"
                    try:
                        # Observe the rest of SSO/MFA through the context rather
                        # than waiting for a particular login document to load.
                        with operation("browser.navigate"):
                            page.goto(login_url, wait_until="commit", timeout=30_000)
                    except PlaywrightError:
                        raise BrowserAuthError("navigation") from None
                    empty_since = None
                    reason = None
                    emit("browser.observe.start")
                    try:
                        while token is None:
                            if cancel.is_set():
                                raise BrowserAuthError("cancelled")
                            now = time.monotonic()
                            if now >= deadline:
                                raise BrowserAuthError("timeout")
                            reason = closure_reason()
                            if reason:
                                raise BrowserAuthError("closed")
                            wait_deadline = deadline
                            if context.pages:
                                empty_since = None
                            else:
                                if empty_since is None:
                                    empty_since = now
                                wait_deadline = min(
                                    deadline, empty_since + EMPTY_TAB_GRACE_SECONDS
                                )
                                if now >= wait_deadline:
                                    reason = "no_pages"
                                    raise BrowserAuthError("closed")
                            try:
                                with context.expect_event(
                                    "request",
                                    predicate=lambda request: token is not None,
                                    timeout=min(100, (wait_deadline - now) * 1000),
                                ):
                                    pass
                            except PlaywrightTimeoutError:
                                pass
                            except PlaywrightError:
                                reason = closure_reason()
                                code = "closed" if reason else "signin"
                                reason = reason or "observation_error"
                                raise BrowserAuthError(code) from None
                    except BrowserAuthError as error:
                        details = {"auth_code": error.code}
                        if reason is not None:
                            details["reason"] = reason
                        emit("browser.observe.failed", **details)
                        raise
                    except BaseException as error:
                        emit(
                            "browser.observe.failed",
                            error=error,
                            reason="observation_error",
                        )
                        raise
                    else:
                        emit("browser.observe.done")
                finally:
                    close_browser_resource(context)
            finally:
                close_browser_resource(browser)
        emit("browser.driver_close.done")

        def check_cancel():
            if cancel.is_set():
                raise BrowserAuthError("cancelled")
            send(("progress", "fetching"))

        client = WorkflowApiClient(
            config, bearer_token=token, before_request=check_cancel
        )
        if inspect_only:
            page = client.fetch_page(offset=0, take=config.api_take)
            client._validate_page_payload(page, page_number=1)
            result = inspect_payload(page.raw, source="api")
            result["pagination"] = {
                "requested_take": config.api_take,
                "reported_total": page.total,
                "first_page_records": len(page.records),
            }
        else:
            records, metadata = client.fetch_all_records()
            result = {"records": records, "fetch": metadata}
        # Do not forward an API response that echoes the bearer into records or metadata.
        serialized = json.dumps(result, ensure_ascii=True)
        if json.dumps(token, ensure_ascii=True)[1:-1] in serialized:
            raise BrowserAuthError("containment")
        check_cancel()
        return result
    finally:
        if client is not None:
            client.close()
        token = None


def _worker(
    config,
    send_pipe,
    cancel,
    ready,
    channel,
    inspect_only,
    sign_in_timeout,
    *,
    diagnostics_enabled=False,
):
    """No raw exception objects, tracebacks, request objects, or headers leave here."""
    if os.name != "nt":
        os.setsid()
    for name in (
        "DEBUG",
        "PWDEBUG",
        "WORKFLOW_API_TOKEN",
        "ETRIEVE_API_TOKEN",
        "SSLKEYLOGFILE",
        "CHROME_LOG_FILE",
    ):
        os.environ.pop(name, None)

    def progress(message):
        try:
            send_pipe.send(message)
        except (OSError, EOFError):
            raise BrowserAuthError("cancelled") from None

    def diagnostic(event):
        safe = validate_event(event)
        if safe is not None:
            progress(("diagnostic", safe))

    try:
        if not ready.wait(30):
            raise BrowserAuthError("policy")
        with capture(diagnostic if diagnostics_enabled else None, bounded=True):
            result = _fetch_with_browser(
                config,
                progress,
                cancel,
                channel=channel,
                inspect_only=inspect_only,
                sign_in_timeout=sign_in_timeout,
            )
        outcome = ("result", result)
    except BrowserAuthError as exc:
        outcome = ("error", exc.code)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        outcome = ("error", {401: "expired", 403: "forbidden"}.get(status, "network"))
    except ApiCredentialDisclosureError:
        outcome = ("error", "containment")
    except ApiConfigurationError:
        outcome = ("error", "redirect")
    except requests.exceptions.JSONDecodeError:
        outcome = ("error", "integrity")
    except requests.RequestException:
        outcome = ("error", "network")
    except (PaginationIntegrityError, ValueError):
        outcome = ("error", "integrity")
    except BaseException:
        outcome = ("error", "browser")
    # Send outside exception handlers so a transport failure cannot expose
    # credential-bearing traceback context.
    try:
        send_pipe.send(outcome)
    except (OSError, EOFError):
        pass
    finally:
        send_pipe.close()


def browser_fetch(
    config: DashboardConfig,
    *,
    cancel=None,
    progress: Callable[[str], None] | None = None,
    channel="msedge",
    inspect_only=False,
    sign_in_timeout=SIGN_IN_TIMEOUT,
    diagnostics=None,
):
    with capture(diagnostics):
        return _browser_fetch(
            config,
            cancel=cancel,
            progress=progress,
            channel=channel,
            inspect_only=inspect_only,
            sign_in_timeout=sign_in_timeout,
        )


def _browser_fetch(config, *, cancel, progress, channel, inspect_only, sign_in_timeout):
    """Return only after the worker and its browser descendants have exited."""
    if not is_packages_request(config.api_url, api_url=config.api_url):
        raise BrowserAuthError("endpoint")
    # Never transfer legacy credentials or arbitrary caller-supplied auth headers.
    safe_config = replace(
        config,
        api_token=None,
        headers={
            k: v
            for k, v in config.headers.items()
            if k.casefold() in ("accept", "user-agent")
        },
    )
    ctx = mp.get_context("spawn")
    cancelled = ctx.Event()
    ready = ctx.Event()
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_worker,
        args=(
            safe_config,
            send,
            cancelled,
            ready,
            channel,
            inspect_only,
            sign_in_timeout,
        ),
        kwargs={"diagnostics_enabled": True} if enabled() else {},
    )
    guard = None
    started = False
    terminal = None
    terminal_time = None
    deadline = time.monotonic() + sign_in_timeout + 1800
    diagnostic_count = 0
    try:
        try:
            guard = ProcessGuard()
        except OSError:
            raise BrowserAuthError("policy") from None
        with operation("worker.start"):
            process.start()
        started = True
        send.close()
        try:
            with operation("worker.attach"):
                guard.attach(process.pid)
        except OSError:
            raise BrowserAuthError("policy") from None
        ready.set()  # Worker cannot launch a browser before tree supervision is attached.
        while True:
            if cancel is not None and cancel.is_set():
                cancelled.set()
                raise BrowserAuthError("cancelled")
            if time.monotonic() >= deadline:
                raise BrowserAuthError("timeout")
            # A terminal message is the last pipe message. Wait for the process
            # separately: polling a closed Windows named pipe can raise OSError.
            if terminal is None:
                try:
                    has_message = receive.poll(0.1)
                    if not has_message and not process.is_alive():
                        # Drain a message sent between the timed poll and exit.
                        has_message = receive.poll()
                        if not has_message:
                            emit("worker.transport.failed")
                            raise BrowserAuthError("worker")
                    if has_message:
                        message = receive.recv()
                        if (
                            type(message) is not tuple
                            or len(message) != 2
                            or type(message[0]) is not str
                        ):
                            emit("worker.transport.failed")
                            raise BrowserAuthError("worker")
                        kind, value = message
                except (EOFError, OSError) as error:
                    emit("worker.transport.failed", error=error)
                    raise BrowserAuthError("worker") from None
                if has_message:
                    if kind == "diagnostic":
                        diagnostic_count += 1
                        safe = validate_event(value)
                        if safe is None or diagnostic_count > MAX_EVENTS:
                            emit("worker.transport.failed")
                            raise BrowserAuthError("worker")
                        # The parent collector receives primitives only, after
                        # independent validation of the credential worker's data.
                        if not accept_worker_event(safe):
                            emit("worker.transport.failed")
                            raise BrowserAuthError("worker")
                    elif kind == "progress":
                        if type(value) is not str or value not in (
                            "signin",
                            "fetching",
                        ):
                            emit("worker.transport.failed")
                            raise BrowserAuthError("worker")
                        if progress is not None:
                            progress(value)
                    elif kind in ("result", "error"):
                        if kind == "error" and (
                            type(value) is not str or value not in MESSAGES
                        ):
                            emit("worker.transport.failed")
                            raise BrowserAuthError("worker")
                        if kind == "result" and type(value) is not dict:
                            emit("worker.transport.failed")
                            raise BrowserAuthError("worker")
                        terminal = (kind, value)
                        terminal_time = time.monotonic()
                    else:
                        emit("worker.transport.failed")
                        raise BrowserAuthError("worker")
            if terminal is not None:
                process.join(0.1)
                if not process.is_alive():
                    break
                if time.monotonic() - terminal_time > 10:
                    raise BrowserAuthError("worker")
        if process.exitcode != 0:
            emit("worker.exit.failed", exit_code=process.exitcode)
            raise BrowserAuthError("worker")
        emit("worker.exit.done", exit_code=process.exitcode)
        guard.close()
        if terminal[0] == "error":
            emit(
                "attempt.failed",
                auth_code=terminal[1] if terminal[1] in MESSAGES else "worker",
            )
            raise BrowserAuthError(terminal[1])
        return terminal[1]
    except OSError:
        raise BrowserAuthError("worker") from None
    finally:
        cancelled.set()
        with operation("worker.cleanup"):
            try:
                if guard is not None:
                    guard.close()
            finally:
                try:
                    if started:
                        process.join(1)
                        if process.is_alive():
                            process.kill()
                            process.join(5)
                        process.close()
                finally:
                    receive.close()
                    send.close()
