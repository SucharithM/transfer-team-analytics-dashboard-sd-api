"""Check actual staged blobs independently of files subsequently edited or removed."""

import subprocess
import sys

import pytest

from tools import check_publication as checker


@pytest.fixture
def publication_repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_publication.py", "--working-tree"])
    return tmp_path


@pytest.mark.parametrize("remove", [False, True])
def test_staged_secret_is_detected_after_working_file_is_cleaned(
    publication_repo, capsys, remove
):
    secret = "ghp_" + "x" * 30
    path = publication_repo / "example.txt"
    path.write_text(secret)
    subprocess.run(["git", "add", "example.txt"], cwd=publication_repo, check=True)
    if remove:
        path.unlink()
    else:
        path.write_text("safe text\n")

    assert checker.main() == 1
    output = capsys.readouterr().out
    assert "index example.txt:1: GitHub token" in output
    assert secret not in output


@pytest.mark.parametrize(
    "name",
    [
        "settings.toml",
        "preferences.json",
        "history.sqlite-wal",
        "history.db-shm",
        "data/private/records.json",
        "report.bak",
        ".PRIVATE/records.csv",
        ".streamlit/secrets.toml",
    ],
)
def test_private_artifacts_are_rejected_when_forced_into_index(
    publication_repo, capsys, name
):
    path = publication_repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic local data\n")
    subprocess.run(["git", "add", "--", name], cwd=publication_repo, check=True)

    assert checker.main() == 1
    assert "private artifact" in capsys.readouterr().out


def test_placeholder_and_untracked_safe_source_pass(publication_repo, capsys):
    (publication_repo / ".env.example").write_text(
        "WORKFLOW_API_URL=https://tenant.example.test/packages\n"
    )
    subprocess.run(["git", "add", ".env.example"], cwd=publication_repo, check=True)
    (publication_repo / "app.py").write_text("value = 1\n")

    assert checker.main() == 0
    assert "Inspected 2 publication files" in capsys.readouterr().out


def test_staged_symlink_requires_review(publication_repo, capsys):
    oid = (
        subprocess.check_output(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=publication_repo,
            input=b"/synthetic/private/config",
        )
        .decode()
        .strip()
    )
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", "120000", oid, "reference"],
        cwd=publication_repo,
        check=True,
    )

    assert checker.main() == 1
    assert (
        "index reference: symlink requires publication review"
        in capsys.readouterr().out
    )
