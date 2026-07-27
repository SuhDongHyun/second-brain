---
id: "sample-access-policy"
title: "외부 LLM 접근 정책"
source_type: "personal_note"
document_type: "policy"
domain: "security"
project: "second-brain"
language: "ko"
created_at: "2026-07-26T11:00:00+09:00"
updated_at: "2026-07-26T11:00:00+09:00"
observed_at: "2026-07-26T12:00:00+09:00"
tags: [security, llm-policy]
access_scope: "private"
llm_policy: "local_only"
content_version: 1
---
# local_only

민감한 문서는 외부 모델에 전달하지 않는다.

## 처리

검색 결과에 포함되더라도 외부 답변 문맥에서는 제외한다.
