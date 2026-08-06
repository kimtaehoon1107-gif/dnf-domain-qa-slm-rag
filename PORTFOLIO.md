# DNF 공식 문서 QA/RAG — 정직한 측정으로 세 번 바꾼 설계

던전앤파이터 공식 문서에서 답을 찾고, 답의 근거를 원문 좌표까지 복원하는 로컬 QA/RAG 시스템을 만들었다. 이 문서는 가장 높은 숫자만 고르는 성공담이 아니다. SLM 파인튜닝, 타입 계약, 자유 생성형 Product RAG를 차례로 실험하고, 측정이 기대와 다를 때 설계를 바꾼 기록이다.

## 0. 한 눈에

| 무엇을 만들었나 | 현재 구성 | 범위 |
|---|---|---|
| 공식 문서 QA/RAG | BM25 + BGE-M3 → BGE reranker → atomic evidence pack → Qwen3 8B 1회 → 최소 검증 → 서버 인용·표 복원 | 무료·로컬 실행 |
| 평가 체계 | 봉인 세트, SHA 동결, 1회 실행, 사람 근거 검수, adaptive 진단 분리 | 성능보다 측정 정직성 우선 |

| 시스템·평가 | 최종 숫자 | 해석 |
|---|---:|---|
| v3 typed, **sealed** | **37/64** | 타입 계약 시스템의 공식 봉인 결과 |
| Product Free RAG A6, **sealed 자동 채점** | **7/32 (21.9%)** | 표면값 중심 자동 채점 결과 |
| Product Free RAG A6, **sealed 사람 감수** | **20/32 (62.5%)** | 봉인 출력을 근거와 대조해 확정한 공식 결과 |
| 숫자 해석 제한 | 비교 금지 | 64문항과 32문항은 서로 겹치지 않는 다른 벤치마크이며 난이도도 통제되지 않았다. 어느 시스템이 더 낫다는 비교에는 사용할 수 없다. |

| 판정 대상 | 판정 | 이유 |
|---|---|---|
| 포트폴리오 공개 | **GO** | 성공뿐 아니라 실패, 측정 오류, 기각한 개선안까지 재현 가능하게 남김 |
| Product Free RAG 제품 기본 경로 승격 | **NO-GO** | A6 사람 감수 정확도가 목표 80%에 미달하고 한 건의 unsupported overclaim이 남음 |

## 1. 문제 정의

공식 문서 QA는 “관련 문서를 찾고 문장을 요약한다”로 끝나지 않는다. 같은 단어와 숫자가 한 문서 안에서 다른 조건을 가질 수 있고, 게시 시점과 적용 시점이 다르며, 표의 셀 안 대상명과 표 전체를 지배하는 주어가 다를 수 있다.

대표 사례가 A6-7이다. 공식 업데이트에는 같은 스킬 이름을 포함한 값 두 쌍이 있다.

```text
- 타이드 바운드 -
쿨타임이 감소합니다. (20초 → 18초)

- '질풍' 스킬 개화 옵션이 변경됩니다.
| 변경 전 | 변경 후 |
| [타이드 바운드] ... 기본 쿨타임 12초 ... |
| [타이드 바운드] ... 기본 쿨타임 9초 ... |
```

질문의 첫 요구는 평시 타이드 바운드의 `20초 → 18초`, 두 번째 요구는 질풍 개화 조건의 `12초 → 9초`다. 숫자는 모두 문서에 있지만 조건을 하나 놓치면 존재하는 숫자로 틀린 답을 만들게 된다. 이 사례의 원문 청크와 좌표는 [A6 adaptive replay](reports/v3/product_free_rag_a6_pending_adaptive_replay_20260806.jsonl)에 보존돼 있다.

시간도 답의 일부다. 이벤트의 진행 여부, 판매 기간, 정책 revision은 질문의 기준일에 따라 답이 달라진다. 그래서 현재·최신·진행 중·전체 개수처럼 집합 연산이 필요한 질문은 메타데이터 경로로 보내고, 특정 문서의 사실은 일반 RAG로 처리한다.

표는 더 까다롭다. 행 안에는 `[타이드 바운드]`가 적혀 있지만, 바로 위 도입문은 그 행이 `'질풍' 스킬 개화 옵션`임을 규정한다. 셀만 잘라 검색하거나 생성하면 “표에 있는 값”과 “질문한 대상의 값”이 분리된다.

## 2. 세 번의 방향 전환

첫 방향은 작은 언어 모델을 도메인에 파인튜닝하는 것이었다. 동일 검색 조건에서 RAG-only, base Qwen, LoRA tuned Qwen을 비교했다. tuned 모델은 Partial 처리와 형식 준수에서 개선됐지만, 개봉 전 게이트인 fresh false joint와 unsupported 명시적 거절을 통과하지 못했다. blind 100문항은 열지 않았고 SLM 파인튜닝을 제품 경로로 밀어붙이지 않았다.

두 번째 방향은 생성을 강한 타입 계약으로 묶는 것이었다. 모델이 `subject`, `relation`, typed `value`, `evidence_ref`를 출력하고 서버가 다단계로 검증했다. **sealed 37/64**를 얻었지만 96개 요구 중 명시적 relation 계약은 **22개**뿐이었다. 알려진 관계를 안전하게 다루는 대신 새로운 표현과 관계를 받기 어려워 실사용 경로로 승격하지 않았다. 근거는 [v3 봉인 결과](reports/v3/typed_evidence_ref_generalization_64_relation_group_currency_v2.json)와 [96개 relation inventory](reports/v3/typed_evidence_ref_relation_inventory_96_20260727.json)에 있다.

세 번째 방향은 모델에게 질문 해석과 문장 작성을 돌려주되, 서버가 짧고 좋은 근거와 최소 안전장치를 제공하는 것이었다. 이것이 현재 실험 경로인 Product Free RAG v1이다. 공식 A6 봉인 출력의 사람 감수 결과는 **sealed 20/32**다. 이 숫자는 앞의 37/64와 다른 문항·다른 시스템에서 나온 값이며 두 결과 사이의 우열을 뜻하지 않는다.

## 3. 1막 — SLM 파인튜닝 (v1/v2)

목표는 0.5B급 SLM이 공식 문서 근거를 읽고 `answerability`, 답변, 인용을 안정적으로 출력하게 만드는 것이었다. BGE-M3 hybrid 검색 조건을 고정한 뒤 RAG-only, base Qwen2.5-0.5B, clean LoRA tuned Qwen을 세 축으로 비교했다.

다음 두 표는 봉인 성능이 아니라 모델 선택에 사용한 **adaptive development evaluation**이다. Fresh conversational dev 30문항 결과는 다음과 같다.

| 지표 | RAG-only | Base Qwen + RAG | Clean tuned Qwen + RAG |
|---|---:|---:|---:|
| schema compliance | 30/30 | 0/30 | 30/30 |
| answerable true | 16/16 | 0/16 | 15/16 |
| exact citation | 14/22 | 0/22 | 14/22 |
| Partial joint | 0/6 | 0/6 | 3/6 |
| false joint | 5/8 | 0/8 | 5/8 |
| retrieval expected hit | 21/22 | 21/22 | 21/22 |

사람이 검수한 Partial dev 20문항에서는 tuned 모델의 장점과 한계가 더 분명했다.

| 지표 | RAG-only | Base Qwen + RAG | Clean tuned Qwen + RAG |
|---|---:|---:|---:|
| schema compliance | 20/20 | 0/20 | 20/20 |
| exact citation | 6/20 | 0/20 | 12/20 |
| Partial joint | 0/20 | 0/20 | 8/20 |
| strict requirement joint | 0/20 | 0/20 | 3/20 |
| grounded and cited slots | 6/31 | 0/31 | 11/31 |
| unsupported explicit abstention | 0/21 | 0/21 | 8/21 |
| unsupported overanswer | 2/21 | - | 0/21 |

따라서 “RAG-only가 모든 면에서 tuned보다 낫다”도, “tuned가 제품 준비를 끝냈다”도 아니었다. tuned는 구조와 Partial에서 좋아졌지만, blind 개봉 전 사전 게이트는 fresh false joint `7/8 이상`과 unsupported explicit abstention `14/21 이상`이었다. 실제 결과는 각각 `5/8`, `8/21`이어서 frozen blind 100문항을 소모하지 않았다. 학습을 더 돌리는 대신 제품 문제를 검색·근거·검증의 구조 문제로 다시 정의했다.

데이터 구축, RAFT, 누수 검사, 체크포인트 선택의 상세 기록은 [DNF Domain QA SLM/RAG v2](PORTFOLIO_REPORT.md)에 남겨 두었다. 위 수치의 집계 근거도 해당 문서 §7과 [final comparison artifacts](reports/final_dev_system_comparison.json)에 있다.

## 4. 2막 — 타입 계약 파이프라인 (v3)

v3 typed 경로는 자유 문장 하나가 아니라 “무엇에 대한 어떤 값이며 어느 근거가 증명하는가”를 모델 출력에 포함시켰다.

```json
{
  "subject": "최후의 과업",
  "relation": "입장 명성",
  "value": {"type": "number", "value": 108921},
  "evidence_ref": "E1"
}
```

서버 검증은 다섯 층이었다.

1. typed value와 출력 스키마가 계약을 지키는지 확인한다.
2. `evidence_ref`가 제공된 근거이고 원문 청크 좌표가 exact slice인지 확인한다.
3. revision과 질문의 시간 조건이 맞는지 확인한다.
4. subject·relation·value가 같은 evidence group 안에서 결속되는지 확인한다.
5. 숫자·화폐·날짜·시각을 정규화한 뒤 인용 근거의 값과 일치하는지 확인한다.

공식 성능 주장은 [봉인 64문항 결과](reports/v3/typed_evidence_ref_generalization_64_relation_group_currency_v2.json)의 **sealed 37/64**다. 후속 replay에서 점수가 달라진 경우도 있지만 저장 출력 재채점과 adaptive 진단이므로 봉인 헤드라인을 대체하지 않았다.

승격하지 않은 결정은 성능 숫자 하나보다 계약의 외연 때문이었다. 봉인 결과를 연 뒤 수행한 **adaptive contract audit**인 [96개 요구 inventory](reports/v3/typed_evidence_ref_relation_inventory_96_20260727.json)에서 고유 relation은 73개였고, 명시적 alias 계약은 **22/96**, 나머지 74개는 unvalidated였다. 관계 이름을 계속 등록하면 알려진 질문은 통제할 수 있지만 질문 표현이 늘 때마다 서버가 먼저 의미를 규정해야 했다. 이 구조는 연구 파이프라인으로 보존하고 제품 경로에서는 제거했다. 상세 설계는 [typed v3 기록](PORTFOLIO_V3_DRAFT.md)에 있다.

## 5. 3막 — Product Free RAG (현재)

### 5-1. 파이프라인

```text
질문
→ Unicode·띄어쓰기 정규화
→ 집합 연산 질문만 metadata routing
→ 전체 질문 + 요구 절별 검색
→ BM25 top 20 + BGE-M3 top 20 (0.25 / 0.75 hybrid)
→ 질의별 결과 union
→ BGE reranker
→ top 8, parent 문서당 최대 2개
→ atomic evidence pack 최대 8개
→ Qwen3 8B 한 번
→ 인용·핵심값·날짜·질문 관계 최소 검증
→ 서버가 원문 인용과 완전한 표를 복원
```

기억에 의존하지 않고 현재 코드의 상수를 확인했다. [retrieve_v3.py](src/v3/retrieve_v3.py)는 BM25와 dense 후보를 각각 20개까지 찾고 BGE-M3에 0.75, BM25에 0.25를 둔다. [product_free_rag.py](src/v3/product_free_rag.py)는 전체 질문과 요구 절을 중복 제거한 뒤 각 질의의 top 20을 합치고, `BAAI/bge-reranker-v2-m3`로 재정렬한다. 최종 후보는 8개이며 같은 parent는 최대 2개다.

atomic pack은 후보 청크를 관련 문장·표 행 단위로 자른다. Qwen에게 긴 SHA와 좌표를 쓰게 하지 않고 `E1`~`E8`만 보인다. atomic prefilter는 요구 질의당 32개, 복수 요구에서는 질의당 3개를 먼저 예약한다. Qwen 호출은 `qwen3-8b:ctx8192`, 입력 context 한도 4,096토큰, 출력 한도 768토큰으로 한 번만 수행한다. 완전한 표는 Qwen이 다시 쓰지 않고 서버가 원문 행을 렌더링한다.

검증기는 선택한 E번호가 실제 pack에 있는지, 답의 숫자·날짜·시각·화폐가 인용 근거에 있는지, 질문에 명시된 시간·관계 조건과 근거가 맞는지를 본다. 자연어 모든 토큰의 포함이나 relation 이름 허용목록은 제품 경로의 계약으로 사용하지 않는다. 거절된 claim은 사용자 답에서는 제거하지만 내부 `rejected_claims`에 남겨 실패 원인을 감사할 수 있다.

### 5-2. 봉인 평가 규율

```text
평가 계약 작성
→ 사람 문항 검수
→ JSONL과 manifest SHA 동결
→ 정확히 한 번 실행
→ 출력 공개 뒤 재실행 영구 금지
```

A6 frozen set SHA는 `9405401d76c87b28418b795716938a3d62578644f33f2e853ddf18fc689b65dc`, freeze manifest SHA는 `4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499`다. 실제 one-shot 결과와 실행 journal은 [A6 결과](reports/v3/product_free_rag_a6_one_shot_4d47ef5d760fdb589fd1a81217d52908a77bd76a78b875384cd2315880c78499.jsonl)에 남아 있다.

출력을 본 뒤의 변경과 재생성은 adaptive다. 같은 질문에서 좋아져도 공식 A6 점수를 바꾸지 않는다. 2026-08-06 adaptive replay의 사람 진단은 **adaptive 24/32 (75.0%)**였지만 공식 결과는 계속 **sealed 20/32**다. adaptive에서 공식 정답 slot 25가 한 건 악화됐기 때문에 이 arm도 승격하지 않았다. 근거는 [adaptive 적용 보고서](reports/v3/product_free_rag_pending_apply_and_adaptive_replay_20260806.md)다.

### 5-3. 자동 21.9%와 사람 62.5% 사이

공식 A6 자동 채점은 **sealed 7/32 (21.9%)**, 동일 저장 출력의 사람 감수는 **sealed 20/32 (62.5%)**였다. 약 40%p 차이는 모델이 갑자기 좋아진 것이 아니라 측정기가 날짜 축약, 값의 어순, 표 서버 렌더링, 정상 partial을 놓친 결과다. 예를 들어 `2025-09-11`과 `25.09.11`, `숫자 6자리`와 `6자리 숫자`를 다른 값으로 보거나, Qwen이 아니라 서버가 복원한 완전한 표를 claim overlap만으로 실패 처리했다.

사람 감수는 모델에게 유리한 정답만 추가하는 절차가 아니었다. slot 22의 근거 없는 보고 채널·기한은 unsupported overclaim 한 건으로 남겼다. 반대로 slot 6에서는 공식 원문이 “태초 서약 중 1종을 균등한 확률로 획득”한다고 말하는데 frozen gold가 그 답을 unsupported로 둔 오류를 발견했다. 봉인셋은 고치지 않고 [append-only 판정 overlay](reports/v3/product_free_rag_a6_slot6_readjudication_20260806.json)에 `gold error 1`로 기록했다.

공식 sealed A6의 다른 안전·효율 수치는 false-full 0, 인용 좌표 32/32, 생성 오류 0, 평균 입력 1,923.4토큰이다. 자동 scorer의 value+claim complete는 29/61이었다. 공식 사람 판정의 남은 실패 슬롯은 `1, 2, 4, 7, 10, 11, 13, 14, 22, 26, 28, 32`이며 제품 기본 경로 승격은 NO-GO다.

## 6. 실패 분석

### 6-1. 어디서 답이 사라졌는가

실패를 한 덩어리의 “정확도”로 부르지 않고 최초 손실 단계에 귀속했다.

| 단계 | 의미 | 공식 one-shot 실패 요구 | adaptive 실패 요구 |
|---|---|---:|---:|
| S1 | 검색 후보에 정답 문서가 없음 | 1 | 1 |
| S2 | 후보에는 있지만 pack이 정답 단위를 고르지 못함 | 5 | 1 |
| S3 | 근거를 받았지만 생성이 누락·오연결 | 3 | 3 |
| S4 | 맞는 claim을 verifier가 제거 | 4 | 3 |
| S5 | 존재하는 값을 다른 관계·대상에 결속 | 1 | 0 |
| 합계 | 요구 단위 | 14 | 8 |

공식 열은 봉인 one-shot, adaptive 열은 ranking context와 요구 예약을 적용한 진단 결과다. 같은 척도의 제품 점수 비교가 아니라 손실 위치를 찾기 위한 단계 귀속이다. 세부 요구별 이동은 [adaptive 적용 보고서의 A5](reports/v3/product_free_rag_pending_apply_and_adaptive_replay_20260806.md)에 있다.

### 6-2. A6-7 — 정보를 모두 줘도 조건이 떨어졌다

원문 청크 `chunk_sha256_b85cf9c381f143cf45072d4a3738bdb2bebdba4634eb37cd962defa2798fc3f6`에는 두 정답이 모두 있다.

```text
서버 근거 단위 189:224
  frozen gold 191:224  타이드 바운드 - 쿨타임이 감소합니다. (20초 → 18초)

frozen gold 273:430
  표 도입: - '질풍' 스킬 개화 옵션이 변경됩니다.
  [타이드 바운드] ... 기본 쿨타임 12초 → 9초
```

adaptive 실행에서 모델이 받은 핵심 evidence JSON도 이미 주어 문맥을 포함했다.

```json
[
  {
    "evidence_ref": "E1",
    "text": "| [타이드 바운드] ... 기본 쿨타임 12초 ... | ... 기본 쿨타임 9초 ... |",
    "context_text": "표 도입: - '질풍' 스킬 개화 옵션이 변경됩니다."
  },
  {
    "evidence_ref": "E2",
    "text": "- 타이드 바운드 - 쿨타임이 감소합니다. (20초 → 18초)"
  }
]
```

그런데 한 번 호출한 모델은 다음처럼 답했다.

```text
타이드 바운드 쿨타임은 12초에서 9초로 줄었습니다.
질풍 개화 옵션의 기본 쿨타임은 12초에서 9초로 바뀌었습니다.
```

결정적 실험은 요구별 fan-out이었다. 첫 질문만 준 호출에서도 표 행 `F1E1`을 타이드 바운드 본체에 결속해 `12→9`를 만들었고, 두 번째 질문만 준 호출에서는 같은 원문 단위 `F2E1`을 질풍 옵션에 결속해 올바른 `12→9`를 만들었다. 동시에 첫 호출은 별도 근거에서 올바른 `20→18`도 생성했다. 즉 검색 누락도, 숫자 환각도 아니었다. 문서 안에 실제로 있는 숫자에서 **조건만 탈락**했다. [fan-out 엄격 재채점](docs/v3/product_free_rag_requirement_fanout_experiment_results_20260806.md)은 핵심 게이트를 0/2로 판정했다.

이 실패에 여섯 번 접근했지만 모두 승격하지 않았다. 아래 결과는 공개된 A6-7을 대상으로 한 **adaptive 진단**이다.

| 시도 | 겨냥한 문제 | 관찰과 결정 |
|---|---|---|
| 표 주어 결속 | 도입문을 evidence context에 추가 | `'질풍'` 문맥이 이미 모델 입력에 있었지만 첫 답은 계속 `12→9`; NO-GO |
| ranking context | 도입문을 근거 순위에도 사용 | 정답 두 단위가 pack에 함께 있어도 오결속 유지 |
| 절 분해 F0 | 복수 요구를 Kiwi로 분리 | 목표 8/8은 복구했지만 비목표 과분해와 A6-26 mode 악화로 롤백 |
| 요구별 예약 | 각 절의 근거를 pack에 보존 | `20→18` 가시성은 복구했지만 생성이 표 값을 먼저 결속 |
| fan-out F1 | 절마다 Qwen을 따로 호출 | 정답 값은 모두 나왔지만 오답도 함께 생성; 엄격 게이트 0/2, A6-7 30.219초 |
| 규칙 차단 b안 | 표 도입문을 verifier 주어 게이트로 사용 | 일반화 근거가 너무 희소해 구현 전 기각 |

b안은 “해보고 나빠서”가 아니라 **adaptive 규칙 설계 audit**에서 코퍼스 통계로 사전 기각했다. 저장된 A6 출력에서 표 딱지를 인용한 claim 18건 중 사람이 확인한 진짜 주어 라벨은 2건뿐이었다. 전체 표 1,532개 가운데 직전 비어 있지 않은 줄에 따옴표 도입부가 있는 표는 29개, **1.9%**였다. 희소한 모양을 일반 규칙으로 만들면 대부분의 표에 주어를 발명하거나 정답을 차단할 위험이 컸다. 근거 원장은 [A6 adaptive replay](reports/v3/product_free_rag_a6_pending_adaptive_replay_20260806.jsonl)와 [표 도입부 전수 진단](reports/v3/product_table_introducer_s1_20260805.jsonl)이다.

이 사례는 정보 배치를 더 정교하게 하는 것만으로 넘기 어려운 8B 모델의 조건·주어 결속 한계를 보여준다. 더 많은 규칙은 이 한 문항을 맞힐 수 있지만, 일반화 안전성을 증명하지 못하면 제품 개선으로 채택하지 않는다.

### 6-3. slot 25 — 안전장치가 정답을 죽였다

slot 25에서 Qwen은 일반 거푸집 `1,900 세라`, 강철 거푸집 `6,900 세라`, 일반 무기 스킨 `교환불가`, 강철 무기 스킨 `교환가능`을 모두 정확한 근거와 함께 생성했다. 그러나 minimal verifier가 네 번째 claim을 `evidence_relevance_below_threshold`로 제거했다.

일회성 생성 변동인지 확인한 adaptive 3회 반복에서 evidence pack, raw Qwen 출력, 최종 답변, 거절 집합이 모두 각각 하나로 동일했다. **adaptive 3/3**에서 같은 정답 claim이 제거됐고 지연은 29.109초, 20.682초, 17.185초였다. 검색이나 생성이 아니라 S4 verifier 과차단이다. 근거는 [slot 25 반복 진단](reports/v3/product_free_rag_a6_slot25_repeat3_analysis_20260806.md)이다.

검증기는 오답을 막는 동시에 정답을 지울 수 있다. 따라서 “차단 건수”만으로 안전성을 주장하지 않고 `실제 오답 차단 / 실제 정답 차단`을 함께 측정한다.

### 6-4. 채택하지 않은 개선안

| 개선안 | 사전 게이트 결과 | 결정 |
|---|---|---|
| question coverage contract | A6-7 값·관계 FAIL, A6-32 모델 unsupported 분리 FAIL, 형식 계약만 PASS | 기본값 `False` 유지 |
| requirement fan-out | A6-7·A6-32 엄격 핵심 게이트 **0/2**, 인용은 통과, A6-7 지연 30.219초 | 기본값 `False`, F2·F3 중단 |
| 표 주어 결속 | context 추가와 좌표 보존은 성공했지만 A6-7 첫 요구 오답 유지 | 런타임 변경 롤백 후 진단만 보존 |
| 표 도입부 규칙 차단 | claim 라벨 2/18, 따옴표 도입부 29/1,532 | 구현 전 기각 |

표의 개선안 결과는 모두 공개 문항을 이용한 **adaptive 진단**이다. 각 실험은 한 문항을 맞혔는지가 아니라 사전 등록한 회귀·안전·지연 게이트를 모두 통과했는지로 결정했다. 자세한 coverage 결과는 [coverage contract 재평가](reports/v3/product_free_rag_coverage_contract_reeval_20260805.md), 표 결속 결과는 [table subject binding](docs/v3/product_free_rag_table_subject_binding_results_20260805.md)에 있다.

## 7. 측정을 의심한 기록

### p95 332초를 곧바로 제품 지연으로 부르지 않았다

공식 A6 one-shot의 **sealed p95는 332.729초**였다. 처음에는 질문별 난이도, 계측되지 않은 구간, 파이프라인 자체의 간헐 정지를 차례로 의심했다.

1. 질문 의존 가설은 같은 질문이 후속 실행에서는 8~13초에 끝난 사실과 맞지 않았다.
2. 미계측 공백 가설은 50회 단계 분해에서 `unattributed` 최대 약 3ms로 반박됐다.
3. 파이프라인 고유 tail 가설은 외부 GPU 앱을 끄고 한 통제 측정과 맞지 않았다.

외부 GPU 앱이 없음을 preflight와 회차 경계에서 확인한 50회 통제 측정은 **adaptive 진단 p50 7.528초, p95 11.579초, max 25.161초, 30초 초과 0/50, 오류 0**이었다. 이전 tail은 GPU 자원 경합의 영향을 받은 측정과 일치한다. 다만 당시 GPU 상태를 동시에 기록하지 않았으므로 인과를 확정하지는 않았다. 그래서 단일 p95 대신 측정 유효성, cold 첫 요청, warm p95, 30초 초과율을 함께 보자는 결론을 냈다. 원시 해석은 [latency tail 조사](reports/v3/product_free_rag_latency_tail_investigation_20260805.md)와 [통제 재측정](reports/v3/product_free_rag_latency_gate_and_controlled_remeasure_20260805.md)에 있다.

### overlap을 “근거가 보인다”로 부른 오류

A6-7에서 기존 `55/62 visible`은 gold 좌표와 조금이라도 겹치면 성공으로 셌다. 앞 문장 `쿨타임이 감소합니다.`만 남고 괄호 값 `(20초 → 18초)`이 빠져도 좌표가 겹쳐 통과했다. 이를 확인한 뒤 단순 overlap 대신 요구 숫자·날짜·시각·화폐가 pack에 실제 존재하는 `value_present` 측정을 추가했다. [표 주어 결속 결과](docs/v3/product_free_rag_table_subject_binding_results_20260805.md)에 반례가 보존돼 있다.

### 자동 채점기를 정답으로 간주한 오류

A6 자동 채점 **sealed 7/32**를 그대로 모델 성능으로 읽으면 같은 출력의 사람 판정 **sealed 20/32**를 설명할 수 없다. 표면 일치에 강한 자동 scorer는 회귀 신호로 유지하되 최종 의미 판정은 질문·답·원문 근거를 한 건씩 대조했다. 동시에 slot 22 overclaim과 slot 6 gold 오류를 남겨 사람 판정도 감사 가능하게 만들었다.

### fan-out의 첫 자동 게이트를 다시 뒤집었다

fan-out 초벌 체크는 필요한 값이 출력에 “존재하는지”만 보고 A6-7을 좋아진 것으로 읽었다. 하지만 `20→18`과 함께 금지해야 할 `12→9`가 첫 요구에도 붙어 있었다. 저장 출력을 추가 호출 없이 엄격 재채점해 요구별 금지 값과 unsupported 상태를 함께 검사했고, 최종 핵심 게이트를 **adaptive 0/2**로 정정했다. 개선 실험의 채점기도 실험 대상이라는 교훈이었다.

## 8. 기술 스택과 재현

### 8-1. 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 언어·실행 | Python, PyTorch, CUDA |
| lexical 검색 | BM25 |
| dense 검색 | `BAAI/bge-m3` |
| reranker | `BAAI/bge-reranker-v2-m3` |
| 생성 | Ollama `qwen3-8b:ctx8192` |
| UI·API | Gradio, FastAPI |
| 데이터·평가 | JSONL, content-addressed SHA, 사람 adjudication overlay |

생성과 평가 실행은 로컬 Ollama를 사용했고 유료 생성 API 호출은 0회다. 모델에 원문 전체를 복사시키지 않고 서버가 보존한 좌표로 인용과 표를 복원한다.

### 8-2. 코퍼스 스냅샷

```text
코퍼스 스냅샷   2026-07-17 수집 · 07-18 정규화 · 07-21 검색용 청크 확정
규모            문서 980 · 청크 3,599
갱신 절차       discover_sources → collect_details → 정규화 → 청킹
                → BM25 재빌드 → dense 재임베딩
```

수집 범위 기준일과 현재 런타임 아티팩트는 [free minimal runtime snapshot](data/v3/runtime/free_minimal_runtime_snapshot_v1.json), 문서·청크 수는 [normalized corpus manifest](data/v3/normalized/normalized_corpus_manifest_3ba1afc14def8d2da1f7297679f02df6ff690e6fd18298931d3b108dcd064ebf.json)와 [chunk corpus manifest](data/v3/chunks/chunk_corpus_manifest_87fb0fc3477088cf6245e8bd3fd7719374a7dbf778094d5e36fa43458dd54c00.json)에 고정돼 있다. 원시 청크 빌드는 07-18, `retrieval_text` 정리 스냅샷은 [07-21 manifest](data/v3/chunks/retrieval_clean_corpus_manifest_01a1d281a8f9054bce6c79b5a70e0e0d33b19c7cd8b48e8de893ffed894ca129.json)에 기록돼 있다. “현재 최신”이라고 주장하지 않고 이 기준일을 명시한다.

코퍼스 갱신이 기존 봉인 인용 좌표를 전부 무효화하지 않는 이유는 청크 ID가 전역 인덱스 순번이 아니라 문서 로컬 값으로 만들어지기 때문이다. [build_chunks.py:124](src/v3/build_chunks.py#L124)의 실제 계약은 다음과 같다.

```python
display_hash = sha256(display_text)
payload = (parent_document_id + offset_source + start_offset + end_offset
           + display_hash + chunker_version)
chunk_id = "chunk_sha256_" + sha256(payload)
```

새 문서를 추가해도 기존 문서의 위 값은 바뀌지 않아 기존 `chunk_id`가 유지된다. 기존 문서를 수정하면 수정된 문서의 영향받은 청크만 새 ID를 얻는다. 갱신 시에는 기존 ID 유지율과 봉인 근거 좌표를 다시 감사하지만, 포트폴리오 작성 라운드에서는 코퍼스·인덱스를 읽기만 했다.

### 8-3. 로컬 데모

Gradio 데모는 `legacy_experimental`과 `product_free_rag_v1`을 같은 질문으로 비교하고, 최종 답, 서버 복원 원문 인용, 검색 후보, 전체 JSON을 보여준다. 문서 작성 중 Qwen 질문을 제출하지 않고 화면 로딩만 확인했다. FastAPI health 함수도 `runtime_loaded: False` 상태에서 정상 응답하는 것을 확인했다.

```powershell
& 'C:\Users\kimdh\AppData\Local\Python\pythoncore-3.14-64\python.exe' `
  app/product_free_rag_demo.py `
  --pipeline product_free_rag_v1 `
  --server-name 127.0.0.1 `
  --server-port 7861
```

브라우저 주소는 `http://127.0.0.1:7861/`이다. 다른 환경에서는 첫 줄의 Python 실행 파일만 해당 설치 경로로 바꾸면 된다.

![Product Free RAG v1 로컬 Gradio 데모](docs/assets/product_free_rag_demo_20260806.png)

문서 작성 직전 마지막 전체 v3 회귀 기록은 **1,269 passed / 2 failed**다. 실패 두 건은 content-addressed manifest SHA를 의도적으로 동결한 기존 면제 항목이며, 이번 문서 라운드에서는 평가·Qwen 호출·코퍼스 재빌드를 다시 실행하지 않았다. 기준과 면제 이름은 [portfolio writing plan](docs/v3/portfolio_final_writing_plan.md)에 고정돼 있다.

## 9. 한계와 다음

첫째, A6-7은 8B 모델이 조건이 다른 같은 이름의 값을 안정적으로 결속하지 못한다는 한계를 보여준다. 규칙 하나로 해당 문항을 막을 수는 있지만 코퍼스 전반의 정밀도를 증명하지 못했다.

둘째, 자동 채점과 사람 의미 판정의 차이가 크다. 자동 scorer는 빠른 회귀 탐지에는 유용하지만 최종 성능을 단독으로 대표할 수 없다. 사람 판정도 overlay·원문·이유를 함께 남겨 재감사해야 한다.

셋째, A6 32문항은 일반화를 주장하기에 작다. 같은 문항을 반복해서 튜닝하지 않고, 새로운 사람 검수 봉인 세트에서 정확도·false-full·overclaim·인용·지연을 다시 측정해야 한다.

넷째, Product Free RAG는 현재 실험 경로이며 기본 제품 경로로 승격되지 않았다. 공식 sealed 20/32와 남은 실패를 기준선으로 보존한다.

다음 라운드는 포트폴리오 이후의 코퍼스 갱신이다.

```text
2026-07-17 이후 신규 공식 문서를 반영한다.
→ 기존 chunk_id 유지율을 측정한다.
→ 검색 순위 변동을 측정한다.
→ 공개된 adaptive 질문의 답 변화만 진단한다.
```

결과가 아직 없으므로 예상 개선 수치는 쓰지 않는다. 갱신을 뒤로 미룬 이유는 지금 코퍼스를 바꾸면 갱신 전 기준선과 봉인 근거의 안정성을 먼저 증명할 수 없기 때문이다.

## 부록 A. 라운드 이력

| 라운드 | 핵심 질문 | 결정 |
|---|---|---|
| v1/v2 | 작은 SLM을 학습하면 RAG QA가 제품 수준이 되는가 | 개발셋 개선은 확인했지만 blind 게이트 실패, 미개봉 종료 |
| v3 typed | 모델 출력을 타입·관계 계약으로 강제하면 안전한가 | sealed 37/64, relation 계약 외연 부족으로 연구 경로 보존 |
| Product A0 | 정답 근거만 주면 Qwen3 8B가 복수 대상을 이해하는가 | 이해 가능, 모델 자체보다 후보 구성 문제를 먼저 진단 |
| Product A1~A4 | E번호, 압축 근거, 최소 verifier가 작동하는가 | 인용 복원과 안전 진단을 유지하며 구조 단순화 |
| Product A5 | 기존 32문항에서 회귀와 실패 유형은 무엇인가 | 공개 개발셋으로 수정 방향을 찾고 새 봉인셋을 분리 |
| Product A6 | 보지 않은 32문항에서 실제 의미 품질은 어떤가 | sealed 사람 감수 20/32, 기본 승격 NO-GO |
| A6 adaptive | ranking context·요구 예약·coverage·fan-out이 일반화되는가 | 일부 복구와 새 회귀가 함께 발생, 공식 점수 불변 |
| latency control | 332초 p95가 제품 고유 지연인가 | 측정 환경을 통제한 별도 진단으로 자원 경합 영향을 분리 |

## 부록 B. 용어

| 용어 | 뜻 |
|---|---|
| sealed | 문항과 계약을 사람 검수한 뒤 SHA로 동결하고 한 번만 실행한 공식 평가 |
| adaptive | 공개된 문항·저장 출력을 이용한 원인 진단 또는 후속 실험. 공식 점수를 대체하지 않음 |
| false-full | 근거가 일부 없는데도 모든 요구에 답했다고 노출한 결과 |
| unsupported overclaim | 문서가 지지하지 않는 구체 사실을 사용자에게 노출한 claim |
| evidence pack | 긴 청크 대신 관련 문장·표 행을 `E1`~`E8`로 압축한 모델 입력 |
| evidence_ref | 모델이 고르는 짧은 근거 번호. 서버가 실제 chunk ID와 원문 좌표로 복원 |
| parent | 하나의 공식 원문 문서. 같은 문서 청크가 후보를 독점하지 않도록 수를 제한 |
| gold | 평가자가 미리 정한 정답 값·상태·허용 근거. gold도 오류 가능하므로 overlay로 정정 이력을 보존 |
