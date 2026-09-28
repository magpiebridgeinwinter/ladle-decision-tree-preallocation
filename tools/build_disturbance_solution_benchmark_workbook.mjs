import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = process.argv[2] || "outputs/disturbance_solution_benchmark/benchmark.json";
const outputPath = process.argv[3] || "outputs/disturbance_solution_benchmark/钢包扰动重调度双线路评价.xlsx";
const previewDir = process.argv[4] || "/private/tmp/ladle_benchmark_previews";
const benchmark = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const font = "Arial";
const navy = "#1F4E78";
const blue = "#4472C4";
const lightBlue = "#D9EAF7";
const green = "#E2F0D9";
const amber = "#FFF2CC";
const red = "#FCE4D6";
const gray = "#F2F2F2";
const border = "#D9E2F3";

const colLetter = (index) => {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
};

const writeMatrix = (sheet, startRow, matrix) => {
  const columns = Math.max(...matrix.map((row) => row.length));
  const padded = matrix.map((row) => [...row, ...Array(columns - row.length).fill(null)]);
  sheet.getRangeByIndexes(startRow, 0, padded.length, columns).values = padded;
  return { rows: padded.length, columns };
};

const styleTitle = (sheet, width, title, subtitle) => {
  const end = colLetter(width - 1);
  sheet.getRange(`A1:${end}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A2:${end}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A1:${end}1`).format = {
    font: { name: font, size: 16, bold: true, color: "#1F1F1F" },
    verticalAlignment: "center",
  };
  sheet.getRange(`A2:${end}2`).format = {
    font: { name: font, size: 10, italic: true, color: "#666666" },
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange(`A1:${end}1`).format.rowHeight = 28;
  sheet.getRange(`A2:${end}2`).format.rowHeight = 34;
};

const styleTable = (sheet, headerRow, dataEndRow, width) => {
  const end = colLetter(width - 1);
  sheet.getRange(`A${headerRow}:${end}${headerRow}`).format = {
    fill: navy,
    font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#FFFFFF" },
  };
  sheet.getRange(`A${headerRow + 1}:${end}${dataEndRow}`).format = {
    font: { name: font, size: 9, color: "#1F1F1F" },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: border },
  };
  sheet.getRange(`A${headerRow}:${end}${dataEndRow}`).format.rowHeight = 24;
};

const summary = benchmark.summary;
const summarySheet = workbook.worksheets.add("实验汇总");
summarySheet.showGridLines = false;
styleTitle(
  summarySheet,
  10,
  "钢包扰动重调度双线路评价",
  "同一位置映射 AP 基线、同一扰动快照和同一硬约束下，比较 AQ 决策树与 AR Codex。事故为真实数据派生的受控输入。",
);
const overview = [
  ["指标", "结果", "说明"],
  ["受控扰动场景", summary.scenario_count, "覆盖 v1 扰动目录全部类型"],
  ["31 炉主场景", summary.primary_31_heat_scenario_count, "行车离线；决策树 30/31，Codex 31/31"],
  ["动态局部窗口", summary.dynamic_local_window_scenario_count, "受影响炉次数量由 PLAN/CRANE/loc_location 计算"],
  ["受影响炉次观察", summary.heat_observation_count, `共 ${summary.unique_heat_count} 个唯一炉次`],
  ["AQ 可执行场景", summary.decision_tree_executable_count, "必须同时满足完整性与全部硬约束"],
  ["AR 可执行场景", summary.codex_executable_count, "离线审计候选，external_api_called=false"],
  ["推荐 Codex", summary.recommendation_counts.codex || 0, "按硬门槛优先的确定性规则"],
  ["工厂钢包可比观察", summary.factory_ladle_observation_count, `共 ${summary.factory_ladle_unique_heat_count} 个唯一炉次；AP/AQ/AR 一致率均为 0%`],
];
writeMatrix(summarySheet, 3, overview);
styleTable(summarySheet, 4, 12, 3);
summarySheet.getRange("A4:A12").format.columnWidth = 24;
summarySheet.getRange("B4:B12").format.columnWidth = 16;
summarySheet.getRange("C4:C12").format.columnWidth = 55;
summarySheet.getRange("B5:B12").setNumberFormat("#,##0");

const groupRows = [
  ["扰动分组", "场景数", "AQ 可执行", "AR 可执行", "推荐 Codex"],
  ...Object.entries(summary.group_results).map(([group, value]) => [
    group,
    value.scenario_count,
    value.decision_tree_executable_count,
    value.codex_executable_count,
    value.recommendation_counts.codex || 0,
  ]),
];
writeMatrix(summarySheet, 13, groupRows);
styleTable(summarySheet, 14, 13 + groupRows.length, 5);
summarySheet.getRange("A14:A22").format.columnWidth = 24;
summarySheet.getRange("B14:E22").format.columnWidth = 15;
summarySheet.getRange("B15:E22").setNumberFormat("#,##0");

const evidenceRows = [
  ["证据边界", "内容"],
  ["真实数据", benchmark.evidence_boundary.source_backed],
  ["受控输入", benchmark.evidence_boundary.controlled],
  ["Codex 结果", benchmark.evidence_boundary.codex],
  ["结论边界", benchmark.evidence_boundary.claim_limit],
  ["工厂可比字段", `PLAN preallocated_ladle；有效记录 ${benchmark.factory_reference.valid_factory_ladle_count || 0} 条`],
  ["工厂不可比字段", "天车任务、事故后人工重排、现场执行结果均未提供"],
];
writeMatrix(summarySheet, 24, evidenceRows);
styleTable(summarySheet, 25, 24 + evidenceRows.length, 2);
summarySheet.getRange("A25:A31").format.columnWidth = 24;
summarySheet.getRange("B25:B31").format.columnWidth = 85;
summarySheet.getRange("A26:B31").format.rowHeight = 34;
summarySheet.freezePanes.freezeRows(4);

const scenarioSheet = workbook.worksheets.add("场景明细");
scenarioSheet.showGridLines = false;
const scenarioHeaders = [
  "序号", "场景编号", "扰动", "分组", "规模", "炉次数",
  "AQ可执行", "AQ完成率", "AQ失败门槛", "AQ按时率", "AQ平均延迟(s)", "AQ最大延迟(s)", "AQ改配炉次", "AQ资源变化",
  "AR可执行", "AR完成率", "AR按时率", "AR平均延迟(s)", "AR最大延迟(s)", "AR改配炉次", "AR资源变化",
  "工厂样本", "AP钢包一致率", "AQ钢包一致率", "AR钢包一致率", "推荐", "评价依据",
];
styleTitle(scenarioSheet, scenarioHeaders.length, "场景明细", "每个场景先判断可执行性，再比较服务效果和计划稳定性；工厂钢包一致率不参与可执行性判定。" );
const scenarioRows = benchmark.scenarios.map((scenario, index) => {
  const aq = scenario.branches.decision_tree;
  const ar = scenario.branches.codex;
  const factory = scenario.factory_comparison.ladle;
  return [
    index + 1, scenario.scenario_id, scenario.title, scenario.disturbance_group,
    scenario.scenario_size_class === "primary_31_heat" ? "31炉主场景" : "动态局部窗口",
    scenario.affected_heat_count,
    aq.executable ? "是" : "否", aq.metrics.completion_rate, aq.failed_hard_gates.join("；"), aq.metrics.on_time_rate,
    aq.metrics.average_delay_seconds, aq.metrics.max_delay_seconds, aq.metrics.changed_heat_count, aq.metrics.resource_change_count,
    ar.executable ? "是" : "否", ar.metrics.completion_rate, ar.metrics.on_time_rate,
    ar.metrics.average_delay_seconds, ar.metrics.max_delay_seconds, ar.metrics.changed_heat_count, ar.metrics.resource_change_count,
    factory.sample_count, factory.ap_agreement_rate, factory.aq_agreement_rate, factory.ar_agreement_rate,
    scenario.recommendation_label, scenario.recommendation_reason,
  ];
});
writeMatrix(scenarioSheet, 3, [scenarioHeaders, ...scenarioRows]);
styleTable(scenarioSheet, 4, 4 + scenarioRows.length, scenarioHeaders.length);
scenarioSheet.getRange(`A5:A${4 + scenarioRows.length}`).setNumberFormat("#,##0");
scenarioSheet.getRange(`F5:F${4 + scenarioRows.length}`).setNumberFormat("#,##0");
for (const column of [7, 9, 15, 22, 23, 24]) {
  const letter = colLetter(column);
  scenarioSheet.getRange(`${letter}5:${letter}${4 + scenarioRows.length}`).setNumberFormat("0.0%");
}
for (const column of [10, 11, 17, 18]) {
  const letter = colLetter(column);
  scenarioSheet.getRange(`${letter}5:${letter}${4 + scenarioRows.length}`).setNumberFormat("#,##0.0");
}
scenarioSheet.getRange(`G5:G${4 + scenarioRows.length}`).conditionalFormats.add("containsText", { text: "否", format: { fill: red, font: { color: "#9C0006" } } });
scenarioSheet.getRange(`O5:O${4 + scenarioRows.length}`).conditionalFormats.add("containsText", { text: "是", format: { fill: green, font: { color: "#006100" } } });
scenarioSheet.getRange(`Z5:Z${4 + scenarioRows.length}`).conditionalFormats.add("containsText", { text: "Codex", format: { fill: lightBlue, font: { bold: true, color: navy } } });
const scenarioWidths = [8, 38, 24, 18, 18, 10, 12, 12, 30, 12, 16, 16, 14, 14, 12, 12, 12, 16, 16, 14, 14, 12, 16, 16, 16, 12, 62];
scenarioWidths.forEach((width, index) => { scenarioSheet.getRange(`${colLetter(index)}4:${colLetter(index)}${4 + scenarioRows.length}`).format.columnWidth = width; });
scenarioSheet.freezePanes.freezeRows(4);
scenarioSheet.freezePanes.freezeColumns(2);

const heatSheet = workbook.worksheets.add("炉次明细");
heatSheet.showGridLines = false;
const heatHeaders = [
  "场景编号", "扰动", "炉次", "工厂钢包", "可比",
  "AP钢包", "AP行车", "AP路线", "AP同工厂",
  "AQ状态", "AQ钢包", "AQ行车", "AQ路线", "AQ改配", "AQ同工厂", "AQ违规",
  "AR状态", "AR钢包", "AR行车", "AR路线", "AR改配", "AR同工厂", "AR违规",
];
styleTitle(heatSheet, heatHeaders.length, "炉次明细", "每行对应一个场景中的受影响炉次。改配只比较钢包与行车；路线变化单独保留在路线列。" );
const heatRows = benchmark.scenarios.flatMap((scenario) => scenario.heat_results.map((row) => [
  row.scenario_id, row.disturbance_kind, row.heat_id, row.factory_ladle_id, row.factory_comparison_available ? "是" : "否",
  row.ap_ladle_id, row.ap_crane_id, row.ap_refining_route, row.ap_matches_factory_ladle == null ? null : (row.ap_matches_factory_ladle ? "是" : "否"),
  row.aq_action, row.aq_ladle_id, row.aq_crane_id, row.aq_refining_route, row.aq_changed_from_ap ? "是" : "否",
  row.aq_matches_factory_ladle == null ? null : (row.aq_matches_factory_ladle ? "是" : "否"), row.aq_violations.join("；"),
  row.ar_action, row.ar_ladle_id, row.ar_crane_id, row.ar_refining_route, row.ar_changed_from_ap ? "是" : "否",
  row.ar_matches_factory_ladle == null ? null : (row.ar_matches_factory_ladle ? "是" : "否"), row.ar_violations.join("；"),
]));
writeMatrix(heatSheet, 3, [heatHeaders, ...heatRows]);
styleTable(heatSheet, 4, 4 + heatRows.length, heatHeaders.length);
const heatWidths = [38, 26, 26, 12, 10, 12, 12, 12, 12, 14, 12, 12, 12, 12, 12, 28, 14, 12, 12, 12, 12, 12, 28];
heatWidths.forEach((width, index) => { heatSheet.getRange(`${colLetter(index)}4:${colLetter(index)}${4 + heatRows.length}`).format.columnWidth = width; });
heatSheet.getRange(`N5:N${4 + heatRows.length}`).conditionalFormats.add("containsText", { text: "是", format: { fill: amber, font: { color: "#7F6000" } } });
heatSheet.getRange(`U5:U${4 + heatRows.length}`).conditionalFormats.add("containsText", { text: "是", format: { fill: lightBlue, font: { color: navy } } });
heatSheet.freezePanes.freezeRows(4);
heatSheet.freezePanes.freezeColumns(3);

const definitionSheet = workbook.worksheets.add("指标说明");
definitionSheet.showGridLines = false;
styleTitle(definitionSheet, 5, "指标说明", "可执行性是硬门槛；只有两条线路都可执行时，才按顺序比较服务效果和计划稳定性。" );
const definitions = [
  ["类别", "指标", "定义", "判定/方向", "备注"],
  ["硬门槛", "完整配包", "所有受影响炉次各有且仅有一条有效分配", "必须 100%", "缺失、重复或未分配均失败"],
  ["硬门槛", "共享校验", "位置、资源、负载、安全距离、路线和场景策略", "全部通过", "AQ 与 AR 使用同一校验器"],
  ["硬门槛", "范围保护", "不修改锁定炉次或影响范围外炉次", "修改数必须 0", "局部重排边界"],
  ["硬门槛", "资源可用", "钢包和行车必须存在于扰动后的候选资源", "未知/不可用必须 0", "事故资源不得继续使用"],
  ["效果", "完成率", "已分配炉次 / 受影响炉次", "越高越好", "硬门槛后仍保留用于解释"],
  ["效果", "按时率", "时间窗结束前完成运输的炉次比例", "越高越好", "排序第 1 项"],
  ["效果", "平均延迟", "逐炉 max(预计到达 - 窗口结束, 0) 的平均值", "越低越好", "排序第 2 项"],
  ["效果", "最大延迟", "所有受影响炉次延迟最大值", "越低越好", "排序第 3 项"],
  ["稳定性", "改配炉次数", "相对 AP 改变钢包或行车的炉次数", "越少越好", "路线变化单独记录"],
  ["稳定性", "资源变化数", "钢包、行车、路线字段变化总数", "越少越好", "排序第 5 项"],
  ["稳定性", "行车负载离散度", "候选行车任务数的总体方差", "越低越好", "排序第 6 项"],
  ["诊断", "工厂钢包一致率", "与 PLAN preallocated_ladle 相同的炉次 / 有效样本", "仅展示", "不参与可执行性和推荐"],
  ["边界", "外部 API", "本批实验是否实时请求大模型", "false", "Codex 方案为离线审计结果"],
];
writeMatrix(definitionSheet, 3, definitions);
styleTable(definitionSheet, 4, 3 + definitions.length, 5);
definitionSheet.getRange("A4:A17").format.columnWidth = 14;
definitionSheet.getRange("B4:B17").format.columnWidth = 24;
definitionSheet.getRange("C4:C17").format.columnWidth = 62;
definitionSheet.getRange("D4:D17").format.columnWidth = 20;
definitionSheet.getRange("E4:E17").format.columnWidth = 42;
definitionSheet.getRange("A5:E17").format.rowHeight = 34;
definitionSheet.freezePanes.freezeRows(4);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
if (errors.ndjson.includes('"kind":"match"')) {
  throw new Error(`formula errors found: ${errors.ndjson}`);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
for (const sheetName of ["实验汇总", "场景明细", "炉次明细", "指标说明"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const summaryInspect = await workbook.inspect({
  kind: "table",
  sheetId: "实验汇总",
  range: "A1:J31",
  include: "values,formulas",
  tableMaxRows: 35,
  tableMaxCols: 12,
});
const scenarioInspect = await workbook.inspect({
  kind: "table",
  sheetId: "场景明细",
  range: "A1:AA24",
  include: "values,formulas",
  tableMaxRows: 25,
  tableMaxCols: 28,
});
console.log(JSON.stringify({
  outputPath,
  sheets: ["实验汇总", "场景明细", "炉次明细", "指标说明"],
  scenarioCount: benchmark.scenarios.length,
  heatObservationCount: summary.heat_observation_count,
  errorScan: errors.ndjson,
  summaryInspect: summaryInspect.ndjson,
  scenarioInspect: scenarioInspect.ndjson,
  previewDir,
}, null, 2));
