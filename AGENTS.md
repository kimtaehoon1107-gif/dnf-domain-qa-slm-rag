# AGENTS.md — DNF Domain QA SLM/RAG v2

던파 공식 문서 기반 **평가 주도형(evaluation-driven) QA/RAG** 파이프라인.
데이터 구축 → 검색(dense+lexical) → answerability → 근거 기반 생성 → RAFT/LoRA SLM → 평가.
정체성: 좋은 숫자가 아니라 **정직한 측정과 실패 분석**.

> **이 파일 업데이트 원칙**: 여기는 "코드만 봐서는 알 수 없는, 반복되면 안 되는 교훈"만 적는다. 어댑터 이름·수치·이번 주 진행상황처럼 매번 바뀌는 건 여기 넣지 말고 [docs/project_progress_report.md](docs/project_progress_report.md)에만 기록할 것. 새로운 durable 교훈이 생겼을 때만 아래 목록에 한두 줄 추가.
>
> **지금 진행 중인 작업**은 [docs/agent_handoff.md](docs/agent_handoff.md)를 확인 — Current Goal/State/Do Not Do/Next Actions가 매 사이클 최신으로 덮어써져 있음.

## ⚠️ 가장 중요한 함정들

1. **임베딩 모델은 BGE-M3가 canonical, MiniLM은 폐기.** `retrieval_config.DEFAULT_EMBEDDING_MODEL = BGE_M3_MODEL`. MiniLM은 128토큰 제한으로 청크 97~99%가 잘리는 버그가 있어 전 인덱스에서 교체됨. 새 인덱스/스크립트에서 MiniLM을 기본값으로 쓰지 말 것.
2. **rank_mode 기본값은 `hybrid`.** `lexical_first`/`semantic`/`hybrid`/`rrf` 중 hybrid가 이 데이터에서 가장 안정적으로 측정됨(`rrf`는 실측상 더 나빠서 비채택). `retrieval_config.RANK_MODES` 참조.
3. **torch/sentence_transformers는 반드시 chromadb보다 먼저 import.** Windows에서 CUDA torch + chromadb를 함께 쓰면 네이티브 DLL 로딩 순서 충돌로 세그폴트 발생. `retrieve.py`/`build_index.py` 상단의 import 순서를 절대 바꾸지 말 것.
4. **`answerability_accuracy` 단독으로 성능 판단 금지.** true/false/partial 라벨만 맞는지 보는 지표라, `exact_citation`/`retrieval_expected_hit_rate` 없이 보면 과대평가됨(실측: domain answerability_accuracy=1.0인데 exact_citation=0.2556). 세 지표를 항상 같이 리포트.
5. **Oracle eval(`run_tuned_slm_oracle_eval.py`)은 `evidence_span`(정답 문장만 오려낸 짧은 텍스트)을 넣어줌, 청크 전체가 아님.** oracle=1.0은 "SLM이 완벽하다"가 아니라 "노이즈 없는 정답 문장이 주어지면 형식을 잘 지킨다"는 뜻. `chunk_oracle`과 `span_oracle`을 구분해서 해석할 것.
6. **RAFT 학습 데이터에서 gold 문서 위치가 항상 1번이면 모델이 "1등만 베끼는" 습관을 학습함.** 실측: `domain_raft_sample_expanded_gate_balanced.jsonl`의 citations 보유 279행 전부 gold가 documents[0]. 새 RAFT를 만들 때는 gold 위치를 반드시 랜덤화하고 gold 앞에도 distractor를 배치할 것.
7. **`fresh_paraphrase_eval_set.jsonl`은 adaptive dev이며 학습에는 계속 금지.** 개별 실패가 반복적으로 모델/데이터 변경을 이끌었으므로 최종 blind 성능으로 부르지 말 것. `data/review/blind_test_v1_candidate.jsonl`은 사람 검수·freeze 전에는 검색/생성 평가도 금지하며 모든 학습 컨텍스트에서 제외할 것.
8. **Hard negative는 answer-aware 필터가 필수.** gold/same-parent 제외만으로는 부족하다. 다른 부모 문서가 같은 사실을 반복해 valid evidence가 distractor로 들어갈 수 있으므로 exact `evidence_span` 및 높은 evidence-token overlap을 제거해야 한다. 미필터 arm은 실측상 거절은 좋아졌지만 exact citation을 크게 망쳤다.

## Repo Map (src/)

- **io_utils.py** 공용 read/write_jsonl · **prompt_format.py** 학습/추론 공용 프롬프트(citations가 answer보다 먼저 오는 순서, 중복 금지·반드시 재사용)
- 수집: **collect_official_docs.py**(게시판, requests+bs4) · **collect_guide_selenium.py**(가이드, Selenium, `##`/`###` 헤딩 보존)
- 청킹: **prepare_chunks.py**(공식문서, 고정 1200자 + `--clean-board-header`) · **chunk_guide.py**(가이드, 섹션기반 재귀+오버랩) · **chunk_official_sections.py**(섹션 기반 ablation용, 비승격 — 평평한 게시판 글엔 고정길이가 더 나음) — 섞지 말 것
- 검색/생성: **build_index.py**(`--model-name`, 기본 BGE-M3) · **retrieve.py**(`--rank-mode`, 기본 hybrid) · **generate_answer.py**(rule-based answerability gate)
- 평가(레거시/공식): **make_official_eval_set.py** · **evaluate.py**(hit_rate@k) · **evaluate_answers.py**(RAGAS/FActScore-style) · **remap_eval_chunks.py**(청킹 변경 시 eval의 expected_chunk_ids 재매핑)
- **도메인 데이터/리키지 방지**: **make_domain_expanded_data.py**(false 템플릿 train/eval 분리, `--legacy-eval-set` parent 제외, `blocked_questions`) · **validate_domain_dataset.py**(train/eval parent·chunk·question 3종 교차 누수 검증, 필수로 통과시킬 것)
- SLM 학습: **make_raft_dataset.py**(`--exclude-eval-set` nargs=+) · **finetune_lora.py**(completion-only 마스킹, LoRA q/k/v/o/gate/up/down_proj) · **run_tuned_slm_smoke.py**(answerability/citation 파싱 및 집계)
- SLM 진단: **run_tuned_slm_oracle_eval.py**(gold-only 컨텍스트로 상한선 측정) · **analyze_tuned_slm_diagnostics.py**(rank별 인용 성공률, 과잉거절 사례 등 실패 패턴 집계)
- 기타: **train_label_classifiers.py** · **label_studio_io.py** · **make_review_samples.py** · **run_smoke_tests.py**

## 현재 데이터/모델 상태

바뀌는 정보(최신 어댑터/RAFT 파일명/수치)는 여기 두지 않음 — 볼 때마다 낡아서 오히려 위험함.
**최신 상태는 항상 [docs/project_progress_report.md](docs/project_progress_report.md)의 "4. 현재 상태 스냅샷" 절을 확인.** `ls outputs/`, `ls data/processed/`로 실물도 같이 확인할 것.

## Commands (PowerShell, cwd = repo root)

```powershell
pip install -r requirements.txt            # 런타임 (+ requirements-train.txt 학습, + selenium 가이드크롤)

# 도메인 인덱스 조회/재생성 (BGE-M3, hybrid가 기본이라 옵션 생략 가능)
python src/retrieve.py "최후의 과업 입장 조건" --persist-dir outputs/chroma_domain_chunks
python src/build_index.py --docs data/processed/domain_doc_chunks.jsonl --persist-dir outputs/chroma_domain_chunks --reset

# 검증 · 회귀 · 데모
python src/validate_domain_dataset.py   # 리키지 검증, 배포 전 필수
python src/run_smoke_tests.py
python app/gradio_app.py

# SLM 평가 3종 + 진단 (<adapter-dir>은 outputs/ 안의 실제 최신 어댑터 경로로 치환)
python src/run_tuned_slm_smoke.py --adapter-dir <adapter-dir> --eval-set data/processed/domain_eval_set_expanded.jsonl --persist-dir outputs/chroma_domain_chunks --output outputs/_domain.json
python src/run_tuned_slm_oracle_eval.py --adapter-dir <adapter-dir> --eval-set data/processed/domain_eval_set_expanded.jsonl --chunks data/processed/domain_doc_chunks.jsonl --output outputs/_domain_oracle.json
python src/analyze_tuned_slm_diagnostics.py --report domain=outputs/_domain.json
```

## 규칙

- `python src/xxx.py`로 실행(스크립트가 src 상대 import). 새 IO/프롬프트는 io_utils/prompt_format 재사용.
- build_index가 임베딩 시 `title`을 prepend → chunk_guide 청크엔 title 없이 섹션헤더만 넣음(중복 방지).
- eval 질문은 **제목 파생 금지**(본문 fact 기반, title_overlap_cap=0.35), 채점은 **청크 단위**(expected_chunk_ids) 우선.
- 새 학습/평가 데이터를 만들면 **`validate_domain_dataset.py`를 반드시 통과**시킬 것(parent/chunk/question 3종 누수 0 확인).
- 지표명은 recall이 아니라 **hit_rate@k**(retrieval), `exact_citation`(인용 정확도)은 `parsed_citation_hit`가 집합 교집합(any-hit)이라 다소 관대한 지표임을 감안.
- 라이브러리 함수는 `SystemExit` 대신 `RuntimeError`.

## Known limitations / next

- **검색 recall 문제**: domain eval에서 gold 근거가 top-3 후보에 없는 경우가 58/90(64%). candidate_k 확장/hybrid 튜닝 우선 필요, reranker는 그 다음.
- **부분답변 품질 취약**: current adaptive fresh dev가 6행뿐이고 partial joint success가 낮다. 신규 blind 후보 검수와 partial 질문 확장이 다음 데이터 게이트다.
- **Hard-negative 후속은 보류**: answer-filtered artifact까지는 생성·검증됐지만 사람 검토 전 즉시 재학습하지 않는다. 기존 미필터 arm은 비승격.
- intent router(`shop_price/active_event/patch_note/notice/unanswerable/ood_safety`) 미구현, shop_price 구조화 데이터 소스 미해결.
- ablation용 인덱스/데이터 파일 다수 미정리(위 표 참조).

> 상세 진행 기록: [docs/guide_rag_stage1.md](docs/guide_rag_stage1.md)(Stage 1 크롤링/청킹) · [docs/tuned_slm_failure_diagnosis.md](docs/tuned_slm_failure_diagnosis.md)(SLM 실패 진단) · [docs/project_progress_report.md](docs/project_progress_report.md)(전체 진행 보고서, 초보자용)
