import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const [planPath, auditPath, workbookPath, csvPath, previewDir] = process.argv.slice(2);
if (!planPath || !auditPath || !workbookPath || !csvPath) {
  throw new Error('usage: node build_outputs.mjs <PLAN.xlsx> <audit.json> <result.xlsx> <result.csv> [preview-dir]');
}

const audit = JSON.parse(await fs.readFile(auditPath, 'utf8'));
if (audit.algorithm !== 'decision_tree') throw new Error(`unsupported algorithm: ${audit.algorithm}`);

const csvColumns = [
  ['炉次主键', 'plan_key'],
  ['出钢记号', 'heat_id'],
  ['计划顺序号', 'plan_sequence'],
  ['方法', 'algorithm'],
  ['分配状态', 'status'],
  ['钢包号', 'ladle_id'],
  ['真实行车号', 'crane_id'],
  ['预计等待时间(秒)', 'expected_wait_seconds'],
  ['等级匹配', 'grade_match'],
  ['硬约束违反', 'violations'],
  ['分配原因', 'reason'],
  ['决策路径', 'decision_path'],
];
const csvMatrix = [csvColumns.map(([label]) => label)];
for (const row of audit.assignment_rows) {
  csvMatrix.push(csvColumns.map(([, key]) => row[key] ?? ''));
}
const csvText = csvMatrix.map((row) => row.map(csvCell).join(',')).join('\r\n');
await fs.mkdir(path.dirname(csvPath), { recursive: true });
await fs.writeFile(csvPath, `\uFEFF${csvText}`, 'utf8');

const csvWorkbook = await Workbook.fromCSV(csvText, { sheetName: '决策树结果' });
const csvSheet = csvWorkbook.worksheets.getItem('决策树结果');
csvSheet.freezePanes.freezeRows(1);
csvSheet.showGridLines = false;
csvSheet.getRange(`A1:L${csvMatrix.length}`).format.font = { name: 'Microsoft YaHei', size: 10 };
csvSheet.getRange('A1:L1').format = {
  fill: '#1F4E78',
  font: { bold: true, color: '#FFFFFF', name: 'Microsoft YaHei', size: 10 },
  wrapText: true,
  verticalAlignment: 'center',
};
csvSheet.getRange('A1:L1').format.rowHeight = 30;
csvSheet.getRange(`C2:C${csvMatrix.length}`).format.numberFormat = '0';
csvSheet.getRange(`H2:H${csvMatrix.length}`).format.numberFormat = '0.000';
csvSheet.getRange(`A1:L${csvMatrix.length}`).format.borders = {
  preset: 'insideHorizontal', style: 'thin', color: '#D9E2F3',
};
const widths = [26, 15, 14, 14, 12, 10, 14, 18, 12, 18, 44, 58];
for (let index = 0; index < widths.length; index += 1) {
  csvSheet.getRangeByIndexes(0, index, csvMatrix.length, 1).format.columnWidth = widths[index];
}
csvSheet.getRange(`I2:I${csvMatrix.length}`).format.horizontalAlignment = 'center';
csvSheet.getRange(`J2:L${csvMatrix.length}`).format.wrapText = true;

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(planPath));
const sheet = workbook.worksheets.getItem('PLAN_TAPPING - 副本');
const values = sheet.getUsedRange().values;
const byKey = new Map(audit.plan_output_rows.map((row) => [row.plan_key, row.result]));
const resultValues = [['决策树分配结果'], ['decision_tree_allocation']];
for (let rowIndex = 2; rowIndex < values.length; rowIndex += 1) {
  const row = values[rowIndex];
  const key = `${String(row[2] ?? '').trim()}::${String(row[0] ?? '').trim()}`;
  resultValues.push([byKey.get(key) ?? '状态=人工复核；原因=炉次主键未匹配']);
}
const lastColumn = values[0].length;
const destination = sheet.getRangeByIndexes(0, lastColumn, resultValues.length, 1);
destination.copyFrom(sheet.getRangeByIndexes(0, lastColumn - 1, resultValues.length, 1), 'all');
destination.values = resultValues;
destination.format.columnWidth = 48;
destination.format.wrapText = true;
destination.format.verticalAlignment = 'center';
sheet.getRangeByIndexes(0, lastColumn, 2, 1).format = {
  fill: '#1F4E78',
  font: { bold: true, color: '#FFFFFF', name: '宋体', size: 11 },
  horizontalAlignment: 'center',
  verticalAlignment: 'center',
  wrapText: true,
};
sheet.getRangeByIndexes(2, lastColumn, resultValues.length - 2, 1).format.rowHeight = 30;
sheet.freezePanes.freezeRows(2);

await fs.mkdir(path.dirname(workbookPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(workbookPath);

const check = await workbook.inspect({
  kind: 'table',
  sheetId: 'PLAN_TAPPING - 副本',
  range: `${columnName(lastColumn + 1)}1:${columnName(lastColumn + 1)}${resultValues.length}`,
  include: 'values,formulas',
  tableMaxRows: 8,
  tableMaxCols: 1,
  maxChars: 6000,
});
const errors = await workbook.inspect({
  kind: 'match',
  searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',
  options: { useRegex: true, maxResults: 100 },
  summary: 'final formula error scan',
});
const resultText = resultValues.slice(2).map(([value]) => String(value));
const assigned = resultText.filter((value) => value.includes('状态=已分配'));
const blank = resultText.filter((value) => !value);
const allowedCraneIds = new Set(audit.real_crane_ids.map(String));
const untraceable = assigned.filter((value) => {
  const match = value.match(/行车=([^;；]+)/);
  return !match || !allowedCraneIds.has(match[1].trim());
});
const csvAssigned = audit.assignment_rows.filter((row) => row.status === '已分配');
if (
  resultValues.length !== audit.plan_output_rows.length + 2
  || csvMatrix.length !== audit.assignment_rows.length + 1
  || blank.length
  || untraceable.length
  || csvAssigned.length !== audit.assignments.filter((row) => row.action === 'assign').length
  || errors.ndjson.includes('"kind":"match"')
) {
  throw new Error(`output verification failed: planRows=${resultValues.length - 2}, csvRows=${csvMatrix.length - 1}, blank=${blank.length}, untraceable=${untraceable.length}`);
}

if (previewDir) {
  await fs.mkdir(previewDir, { recursive: true });
  const startColumn = Math.max(0, lastColumn - 5);
  const planPreview = await workbook.render({
    sheetName: 'PLAN_TAPPING - 副本',
    range: `${columnName(startColumn + 1)}1:${columnName(lastColumn + 1)}16`,
    scale: 1.4,
    format: 'png',
  });
  await fs.writeFile(path.join(previewDir, 'plan_result.png'), new Uint8Array(await planPreview.arrayBuffer()));
  const csvPreview = await csvWorkbook.render({
    sheetName: '决策树结果', range: 'A1:L16', scale: 1.1, format: 'png',
  });
  await fs.writeFile(path.join(previewDir, 'csv_result.png'), new Uint8Array(await csvPreview.arrayBuffer()));
}

console.log(JSON.stringify({
  workbook: workbookPath,
  csv: csvPath,
  planRows: resultValues.length - 2,
  allocationRows: audit.assignment_rows.length,
  assigned: csvAssigned.length,
  resultColumn: columnName(lastColumn + 1),
  realCraneIds: audit.real_crane_ids,
  inspect: check.ndjson,
}));

function csvCell(value) {
  if (typeof value === 'number') return String(value);
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function columnName(oneBased) {
  let number = oneBased;
  let result = '';
  while (number > 0) {
    number -= 1;
    result = String.fromCharCode(65 + (number % 26)) + result;
    number = Math.floor(number / 26);
  }
  return result;
}
