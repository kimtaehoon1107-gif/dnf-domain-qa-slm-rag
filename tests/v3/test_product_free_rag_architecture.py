from __future__ import annotations

import ast
from pathlib import Path

from src.v3.product_free_rag import (
    DEFAULT_EVIDENCE_UNITS,
    DEFAULT_PARENT_LIMIT,
    DEFAULT_RERANK_DEPTH,
    DEFAULT_RETRIEVAL_DEPTH,
    ProductClaim,
    ProductRagOutput,
)


ROOT = Path(__file__).resolve().parents[2]
CORE_FILES = (
    ROOT / "src/v3/product_free_rag.py",
    ROOT / "src/v3/product_evidence_pack.py",
    ROOT / "src/v3/product_minimal_verifier.py",
)
BANNED_IMPORT_PREFIXES = (
    "src.v3.claim_contract_relation_registry",
    "src.v3.llm_query_plan",
    "src.v3.minimal_claim",
    "src.v3.question_router",
    "src.v3.typed_evidence_ref",
)


def test_product_core_keeps_the_bounded_minimal_contract() -> None:
    imported_modules = set()
    for path in CORE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)

    assert not any(
        module.startswith(prefix)
        for module in imported_modules
        for prefix in BANNED_IMPORT_PREFIXES
    )
    assert DEFAULT_RETRIEVAL_DEPTH == 20
    assert DEFAULT_RERANK_DEPTH == 8
    assert DEFAULT_PARENT_LIMIT == 2
    assert DEFAULT_EVIDENCE_UNITS == 8
    assert set(ProductClaim.model_fields) == {"text", "evidence_refs"}
    assert set(ProductRagOutput.model_fields) == {
        "mode",
        "claims",
        "clarification",
    }
