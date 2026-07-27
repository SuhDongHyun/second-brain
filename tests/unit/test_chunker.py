from pathlib import Path

from app.ingestion.chunker import chunk_markdown, embedding_text
from app.ingestion.markdown import DocumentMetadata, ParsedMarkdown, compute_content_hash


def parsed_document(content: str, metadata: dict[str, object]) -> ParsedMarkdown:
    model = DocumentMetadata.model_validate(metadata)
    return ParsedMarkdown(
        source_path=Path("/tmp/sample.md"),
        metadata=model,
        normalized_content=content,
        content_hash=compute_content_hash(model, content),
    )


def test_tracks_heading_hierarchy_and_ignores_code_heading(
    metadata: dict[str, object],
) -> None:
    parsed = parsed_document(
        """서문입니다.

# A

A 본문

## B

```text
# heading 아님
```

B 본문
""",
        metadata,
    )

    chunks = chunk_markdown(parsed)

    assert [chunk.heading_path for chunk in chunks] == [(), ("A",), ("A", "B")]
    assert "# heading 아님" in chunks[2].chunk_text
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]


def test_splits_large_section_with_bounded_overlap(metadata: dict[str, object]) -> None:
    parsed = parsed_document(
        "# 제목\n\n하나 둘 셋 넷\n\n다섯 여섯 일곱 여덟\n\n아홉 열 열하나 열둘\n",
        metadata,
    )

    chunks = chunk_markdown(parsed, max_tokens=8, overlap_tokens=2)

    assert len(chunks) >= 2
    assert all(chunk.token_count <= 8 for chunk in chunks)
    assert chunks[0].heading_path == ("제목",)


def test_chunking_is_deterministic_and_embedding_text_has_provenance(
    metadata: dict[str, object],
) -> None:
    parsed = parsed_document("# 제목\n\n본문입니다.\n", metadata)

    first = chunk_markdown(parsed)
    second = chunk_markdown(parsed)

    assert first == second
    value = embedding_text(parsed, first[0])
    assert "문서: 샘플 문서" in value
    assert "도메인: development" in value
    assert "섹션: 제목" in value
