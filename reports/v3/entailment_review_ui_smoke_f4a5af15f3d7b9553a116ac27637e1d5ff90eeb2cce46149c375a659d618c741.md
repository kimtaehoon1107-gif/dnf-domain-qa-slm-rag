# DNF RAG v3 Entailment Human Review UI Smoke

## Decision

- UI contract: **GO**
- Human review: **PENDING**
- Natural Verifier evaluation: **NO-GO**
- Production Verifier / Generator: **NO-GO**

The UI loads 40 frozen review rows, does not load the sampling ledger or model predictions, writes only a mutable draft under `outputs/v3`, and requires `ready_for_scoring=true` before immutable export.

Run locally with:

`python src/v3/review_entailment_app.py`

The default server is `127.0.0.1:7861`; sharing is disabled unless explicitly requested.
