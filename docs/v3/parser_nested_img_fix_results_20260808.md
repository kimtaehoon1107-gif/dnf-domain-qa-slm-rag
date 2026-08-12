# 중첩 `img` 파서 수정 결과

작성일: 2026-08-08  
실행 기준: `docs/v3/parser_nested_img_fix_plan.md`

## 결론

P0에서 수정 전 회귀를 재현했고, P1에서 `decompose()`로 이미 무효화된 이미지 태그를 건너뛰는 2줄 수정만 적용했다. P2의 998건 재검증 결과 기존 정상 문서의 추출 결과는 바뀌지 않았고, 실패했던 `21stpcb` 문서만 정상 복구됐다. 따라서 P2 게이트는 **PASS**이며, 원문 재수집 없이 `corpus_refresh_round_plan.md`의 K2부터 재개할 수 있다.

## P0 — 수정 전 실패 재현

추가한 회귀 자산:

- `tests/v3/fixtures/nested_img_void_tag.html`
- `tests/v3/test_harden_detail_parsers_nested_img.py`

fixture는 앞쪽의 닫힘 슬래시 없는 이미지와 뒤쪽 이미지 묶음을 함께 포함한다. 두 번째 이미지에는 `alt="설명 있는 이미지"`를 넣어, 크래시만 피하고 의미 정보를 잃는 수정도 실패하도록 했다.

수정 전 단일 테스트는 다음 위치에서 예상대로 실패했다.

```text
AttributeError: 'NoneType' object has no attribute 'get'
src/v3/harden_detail_parsers.py:133
```

수정 전 전체 회귀:

```text
3 failed, 1269 passed, 2 warnings, 67 subtests passed
```

새 실패 1건과 기존 SHA 면제 실패 2건뿐이었다.

## 원문 원인 정정

초기 분석에서 `21stpcb`의 아이콘 이미지 첫 항목에 닫힘 슬래시가 없다고 보았지만, 로컬 원문을 다시 확인한 결과 아이콘 3개는 모두 `/>`였다. 실제 닫힘 슬래시 없는 태그는 같은 문서 앞부분의 게임 시작 이미지다. 이 앞쪽 태그와 뒤쪽 이미지 묶음이 함께 파싱·직렬화될 때 BeautifulSoup 트리에서 이미지가 중첩되고, 바깥 이미지를 `decompose()`한 뒤 미리 수집해 둔 안쪽 이미지에 접근하면서 예외가 발생했다.

원문에는 `</img>`가 없다. 해당 표시는 파싱된 트리를 문자열로 되돌리는 과정에서 나타난 것이다.

## P1 — 최소 수정

`src/v3/harden_detail_parsers.py`의 기존 이미지 순회에 다음 방어만 추가했다.

```python
if image.decomposed:
    continue
```

물리 변경은 2줄이며, 추출기 교체·트리 평탄화·라이브러리 변경은 하지 않았다.

수정 후 단일 테스트:

```text
1 passed
```

수정 후 전체 회귀:

```text
2 failed, 1270 passed, 2 warnings, 67 subtests passed
```

남은 두 실패는 기존 SHA 면제 2건과 정확히 일치한다.

## P2 — 998건 재검증

네트워크 요청이나 재수집 없이 기존 레지스트리·수집 ledger·원문 snapshot으로 hardened 추출만 다시 실행했다.

주요 결과:

| 항목 | 결과 |
|---|---:|
| 전체 문서 | 998 |
| 정상 파싱 | 995 |
| unavailable redirect | 3 |
| parser failure | 0 |
| raw hash mismatch | 0 |
| body fallback | 0 |
| FAQ/policy 오류 | 0 |

이전·이후 998행을 URL 기준으로 대조한 결과:

- 기존에 파싱된 994개 비대상 문서: 추출 텍스트 **994/994 완전 동일**
- 달라진 문서: `21stpcb` 1건뿐
- `21stpcb`: `parser_failed`, 빈 텍스트 → `parsed`, 2,750자

### 중첩 이미지 snapshot 5건 대조

| raw snapshot prefix | 문서 | 수정 전 | 수정 후 | 판정 |
|---|---|---|---|---|
| `0a500b0e…` | `tropicalpkg` 구 snapshot | parsed, 27,751자 | parsed, 27,751자 | SHA-256 동일 |
| `b8474cd2…` | `tropicalpkg` 현재 snapshot | parsed, 27,751자 | parsed, 27,751자 | SHA-256 동일 |
| `b9a61c93…` | `21stpcb` | parser_failed | parsed, 2,750자 | 실패 복구 |
| `db0ebbc6…` | `21stspecialmission` | parsed, 8,311자 | parsed, 8,311자 | SHA-256 동일 |
| `fdd59c38…` | `nbafreethrow` | parsed, 738자 | parsed, 738자 | SHA-256 동일 |

기존에 통과하던 중첩 이미지 문서 4건의 출력은 모두 byte-equivalent SHA-256으로 유지됐다.

## 생성 artifact

- preview: `data/v3/collections/detail_hardened_extraction_preview_72e6787ffafbb0847a41588f994435dbccfeede5214788bd7ef82276a56fb27c.jsonl`
- manifest: `data/v3/collections/detail_parser_hardening_manifest_b652b109a246e01fca3fbdc815f2b3df8005689ee8bd1c60facd651f3a9c0207.json`
- report: `reports/v3/detail_parser_hardening_0f5427dd8bfb458f3020be771c7df5efa76bc110980f5a91bcfe58e379f52a29.json`
- report: `reports/v3/detail_parser_hardening_0f5427dd8bfb458f3020be771c7df5efa76bc110980f5a91bcfe58e379f52a29.md`

## 다음 단계

P2는 통과했다. `corpus_refresh_round_plan.md`의 K2 정규화/청킹부터 재개한다. K2의 봉인 청크 보존 게이트를 통과한 뒤에만 K3로 이동하며, K3 시작 직전에 다른 GPU 작업이 실행 중인지 확인한다.
