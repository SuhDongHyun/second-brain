from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarkdownValidationError(ValueError):
    """Raised when a Markdown knowledge document is invalid."""


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    project: str | None = None
    language: str | None = None
    created_at: datetime
    updated_at: datetime
    observed_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    tags: list[str]
    access_scope: str = Field(min_length=1)
    llm_policy: Literal["external_allowed", "local_only"]
    content_version: int = Field(ge=1)
    content_hash: str | None = None

    @field_validator(
        "created_at",
        "updated_at",
        "observed_at",
        "valid_from",
        "valid_to",
    )
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("datetime must include a timezone offset")
        return value


@dataclass(frozen=True, slots=True)
class ParsedMarkdown:
    source_path: Path
    metadata: DocumentMetadata
    normalized_content: str
    content_hash: str


def normalize_markdown(text: str) -> str:
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).strip("\n")
    return f"{normalized}\n" if normalized else ""


def _canonical_metadata(metadata: DocumentMetadata) -> dict[str, Any]:
    values = metadata.model_dump(mode="json")
    values.pop("content_hash", None)
    return values


def compute_content_hash(metadata: DocumentMetadata, content: str) -> str:
    canonical = json.dumps(
        _canonical_metadata(metadata),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload = f"{canonical}\n{normalize_markdown(content)}".encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def parse_markdown(path: Path) -> ParsedMarkdown:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MarkdownValidationError(f"cannot read {path}: {exc}") from exc

    raw = raw.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.startswith("---\n"):
        raise MarkdownValidationError("YAML front matter must start with '---'")

    closing = raw.find("\n---\n", 4)
    if closing == -1:
        raise MarkdownValidationError("YAML front matter closing delimiter is missing")

    yaml_text = raw[4:closing]
    body = normalize_markdown(raw[closing + 5 :])
    if not body.strip():
        raise MarkdownValidationError("Markdown body must not be empty")

    try:
        loaded = yaml.safe_load(yaml_text)
        if not isinstance(loaded, dict):
            raise MarkdownValidationError("YAML front matter must be a mapping")
        metadata = DocumentMetadata.model_validate(loaded)
    except (yaml.YAMLError, ValueError) as exc:
        if isinstance(exc, MarkdownValidationError):
            raise
        raise MarkdownValidationError(f"invalid YAML front matter: {exc}") from exc

    return ParsedMarkdown(
        source_path=path.resolve(),
        metadata=metadata,
        normalized_content=body,
        content_hash=compute_content_hash(metadata, body),
    )
