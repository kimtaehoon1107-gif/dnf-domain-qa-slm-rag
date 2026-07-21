# v3.2 미구현 개선안 — 기능별 A/B 최종 감사

모든 항목은 독립 Arm으로 검토했다. 개선이 없거나 검증 불가능한 파생본은 보존하되 채택하지 않았고, runtime/canonical 승격은 0건이다.

| 첨부 개선안 | 현재 상태 | 판정 근거 |
|---|---|---|
| 검색·인용용 clean view 통일 | 구현/A-B · NO-GO | 73/82 grounded와 9/82 false-full이 동일해 품질 개선 없음 |
| 표 row-level atomic fact | 구현 · GO 후보 | 초월 비용 값 행과 전체 희귀도 표 복구, exact offset 100%, 회귀 0 |
| 전 출처 temporal 계약 | 구현 · GO 메타데이터 후보 | 980개 문서 계약화, current gold/citation deny 0, 오래된 공지 자동 만료 0 |
| duplicate family 관계 | 구현 · GO 메타데이터 후보 | 7 family/14 member 역할 보존, gold 손실 0, runtime dedup 미적용 |
| 긴 운영정책 조항별 재청킹 | 구현/A-B · NO-GO | late-union 후에도 policy top-10 9/16로 기준선과 동일 |
| FAQ 제목 중복 제거 | 구현/A-B · NO-GO | 279개/9,960자 제거했으나 top-10 11/14로 동일 |
| OCR 구조 복구 | 선행조건 NO-GO · 의도적 미구현 | layout 좌표 0, visual gold group 0; 검증 불가능한 구조 추정은 미구현 |
| top-5/10/20 비교 | 비교 완료 · 추가 이득 없음 | 모든 depth 96/109·75/82·회귀 0; 깊이 증가 이득 0 |

## 현재 채택 가능한 개발 후보

- 표 row atomic fact + complete-table 출력 조립: 초월 가격처럼 희귀도별 값 표를 exact 인용으로 노출한다.
- 전 출처 temporal overlay: 오래된 공지를 날짜만으로 만료시키지 않고 `current_unverified`로 구분한다.
- duplicate family overlay: 이벤트 조건과 상점 가격의 출처 역할을 보존한다.

세 후보 모두 아직 runtime/canonical에는 승격하지 않았다. 조합 후 새 sealed canary가 다음 필수 게이트다.
