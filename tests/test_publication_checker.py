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


@pytest.mark.parametrize("kind", ["commit", "tag"])
@pytest.mark.parametrize("reachable", [False, True])
@pytest.mark.parametrize("all_objects", [False, True])
def test_history_metadata_secrets_are_detected_and_redacted(
    publication_repo, monkeypatch, capsys, kind, reachable, all_objects
):
    def git(*args, input=None):
        return subprocess.check_output(
            ["git", "-c", "user.name=Audit Test", "-c", "user.email=audit@example.test", *args],
            cwd=publication_repo, input=input,
        ).strip()

    secret = "ghp_" + "x" * 30
    tree = git("mktree", input=b"")
    oid = git("commit-tree", tree.decode(), input=(secret if kind == "commit" else "Safe commit").encode())
    if kind == "tag":
        oid = git("mktag", input=(
            f"object {oid.decode()}\ntype commit\ntag audit\n"
            f"tagger Audit Test <audit@example.test> 0 +0000\n\n{secret}\n"
        ).encode())
    if reachable:
        git("update-ref", "refs/tags/audit" if kind == "tag" else "refs/heads/audit", oid.decode())
    monkeypatch.setattr(sys, "argv", ["check_publication.py"] + (["--all-objects"] if all_objects else []))

    assert checker.main() == int(reachable or all_objects)
    output = capsys.readouterr().out
    assert secret not in output
    if reachable or all_objects:
        assert f"history {kind} {oid.decode()[:12]}" in output
        assert "GitHub token (value withheld)" in output


def test_safe_commit_and_annotated_tag_pass(publication_repo, capsys):
    subprocess.run(
        ["git", "-c", "user.name=Audit Test", "-c", "user.email=audit@example.test",
         "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "Safe commit"],
        cwd=publication_repo, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=Audit Test", "-c", "user.email=audit@example.test",
         "-c", "tag.gpgsign=false", "tag", "-a", "audit", "-m", "Safe annotation"],
        cwd=publication_repo, check=True,
    )

    assert checker.main() == 0
    assert "2 Git objects" in capsys.readouterr().out


@pytest.mark.parametrize("test_file", [False, True])
def test_unreachable_test_url_exception_requires_a_known_test_path(
    publication_repo, monkeypatch, capsys, test_file
):
    name = "tests/test_url.py" if test_file else "app.py"
    path = publication_repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('url = "https://' + 'user:pass@configured.example.test/packages"\n')
    subprocess.run(["git", "add", name], cwd=publication_repo, check=True)
    tree = subprocess.check_output(["git", "write-tree"], cwd=publication_repo).decode().strip()
    subprocess.run(
        ["git", "-c", "user.name=Audit Test", "-c", "user.email=audit@example.test",
         "commit-tree", tree, "-m", "Unreachable commit"],
        cwd=publication_repo, check=True, capture_output=True,
    )
    subprocess.run(["git", "update-index", "--force-remove", name], cwd=publication_repo, check=True)
    path.unlink()
    monkeypatch.setattr(sys, "argv", ["check_publication.py", "--all-objects"])

    assert checker.main() == int(not test_file)
    output = capsys.readouterr().out
    assert "user:pass" not in output
    if not test_file:
        assert "credential URL (value withheld)" in output
