# Typed evidence-ref temporal role 연결 결과

작성일: 2026-07-25

## 범위

기존 temporal overlay를 다시 만들지 않고, canonical requirement relation과
evidence unit의 날짜 역할을 generator/verifier 경로에 연결했다.

```text
공식 봉인 결과: 37/64 (변경 없음)
새 모델 호출: 0
검색 재실행: 0
```

## 확인된 연결 누락

문서 수준에는 `published_at`, `valid_from`, `valid_to`, `status`가 있었지만,
문장 단위 evidence에는 `effective_at`, `event_end` 같은 역할이 표시되지
않았다.

또한 verifier는 한국어 `적용일`은 인식했지만 sealed requirement의 canonical
relation인 `effective_at`은 인식하지 못했다.

9번 후보 청크에는 다음 두 날짜가 함께 있었다.

```text
2026.06.02 15:00
→ published_at

6/4(목) 점검 중 업데이트 되는 내용
→ effective_at
```

모델은 게시일을 적용일로 잘못 골랐고 제목 evidence를 인용했다.

## 구현

- evidence unit에 `source_kind`, `valid_from`, `valid_to` 연결
- prompt의 각 evidence line에 `temporal_roles` 표시
- canonical relation 매핑 추가:
  - `effective_at`, `published_at`
  - `download_start`, `deletion_at`
  - `sale_start`, `sale_end`, `sale_period`
  - `event_start`, `event_end`, `event_period`
  - `broadcast_at`, `fixed_at`, `maintenance_time`
  - `revision_cutoff`, `stopped_at`
- 동일 기간 문장 안에서도 첫 날짜와 마지막 날짜를 start/end로 구분
- 인접 heading의 `적용 일자` 문맥을 날짜 evidence에 연결
- account policy의 공식 `valid_from`을 `effective_at`으로 연결
- 단순 `### 업데이트` heading만으로 게시일을 적용일로 판정하지 않음

## 검증

```text
canonical effective_at:
  published_at 2026-06-02 -> temporal_role_mismatch
  6/4 점검 중 업데이트 -> supported_exact

event_end:
  기간 시작일 -> temporal_role_mismatch
  기간 종료일 -> supported_exact

전체 tests/v3:
  676 passed, 54 subtests passed
```

저장된 64문항 출력에 적용한 verifier-only 사후 replay:

```text
진단 점수: 43/64
기존 Typed relation-group/currency v2 대비 점수 변화: 0
회귀: 0
새 LLM 호출: 0
검색 재실행: 0
```

이 replay는 공식 일반화 점수가 아니다. 공식 one-shot은 계속 `37/64`다.

산출물:

- `outputs/v3/diagnostics/typed_evidence_ref_generalization_64_temporal_role_connection_v2.jsonl`
- `reports/v3/typed_evidence_ref_generalization_64_temporal_role_connection_v2_diagnostic.json`
