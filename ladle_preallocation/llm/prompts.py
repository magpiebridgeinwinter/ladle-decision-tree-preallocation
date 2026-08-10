"""Prompts for the LLM ReAct rescheduling agent."""

RESCHEDULING_SYSTEM_PROMPT = """你是一个钢铁冶炼调度专家，专门处理生产扰动后的钢包重调度。

## 你的角色
预配包决策树已经对炉次进行了分配，但发生了设备扰动（行车离线、钢包不可用等）。
决策树使用了剩余资源重排，但失败了——部分炉次仍然无法分配。
你需要在这些困难场景中进行局部重调度，尽量救回受影响炉次。

## 约束规则（必须遵守）
1. 每个钢包同时只能分配给一个炉次
2. 行车不能超载：当前负载 + 钢包空包重量 <= 行车最大载重
3. 钢包位置必须在行车运行区间 [limit_0_m, limit_1_m] 内
4. 行车到达时间 = window_start + |行车位置 - 钢包位置| / 行车速度
5. 到达时间必须 <= window_end（时间窗约束）
6. 行车之间的安全间距必须满足：|位置差| >= safe_distance_m
7. 关注钢包等级匹配：letter grade 字母越接近越好（不是硬约束，但优先匹配）
8. 行车负载尽量均衡：避免把所有任务都塞给一台行车

## 输出格式
始终以 JSON 格式输出：
```json
{
  "assignments": [
    {
      "heat_id": "炉次ID",
      "ladle_id": "分配的钢包ID",
      "crane_id": "分配的行车ID",
      "reason": "分配理由",
      "expected_arrival_seconds": 预计到达秒数
    }
  ]
}
```

## 策略建议
- 优先使用行车运行区间覆盖目标钢包的候选
- 如果某个行车负载过高，尝试切换到负载更低的行车
- 关注时间窗紧迫的炉次优先分配
- 如果实在无法为某个炉次分配，assignments 中不要包含它
""".strip()


def build_problem_description(
    heats: list[dict],
    ladles: list[dict],
    cranes: list[dict],
) -> str:
    """Build a structured problem description for the LLM."""

    def _safe(v: object, default: str = "-") -> str:
        if v is None or v == "":
            return default
        return str(v)

    lines = ["## 当前需要重新分配的炉次\n"]
    lines.append("| 炉次ID | 所需等级 | 时间窗开始(s) | 时间窗结束(s) | 优先级 |")
    lines.append("|--------|---------|-------------|-------------|-------|")
    for h in heats:
        lines.append(
            f"| {_safe(h.get('heat_id'))} "
            f"| {_safe(h.get('required_grade'))} "
            f"| {_safe(h.get('window_start'))} "
            f"| {_safe(h.get('window_end'))} "
            f"| {_safe(h.get('priority'))} |"
        )

    lines.append("\n## 可用钢包\n")
    lines.append("| 钢包ID | 等级 | 位置(m) | 重量(t) | 已用龄期(s) |")
    lines.append("|--------|------|--------|--------|----------|")
    for l in ladles:
        lines.append(
            f"| {_safe(l.get('ladle_id'))} "
            f"| {_safe(l.get('grade'))} "
            f"| {_safe(l.get('position_m'))} "
            f"| {_safe(l.get('weight_tonnes'))} "
            f"| {_safe(l.get('age_seconds'))} |"
        )

    lines.append("\n## 可用行车\n")
    lines.append("| 行车ID | 位置(m) | 当前负载(t) | 最大载重(t) | 速度(m/s) | 安全间距(m) | 运行区间 |")
    lines.append("|--------|--------|----------|----------|--------|----------|--------|")
    for c in cranes:
        limit = f"[{_safe(c.get('limit_0_m'))}, {_safe(c.get('limit_1_m'))}]"
        lines.append(
            f"| {_safe(c.get('crane_id'))} "
            f"| {_safe(c.get('position_m'))} "
            f"| {_safe(c.get('current_load_tonnes'))} "
            f"| {_safe(c.get('max_load_tonnes'))} "
            f"| {_safe(c.get('speed_mps'))} "
            f"| {_safe(c.get('safe_distance_m'))} "
            f"| {limit} |"
        )

    lines.append("\n## 任务\n")
    lines.append(
        f"需要为上述 {len(heats)} 个炉次分配钢包和行车。"
        "请输出完整的 assignments JSON 数组。"
    )
    return "\n".join(lines)


def build_feedback_prompt(
    violations: dict[str, list[str]],
    round_num: int,
    max_rounds: int,
) -> str:
    """Build feedback prompt when validation fails."""

    def _translate_violation(code: str) -> str:
        translations = {
            "unknown_heat": "炉次ID不存在",
            "unknown_ladle": "钢包ID不存在",
            "unknown_crane": "行车ID不存在",
            "ladle_already_used": "钢包已被其他炉次占用",
            "load": "行车超载",
            "x_limit": "钢包位置超出行车运行区间",
            "time_window": "到达时间超出时间窗",
            "safe_distance": "行车安全间距不足",
            "grade_not_available": "无该等级钢包可用",
            "age_out_of_range": "钢包龄期不合格",
            "offline": "钢包离线/不可用",
            "major_repair": "钢包大修中",
            "empty_weight_out_of_range": "钢包空包重量不合格",
            "argon_required": "缺少氩气",
        }
        return translations.get(code, code)

    lines = [
        f"## 校验反馈（第 {round_num}/{max_rounds} 轮）\n",
        "你的方案存在以下违反约束的情况，请修正：\n",
    ]
    for heat_id, errs in sorted(violations.items()):
        readable = [_translate_violation(e) for e in errs]
        lines.append(f"- **{heat_id}**: {'，'.join(readable)}")

    lines.append("\n请重新输出修正后的 assignments JSON。思考以下关键点：")
    lines.append("- 确保每个钢包只分配一次")
    lines.append("- 检查行车载重上限")
    lines.append("- 确认钢包位置在行车运行区间内")
    lines.append("- 验证到达时间不超时间窗")
    lines.append("- 确保行车间安全间距")
    return "\n".join(lines)


def build_final_format_prompt() -> str:
    """Prompt to enforce correct JSON output format."""
    return """你的输出格式不正确。请严格按照以下格式输出 JSON：

```json
{
  "assignments": [
    {
      "heat_id": "具体的炉次ID",
      "ladle_id": "具体的钢包ID",
      "crane_id": "具体的行车ID",
      "reason": "分配理由",
      "expected_arrival_seconds": 数字
    }
  ]
}
```

每个炉次必须使用来自问题描述中的真实 ID。不要编造 ID。"""
