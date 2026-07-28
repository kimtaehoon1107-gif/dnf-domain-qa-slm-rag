# DNF Simple RAG RC1 데모

## 실행 구성

```text
Simple RAG v2 @ f34eec0
→ BM25 + BGE-M3 hybrid top 20
→ BGE-reranker-v2-m3 top 5
→ source route일 때 전역 fallback 최대 1개
→ qwen3-8b:ctx8192
→ exact citation 및 숫자·날짜·단위 검사
→ A1~A3 최소 안전장치
```

데모 시작 시 다음을 확인한다.

- `src/v3/simple_domain_rag.py`가 봉인된 v2 SHA와 일치
- Ollama 모델 태그가 `qwen3-8b:ctx8192`
- 모델 blob SHA가 봉인 manifest와 일치
- Modelfile에 `num_ctx 8192`가 명시

## 사전 조건

```powershell
ollama list
```

목록에 `qwen3-8b:ctx8192`가 있어야 한다. Ollama 서버가 실행 중이어야 한다.

## Gradio 실행

저장소 루트에서:

```powershell
python app/simple_rag_rc1_demo.py
```

브라우저:

```text
http://127.0.0.1:7860
```

포트를 변경하려면:

```powershell
python app/simple_rag_rc1_demo.py --server-port 7861
```

## CLI 실행

```powershell
python src/v3/simple_rag_rc1.py "질문을 입력하세요"
```

## 화면 출력

- full / partial / abstain
- 노출 답변
- 정확한 원문 인용 좌표
- 문서 제목·출처·게시일
- 검색 후보와 reranker 점수
- A1~A3 차단 이유
- 생성 및 전체 처리시간

## 비승격 기능

다음 기능은 RC1에서 사용하지 않는다.

```text
Typed evidence-ref
Claim Contract v8
B1+B3+B4 인용 복구
relation-semantic selector
subject-anchored 추가 검색
semantic fallback
```

이 데모는 포트폴리오·연구용이며 제품 기본 배포 모델이 아니다.
