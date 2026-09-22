import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2] || "outputs/PLAN(1)_事故扰动重配包结果.xlsx";
const auditPath = process.argv[3] || "outputs/real_data_location_aware/decision_tree_audit.json";
const outputPath = process.argv[4] || "outputs/PLAN(1)_位置映射决策树预配包结果_含行车位置.xlsx";
const previewPath = process.argv[5] || "/private/tmp/PLAN1_location_aware_preview.png";
const stressAuditPath = process.argv[6] || "outputs/real_data_codex_stress_demo/audit.json";

const audit = JSON.parse(await fs.readFile(auditPath, "utf8"));
const stressAudit = JSON.parse(await fs.readFile(stressAuditPath, "utf8"));
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = workbook.worksheets.getItemAt(0);
const used = sheet.getUsedRange();
const sourceValues = used.values;
const rowCount = sourceValues.length;
const sourceColumnCount = sourceValues[0]?.length || 0;
if (sourceColumnCount !== 41) {
  throw new Error(`输入工作簿应以 AO 结束，实际列数为 ${sourceColumnCount}`);
}

const originalAtoAO = sourceValues.map((row) => row.slice(0, 41).map((value) => value ?? null));
const resultByKey = new Map(audit.plan_output_rows.map((row) => [row.plan_key, row]));
const assignmentByKey = new Map(audit.assignment_rows.map((row) => [row.plan_key, row]));
const craneById = new Map(
  (audit.scheduling_inputs?.cranes || []).map((row) => [String(row.crane_id), row]),
);
const affectedHeatIds = new Set(stressAudit.stress_audit.window.affected_heat_ids.map(String));
const decisionTreeAfterDisturbance = new Map(
  stressAudit.decision_tree.assignments.map((row) => [String(row.heat_id), row]),
);
const codexAfterDisturbance = new Map(
  stressAudit.codex_llm.assignments.map((row) => [String(row.heat_id), row]),
);
const stressHeats = new Map(
  stressAudit.scenario_inputs.heats.map((row) => [String(row.heat_id), row]),
);
const apAfterLocationMap = new Map(
  stressAudit.baseline_full_assignments.map((row) => [String(row.heat_id), row]),
);
const outputValues = Array.from({ length: rowCount }, () => [null]);
const cranePositionValues = Array.from({ length: rowCount }, () => [null, null]);
outputValues[0] = ["决策树预配包（接入位置映射）"];
outputValues[1] = ["DecisionTreePreallocationWithLocationMap"];
cranePositionValues[0] = ["预配行车当前位置", "行车位置图示（0–48000）"];
cranePositionValues[1] = ["PreallocatedCranePosition", "PreallocatedCranePositionPercent"];

const formatCoordinate = (value) => Math.round(Number(value)).toLocaleString("en-US");
const cranePosition = (craneId) => {
  const crane = craneById.get(String(craneId));
  if (!crane) return ["行车快照缺失", null];
  const position = Number(crane.position_m);
  const lower = Number(crane.limit_0_m);
  const upper = Number(crane.limit_1_m);
  if (![position, lower, upper].every(Number.isFinite) || upper <= lower) {
    return [`行车 ${craneId}｜位置或作业范围缺失`, null];
  }
  const ratio = Math.min(1, Math.max(0, (position - lower) / (upper - lower)));
  return [
    `行车 ${craneId}｜坐标 ${formatCoordinate(position)}｜作业范围 ${formatCoordinate(lower)}–${formatCoordinate(upper)}`,
    ratio,
  ];
};

for (let index = 2; index < rowCount; index += 1) {
  const row = sourceValues[index] || [];
  const planKey = `${String(row[2] ?? "").trim()}::${String(row[0] ?? "").trim()}`;
  const assignment = assignmentByKey.get(planKey);
  const output = resultByKey.get(planKey);
  if (assignment?.status === "已分配") {
    outputValues[index][0] = `已分配｜钢包 ${assignment.ladle_id}｜行车 ${assignment.crane_id}`;
    cranePositionValues[index] = cranePosition(assignment.crane_id);
  } else if (assignment) {
    outputValues[index][0] = `状态=${assignment.status}｜${assignment.reason || "无可行候选"}`;
    cranePositionValues[index][0] = "未分配｜无行车位置";
  } else if (output) {
    outputValues[index][0] = output.result;
    cranePositionValues[index][0] = "未纳入｜无行车位置";
  } else {
    outputValues[index][0] = "状态=未纳入；原因=炉次主键未匹配";
    cranePositionValues[index][0] = "未纳入｜无行车位置";
  }
}

// AM/AN contain the superseded, non-location-aware disturbance result. Clear
// those columns while keeping AP/AQ/AR at the explicitly requested positions.
sheet.getRange(`AM1:AN${rowCount}`).clear({ applyTo: "all" });
sheet.getRange(`AO1:AO${rowCount}`).copyTo(sheet.getRange(`AP1:AP${rowCount}`), "all");
sheet.getRange(`AP1:AP${rowCount}`).values = outputValues;
sheet.getRange(`AP1:AP${rowCount}`).format.columnWidth = 32;
sheet.getRange(`AP1:AP${rowCount}`).format.wrapText = true;
sheet.getRange(`AP1:AP${rowCount}`).format.verticalAlignment = "center";
sheet.getRange(`AP3:AP${rowCount}`).format.rowHeight = 24;
sheet.getRange("AP1:AP2").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF", name: "宋体", size: 11 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};

const rowForHeat = new Map();
for (let index = 2; index < rowCount; index += 1) {
  const row = sourceValues[index] || [];
  const heatId = `${String(row[2] ?? "").trim()}-${String(row[0] ?? "").trim()}`;
  if (heatId !== "-") rowForHeat.set(heatId, index);
}

const formatDisturbanceAssignment = (assignment) => {
  if (!assignment) return null;
  if (assignment.action === "unassigned") {
    return `未完成配包｜${assignment.reason || "无可行候选"}`;
  }
  return `已分配｜钢包 ${String(assignment.ladle_id ?? "").trim()}｜行车 ${String(assignment.crane_id ?? "").trim()}`;
};

const disturbanceValues = Array.from({ length: rowCount }, () => [null, null]);
disturbanceValues[0] = ["扰动后决策树重排", "扰动后 Codex 重排"];
disturbanceValues[1] = ["DecisionTreePostDisturbanceReallocation", "CodexPostDisturbanceReallocation"];
let matchedAffected = 0;
let decisionTreeAssigned = 0;
let codexAssigned = 0;
for (const heatId of affectedHeatIds) {
  const rowIndex = rowForHeat.get(heatId);
  if (rowIndex == null) throw new Error(`扰动炉次未匹配 PLAN(1): ${heatId}`);
  const decisionTreeValue = formatDisturbanceAssignment(decisionTreeAfterDisturbance.get(heatId));
  const codexValue = formatDisturbanceAssignment(codexAfterDisturbance.get(heatId));
  if (!decisionTreeValue || !codexValue) throw new Error(`扰动结果缺少炉次: ${heatId}`);
  disturbanceValues[rowIndex][0] = decisionTreeValue;
  disturbanceValues[rowIndex][1] = codexValue;
  matchedAffected += 1;
  if (decisionTreeAfterDisturbance.get(heatId)?.action === "assign") decisionTreeAssigned += 1;
  if (codexAfterDisturbance.get(heatId)?.action === "assign") codexAssigned += 1;
}

sheet.getRange(`AP1:AP${rowCount}`).copyTo(sheet.getRange(`AQ1:AQ${rowCount}`), "all");
sheet.getRange(`AP1:AP${rowCount}`).copyTo(sheet.getRange(`AR1:AR${rowCount}`), "all");
sheet.getRange(`AQ1:AR${rowCount}`).values = disturbanceValues;
sheet.getRange(`AQ1:AR${rowCount}`).format.columnWidth = 32;
sheet.getRange(`AQ1:AR${rowCount}`).format.wrapText = true;
sheet.getRange(`AQ1:AR${rowCount}`).format.verticalAlignment = "center";
sheet.getRange(`AQ3:AR${rowCount}`).format.rowHeight = 24;

// Keep the preallocation crane snapshot adjacent to the two response paths.
// The percentage in AT is derived from the same CRANE coordinate scale and is
// rendered as an Excel data bar, rather than a decorative text approximation.
sheet.getRange(`AS1:AT${rowCount}`).values = cranePositionValues;
sheet.getRange(`AS1:AT${rowCount}`).format.wrapText = true;
sheet.getRange(`AS1:AT${rowCount}`).format.verticalAlignment = "center";
sheet.getRange(`AS3:AS${rowCount}`).format.columnWidth = 34;
sheet.getRange(`AT3:AT${rowCount}`).format.columnWidth = 22;
sheet.getRange(`AS3:AT${rowCount}`).format.rowHeight = 24;
sheet.getRange("AS1:AT2").format = {
  fill: "#4472C4",
  font: { bold: true, color: "#FFFFFF", name: "宋体", size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange(`AS3:AS${rowCount}`).format = {
  fill: "#F2F6FC",
  font: { name: "宋体", size: 10, color: "#1F1F1F" },
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange(`AT3:AT${rowCount}`).format = {
  fill: "#F2F6FC",
  font: { name: "宋体", size: 10, color: "#1F1F1F" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange(`AT3:AT${rowCount}`).setNumberFormat("0.0%");
sheet.getRange(`AT3:AT${rowCount}`).conditionalFormats.add("dataBar", {
  color: "#5B9BD5",
  gradient: false,
  thresholds: [{ type: "num", value: 0 }, { type: "num", value: 1 }],
});

const evaluationValues = Array.from({ length: rowCount }, () => Array(8).fill(null));
evaluationValues[0] = [
  "决策树校验", "Codex 校验", "决策树按时", "Codex 按时",
  "决策树是否改配", "Codex 是否改配", "推荐方案", "评价依据",
];
evaluationValues[1] = [
  "DecisionTreeValidation", "CodexValidation", "DecisionTreeOnTime", "CodexOnTime",
  "DecisionTreeChanged", "CodexChanged", "Recommendation", "EvaluationReason",
];

const isAssigned = (assignment) => assignment?.action === "assign";
const onTimeStatus = (assignment, heat) => {
  if (!isAssigned(assignment)) return "未分配";
  const arrival = Number(assignment.expected_arrival_seconds);
  const deadline = Number(heat?.window_end);
  return Number.isFinite(arrival) && Number.isFinite(deadline) && arrival <= deadline ? "是" : "否";
};
const delaySeconds = (assignment, heat) => {
  if (!isAssigned(assignment)) return Number.POSITIVE_INFINITY;
  const arrival = Number(assignment.expected_arrival_seconds);
  const deadline = Number(heat?.window_end);
  return Number.isFinite(arrival) && Number.isFinite(deadline) ? Math.max(0, arrival - deadline) : Number.POSITIVE_INFINITY;
};
const changedFromAp = (assignment, heatId) => {
  const ap = apAfterLocationMap.get(heatId);
  if (!ap || !assignment) return false;
  return String(ap.ladle_id ?? "") !== String(assignment.ladle_id ?? "")
    || String(ap.crane_id ?? "") !== String(assignment.crane_id ?? "");
};
const validationStatus = (assignment, label) => (
  isAssigned(assignment) ? "通过" : `失败｜${label}: ${assignment?.reason || "未返回可行分配"}`
);
const chooseRowRecommendation = (dt, codex, heat, dtChanged, codexChanged) => {
  const dtValid = isAssigned(dt);
  const codexValid = isAssigned(codex);
  if (!dtValid && !codexValid) return ["人工复核", "两条线路均未通过硬约束校验"];
  if (!dtValid) return ["Codex", "决策树校验失败，Codex 返回完整可行方案"];
  if (!codexValid) return ["决策树", "Codex 校验失败，决策树保留可行方案"];
  const dtOnTime = onTimeStatus(dt, heat) === "是";
  const codexOnTime = onTimeStatus(codex, heat) === "是";
  if (dtOnTime !== codexOnTime) return dtOnTime ? ["决策树", "两条线路均合法，决策树按时、Codex 未按时"] : ["Codex", "两条线路均合法，Codex 按时"];
  const dtDelay = delaySeconds(dt, heat);
  const codexDelay = delaySeconds(codex, heat);
  if (dtDelay !== codexDelay) return dtDelay < codexDelay ? ["决策树", "两条线路均按时，决策树延迟更低"] : ["Codex", "两条线路均按时，Codex 延迟更低"];
  if (dtChanged !== codexChanged) return dtChanged ? ["Codex", "服务指标相同，Codex 改配范围更小"] : ["决策树", "服务指标相同，决策树改配范围更小"];
  return ["持平", "两条线路在本炉次的校验、按时和改配指标相同"];
};

for (const heatId of affectedHeatIds) {
  const rowIndex = rowForHeat.get(heatId);
  if (rowIndex == null) throw new Error(`评价炉次未匹配 PLAN(1): ${heatId}`);
  const heat = stressHeats.get(heatId);
  const dt = decisionTreeAfterDisturbance.get(heatId);
  const codex = codexAfterDisturbance.get(heatId);
  if (!heat || !dt || !codex) throw new Error(`评价输入缺少炉次: ${heatId}`);
  const dtChanged = changedFromAp(dt, heatId);
  const codexChanged = changedFromAp(codex, heatId);
  const [recommendation, reason] = chooseRowRecommendation(dt, codex, heat, dtChanged, codexChanged);
  evaluationValues[rowIndex] = [
    validationStatus(dt, "决策树"), validationStatus(codex, "Codex"),
    onTimeStatus(dt, heat), onTimeStatus(codex, heat),
    dtChanged ? "是" : "否", codexChanged ? "是" : "否",
    recommendation, reason,
  ];
}

sheet.getRange(`AU1:BB${rowCount}`).values = evaluationValues;
sheet.getRange(`AU1:BB${rowCount}`).format.wrapText = true;
sheet.getRange(`AU1:BB${rowCount}`).format.verticalAlignment = "center";
sheet.getRange(`AU1:BB${rowCount}`).format.columnWidth = 18;
sheet.getRange(`BB1:BB${rowCount}`).format.columnWidth = 38;
sheet.getRange(`AU3:BB${rowCount}`).format.rowHeight = 24;
sheet.getRange("AU1:BB2").format = {
  fill: "#2F75B5",
  font: { bold: true, color: "#FFFFFF", name: "宋体", size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange(`AU3:BB${rowCount}`).conditionalFormats.add("containsText", {
  text: "Codex",
  format: { fill: "#E2F0D9", font: { color: "#375623", bold: true } },
});
sheet.getRange(`AU3:BB${rowCount}`).conditionalFormats.add("containsText", {
  text: "失败",
  format: { fill: "#FCE4D6", font: { color: "#9C0006" } },
});

const dtMetrics = stressAudit.decision_tree.metrics;
const codexMetrics = stressAudit.codex_llm.metrics;
const affectedCount = affectedHeatIds.size;
const dtComplete = stressAudit.decision_tree.num_assigned;
const codexComplete = stressAudit.codex_llm.num_assigned;
const globalRecommendation = stressAudit.decision_tree.success && !stressAudit.codex_llm.success
  ? "决策树"
  : !stressAudit.decision_tree.success && stressAudit.codex_llm.success ? "Codex" : "按指标复核";
const summaryRows = [
  ["指标", "决策树 AQ", "Codex AR"],
  ["受影响炉次", affectedCount, affectedCount],
  ["完整配包数", dtComplete, codexComplete],
  ["完成率", dtComplete / affectedCount, codexComplete / affectedCount],
  ["按时率", dtMetrics.on_time_rate, codexMetrics.on_time_rate],
  ["平均延迟（秒）", dtMetrics.average_delay_seconds, codexMetrics.average_delay_seconds],
  ["最大延迟（秒）", dtMetrics.max_delay_seconds, codexMetrics.max_delay_seconds],
  ["硬约束违规数", dtMetrics.rule_violations, codexMetrics.rule_violations],
  ["相对 AP 改配炉次数", dtMetrics.changed_heats, codexMetrics.changed_heats],
  ["离线决策耗时（秒）", stressAudit.decision_tree.elapsed_seconds, stressAudit.codex_llm.elapsed_seconds],
  ["最终推荐", globalRecommendation, globalRecommendation],
];
let summarySheet;
try {
  summarySheet = workbook.worksheets.getItem("对比汇总");
  summarySheet.getUsedRange().clear({ applyTo: "all" });
} catch {
  summarySheet = workbook.worksheets.add("对比汇总");
}
summarySheet.showGridLines = false;
summarySheet.getRange("A1:C1").merge();
summarySheet.getRange("A1:C1").values = [["AP 基线双线路扰动对比汇总"]];
summarySheet.getRange("A2:C2").merge();
summarySheet.getRange("A2:C2").values = [["真实位置映射审计｜11:00-11:20｜31 炉｜行车 2500 离线 + 受控路线约束"]];
summarySheet.getRange(`A4:C${3 + summaryRows.length}`).values = summaryRows;
summarySheet.getRange("A1:C1").format = { fill: "#1F4E78", font: { bold: true, color: "#FFFFFF", name: "宋体", size: 14 }, horizontalAlignment: "center", verticalAlignment: "center" };
summarySheet.getRange("A2:C2").format = { fill: "#D9EAF7", font: { color: "#1F1F1F", name: "宋体", size: 10 }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
summarySheet.getRange("A4:C4").format = { fill: "#5B9BD5", font: { bold: true, color: "#FFFFFF", name: "宋体", size: 11 }, horizontalAlignment: "center", verticalAlignment: "center" };
summarySheet.getRange(`A5:A${3 + summaryRows.length}`).format.font = { bold: true, name: "宋体", size: 10 };
summarySheet.getRange(`A4:C${3 + summaryRows.length}`).format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
summarySheet.getRange(`A5:C${3 + summaryRows.length}`).format.verticalAlignment = "center";
summarySheet.getRange("A1:C2").format.rowHeight = 26;
summarySheet.getRange(`A4:C${3 + summaryRows.length}`).format.rowHeight = 22;
summarySheet.getRange("A1:A14").format.columnWidth = 26;
summarySheet.getRange("B1:C14").format.columnWidth = 18;
summarySheet.getRange("B7:C8").setNumberFormat("0.0%");
summarySheet.getRange("B9:C10").setNumberFormat("0.0");
summarySheet.getRange(`B5:C${3 + summaryRows.length}`).format.horizontalAlignment = "right";
summarySheet.getRange("B14:C14").format.horizontalAlignment = "center";
summarySheet.getRange("B14:C14").format.font = { bold: true, color: "#375623", name: "宋体", size: 11 };
summarySheet.freezePanes.freezeRows(4);

const afterValues = sheet.getUsedRange().values;
let changedCells = 0;
for (let row = 0; row < originalAtoAO.length; row += 1) {
  for (let column = 0; column < 41; column += 1) {
    if (column === 38 || column === 39) continue;
    if (JSON.stringify(originalAtoAO[row][column]) !== JSON.stringify(afterValues[row][column] ?? null)) changedCells += 1;
  }
}
if (changedCells !== 0) throw new Error(`除 AM/AN 旧版列外，原有 A:AO 被改变，差异单元格=${changedCells}`);
const clearedLegacyCells = afterValues.slice(0, rowCount).reduce(
  (count, row) => count + (row[38] == null && row[39] == null ? 2 : 0),
  0,
);
if (clearedLegacyCells !== rowCount * 2) throw new Error(`AM/AN 旧版列未完全清除，空单元格=${clearedLegacyCells}`);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!",
  options: { useRegex: true, maxResults: 100 },
  summary: "location-aware workbook formula error scan",
});
if (errors.ndjson.includes('"kind":"match"')) throw new Error(`公式错误扫描失败: ${errors.ndjson}`);

const assigned = outputValues.slice(2).filter(([value]) => String(value).startsWith("已分配"));
const missing = outputValues.slice(2).filter(([value]) => !value);
if (assigned.length !== audit.assignment_rows.filter((row) => row.status === "已分配").length || missing.length) {
  throw new Error(`AP 结果校验失败：已分配=${assigned.length}，空值=${missing.length}`);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
const preview = await workbook.render({ sheetName: sheet.name, range: "AO1:BB18", scale: 1.5, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
console.log(JSON.stringify({
  inputPath,
  outputPath,
  auditPath,
  stressAuditPath,
  sheet: sheet.name,
  usedRange: `A1:BB${rowCount}`,
  sourceColumnCount,
  clearedColumns: ["AM", "AN"],
  appendedColumns: ["AP", "AQ", "AR", "AS:AT 行车位置", "AU:BB 评价"],
  evaluatedRows: audit.assignment_rows.length,
  assignedRows: assigned.length,
  affectedHeatCount: affectedHeatIds.size,
  matchedAffected,
  decisionTreeAssigned,
  codexAssigned,
  summarySheet: summarySheet.name,
  excludedRows: outputValues.slice(2).filter(([value]) => String(value).includes("未纳入")).length,
  changedCellsAtoAO: changedCells,
  formulaErrors: errors.ndjson,
  previewPath,
}));
