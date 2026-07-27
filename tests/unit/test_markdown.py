from pathlib import Path

import pytest

from app.ingestion.markdown import (
    DocumentMetadata,
    MarkdownValidationError,
    compute_content_hash,
    normalize_markdown,
    parse_markdown,
)


def test_parse_valid_markdown(markdown_file: Path) -> None:
    parsed = parse_markdown(markdown_file)

    assert parsed.metadata.id == "sample-document"
    assert parsed.metadata.created_at.utcoffset() is not None
    assert parsed.normalized_content == "# 개요\n\n테스트 본문입니다.\n"
    assert parsed.content_hash.startswith("sha256:")
    assert len(parsed.content_hash) == 71


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("# no front matter\n", "front matter"),
        ("---\nid: x\n", "closing delimiter"),
        ("---\nid: x\n---\nbody\n", "front matter"),
        (
            """---
id: x
title: x
source_type: note
document_type: note
domain: test
created_at: "2026-01-01T00:00:00"
updated_at: "2026-01-01T00:00:00+09:00"
observed_at: "2026-01-01T00:00:00+09:00"
tags: []
access_scope: private
llm_policy: external_allowed
content_version: 1
---
body
""",
            "timezone",
        ),
    ],
)
def test_rejects_invalid_markdown(tmp_path: Path, contents: str, message: str) -> None:
    path = tmp_path / "invalid.md"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(MarkdownValidationError, match=message):
        parse_markdown(path)


def test_normalize_is_conservative() -> None:
    text = "\ufeffline  \r\n\r\n```python\r\nvalue = 'a  b'  \r\n```\r\n"

    assert normalize_markdown(text) == "line\n\n```python\nvalue = 'a  b'\n```\n"


def test_hash_ignores_input_hash_and_metadata_key_order(metadata: dict[str, object]) -> None:
    first = DocumentMetadata.model_validate({**metadata, "content_hash": "sha256:old"})
    reversed_values = dict(reversed(list(metadata.items())))
    second = DocumentMetadata.model_validate(
        {**reversed_values, "content_hash": "sha256:different"}
    )

    assert compute_content_hash(first, "body\r\n") == compute_content_hash(second, "body\n")
