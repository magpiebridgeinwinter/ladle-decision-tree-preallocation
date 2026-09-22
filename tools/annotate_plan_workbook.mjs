import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "/Users/admin/Desktop/数据文件/PLAN(1).xlsx";
const outputPath = "/Users/admin/Desktop/钢包配包/outputs/PLAN(1)_事故扰动重配包结果.xlsx";
const previewPath = "/private/tmp/PLAN1_annotated_preview.png";
const mode = process.argv[2] || "inspect";

const input = await FileBlob.load((mode === "verify" || mode === "compare") ? outputPath : inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

if (mode === "inspect") {
  console.log((await workbook.inspect({
    kind: "workbook,sheet,table",
    maxChars: 12000,
    tableMaxRows: 8,
    tableMaxCols: 70,
    tableMaxCellChars: 100,
  })).ndjson);
  const sheet = workbook.worksheets.getItemAt(0);
  const used = sheet.getUsedRange();
  const values = used.values;
  console.log("SHEET", sheet.name);
  console.log("USED", used.address || "unknown");
  console.log("VALUES", JSON.stringify(sheet.getRange("A1:AZ12").values));
  const style = await workbook.inspect({ kind: "computedStyle", sheetId: sheet.name, range: "AE1:AZ6", maxChars: 6000 });
  console.log(style.ndjson);
  const needles = ["JU6310E7", "300755", "300762", "300774", "300781"];
  for (const needle of needles) {
    const hits = [];
    for (let r = 0; r < Math.min(values.length, 500); r++) {
      const row = values[r] || [];
      if (row.some((v) => String(v ?? "").includes(needle))) hits.push({ row: r + 1, values: row.slice(0, 8) });
    }
    console.log("HITS", needle, JSON.stringify(hits));
  }
  const audit = JSON.parse(await fs.readFile("/Users/admin/Desktop/钢包配包/outputs/real_data_codex_stress_demo/audit.json", "utf8"));
  const affected = audit.stress_audit.affected_heat_ids;
  for (const heatId of affected) {
    const match = heatId.match(/^(.*)-(\d+)$/);
    const prefix = match?.[1];
    const seq = Number(match?.[2]);
    const rowIndex = values.findIndex((row) => String(row[0]) === String(seq) && String(row[2]).trim() === prefix);
    if (rowIndex >= 0) console.log("AFFECTED_ROW", rowIndex + 1, JSON.stringify(values[rowIndex].slice(0, 3)), JSON.stringify(values[rowIndex].slice(30, 38)));
    else console.log("AFFECTED_MISSING", heatId);
  }
  const preview = await workbook.render({ sheetName: sheet.name, range: "AE1:AZ18", scale: 1.5, format: "png" });
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  console.log("PREVIEW", previewPath);
  console.log("HELP", workbook.help("table.*", { include: "index,examples,notes", maxChars: 6000 }).ndjson);
  process.exit(0);
}

if (mode === "verify") {
  const sheet = workbook.worksheets.getItemAt(0);
  const used = sheet.getUsedRange();
  const values = used.values;
  const added = sheet.getRange(`AM1:AO${values.length}`).values;
  const data = added.slice(2);
  const populated = data.filter(([assignment, handling]) => assignment || handling);
  const llm = data.filter(([, handling]) => String(handling ?? "").includes("LLM"));
  const decisionTree = data.filter(([, handling]) => String(handling ?? "").startsWith("受扰动｜决策树"));
  const changed = data.filter(([, handling]) => String(handling ?? "").includes("改配"));
  const baseline = data.filter(([, , value]) => value);
  const audit = JSON.parse(await fs.readFile("/Users/admin/Desktop/钢包配包/outputs/real_data_codex_stress_demo/audit.json", "utf8"));
  const rowForHeat = new Map();
  for (let index = 2; index < values.length; index++) {
    const row = values[index] || [];
    rowForHeat.set(`${String(row[2] ?? "").trim()}-${String(row[0] ?? "").trim()}`, index);
  }
  let factoryValid = 0;
  let factorySameAsDecisionTree = 0;
  let factoryDifferentFromDecisionTree = 0;
  for (const assignment of audit.baseline_full_assignments) {
    const rowIndex = rowForHeat.get(assignment.heat_id);
    if (rowIndex == null) continue;
    const factoryLadle = String(values[rowIndex][30] ?? "").trim();
    if (/^ST\d+$/.test(factoryLadle)) {
      factoryValid += 1;
      if (factoryLadle === String(assignment.ladle_id ?? "").trim()) factorySameAsDecisionTree += 1;
      else factoryDifferentFromDecisionTree += 1;
    }
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "formula error scan",
  });
  console.log(JSON.stringify({
    sheet: sheet.name,
    usedRange: used.address || null,
    rows: values.length,
    columns: values[0]?.length || 0,
    populatedAnnotationRows: populated.length,
    llmRows: llm.length,
    decisionTreeRows: decisionTree.length,
    changedRows: changed.length,
    decisionTreeBaselineRows: baseline.length,
    factoryValid,
    factorySameAsDecisionTree,
    factoryDifferentFromDecisionTree,
    formulaErrors: errors.ndjson,
  }));
  console.log((await workbook.inspect({
    kind: "table",
    sheetId: sheet.name,
    range: "AM90:AO145",
    include: "values,formulas",
    tableMaxRows: 60,
    tableMaxCols: 4,
    tableMaxCellChars: 100,
  })).ndjson);
  const preview = await workbook.render({ sheetName: sheet.name, range: "AE128:AO142", scale: 1.5, format: "png" });
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  console.log("PREVIEW", previewPath);
  process.exit(0);
}

if (mode === "compare") {
  const sourceWorkbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
  const sourceSheet = sourceWorkbook.worksheets.getItemAt(0);
  const outputSheet = workbook.worksheets.getItemAt(0);
  const sourceValues = sourceSheet.getRange("A1:AL471").values;
  const outputValues = outputSheet.getRange("A1:AL471").values;
  let changedCells = 0;
  const samples = [];
  for (let r = 0; r < sourceValues.length; r++) {
    for (let c = 0; c < sourceValues[r].length; c++) {
      const a = JSON.stringify(sourceValues[r][c] ?? null);
      const b = JSON.stringify(outputValues[r][c] ?? null);
      if (a !== b) {
        changedCells += 1;
        if (samples.length < 8) samples.push({ row: r + 1, col: c + 1, source: sourceValues[r][c], output: outputValues[r][c] });
      }
    }
  }
  console.log(JSON.stringify({ sourceRange: "A1:AL471", changedCells, samples }));
  process.exit(0);
}

if (mode !== "edit") throw new Error(`Unknown mode: ${mode}`);

const sheet = workbook.worksheets.getItemAt(0);
const used = sheet.getUsedRange();
const values = used.values;
const rowCount = values.length;
const colCount = values[0]?.length || 0;
console.log("EDITING", sheet.name, "rows", rowCount, "cols", colCount);

const audit = JSON.parse(await fs.readFile("/Users/admin/Desktop/钢包配包/outputs/real_data_codex_stress_demo/audit.json", "utf8"));
const mainAssignments = new Map(
  audit.codex_llm.assignments.map((item) => [item.heat_id, item]),
);
const decisionTreeBaseline = new Map(
  audit.baseline_full_assignments.map((item) => [item.heat_id, item]),
);
const changedIds = new Set(audit.stress_audit.changed_assignments.map((item) => item.heat_id));

// The control scenario is the real-data two-heat case stored in the offline scenario DB.
// Its final decision-tree assignments were verified from scenario_id decision_tree_control_001.
const controlAssignments = new Map([
  ["AQ0640E1-300703", { ladle_id: "ST07", crane_id: "4170" }],
  ["DU3851D1-300667", { ladle_id: "ST08", crane_id: "2500" }],
]);

const assignmentByHeat = new Map();
for (const [heatId, assignment] of mainAssignments) {
  assignmentByHeat.set(heatId, {
    ...assignment,
    handling: changedIds.has(heatId) ? "受扰动｜LLM｜改配" : "受扰动｜LLM｜保持决策树预配",
  });
}
for (const [heatId, assignment] of controlAssignments) {
  if (assignmentByHeat.has(heatId)) throw new Error(`Duplicate scenario assignment: ${heatId}`);
  assignmentByHeat.set(heatId, {
    ...assignment,
    handling: "受扰动｜决策树重排序",
  });
}

const rowForHeat = new Map();
for (let index = 2; index < values.length; index++) {
  const row = values[index] || [];
  const sequence = String(row[0] ?? "").trim();
  const heatPrefix = String(row[2] ?? "").trim();
  if (sequence && heatPrefix) rowForHeat.set(`${heatPrefix}-${sequence}`, index + 1);
}

const missingRows = [...assignmentByHeat.keys()].filter((heatId) => !rowForHeat.has(heatId));
if (missingRows.length) throw new Error(`Scenario heat IDs missing from PLAN(1): ${missingRows.join(", ")}`);

// Extend the visible sheet beside the existing AL column without changing the source columns.
// Copying AL preserves the imported workbook's header, filter-row, font, and number-format conventions.
sheet.getRange(`AL1:AL${rowCount}`).copyTo(sheet.getRange(`AM1:AM${rowCount}`), "all");
sheet.getRange(`AL1:AL${rowCount}`).copyTo(sheet.getRange(`AN1:AN${rowCount}`), "all");
sheet.getRange(`AL1:AL${rowCount}`).copyTo(sheet.getRange(`AO1:AO${rowCount}`), "all");
sheet.getRange(`AM1:AM${rowCount}`).format.columnWidth = 25;
sheet.getRange(`AN1:AN${rowCount}`).format.columnWidth = 25;
sheet.getRange(`AO1:AO${rowCount}`).format.columnWidth = 25;
sheet.getRange(`AM1:AO${rowCount}`).format.wrapText = true;

const newColumns = Array.from({ length: rowCount }, () => [null, null, null]);
newColumns[0] = ["LLM扰动后最终配包", "扰动及处理方式", "决策树预配包（扰动前）"];
newColumns[1] = ["PostDisturbanceAssignment", "DisturbanceHandling", "DecisionTreePreallocation"];

let matchedLlm = 0;
let matchedDecisionTree = 0;
let changedCount = 0;
let baselineCount = 0;
for (const [heatId, assignment] of decisionTreeBaseline) {
  const rowNumber = rowForHeat.get(heatId);
  if (!rowNumber) continue;
  const output = assignment.action === "unassigned"
    ? "未完成配包"
    : `钢包 ${String(assignment.ladle_id ?? "").trim()}；行车 ${String(assignment.crane_id ?? "").trim()}`;
  newColumns[rowNumber - 1][2] = output;
  baselineCount += 1;
}
for (const [heatId, assignment] of assignmentByHeat) {
  const rowNumber = rowForHeat.get(heatId);
  const output = assignment.action === "unassigned"
    ? "未完成配包"
    : `钢包 ${String(assignment.ladle_id ?? "").trim()}；行车 ${String(assignment.crane_id ?? "").trim()}`;
  newColumns[rowNumber - 1][0] = output;
  newColumns[rowNumber - 1][1] = assignment.handling;
  if (assignment.handling.startsWith("受扰动｜LLM")) matchedLlm += 1;
  if (assignment.handling.startsWith("受扰动｜决策树")) matchedDecisionTree += 1;
  if (assignment.handling.includes("改配")) changedCount += 1;
}

sheet.getRange(`AM1:AO${rowCount}`).values = newColumns;
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const check = await workbook.inspect({
  kind: "table",
  sheetId: sheet.name,
  range: `AM1:AO${rowCount}`,
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 4,
  tableMaxCellChars: 100,
});
console.log(check.ndjson);
console.log(JSON.stringify({
  outputPath,
  rowCount,
  sourceColumnCount: colCount,
  annotatedHeatCount: assignmentByHeat.size,
  decisionTreeBaselineCount: baselineCount,
  matchedLlm,
  matchedDecisionTree,
  changedCount,
  blankDataRows: newColumns.slice(2).filter(([assignment, handling, baseline]) => !assignment && !handling && !baseline).length,
}));

const preview = await workbook.render({ sheetName: sheet.name, range: "AE1:AO18", scale: 1.5, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
console.log("PREVIEW", previewPath);
