# DNF RAG v3 ChunkV3 파일럿 계약

## 범위와 판정

이 사이클은 승격된 DocumentV3 980개 전체를 청킹하기 전, 출처·상태·본문 형식이 다른 63개 문서로 오프셋 보존형 ChunkV3 규칙을 검증한 파일럿이다.

- chunker version: `dnf_offset_chunk_pilot_v3.1`
- chunk schema: `dnf_chunk_v3.1`
- manifest schema: `dnf_chunk_pilot_manifest_v3.1`
- fixed `built_at`: `2026-07-18T00:30:00+09:00`
- 전체 980개 청킹 진입 판정: **GO**

이 사이클에서는 전체 청킹, BM25·dense index, Router, 생성, 평가, 학습을 수행하지 않았다.

## 결정론적 표본 선택

표본은 `document_id`의 SHA-256 순위를 사용하므로 입력이 같으면 선택 결과도 같다. 먼저 반드시 포함해야 하는 문서를 선택하고, 출처별 목표 수까지 `category_path`가 다양한 문서를 우선하여 채운다.

- visual evidence 보유 문서 18개 전부
- material revision이 두 개 존재하는 게임가이드 lineage 전부
- 운영정책은 시행일 순서의 oldest, 1/4, middle, 3/4, latest 5개
- 공지는 모든 `source_kind`에서 최대 2개씩
- 업데이트는 live/current 3개와 preview/unknown 3개
- 이달의 아이템과 세리아 상점은 current/expired 상태별 통제 표본

| source | documents |
|---|---:|
| `dnf_account_policy` | 5 |
| `dnf_event` | 6 |
| `dnf_faq` | 16 |
| `dnf_game_guide` | 8 |
| `dnf_monthly_item` | 4 |
| `dnf_notice` | 12 |
| `dnf_seria_shop` | 6 |
| `dnf_update` | 6 |
| **합계** | **63** |

상태 분포는 current 49, expired 6, superseded 5, unknown 3이다. preview, 과거 정책, 종료 항목이 기본 검색에 섞이지 않는지 함께 검사한다.

## 출처별 청크 설정

각 값은 `(max_chars, overlap_chars)`이다. overlap은 문장이나 줄을 임의 복제하는 고정 문자 슬라이스가 아니라, 같은 section 안의 앞선 원자 단위를 다음 청크에 다시 포함할 때 적용하는 하한이다.

| source | max chars | overlap chars |
|---|---:|---:|
| `dnf_account_policy` | 1800 | 200 |
| `dnf_event` | 1400 | 160 |
| `dnf_faq` | 1200 | 120 |
| `dnf_game_guide` | 1400 | 160 |
| `dnf_monthly_item` | 1400 | 160 |
| `dnf_notice` | 1200 | 120 |
| `dnf_seria_shop` | 1400 | 160 |
| `dnf_update` | 1400 | 160 |

## 본문, 헤딩, 표와 오프셋

DOM 본문과 visual OCR은 별도의 오프셋 공간을 사용한다.

- `offset_source=dom_text`: `DocumentContentV3.text` 기준
- `offset_source=visual_ocr`: `DocumentContentV3.visual_evidence.text` 기준
- 모든 청크에서 `source_text[start_offset:end_offset] == display_text`가 성립해야 한다.
- Markdown `#`~`######` 헤딩은 원문에 그대로 남기고, 정규화한 레이블을 `heading_path`에도 기록한다.
- 파이프 문자가 포함된 행은 표 원자 단위로 취급해 행·열 문자열을 보존한다. 표와 일반 텍스트가 함께 묶이면 `chunk_type=mixed`이다.
- 긴 일반 텍스트 한 줄은 문장/공백 경계에서 나눈다. `max_chars`보다 긴 표 행도 같은 방식으로 정확한 원문 offset span으로 나누되 각 span의 table 유형과 연속 오프셋을 보존한다.
- 여러 청크가 생긴 문서에서 80자 미만의 고립 청크는 `max_chars`를 넘지 않는 인접 청크와 결정론적으로 병합한다. 인접 청크가 이미 상한에 가까워 병합할 수 없으면 짧은 span을 인접 원문 방향으로만 확장해 bounded overlap을 만든다.

`retrieval_text`는 title, 선택적 heading breadcrumb, `display_text`를 합친 파생 필드다. `display_text`와 오프셋은 검색용 prefix의 영향을 받지 않는다.

`token_count_method=unicode_word_punct_v1`은 Unicode 단어·구두점 개수의 결정론적 추정치다. 임베딩 또는 생성 모델의 tokenizer 길이가 아니므로 이후 모델별 길이 제한은 별도로 측정해야 한다.

## 시각 근거 안전성

OCR 텍스트는 공식 페이지 이미지에서 얻었더라도 아직 사람이 검수한 authoritative text가 아니다.

- `chunk_type=visual_ocr`
- `evidence_quality=unverified_ocr`
- `review_required=true`
- `default_exposure=false`

따라서 OCR 청크 22개는 원문 보존과 검수 후보 생성에만 사용하며, 기본 현재 사실 검색에 노출하지 않는다. DOM 청크는 부모 DocumentV3의 `status`와 `default_exposure`를 그대로 상속한다.

## 파일럿 결과

| metric | result |
|---|---:|
| selected documents | 63 |
| DOM chunks | 445 |
| visual OCR chunks | 22 |
| total chunks | 467 |
| table or mixed DOM chunks | 182 |
| heading path DOM chunks | 427 |
| default exposure chunks | 272 |

모든 출처와 네 상태를 포함했고, visual evidence 문서 18개도 전부 표본에 포함됐다. 다음 오류 수는 모두 0이다.

- DOM 청크가 없는 선택 문서
- 오프셋 불일치
- 중복 `chunk_id`
- 빈 display/retrieval text
- 최대 길이를 넘은 atomic 청크
- 다중 청크 문서의 80자 미만 고립 청크
- 상태·source kind 기준 기본 노출 정책 위반
- OCR 청크의 기본 노출 또는 검토 정책 위반

최초 파일럿 실행은 헤딩을 항상 독립 section으로 분리해 80자 미만 고립 청크 153개가 생겼고 **NO-GO**였다. 이 실행 기록은 기존 content-addressed report로 남겨 두었다. 최종 규칙은 짧은 section을 길이 상한 안에서 인접 span과 병합하며, 같은 입력에서 재실행한 결과 고립 청크가 0이 되어 **GO**로 승격됐다.

## Canonical artifacts

- selection: `data/v3/chunks/chunk_pilot_selection_af717de4e375b7c6f74a4a6da41640280c1ea2c4c5550278c1811c2954553b2b.jsonl`
- chunks: `data/v3/chunks/chunks_pilot_f97e62d54d2fa4419f8a33ef3543f93916b14c27b978cd1ff6b38b2fff7b0dbe.jsonl`
- manifest: `data/v3/chunks/chunk_pilot_manifest_ba5e1d5a9b8a237df9a99e5fb698bbb8e0a4b6dc1668b3cabece9e971e0154e6.json`
- report: `reports/v3/chunk_pilot_d35f24f989135a1bad7c6a5c1f3f9eaccbcc5bd018268c2bbc8db731395a189d.json` 및 `.md`

각 JSON/JSONL 파일명의 64자리 suffix는 해당 파일 bytes의 SHA-256이다. Markdown report는 같은 report hash를 이름에 사용한다. 고정 입력과 `built_at`으로 재실행하면 위 경로와 해시를 재사용해야 한다.

## 다음 단계

다음 사이클은 이 규칙으로 DocumentV3 980개 전체를 결정론적으로 청킹하고, 문서별 coverage, offset/hash, 길이 분포, 고립 청크, 노출 정책, OCR 검토 격리를 corpus-wide로 다시 감사하는 단계다. 전체 감사가 통과하기 전에는 BM25나 dense index를 만들지 않는다.
