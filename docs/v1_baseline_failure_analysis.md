# v1 Baseline Failure Analysis

이 문서는 기존 `dnf-llm-eval`을 DNF Domain QA SLM/RAG v2의 v1 baseline으로 선언하고, 실제 repo/결과 파일에서 확인한 실패 유형을 v2 설계 요구사항으로 변환한다.

## 1. 분석 범위

### 확인한 repo

- GitHub repo: `https://github.com/kimtaehoon1107-gif/dnf-llm-eval`
- 확인 commit: `ae97ef95936995cbe4d5f684bb09d49b4847832d`
- 로컬 제출 패키지: `C:\Users\kimdh\OneDrive\문서\dnf-llm-eval`
- HEAD 확인용 clone: `C:\Users\kimdh\AppData\Local\Temp\dnf-llm-eval-head`

### 근거 파일

- `README.md`
- `report/final_portfolio_report.md`
- `report/final_closing_review.md`
- `report/heldout_factual_ablation_v1.md`
- `report/structured_record_probe_v1.md`
- `report/deepeval_faithfulness_independent_recheck_v1.md`
- `eval/retrieval_compare_summary.csv`
- `eval/answer_compare_summary.csv`
- `eval/ablation_answer_compare_summary.csv`
- `eval/v2026_06_answer_compare_summary.csv`
- `eval/v2026_06_retrieval_compare_summary.csv`
- `eval/v2026_06_structured_fix_answer_compare_summary.csv`
- `eval/safety_heldout_combined_summary.csv`

## 2. v1 Baseline 요약

v1은 던파 공식 업데이트 문서를 수집하고, 로컬 LLM 답변 품질을 Non-RAG, RAG, BM25 heuristic, BGE-M3, structured data, safety gate 관점에서 평가한 offline benchmark다.

핵심 구성:

- 문서 수집: 던파 공식 업데이트 문서 Markdown화
- 질문셋: 문서 기반 질문, OOD 질문, adversarial 질문
- 검색: BM25 heuristic, BGE-M3
- 생성: `qwen3:4b`, `qwen3:4b-instruct-2507-q4_K_M`
- 평가: retrieval hit, factual proxy, format proxy, 수동 rubric, safety held-out

## 3. 주요 정량 결과

### Baseline vs RAG

| 방식 | 전체 평균 | 문서 기반 질문 평균 | OOD 질문 평균 |
|---|---:|---:|---:|
| Non-RAG baseline | 13.87 / 21 | 11.27 / 21 | 21.00 / 21 |
| RAG 적용 | 19.43 / 21 | 18.86 / 21 | 21.00 / 21 |

해석: RAG는 문서 기반 질문에서 큰 개선을 만들었다. v2는 여기서 더 나아가 "근거가 있을 때 답한다"뿐 아니라 "근거가 부족하면 답변 불가로 판단한다"를 명시적인 데이터/평가 축으로 둔다.

### Retriever 비교

| Retriever | Top-8 evidence hit | Top-1 evidence hit | Avg token recall |
|---|---:|---:|---:|
| BM25 heuristic | 22 / 22 | 19 / 22 | 0.994 |
| BGE-M3 | 22 / 22 | 21 / 22 | 1.000 |

해석: 검색 실패 자체보다 top-1 ranking, 표형 정보 보존, 생성 단계의 충실성이 남은 병목이었다.

### 생성 모델/형식 비교

| 설정 | Factual proxy | Format proxy | Meta reasoning | Avg latency |
|---|---:|---:|---:|---:|
| BGE-M3 + `qwen3:4b` | 17 / 22 | 9 / 22 | 13 | 11.635s |
| BGE-M3 + `qwen3:4b-instruct-2507` | 18 / 22 | 22 / 22 | 0 | 4.625s |

해석: 검색 근거가 있어도 생성 모델이 영어 추론 과정이나 메타 발화를 노출하면 서비스 답변으로 부적합하다. v2의 SLM 학습 데이터는 답변 형식, 근거 인용, 답변 불가 형식을 함께 학습 대상으로 둔다.

### Structured data 실험

| 실험 | 결과 |
|---|---:|
| 상점표 관련 Q001-Q004, structured 전 | 3 / 4 factual proxy |
| 상점표 관련 Q001-Q004, structured 후 | 4 / 4 factual proxy |
| 2026-06 dev structured fix 전 | 16 / 20 factual proxy |
| 2026-06 dev structured fix 후 | 20 / 20 factual proxy |
| blind held-out factual v1 | 모든 ablation 조건 23 / 25 |
| blind held-out structured record firing | 0 / 25 |
| structured record diagnostic probe | 24 / 35 -> 32 / 35 |

해석: structured record는 발동하면 도움이 되지만, 손으로 만든 record가 blind held-out 질문에 자동으로 전이되지는 않았다. v2는 Label Studio 라벨과 RAFT-style 데이터에서 evidence document와 distractor document를 명확히 분리해, record coverage/근거 품질을 추적해야 한다.

### Safety held-out

| Classifier | Scope | Attack recall | Benign FP |
|---|---|---:|---:|
| keyword gate | v6 fresh | 1 / 24 | 0 / 24 |
| intent_rules_v5 | v6 fresh | 12 / 24 | 0 / 24 |
| intent_rules_v5 | backward compatible non-circular | 90 / 120 | 1 / 120 |

해석: 규칙 기반 safety gate는 직접 키워드에는 빠르지만, stealth/paraphrase 공격에는 약하다. v2는 answerability와 intent를 라벨링하고, 정상 질문 과차단과 위험 질문 미차단을 별도 평가한다.

## 4. 실패 유형

### F1. 생성 형식 실패

증상:

- `qwen3:4b`가 근거를 받아도 영어 reasoning, "Wait", "Let's tackle" 같은 메타 발화를 출력했다.
- Format proxy가 9/22에 그쳤고 meta reasoning이 13건 발생했다.

v2 대응:

- RAFT-style answer에 짧은 한국어 서비스 답변 형식을 고정한다.
- 답변 평가에 `format_proxy`, `json_validity`, `citation_accuracy`를 포함한다.
- LoRA/QLoRA scaffold는 동일 형식을 학습할 수 있도록 prompt/completion 포맷을 만든다.

### F2. 표형 정보/인접 행 혼입

증상:

- Q002에서 `태초 광휘의 의지` 가격은 맞혔지만, 인접 상품인 `태초 소울 1개 상자`의 월 4회/이월 조건이 섞였다.
- 일반 chunk 검색은 표의 행 단위 관계를 안정적으로 보존하지 못했다.

v2 대응:

- evidence quality 라벨에 `good`, `partial`, `poor`를 둔다.
- 구조화 근거가 필요한 질문을 failure category로 남긴다.
- FActScore-style atomic fact support rate로 수치/조건 단위 누락과 혼입을 잡는다.

### F3. 세부 조건 누락

증상:

- held-out `HF023`, `HF024`에서 경로 추가나 게이트 개수 같은 일부 변경점은 답했지만, 중간보스 생략 가능 조건 또는 1개 게이트 추가 조건을 빠뜨렸다.
- dev `Q012`에서도 핵심 수치 변경은 답했지만 유지 조건을 생략했다.

v2 대응:

- Label Studio 라벨에 answerability뿐 아니라 evidence quality와 reviewer notes를 남긴다.
- 평가셋의 `failure_focus`에 `item_name_or_numeric_value_error`, `unsupported_hallucination`, `date_or_period_error`를 유지한다.
- answer evaluator는 expected answer overlap과 atomic fact support를 별도 기록한다.

### F4. Test-informed structured record 한계

증상:

- dev에서는 structured fix가 20/20까지 개선됐지만, blind held-out에서는 structured record firing이 0/25였다.
- diagnostic probe에서는 record가 발동할 때 24/35에서 32/35로 개선됐으나, 이는 일반화 증거가 아니라 메커니즘 확인이다.

v2 대응:

- `official_raft_sample.jsonl`처럼 gold evidence와 distractor evidence를 분리한다.
- 추후 자동 record extractor 또는 라벨링 기반 record generation으로 확장할 수 있게 schema를 유지한다.
- 비교 리포트에서 dev/test-informed와 held-out 결과를 분리해 적는다.

### F5. 자동 평가 proxy와 judge 불일치

증상:

- Q016은 사람이 보면 정답에 가까웠지만 factual proxy에서 실패로 처리됐다.
- DeepEval faithfulness fail 6건 재검증에서 5건은 judge 오류 또는 reason-score 불일치였고, Q003은 경계 사례로 남았다.

v2 대응:

- RAGAS-style/FActScore-style 평가는 최종 판정자가 아니라 triage 지표로 둔다.
- script output에 detail row를 남겨 사람이 재검토할 수 있게 한다.
- 숫자 하나가 아니라 answerability, citation, relevance, faithfulness, atomic support를 분리한다.

### F6. Safety 일반화 한계

증상:

- keyword gate는 v6 fresh attack recall이 1/24였다.
- intent gate는 12/24로 개선됐지만 아직 절반 수준이다.
- regression/dev 결과와 fresh held-out 결과가 크게 다르다.

v2 대응:

- intent 라벨과 answerability 라벨을 분리한다.
- `answerability=false`에서 evidence 없는 강제 답변을 실패로 평가한다.
- 추후 semantic classifier와 output safety check를 붙일 수 있게 데이터 포맷을 확장한다.

### F7. 변수 통제/비교 가능성 문제

증상:

- 초기 실험 일부는 `--restrict-to-question-doc`로 검색과 생성 능력을 분리했다.
- 이는 진단에는 유용하지만 실제 서비스 조건과 다르다.

v2 대응:

- 비교 리포트에서 RAG-only, LLM-RAG, tuned-SLM의 입력, 모델, 검색기, 평가셋을 명시한다.
- 실행하지 않은 tuned-SLM 결과는 수치로 주장하지 않고 scaffold와 acceptance gate로 구분한다.

## 5. v2 요구사항으로 변환

| v1 관찰 | v2 산출물 |
|---|---|
| RAG가 baseline보다 강하지만 답변 불가 판단은 약함 | answerability 라벨, unanswerable eval, Gradio refusal |
| 표형 정보와 세부 조건이 섞이거나 누락됨 | evidence quality 라벨, RAFT gold/distractor, atomic fact 평가 |
| 생성 모델 형식 제어가 중요함 | LoRA/QLoRA scaffold, service-answer prompt format |
| 자동 proxy는 오판 가능 | RAGAS/FActScore-style detail report와 수동 review hook |
| safety regression과 held-out 차이 큼 | intent/answerability 분리, false positive/false negative 추적 |

## 6. v2 성공 기준

1. 데이터셋: 문서, QA, 평가셋, RAFT-style 학습 샘플이 같은 evidence ID 체계를 공유한다.
2. 라벨링: Label Studio에서 intent, answerability, evidence quality를 일관되게 export할 수 있다.
3. RAG MVP: 공식 문서 chunk 검색이 expected evidence를 회수하고, 근거 부족 질문을 거절한다.
4. 평가: retrieval 지표와 answer 지표를 분리하고, atomic fact support까지 기록한다.
5. SLM 확장: LoRA/QLoRA 학습을 바로 실행할 수 있는 scaffold와 dry-run 검증을 제공한다.
6. 비교: RAG-only, LLM-RAG, tuned-SLM의 현재 상태와 남은 실험을 수치/상태로 구분해 보고한다.
