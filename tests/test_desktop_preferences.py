import json
from pathlib import Path

import pytest

from workflow_dashboard import desktop_preferences as preferences


@pytest.mark.parametrize("content", [
    "", "{broken", "null", "[]", '"string"', '{"output_directory": 12}',
    '{"output_directory": ""}', '{"output_directory": "relative/path"}',
    '{"output_directory": "/tmp/folder", "token": "synthetic-private-secret"}',
    '{"output_directory": "/tmp/\\u0000folder"}',
])
def test_damaged_or_incompatible_preferences_fall_back(tmp_path, content):
    file = tmp_path / "preferences.json"
    file.write_text(content, encoding="utf-8")
    assert preferences.load_output_directory(file) is None


def test_missing_preferences_and_read_failure_fall_back(tmp_path):
    assert preferences.load_output_directory(tmp_path / "missing.json") is None
    assert preferences.load_output_directory(tmp_path) is None


def test_selected_path_survives_restart_without_importing_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKFLOW_API_TOKEN", "synthetic-private-secret")
    directory = tmp_path / "Reports with spaces — 学生"
    directory.mkdir()
    file = tmp_path / "app" / "preferences.json"
    preferences.save_output_directory(file, directory)
    assert preferences.load_output_directory(file) == directory
    assert json.loads(file.read_text(encoding="utf-8")) == {"output_directory": str(directory)}
    assert "synthetic-private-secret" not in file.read_text(encoding="utf-8")
    assert list(file.parent.iterdir()) == [file]


def test_failed_atomic_save_preserves_previous_selection(monkeypatch, tmp_path):
    file = tmp_path / "preferences.json"
    preferences.save_output_directory(file, tmp_path / "previous")
    original = file.read_bytes()
    def fail_replace(*args):
        raise PermissionError("synthetic-private-secret")
    monkeypatch.setattr(preferences.os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        preferences.save_output_directory(file, tmp_path / "next")
    assert file.read_bytes() == original
    assert list(tmp_path.iterdir()) == [file]


def test_preflight_checks_and_cleans_only_its_own_files(tmp_path):
    existing = tmp_path / "existing.html"
    existing.write_text("keep this")
    assert preferences.validate_output_directory(tmp_path) == tmp_path.resolve()
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_text() == "keep this"


@pytest.mark.parametrize("kind", ["missing", "file", "unwritable"])
def test_preflight_rejects_unavailable_folder(monkeypatch, tmp_path, kind):
    directory = tmp_path / "output"
    if kind == "file":
        directory.write_text("not a directory")
    elif kind == "unwritable":
        directory.mkdir()
        def deny(*args, **kwargs):
            raise PermissionError("permission denied")
        monkeypatch.setattr(preferences.tempfile, "TemporaryDirectory", deny)
    with pytest.raises(OSError):
        preferences.validate_output_directory(directory)
    if directory.is_dir():
        assert not list(directory.iterdir())


def test_chooser_defaults_to_documents_then_home_and_remembered_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert preferences.initial_output_directory(None) == tmp_path
    documents = tmp_path / "Documents"
    documents.mkdir()
    assert preferences.initial_output_directory(None) == documents
    remembered = tmp_path / "Chosen"
    remembered.mkdir()
    assert preferences.initial_output_directory(remembered) == remembered
    assert preferences.initial_output_directory(tmp_path / "unavailable") == documents
