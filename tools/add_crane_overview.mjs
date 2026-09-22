import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2] || "outputs/PLAN(1)_位置映射决策树预配包结果_含行车位置.xlsx";
const auditPath = process.argv[3] || "outputs/real_data_location_aware/decision_tree_audit.json";
const outputPath = process.argv[4] || "outputs/PLAN(1)_位置映射决策树预配包结果_含天车总览.xlsx";
const previewPath = process.argv[5] || "/private/tmp/crane_overview_preview.png";

const audit = JSON.parse(await fs.readFile(auditPath, "utf8"));
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const font = "宋体";
const cranes = [...audit.scheduling_inputs.cranes].sort((left, right) => String(left.crane_id).localeCompare(String(right.crane_id)));
const craneIds = cranes.map((item) => String(item.crane_id));
const craneById = new Map(cranes.map((item) => [String(item.crane_id), item]));
const ladleById = new Map(audit.scheduling_inputs.ladles.map((item) => [String(item.ladle_id), item]));
const assignmentByHeat = new Map(audit.assignments.map((item) => [String(item.heat_id), item]));
const heats = [...audit.scheduling_inputs.heats].sort((left, right) => Number(left.pour_at) - Number(right.pour_at));

const formatTime = (seconds) => new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
}).format(new Date(Number(seconds) * 1000)).replaceAll("/", "-");

const formatSnapshotTime = (value) => String(value || "")
  .replace(/^(\d{4}-\d{2}-\d{2})-(\d{2})\.(\d{2}).*$/, "$1 $2:$3");

const initialPosition = new Map(cranes.map((item) => [String(item.crane_id), Number(item.position_m)]));
const currentPosition = new Map(initialPosition);
const taskCounts = new Map(craneIds.map((id) => [id, 0]));
const firstTask = new Map();
const lastTask = new Map();

const trajectoryRows = [["生产开始", ...craneIds]];
trajectoryRows.push([formatTime(heats[0].pour_at), ...craneIds.map((id) => initialPosition.get(id))]);
for (const heat of heats) {
  const assignment = assignmentByHeat.get(String(heat.heat_id));
  if (assignment?.action === "assign") {
    const craneId = String(assignment.crane_id);
    const ladle = ladleById.get(String(assignment.ladle_id));
    const targetPosition = Number(ladle?.position_m);
    if (currentPosition.has(craneId) && Number.isFinite(targetPosition)) {
      currentPosition.set(craneId, targetPosition);
      taskCounts.set(craneId, (taskCounts.get(craneId) || 0) + 1);
      if (!firstTask.has(craneId)) firstTask.set(craneId, Number(heat.pour_at));
      lastTask.set(craneId, Number(heat.pour_at));
    }
  }
  trajectoryRows.push([formatTime(heat.pour_at), ...craneIds.map((id) => currentPosition.get(id))]);
}

const summaryRows = [
  ["行车", "快照时刻", "起始位置 X", "计划终点 X", "作业范围", "预配任务数", "首次计划服务", "最后计划服务"],
  ...cranes.map((crane) => {
    const id = String(crane.crane_id);
    const lower = Number(crane.limit_0_m);
    const upper = Number(crane.limit_1_m);
    return [
      id,
      formatSnapshotTime(crane.source_updated_at),
      initialPosition.get(id),
      currentPosition.get(id),
      `${Math.round(lower).toLocaleString("en-US")}–${Math.round(upper).toLocaleString("en-US")}`,
      taskCounts.get(id) || 0,
      firstTask.has(id) ? formatTime(firstTask.get(id)) : "无预配任务",
      lastTask.has(id) ? formatTime(lastTask.get(id)) : "无预配任务",
    ];
  }),
];

let sheet;
try {
  sheet = workbook.worksheets.getItem("天车位置总览");
  sheet.charts.deleteAll();
  sheet.getUsedRange().clear({ applyTo: "all" });
} catch {
  sheet = workbook.worksheets.add("天车位置总览");
}

sheet.showGridLines = false;
sheet.getRange("A1:L1").merge();
sheet.getRange("A1").values = [["天车位置总览"]];
sheet.getRange("A2:L2").merge();
sheet.getRange("A2").values = [[
  `生产计划 ${formatTime(heats[0].pour_at)} 至 ${formatTime(heats.at(-1).pour_at)}｜CRANE 起始快照 + 决策树预配任务`,
]];
sheet.getRange("A3:L3").merge();
sheet.getRange("A3").values = [[
  "图示含义：按预配任务顺序更新行车服务位置。允许多台行车作为独立资源被同时分配；未包含真实运行时间、加速度、任务占用或多车避碰。",
]];
sheet.getRange("A1:L1").format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF", name: font, size: 16 },
  horizontalAlignment: "left",
  verticalAlignment: "center",
};
sheet.getRange("A2:L2").format = {
  fill: "#D9EAF7",
  font: { color: "#1F1F1F", name: font, size: 10 },
  verticalAlignment: "center",
};
sheet.getRange("A3:L3").format = {
  fill: "#FFF2CC",
  font: { color: "#7F6000", name: font, size: 10 },
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange("A1:L1").format.rowHeight = 28;
sheet.getRange("A2:L2").format.rowHeight = 22;
sheet.getRange("A3:L3").format.rowHeight = 32;

sheet.getRange(`A5:H${4 + summaryRows.length}`).values = summaryRows;
sheet.getRange("A5:H5").format = {
  fill: "#4472C4",
  font: { bold: true, color: "#FFFFFF", name: font, size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
sheet.getRange(`A6:H${4 + summaryRows.length}`).format = {
  font: { name: font, size: 10, color: "#1F1F1F" },
  verticalAlignment: "center",
};
sheet.getRange(`A5:H${4 + summaryRows.length}`).format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
sheet.getRange(`A6:D${4 + summaryRows.length}`).format.horizontalAlignment = "center";
sheet.getRange(`E6:H${4 + summaryRows.length}`).format.horizontalAlignment = "center";
sheet.getRange(`C6:D${4 + summaryRows.length}`).setNumberFormat("#,##0");
sheet.getRange(`F6:F${4 + summaryRows.length}`).setNumberFormat("#,##0");
sheet.getRange("A5:A15").format.columnWidth = 11;
sheet.getRange("B5:B15").format.columnWidth = 25;
sheet.getRange("C5:D15").format.columnWidth = 13;
sheet.getRange("E5:E15").format.columnWidth = 18;
sheet.getRange("F5:F15").format.columnWidth = 12;
sheet.getRange("G5:H15").format.columnWidth = 21;
sheet.getRange(`C6:C${4 + summaryRows.length}`).conditionalFormats.add("dataBar", {
  color: "#A5A5A5",
  gradient: false,
  thresholds: [{ type: "num", value: 0 }, { type: "num", value: 48000 }],
});
sheet.getRange(`D6:D${4 + summaryRows.length}`).conditionalFormats.add("dataBar", {
  color: "#5B9BD5",
  gradient: false,
  thresholds: [{ type: "num", value: 0 }, { type: "num", value: 48000 }],
});

const timelineHeaderRow = 18;
const timelineStartRow = timelineHeaderRow + 1;
const timelineEndRow = timelineHeaderRow + trajectoryRows.length - 1;
sheet.getRange(`A${timelineHeaderRow}:K${timelineEndRow}`).values = trajectoryRows;
sheet.getRange(`A${timelineHeaderRow}:K${timelineHeaderRow}`).format = {
  fill: "#4472C4",
  font: { bold: true, color: "#FFFFFF", name: font, size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
sheet.getRange(`A${timelineStartRow}:K${timelineEndRow}`).format = {
  font: { name: font, size: 9, color: "#1F1F1F" },
  verticalAlignment: "center",
};
sheet.getRange(`A${timelineStartRow}:A${timelineEndRow}`).format.columnWidth = 20;
sheet.getRange(`B${timelineStartRow}:K${timelineEndRow}`).format.columnWidth = 12;
sheet.getRange(`B${timelineStartRow}:K${timelineEndRow}`).setNumberFormat("#,##0");
sheet.getRange(`A${timelineHeaderRow}:K${timelineEndRow}`).format.borders = { preset: "all", style: "thin", color: "#E6EEF7" };
sheet.getRange(`A${timelineStartRow}:K${timelineEndRow}`).format.rowHeight = 18;

const seriesColors = ["#4472C4", "#A5A5A5", "#ED7D31", "#70AD47", "#5B9BD5", "#FFC000", "#8064A2", "#C55A11", "#264478", "#548235"];
const chart = sheet.charts.add("line", { from: { row: 1, col: 12 }, extent: { widthPx: 920, heightPx: 500 } });
chart.categories = trajectoryRows.slice(1).map((row) => row[0]);
for (const [index, craneId] of craneIds.entries()) {
  const series = chart.series.add(`行车 ${craneId}`);
  series.categories = chart.categories;
  series.values = trajectoryRows.slice(1).map((row) => row[index + 1]);
  series.line = { fill: seriesColors[index], style: "solid", width: 1.5 };
}
chart.title = "预配任务顺序下的天车 X 位置推演（0–48,000）";
chart.titleTextStyle.typeface = font;
chart.titleTextStyle.fontSize = 13;
chart.legend = { position: "top", textStyle: { typeface: font, fontSize: 9 } };
chart.xAxis = { axisType: "textAxis", textStyle: { typeface: font, fontSize: 8 } };
chart.yAxis = {
  numberFormatCode: "#,##0",
  numberFormatSourceLinked: false,
  textStyle: { typeface: font, fontSize: 9 },
};
chart.setPosition("M2", "AD25");

sheet.freezePanes.freezeRows(5);

const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 200 },
  summary: "crane overview formula error scan",
});
if (errorScan.ndjson.includes('"kind":"match"')) {
  throw new Error(`公式错误扫描失败: ${errorScan.ndjson}`);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
const preview = await workbook.render({ sheetName: sheet.name, range: "A1:AD26", scale: 1.25, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

console.log(JSON.stringify({
  inputPath,
  outputPath,
  sheet: sheet.name,
  craneCount: cranes.length,
  heatCount: heats.length,
  timelineRows: trajectoryRows.length - 1,
  productionStart: formatTime(heats[0].pour_at),
  productionEnd: formatTime(heats.at(-1).pour_at),
  taskCounts: Object.fromEntries(taskCounts),
  errorScan: errorScan.ndjson,
  previewPath,
}));
