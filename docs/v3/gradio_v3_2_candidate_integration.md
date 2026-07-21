# v3.2 GO-candidate Gradio integration

The development demo exposes the three component-level GO candidates behind one
reversible switch. This is UI/runtime wiring for development only; it is not a
canonical or production promotion.

## ON behavior (default in the development demo)

- Table row atomic facts are searched as an additive sidecar. A selected seed expands
  to the complete source table, and every displayed row remains an exact parent-chunk slice.
- A table seed must belong to a parent already cited for the same requirement. The route's
  source list alone cannot attach a table from another product or revision.
- The global temporal overlay removes `deny` documents only for current-mode retrieval.
  `current_unverified` citations remain visible with an explicit warning and no fabricated
  `last_verified_at`.
- Current-mode table-sidecar search applies the same global temporal decision as parent
  retrieval. Historical or preview modes remain bounded to their already-cited parents.
- Duplicate-family metadata is shown on citations as a candidate family ID and source
  role. Documents are not merged or deduplicated.

## OFF control

Run with `--disable-v3-2-candidates` to reproduce the prior development demo. The OFF
arm does not load or apply any of the three candidate overlays.

## Safety boundary

The dirty canonical corpus, parent retrieval, planner, reranker, extractive assembler,
and exact-citation validation remain unchanged. The integration does not train models,
change gold, or access a sealed/frozen benchmark.
