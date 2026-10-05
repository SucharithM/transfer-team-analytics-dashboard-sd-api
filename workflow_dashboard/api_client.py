"""API and fixture loading utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import DashboardConfig, is_secure_api_url
from .normalization import FIELD_ALIASES
from .diagnostics import emit, operation


RECORD_LIST_KEYS = ("Item2", "items", "records", "results", "data", "packages", "value")
TOTAL_KEYS = ("Item1", "total", "totalCount", "count", "recordsTotal")


class ApiConfigurationError(RuntimeError):
    """Raised when live API execution is requested without required config."""


class ApiCredentialDisclosureError(ApiConfigurationError):
    """Raised when an API response contains the credential used to fetch it."""


class PaginationIntegrityError(RuntimeError):
    """Raised when paginated API records cannot be proven complete and unique."""


@dataclass(frozen=True)
class PagePayload:
    records: list[dict[str, Any]]
    total: int | None
    raw: Any
    schema_recognized: bool = False


def load_fixture(path: Path) -> Any:
    """Load a JSON fixture response from disk."""

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_total(raw: dict[str, Any]) -> tuple[int | None, bool]:
    """Return a consistent supported total and whether declared totals are valid."""

    totals: list[int] = []
    for key in TOTAL_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool):
            return None, False
        if isinstance(value, int):
            totals.append(value)
            continue
        if isinstance(value, str) and value.isdigit():
            try:
                totals.append(int(value))
            except ValueError:
                return None, False
            continue
        return None, False

    if not totals:
        return None, True
    if len(set(totals)) != 1:
        return None, False
    return totals[0], True


def _validated_records(items: list[Any]) -> list[dict[str, Any]] | None:
    """Return object records, rejecting lists containing any other JSON type."""

    if not all(isinstance(item, dict) for item in items):
        return None
    return list(items)


def extract_page_payload(raw: Any) -> PagePayload:
    """Extract records and total from supported API response shapes."""

    if isinstance(raw, list):
        records = _validated_records(raw)
        return PagePayload(
            records=records or [],
            total=None,
            raw=raw,
            schema_recognized=records is not None,
        )

    if not isinstance(raw, dict):
        return PagePayload(
            records=[], total=None, raw=raw, schema_recognized=False
        )

    total, total_is_valid = _extract_total(raw)
    if not total_is_valid:
        return PagePayload(
            records=[], total=None, raw=raw, schema_recognized=False
        )

    for key in RECORD_LIST_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, list):
            records = _validated_records(value)
            return PagePayload(
                records=records or [],
                total=total,
                raw=raw,
                schema_recognized=records is not None,
            )
        if isinstance(value, dict):
            nested = extract_page_payload(value)
            if nested.schema_recognized:
                nested_total = total if total is not None else nested.total
                return PagePayload(
                    records=nested.records,
                    total=nested_total,
                    raw=raw,
                    schema_recognized=True,
                )
            return PagePayload(
                records=[], total=total, raw=raw, schema_recognized=False
            )
        return PagePayload(
            records=[], total=total, raw=raw, schema_recognized=False
        )

    return PagePayload(
        records=[],
        total=total,
        raw=raw,
        schema_recognized=total == 0,
    )


def inspect_payload(raw: Any, *, source: str) -> dict[str, Any]:
    """Return a compact shape summary for inspect command output."""

    page = extract_page_payload(raw)
    first_record = page.records[0] if page.records else {}
    top_level_keys = list(raw.keys()) if isinstance(raw, dict) else None
    record_keys = sorted(first_record.keys()) if isinstance(first_record, dict) else []
    return {
        "source": source,
        "top_level_type": type(raw).__name__,
        "top_level_keys": top_level_keys,
        "record_count_in_payload": len(page.records),
        "reported_total": page.total,
        "schema_recognized": page.schema_recognized,
        "record_keys": record_keys,
    }


class WorkflowApiClient:
    """Small client for offset/take workflow APIs."""

    def __init__(self, config: DashboardConfig, *, bearer_token: str | None = None, before_request=None):
        self.config = config
        self._bearer_token = bearer_token or config.api_token
        self._before_request = before_request

    @operation('api.request')
    def fetch_page(self, *, offset: int = 0, take: int | None = None) -> PagePayload:
        if not is_secure_api_url(self.config.api_url):
            raise ApiConfigurationError("Configure an HTTPS API endpoint without credentials, query parameters, or fragments.")
        if self._before_request is not None:
            self._before_request()
        if not self._bearer_token:
            raise ApiConfigurationError("WORKFLOW_API_TOKEN is required for --source api")

        page_size = take or self.config.api_take
        params: list[tuple[str, Any]] = [("offset", offset), ("take", page_size)]
        params.extend(("statusFilters", status) for status in self.config.status_filters)
        headers = dict(self.config.headers)
        headers["Authorization"] = f"Bearer {self._bearer_token}"

        response = requests.get(
            self.config.api_url,
            headers=headers,
            params=params,
            timeout=self.config.request_timeout_seconds,
            allow_redirects=False,
        )
        try:
            if type(response.status_code) is int and 100 <= response.status_code <= 599:
                emit('api.response', http_status=response.status_code)
            if 300 <= response.status_code < 400:
                raise ApiConfigurationError("API redirected instead of returning records; sign in again.")
            response.raise_for_status()
            raw = response.json()
            # Check the entire envelope before inspection or export can consume it.
            serialized_token = json.dumps(self._bearer_token, ensure_ascii=True)[1:-1]
            if serialized_token in json.dumps(raw, ensure_ascii=True):
                raise ApiCredentialDisclosureError("The API response contained authentication material and was rejected.")
            return extract_page_payload(raw)
        finally:
            response.close()

    def close(self) -> None:
        """Release the credential reference; worker exit releases remaining copies."""
        self._bearer_token = None

    @staticmethod
    def _record_id(record: dict[str, Any]) -> str | None:
        """Return a normalized package identity using the canonical ID aliases."""

        lowered = {str(key).casefold(): key for key in record}
        for alias in FIELD_ALIASES["record_id"]:
            actual = alias if alias in record else lowered.get(alias.casefold())
            if actual is None:
                continue
            value = record[actual]
            if value is None:
                continue
            identity = str(value).strip()
            if identity:
                return identity.casefold()
        return None

    @classmethod
    def _validate_page_payload(
        cls, page: PagePayload, *, page_number: int
    ) -> None:
        """Reject unrecognized schemas and records without package identities."""

        if not page.schema_recognized:
            raise PaginationIntegrityError(
                f"Page {page_number} response schema is unrecognized or malformed"
            )
        for index, record in enumerate(page.records, start=1):
            if not isinstance(record, dict):
                raise PaginationIntegrityError(
                    f"Page {page_number} record {index} is not an object"
                )
            if cls._record_id(record) is None:
                raise PaginationIntegrityError(
                    f"Page {page_number} record {index} has no package ID"
                )

    def _fetch_all_records_once(
        self, *, attempt: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch and validate one complete pagination pass."""

        offset = 0
        take = self.config.api_take
        records: list[dict[str, Any]] = []
        record_ids: set[str] = set()
        total: int | None = None
        pages = 0
        previous_last_id: str | None = None

        while True:
            page = self.fetch_page(offset=offset, take=take)
            pages += 1
            self._validate_page_payload(page, page_number=pages)
            if page.total is not None:
                if page.total < 0:
                    raise PaginationIntegrityError(
                        f"Page {pages} reported a negative total ({page.total})"
                    )
                if total is None:
                    total = page.total
                elif page.total != total:
                    raise PaginationIntegrityError(
                        f"Reported total changed from {total} to {page.total} "
                        f"on page {pages}"
                    )

            if not page.records:
                if total is not None and len(record_ids) != total:
                    raise PaginationIntegrityError(
                        f"Pagination ended at {len(record_ids)} unique records; "
                        f"reported total is {total}"
                    )
                break

            page_ids: list[str] = []
            page_seen: set[str] = set()
            for record in page.records:
                record_id = self._record_id(record)
                assert record_id is not None
                if record_id in page_seen:
                    raise PaginationIntegrityError(
                        f"Page {pages} contains duplicate package ID {record_id}"
                    )
                page_seen.add(record_id)
                page_ids.append(record_id)

            if previous_last_id is not None and page_ids[0] == previous_last_id:
                raise PaginationIntegrityError(
                    f"Page-boundary overlap at offset {offset}: package ID "
                    f"{page_ids[0]} is both the prior page's last record and "
                    "the current page's first record"
                )

            cross_page_duplicates = record_ids.intersection(page_seen)
            if cross_page_duplicates:
                duplicate = sorted(cross_page_duplicates)[0]
                raise PaginationIntegrityError(
                    f"Page {pages} repeats package ID {duplicate} from an earlier page"
                )

            records.extend(page.records)
            record_ids.update(page_seen)
            previous_last_id = page_ids[-1]

            if total is not None:
                if len(record_ids) > total:
                    raise PaginationIntegrityError(
                        f"Retrieved {len(record_ids)} unique records, exceeding "
                        f"reported total {total}"
                    )
                if len(record_ids) == total:
                    break
                if len(page.records) < take:
                    raise PaginationIntegrityError(
                        f"Page {pages} returned only {len(page.records)} records "
                        f"while {total - len(record_ids)} reported records remain"
                    )

            offset += len(page.records)

        return records, {
            "pages": pages,
            "attempts": attempt,
            "requested_take": take,
            "reported_total": total,
            "retrieved_records": len(records),
            "unique_records": len(record_ids),
            "duplicate_records": 0,
            "pagination_validated": total is not None,
        }

    @operation('api.fetch')
    def fetch_all_records(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch all records, retrying one failed integrity check from offset zero."""

        last_error: PaginationIntegrityError | None = None
        for attempt in (1, 2):
            try:
                return self._fetch_all_records_once(attempt=attempt)
            except PaginationIntegrityError as exc:
                emit('api.validate.failed')
                last_error = exc

        assert last_error is not None
        raise PaginationIntegrityError(
            f"Pagination validation failed after 2 attempts: {last_error}"
        ) from last_error


def records_from_source(source: str, config: DashboardConfig) -> tuple[list[dict[str, Any]], dict[str, Any], Any]:
    """Load records from fixture or live API."""

    if source == "fixture":
        raw = load_fixture(config.fixture_path)
        page = extract_page_payload(raw)
        WorkflowApiClient._validate_page_payload(page, page_number=1)
        meta = {
            "pages": 1,
            "attempts": 1,
            "requested_take": None,
            "reported_total": page.total,
            "retrieved_records": len(page.records),
            "unique_records": None,
            "duplicate_records": None,
            "pagination_validated": False,
        }
        return page.records, meta, raw

    client = WorkflowApiClient(config)
    try:
        records, meta = client.fetch_all_records()
        return records, meta, {"records": records}
    finally:
        client.close()
