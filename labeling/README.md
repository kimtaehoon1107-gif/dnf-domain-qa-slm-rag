# Label Studio Workflow

이 폴더는 intent, answerability, evidence quality를 Label Studio에서 라벨링하기 위한 설정과 export 포맷을 담는다.

## 1. Import config

Label Studio 프로젝트 생성 후 `labeling/label_studio_config.xml` 내용을 Labeling Interface에 붙여넣는다.

라벨링 대상:

- `intent`: 질문 의도
- `answerability`: 수집 문서만으로 답할 수 있는지
- `evidence_quality`: 후보 근거가 답변을 얼마나 직접 지원하는지
- `evidence_doc_ids`: 답변을 지지하는 문서 ID
- `corrected_answer`: 문서 근거 기반 정답
- `review_notes`: 누락/오류/애매함 메모

## 2. Create import tasks

```powershell
python src/label_studio_io.py export-tasks `
  --input data/processed/qa_dataset.jsonl `
  --docs data/raw/docs.jsonl `
  --output outputs/label_studio_tasks.json `
  --include-prelabels
```

공식 문서 평가셋을 라벨링하려면 다음처럼 실행한다.

```powershell
python src/label_studio_io.py export-tasks `
  --input data/processed/official_eval_set.jsonl `
  --docs data/raw/official_docs.jsonl `
  --output outputs/official_label_studio_tasks.json `
  --include-prelabels
```

## 3. Export normalized JSONL

Label Studio에서 JSON으로 export한 뒤 normalized JSONL로 변환한다.

```powershell
python src/label_studio_io.py convert-export `
  --input exports/label_studio_export.json `
  --output data/processed/labeled_qa_from_label_studio.jsonl
```

출력 row는 `labeling/export_schema.json` 형식을 따른다.

## 4. Review rules

- `answerability=false`이면 `evidence_doc_ids`는 비우거나, "관련은 있으나 답변 불가"인 근거만 notes에 설명한다.
- `evidence_quality=good`은 문서 하나만으로도 답변 가능한 경우에만 사용한다.
- 날짜, 이벤트 기간, 아이템명, 수치는 원문에 있는 표현을 우선한다.
- 개인 계정 상태, 실시간 장애, 현재 시세처럼 수집 문서 밖 확인이 필요한 질문은 `answerability=false`로 둔다.
