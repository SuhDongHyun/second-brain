from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.ingestion.markdown import ParsedMarkdown

TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")


@dataclass(frozen=True, slots=True)
class ChunkData:
    chunk_index: int
    heading_path: tuple[str, ...]
    chunk_type: str
    chunk_text: str
    token_count: int
    content_hash: str


def estimate_tokens(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def _sections(content: str) -> list[tuple[tuple[str, ...], str]]:
    headings: list[str] = []
    current: list[str] = []
    current_path: tuple[str, ...] = ()
    result: list[tuple[tuple[str, ...], str]] = []
    fence: str | None = None

    def flush() -> None:
        text = "\n".join(current).strip()
        if text:
            result.append((current_path, text))
        current.clear()

    for line in content.splitlines():
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            current.append(line)
            continue

        heading_match = HEADING_RE.match(line) if fence is None else None
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            headings[level - 1 :] = [title]
            current_path = tuple(headings)
        else:
            current.append(line)
    flush()
    return result


def _blocks(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]


def _split_block(block: str, max_tokens: int) -> list[str]:
    if estimate_tokens(block) <= max_tokens:
        return [block]
    matches = list(TOKEN_RE.finditer(block))
    pieces: list[str] = []
    for start in range(0, len(matches), max_tokens):
        group = matches[start : start + max_tokens]
        left = group[0].start()
        right = group[-1].end()
        pieces.append(block[left:right].strip())
    return pieces


def _tail_for_overlap(text: str, overlap_tokens: int) -> str:
    matches = list(TOKEN_RE.finditer(text))
    if not matches or overlap_tokens <= 0:
        return ""
    start = matches[max(0, len(matches) - overlap_tokens)].start()
    return text[start:].strip()


def _chunk_section(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    blocks = [
        piece for block in _blocks(text) for piece in _split_block(block, max_tokens=max_tokens)
    ]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}".strip() if current else block
        if current and estimate_tokens(candidate) > max_tokens:
            chunks.append(current)
            overlap = _tail_for_overlap(current, overlap_tokens)
            candidate = f"{overlap}\n\n{block}".strip() if overlap else block
            if estimate_tokens(candidate) > max_tokens:
                candidate = block
        current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_markdown(
    parsed: ParsedMarkdown,
    max_tokens: int = 800,
    overlap_tokens: int = 100,
) -> list[ChunkData]:
    if max_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("require max_tokens > overlap_tokens >= 0")

    chunks: list[ChunkData] = []
    for heading_path, section in _sections(parsed.normalized_content):
        for text in _chunk_section(section, max_tokens, overlap_tokens):
            digest = hashlib.sha256(text.encode()).hexdigest()
            chunks.append(
                ChunkData(
                    chunk_index=len(chunks),
                    heading_path=heading_path,
                    chunk_type="section",
                    chunk_text=text,
                    token_count=estimate_tokens(text),
                    content_hash=f"sha256:{digest}",
                )
            )
    return chunks


def embedding_text(parsed: ParsedMarkdown, chunk: ChunkData) -> str:
    section = " > ".join(chunk.heading_path) if chunk.heading_path else "(문서 서문)"
    return (
        f"문서: {parsed.metadata.title}\n"
        f"도메인: {parsed.metadata.domain}\n"
        f"섹션: {section}\n\n"
        f"본문:\n{chunk.chunk_text}"
    )
