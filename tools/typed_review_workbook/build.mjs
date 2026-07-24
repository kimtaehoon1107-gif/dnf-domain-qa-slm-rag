import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const inputPath = path.join(
  root,
  "data/review/typed_evidence_ref_generalization_candidate_64.jsonl",
);
const validationPath = path.join(
  root,
  "reports/v3/typed_evidence_ref_generalization_candidate_64_validation.json",
);
const outputDir = path.join(
  root,
  "outputs/019f8a1b-d701-7662-81fe-3741d3277c70",
);
const outputPath = path.join(
  outputDir,
  "typed_evidence_ref_generalization_review_64.xlsx",
);

const records = (await fs.readFile(inputPath, "utf8"))
  .trim()
  .split(/\r?\n/)
  .map(JSON.parse);
const validation = JSON.parse(await fs.readFile(validationPath, "utf8"));

const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const review = workbook.worksheets.add("Review");
const evidence = workbook.worksheets.add("Evidence");
const readme = workbook.worksheets.add("README");

const navy = "#17324D";
const blue = "#2F75B5";
const lightBlue = "#D9EAF7";
const lightGray = "#F2F4F7";
const border = "#D0D7DE";
const amber = "#FFF2CC";
const green = "#E2F0D9";
const red = "#FCE4D6";
const white = "#FFFFFF";

function titleStyle(range) {
  range.format = {
    fill: navy,
    font: { bold: true, color: white, size: 16 },
    verticalAlignment: "center",
  };
  range.format.rowHeight = 30;
}

function headerStyle(range) {
  range.format = {
    fill: blue,
    font: { bold: true, color: white },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: border },
  };
  range.format.rowHeight = 28;
}

function gridStyle(range) {
  range.format = {
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: border },
  };
}

summary.showGridLines = false;
summary.getRange("A1:F1").merge();
summary.getRange("A1:F1").values = [["Typed evidence-ref 일반화 후보 64문항 — 검수 현황"]];
titleStyle(summary.getRange("A1:F1"));
summary.getRange("A3:B10").values = [
  ["지표", "값"],
  ["전체 문항", null],
  ["pending review", null],
  ["execution allowed", null],
  ["정확 근거 단위", validation.evidence_unit_count],
  ["과거 질문 exact overlap", validation.prior_exact_question_overlap_slots.length],
  ["미등록 parent overlap", validation.unregistered_parent_overlap_count],
  ["자동 검증", validation.status.toUpperCase()],
];
summary.getRange("B4").formulas = [["=COUNTA(Review!A2:A65)"]];
summary.getRange("B5").formulas = [['=COUNTIF(Review!M2:M65,"pending")']];
summary.getRange("B6").formulas = [['=COUNTIF(Review!Q2:Q65,TRUE)']];
headerStyle(summary.getRange("A3:B3"));
gridStyle(summary.getRange("A4:B10"));
summary.getRange("A12:B20").values = [
  ["출처", "문항 수"],
  ["dnf_notice", null],
  ["dnf_update", null],
  ["dnf_event", null],
  ["dnf_game_guide", null],
  ["dnf_faq", null],
  ["dnf_account_policy", null],
  ["dnf_seria_shop", null],
  ["dnf_monthly_item", null],
];
summary.getRange("B13").formulas = [['=COUNTIF(Review!B$2:B$65,A13)']];
summary.getRange("B13:B20").fillDown();
headerStyle(summary.getRange("A12:B12"));
gridStyle(summary.getRange("A13:B20"));
summary.getRange("D12:E20").values = [
  ["1차 차원", "문항 수"],
  ["temporal_role", null],
  ["boolean_direction", null],
  ["sibling_relation", null],
  ["multi_requirement", null],
  ["table_attribute", null],
  ["revision_selection", null],
  ["unsupported_or_partial", null],
  ["direct_fact", null],
];
summary.getRange("E13").formulas = [['=COUNTIF(Review!C$2:C$65,D13)']];
summary.getRange("E13:E20").fillDown();
headerStyle(summary.getRange("D12:E12"));
gridStyle(summary.getRange("D13:E20"));
summary.getRange("A22:F25").values = [
  ["잠금 상태", "64개 모두 pending_human_review", null, null, null, null],
  ["평가 실행", "실행하지 않음", null, null, null, null],
  ["승격 조건", "사람 검수 완료 후 freeze SHA 생성", null, null, null, null],
  ["주의", "현재 파일은 검수 패킷이며 독립 성능으로 주장할 수 없음", null, null, null, null],
];
summary.getRange("A22:A25").format = {
  fill: lightBlue,
  font: { bold: true, color: navy },
};
gridStyle(summary.getRange("A22:F25"));
summary.getRange("A:F").format.columnWidth = 18;
summary.getRange("B:B").format.columnWidth = 30;
summary.getRange("E:E").format.columnWidth = 18;
summary.freezePanes.freezeRows(1);

const reviewHeaders = [
  "Slot",
  "Source",
  "Primary dimension",
  "Question",
  "Expected mode",
  "Time scope",
  "As of",
  "Req count",
  "Requirements summary",
  "Primary document",
  "Source URL",
  "Author status",
  "Review status",
  "Reviewer ID",
  "Reviewed at",
  "Review rationale",
  "Execution allowed",
  "Parent overlap exception",
];
const reviewRows = records.map((record) => [
  record.slot_ordinal,
  record.source_id,
  record.primary_dimension,
  record.question_text,
  record.expected_response_mode,
  record.time_scope,
  record.as_of,
  record.requirements.length,
  record.requirements
    .map(
      (item) =>
        `${item.requirement_id}: ${item.subject} / ${item.relation} / ${item.value_type} / ${JSON.stringify(item.required_values)}`,
    )
    .join("\n"),
  record.primary_document_title,
  record.primary_document_url,
  record.author_status,
  record.review.status,
  record.review.reviewer_id,
  record.review.reviewed_at,
  record.review.rationale,
  record.execution_allowed,
  record.parent_overlap_exception_reason,
]);
review.getRangeByIndexes(0, 0, 1, reviewHeaders.length).values = [reviewHeaders];
review.getRangeByIndexes(1, 0, reviewRows.length, reviewHeaders.length).values = reviewRows;
headerStyle(review.getRange("A1:R1"));
gridStyle(review.getRange("A2:R65"));
review.tables.add("A1:R65", true, "ReviewCandidatesTable").style = "TableStyleMedium2";
review.freezePanes.freezeRows(1);
review.freezePanes.freezeColumns(3);
review.getRange("M2:M65").dataValidation = {
  rule: { type: "list", values: ["pending", "approved", "rewrite", "rejected"] },
};
review.getRange("M2:M65").conditionalFormats.add("containsText", {
  text: "pending",
  format: { fill: amber, font: { color: "#7F6000" } },
});
review.getRange("M2:M65").conditionalFormats.add("containsText", {
  text: "approved",
  format: { fill: green, font: { color: "#375623" } },
});
review.getRange("M2:M65").conditionalFormats.add("containsText", {
  text: "rewrite",
  format: { fill: "#FCE4D6", font: { color: "#9C5700" } },
});
review.getRange("M2:M65").conditionalFormats.add("containsText", {
  text: "rejected",
  format: { fill: red, font: { color: "#9C0006" } },
});
review.getRange("A:A").format.columnWidth = 7;
review.getRange("B:C").format.columnWidth = 20;
review.getRange("D:D").format.columnWidth = 48;
review.getRange("E:H").format.columnWidth = 15;
review.getRange("I:I").format.columnWidth = 55;
review.getRange("J:J").format.columnWidth = 32;
review.getRange("K:K").format.columnWidth = 36;
review.getRange("L:M").format.columnWidth = 21;
review.getRange("N:P").format.columnWidth = 20;
review.getRange("Q:Q").format.columnWidth = 16;
review.getRange("R:R").format.columnWidth = 45;
review.getRange("A2:R65").format.rowHeight = 64;

const evidenceHeaders = [
  "Slot",
  "Requirement ID",
  "Expected status",
  "Subject",
  "Relation",
  "Value type",
  "Required values",
  "Evidence #",
  "Exact evidence text",
  "Document title",
  "Document ID",
  "Chunk ID",
  "Start",
  "End",
  "Source URL",
];
const evidenceRows = [];
for (const record of records) {
  for (const requirement of record.requirements) {
    if (requirement.acceptable_evidence_units.length === 0) {
      evidenceRows.push([
        record.slot_ordinal,
        requirement.requirement_id,
        requirement.expected_status,
        requirement.subject,
        requirement.relation,
        requirement.value_type,
        JSON.stringify(requirement.required_values),
        0,
        "(공식 문서에서 근거 없음)",
        record.primary_document_title,
        record.primary_document_id,
        null,
        null,
        null,
        record.primary_document_url,
      ]);
      continue;
    }
    requirement.acceptable_evidence_units.forEach((unit, index) => {
      evidenceRows.push([
        record.slot_ordinal,
        requirement.requirement_id,
        requirement.expected_status,
        requirement.subject,
        requirement.relation,
        requirement.value_type,
        JSON.stringify(requirement.required_values),
        index + 1,
        unit.text,
        unit.title,
        unit.document_id,
        unit.chunk_id,
        unit.start_char,
        unit.end_char,
        unit.canonical_url,
      ]);
    });
  }
}
evidence.getRangeByIndexes(0, 0, 1, evidenceHeaders.length).values = [evidenceHeaders];
evidence.getRangeByIndexes(1, 0, evidenceRows.length, evidenceHeaders.length).values =
  evidenceRows;
const evidenceEnd = evidenceRows.length + 1;
headerStyle(evidence.getRange(`A1:O1`));
gridStyle(evidence.getRange(`A2:O${evidenceEnd}`));
evidence.tables.add(`A1:O${evidenceEnd}`, true, "EvidenceUnitsTable").style =
  "TableStyleMedium2";
evidence.freezePanes.freezeRows(1);
evidence.freezePanes.freezeColumns(3);
evidence.getRange("A:A").format.columnWidth = 7;
evidence.getRange("B:C").format.columnWidth = 20;
evidence.getRange("D:E").format.columnWidth = 28;
evidence.getRange("F:H").format.columnWidth = 18;
evidence.getRange("I:I").format.columnWidth = 60;
evidence.getRange("J:J").format.columnWidth = 32;
evidence.getRange("K:L").format.columnWidth = 42;
evidence.getRange("M:N").format.columnWidth = 10;
evidence.getRange("O:O").format.columnWidth = 40;
evidence.getRange(`A2:O${evidenceEnd}`).format.rowHeight = 54;
evidence.getRange(`C2:C${evidenceEnd}`).conditionalFormats.add("containsText", {
  text: "unsupported",
  format: { fill: lightGray, font: { italic: true, color: "#666666" } },
});

readme.showGridLines = false;
readme.getRange("A1:F1").merge();
readme.getRange("A1:F1").values = [["검수 안내"]];
titleStyle(readme.getRange("A1:F1"));
readme.getRange("A3:B13").values = [
  ["항목", "설명"],
  ["목적", "새 Typed evidence-ref 기준선의 일반화 검증용 64문항 후보를 사람 검수"],
  ["현재 상태", "64/64 draft_complete_pending_human_review"],
  ["평가 가능 여부", "불가 — execution_allowed=false"],
  ["Review 시트", "질문·요구·정답 값을 확인하고 M~P열에 판정/검수자/시각/근거를 기록"],
  ["Evidence 시트", "요구별 exact source slice와 document/chunk 좌표 확인"],
  ["승인", "내용 정답과 근거가 직접 연결되며 질문이 모호하지 않을 때 approved"],
  ["Rewrite", "질문 또는 gold를 일반화 가능한 형태로 수정해야 할 때 rewrite"],
  ["Rejected", "근거 부족·중복·시점 불명확 등으로 평가 문항에 부적합할 때 rejected"],
  ["주의", "문항 작성 후 아직 검색·reranker·Qwen3·verifier를 실행하지 않음"],
  ["다음 단계", "사람 검수 완료 → approved 60개 이상 확인 → freeze 및 SHA 기록 → 최초 A/B"],
];
headerStyle(readme.getRange("A3:B3"));
gridStyle(readme.getRange("A4:B13"));
readme.getRange("A:A").format.columnWidth = 22;
readme.getRange("B:B").format.columnWidth = 80;
readme.getRange("A4:B13").format.rowHeight = 38;
readme.freezePanes.freezeRows(1);

await fs.mkdir(outputDir, { recursive: true });
const summaryPreview = await workbook.render({
  sheetName: "Summary",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_summary.png"),
  new Uint8Array(await summaryPreview.arrayBuffer()),
);
const reviewPreview = await workbook.render({
  sheetName: "Review",
  autoCrop: "all",
  scale: 0.6,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_review.png"),
  new Uint8Array(await reviewPreview.arrayBuffer()),
);
const evidencePreview = await workbook.render({
  sheetName: "Evidence",
  autoCrop: "all",
  scale: 0.6,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_evidence.png"),
  new Uint8Array(await evidencePreview.arrayBuffer()),
);
const readmePreview = await workbook.render({
  sheetName: "README",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_readme.png"),
  new Uint8Array(await readmePreview.arrayBuffer()),
);
const siblingPreview = await workbook.render({
  sheetName: "Review",
  range: "A1:J22",
  scale: 1.4,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_sibling_slots.png"),
  new Uint8Array(await siblingPreview.arrayBuffer()),
);
const slot25Preview = await workbook.render({
  sheetName: "Review",
  range: "A23:J29",
  scale: 1.4,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_slot25_temporal.png"),
  new Uint8Array(await slot25Preview.arrayBuffer()),
);

const inspection = await workbook.inspect({
  kind: "workbook,sheet,table,formula",
  maxChars: 6000,
  tableMaxRows: 4,
  tableMaxCols: 8,
  tableMaxCellChars: 80,
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_inspection.ndjson"),
  inspection.ndjson,
  "utf8",
);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
await fs.writeFile(
  path.join(outputDir, "typed_evidence_ref_generalization_review_64_formula_errors.ndjson"),
  formulaErrors.ndjson,
  "utf8",
);

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(
  JSON.stringify(
    {
      outputPath,
      rowCount: records.length,
      evidenceRowCount: evidenceRows.length,
      validationStatus: validation.status,
    },
    null,
    2,
  ),
);
