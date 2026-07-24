# Question-partial context answer-unit A/B

## 목적

Arm Q2의 mixed 13문항 중 chunk-level correct partial은 12건이지만, strict span
completeness는 9건이다. 이 A/B는 남은 네 건의 실제 인용과 gold span을 직접
감사하고, 이미 인용한 같은 청크 안에 정답이 남아 있는 경우에만 청크 문맥을
exact-extractive answer-unit으로 보존했을 때의 효과를 측정한다.

## Arm Q3

- 입력은 frozen Arm Q2 결과와 기존 canonical chunk다.
- Gold 기반 span-completeness를 runtime trigger로 사용하지 않는다. Arm Q2의
  question-level partial 신호가 적용된 모든 질문에서 이미 인용한 chunk의
  `display_text` 전체를 exact answer-unit으로 재채점한다.
- chunk ID를 새로 고르거나 source 범위를 넓히지 않는다.
- 원문 전체가 answer-unit이므로 exact substring은 코드로 보장한다.
- Arm Q2가 적용되지 않은 출력만 그대로 둔다.

이 arm은 개발 진단이다. 최종 UI에서 청크 전체를 그대로 보여 주는 승격안이
아니며, 통과하면 후속 구현에서 같은 효과를 내는 더 작은 section/adjacent
answer-unit으로 축소해야 한다.

## 마일리지 잔여 1건

해당 문항은 hard route가 `dnf_seria_shop`만 검색해 `dnf_event` gold chunk가 후보에
없고, question-level partial signal도 개인 계산 요구를 놓쳤다. 기존 frozen
federated A/B에서는 official 두 group이 모두 회수되지만, federated 전체 arm은
다른 문항 회귀로 NO-GO였다. 따라서 이번 arm에는 적용하지 않고 다음 두 문제가
동시에 해결되어야 하는 별도 잔여로 보존한다.

1. 제한적 source-scope fallback
2. 키워드가 아닌 semantic/structural mixed-answerability 판정

## 게이트

- strict mixed span completeness가 9/13보다 개선
- chunk-level correct mixed partial 12/13 유지
- mixed overclaim 0, 기존 correct mixed 회귀 0
- exact substring 100%, partial safety 100%
- docs-only 61/69 chunk 및 45/69 span-value, reject 11/11, realtime 2/2 불변
- gold/질문/코퍼스 변경 0, runtime/canonical 승격 0

## 금지

개별 문항 키워드, gold 기반 runtime 결정, 모델 호출, 학습, 검색·planner·reranker·
assembler 변경, frozen blind 접근을 금지한다.
