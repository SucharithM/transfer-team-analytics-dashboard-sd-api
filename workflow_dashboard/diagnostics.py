"""Bounded, session-only technical events. Arbitrary text is never a log field."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import sqlite3
import sys
import threading
import time
import uuid

SCHEMA = 1
MAX_ATTEMPTS = 10
MAX_EVENTS = 256
MAX_REPORT_BYTES = 64 * 1024
OPERATIONS = (
    'settings.load', 'folder.choose', 'folder.access', 'preferences.load', 'preferences.save',
    'worker.start', 'worker.attach', 'worker.exit', 'worker.transport', 'worker.cleanup',
    'supervision.create', 'supervision.attach', 'supervision.close', 'browser.launch',
    'browser.context', 'browser.navigate', 'browser.observe', 'browser.context_close',
    'browser.close', 'browser.driver_close', 'api.fetch', 'api.request', 'api.validate',
    'generation.normalize', 'generation.workflow', 'generation.analytics', 'history.prepare',
    'history.load', 'history.save', 'export.csv', 'export.html', 'export.xlsx',
    'export.validate', 'export.publish', 'export.rollback', 'generation.complete',
    'dashboard.open', 'folder.open', 'desktop.callback', 'desktop.thread', 'clipboard.copy',
)
CATALOG = {f'{operation}.{outcome}': (
    'error' if outcome == 'failed' else 'info', f'{operation}: {outcome}'
) for operation in OPERATIONS for outcome in ('start', 'done', 'failed')}
CATALOG.update({
    'browser.page.opened': ('info', 'Browser page opened'),
    'browser.page.closed': ('info', 'Browser page closed'),
    'browser.page.crashed': ('warning', 'Browser page crashed'),
    'browser.context.closed': ('info', 'Browser context closed'),
    'browser.disconnected': ('info', 'Browser disconnected'),
    'api.response': ('info', 'API response status available'),
    'session.start': ('info', 'Application session started'),
    'attempt.start': ('info', 'Attempt started'),
    'attempt.success': ('info', 'Attempt completed'),
    'attempt.failed': ('error', 'Attempt failed'),
    'attempt.cancelled': ('info', 'Attempt cancelled'),
    'cancel.requested': ('info', 'Cancellation requested'),
    'credential.observed': ('info', 'Credential observed for the approved API endpoint'),
    'browser.version': ('info', 'Browser version available'),
    'diagnostics.truncated': ('warning', 'Diagnostic event limit reached'),
    'diagnostics.unavailable': ('warning', 'Some diagnostics could not be collected'),
})
AUTH_CODES = frozenset(('cancelled', 'timeout', 'closed', 'expired', 'forbidden', 'network',
    'integrity', 'browser', 'navigation', 'signin', 'browser_cleanup', 'dependency',
    'endpoint', 'redirect', 'containment', 'worker', 'policy'))
CATEGORIES = frozenset(('permission', 'filesystem', 'timeout', 'connection', 'http',
    'database', 'configuration', 'unexpected'))
VERSION = re.compile(r'\d{1,5}(?:\.\d{1,5}){1,3}(?:(?:a|b|rc|\.post|\.dev)\d{1,5})?\Z')
UTC = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z')
DEPENDENCIES = ('playwright', 'requests', 'pandas', 'plotly', 'openpyxl', 'pyinstaller')
# Explicit code-only identity: never add settings, fixtures, history, or reports.
CODE_FILES = ('__init__.py', 'diagnostics.py', 'diagnostics_ui.py', 'build_identity.py',
    'desktop.py', 'desktop_preferences.py', 'browser_auth.py', 'process_guard.py',
    'api_client.py', 'generation.py', 'config.py', 'normalization.py', 'analytics.py',
    'history.py', 'dashboard_html.py', 'dashboard_content.py', 'excel_export.py',
    'number_format.py', 'time_utils.py', '__main__.py')
_current = ContextVar('safe_diagnostic_emitter', default=None)


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def _version(value):
    return value if type(value) is str and len(value) <= 40 and VERSION.fullmatch(value) else 'unavailable'


def validate_details(value):
    if type(value) is not dict or len(value) > 7:
        return None
    result = {}
    for key, item in value.items():
        if type(key) is not str:
            return None
        if key == 'category' and type(item) is str and item in CATEGORIES:
            result[key] = item
        elif key == 'auth_code' and type(item) is str and item in AUTH_CODES:
            result[key] = item
        elif key == 'reason' and type(item) is str and item in ('disconnected', 'context_closed', 'no_pages', 'observation_error'):
            result[key] = item
        elif key == 'closure_phase' and type(item) is str and item in ('signin', 'cleanup'):
            result[key] = item
        elif key == 'browser_version' and _version(item) != 'unavailable':
            result[key] = item
        elif key == 'http_status' and _integer(item, 100, 599):
            result[key] = item
        elif key in ('errno', 'winerror', 'sqlite_code') and _integer(item, 0, 65535):
            result[key] = item
        elif key == 'exit_code' and _integer(item, -(2**31), 2**32 - 1):
            result[key] = item
        else:
            return None
    return result


def validate_event(value):
    if type(value) is not dict or set(value) != {'code', 'utc', 'elapsed_ms', 'details', 'source'}:
        return None
    code, stamp = value['code'], value['utc']
    if type(value['source']) is not str or value['source'] not in ('desktop', 'worker'):
        return None
    if type(code) is not str or code not in CATALOG:
        return None
    if type(stamp) is not str or not UTC.fullmatch(stamp):
        return None
    try:
        datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return None
    details = validate_details(value['details'])
    if details is None or not _integer(value['elapsed_ms'], 0, 7 * 86400 * 1000):
        return None
    return {'code': code, 'utc': stamp, 'elapsed_ms': value['elapsed_ms'], 'details': details, 'source': value['source']}


def exception_details(error):
    """Classify by approved types; never format or retain the exception."""
    result = {'category': 'unexpected'}
    if isinstance(error, PermissionError):
        result['category'] = 'permission'
    elif isinstance(error, TimeoutError):
        result['category'] = 'timeout'
    elif isinstance(error, ConnectionError):
        result['category'] = 'connection'
    elif isinstance(error, OSError):
        result['category'] = 'filesystem'
    elif isinstance(error, sqlite3.Error):
        result['category'] = 'database'
    elif isinstance(error, (ValueError, TypeError)):
        result['category'] = 'configuration'
    if isinstance(error, OSError):
        for name in ('errno', 'winerror'):
            number = getattr(error, name, None)
            if _integer(number, 0, 65535):
                result[name] = number
    if isinstance(error, sqlite3.Error):
        number = getattr(error, 'sqlite_errorcode', None)
        if _integer(number, 0, 65535):
            result['sqlite_code'] = number
    try:
        import requests
        if isinstance(error, requests.Timeout):
            result['category'] = 'timeout'
        elif isinstance(error, requests.HTTPError):
            result['category'] = 'http'
        elif isinstance(error, requests.RequestException):
            result['category'] = 'connection'
    except ImportError:
        pass
    return result


class Emitter:
    def __init__(self, sink, *, bounded=False):
        self.sink, self.bounded = sink, bounded
        self.started = getattr(sink, 'started', time.monotonic())
        self.sent = 0

    def record(self, code, *, error=None, **details):
        try:
            if self.bounded and self.sent >= MAX_EVENTS:
                return
            if error is not None:
                details = {**exception_details(error), **details}
            if self.bounded and self.sent == MAX_EVENTS - 1:
                code, details = 'diagnostics.truncated', {}
            event = validate_event({'code': code,
                'source': 'worker' if self.bounded else 'desktop',
                'utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'elapsed_ms': max(0, int((time.monotonic() - self.started) * 1000)),
                'details': details})
            if event is None:
                event = validate_event({'code': 'diagnostics.unavailable',
                    'source': 'worker' if self.bounded else 'desktop',
                    'utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'elapsed_ms': 0, 'details': {}})
            self.sent += 1
            self.sink(event)
        except Exception:
            # No fallback logger: even its exception could contain private data.
            pass


@contextmanager
def capture(sink=None, *, bounded=False):
    if sink is None:
        yield
        return
    token = _current.set(Emitter(sink, bounded=bounded))
    try:
        yield
    finally:
        _current.reset(token)


def enabled():
    return _current.get() is not None


def emit(code, *, error=None, **details):
    emitter = _current.get()
    if emitter is not None:
        emitter.record(code, error=error, **details)


def accept_worker_event(event):
    safe = validate_event(event)
    if safe is None or safe['source'] != 'worker':
        return False
    emitter = _current.get()
    if emitter is not None:
        try:
            emitter.sink(safe)
        except Exception:
            emit('diagnostics.unavailable')
    return True


@contextmanager
def operation(name):
    emit(name + '.start')
    try:
        yield
    except BaseException as error:
        emit(name + '.failed', error=error)
        raise
    else:
        emit(name + '.done')


def code_fingerprint():
    root = Path(__file__).parent
    try:
        if getattr(sys, 'frozen', False):
            manifest = root / 'build_identity.json'
            if manifest.stat().st_size > 256:
                return 'unavailable'
            value = json.loads(manifest.read_text(encoding='utf-8'))
            if type(value) is dict and set(value) == {'schema', 'fingerprint'} and type(value['schema']) is int and value['schema'] == SCHEMA:
                fingerprint = value['fingerprint']
                if type(fingerprint) is str and re.fullmatch('[0-9a-f]{64}', fingerprint):
                    return fingerprint
            return 'unavailable'
        digest = hashlib.sha256()
        for name in CODE_FILES:
            data = (root / name).read_bytes()
            digest.update(name.encode('ascii') + b'\0' + data + b'\0')
        digest.update((root.parent / 'desktop_launcher.py').read_bytes())
        return digest.hexdigest()
    except Exception:
        return 'unavailable'


def runtime_metadata(channel):
    from . import __version__
    family = {'win32': 'windows', 'darwin': 'macos', 'linux': 'linux'}.get(sys.platform, 'other')
    try:
        if sys.platform == 'win32':
            version = sys.getwindowsversion()
            release = f'{version.major}.{version.minor}.{version.build}'
        elif sys.platform == 'darwin':
            release = platform.mac_ver()[0]
        else:
            release = platform.release().split('-', 1)[0]
        architecture = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64',
                        'aarch64': 'arm64', 'x86': 'x86', 'i386': 'x86'}.get(platform.machine().lower(), 'other')
    except Exception:
        release, architecture = 'unavailable', 'other'
    versions = {'python': '.'.join(map(str, sys.version_info[:3]))}
    for name in DEPENDENCIES:
        try:
            versions[name] = _version(metadata.version(name))
        except Exception:
            versions[name] = 'unavailable'
    return {'schema': SCHEMA, 'app_version': _version(__version__),
        'build_fingerprint': code_fingerprint(), 'mode': 'executable' if getattr(sys, 'frozen', False) else 'source',
        'os_family': family, 'os_version': _version(release), 'architecture': architecture,
        'browser_channel': channel if type(channel) is str and channel in ('msedge', 'chrome') else 'unavailable',
        'versions': versions}


def validate_metadata(value):
    if type(value) is not dict or set(value) != {'schema', 'app_version', 'build_fingerprint', 'mode',
        'os_family', 'os_version', 'architecture', 'browser_channel', 'versions'}:
        return None
    if type(value['schema']) is not int or value['schema'] != SCHEMA:
        return None
    for key in ('app_version', 'os_version'):
        if type(value[key]) is not str or (value[key] != 'unavailable' and _version(value[key]) == 'unavailable'):
            return None
    for key, choices in (
        ('mode', ('source', 'executable')), ('os_family', ('windows', 'macos', 'linux', 'other')),
        ('architecture', ('x64', 'x86', 'arm64', 'other')), ('browser_channel', ('msedge', 'chrome', 'unavailable')),
    ):
        if type(value[key]) is not str or value[key] not in choices:
            return None
    fingerprint = value['build_fingerprint']
    if type(fingerprint) is not str or (fingerprint != 'unavailable' and not re.fullmatch('[0-9a-f]{64}', fingerprint)):
        return None
    versions = value['versions']
    if type(versions) is not dict or set(versions) != {'python', *DEPENDENCIES}:
        return None
    if any(type(item) is not str or (item != 'unavailable' and _version(item) == 'unavailable') for item in versions.values()):
        return None
    return {**value, 'versions': dict(versions)}


class Attempt:
    def __init__(self):
        self.identifier = uuid.uuid4().hex
        self.started = time.monotonic()
        self.events = []
        self.truncated = False
        self.incident = False
        self.completed = False
        self.outcome = 'running'

    def append(self, event, source):
        safe = validate_event(event)
        if safe is None or source not in ('desktop', 'worker'):
            return
        self.incident |= CATALOG[safe['code']][0] in ('error', 'warning')
        self.events.append((safe['source'], safe))
        if len(self.events) > MAX_EVENTS:
            del self.events[MAX_EVENTS // 2]
            self.truncated = True


class DiagnosticSession:
    def __init__(self, channel='msedge'):
        self.metadata = runtime_metadata(channel)
        self.lock = threading.RLock()
        self.attempts = OrderedDict()

    def begin(self, key):
        with self.lock:
            for old in list(self.attempts):
                attempt = self.attempts[old]
                if attempt.completed and not attempt.incident:
                    del self.attempts[old]
            self.attempts[key] = Attempt()
        self.record(key, 'attempt.start')

    def sink(self, key, source='desktop'):
        def accept(event):
            with self.lock:
                attempt = self.attempts.get(key)
                if attempt is not None:
                    attempt.append(event, source)
                    self._prune()
        with self.lock:
            attempt = self.attempts.get(key)
            accept.started = attempt.started if attempt is not None else time.monotonic()
        return accept

    def record(self, key, code, *, error=None, **details):
        Emitter(self.sink(key)).record(code, error=error, **details)

    def finish(self, key, outcome):
        if outcome not in ('success', 'failed', 'cancelled'):
            outcome = 'failed'
        self.record(key, 'attempt.' + outcome)
        with self.lock:
            attempt = self.attempts.get(key)
            if attempt is not None:
                attempt.completed, attempt.outcome = True, outcome
            self._prune()

    def _prune(self):
        affected = [key for key, value in self.attempts.items() if value.completed and value.incident]
        for key in affected[:-MAX_ATTEMPTS]:
            del self.attempts[key]

    def reports(self):
        with self.lock:
            result = []
            for attempt in reversed(list(self.attempts.values())):
                if not attempt.completed or not attempt.incident:
                    continue
                result.append((attempt.identifier, self._render(attempt)))
            return result

    def has_reports(self):
        with self.lock:
            return any(attempt.completed and attempt.incident for attempt in self.attempts.values())

    def record_report_issue(self, identifier, code, *, error=None):
        with self.lock:
            for key, attempt in self.attempts.items():
                if attempt.identifier == identifier:
                    self.record(key, code, error=error)
                    break

    def _render(self, attempt):
        # Revalidate at export, including all environment metadata.
        environment = validate_metadata(self.metadata)
        if environment is None:
            return 'Diagnostic metadata unavailable. No private details were included.'
        if type(attempt.identifier) is not str or not re.fullmatch('[0-9a-f]{32}', attempt.identifier):
            return 'Diagnostic report unavailable.'
        header = ['Transfer Credit Dashboard — technical diagnostics',
            'Session only. Copy and paste this report to share it.',
            'Attempt: ' + attempt.identifier, 'Outcome: ' + (attempt.outcome if attempt.outcome in ('success', 'failed', 'cancelled') else 'failed'),
            json.dumps(environment, sort_keys=True, indent=2), '', 'Events:']
        lines = []
        truncated = attempt.truncated
        for source, value in attempt.events:
            event = validate_event(value)
            if event is None or source not in ('desktop', 'worker'):
                truncated = True
                continue
            level, description = CATALOG[event['code']]
            lines.append(f"{event['utc']} +{event['elapsed_ms']}ms [{source}/{level}] {event['code']} — {description} "
                         + json.dumps(event['details'], sort_keys=True))
        while len(('\n'.join(header + lines + ['Diagnostic report truncated.'])).encode('utf-8')) > MAX_REPORT_BYTES and lines:
            del lines[len(lines) // 2]
            truncated = True
        return '\n'.join(header + lines + (['Diagnostic report truncated.'] if truncated else []))
