import argparse

import pytest

from workflow_dashboard import __main__ as cli
from workflow_dashboard.api_client import (
    PagePayload,
    PaginationIntegrityError,
    WorkflowApiClient,
    extract_page_payload,
    records_from_source,
)
from workflow_dashboard.config import DashboardConfig


def _record(record_id: object, *, key: str = "packageID") -> dict[str, object]:
    return {key: record_id}


def _client(*, take: int = 100) -> WorkflowApiClient:
    return WorkflowApiClient(DashboardConfig(api_token="test-token", api_take=take))


def _recognized_page(
    records: list[dict[str, object]],
    *,
    total: int | None,
    raw: object = None,
) -> PagePayload:
    return PagePayload(
        records=records,
        total=total,
        raw=raw,
        schema_recognized=True,
    )


def test_list_payload_does_not_infer_an_overall_total() -> None:
    page = extract_page_payload([_record("one"), _record("two")])

    assert len(page.records) == 2
    assert page.total is None
    assert page.schema_recognized is True


@pytest.mark.parametrize(
    "raw",
    [
        {"unexpected": "shape"},
        {"arbitrary": []},
        {"total": 1},
        {"total": "not-a-number", "records": []},
        {"records": ["not-an-object"]},
        None,
        "not-an-envelope",
    ],
)
def test_unrecognized_or_malformed_payloads_are_flagged(raw) -> None:
    page = extract_page_payload(raw)

    assert page.records == []
    assert page.schema_recognized is False


@pytest.mark.parametrize(
    ("raw", "expected_total"),
    [
        ([], None),
        ({"items": []}, None),
        ({"data": {"records": []}}, None),
        ({"total": 0}, 0),
        ({"Item1": "0"}, 0),
    ],
)
def test_supported_empty_payloads_are_recognized(raw, expected_total) -> None:
    page = extract_page_payload(raw)

    assert page.records == []
    assert page.total == expected_total
    assert page.schema_recognized is True


def test_inspection_reports_schema_recognition() -> None:
    summary = cli.inspect_payload({"unexpected": "shape"}, source="api")

    assert summary["schema_recognized"] is False


def test_overfilled_pages_advance_by_actual_response_length(monkeypatch) -> None:
    client = _client(take=100)
    calls: list[int] = []

    def fetch_page(*, offset: int, take: int) -> PagePayload:
        calls.append(offset)
        page_sizes = {0: 101, 101: 101, 202: 3}
        records = [_record(index) for index in range(offset, offset + page_sizes[offset])]
        return _recognized_page(records, total=205, raw={})

    monkeypatch.setattr(client, "fetch_page", fetch_page)

    records, meta = client.fetch_all_records()

    assert calls == [0, 101, 202]
    assert len(records) == 205
    assert len({record["packageID"] for record in records}) == 205
    assert meta == {
        "pages": 3,
        "attempts": 1,
        "requested_take": 100,
        "reported_total": 205,
        "retrieved_records": 205,
        "unique_records": 205,
        "duplicate_records": 0,
        "pagination_validated": True,
    }


def test_unknown_total_continues_through_short_page_until_empty(monkeypatch) -> None:
    client = _client(take=100)
    calls: list[int] = []
    pages = {
        0: [_record("one"), _record("two")],
        2: [_record("three")],
        3: [],
    }

    def fetch_page(*, offset: int, take: int) -> PagePayload:
        calls.append(offset)
        return _recognized_page(
            pages[offset], total=None, raw=pages[offset]
        )

    monkeypatch.setattr(client, "fetch_page", fetch_page)

    records, meta = client.fetch_all_records()

    assert calls == [0, 2, 3]
    assert [record["packageID"] for record in records] == ["one", "two", "three"]
    assert meta["reported_total"] is None
    assert meta["unique_records"] == 3
    assert meta["pagination_validated"] is False


def test_explicit_zero_total_is_a_validated_empty_result(monkeypatch) -> None:
    client = _client()

    monkeypatch.setattr(
        client,
        "fetch_page",
        lambda *, offset, take: extract_page_payload({"total": 0}),
    )

    records, meta = client.fetch_all_records()

    assert records == []
    assert meta["reported_total"] == 0
    assert meta["pagination_validated"] is True


def test_boundary_overlap_restarts_the_full_fetch_once(monkeypatch) -> None:
    client = _client(take=2)
    calls: list[int] = []
    passes = 0

    def fetch_page(*, offset: int, take: int) -> PagePayload:
        nonlocal passes
        calls.append(offset)
        if offset == 0:
            passes += 1
            return _recognized_page(
                [_record("one"), _record("two")], total=3, raw={}
            )
        if passes == 1:
            return _recognized_page(
                [_record("two"), _record("three")], total=3, raw={}
            )
        return _recognized_page([_record("three")], total=3, raw={})

    monkeypatch.setattr(client, "fetch_page", fetch_page)

    records, meta = client.fetch_all_records()

    assert calls == [0, 2, 0, 2]
    assert [record["packageID"] for record in records] == ["one", "two", "three"]
    assert meta["attempts"] == 2


@pytest.mark.parametrize(
    ("take", "fetch_page", "message"),
    [
        (
            2,
            lambda offset, take: _recognized_page(
                records=[_record("one"), _record("one")], total=2, raw={}
            ),
            "duplicate package ID",
        ),
        (
            2,
            lambda offset, take: _recognized_page(
                records=[{"packageName": "missing"}], total=1, raw={}
            ),
            "has no package ID",
        ),
        (
            2,
            lambda offset, take: _recognized_page(
                records=[_record(offset), _record(offset + 1)],
                total=4 if offset == 0 else 3,
                raw={},
            ),
            "Reported total changed",
        ),
        (
            2,
            lambda offset, take: _recognized_page(
                records=[_record("one"), _record("two"), _record("three")],
                total=2,
                raw={},
            ),
            "exceeding reported total",
        ),
        (
            3,
            lambda offset, take: _recognized_page(
                records=[_record("one"), _record("two")], total=4, raw={}
            ),
            "reported records remain",
        ),
        (
            2,
            lambda offset, take: _recognized_page(
                records=[_record("one"), _record("two")] if offset == 0 else [],
                total=4,
                raw={},
            ),
            "Pagination ended",
        ),
        (
            2,
            lambda offset, take: _recognized_page(
                records=(
                    [_record("one"), _record("two")]
                    if offset == 0
                    else [_record("three"), _record("one")]
                ),
                total=4,
                raw={},
            ),
            "repeats package ID",
        ),
    ],
)
def test_integrity_failures_retry_once_then_raise(
    monkeypatch, take, fetch_page, message
) -> None:
    client = _client(take=take)
    offsets: list[int] = []

    def tracked_fetch_page(*, offset: int, take: int) -> PagePayload:
        offsets.append(offset)
        return fetch_page(offset, take)

    monkeypatch.setattr(client, "fetch_page", tracked_fetch_page)

    with pytest.raises(PaginationIntegrityError, match=message):
        client.fetch_all_records()

    assert offsets.count(0) == 2


def test_package_id_lookup_is_case_insensitive_and_uses_known_aliases(monkeypatch) -> None:
    client = _client(take=2)

    def fetch_page(*, offset: int, take: int) -> PagePayload:
        return _recognized_page(
            records=[_record(" ONE ", key="PACKAGEid"), _record("two", key="requestId")],
            total=2,
            raw={},
        )

    monkeypatch.setattr(client, "fetch_page", fetch_page)

    records, meta = client.fetch_all_records()

    assert len(records) == 2
    assert meta["unique_records"] == 2


def test_unrecognized_schema_retries_once_then_raises(monkeypatch) -> None:
    client = _client()
    calls = 0

    def fetch_page(*, offset: int, take: int) -> PagePayload:
        nonlocal calls
        calls += 1
        return extract_page_payload({"unexpected": "shape"})

    monkeypatch.setattr(client, "fetch_page", fetch_page)

    with pytest.raises(PaginationIntegrityError, match="schema is unrecognized"):
        client.fetch_all_records()

    assert calls == 2


def test_fixture_source_rejects_unrecognized_schema(tmp_path) -> None:
    fixture_path = tmp_path / "unknown.json"
    fixture_path.write_text('{"unexpected": "shape"}', encoding="utf-8")
    config = DashboardConfig(fixture_path=fixture_path)

    with pytest.raises(PaginationIntegrityError, match="schema is unrecognized"):
        records_from_source("fixture", config)


def test_cli_integrity_failure_writes_no_outputs_or_history(
    monkeypatch, tmp_path, capsys
) -> None:
    output_dir = tmp_path / "outputs"
    history_db = tmp_path / "history.sqlite"

    def fail_records_from_source(source, config):
        raise PaginationIntegrityError("duplicate IDs remain")

    monkeypatch.setattr(cli, "records_from_source", fail_records_from_source)
    args = argparse.Namespace(
        source="api",
        output_dir=output_dir,
        fixture_path=None,
        history_db=history_db,
    )

    assert cli.run_command(args) == 2
    output = capsys.readouterr().out
    assert "incomplete or malformed records" in output
    assert "duplicate IDs remain" not in output
    assert not output_dir.exists()
    assert not history_db.exists()


def test_cli_unrecognized_success_response_writes_no_outputs_or_history(
    monkeypatch, tmp_path, capsys
) -> None:
    output_dir = tmp_path / "outputs"
    history_db = tmp_path / "history.sqlite"
    config = DashboardConfig(
        api_token="test-token",
        output_dir=output_dir,
        history_db_path=history_db,
    )

    monkeypatch.setattr(cli, "load_config", lambda **kwargs: config)
    monkeypatch.setattr(
        WorkflowApiClient,
        "fetch_page",
        lambda self, *, offset, take: extract_page_payload(
            {"unexpected": "shape"}
        ),
    )
    args = argparse.Namespace(
        source="api",
        output_dir=output_dir,
        fixture_path=None,
        history_db=history_db,
    )

    assert cli.run_command(args) == 2
    assert "incomplete or malformed records" in capsys.readouterr().out
    assert not output_dir.exists()
    assert not history_db.exists()
