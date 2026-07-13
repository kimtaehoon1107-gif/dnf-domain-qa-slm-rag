from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from io_utils import read_jsonl, write_jsonl


DEFAULT_BLOCKED_EVAL_SETS = (
    Path("data/processed/domain_eval_set_expanded.jsonl"),
    Path("data/processed/official_eval_set.jsonl"),
    Path("data/processed/fresh_paraphrase_eval_set.jsonl"),
    Path("data/processed/partial_dev_human_v1.jsonl"),
    Path("data/eval/blind_test_v1.jsonl"),
)
GENERIC_REFUSAL = "수집된 공식 문서만으로는 해당 질문에 답하기에 충분한 근거가 없습니다."
ALLOWED_SOURCE_TYPES = {"casual_paraphrase_train", "contrastive_true_train"}

VARIANTS = {
    "event_fact": (
        (
            "그리고 내 계정 상황에서 이 이벤트를 우선 챙길 가치가 있는지도 판단해줘.",
            "다만 우선 참여할 가치는 계정 진행도와 필요한 보상을 알 수 없어 판단할 수 없습니다.",
            ["우선 챙길 가치", "참여할 가치", "계정 진행도"],
        ),
        (
            "이 내용을 바탕으로 내가 지금 참여해야 하는지도 정해줘.",
            "개인별 참여 여부는 현재 성장 상황과 보유 보상을 확인할 수 없어 정할 수 없습니다.",
            ["지금 참여", "참여 여부", "성장 상황"],
        ),
        (
            "내 캐릭터 기준으로 이 보상을 노리는 게 좋은지도 골라줘.",
            "어떤 보상을 우선 노릴지는 캐릭터 상태와 목표 정보가 없어 결정할 수 없습니다.",
            ["보상을 노리는", "우선 노릴", "캐릭터 상태"],
        ),
    ),
    "guide_fact": (
        (
            "그리고 내 캐릭터가 이 기능이나 콘텐츠를 지금 우선 이용해야 하는지도 정해줘.",
            "다만 이용 우선순위는 현재 장비와 성장 목표를 알 수 없어 정할 수 없습니다.",
            ["우선 이용", "이용 우선순위", "성장 목표"],
        ),
        (
            "이 설명을 바탕으로 내 상황에서 지금 하는 게 좋은지도 판단해줘.",
            "개인 상황에서의 적합성은 보유 장비와 플레이 목표 정보가 없어 판단할 수 없습니다.",
            ["지금 하는 게 좋은", "개인 상황", "플레이 목표"],
        ),
        (
            "내 성장 단계에서도 이 방법을 먼저 선택해야 하는지도 골라줘.",
            "어떤 방법을 먼저 선택할지는 성장 단계와 필요한 결과를 확인할 수 없어 결정할 수 없습니다.",
            ["먼저 선택", "성장 단계", "어떤 방법"],
        ),
    ),
    "account_payment": (
        (
            "그리고 이 안내가 내가 겪은 상황에도 그대로 해당하는지도 판단해줘.",
            "다만 실제 계정과 연락 내용을 확인할 수 없어 개별 상황의 적용 여부는 판단할 수 없습니다.",
            ["내가 겪은 상황", "적용 여부", "실제 계정"],
        ),
        (
            "내 계정에서 지금 어떤 조치를 우선 해야 하는지도 정해줘.",
            "개별 계정 상태를 조회할 수 없으므로 어떤 조치를 우선할지는 정할 수 없습니다.",
            ["어떤 조치를 우선", "계정 상태", "내 계정"],
        ),
        (
            "내가 받은 연락에도 이 내용을 적용할 수 있는지 확인해줘.",
            "받은 연락의 발신자와 내용을 볼 수 없어 실제 적용 가능 여부는 확인할 수 없습니다.",
            ["받은 연락", "적용 가능", "발신자"],
        ),
    ),
}
EVENT_ITEM_HINTS = ("상자", "아바타", "패키지", "증폭서", "쿠폰", "보상", "큐브")
EVENT_ITEM_VARIANTS = (
    (
        "그리고 내 캐릭터에 이 아이템이나 보상을 지금 챙길 가치가 있는지도 판단해줘.",
        "다만 사용하거나 확보할 가치는 현재 장비와 필요한 보상을 알 수 없어 판단할 수 없습니다.",
        ["챙길 가치", "확보할 가치", "현재 장비"],
    ),
    (
        "내 계정에서는 이 아이템이나 보상을 우선 확보해야 하는지도 골라줘.",
        "어떤 아이템이나 보상을 먼저 확보할지는 보유 아이템과 목표 정보가 없어 정할 수 없습니다.",
        ["우선 확보", "먼저 확보", "보유 아이템"],
    ),
    (
        "이 구성이나 제한이 내 캐릭터에도 유리한지도 정해줘.",
        "개인 캐릭터에 유리한지는 장비 구성과 활용 목적을 확인할 수 없어 결정할 수 없습니다.",
        ["유리한지", "장비 구성", "활용 목적"],
    ),
)


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_parent_ids(row: dict[str, Any]) -> set[str]:
    values = {str(item) for item in row.get("expected_evidence_doc_ids", []) if item}
    if row.get("expected_doc_id"):
        values.add(str(row["expected_doc_id"]))
    return values


def expected_chunk_ids(row: dict[str, Any]) -> set[str]:
    values = {str(item) for item in row.get("expected_chunk_ids", []) if item}
    if row.get("expected_chunk_id"):
        values.add(str(row["expected_chunk_id"]))
    return values


def blocked_ids(rows: list[dict[str, Any]]) -> tuple[set[str], set[str], set[str]]:
    parents: set[str] = set()
    chunks: set[str] = set()
    questions: set[str] = set()
    for row in rows:
        parents.update(expected_parent_ids(row))
        chunks.update(expected_chunk_ids(row))
        question = normalize_space(row.get("question")).lower()
        if question:
            questions.add(question)
    return parents, chunks, questions


def source_quality(row: dict[str, Any]) -> tuple[int, int]:
    question = normalize_space(row.get("question"))
    answer = normalize_space(row.get("gold_answer") or row.get("expected_answer"))
    score = 0
    score += int(15 <= len(question) <= 45) * 2
    score += int(20 <= len(answer) <= 140) * 2
    score -= int("공식 문서가 설명한 건 뭐야" in question) * 3
    score -= int("어떻게 안내돼" in question) * 2
    score -= int(answer.startswith(("*", "##", "[")))
    return score, -stable_int(str(row.get("qa_id") or question))


def variants_for(row: dict[str, Any]) -> tuple[tuple[str, str, list[str]], ...]:
    if str(row.get("intent")) == "event_fact" and any(
        hint in str(row.get("question") or "") for hint in EVENT_ITEM_HINTS
    ):
        return EVENT_ITEM_VARIANTS
    return VARIANTS[str(row["intent"])]


def build_candidates(
    train_rows: list[dict[str, Any]],
    blocked_rows: list[dict[str, Any]],
    limit: int,
    max_per_parent: int = 2,
) -> list[dict[str, Any]]:
    blocked_parents, blocked_chunks, blocked_questions = blocked_ids(blocked_rows)
    eligible = []
    for row in train_rows:
        if str(row.get("answerability")) != "true" or str(row.get("intent")) not in VARIANTS:
            continue
        if str(row.get("source_eval_type")) not in ALLOWED_SOURCE_TYPES:
            continue
        question = normalize_space(row.get("question"))
        answer = normalize_space(row.get("gold_answer") or row.get("expected_answer"))
        evidence = normalize_space(row.get("evidence_span"))
        parents = expected_parent_ids(row)
        chunks = expected_chunk_ids(row)
        if not question or not answer or not evidence or not parents or not chunks:
            continue
        if parents & blocked_parents or chunks & blocked_chunks or question.lower() in blocked_questions:
            continue
        eligible.append(row)

    eligible.sort(key=source_quality, reverse=True)
    selected = []
    parent_counts: Counter[str] = Counter()
    for row in eligible:
        parent = sorted(expected_parent_ids(row))[0]
        if parent_counts[parent] >= max_per_parent:
            continue
        selected.append(row)
        parent_counts[parent] += 1
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        raise ValueError(f"Only {len(selected)} leakage-safe source rows available for limit={limit}.")

    candidates = []
    for index, row in enumerate(selected, start=1):
        source_id = str(row.get("qa_id") or f"source_{index:04d}")
        variant_list = variants_for(row)
        request, refusal, target_phrases = variant_list[stable_int(source_id) % len(variant_list)]
        source_question = normalize_space(row["question"])
        if not source_question.endswith(("?", ".", "!")):
            source_question += "?"
        grounded_answer = normalize_space(row.get("gold_answer") or row.get("expected_answer"))
        if not grounded_answer.endswith((".", "!", "?")):
            grounded_answer += "."
        answer = f"{grounded_answer} {refusal}"
        if GENERIC_REFUSAL in answer:
            raise ValueError(f"Generic refusal leaked into decomposition answer: {source_id}")
        candidate_id = f"partial_decomp_train_{index:04d}"
        chunk_ids = sorted(expected_chunk_ids(row))
        parent_ids = sorted(expected_parent_ids(row))
        candidates.append(
            {
                "question": f"{source_question} {request}",
                "intent": "partial_decomposition",
                "answerability": "partial",
                "expected_answer": answer,
                "gold_answer": answer,
                "evidence_span": normalize_space(row["evidence_span"]),
                "expected_doc_id": parent_ids[0],
                "expected_chunk_id": chunk_ids[0],
                "expected_evidence_doc_ids": parent_ids,
                "expected_chunk_ids": chunk_ids,
                "difficulty": "hard",
                "failure_focus": "partial_requirement_decomposition",
                "source_eval_type": "partial_decomposition_train",
                "source_split": "train",
                "split": "train",
                "qa_id": candidate_id,
                "source_qa_id": source_id,
                "source_intent": row["intent"],
                "source_eval_type_original": row.get("source_eval_type", ""),
                "source_question": normalize_space(row["question"]),
                "grounded_answer": grounded_answer,
                "unsupported_request": request,
                "targeted_abstention": refusal,
                "requirements": [
                    {
                        "requirement_id": f"{candidate_id}_g1",
                        "type": "grounded",
                        "description": "source fact request",
                        "expected_answer": grounded_answer,
                        "evidence_span": normalize_space(row["evidence_span"]),
                        "expected_chunk_ids": chunk_ids,
                    },
                    {
                        "requirement_id": f"{candidate_id}_u1",
                        "type": "unsupported",
                        "description": "personalized decision",
                        "target_phrases": target_phrases,
                        "expected_behavior": "targeted_abstention",
                    },
                ],
            }
        )
    return candidates


def validate_candidate_evidence(
    candidates: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> dict[str, int]:
    chunks_by_id = {str(row["doc_id"]): row for row in chunks}
    missing_chunks = 0
    span_mismatches = 0
    for row in candidates:
        expected = [str(item) for item in row.get("expected_chunk_ids", []) if item]
        missing_chunks += int(any(chunk_id not in chunks_by_id for chunk_id in expected))
        if expected and all(chunk_id in chunks_by_id for chunk_id in expected):
            span = normalize_space(row.get("evidence_span"))
            visible = any(
                span in normalize_space(chunks_by_id[chunk_id].get("text")) for chunk_id in expected
            )
            span_mismatches += int(not visible)
    if missing_chunks or span_mismatches:
        raise ValueError(
            f"Candidate evidence validation failed: missing_chunks={missing_chunks}, "
            f"span_mismatches={span_mismatches}"
        )
    return {"missing_chunks": missing_chunks, "span_mismatches": span_mismatches}


def review_sample(candidates: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    # Stable spread across the full candidate order; source rows were already quality-ranked.
    if sample_size > len(candidates):
        raise ValueError("Review sample cannot exceed candidate count.")
    positions = [round(index * (len(candidates) - 1) / max(sample_size - 1, 1)) for index in range(sample_size)]
    return [candidates[position] for position in positions]


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "candidate_id",
        "source_qa_id",
        "expected_doc_id",
        "expected_chunk_ids",
        "source_question",
        "grounded_answer",
        "evidence_span",
        "unsupported_request",
        "targeted_abstention",
        "proposed_question",
        "proposed_answer",
        "grounded_fact_correct",
        "unsupported_request_natural",
        "targeted_abstention_correct",
        "human_decision",
        "human_question",
        "human_answer",
        "review_notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "candidate_id": row["qa_id"],
                    "source_qa_id": row["source_qa_id"],
                    "expected_doc_id": row["expected_doc_id"],
                    "expected_chunk_ids": "|".join(row["expected_chunk_ids"]),
                    "source_question": row["source_question"],
                    "grounded_answer": row["grounded_answer"],
                    "evidence_span": row["evidence_span"],
                    "unsupported_request": row["unsupported_request"],
                    "targeted_abstention": row["targeted_abstention"],
                    "proposed_question": row["question"],
                    "proposed_answer": row["gold_answer"],
                    "grounded_fact_correct": "",
                    "unsupported_request_natural": "",
                    "targeted_abstention_correct": "",
                    "human_decision": "",
                    "human_question": "",
                    "human_answer": "",
                    "review_notes": "",
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create train-only Partial decomposition QA candidates.")
    parser.add_argument(
        "--train-qa",
        type=Path,
        default=Path("data/processed/domain_train_qa_measurement_fixed_blind_safe_v2.jsonl"),
    )
    parser.add_argument(
        "--chunks", type=Path, default=Path("data/processed/domain_doc_chunks.jsonl")
    )
    parser.add_argument(
        "--blocked-eval-set", type=Path, nargs="*", default=list(DEFAULT_BLOCKED_EVAL_SETS)
    )
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--max-per-parent", type=int, default=3)
    parser.add_argument("--review-size", type=int, default=24)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/domain_partial_decomposition_train_candidates.jsonl"),
    )
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("data/review/partial_decomposition_train_review_24.csv"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("reports/partial_decomposition_train_candidates_manifest.json"),
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    blocked_rows = [row for path in args.blocked_eval_set for row in read_jsonl(path)]
    candidates = build_candidates(
        read_jsonl(args.train_qa), blocked_rows, args.limit, args.max_per_parent
    )
    evidence_validation = validate_candidate_evidence(candidates, read_jsonl(args.chunks))
    write_jsonl(args.output, candidates)
    sample = review_sample(candidates, args.review_size)
    write_review_csv(args.review_output, sample)
    candidate_parents = {row["expected_doc_id"] for row in candidates}
    candidate_chunks = {item for row in candidates for item in row["expected_chunk_ids"]}
    candidate_questions = {normalize_space(row["question"]).lower() for row in candidates}
    blocked_parents, blocked_chunks, blocked_questions = blocked_ids(blocked_rows)
    manifest = {
        "status": "pending_human_review",
        "may_be_used_for_training": False,
        "source_train_qa": str(args.train_qa),
        "chunks": str(args.chunks),
        "blocked_eval_sets": [str(path) for path in args.blocked_eval_set],
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        "rows": len(candidates),
        "unique_questions": len(candidate_questions),
        "unique_parents": len(candidate_parents),
        "source_intent_counts": dict(Counter(row["source_intent"] for row in candidates)),
        "review_output": str(args.review_output),
        "review_sha256": sha256(args.review_output),
        "review_rows": len(sample),
        "all_candidates_in_review": len(sample) == len(candidates),
        "generic_refusal_rows": sum(GENERIC_REFUSAL in row["gold_answer"] for row in candidates),
        "blocked_parent_overlap": len(candidate_parents & blocked_parents),
        "blocked_chunk_overlap": len(candidate_chunks & blocked_chunks),
        "blocked_question_overlap": len(candidate_questions & blocked_questions),
        **evidence_validation,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
