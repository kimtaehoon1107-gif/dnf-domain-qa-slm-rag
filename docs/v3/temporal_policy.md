# DNF RAG v3 Temporal Policy

## 원칙

시간 적합성은 검색 점수나 최신성 가중치가 아니라 순위 계산 전의 강제
필터다. 운영정책의 기본 현재 질문에는 snapshot에서 current로 확인된 최신
revision 한 개만 허용한다. 오래된 revision은 보존하지만 명시적인 과거 또는
비교 모드 없이는 BM25, dense, reranker 후보가 될 수 없다.

우선순위는 다음과 같다.

```text
시간·상태 적합성 hard filter
→ 허용 revision 확정
→ BM25/dense 검색
→ hybrid/reranker 순위
```

작성일 최신성은 hard filter를 통과한 문서 사이에서만 보조 신호로 사용할 수
있다. 오래 작성된 current 보안 공지를 작성일만으로 제외하지 않는다.

## 운영정책 overlay

기존 DocumentV3는 수정하지 않는다. `dnf_account_policy`의 51개 revision을
같은 `lineage_id`로 정렬하고 별도 content-addressed overlay에 다음 필드를
계산한다.

- `published_at`, `updated_at`
- `valid_from`, 다음 revision 전날로 계산한 `valid_to`
- `status`, `revision_id`, `is_current_revision`
- `supersedes_document_id`, `superseded_by`
- `last_verified_at`, `default_exposure`

`last_verified_at`은 작성일과 별개로 해당 official revision을 snapshot에서
마지막 확인한 시각이다.

## 검색 모드

- `current`: `is_current_revision=true`, `status=current`,
  `default_exposure=true`인 문서 한 개만 허용한다.
- `historical`: `as_of`가 `[valid_from, valid_to]`에 포함되는 revision 한 개만
  허용한다.
- `comparison`: `as_of` revision과 그 직전 revision을 한 쌍으로 허용하고
  결과에 `selected_revision`/`previous_revision` 역할을 붙인다.

허용 `document_id`는 `SearchPolicy.allowed_parent_document_ids`로 전달되어 BM25와
dense 후보 생성 전에 동일하게 적용된다. reranker는 필터를 통과한 후보만
받는다.

## 취소된 6건 검수

`entailment_revision_conflict_packet` 6건은 과거 운영정책 claim을 현재 질문처럼
보이게 만들었으므로 current-QA 평가에 부적합하다. artifact는 실행 이력으로
보존하지만 사람 검수는 취소하며, 학습·최종 benchmark·기본 현재 검색에는
사용하지 않는다.

## 승격 경계

이 사이클의 GO는 운영정책 revision 선택과 검색 전 필터가 정확하다는 뜻이다.
질문 의도를 자동으로 current/historical/comparison으로 분류하는 Router,
Generator, 최종 benchmark 승격은 포함하지 않는다.
