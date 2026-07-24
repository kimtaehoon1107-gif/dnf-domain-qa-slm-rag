# Typed evidence-ref 기준선 동결

## 판정

현재 Arm을 새 일반화 평가의 변경 금지 기준선으로 동결한다.

```text
Subject-anchored 검색
→ 질문당 요구 전체를 한 번에 생성
→ 비표: typed value + evidence_ref
→ 표: table-row branch
→ relation / temporal-role / boolean verifier
→ Qwen3 8B ctx8192
```

이 동결은 라이브 승격이 아니다. adaptive 32문항에서 얻은 개발 기준선을 새
human-reviewed 세트에 한 번 적용하기 위한 재현 계약이다.

## adaptive 32 참고 성능

사람 의미 재검수:

| 지표 | 결과 |
|---|---:|
| 후보 보유 | 31/32 |
| 의미 기준 완전 정답 + 직접 근거 | 30/32 |
| 부분답 | 2/32 |
| 실제 false-full | 0/32 |
| 인용 좌표 복원 | 100% |
| 생성 오류 | 0 |
| LLM 호출 | 32 |
| 평균 응답시간 | 20.33초 |
| 전체 토큰 | 149,937 |

5번과 14번은 verifier가 안전하게 차단한 partial이다. 새 세트의 최초 결과를
보기 전에는 두 문항에 맞춘 규칙을 추가하지 않는다.

## 재현성 주의

현재 Git 작업 트리에는 기존 사용자 변경과 이번 연구 변경이 함께 존재한다.
따라서 Git HEAD만으로 현재 Arm을 재현할 수 없다. 동결 manifest는 Git HEAD와
`working_tree_dirty=true`를 기록하고, 실제 실행에 관여한 코드·입력·출력 파일의
SHA-256을 개별 기록한다.

동결 뒤 다음 항목을 바꾸면 동일 Arm으로 간주하지 않는다.

- corpus, temporal overlay, table atomic facts
- BM25 또는 BGE-M3 index
- BGE reranker 모델·revision·max length
- subject-anchored 후보 조립
- typed evidence prompt 또는 출력 schema
- relation, temporal-role, boolean verifier
- Qwen 모델 태그 또는 `num_ctx`

## 변경 잠금

새 평가 파일이 사람 검수와 SHA freeze를 통과하고 최초 A/B가 끝날 때까지:

- adaptive 32문항 규칙 수정 금지
- 검색·reranker 설정 변경 금지
- Qwen 모델 또는 prompt 변경 금지
- verifier 변경 금지
- 속도 최적화 금지

새 평가 준비 규칙은
[typed_evidence_ref_generalization_protocol.md](typed_evidence_ref_generalization_protocol.md)에
기록한다.
