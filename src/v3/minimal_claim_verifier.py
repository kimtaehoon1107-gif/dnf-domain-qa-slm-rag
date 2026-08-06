from __future__ import annotations

from typing import Any

from src.v3.minimal_atomic_proof import verify_atomic_claim_proof
from src.v3.minimal_boolean_semantics import boolean_relation_evidence
from src.v3.minimal_evidence_contract import (
    PRODUCT_RECORD,
    selected_evidence_contract,
)
from src.v3.minimal_list_contract import verify_entity_list_contract
from src.v3.minimal_record_identity import evaluate_record_identity
from src.v3.minimal_structured_evidence import (
    verify_structured_row_binding,
)
from src.v3.typed_evidence_ref import (
    TypedRequirementBatchOutput,
    _entity_value_supported,
    _relation_supported,
    _render_value,
    _subject_supported,
    _temporal_role_supported,
    _text_value_supported,
    _value_supported,
)
from src.v3.value_normalization import boolean_value


_ENTITY_TYPES = {"enum", "entity", "entity_list"}
_STRUCTURED_TYPES = {
    "boolean",
    "currency",
    "date",
    "date_range",
    "datetime",
    "duration_range",
    "number",
    "percentage",
    "price",
    "time",
    "time_range",
}


def _value_is_supported(
    requirement: dict[str, Any],
    value_type: str,
    value: Any,
    evidence_text: str,
    *,
    as_of: str,
    relation_aware_boolean: bool,
) -> bool:
    if value_type == "boolean" and relation_aware_boolean:
        normalized = boolean_value(value)
        return (
            normalized is not None
            and normalized
            in boolean_relation_evidence(
                requirement,
                evidence_text,
            )
        )
    if value_type in _ENTITY_TYPES:
        return _entity_value_supported(value, evidence_text)
    if value_type in _STRUCTURED_TYPES:
        return _value_supported(
            value_type,
            value,
            evidence_text,
            as_of=as_of,
        )
    return _text_value_supported(value, evidence_text)


def _citation_for_unit(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": unit["chunk_id"],
        "parent_document_id": unit["parent_document_id"],
        "source_id": unit["source_id"],
        "revision_id": unit.get("revision_id"),
        "start_char": unit["start_char"],
        "end_char": unit["end_char"],
        "text": unit["text"],
        "evidence_ref": unit["evidence_ref"],
    }


def _exact_unit(
    unit: dict[str, Any],
    *,
    chunks_by_id: dict[str, dict[str, Any]],
) -> bool:
    chunk = chunks_by_id.get(str(unit.get("chunk_id") or ""))
    if chunk is None:
        return False
    start = int(unit.get("start_char", -1))
    end = int(unit.get("end_char", -1))
    return (
        0 <= start < end <= len(chunk["display_text"])
        and chunk["display_text"][start:end] == unit.get("text")
    )


def _unsupported_requirement(
    requirement: dict[str, Any],
    *,
    model_status: str | None,
    failures: list[str],
    record_identity: dict[str, Any] | None = None,
    structured_binding: dict[str, Any] | None = None,
    evidence_contract: dict[str, Any] | None = None,
    list_contract: dict[str, Any] | None = None,
    atomic_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "requirement_id": requirement["requirement_id"],
        "status": "unsupported",
        "value_type": requirement["value_type"],
        "value": None,
        "answer": "",
        "citations": [],
        "verification": {
            "model_status": model_status,
            "failure_reasons": list(dict.fromkeys(failures)),
            "record_identity": record_identity,
            "structured_binding": structured_binding,
            "evidence_contract": evidence_contract,
            "list_contract": list_contract,
            "atomic_proof": atomic_proof,
        },
    }


def verify_minimal_claim_batch(
    output: TypedRequirementBatchOutput | dict[str, Any],
    *,
    requirements: list[dict[str, Any]],
    question: str,
    as_of: str,
    evidence_units_by_ref: dict[str, dict[str, Any]],
    chunks_by_id: dict[str, dict[str, Any]],
    structured_rows_by_coordinate: dict[
        tuple[str, int, int], dict[str, Any]
    ] | None = None,
    profile: str = "v3",
    enable_atomic_proof: bool = False,
) -> dict[str, Any]:
    """Verify fixed typed values and server-owned evidence references."""

    if profile not in {"v2", "v3"}:
        raise RuntimeError(f"unknown minimal verifier profile: {profile}")
    relation_aware_boolean = profile == "v3"
    parsed = (
        output
        if isinstance(output, TypedRequirementBatchOutput)
        else TypedRequirementBatchOutput.model_validate(output)
    )
    expected_ids = [str(row["requirement_id"]) for row in requirements]
    actual_ids = [row.requirement_id for row in parsed.requirements]
    if (
        len(actual_ids) != len(set(actual_ids))
        or set(actual_ids) != set(expected_ids)
    ):
        verified = [
            _unsupported_requirement(
                requirement,
                model_status=None,
                failures=["fixed_requirement_contract_mismatch"],
            )
            for requirement in requirements
        ]
        return _render_batch(
            verified,
            batch_failures=["fixed_requirement_contract_mismatch"],
        )

    parsed_by_id = {row.requirement_id: row for row in parsed.requirements}
    verified = []
    for requirement in requirements:
        requirement_id = str(requirement["requirement_id"])
        selection = parsed_by_id[requirement_id]
        if selection.status == "unsupported":
            verified.append(
                _unsupported_requirement(
                    requirement,
                    model_status="unsupported",
                    failures=[],
                )
            )
            continue

        failures = []
        expected_type = str(requirement["value_type"])
        if selection.value_type != expected_type:
            failures.append("value_type_mismatch")

        refs = list(dict.fromkeys(selection.evidence_refs))
        if len(refs) != len(selection.evidence_refs):
            failures.append("duplicate_evidence_ref")
        selected_units = []
        for evidence_ref in refs:
            unit = evidence_units_by_ref.get(evidence_ref)
            if unit is None:
                failures.append("evidence_ref_not_in_candidates")
                continue
            if not _exact_unit(unit, chunks_by_id=chunks_by_id):
                failures.append("evidence_coordinate_mismatch")
                continue
            selected_units.append(unit)

        record_identity = evaluate_record_identity(
            requirement,
            selected_units,
            question=question,
            force=False,
        )
        evidence_contract = selected_evidence_contract(
            selected_units,
            structured_rows_by_coordinate=(
                structured_rows_by_coordinate or {}
            ),
        )
        if evidence_contract["branch"] == PRODUCT_RECORD:
            if profile == "v3":
                record_identity = evaluate_record_identity(
                    requirement,
                    selected_units,
                    question=question,
                    force=True,
                )
        if record_identity["state"] in {"mismatch", "unproven"}:
            failures.append("record_identity_failed")
        structured_binding = verify_structured_row_binding(
            requirement,
            selection.value,
            selected_units,
            structured_rows_by_coordinate=(
                structured_rows_by_coordinate or {}
            ),
            value_matches=lambda value, text: _value_is_supported(
                requirement,
                expected_type,
                value,
                text,
                as_of=as_of,
                relation_aware_boolean=relation_aware_boolean,
            ),
        )
        if structured_binding["state"] == "mismatch":
            failures.append("structured_row_binding_failed")

        selected_text = "\n".join(
            str(unit.get("text") or "") for unit in selected_units
        )
        semantic_text = "\n".join(
            "\n".join(
                value
                for value in (
                    str(unit.get("context_text") or ""),
                    str(unit.get("text") or ""),
                )
                if value
            )
            for unit in selected_units
        )
        titles = " ".join(
            str(unit.get("title") or "") for unit in selected_units
        )
        list_contract = (
            verify_entity_list_contract(
                requirement,
                selection.value,
                selected_text,
            )
            if profile == "v3"
            else {
                "state": "not_applicable",
                "failures": [],
                "required_items": [],
            }
        )
        if list_contract["state"] == "mismatch":
            failures.append("entity_list_contract_failed")
        atomic_proof = (
            verify_atomic_claim_proof(
                requirement,
                selection.value,
                selected_units,
                structured_rows_by_coordinate=(
                    structured_rows_by_coordinate or {}
                ),
                subject_matches=lambda row, text, title: (
                    _subject_supported(
                        row,
                        text,
                        title,
                        as_of=as_of,
                    )
                ),
                relation_matches=_relation_supported,
                value_matches=lambda value, text: (
                    _value_is_supported(
                        requirement,
                        expected_type,
                        value,
                        text,
                        as_of=as_of,
                        relation_aware_boolean=relation_aware_boolean,
                    )
                ),
            )
            if enable_atomic_proof
            else {
                "state": "not_applicable",
                "failures": [],
                "facts": [],
            }
        )
        if atomic_proof["state"] == "mismatch":
            failures.append("atomic_claim_proof_failed")

        if selected_units and not _subject_supported(
            requirement,
            semantic_text,
            titles,
            as_of=as_of,
        ):
            failures.append("subject_not_supported_by_evidence")
        if selected_units and not _relation_supported(
            requirement,
            semantic_text,
            titles,
        ):
            failures.append("relation_not_supported_by_evidence")
        if selected_units and not _temporal_role_supported(
            requirement,
            selection.value,
            selected_units,
            as_of=as_of,
        ):
            failures.append("temporal_role_mismatch")
        if selected_units and not _value_is_supported(
            requirement,
            expected_type,
            selection.value,
            selected_text,
            as_of=as_of,
            relation_aware_boolean=relation_aware_boolean,
        ):
            failures.append("typed_value_not_supported_by_evidence")

        if failures:
            verified.append(
                _unsupported_requirement(
                    requirement,
                    model_status="supported",
                    failures=failures,
                    record_identity=record_identity,
                    structured_binding=structured_binding,
                    evidence_contract=evidence_contract,
                    list_contract=list_contract,
                    atomic_proof=atomic_proof,
                )
            )
            continue

        citation_refs = []
        for unit in selected_units:
            citation_refs.extend(unit.get("context_refs", []))
            citation_refs.append(unit["evidence_ref"])
        citations = [
            _citation_for_unit(evidence_units_by_ref[evidence_ref])
            for evidence_ref in dict.fromkeys(citation_refs)
            if evidence_ref in evidence_units_by_ref
            and _exact_unit(
                evidence_units_by_ref[evidence_ref],
                chunks_by_id=chunks_by_id,
            )
        ]
        verified.append(
            {
                "requirement_id": requirement_id,
                "status": "supported_exact",
                "value_type": expected_type,
                "value": selection.value,
                "answer": _render_value(expected_type, selection.value),
                "citations": citations,
                "verification": {
                    "model_status": "supported",
                    "failure_reasons": [],
                    "record_identity": record_identity,
                    "structured_binding": structured_binding,
                    "evidence_contract": evidence_contract,
                    "list_contract": list_contract,
                    "atomic_proof": atomic_proof,
                },
            }
        )

    return _render_batch(verified, batch_failures=[])


def _render_batch(
    requirements: list[dict[str, Any]],
    *,
    batch_failures: list[str],
) -> dict[str, Any]:
    supported = [
        row for row in requirements if row["status"] == "supported_exact"
    ]
    if not supported:
        response_mode = "abstain"
    elif len(supported) == len(requirements):
        response_mode = "full_answer"
    else:
        response_mode = "partial_answer"
    rendered_answer = "\n".join(
        f"- {row['answer']} "
        + " ".join(
            f"[{citation['chunk_id']}]"
            for citation in row["citations"]
        )
        for row in supported
    )
    return {
        "response_mode": response_mode,
        "requirements": requirements,
        "rendered_answer": rendered_answer,
        "verification": {
            "batch_failure_reasons": batch_failures,
            "all_exposed_citations_verified": all(
                row["citations"]
                for row in supported
            ),
        },
    }
