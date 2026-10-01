#!/usr/bin/env python3
"""Offline, redacted publication checks for the index, working tree, and Git history."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": rb"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----",
    "AWS access key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "GitHub token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b",
    "Google API key": rb"\bAIza[\w-]{30,}\b",
    "Slack token": rb"\bxox[baprs]-[\w-]{10,}\b",
    "JWT": rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    "credential URL": rb"(?i)\b(?:https?|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s/\"\x27]+:[^\s/\"\x27]+@",
}
COMPILED = {name: re.compile(pattern) for name, pattern in PATTERNS.items()}
PRIVATE_SUFFIXES = {
    ".db", ".db-journal", ".db-wal", ".db-shm", ".pem", ".key", ".p12", ".pfx",
    ".jks", ".keystore", ".har", ".pcap", ".pcapng", ".pyc", ".log", ".bak",
    ".old", ".orig", ".tmp", ".swp",
}
PRIVATE_DIRECTORIES = {
    ".private", ".publication", ".venv", "venv", "env", "outputs", "build", "dist",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".cache",
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def private_path(name: str) -> bool:
    path = Path(name.casefold())
    return (
        any(part in PRIVATE_DIRECTORIES for part in path.parts)
        or path.parts[:2] == ("data", "private")
        or path.name in {".ds_store", ".pypirc", "settings.toml", "preferences.json", "local_settings.py"}
        or (path.name.startswith(".env") and path.name != ".env.example")
        or path.name.endswith((".local.toml", "~"))
        or path.suffix.startswith(".sqlite")
        or path.suffix in PRIVATE_SUFFIXES
        or ".abstra" in path.parts
        or path.parts[-2:] == (".streamlit", "secrets.toml")
    )


def scan(data: bytes, label: str, *, test_file: bool = False) -> list[str]:
    findings = []
    for name, pattern in COMPILED.items():
        for match in pattern.finditer(data):
            # Literal credentials used solely in URL rejection tests are synthetic.
            if name == "credential URL" and test_file and match.group() == b"https://" + b"user:pass@":
                continue
            line = data.count(b"\n", 0, match.start()) + 1
            findings.append(f"{label}:{line}: {name} (value withheld)")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working-tree", action="store_true", help="Also inspect unignored untracked files")
    parser.add_argument("--all-objects", action="store_true", help="Include unreachable Git blobs")
    args = parser.parse_args()
    staged = []
    for entry in git("ls-files", "--stage", "-z").decode().split("\0"):
        if entry:
            metadata, name = entry.split("\t", 1)
            mode, oid, _ = metadata.split()
            staged.append((mode, oid, name))
    files = {name for _, _, name in staged}
    if args.working_tree:
        files.update(filter(None, git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")))
    findings = []
    for mode, oid, name in staged:
        if mode == "120000":
            findings.append(f"index {name}: symlink requires publication review")
        elif mode == "160000":
            findings.append(f"index {name}: submodule requires publication review")
        else:
            findings += scan(git("cat-file", "blob", oid), f"index {name}", test_file=name.startswith("tests/"))
    for name in sorted(files):
        if private_path(name):
            findings.append(f"{name}: private artifact is tracked or eligible for publication")
        path = ROOT / name
        if path.is_symlink():
            findings.append(f"{name}: symlink requires publication review")
        elif path.is_file():
            findings += scan(path.read_bytes(), name, test_file=name.startswith("tests/"))

    historical = {}
    for row in git("rev-list", "--objects", "--all", "--reflog").decode().splitlines():
        oid, _, name = row.partition(" ")
        historical[oid] = name
        if name and private_path(name):
            findings.append(f"history {oid[:12]} {name}: private artifact exists in reachable history")
    if args.all_objects:
        objects = git("cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)").decode().splitlines()
        blobs = [row.split()[0] for row in objects if row.endswith(" blob")]
    else:
        blobs = [oid for oid in historical if git("cat-file", "-t", oid).strip() == b"blob"]
    for oid in blobs:
        name = historical.get(oid, "unmapped blob")
        findings += scan(git("cat-file", "blob", oid), f"history {oid[:12]} {name}", test_file=name.startswith("tests/"))
    findings = sorted(set(findings))
    print(f"Inspected {len(files)} publication files and {len(blobs)} Git blobs.")
    for finding in findings:
        print(finding)
    if findings:
        print(f"FAIL: {len(findings)} publication findings require review.")
        return 1
    print("PASS: no private paths or supported secret-pattern matches found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
