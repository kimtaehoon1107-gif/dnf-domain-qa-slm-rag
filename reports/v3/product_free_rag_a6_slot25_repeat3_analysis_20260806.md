# ADAPTIVE 진단 — A6 slot 25 세 번 반복

**이미 공개된 A6 문항의 변동성 진단이며 공식 A6 점수와 앞선 adaptive 24/32를 변경하지 않는다.**

## 결과

| 실행 | Qwen raw 출력 | 서버 최종 답변 | 거절 사유 | 지연 |
|---:|---|---|---|---:|
| 1 | 네 정답 모두 생성 | 강철 거푸집 `교환가능` 누락 | `evidence_relevance_below_threshold` | 29.109초 |
| 2 | 네 정답 모두 생성 | 강철 거푸집 `교환가능` 누락 | `evidence_relevance_below_threshold` | 20.682초 |
| 3 | 네 정답 모두 생성 | 강철 거푸집 `교환가능` 누락 | `evidence_relevance_below_threshold` | 17.185초 |

Qwen이 세 번 모두 생성한 내용:

1. 일반 거푸집: 1,900 세라
2. 강철 거푸집: 6,900 세라
3. 일반 거푸집 무기 스킨: 교환불가
4. 강철 거푸집 무기 스킨: 교환가능

서버가 세 번 모두 네 번째 claim만 제거했다. 사용자에게 보인 최종 답변에는 앞의 세 항목만 남았다.

## 재현성

- 실행: 3회
- Qwen 호출: 3회
- 오류·timeout: 0
- 고유 evidence pack: 1개
- 고유 raw Qwen 출력: 1개
- 고유 최종 답변: 1개
- 고유 verifier 거절 집합: 1개
- 원시 결과 SHA-256: `9c6ad547abd1c075b26661896b0c086c38829727fd778c881a83871d3d9277ea`

## 판정

slot 25의 A4 악화는 이번 세 번에서 **3/3 재현**됐다. 검색 근거 누락이나 Qwen의 이해 실패가 아니다. 동일 evidence pack의 E5를 사용해 정답 claim을 생성했지만, minimal verifier의 relevance 검사에서 매번 제거됐다.

따라서 현재 증거가 가리키는 손실 지점은 S4 verifier이며, 일회성 생성 변동으로 돌릴 수 없다. 이번 요청은 반복 측정만 수행했으며 verifier 코드는 수정하지 않았다.
