---
id: "sample-chunking"
title: "Heading 기반 Chunking"
source_type: "manual"
document_type: "design"
domain: "development"
project: "second-brain"
language: "ko"
created_at: "2026-07-24T13:00:00+09:00"
updated_at: "2026-07-24T13:00:00+09:00"
observed_at: "2026-07-26T12:00:00+09:00"
tags: [chunking, rag]
access_scope: "private"
llm_policy: "external_allowed"
content_version: 1
---
# Chunk 순서

Markdown heading, 표, 문단, token 제한 순서로 경계를 선택한다.

## 권장 크기

초기 Chunk 크기는 300~800 token을 목표로 한다.
