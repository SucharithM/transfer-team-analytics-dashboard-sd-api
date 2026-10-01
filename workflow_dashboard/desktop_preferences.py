"""Nonsecret, per-user output preferences and export-folder preflight."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def load_output_directory(preferences_file: Path) -> Path | None:
    """Ignore missing, damaged, or incompatible preferences without guessing paths."""
    try:
        with preferences_file.open(encoding="utf-8") as file:
            value = json.load(file)
        if not isinstance(value, dict) or set(value) != {"output_directory"}:
            return None
        directory = value["output_directory"]
        if not isinstance(directory, str) or not directory.strip() or "\0" in directory:
            return None
        path = Path(directory)
        return path if path.is_absolute() else None
    except (OSError, ValueError):
        return None


def save_output_directory(preferences_file: Path, directory: Path) -> None:
    """Atomically replace the preference; no reporting settings or credentials."""
    if not directory.is_absolute():
        raise ValueError("Output directory must be absolute")
    preferences_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=preferences_file.parent,
            prefix=".preferences-", suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump({"output_directory": str(directory)}, file, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, preferences_file)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_output_directory(directory: Path) -> Path:
    """Check the operations publication needs, leaving no probe files behind.

    Called only off Tk's thread; filesystem access can block on network drives.
    """
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        raise NotADirectoryError("Choose an existing output folder")
    with tempfile.TemporaryDirectory(prefix=".dashboard-access-", dir=directory) as probe:
        source = Path(probe) / "write-check"
        source.write_bytes(b"dashboard folder check\n")
        source.replace(Path(probe) / "rename-check")
    return directory


def initial_output_directory(remembered: Path | None) -> Path:
    if remembered is not None and remembered.is_dir():
        return remembered
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()
