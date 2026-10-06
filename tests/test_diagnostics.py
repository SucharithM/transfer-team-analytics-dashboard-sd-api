"""Privacy, process-boundary and desktop checks for session-only diagnostics."""
import json
import multiprocessing
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

from workflow_dashboard import diagnostics as logs, diagnostics_ui, browser_auth as auth, desktop
from workflow_dashboard.config import DashboardConfig
from workflow_dashboard.generation import generate_dashboard
from .test_browser_auth import install_fake_browser, Pipe, TOKEN
from .test_desktop_recovery import harness, complete

PRIVATE_VALUES = (
    TOKEN, 'private-person@example.test', 'Sensitive Student Name', 'Private Staff Name',
    'https://private-tenant.example.test/packages', 'C:\\Users\\Private User\\Secret Reports',
    'private-cookie-value', 'private-workflow-name', 'private-package-id',
)


def session():
    value = logs.DiagnosticSession()
    value.begin(1)
    return value


def safe_event(code='browser.observe.failed', **details):
    return {'code': code, 'utc': '2026-10-04T15:00:00Z', 'elapsed_ms': 123,
            'source': 'worker', 'details': details}


def assert_private_absent(value):
    text = json.dumps(value, default=lambda obj: '<unsupported>')
    for private in PRIVATE_VALUES:
        assert private not in text


def test_exception_text_notes_tracebacks_and_attributes_are_never_formatted_or_retained(tmp_path, capsys):
    value = session()
    class Unformattable(RuntimeError):
        def __str__(self):
            pytest.fail('No exception formatting is permitted')
        def __repr__(self):
            pytest.fail('No exception representation is permitted')
    error = Unformattable('|'.join(PRIVATE_VALUES))
    error.add_note(TOKEN)
    with logs.capture(value.sink(1)):
        logs.emit('browser.observe.failed', error=error)
        logs.emit('folder.access.failed', error=PermissionError(13, TOKEN, PRIVATE_VALUES[5]))
    value.finish(1, 'failed')
    report = value.reports()[0][1]
    assert 'errno' in report and 'permission' in report
    assert_private_absent(report)
    assert all(type(event['details']) is dict for _, event in value.attempts[1].events)
    assert list(tmp_path.iterdir()) == []
    output = capsys.readouterr()
    assert output.out == output.err == ''


@pytest.mark.parametrize('details', [
    {'message': TOKEN}, {'headers': {'Authorization': TOKEN}}, {'browser_version': TOKEN},
    {'http_status': True}, {'exit_code': TOKEN}, {'errno': -1}, {'http_status': 600},
    {'category': TOKEN}, {'auth_code': TOKEN}, {'winerror': 65536},
])
def test_arbitrary_fields_and_invalid_types_are_rejected_before_storage(details):
    value = session()
    assert logs.validate_event(safe_event(**details)) is None
    with logs.capture(value.sink(1)):
        logs.emit('browser.observe.failed', **details)
    value.finish(1, 'failed')
    assert_private_absent(value.reports())
    assert 'diagnostics.unavailable' in value.reports()[0][1]


@pytest.mark.parametrize('change', [
    {'code': TOKEN}, {'utc': TOKEN}, {'elapsed_ms': True}, {'elapsed_ms': -1},
    {'source': TOKEN}, {'extra': TOKEN}, {'utc': '2026-99-99T15:00:00Z'},
])
def test_wire_schema_rejects_unknown_and_malformed_events(change):
    assert logs.validate_event({**safe_event(), **change}) is None


def test_limits_keep_first_and_last_events_and_latest_failure():
    value = session()
    with logs.capture(value.sink(1)):
        for _ in range(600):
            logs.emit('api.response', http_status=200)
        logs.emit('browser.observe.failed', auth_code='signin')
    value.finish(1, 'failed')
    assert len(value.attempts[1].events) == logs.MAX_EVENTS
    assert value.attempts[1].truncated
    report = value.reports()[0][1]
    assert 'attempt.start' in report and 'browser.observe.failed' in report
    assert 'truncated' in report
    assert len(report.encode('utf-8')) <= logs.MAX_REPORT_BYTES
    for key in range(2, 20):
        value.begin(key)
        value.finish(key, 'success')
    assert 1 in value.attempts  # Successful retries do not erase the incident.
    for key in range(20, 35):
        value.begin(key)
        value.finish(key, 'failed')
    assert len(value.reports()) == logs.MAX_ATTEMPTS


def test_export_revalidates_metadata_and_event_contents():
    value = session()
    value.finish(1, 'failed')
    value.attempts[1].events.append(('worker', safe_event(message=TOKEN)))
    assert_private_absent(value.reports())
    value.metadata['app_version'] = TOKEN
    assert_private_absent(value.reports())
    assert 'metadata unavailable' in value.reports()[0][1]


def test_runtime_metadata_has_only_approved_technical_fields(monkeypatch):
    monkeypatch.setattr(logs.platform, 'machine', lambda: TOKEN)
    monkeypatch.setattr(logs.metadata, 'version', lambda name: TOKEN)
    metadata = logs.runtime_metadata(TOKEN)
    assert logs.validate_metadata(metadata) is not None
    assert metadata['architecture'] == 'other'
    assert metadata['browser_channel'] == 'unavailable'
    assert_private_absent(metadata)


def test_build_identity_excludes_settings_and_data_and_loads_frozen_manifest(tmp_path, monkeypatch):
    root = tmp_path / 'workflow_dashboard'
    root.mkdir()
    for name in logs.CODE_FILES:
        (root / name).write_text('code', encoding='utf-8')
    (tmp_path / 'desktop_launcher.py').write_text('launcher', encoding='utf-8')
    monkeypatch.setattr(logs, '__file__', str(root / 'diagnostics.py'))
    first = logs.code_fingerprint()
    (root / 'desktop_settings.toml').write_text(TOKEN, encoding='utf-8')
    (root / '.env').write_text(TOKEN, encoding='utf-8')
    (root / 'records.json').write_text(TOKEN, encoding='utf-8')
    assert logs.code_fingerprint() == first
    (root / 'desktop.py').write_text('changed code', encoding='utf-8')
    second = logs.code_fingerprint()
    assert second != first
    (root / 'build_identity.json').write_text(json.dumps({'schema': logs.SCHEMA, 'fingerprint': second}), encoding='utf-8')
    monkeypatch.setattr(logs.sys, 'frozen', True, raising=False)
    assert logs.code_fingerprint() == second
    (root / 'build_identity.json').write_text(TOKEN, encoding='utf-8')
    assert logs.code_fingerprint() == 'unavailable'


def test_logging_sink_failure_does_not_change_generation(tmp_path):
    def fail(event):
        raise RuntimeError(TOKEN)
    result = generate_dashboard(DashboardConfig(output_dir=tmp_path / 'reports', history_db_path=tmp_path / 'history.sqlite'),
        [{'packageID': 'demo-diagnostics', 'workflowName': 'Synthetic Workflow', 'stepName': 'End',
          'submissionDate': '2026-09-29T09:00:00', 'lastActivityDate': '2026-09-30T10:00:00'}],
        {'pagination_validated': True}, source='fixture', diagnostics=fail)
    assert Path(result['outputs']['html']).is_file()


def test_generation_failure_reports_stage_without_workflow_values(tmp_path):
    value = session()
    config = DashboardConfig(workflow_filter='private-workflow-name', output_dir=tmp_path / 'reports')
    with pytest.raises(Exception):
        generate_dashboard(config, [{'packageID': 'private-package-id', 'workflowName': 'Other Private Workflow'}],
                           {'pagination_validated': True}, diagnostics=value.sink(1))
    value.finish(1, 'failed')
    report = value.reports()[0][1]
    assert 'generation.workflow.failed' in report
    assert_private_absent(report)
    assert 'Other Private Workflow' not in report
    assert not (tmp_path / 'reports').exists()


def test_worker_diagnostics_are_validated_and_contain_no_credential(monkeypatch, capsys):
    install_fake_browser(monkeypatch, navigation_error=PlaywrightError('|'.join(PRIVATE_VALUES)))
    monkeypatch.setattr(auth.os, 'setsid', lambda: None, raising=False)
    pipe = Pipe()
    ready = threading.Event(); ready.set()
    auth._worker(DashboardConfig(), pipe, threading.Event(), ready, 'msedge', False, 600, diagnostics_enabled=True)
    events = [data for kind, data in pipe.messages if kind == 'diagnostic']
    assert events and all(logs.validate_event(data) is not None for data in events)
    assert all(data['source'] == 'worker' for data in events)
    assert any(data['code'] == 'browser.navigate.failed' for data in events)
    assert pipe.messages[-1] == ('error', 'navigation')
    assert_private_absent(pipe.messages)
    output = capsys.readouterr()
    assert output.out == output.err == ''


@pytest.mark.parametrize('status, expected', [(200, 'result'), (401, 'expired'), (403, 'forbidden')])
def test_credential_capture_cleanup_and_http_status_have_safe_ordered_events(monkeypatch, status, expected):
    import requests
    lifecycle = install_fake_browser(monkeypatch)
    monkeypatch.setattr(auth.os, 'setsid', lambda: None, raising=False)
    class Response:
        status_code = status
        def raise_for_status(self):
            if status != 200:
                raise requests.HTTPError('|'.join(PRIVATE_VALUES), response=self)
        def json(self):
            return {'total': 1, 'records': [{'packageID': 'private-package-id'}]}
        def close(self):
            pass
    def get(*args, **kwargs):
        assert lifecycle == ['context_closed', 'browser_closed', 'driver_stopped']
        assert kwargs['headers']['Authorization'] == f'Bearer {TOKEN}'
        return Response()
    monkeypatch.setattr(requests, 'get', get)
    pipe = Pipe()
    ready = threading.Event(); ready.set()
    auth._worker(DashboardConfig(), pipe, threading.Event(), ready, 'msedge', False, 600, diagnostics_enabled=True)
    events = [event for kind, event in pipe.messages if kind == 'diagnostic']
    codes = [event['code'] for event in events]
    ordered = ['credential.observed', 'browser.context_close.done', 'browser.close.done',
               'browser.driver_close.done', 'api.fetch.start', 'api.response']
    assert [codes.index(code) for code in ordered] == sorted(codes.index(code) for code in ordered)
    assert all(logs.validate_event(event) is not None for event in events)
    assert_private_absent(events)
    assert next(event for event in events if event['code'] == 'api.response')['details'] == {'http_status': status}
    if expected == 'result':
        assert pipe.messages[-1][0] == 'result'
    else:
        assert pipe.messages[-1] == ('error', expected)
        assert 'api.request.failed' in codes


def diagnostic_worker(config, pipe, cancel, ready, channel, inspect_only, timeout, *, diagnostics_enabled=False):
    import os
    if os.name != 'nt':
        os.setsid()
    ready.wait(10)
    pipe.send(('diagnostic', safe_event(auth_code='signin')))
    pipe.send(('error', 'signin'))
    pipe.close()


def invalid_diagnostic_worker(config, pipe, cancel, ready, channel, inspect_only, timeout, *, diagnostics_enabled=False):
    import os
    if os.name != 'nt':
        os.setsid()
    ready.wait(10)
    pipe.send(('diagnostic', safe_event(message=TOKEN)))
    pipe.send(('result', {'records': [], 'fetch': {}}))
    pipe.close()


@pytest.mark.parametrize('target, expected', [(diagnostic_worker, 'signin'), (invalid_diagnostic_worker, 'worker')])
def test_parent_revalidates_worker_events_and_reaps_before_failure(monkeypatch, target, expected):
    value = session()
    monkeypatch.setattr(auth, '_worker', target)
    with pytest.raises(auth.BrowserAuthError) as error:
        auth.browser_fetch(DashboardConfig(), diagnostics=value.sink(1))
    assert error.value.code == expected
    value.finish(1, 'failed')
    assert_private_absent(value.reports())
    assert not multiprocessing.active_children()
    if expected == 'signin':
        assert '[worker/error]' in value.reports()[0][1]


def test_worker_event_budget_is_bounded():
    events = []
    with logs.capture(events.append, bounded=True):
        for _ in range(600):
            logs.emit('api.request.done')
    assert len(events) == logs.MAX_EVENTS
    assert events[-1]['code'] == 'diagnostics.truncated'


def test_button_disabled_during_work_and_enabled_after_failure(monkeypatch, harness):
    assert harness.app.logs_button.options['text'] == 'Send Error Logs'
    assert harness.app.logs_button.options['state'] == 'disabled'
    def fail(*args, **kwargs):
        raise auth.BrowserAuthError('signin')
    monkeypatch.setattr(desktop, 'fetch_and_generate', fail)
    harness.selections.append(str(harness.chosen))
    harness.app.generate()
    assert harness.app.logs_button.options['state'] == 'disabled'
    complete(harness)
    assert harness.app.logs_button.options['state'] == 'normal'
    assert 'signin' in harness.app.diagnostics.reports()[0][1]


def test_preview_copies_immutable_validated_snapshot_and_reports_clipboard_failure(monkeypatch, harness):
    app = harness.app
    app.diagnostics.record(0, 'browser.observe.failed', auth_code='signin')
    snapshot = app.diagnostics.reports()[0][1]
    old_count = len(harness.widgets)
    diagnostics_ui.open_preview(harness.root, app.diagnostics)
    widgets = harness.widgets[old_count:]
    text = next(widget for widget in widgets if 'yscrollcommand' in widget.options)
    assert text.content == snapshot and text.options['state'] == 'disabled'
    # Even an altered display widget must not become an arbitrary clipboard source.
    text.content = TOKEN
    button = next(widget for widget in widgets if widget.options.get('text') == 'Copy Logs')
    button.invoke()
    assert harness.root.clipboard == snapshot
    assert_private_absent(harness.root.clipboard)
    def deny(value):
        raise PermissionError(TOKEN)
    monkeypatch.setattr(harness.root, 'clipboard_append', deny)
    button.invoke()
    notice = next(widget.options['textvariable'] for widget in widgets if 'textvariable' in widget.options)
    assert 'copy it manually' in notice.get()
    assert TOKEN not in notice.get()
    assert 'clipboard.copy.failed' in app.diagnostics.reports()[0][1]


def test_startup_settings_error_keeps_copy_action_without_private_error(monkeypatch, harness):
    monkeypatch.setattr(harness.fake_tk, 'Tk', lambda: harness.root)
    def fail(*args):
        raise ValueError('|'.join(PRIVATE_VALUES))
    monkeypatch.setattr(desktop, 'desktop_config', fail)
    sessions = []
    monkeypatch.setattr(desktop, 'open_preview', lambda root, value: sessions.append(value))
    before = len(harness.widgets)
    assert desktop.launch_desktop() == 2
    assert harness.root.looped and not harness.root.destroyed
    buttons = harness.widgets[before:]
    next(widget for widget in buttons if widget.options.get('text') == 'Send Error Logs').invoke()
    assert 'settings.load.failed' in sessions[0].reports()[0][1]
    assert_private_absent(sessions[0].reports())


def test_callback_failure_has_safe_diagnostics_without_printing_traceback(harness, capsys):
    harness.root.report_callback_exception(RuntimeError, RuntimeError(TOKEN), None)
    assert harness.app.logs_button.options['state'] == 'normal'
    assert 'desktop.callback.failed' in harness.app.diagnostics.reports()[0][1]
    assert_private_absent(harness.app.diagnostics.reports())
    output = capsys.readouterr()
    assert output.out == output.err == ''


def test_delayed_events_are_associated_with_the_original_attempt():
    value = session()
    original = value.sink(1)
    value.finish(1, 'failed')
    value.begin(2)
    value.finish(2, 'failed')
    with logs.capture(original):
        logs.emit('dashboard.open.failed')
    reports = value.reports()
    assert 'dashboard.open.failed' not in reports[0][1]
    assert 'dashboard.open.failed' in reports[1][1]


@pytest.mark.parametrize('reason', ['disconnected', 'context_closed', 'no_pages', 'observation_error'])
def test_observation_failure_has_safe_reason_and_cleanup_phase(monkeypatch, reason):
    from .test_browser_auth import Clock
    clock = Clock()
    def fail(context, observe):
        if reason == 'disconnected':
            context.browser.emit('disconnected')
        elif reason == 'context_closed':
            context.emit('close')
        elif reason == 'observation_error':
            raise PlaywrightError('|'.join(PRIVATE_VALUES))
    install_fake_browser(monkeypatch, capture=False, closed=reason == 'no_pages',
                         events=[fail], clock=clock)
    monkeypatch.setattr(auth.os, 'setsid', lambda: None, raising=False)
    pipe = Pipe()
    ready = threading.Event()
    ready.set()
    auth._worker(DashboardConfig(), pipe, threading.Event(), ready, 'msedge', False, 600,
                 diagnostics_enabled=True)
    events = [data for kind, data in pipe.messages if kind == 'diagnostic']
    failed = next(e for e in events if e['code'] == 'browser.observe.failed')
    assert failed['details'] == {'auth_code': 'signin' if reason == 'observation_error' else 'closed',
                                  'reason': reason}
    assert events.index(failed) < next(i for i, e in enumerate(events) if e['code'] == 'browser.context_close.start')
    assert any(e['code'] == 'browser.page.opened' and e['details']['closure_phase'] == 'signin' for e in events)
    for code in ('browser.page.closed', 'browser.context.closed', 'browser.disconnected'):
        assert any(e['code'] == code and e['details']['closure_phase'] == 'cleanup' for e in events)
    assert all(logs.validate_event(e) is not None for e in events)
    assert_private_absent(pipe.messages)


@pytest.mark.parametrize('details', [{'reason': TOKEN}, {'closure_phase': TOKEN},
                                    {'reason': True}, {'closure_phase': 1}])
def test_lifecycle_fields_reject_unknown_values(details):
    assert logs.validate_event(safe_event(**details)) is None


def test_page_crash_event_contains_no_page_data(monkeypatch):
    from .test_browser_auth import Clock
    def crash(context, observe):
        context.pages[0].emit('crash', SimpleNamespace(url=PRIVATE_VALUES[4]))
        context.emit('close')
    install_fake_browser(monkeypatch, capture=False, clock=Clock(), events=[crash])
    events = []
    with logs.capture(events.append):
        with pytest.raises(auth.BrowserAuthError):
            auth._fetch_with_browser(DashboardConfig(), lambda _: None, threading.Event(),
                                     channel='msedge', inspect_only=False, sign_in_timeout=600)
    event = next(e for e in events if e['code'] == 'browser.page.crashed')
    assert event['details'] == {'closure_phase': 'signin'}
    assert_private_absent(events)


@pytest.mark.parametrize('capture_token', [False, True])
def test_browser_callbacks_keep_diagnostics_across_playwright_greenlets(monkeypatch, capture_token):
    from .test_browser_auth import Clock
    def close(context, observe):
        context.emit('close')
    install_fake_browser(monkeypatch, capture=capture_token, events=[close],
                         clock=Clock(), event_greenlets=True)
    monkeypatch.setattr(auth.os, 'setsid', lambda: None, raising=False)
    monkeypatch.setattr(auth.WorkflowApiClient, 'fetch_all_records',
                        lambda self: ([], {'pagination_validated': True}))
    pipe = Pipe()
    ready = threading.Event()
    ready.set()
    auth._worker(DashboardConfig(), pipe, threading.Event(), ready, 'msedge', False, 600,
                 diagnostics_enabled=True)
    events = [data for kind, data in pipe.messages if kind == 'diagnostic']
    codes = [event['code'] for event in events]
    assert 'browser.page.opened' in codes
    assert 'browser.page.closed' in codes
    assert 'browser.disconnected' in codes
    assert ('credential.observed' in codes) == capture_token
    if not capture_token:
        closed = next(e for e in events if e['code'] == 'browser.context.closed')
        assert closed['details'] == {'closure_phase': 'signin'}
        assert codes.index('browser.context.closed') < codes.index('browser.observe.failed')
        assert pipe.messages[-1] == ('error', 'closed')
    else:
        assert pipe.messages[-1][0] == 'result'
    assert all(e['source'] == 'worker' and logs.validate_event(e) is not None for e in events)
    assert_private_absent(pipe.messages)


def test_bound_emitter_shares_budget_and_validation_across_greenlets():
    from greenlet import greenlet
    events = []
    with logs.capture(events.append, bounded=True):
        bound = logs.bind_emitter()
        greenlet(lambda: bound('browser.context.closed', reason=TOKEN)).switch()
        for _ in range(logs.MAX_EVENTS):
            logs.emit('browser.observe.start')
            greenlet(lambda: bound('browser.page.opened', closure_phase='signin')).switch()
    assert len(events) == logs.MAX_EVENTS
    assert events[0]['code'] == 'diagnostics.unavailable'
    assert events[-1]['code'] == 'diagnostics.truncated'
    assert_private_absent(events)


def test_emitter_bound_without_capture_stays_disabled():
    from greenlet import greenlet
    bound = logs.bind_emitter()
    events = []
    with logs.capture(events.append):
        greenlet(lambda: bound('browser.page.opened', closure_phase='signin')).switch()
    assert events == []
