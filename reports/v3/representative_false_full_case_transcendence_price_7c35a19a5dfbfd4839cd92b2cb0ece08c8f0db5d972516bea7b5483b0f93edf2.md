# 대표 실패 케이스: “초월 가격 알려줘”

> **개발 데모 · runtime/canonical 미승격.** 이 사례는 “원문을 정확히 복사했다”와 “질문에 실제로 답했다”가 다르다는 점을 보여준다. 질문과 화면 출력은 프로즌 평가셋 문항이 아닌 개발 데모 재현 사례이며, 아래 인용문·청크·offset·선택 설정은 프로즌 dirty canonical과 assembler manifest에서 대조했다.

## 한눈에 본 결과

| 항목 | 실제 데모 결과 |
|---|---|
| 질문 | `초월 가격 알려줘` |
| 라우팅 | `retrieve` |
| 응답 | `full_answer` |
| 요구 상태 | `supported` |
| planner 요구 | `초월 — price` |
| 판정 | **false-full** — 세 인용 모두 원문의 정확한 substring이지만, 초월 비용의 값을 답하지 않았다. |

파이프라인은 세 인용의 원문 일치를 모두 확인했기 때문에 “지원됨”으로 처리했다. 그러나 실제 출력은 다음과 같았다.

1. `chunk_sha256_04115b844659e731254dced013c78943e463f72e2baf4c4589cc1df2df1ea421`
   
   > 서약 결정 초월 비용은 아래와 같습니다.

   `display_text[1289:1311]`, 부모문서 `[4591:4613]`, 출처: [서약 / 결정](https://df.nexon.com/guide?no=1532)

2. `chunk_sha256_72b83b77fa143997b8639babb8522b1f5133f91da23811116f65814c8685d969`
   
   > 서약 결정 초월 비용은 아래와 같습니다.

   `display_text[72:94]`, 부모문서 `[4591:4613]`, 출처: [서약 / 결정](https://df.nexon.com/guide?no=1532)

   첫 인용과 **같은 부모문서의 같은 문자 구간**이다. 160자 overlap으로 만들어진 인접 청크가 같은 머리말을 중복 보유한다.

3. `chunk_sha256_8d2e89dd99cbbd2e9e51c10f87881677b71d7174dfe05da3524969d2e1a6af82`
   
   > | 태초 소울 | &lt;주요 사용처&gt; - 종말의 계시 구매 - 장비 변환 - 흑아 장비로 변환 - 115Lv 이상 태초 장비 초월 &lt;주요 사용 NPC&gt; - 신비한 힘의 마법서 - 다정한 죽음 세니르 &lt;주요 획득처&gt; - 115Lv 이상 태초 장비 무기고 등록/해체 | 에픽 소울 20개 | 계정귀속 |

   `display_text[453:618]`, 부모문서 `[4350:4515]`, 출처: [[115] 종말의 숭배자](https://df.nexon.com/guide?no=1486)

   이 행은 태초 소울의 사용처·상점 교환 재료를 설명할 뿐, 질문이 요구한 장비/서약 결정의 **초월 비용표가 아니다**.

## 정답은 이미 검색된 청크 안에 있었다

정답 원천은 `chunk_sha256_44dc7778608597cb03b82b94de29f4cd76f5f93a5e744306b0f24835fa9bede7`, heading `NPC 장비 초월 > 비용`, 출처 [초월](https://df.nexon.com/guide?no=1227)이다. 이 청크의 `display_text`에는 다음 값들이 원문 그대로 들어 있다.

```text
115Lv 장비 초월 비용은 아래와 같습니다.
[TABLE]
| 장비 종류 | 구분 | 레어리티별 소울 | 상급 원소 결정 | 순례의 인장 | 보이드 소울 |
| 무기 | 레어 | 75 | 9 | 20 | - |
| 유니크 | 60 | 36 | 38 | 2 |
```

위 발췌는 `display_text[7:152]`이며, 뒤에 무기·방어구/악세서리·특수장비의 레어리티별 행이 계속된다.

```text
서약 결정 초월 비용은 아래와 같습니다.
- 미광의 서약 결정(레어), 고유 서약 결정은 초월이 불가능합니다.
[TABLE]
| 구분 | 광휘의 소울 | 상급 원소 결정 | 순례의 인장 / 골드 | 솔리드 소울 |
| 유니크 | 25개 | 36개 | 순례의 인장 25개 or 125,000골드 | 1개 |
| 레전더리 | 60개 | 180개 | 순례의 인장 250개 or 1,250,000골드 | 65개 |
| 에픽 | 200개 | 810개 | 순례의 인장 750개 or 3,750,000골드 | 150개 |
| 태초 | 500개 | 810개 | 순례의 인장 3,000개 or 15,000,000골드 | 500개 |
[/TABLE]
```

위 발췌는 `display_text[639:992]`이다. 즉 검색이 정답 청크를 놓친 문제가 아니라, **정답 청크 안에서 값 행 대신 머리말을 선택한 문제**다.

질문 자체는 “115Lv 장비 초월”과 “서약 결정 초월” 중 무엇을 뜻하는지 모호하다. 안전한 extractive 응답은 두 비용표를 구분해 함께 인용하거나 대상을 되물어야 한다. 어느 해석에서도 값 없는 머리말 세 개만으로 `full_answer`를 선언할 수는 없다.

## 어디서, 왜 실패했나

`검색 성공 → 문장·표행 segment 분할 → 요구별 segment rerank → exact slice 인용` 중 실패 단계는 **segment 선택**이다.

- 요구 질의 `초월 + price`와 “초월 비용은 아래와 같습니다”라는 머리말은 의미·표면 단어가 직접 겹친다.
- 반면 값 행 `| 유니크 | 25개 | 36개 | … |`에는 상위 표의 주어인 “서약 결정 초월”과 속성인 “비용”이 상속되지 않는다.
- 프로즌 설정 `threshold=0.001`, `K=3`, `distinct_chunks`는 청크당 최대 한 segment만 뽑는다. 한 청크에서 머리말이 먼저 뽑히면 같은 청크의 값 행은 후보에서 제외된다.
- overlap 청크 두 개가 동일 부모 offset의 머리말을 각각 제공해, 서로 다른 청크라는 이유만으로 중복 인용이 허용됐다.
- exact-substring 검사는 세 인용 모두 통과했다. 이 검사는 **복사 정확성**만 보장하며, span이 요구 속성의 값을 실제로 답하는지는 보장하지 않는다.

따라서 근본원인은 모델이 답을 자유 생성해서가 아니라, 표를 평탄화하면서 **행의 주어–속성–값 귀속이 사라진 데이터 표현**과 부모 offset을 보지 않는 chunk-diverse 선택의 결합이다.

## v3.2 수정 방향

1. 원문 `display_text`는 보존하고, 검색·선택용 표 행에 caption/header를 상속한 구조화 view를 만든다. 예: `서약 결정 초월 · 유니크 · 광휘의 소울 = 25개 · 상급 원소 결정 = 36개 · 순례의 인장 = 25개 또는 125,000골드 · 솔리드 소울 = 1개`.
2. 선택은 `chunk_id`가 아니라 `(parent_document_id, parent start/end)`도 함께 보아 겹침 청크의 동일 span을 중복 제거한다.
3. `value_type=amount` 요구에는 값이 없는 머리말만으로 `supported`가 되지 않도록, 구조화 행의 값 존재를 기계적으로 확인한다.
4. 최종 인용은 구조화 view가 아니라 보존된 원문 row의 offset으로 되돌려 exact-slice 100%를 유지한다.
5. 승격 게이트는 이 사례에서 최소 한 개의 실제 비용 행 인용, 중복 부모 span 0, 새 false-full 0으로 둔다.

## 재현 계보와 스크린샷 슬롯

- dirty canonical: `data/v3/chunks/chunks_dnf_official_v3.1_bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885.jsonl`
- dirty canonical SHA-256: `bd0242b3f19646c22eafd2e61bf2544e670718a1c9927de288decb5657e92885`
- normalized documents SHA-256: `d4d8ae1030e9d769c05b5914a908c75a233c9bc8e0af2a3cc45149d680271c9d`
- assembler manifest: `data/v3/evidence/extractive_assembler_v3_chunk_diverse_manifest_9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8.json`
- assembler manifest SHA-256: `9db367b14a981bd05ba37d6029fc79a9e0e8606efc06221dd6eee117a38bc2b8`
- 선택 설정: `mechanical-chunk-diverse-assembler-v3.5`, `BAAI/bge-reranker-v2-m3`, `threshold_0.001_k_3_distinct_chunks`
- 데모 버전: `dnf-v3-backbone-gradio-demo-v1.0`
- 데모 코드 SHA-256: `ee0ebe02677e73f33cf78e06792ff0b5b7fe741fa1480b43ca6f7fdb441436ad`
- 기록 성격: 개발 데모 재현 문서, 새 benchmark 측정 아님, runtime/canonical 승격 없음

> **데모 스크린샷 슬롯**  
> 여기에 상단의 “개발 데모 · 9/82 false-full · 미승격” 배너, 질문 `초월 가격 알려줘`, 라우팅/응답 상태, 요구별 판정, 세 원문 인용이 한 화면에 보이도록 캡처를 삽입한다. 캡처 절차: `python src/v3/gradio_backbone_demo.py --port 7862` → 브라우저에서 질문 입력 → `정확 인용으로 확인` → 기술 정보는 접고 인용 3개까지 포함해 캡처. 이 문서 작성 단계에서는 새 실행이나 스크린샷 생성을 하지 않았다.
