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

SIGN_IN_TIMEOUT = 600
MESSAGES = {
    "cancelled": "Generation cancelled. No dashboard was created.",
    "timeout": "Sign-in timed out. Click Generate Dashboard to try again.",
    "closed": "The sign-in browser was closed. Start again to sign in.",
    "expired": "Your eTrieve session expired. Sign in again; fetching will restart from the beginning.",
    "forbidden": "Your account cannot access these workflow records. Contact your eTrieve administrator.",
    "network": "Cannot reach the workflow API. Check your network and try again.",
    "integrity": "The API returned incomplete or malformed records. Nothing was generated; try again.",
    "browser": "Cannot complete browser sign-in. Check that the selected browser is installed and workplace policy permits automation.",
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
        return (actual.scheme == "https" and actual.hostname == expected.hostname
                and actual.port in (None, 443) and actual.path == expected.path
                and actual.username is None and actual.password is None and not actual.fragment)
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


def _fetch_with_browser(config, send, cancel, *, channel, inspect_only, sign_in_timeout):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserAuthError("dependency") from None
    token = None
    client = None
    try:
        send(("progress", "signin"))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=channel, headless=False)
            try:
                context = browser.new_context(accept_downloads=False)
                try:
                    def observe(request):
                        nonlocal token
                        if token is None:
                            token = bearer_from_request(request, api_url=config.api_url)

                    context.on("request", observe)
                    page = context.new_page()
                    deadline = time.monotonic() + sign_in_timeout
                    endpoint = urlsplit(config.api_url)
                    login_url = f"https://{endpoint.netloc}"
                    page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)
                    while token is None:
                        if cancel.is_set():
                            raise BrowserAuthError("cancelled")
                        if time.monotonic() >= deadline:
                            raise BrowserAuthError("timeout")
                        if not browser.is_connected() or not context.pages:
                            raise BrowserAuthError("closed")
                        # Pump Playwright events while the user completes sign-in.
                        context.pages[0].wait_for_timeout(100)
                finally:
                    context.close()
            finally:
                browser.close()

        def check_cancel():
            if cancel.is_set():
                raise BrowserAuthError("cancelled")
            send(("progress", "fetching"))

        client = WorkflowApiClient(config, bearer_token=token, before_request=check_cancel)
        if inspect_only:
            page = client.fetch_page(offset=0, take=config.api_take)
            client._validate_page_payload(page, page_number=1)
            result = inspect_payload(page.raw, source="api")
            result["pagination"] = {"requested_take": config.api_take,
                                    "reported_total": page.total, "first_page_records": len(page.records)}
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


def _worker(config, send_pipe, cancel, ready, channel, inspect_only, sign_in_timeout):
    """No raw exception objects, tracebacks, request objects, or headers leave here."""
    if os.name != "nt":
        os.setsid()
    for name in ("DEBUG", "PWDEBUG", "WORKFLOW_API_TOKEN", "ETRIEVE_API_TOKEN", "SSLKEYLOGFILE", "CHROME_LOG_FILE"):
        os.environ.pop(name, None)

    def progress(message):
        try:
            send_pipe.send(message)
        except (OSError, EOFError):
            raise BrowserAuthError("cancelled") from None

    try:
        if not ready.wait(30):
            raise BrowserAuthError("policy")
        result = _fetch_with_browser(config, progress, cancel, channel=channel,
                                    inspect_only=inspect_only, sign_in_timeout=sign_in_timeout)
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


def browser_fetch(config: DashboardConfig, *, cancel=None, progress: Callable[[str], None] | None = None,
                  channel="msedge", inspect_only=False, sign_in_timeout=SIGN_IN_TIMEOUT):
    """Return only after the worker and its browser descendants have exited."""
    if not is_packages_request(config.api_url, api_url=config.api_url):
        raise BrowserAuthError("endpoint")
    # Never transfer legacy credentials or arbitrary caller-supplied auth headers.
    safe_config = replace(config, api_token=None,
                          headers={k: v for k, v in config.headers.items()
                                   if k.casefold() in ("accept", "user-agent")})
    ctx = mp.get_context("spawn")
    cancelled = ctx.Event()
    ready = ctx.Event()
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_worker,
                         args=(safe_config, send, cancelled, ready, channel, inspect_only, sign_in_timeout))
    guard = None
    started = False
    terminal = None
    terminal_time = None
    deadline = time.monotonic() + sign_in_timeout + 1800
    try:
        guard = ProcessGuard()
        process.start()
        started = True
        send.close()
        guard.attach(process.pid)
        ready.set()  # Worker cannot launch a browser before tree supervision is attached.
        while True:
            if cancel is not None and cancel.is_set():
                cancelled.set()
                raise BrowserAuthError("cancelled")
            if time.monotonic() >= deadline:
                raise BrowserAuthError("timeout")
            if receive.poll(0.1):
                try:
                    kind, value = receive.recv()
                except EOFError:
                    if terminal is None:
                        raise BrowserAuthError("worker") from None
                else:
                    if kind == "progress":
                        if progress is not None:
                            progress(value)
                    elif kind in ("result", "error"):
                        terminal = (kind, value)
                        terminal_time = time.monotonic()
                    else:
                        raise BrowserAuthError("worker")
            if terminal is not None:
                process.join(0.1)
                if not process.is_alive():
                    break
                if time.monotonic() - terminal_time > 10:
                    raise BrowserAuthError("worker")
            elif not process.is_alive():
                # Drain a final message sent immediately before worker exit.
                if not receive.poll():
                    raise BrowserAuthError("worker")
        if process.exitcode != 0:
            raise BrowserAuthError("worker")
        guard.close()
        if terminal[0] == "error":
            raise BrowserAuthError(terminal[1])
        return terminal[1]
    except OSError:
        raise BrowserAuthError("policy") from None
    finally:
        cancelled.set()
        if guard is not None:
            guard.close()
        if started:
            process.join(1)
            if process.is_alive():
                process.kill()
                process.join(5)
            process.close()
        receive.close()
        send.close()
