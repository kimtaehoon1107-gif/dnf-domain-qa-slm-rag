from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.io_utils import read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise RuntimeError(f"output already exists: {args.output}")

    rows = list(read_jsonl(args.candidates))
    lines = [
        "# Typed evidence-ref 신규 32문항 사람 검수 패킷",
        "",
        "> 상태: 초안 / 실행 잠금. 각 문항의 질문, 요구별 정답, 공식 원문을 검수한 뒤 승인 여부를 기록합니다.",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row['slot_ordinal']:02d}. {row['question_text']}",
                "",
                f"- 출처: `{row['source_id']}`",
                f"- 유형: `{row['primary_dimension']}`",
                f"- 기대 응답: `{row['expected_response_mode']}`",
                f"- 공식 문서: [{row['primary_document_title']}]({row['primary_document_url']})",
                "",
            ]
        )
        for requirement in row["requirements"]:
            values = (
                json.dumps(requirement["required_values"], ensure_ascii=False)
                if requirement["expected_status"] == "supported"
                else "문서 근거 없음(unsupported)"
            )
            lines.extend(
                [
                    f"### {requirement['requirement_id']}",
                    "",
                    f"- subject: `{requirement['subject']}`",
                    f"- relation: `{requirement['relation']}`",
                    f"- value type: `{requirement['value_type']}`",
                    f"- 정답: `{values}`",
                    "",
                ]
            )
            if requirement["acceptable_evidence_units"]:
                lines.append("공식 원문:")
                lines.append("")
                for unit in requirement["acceptable_evidence_units"]:
                    lines.extend(
                        [
                            "```text",
                            unit["text"],
                            "```",
                            "",
                            f"좌표: `{unit['chunk_id']}:{unit['start_char']}:{unit['end_char']}`",
                            "",
                        ]
                    )
            else:
                lines.extend(["공식 원문: 없음", ""])
        lines.extend(
            [
                "- [ ] 질문 표현 승인",
                "- [ ] 정답 값 승인",
                "- [ ] 원문 근거·좌표 승인",
                "- 검수 메모:",
                "",
            ]
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} review rows to {args.output}")


if __name__ == "__main__":
    main()
