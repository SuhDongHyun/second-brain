---
id: "sample-trading-api-role"
title: "trading-api 프로젝트 역할"
source_type: "project_note"
document_type: "project_overview"
domain: "development"
project: "trading-api"
language: "ko"
created_at: "2026-07-23T09:00:00+09:00"
updated_at: "2026-07-23T11:00:00+09:00"
observed_at: "2026-07-27T10:00:00+09:00"
valid_from: null
valid_to: null
tags: [trading-api, fastapi, market-data, orders]
access_scope: "private"
llm_policy: "external_allowed"
content_version: 1
---
# 프로젝트 역할

trading-api는 투자 에이전트와 증권사 API 사이의 통합 경계 역할을 하는 FastAPI
서비스다. 여러 증권사의 서로 다른 요청과 응답 형식을 내부 공통 모델로 변환한다.

## 제공 기능

현재가와 기간별 시세 조회, 계좌 잔고 조회, 주문 요청 검증 기능을 제공한다. 실제 주문
전송은 명시적으로 승인된 요청만 허용하며, 조회 기능과 주문 기능의 권한을 분리한다.

## Second-Brain 연계

Second-Brain에는 trading-api의 설계 결정, 장애 해결 기록과 API 사용법을 저장한다.
검색 에이전트는 이 기록을 이용해 프로젝트 역할과 과거 문제 해결 과정을 설명한다.
