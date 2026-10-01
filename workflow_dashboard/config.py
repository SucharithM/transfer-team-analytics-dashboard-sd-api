"""Configuration loading for workflow dashboard generation."""

from __future__ import annotations

import math
import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


DEFAULT_API_URL = "https://tenant.example.test/flow/api/user-dashboard/packages"
DEFAULT_STATUS_FILTERS = ("NeedsReview", "InProgress", "Completed")
DEFAULT_DASHBOARD_TITLE = "Transfer Credit Evaluation Executive Dashboard"
DEFAULT_TEAM_MEMBERS = (
    "Staff Member A",
    "Staff Member B",
    "Staff Member C",
    "Staff Member D",
    "Staff Member E",
)


def is_secure_api_url(url: str) -> bool:
    """Require an HTTPS endpoint without embedded credentials or URL secrets."""
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.port in (None, 443) and bool(parsed.path.strip("/"))
                and parsed.username is None and parsed.password is None
                and not parsed.query and not parsed.fragment)
    except (TypeError, ValueError):
        return False


def _team_members(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_TEAM_MEMBERS
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError("WORKFLOW_TEAM_MEMBERS must be a JSON array of names") from None
    if not isinstance(parsed, list) or not all(isinstance(v, str) and v.strip() for v in parsed):
        raise ValueError("WORKFLOW_TEAM_MEMBERS must be a JSON array of names")
    return tuple(v.strip() for v in parsed)


@dataclass(frozen=True)
class DashboardConfig:
    """Runtime configuration sourced from environment and CLI overrides."""

    api_url: str = DEFAULT_API_URL
    api_token: str | None = field(default=None, repr=False)
    api_take: int = 100
    status_filters: tuple[str, ...] = DEFAULT_STATUS_FILTERS
    workflow_filter: str | None = None
    dashboard_title: str = DEFAULT_DASHBOARD_TITLE
    team_members: tuple[str, ...] = DEFAULT_TEAM_MEMBERS
    backlog_age_days: float = 7.0
    output_dir: Path = Path("outputs")
    fixture_path: Path = Path("data/sample_api_response.json")
    history_db_path: Path = Path("outputs/history/workflow_history.sqlite")
    request_timeout_seconds: int = 30
    terminal_statuses: tuple[str, ...] = (
        "completed",
        "complete",
        "closed",
        "cancelled",
        "canceled",
    )
    terminal_steps: tuple[str, ...] = ("end",)
    stale_idle_days: int = 3
    old_age_days: int = 14
    minimum_wait_completeness: float = 0.95
    minimum_idle_completeness: float = 0.95
    minimum_completion_completeness: float = 0.95
    env_file: Path = Path(".env")
    headers: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for name in (
            "minimum_wait_completeness",
            "minimum_idle_completeness",
            "minimum_completion_completeness",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not (0 <= value <= 1):
                raise ValueError(f"{name} must be a decimal from 0 through 1")


def _split_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    parsed = tuple(part.strip() for part in value.split(",") if part.strip())
    return parsed or default


def _completeness_from_env(name: str, default: str = "0.95", *, get=os.getenv) -> float:
    raw_value = get(name, default)
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a decimal from 0 through 1") from exc


def load_config(
    *,
    output_dir: str | Path | None = None,
    fixture_path: str | Path | None = None,
    history_db_path: str | Path | None = None,
    env_file: str | Path | None = None,
    include_credentials: bool = False,
) -> DashboardConfig:
    """Load config from .env/environment, with optional CLI path overrides."""

    env_path = Path(env_file or ".env")
    values = dict(dotenv_values(env_path, interpolate=False)) if env_path.exists() else {}
    if not include_credentials:
        for key in ("WORKFLOW_API_TOKEN", "ETRIEVE_API_TOKEN"):
            values.pop(key, None)

    def get(name, default=None):
        return os.environ.get(name, values.get(name) or default)

    token = (get("WORKFLOW_API_TOKEN") or get("ETRIEVE_API_TOKEN")) if include_credentials else None
    status_filters = _split_csv(
        get("WORKFLOW_STATUS_FILTERS"), DEFAULT_STATUS_FILTERS
    )
    api_take_raw = get("WORKFLOW_API_TAKE", "100")
    try:
        api_take = max(1, int(api_take_raw))
    except ValueError:
        api_take = 100
    minimum_wait_completeness = _completeness_from_env("WORKFLOW_MIN_WAIT_COMPLETENESS", get=get)
    minimum_idle_completeness = _completeness_from_env("WORKFLOW_MIN_IDLE_COMPLETENESS", get=get)
    minimum_completion_completeness = _completeness_from_env(
        "WORKFLOW_MIN_COMPLETION_COMPLETENESS", get=get
    )

    headers: dict[str, str] = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "workflow-operations-dashboard/0.1",
    }
    origin = get("WORKFLOW_API_ORIGIN")
    referer = get("WORKFLOW_API_REFERER")
    if origin:
        headers["Origin"] = origin
    if referer:
        headers["Referer"] = referer

    return DashboardConfig(
        api_url=get("WORKFLOW_API_URL", DEFAULT_API_URL),
        api_token=token,
        api_take=api_take,
        status_filters=status_filters,
        workflow_filter=get("WORKFLOW_FILTER"),
        dashboard_title=get("WORKFLOW_DASHBOARD_TITLE", DEFAULT_DASHBOARD_TITLE),
        team_members=_team_members(get("WORKFLOW_TEAM_MEMBERS")),
        output_dir=(
            Path(output_dir)
            if output_dir is not None
            else Path(get("WORKFLOW_OUTPUT_DIR", "outputs"))
        ),
        fixture_path=(
            Path(fixture_path)
            if fixture_path is not None
            else Path(
                get("WORKFLOW_FIXTURE_PATH", "data/sample_api_response.json")
            )
        ),
        history_db_path=(
            Path(history_db_path)
            if history_db_path is not None
            else Path(
                get(
                    "WORKFLOW_HISTORY_DB", "outputs/history/workflow_history.sqlite"
                )
            )
        ),
        request_timeout_seconds=int(
            get("WORKFLOW_REQUEST_TIMEOUT_SECONDS", "30")
        ),
        minimum_wait_completeness=minimum_wait_completeness,
        minimum_idle_completeness=minimum_idle_completeness,
        minimum_completion_completeness=minimum_completion_completeness,
        env_file=env_path,
        headers=headers,
    )
