"""CLI and desktop entry points for workflow dashboard generation."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from dataclasses import replace
from pathlib import Path

import requests

from .api_client import (
    ApiConfigurationError,
    ApiCredentialDisclosureError,
    PaginationIntegrityError,
    WorkflowApiClient,
    inspect_payload,
    load_fixture,
    records_from_source,
)
from .browser_auth import BrowserAuthError, MESSAGES, browser_fetch
from .config import load_config
from .generation import generate_dashboard
from .history import HistorySchemaError
from .normalization import WorkflowPopulationError


def _report_error(error):
    """Keep request details and source values out of command-line failures."""
    if isinstance(error, BrowserAuthError):
        message = MESSAGES[error.code]
    elif isinstance(error, ApiCredentialDisclosureError):
        message = MESSAGES["containment"]
    elif isinstance(error, (PaginationIntegrityError, requests.exceptions.JSONDecodeError)):
        message = "The source returned incomplete or malformed records. Check the source and try again."
    elif isinstance(error, WorkflowPopulationError):
        message = "No single matching workflow was found. Check the configured workflow and your access."
    elif isinstance(error, ApiConfigurationError):
        message = "Cannot access the workflow API. Check the endpoint and authentication settings."
    elif isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else None
        message = MESSAGES[{401: "expired", 403: "forbidden"}.get(status, "network")]
    elif isinstance(error, requests.RequestException):
        message = MESSAGES["network"]
    elif isinstance(error, HistorySchemaError):
        message = "Reporting history is incompatible. Archive it before running this version."
    elif isinstance(error, ValueError):
        message = "Invalid dashboard configuration or source data. Check the settings and input."
    elif isinstance(error, OSError):
        message = "Cannot read or write dashboard files. Check file access and try again."
    else:
        message = "Could not complete the dashboard command. Check the settings and source data."
    print(json.dumps({"error": message}, indent=2))
    return 2


def _config(args):
    # Programmatic callers predating --auth retain their explicit legacy configuration.
    auth = getattr(args, "auth", "env")
    return load_config(output_dir=args.output_dir, fixture_path=args.fixture_path,
                       history_db_path=args.history_db,
                       include_credentials=args.source == "api" and auth == "env")


def inspect_command(args):
    try:
        config = _config(args)
        if args.source == "fixture":
            raw = load_fixture(config.fixture_path)
            summary = inspect_payload(raw, source="fixture")
            summary["pagination"] = {"pages": 1, "mode": "fixture"}
        elif getattr(args, "auth", "env") == "browser":
            summary = browser_fetch(config, channel=args.browser_channel, inspect_only=True,
                                    progress=_print_progress)
        else:
            client = WorkflowApiClient(config)
            try:
                page = client.fetch_page(offset=0, take=config.api_take)
                summary = inspect_payload(page.raw, source="api")
                summary["pagination"] = {"requested_take": config.api_take,
                                         "reported_total": page.total, "first_page_records": len(page.records)}
            finally:
                client.close()
    except Exception as exc:
        return _report_error(exc)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def _print_progress(stage):
    if getattr(_print_progress, "last_stage", None) == stage:
        return
    _print_progress.last_stage = stage
    print({"signin": "Complete SSO in the browser. If needed, open the eTrieve workflow dashboard.",
           "fetching": "Fetching workflow records…"}.get(stage, stage), file=sys.stderr)


def run_command(args):
    try:
        config = _config(args)
        if args.source == "api" and getattr(args, "auth", "env") == "browser":
            fetched = browser_fetch(config, channel=args.browser_channel, progress=_print_progress)
            records, fetch_meta = fetched["records"], fetched["fetch"]
        else:
            records, fetch_meta, _ = records_from_source(args.source, config)
        result = generate_dashboard(replace(config, api_token=None), records, fetch_meta, source=args.source)
    except Exception as exc:
        return _report_error(exc)
    print(json.dumps(result, indent=2))
    return 0


def desktop_command(args):
    from .desktop import launch_desktop
    return launch_desktop(settings_path=args.settings, channel=args.browser_channel)


def build_parser():
    parser = argparse.ArgumentParser(description="Generate a workflow operations dashboard.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command_name in ("inspect", "run"):
        sub = subparsers.add_parser(command_name)
        sub.add_argument("--source", choices=("api", "fixture"), default="fixture")
        sub.add_argument("--auth", choices=("browser", "env"), default="browser")
        sub.add_argument("--browser-channel", choices=("msedge", "chrome"), default="msedge")
        sub.add_argument("--output-dir", type=Path)
        sub.add_argument("--fixture-path", type=Path)
        sub.add_argument("--history-db", type=Path)
        sub.set_defaults(func=inspect_command if command_name == "inspect" else run_command)
    desktop = subparsers.add_parser("desktop")
    desktop.add_argument("--settings", type=Path)
    desktop.add_argument("--browser-channel", choices=("msedge", "chrome"), default="msedge")
    desktop.set_defaults(func=desktop_command)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
