# Guide RAG — Stage 1 (게임가이드 코퍼스 + BGE-M3)

DNF 공식 **게임가이드**를 RAG 코퍼스로 편입한 작업 기록. (AGENTS.md의 상세 버전 — 필요할 때만 참조)

## 배경 / 문제

- 기존 코퍼스는 notice/update/event 게시판(시점성)뿐. evergreen 게임 지식이 없었음.
- 게임가이드(`df.nexon.com/guide`)는 풍부하지만 **JS 렌더링**(jQuery.tmpl)이라 requests+bs4로는 메뉴 껍데기만 수집됨 → **Selenium** 필요.
- 기존 임베딩 모델 `paraphrase-multilingual-MiniLM-L12-v2`의 **max_seq_length=128 토큰**인데, 청크가 평균 728토큰이라 **99%가 잘려서** 임베딩됨(뒷부분 미반영). 검색 품질의 숨은 병목이었음.

## 한 일

### 1. 구조 보존 크롤러 — `src/collect_guide_selenium.py`
- 아티클은 `df.nexon.com/guide?no={id}` 형태(랜딩에서 링크 수집, 125개).
- 헤드리스 Chrome으로 렌더 후 콘텐츠 컨테이너의 `innerHTML`을 BeautifulSoup로 파싱.
- `h1/h2` → `## `, `h3~h5` → `### ` 마커로 **섹션 구조 보존**(flat text 아님), 블록마다 줄바꿈.
- 본문의 "이 문서는 YYYY-MM-DD에 업데이트 되었습니다" → `published_at` 파싱, "텍스트복사" 버튼 라벨 제거.
- robots.txt 허용 범위(`/guide`)만, 아티클당 4초 렌더 대기.

### 2. 섹션 기반 재귀 청커 — `src/chunk_guide.py`
- `## `/`### ` 마커로 **논리 섹션 분할**(heading path 추적).
- 섹션이 크면 **재귀 폴백**: 문단(`\n`) → 문장 → 하드 문자컷.
- **단위 오버랩**: 이전 청크의 마지막 unit을 다음 청크로 carry.
- 각 청크 text에 **섹션 헤더 prepend**(`{섹션경로}\n{본문}`). 문서 title은 build_index가 임베딩 시 붙이므로 중복 방지 위해 title은 안 넣음.
- 결과: 125문서 → **1,110청크**(전부 섹션 헤더 있음), 문서당 평균 8.9개.

### 3. 임베딩 모델 교체 — BGE-M3
- MiniLM(128tok) → **BAAI/bge-m3(8192tok)**.
- 검증: 청크 토큰 평균 192 / 최대 658 → **창 초과(잘림) 0/1110** (이전 99% → 0%).
- `src/build_index.py`에 `published_at` None 가드 추가(날짜 없는 가이드 44개도 인덱싱 가능).
- 인덱스: `outputs/chroma_guide_chunks` (1,110).

### 4. 검색 검증 (BGE-M3)
```
python src/retrieve.py "최후의 과업 입장 조건" --persist-dir outputs/chroma_guide_chunks --model-name BAAI/bge-m3 --top-k 3
```
| 질의 | top-1 | distance |
|---|---|---|
| 최후의 과업 입장 명성 | 최후의 과업 | 0.365 |
| 무력화/카운터 설명 | 전투 시스템 | 0.402 |
| 장비 마법부여 방법 | 모험가 명성을 올리는 방법 | 0.304 |

MiniLM(0.6~0.66) 대비 distance가 타이트(0.3~0.5)해짐.

## 결과 요약

| 항목 | Before | After |
|---|---|---|
| 가이드 코퍼스 | 없음 | 125 문서 |
| 청킹 | 플랫, 고정크기 | 섹션 기반 재귀 + 오버랩, 1,110청크 |
| 헤딩 구조 | 소실 | `##`/`###` 보존 + 청크 헤더 |
| 임베딩 창 초과 | 99% 잘림 | **0% (BGE-M3 8192)** |
| 인덱스 | — | outputs/chroma_guide_chunks |

회귀: 기존 스모크 통과, 기존 MiniLM 인덱스 무영향.

## 다음 (Stage 2)

- BGE-M3 **sparse + dense RRF 하이브리드** (현재는 dense + 기존 lexical rerank).
- 가이드 기반 **평가셋**(`make_official_eval_set`를 guide_chunks에 적용) → 정직한 eval에 게임가이드 질문 포함.
- 그 위에서 청크 크기/헤더 정책 A/B.
- `chunk_guide`의 `section`을 Chroma metadata에도 넣어 citation에 노출(`to_chroma_metadata` 확장).
