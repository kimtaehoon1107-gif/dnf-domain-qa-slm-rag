# DNF RAG v3 unified adaptive runtime

## 실행 결과

- adaptive dev rows: 63
- route actions: {'decompose': 4, 'realtime_api': 2, 'reject': 6, 'retrieve': 51}
- successful verified responses: 55/55
- verified claims: 59/59
- retrieval evidence groups: 58/59
- selected evidence groups: 58/59
- cited evidence groups: 47/59
- minimum gold-span token recall: 0.0000
- false-route evidence exposures: 0
- policy violations: 0

## 판정

- unified_runtime_integration: **GO**
- adaptive_end_to_end_quality: **NO-GO**
- extractive_runtime_baseline_promotion: **NO-GO**
- natural_language_generator: **NO-GO**
- production_nli_verifier: **NO-GO**
- final_benchmark: **NO-GO**

## 엄격 게이트 실패

- 외부 메신저 거래 유도 사기 주의사항은 뭐야? (dnf_notice): missing_cited:evidence_1
- 외부 결제 요구 주의사항은 뭐야? (dnf_notice): missing_cited:evidence_1
- 골드 코인 10개 가격과 거래 타입은? (dnf_seria_shop): missing_cited:evidence_1
- 트로피컬 바캉스 패키지 가격과 일괄 삭제일은? (dnf_seria_shop): missing_cited:evidence_1
- 운영정책 위반으로 얻은 재화는 비정상 재화인지 몰랐어도 회수될 수 있어? (dnf_account_policy): missing_cited:evidence_1
- 이용제한에 이의신청하려면 어디로 문의해야 하고 근거 데이터는 얼마나 보관돼? (dnf_account_policy): missing_cited:evidence_1
- 마법부여 상점 설치 방법을 설명해주면서, 수수료와 설치 위치도 내 상황에 맞게 정해줘? (dnf_game_guide): missing_cited:evidence_1
- 비인가 프로그램 사용 주의사항은 뭐야? (dnf_notice): missing_retrieval:evidence_1, missing_selected:evidence_1, missing_cited:evidence_1
- 트레이닝 시뮬레이션은 피로도 써? (dnf_event): missing_cited:evidence_1
- 서약 / 결정 사용 방법은 뭐야? (dnf_game_guide): missing_cited:evidence_1
- 개인정보/인증번호 요구 주의사항은 뭐야? (dnf_notice): missing_cited:evidence_1
- 세라샵 아이템 청약철회는 구입 후 며칠 안에 문의해야 하고, 언제 불가능해? (dnf_faq): missing_cited:evidence_1

이 결과는 adaptive development replay이며 final blind 성능이 아니다.
