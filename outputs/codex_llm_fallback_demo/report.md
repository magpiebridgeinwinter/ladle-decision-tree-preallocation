# Codex LLM 兜底演练报告

> 本报告中的方案由当前 Codex 会话生成，并通过控制器的 LLM callable 边界注入。未调用外部模型 API。

## 场景

- 扰动：基线行车 `C0` 在 `t=100s` 离线。
- 受影响炉次：`H-FLEX`、`H-TIGHT`。
- 最早开浇：`t=600s`；扣除 90 秒安全缓冲后，LLM 预算为 `410s`。
- `H-TIGHT` 只有 10 秒运输窗口，必须使用近端 `L-NEAR/C1`。

## 决策树失败

决策树结果为 `decision_tree_failure`，只完成 `1/2` 个炉次。它先把 `L-FAR` 分给 `C1`，之后 `H-TIGHT` 因 `grade,time_window,x_limit` 无候选。

## Codex 方案

| 炉次 | 钢包 | 行车 | 选择原因 |
| --- | --- | --- | --- |
| H-FLEX | L-FAR | C2 | Codex 全局分配：将 C1 保留给紧窗口炉次 |
| H-TIGHT | L-NEAR | C1 | Codex 全局分配：使用近端行车满足 10 秒窗口 |

控制器实际进入 `llm_react_success`，完成 `2/2`；完整性检查和共享 `validate_output` 硬约束终检均通过。

## 结论

这次演练证明了当前控制器能在决策树失败且预算充足时接收 Codex 方案，并由统一校验器决定是否采用。它验证的是接口与约束闭环，不等同于已接通生产环境中的 Codex API。
