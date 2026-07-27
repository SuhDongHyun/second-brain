---
id: "sample-content-hash"
title: "Content Hash 증분 처리"
source_type: "manual"
document_type: "design"
domain: "development"
project: "second-brain"
language: "ko"
created_at: "2026-07-26T09:00:00+09:00"
updated_at: "2026-07-26T09:00:00+09:00"
observed_at: "2026-07-26T12:00:00+09:00"
tags: [hash, ingestion]
access_scope: "private"
llm_policy: "external_allowed"
content_version: 1
---
# 변경 감지

정규화된 본문과 canonical metadata로 SHA-256 hash를 만든다.

## No-op

현재 버전과 hash가 같으면 Chunk와 Embedding을 다시 만들지 않는다.
