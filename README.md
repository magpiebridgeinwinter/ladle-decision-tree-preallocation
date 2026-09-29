# 钢包决策树预配包与局部重调度

系统把上游 `PLAN` 炉次计划作为输入，结合 `CRANE` 行车快照和位置映射生成可解释的决策树预配包。正常预配包始终由决策树完成；突发扰动进入独立的 LLM Workflow，所有方案仍需经过确定性硬约束校验。

## 运行入口

| 用途 | 命令 |
| --- | --- |
| 兼容全量回放 | `python -m ladle_preallocation.real_data.pipeline` |
| 180 分钟滑窗预配 | `python -m ladle_preallocation.real_data.pipeline --sliding-window` |
| 正常预配包 HTTP 接口 | `source .env.local && .venv/bin/python tools/serve_visualization.py --port 4173` |
| 离线重调度 Demo | `python -m ladle_preallocation.demo --skip-llm --num-scenarios 10` |
| 启动可视化服务 | `source .env.local && python3 tools/serve_visualization.py --port 4173` |
| 使用 LLM 的 Demo | `source .env.local && python -m ladle_preallocation.demo`，也可传入 `--llm-api-key` 覆盖 |
| 测试 | `python -m pytest -q` |

先创建环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 首次配置 LLM
cp .env.local.example .env.local
# 编辑 .env.local，填写 LLM_API_KEY 后加载到当前 shell
source .env.local
```

真实数据入口会写入 `outputs/decision_tree_audit.json` 和 `outputs/result_summary.md`。启用滑窗时，审计文件还会保留每个炉次的 `unallocated`、`preallocated`、`locked` 生命周期记录。

## 扰动响应

1. 在转炉开吹前 180 分钟进入预配窗口；已经吹炼的炉次锁定，不能被扰动重写。
2. 行车不可用、钢包不可用、设施不可用或计划偏差只影响仍可重调度的局部炉次。
3. 以 `最早开浇时刻 - 事件时刻 - 90 秒` 计算 LLM 决策预算。预算耗尽时不再等待 LLM，直接 Frozen 并要求人工复核。
4. 扰动预算充足时直接进入 LLM Workflow。LLM 未配置、调用失败或方案校验失败时也会 Frozen + 人工复核。任何 LLM 输出都必须通过钢包状态、载重、运行区间、时间窗和安全间距校验。

LLM 配置使用项目根目录的 `.env.local`。该文件采用 shell `export` 语法，必须先执行 `source .env.local`，再启动服务或 Demo；程序读取进程环境变量 `LLM_API_KEY`、`LLM_API_BASE` 和 `LLM_MODEL`。真实 `.env.local` 已被 Git 忽略，绝不写入代码、审计或报告。命令行参数 `--llm-api-key`、`--llm-api-base` 和 `--llm-model` 可以覆盖环境变量。离线测试和 `--skip-llm` Demo 不会访问外部网络。

## HTTP 接口

完整接口契约见 [docs/ladle-preallocation-openapi.yaml](docs/ladle-preallocation-openapi.yaml)。静态可视化页面不是业务 API。

### 接口列表

| 方法 | 路径 | 输入 | 输出 |
| --- | --- | --- | --- |
| `GET` | `/api/scenarios/summary` | 无 | 场景库版本、数量、分类和已验证回退数量 |
| `GET` | `/api/scenarios?category=...` | 可选 `category` 查询参数 | 场景摘要列表 |
| `GET` | `/api/scenarios/{scenario_id}` | 路径中的场景编号 | 完整事件、资源、响应、校验和审计 |
| `POST` | `/api/simulate` | 可选 `scenario_id` JSON | 受控扰动 Workflow 结果；失败时 Frozen/人工复核 |
| `POST` | `/api/v1/ladle-preallocation/allocate` | 炉次计划、钢包、行车和位置映射 JSON | 决策树预配结果、指标和审计 |
| `POST` | `/api/v1/ladle-preallocation/disturbances` | 扰动事件、版本和当前资源快照 | 版本化重调度任务和候选 revision |
| `GET` | `/api/v1/ladle-preallocation/jobs/{job_id}` | 任务编号 | Workflow 状态和影响范围 |
| `GET` | `/api/v1/ladle-preallocation/revisions/{revision_id}` | revision 编号 | 候选、确认或已发布结果 |
| `POST` | `/api/v1/ladle-preallocation/revisions/{revision_id}/confirm` | 操作人和确认原因 | 已确认或驳回的 revision |
| `POST` | `/api/v1/ladle-preallocation/revisions/{revision_id}/publish` | 操作人和发布原因 | 发布凭证和新配包版本 |

### 真实扰动接口怎么用

真实扰动要按下面的顺序调用。每一步的编号都来自上一步响应，不能自己随意填写：

```text
1. 正常预配包：拿到 allocation_version
2. 发生扰动：提交 disturbance_id 和三个版本号
3. 查询任务：拿到 job_id 和 revision_id
4. 候选可行时：人工 confirm
5. confirm 成功后：publish
```

### 1. 启动服务

项目根目录执行：

```bash
source .env.local
.venv/bin/python tools/serve_visualization.py --port 4173
```

如果只测试没有 LLM 的情况，也可以直接启动。扰动接口会返回 `frozen` 或 `human_review`，不会伪造成功结果。

### 2. 正常预配包，生成基线

正常预配包接收上游已经安排好的炉次计划和资源快照，不重新编制炉次计划。请求中的 `plan_version` 和 `snapshot_version` 由上游系统提供；响应中的 `allocation_version` 由服务生成。

```bash
curl -i -X POST http://127.0.0.1:4173/api/v1/ladle-preallocation/allocate \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id": "demo-001",
    "plan_version": "PLAN-20260306-V1",
    "snapshot_version": "SNAPSHOT-20260306-080000",
    "plan_date": "2026-03-06",
    "execution_mode": "sliding_window",
    "window_minutes": 180,
    "heats": [{
      "heat_id": "AQ0640E1",
      "plan_sequence": 640,
      "required_grade": 5,
      "tap_finish_at": "2026-03-06T08:20:00Z",
      "ladle_arrival_at": "2026-03-06T08:35:00Z",
      "ladle_pour_start_at": "2026-03-06T08:52:00Z"
    }],
    "ladles": [{
      "ladle_id": "ST38",
      "grade": 5,
      "position_code": "4QF5",
      "position_m": 38105,
      "weight_tonnes": 160,
      "age_seconds": 420,
      "availability": "available"
    }],
    "cranes": [{
      "crane_id": "2500",
      "online_status": "online",
      "position_m": 35000,
      "speed_mps": 2,
      "current_load_tonnes": 0,
      "max_load_tonnes": 300,
      "safe_distance_m": 10,
      "limit_0_m": 0,
      "limit_1_m": 48000
    }],
    "location_map": [{
      "position_code": "4QF5",
      "span_name": "4Q",
      "position_m": 38105,
      "location_type": "ladle_yard",
      "status": "available"
    }]
  }'
```

返回 `200` 表示所有炉次完成分配；返回 `422` 表示请求格式正确但至少一条炉次没有可行候选，响应仍包含逐炉次原因和 `manual_review`/`unassigned` 状态。请求格式的完整 OpenAPI 文件见 `docs/ladle-preallocation-openapi.yaml`。

请从响应中复制这三个字段，下一步要使用：

```json
{
  "plan_version": "PLAN-20260306-V1",
  "snapshot_version": "SNAPSHOT-20260306-080000",
  "allocation_version": "ALLOC-服务返回的值"
}
```

### 3. 提交真实扰动

下面示例表示 `2500` 号行车离线。把 `ALLOC-服务返回的值` 替换成上一步实际返回的 `allocation_version`：

```bash
curl -i -X POST http://127.0.0.1:4173/api/v1/ladle-preallocation/disturbances \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: DIST-20260306-0001' \
  -d '{
    "disturbance_id": "DIST-20260306-0001",
    "event_type": "crane_offline",
    "occurred_at": "2026-03-06T08:40:00+08:00",
    "resource_id": "2500",
    "plan_version": "PLAN-20260306-V1",
    "allocation_version": "ALLOC-服务返回的值",
    "snapshot_version": "SNAPSHOT-20260306-080000",
    "locked_heat_ids": []
  }'
```

`disturbance_id` 是这次扰动的唯一编号。相同编号重复提交时，服务会返回原来的任务，不会重复调用 LLM。

响应中重点关注：

| 字段 | 含义 |
| --- | --- |
| `job_id` | 这次扰动任务的编号 |
| `status` | `pending_confirmation`、`frozen` 或 `human_review` 等 |
| `revision_id` | 本次重调度结果编号 |
| `impact_scope` | 受影响、锁定和未受影响的炉次 |

### 4. 查询任务和结果

把响应中的编号替换到 URL 中：

```bash
curl -i http://127.0.0.1:4173/api/v1/ladle-preallocation/jobs/JOB-服务返回的值
curl -i http://127.0.0.1:4173/api/v1/ladle-preallocation/revisions/REV-服务返回的值
```

### 5. 人工确认并发布

只有 `status=pending_confirmation` 且硬约束校验通过的候选结果可以确认：

```bash
curl -i -X POST \
  http://127.0.0.1:4173/api/v1/ladle-preallocation/revisions/REV-服务返回的值/confirm \
  -H 'Content-Type: application/json' \
  -d '{
    "operator": "dispatcher-01",
    "reason": "人工确认方案可执行"
  }'
```

确认成功后才能发布：

```bash
curl -i -X POST \
  http://127.0.0.1:4173/api/v1/ladle-preallocation/revisions/REV-服务返回的值/publish \
  -H 'Content-Type: application/json' \
  -d '{
    "operator": "dispatcher-01",
    "reason": "确认后发布"
  }'
```

发布前服务会再次检查版本、资源快照和校验结果。`frozen`、`human_review`、`rejected` 或未确认的 revision 不能发布。

## 结果与边界

批量实验为 Frozen、决策树和 LLM 路径分别输出按时率、优先级加权按时率、延迟、变更炉次、人工复核率、规则违反数和决策耗时；LLM 核心指标只在“决策树失败且实际尝试 LLM”的样本上计算。

这是处理后历史数据的离线回放与 Demo，不代表现场生产控制验收，也不替代人工审批或现场安全机制。
