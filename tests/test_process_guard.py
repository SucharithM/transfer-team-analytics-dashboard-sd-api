"""Windows API contract tests; a real Windows/Edge pilot is still required."""
from types import SimpleNamespace

import pytest

from workflow_dashboard import process_guard


class Function:
    def __init__(self, implementation):
        self.implementation = implementation
    def __call__(self, *args):
        return self.implementation(*args)


def fake_kernel(*, assign=True, configure=True):
    calls = []
    kernel = SimpleNamespace(
        CreateJobObjectW=Function(lambda *args: 101),
        SetInformationJobObject=Function(lambda *args: calls.append(('configure', args[1], args[2]._obj.basic.flags)) or configure),
        OpenProcess=Function(lambda access, inherited, pid: calls.append(('open', pid)) or 202),
        AssignProcessToJobObject=Function(lambda job, worker: calls.append(('assign', job, worker)) or assign),
        CloseHandle=Function(lambda handle: calls.append(('close', handle)) or True),
    )
    return kernel, calls


def test_windows_job_supervises_only_spawned_worker(monkeypatch):
    kernel, calls = fake_kernel()
    # Patch the module's platform view, not the global os.name used by pathlib/pytest.
    monkeypatch.setattr(process_guard, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(process_guard.ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    guard = process_guard.ProcessGuard()
    guard.attach(999)
    guard.close()
    guard.close()
    assert calls == [('configure', 9, 0x2000), ('open', 999), ('assign', 101, 202), ('close', 202), ('close', 101)]


def test_windows_job_assignment_failure_is_not_ignored(monkeypatch):
    kernel, calls = fake_kernel(assign=False)
    monkeypatch.setattr(process_guard, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(process_guard.ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    guard = process_guard.ProcessGuard()
    with pytest.raises(OSError, match='policy'):
        guard.attach(999)
    guard.close()
    assert ('close', 202) in calls
    assert ('close', 101) in calls


def test_windows_configuration_failure_closes_job(monkeypatch):
    kernel, calls = fake_kernel(configure=False)
    monkeypatch.setattr(process_guard, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(process_guard.ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    with pytest.raises(OSError, match='configure'):
        process_guard.ProcessGuard()
    assert calls[-1] == ('close', 101)
