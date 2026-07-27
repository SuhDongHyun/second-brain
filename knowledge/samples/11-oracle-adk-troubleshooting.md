---
id: "sample-oracle-adk-troubleshooting"
title: "Oracle Cloud ADK 접속 문제 해결"
source_type: "personal_note"
document_type: "troubleshooting"
domain: "development"
project: "second-brain"
language: "ko"
created_at: "2026-07-22T12:00:00+09:00"
updated_at: "2026-07-22T15:30:00+09:00"
observed_at: "2026-07-27T10:00:00+09:00"
valid_from: null
valid_to: null
tags: [oracle-cloud, google-adk, networking, troubleshooting]
access_scope: "private"
llm_policy: "external_allowed"
content_version: 1
---
# 증상

Oracle Cloud에서 실행한 Second-Brain API가 Google ADK endpoint에 연결하지 못하고
timeout을 반환했다. 애플리케이션의 API key 설정은 정상적이었다.

## 원인

Oracle Cloud의 egress 방화벽 규칙에서 HTTPS 443 outbound 연결이 허용되지 않았고,
ADK endpoint 환경변수에 이전 테스트 주소가 남아 있었다.

## 해결

VCN security list와 인스턴스 방화벽에서 HTTPS 443 outbound를 허용했다. 그 다음
ADK endpoint 환경변수를 현재 주소로 수정하고 API 프로세스를 재시작했다.

재시작 후 health check와 짧은 모델 요청을 실행하여 DNS 조회, TLS 연결, ADK 응답이
모두 정상임을 확인했다. 자격 증명 값은 문서에 기록하지 않았다.
