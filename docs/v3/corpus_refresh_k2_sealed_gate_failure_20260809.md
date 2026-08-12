# 코퍼스 갱신 K2 봉인 좌표 게이트 실패

작성일: 2026-08-09  
고정 수집 시각: `2026-08-07T19:12:13+09:00`

## 결론

신규 이미지 의존 문서 2건의 visual evidence를 복구하고 정규화·청킹 자체의 모든 안전 검사를 통과했지만, 봉인 A6가 참조하는 기존 청크 좌표는 **8/33만 유지**됐다. `corpus_refresh_round_plan.md`의 K2 필수 조건인 33/33을 충족하지 못했으므로 **K3 이후를 실행하지 않았다**.

이번 실패의 주원인은 정답 본문 변경이 아니다. 조회수, 회전형 피싱 방지 이미지 alt, 다른 상품 문서에 함께 렌더링되는 현재 월간 상품 모듈, 정책 페이지의 접근 날짜가 전체 문서 해시를 바꾸었다. `chunk_id`가 `parent_document_id`를 포함하므로 문서 안의 무관한 동적 값 하나가 바뀌어도 동일한 근거 문장 청크의 좌표까지 달라진다.

## visual evidence blocker 해소

기존 15개 문서의 visual asset ledger를 재사용하고 다음 두 문서만 추가 수집·OCR했다. 공식 상세 원문 998건은 재수집하지 않았다.

| 문서 | 자산 | OCR 문자 | 결과 |
|---|---:|---:|---|
| `https://df.nexon.com/pg/21stspecialmission` | 308 | 1,385 | `resolved_with_tolerated_css_404` |
| `https://df.nexon.com/pg/michaela` | 28 | 1,460 | `resolved` |

시각 확인 결과 첫 문서는 미션·보상 표, 두 번째 문서는 21주년 프로모션·보상 정보를 실제 이미지에 포함한다. 신규 404 두 건은 직접 본문 이미지가 아니라 inline CSS의 오래된 참조이며, 다른 핵심 이미지와 OCR이 완전하게 확보돼 기존 계약에 따라 허용했다.

최종 visual evidence 결과:

- 대상: 17
- resolved: 17/17
- unresolved: 0
- blocked response: 0
- OCR engine failure: 0
- normalization candidate: 995

canonical artifact:

- `data/v3/visual_evidence/visual_asset_ledger_964f80ec9e06e845ff8d2f963a89b38173ea9aa6dbc1c7bee1de8e3fe3e4871d.jsonl`
- `data/v3/visual_evidence/visual_document_evidence_e52fcfec02582fb3eb16f59a70f84d10f4b320728be222ade0c1ae722df8244e.jsonl`
- `data/v3/visual_evidence/discovery_correction_overlay_b42186f9308c7d792fd5c155cec4d66478bf46508666fe68ecc6fc68a30b4c32.jsonl`
- `data/v3/visual_evidence/visual_evidence_manifest_2e00eb8eceb12126be84da2ba5222ab232bc4840401ab97b5090d61c7a454d02.json`
- `reports/v3/visual_evidence_pilot_7d7329fd7a6e0af282cbf44666e8671a74a5e17f335f726b5843977ad05ac659.json`

## 갱신 중 제거한 snapshot 전용 하드코딩

세 위치가 과거 2026-07-17 snapshot 숫자를 안전 계약처럼 사용하고 있었다.

1. visual evidence 대상 `18`건 고정
2. visual 정규화 후보 기준 `961` 고정
3. normalized corpus 후보 `979`, 제외 `3`, 보존 revision `1` 고정
4. ChunkV3 문서 수 `980` 고정

이를 다음 실제 계약으로 교체했다.

- visual 대상과 후보 수는 현재 hardened preview에서 계산
- eligible URL은 candidate 또는 근거 있는 overlay 제외로 전부 귀속
- material revision은 현재 preview가 선언한 개수만큼 전부 보존
- ChunkV3 기대 문서 수는 normalized manifest의 `documents.row_count` 사용

관련 커밋:

- `32a5b2a fix: derive visual evidence target counts`
- `8bf2fa3 fix: generalize normalized corpus promotion gates`
- `27f3e1d fix: derive chunk corpus size from manifest`

## K2 생성 결과

DocumentV3:

- 문서/내용: 996/996
- candidate: 995
- 제외 redirect: 3
- 보존 baseline revision: 1
- visual evidence 문서: 17
- promotion decision: **GO**

artifact:

- `data/v3/normalized/documents_dnf_official_detail_v3.1_c7128b36aa972616f5f1fa3e5d047c11fac3fa9f9264f69ae73c99a2556b2e76.jsonl`
- `data/v3/normalized/document_contents_dnf_official_detail_v3.1_44c326b14ad8d99d13e0c5b72ee926a1ca76bb6f4714394694009504c322af05.jsonl`
- `data/v3/normalized/normalized_corpus_manifest_17c6375cd94eb805697db866e202a473375d829185b4511554d897f587f6879a.json`
- `reports/v3/document_v3_promotion_41f1f77ebc6d40437b19b7bf883528d4c8aae33d12dc6f6cdbc1e0da78a8d5bb.json`

ChunkV3:

- 문서/내용: 996/996
- 전체 청크: 3,887
- DOM: 3,868
- visual OCR: 19
- offset·coverage·schema·parent·hash 안전 검사: 전부 통과
- indexing decision: **GO**

artifact:

- `data/v3/chunks/chunks_dnf_official_v3.1_930a7d8d1581a3f234ad4d1d437a2bf6e863eabe65723e98a26c35a91c33cd40.jsonl`
- `data/v3/chunks/chunk_corpus_manifest_7b4deb36cd237f82d300a87c42398df94381caf29e72fc4a519f5fbd05328001.json`
- `reports/v3/chunk_corpus_audit_13d7b594a5ab7de6e1e116c5d46133522356de60ac6b389ef6dd6bb43beefb58.json`

## 봉인 좌표 게이트

| 항목 | 결과 |
|---|---:|
| 기존 청크 | 3,599 |
| 신규 청크 | 3,887 |
| 기존 ID 유지 | 1,330 |
| 기존 ID 소멸 | 2,269 |
| 신규 ID | 2,557 |
| 봉인 A6 좌표 유지 | **8/33** |
| 봉인 A6 좌표 소멸 | **25/33** |
| 영향받은 봉인 부모 문서 | 20 |

K2 판정: **FAIL — K3 진입 금지**

## 봉인 25개 실패 원인

| 원인 | 부모 문서 | 봉인 청크 | 설명 |
|---|---:|---:|---|
| 현재 월간 상품 모듈의 cross-document 혼입 | 7 | 8 | 과거 상품 본문은 같은데 공통 영역의 `7월 이달의 아이템`이 `8월`로 변경 |
| 조회수·회전형 피싱 이미지 alt | 8 | 9 | 공지·업데이트·이벤트 본문과 무관한 동적 숫자/alt 변경 |
| 정책 페이지 접근 날짜 | 1 | 4 | 본문에 `2026년 08월 07일` 한 줄 삽입 |
| 실제 현재 월간 상품 변경 | 1 | 1 | 판매 기간과 상품 자체가 7월에서 8월로 변경 |
| 이전 corpus 문서 미보존 | 3 | 3 | 현재 collection eligibility 밖으로 나간 과거 이벤트·공지 |
| **합계** | **20** | **25** | |

### 사라진 chunk_id 전체

현재 월간 상품 모듈 혼입:

```text
chunk_sha256_00a42c60fa1c8063b1f51b02f92437c8ac13fa33f44dbcdd35133ff9ca173874
chunk_sha256_0477e57601898ca3280ab2e5517895cddd2b1015af324d229d98a90cbfcac8da
chunk_sha256_6e6b9e641c88d34677c986ee9c339ed562ade2aa5061cb2c76bc9d50d8010d8c
chunk_sha256_7dd84109b96acd0baa8878a380a0b5876bf5ed72ad9abb862f9d952c67e69fef
chunk_sha256_9215d277cdf3dcb4a97c9744fdfa8639a6d5f19d2069ca52a69ec279ec48113a
chunk_sha256_94379e20d73b98a29c63d351a0ed78a8551675f120ad178f57a1598091933f19
chunk_sha256_f002c2893434cb114c5a48d9c4b80d195b722d24b0a5a0ad57cbea04b3ab5c7d
chunk_sha256_f203c60c78615e63701bb5010736e4fe56a4eb4cac26b9bc7746ee647ee1a5ee
```

조회수·회전형 피싱 이미지 alt:

```text
chunk_sha256_0b5c98314c6c5811af11802b239987441ce3415a8619b74749b883dd4f15ab69
chunk_sha256_0d3460160bf2f90e0fab1d578711bfa0975da45bb5dd075fc31afae04c185753
chunk_sha256_335e912feb7afd35d6f84f0f577b90bb62358201bedde54ff8784877dd910085
chunk_sha256_49c240196412b8a85e14a28c27e423b0ac7a661293a851dbada907dea42384a9
chunk_sha256_5b284aab49ae09f84883bf38acc9de2319359bd728b9c49d10ee171224679f3b
chunk_sha256_6b9dc932e194d06fba4869682412425f032ee82b7a09197fa978ee628da351c7
chunk_sha256_7d359ac1c7b0b74a9733bef2f4e4767dc502b3b86357928b3a853c9ef8b77e99
chunk_sha256_ad9fe6ce44df819f0d55d310a1b1b7ab60136e1fca54d9ba0434c3b960441547
chunk_sha256_b85cf9c381f143cf45072d4a3738bdb2bebdba4634eb37cd962defa2798fc3f6
```

정책 페이지 접근 날짜:

```text
chunk_sha256_794ba7192ebf7b3ed1ed537610afbeb34088b30384ec050fef986ea18357c3a0
chunk_sha256_89cd3ff19da0087bafabc531b84e42e0f9792150cc38c3797cafc3c67317f787
chunk_sha256_9beda9e680b5bace135c96669dc3249cf5f7da5ab48f0876ea02166096065a76
chunk_sha256_bb0076d106006bfa3f4602984397c33211ec5207c0db75fa977e1c39c40a4353
```

실제 월간 상품 변경:

```text
chunk_sha256_d23a0df67a37d463f0221e3e9bfbd4fd8a65bd4b2577478c7573239523ef6043
```

이전 corpus에서 누락된 문서:

```text
chunk_sha256_23c6c9aa09ce5bca0656412de5544b822a3bbb98a6ba48cb78c3fa29a574599a
chunk_sha256_3287297a1a95058d0d4f309bf8a3694a98e81619c02e340e519c17aedc6ba98a
chunk_sha256_af8947ead8fd513fcfb6233efe7df54cee236dd291d7bdc8bb764f8487454619
```

## 왜 근거 문장이 그대로인데 ID가 바뀌었는가

일부 누락 청크는 신규 corpus의 대응 청크와 `display_text`가 100% 동일하다. 그러나 현재 ID 계약은 다음과 같다.

```text
document_id = hash(canonical_url + 전체 문서 content_hash)
chunk_id    = hash(parent_document_id + offset + display_text_hash + chunker_version)
```

따라서 문서 말미의 조회수나 다른 상품 모듈 한 줄이 바뀌면 `document_id`가 달라지고, 동일한 본문 근거도 새 parent를 사용하므로 `chunk_id`가 달라진다. 이는 해시 충돌이나 chunker 비결정성이 아니다.

## 다음 권장 작업

우선순위는 **이전 canonical corpus를 revision으로 보존하는 일반 merge**다.

1. `build_normalized_corpus`가 이전 v3.1 DocumentV3의 URL당 복수 revision을 입력받도록 확장한다.
2. 이전 `document_id`가 새 corpus에 없으면 그대로 보존하되 current/default로 노출하지 않는다.
3. 새 내용은 새 revision으로 추가하고 lineage/supersedes를 연결한다.
4. 과거 eligibility 밖으로 나간 문서도 expired/non-default revision으로 유지한다.
5. benchmark의 33개 ID를 코드에 하드코딩하지 않고 모든 이전 revision을 동일 규칙으로 보존한다.
6. 별도 parser cleanup으로 조회수·회전형 피싱 alt·cross-document 월간 상품 모듈·접근 날짜를 현재 revision에서 제거해 다음 갱신의 불필요한 churn을 줄인다.
7. K2를 처음부터 다시 실행해 33/33을 확인한다.

기존 오염 값을 신규 본문에 억지로 복사하거나, 봉인 33개만 예외 보존하거나, 좌표를 수동 remap해서 통과시키면 안 된다.

## 실행하지 않은 단계

- K3 GPU preflight 및 BM25/BGE-M3 인덱싱
- K4 런타임 상수 4개 전환
- K4 전체 회귀
- K5 Qwen adaptive 32
- K6 채택/롤백

기존 런타임은 계속 2026-07-17 corpus를 가리킨다.
