---
id: "sample-local-factory"
title: "로컬 Knowledge Factory"
source_type: "personal_note"
document_type: "architecture"
domain: "development"
project: "second-brain"
language: "ko"
created_at: "2026-07-22T11:00:00+09:00"
updated_at: "2026-07-22T11:00:00+09:00"
observed_at: "2026-07-26T12:00:00+09:00"
tags: [ollama, ingestion]
access_scope: "private"
llm_policy: "external_allowed"
content_version: 1
---
# 로컬 처리

로컬 PC는 Markdown 정규화, Chunk 생성, Embedding 생성을 수행한다.

## 원본

민감한 원본과 API 응답 캐시는 Git에 저장하지 않는다.
