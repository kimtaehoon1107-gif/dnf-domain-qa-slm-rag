# v3.2 Arm 7 — OCR structure-recovery readiness

OCR structure recovery is suitable only when layout coordinates or an equivalent
line/cell geometry source exists and a reviewed evaluation set can distinguish a
correct row/column reconstruction from a plausible but wrong one.

This readiness arm reads only the frozen v3 visual-evidence, OCR ledger, canonical
chunks, and existing development evaluations. It does not read image snapshots,
rerun OCR, emit structured facts, or expose unverified OCR to default retrieval.

Required preconditions for a future executable A/B are:

1. OCR word/line bounding boxes for at least the targeted assets.
2. Human-reviewed visual evidence groups with exact asset/region provenance.
3. The existing `review_required=true`, `default_exposure=false` safety boundary.
4. A predefined row/cell reconstruction metric and zero false-structure gate.

If either layout geometry or reviewed gold is absent, structure recovery is skipped
as `NO_GO_PRECONDITION`; heuristic line splitting is not treated as an implementation.
