# Test artifact freeze contract split — results

## P0 조사

- 직접 freeze 호출 테스트: 15개
- 이미 격리된 테스트: 4개
- 저장소 경로를 사용한 테스트: 11개
- 별도로 확인된 동일 계열 저장소 writer 테스트: 4개
- 기존 오염 테스트가 생성하던 미추적 파일: 14개
- P0 상세 근거: `reports/v3/test_artifact_freeze_contract_split_survey_20260813.json`

## P1 설계

- 봉인 검증은 기존 artifact를 읽고 고정 SHA를 대조하는 읽기 전용 테스트로 분리했다.
- 생성 결정성 검증은 `tmp_path` 아래에만 artifact를 쓰고 두 번의 결과가 같은지 확인한다.
- 프로덕션 기본값은 저장소 root를 유지해 기존 CLI와 승격 스크립트 동작을 바꾸지 않았다.
- `freeze_claim_reranker`는 evaluator source SHA 자체가 canonical 계약이므로 생산 코드를 바꾸지 않고 테스트의 `write_immutable`만 `tmp_path`로 격리했다.

## P2 구현

- 대상 테스트 15개를 읽기 전용 봉인 검증과 임시 경로 생성 검증으로 분리했다.
- 12개 artifact writer에 선택적 `artifact_root`를 추가했다. 인자를 생략하면 이전과 동일하게 저장소 root를 사용한다.
- 이미 출력 디렉터리 인자가 있던 `build_normalized_corpus`와 `freeze_hardening_artifacts`는 생산 코드를 바꾸지 않았다.
- frozen SHA 상수, sealed artifact, `app/`, `app/ui/`, `retrieve_v3.py`는 변경하지 않았다.
- `skip`/`xfail`은 추가하지 않았다.

## P3 검증

- 최초 전체 실행에서 간접 호출 경로인 canonical reranker audit가 evaluator source SHA 변경을 감지했다: 1 failed / 1,377 passed.
- 해당 생산 코드 변경을 원복하고 claim-reranker 생성 테스트의 쓰기만 `tmp_path`로 격리했다.
- 최종 기준: `origin/main` `bbf2d2c79b908a76aa76988d9eb35289eb5ad0a8`에 최종 diff를 적용한 별도 worktree.
- 최종 `python -m pytest tests/v3 -q`: **1,378 passed / 0 failed / 67 subtests passed**.
- 종료 코드: **0**.
- 실행 전후 `git status --porcelain=v1 --untracked-files=all`: **27개 → 27개, 완전히 동일**.
- `git diff --check`: 통과.
- frozen SHA 상수 변경: 0개.
- 새 회귀 실패: 0개.
- Qwen 호출: 0회.

## 판정

**채택.** 테스트가 생산 artifact 경로에 쓰지 않으면서 봉인 무결성과 생성 결정성을 각각 검증한다.
