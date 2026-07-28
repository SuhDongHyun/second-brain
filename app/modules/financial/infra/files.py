from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def raw_path(
    base: Path,
    stock_code: str,
    year: int,
    receipt_number: str,
    statement_type: str,
) -> Path:
    """Build the deterministic path for one raw statement payload.
    Stock code, year, receipt, and statement scope form the artifact identity."""
    return base / stock_code / str(year) / f"{receipt_number}-{statement_type}.json"


def markdown_path(base: Path, stock_code: str, year: int, receipt_number: str) -> Path:
    """Build the deterministic path for a rendered financial report.
    One Markdown artifact is stored per stock, year, and receipt number."""
    return base / stock_code / str(year) / f"{receipt_number}.md"


def _write_atomic(path: Path, content: str) -> bool:
    """Replace a text artifact atomically only when its content changes.
    A sibling temporary file prevents readers from observing partial writes."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        temporary.replace(path)
        return True
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> bool:
    """Serialize a mapping deterministically and write it atomically.
    The return value reports whether the stored artifact actually changed."""
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return _write_atomic(path, content)


def write_text_atomic(path: Path, content: str) -> bool:
    """Normalize text line endings before an atomic write.
    The stored file always ends with exactly one newline."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return _write_atomic(path, normalized)
