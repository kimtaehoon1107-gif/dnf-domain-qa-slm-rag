# 퍼스트 서버(preview_patch) 노출 경계 실행 결과

실행일: 2026-08-10
지시서: `docs/v3/preview_patch_exposure_boundary_plan.md`
최종 판정: **선택지 B 안전 경계 구현 GO / 미카엘라 정상 재실행 partial**

## P0 조사

- canonical 코퍼스: 3,599청크 중 `preview_patch` 105청크, 3문서
- 새 코퍼스 후보: 3,925청크 중 `preview_patch` 260청크, 4문서
- canonical의 preview 문서는 모두 `status=unknown`, `default_exposure=false`,
  `valid_from=null`, `valid_to=null`이다.
- `published_at` 분포: 2026-05-06 26청크, 2026-05-20 55청크,
  2026-07-08 24청크
- 대응 라이브 문서: 3쌍
  - 5/6 preview → 5/13 라이브 업데이트: 7일, 긴 정규화 행 131/144 일치
  - 5/20 preview → 라이브 가이드: 가이드 게시일이 없어 지연 측정 불가,
    88/354 일치
  - 7/8 preview → 7/15 게시(7/16 패치) 라이브 업데이트: 7일,
    57/67 일치
- 저장 artifact 884개를 조사했다.
  - 경로 기준 후보 사례 2,654건 중 preview 후보 213건, preview 인용 108건
  - 실행 fingerprint 중복 제거 후 999건 중 preview 후보 88건, preview 인용 37건
  - preview 인용 질문은 고유 6개: 명시적 퍼스트 서버 질문 5개, 일반 질문 1개
  - 일반 질문 누출 실측: `2026년 5월 고대의 바인드 큐브 8개 상자...`가
    5/20 퍼스트 서버 문서를 경고 없이 인용했다.
- 공식 A6 one-shot과 당시 adaptive에서는 최종 preview 인용이 모두 0건이었다.
- 미카엘라 검색 재현에서 라이브 가이드는 reranker 1·3위,
  7/29 preview는 2·4위였다. 라이브 부재가 아니라 두 출처가 공존한 뒤
  근거 선택 단계에서 preview가 살아남는 문제였다.
- 신규 콘텐츠의 preview-only 기간 가설은 날짜를 잴 수 있는 2쌍에서 모두
  7일로 관측됐지만, 게시일이 없는 가이드가 있어 전체에 일반화할 수 없다.

P0 원자료:
`reports/v3/preview_exposure_survey_20260810.json`
SHA-256: `394d348041e36b1bc79dc96076415a493b9a285dcf7c2fe1691944b842802809`

## P1 설계안

권고·승인안은 **B: preview 검색은 허용하되, 실제 최종 승인 인용에 쓰였을
때 서버가 경고를 강제 표시**하는 방식이다.

서버 경고 문구:

> 퍼스트 서버(테스트 서버) 기준 정보입니다. 라이브 서버 적용 시 변경될 수 있습니다.

선택 이유:

- 전면 제외(A)는 실제 명시적 preview 질문 5개(실행 fingerprint 36건)를
  답하지 못하게 한다.
- 같은 주제의 라이브 문서를 자동 연결하는 C는 안정적인 lineage가 없고
  가이드 게시일도 비어 있어 오연결 위험이 있다.
- 현행 유지(D)는 이미 관측된 일반 질문 누출을 방치한다.
- A6에는 최종 preview 인용이 0건이므로 봉인 결과에는 영향이 없어야 한다.

## P2 구현

`src/v3/product_free_rag.py`에 다음 최소 경계를 추가했다.

1. verifier와 cross-parent 정리가 끝난 **최종 승인 claim**만 검사한다.
2. claim의 E번호를 evidence unit의 chunk/document 메타데이터로 복원한다.
3. `source_kind == "preview_patch"`인 최종 인용이 하나라도 있으면 서버가
   경고를 `rendered_answer` 첫 줄에 직접 삽입한다.
4. 후보에 preview가 있기만 한 경우와 verifier에서 거절된 preview claim에는
   경고를 붙이지 않는다.
5. 감사용으로 `preview_source_notice_required`, `preview_evidence_refs`,
   `preview_source_notice`를 결과에 남긴다.

특정 URL·문서 ID·미카엘라 명칭 분기는 없고, 검색 후보를 제외하거나 순위를
바꾸지도 않았다. `app/`도 수정하지 않았다.

테스트는 수정 전에 실패를 확인한 뒤 다음 4경계를 고정했다.

- 승인된 preview 인용 → 경고 표시
- preview 후보만 있고 최종 인용은 live → 경고 없음
- preview claim이 verifier에서 거절됨 → 경고 없음
- `source_kind`가 청크가 아니라 문서 메타데이터에만 있음 → 경고 표시

## P3 검증

### 회귀

- Product 단위: **129 passed**
- A6 실행 전 preflight: **172 passed**
- 전체 v3: **1,288 passed / 2 failed / 67 subtests passed**
- 두 실패는 작업 전부터 존재한 봉인 manifest SHA 불일치와 동일하다.
  - `test_retrieve_decomposed.py` manifest SHA
  - `test_run_unified_runtime.py` manifest SHA
- 새 회귀 실패: **0**
- `git diff --check`: 통과

### 봉인 A6 저장 출력 재채점(Qwen 0회)

- 32/32 완료
- 자동 채점: 7/32 (기존과 동일)
- non-overclaim 채점 변화 슬롯: 0
- 인용 좌표 복원: 32/32
- 공식 사람 감수 **sealed 20/32 (62.5%)는 불변**
- 봉인 artifact는 수정하거나 재실행하지 않았다.

결과:
`reports/v3/preview_patch_a6_saved_rescore_20260810.jsonl`
SHA-256: `a57327cb599b05de1604fb033259ad18d762684df85c8009ac29e859a908fa43`

### adaptive 32문항(Qwen 32회, 공식 아님)

- 완료: 32/32
- 생성 오류: 0
- 인용 좌표 복원: 32/32
- 자동 의미 채점: 9/32 (이전 실행과 의미 판정 변화 0)
- false-full: slot 6 한 건(기존 판정 유지)
- unsupported overclaim: 0
- 평균 입력 토큰: 2,069.375
- p50: 10.155초
- p95: 14.177초
- 최대: 29.220초
- 30초 초과: 0
- 최종 preview 인용·경고: 0건

이전 adaptive 대비 사용자 답변이 달라진 슬롯은 3개뿐이며, mode·자동 의미
판정·인용 근거는 바뀌지 않았다.

| slot | 이전 | 이번 | 판정 |
|---:|---|---|---|
| 2 | `서버는 8월 13일 다시 열린다` | `서버는 8월 13일 다시 열릴 예정이다` | 시제 표현만 변경 |
| 6 | `필요합니다/살 수 있습니다` | `필요하다/살 수 있다` | 존댓말 어미만 변경 |
| 20 | `[I]키` | `[I] 키` | 띄어쓰기만 변경 |

- mode 변화 슬롯: 없음
- 자동 의미 개선 슬롯: 없음
- 자동 의미 악화 슬롯: 없음

결과:
`reports/v3/preview_patch_a6_adaptive_replay_20260810.jsonl`
SHA-256: `e0e7d40e0c125c4346d881de6780d70f65f23138627a4bc4d2bd140d53441aff`

### 미카엘라 정상 Unicode 재실행

첫 실행의 `unsupported`는 PowerShell here-string을 Python 표준 입력으로
전달하는 과정에서 한글 질문이 `?`로 손상된 테스트 harness 오류였다.
손상된 질문의 lexical token은 0개였으므로 Product RAG 실패로 판정하지
않는다.

질문: `미카엘라 레이드 하드와 일반의 보상 차이 알려줘.`
대상: 별도 새 코퍼스 후보(996문서, 3,925청크)
정상 재실행 결과: `partial`

정상 Unicode 입력의 검색 결과:

- 라이브 가이드: reranker 1·3위
- 7/29 퍼스트 서버 업데이트: reranker 2·4위
- 최종 승인 인용: `preview_patch`의 E2·E3·E6

사용자에게 노출된 답:

```text
퍼스트 서버(테스트 서버) 기준 정보입니다. 라이브 서버 적용 시 변경될 수 있습니다.

미카엘라 레이드 하드 모드에서는 '미카엘라 : 종언서'를 획득할 수 있습니다.
미카엘라 레이드 하드 모드에서는 '광휘의 잔재'를 90개 획득할 수 있습니다.
미카엘라 레이드 일반 모드에서는 '광휘의 잔재'를 40개 획득할 수 있습니다.
미카엘라 레이드 하드 모드에서는 '초월의 의지'를 200개 획득할 수 있습니다.
미카엘라 레이드 일반 모드에서는 '초월의 의지'를 200개 획득할 수 있습니다.
```

- `광휘의 잔재`: 일반 40개 / 하드 90개 — 정확
- `초월의 의지`: 일반 200개 / 하드 200개 — 정확
- 근거에 없는 차이값 재계산 없음
- preview 경고: 답변 첫 줄에 서버가 정상 삽입
- 노출 인용: 모두 원문 좌표로 복원
- 거절 claim 1개: `일반 모드 미카엘라 : 균열서`
  - 선택한 E3·E6에는 균열서가 없으므로 `comparison_values_incomplete`로
    거절한 것이 맞다.
- 총 지연: 18.485초, 생성: 13.218초

## 최종 판정

preview 노출 경계 B안은 의도한 안전 계약을 충족한다.

- 명시적 preview 질의 능력은 검색 단계에서 보존
- 실제 승인 preview 인용만 서버 경고
- 후보만 존재하거나 거절된 근거에는 경고 없음
- sealed 결과와 adaptive 의미 판정 회귀 없음

미카엘라 정상 재실행으로 preview 경고 계약도 end-to-end로 확인됐다.
다만 질문이 넓은 "보상 차이"이므로 모든 보상 종류를 포괄하지 못해
`partial`인 점, 라이브 가이드가 1·3위인데도 최종 atomic 근거는 preview
행을 선택한 점은 다음 evidence coverage/source preference 과제로 남는다.
