from __future__ import annotations

from typing import Any


def compact_prompt_evidence_refs(
    prompt: str,
    evidence_units_by_ref: dict[str, dict[str, Any]],
) -> tuple[
    str,
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    """Expose contiguous short refs while preserving server-owned coordinates."""

    ordered_refs = []
    for line in prompt.splitlines():
        evidence_ref = line.split("\t", 1)[0]
        if (
            "\t" in line
            and evidence_ref in evidence_units_by_ref
            and evidence_ref not in ordered_refs
        ):
            ordered_refs.append(evidence_ref)
    if set(ordered_refs) != set(evidence_units_by_ref):
        raise RuntimeError("prompt and visible evidence refs differ")

    original_to_prompt = {
        original_ref: f"E{index}"
        for index, original_ref in enumerate(ordered_refs, start=1)
    }
    compact_units = {}
    for original_ref in ordered_refs:
        prompt_ref = original_to_prompt[original_ref]
        original = evidence_units_by_ref[original_ref]
        unit = {
            **original,
            "evidence_ref": prompt_ref,
            "original_evidence_ref": original_ref,
            "context_refs": [
                original_to_prompt[context_ref]
                for context_ref in original.get("context_refs", [])
                if context_ref in original_to_prompt
            ],
            "continuation_refs": [
                original_to_prompt[continuation_ref]
                for continuation_ref in original.get(
                    "continuation_refs",
                    [],
                )
                if continuation_ref in original_to_prompt
            ],
        }
        compact_units[prompt_ref] = unit

    compact_lines = []
    for line in prompt.splitlines():
        original_ref = line.split("\t", 1)[0]
        if original_ref in original_to_prompt and "\t" in line:
            line = (
                original_to_prompt[original_ref]
                + "\t"
                + line.split("\t", 1)[1]
            )
        compact_lines.append(line)
    return "\n".join(compact_lines), compact_units, original_to_prompt
