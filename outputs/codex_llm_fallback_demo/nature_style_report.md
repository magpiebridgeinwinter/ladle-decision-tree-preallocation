# A validated Codex fallback resolves a greedy allocation failure in tiered ladle rescheduling

## Abstract

Fast rule-based allocation is suitable for routine ladle preallocation, but a greedy local choice can leave a later, tightly constrained heat without a feasible assignment after a production disturbance. We evaluated a tiered response controller that invokes a Codex-generated fallback only after the decision-tree allocator fails and while a positive safety budget remains. In a deterministic two-heat scenario, the baseline crane became unavailable 500 s before the earliest pour time, leaving 410 s after a 90-s safety buffer. The decision tree assigned one of two affected heats and achieved an on-time rate of 0.50. Codex instead considered both heats jointly, reserved the near crane for the 10-s transport window, and assigned the flexible heat to the second crane. The resulting two-heat mapping was complete and passed the same grade, ladle-state, load, operating-range, time-window and safety-distance checks used for the decision-tree output, increasing the on-time rate to 1.00 with no recorded hard-constraint violations. This experiment validates the controller boundary and shared validation loop for a Codex-authored fallback. It does not establish production API availability, model latency, robustness across disturbances or performance on plant-scale data.

## Introduction

Ladle preallocation must respond quickly to crane, ladle, facility and schedule disturbances without weakening production constraints. A decision tree provides a traceable and low-latency primary path because it filters infeasible resources and ranks feasible candidates using explicit rules. This local strategy is appropriate when each choice has little effect on subsequent heats. It can nevertheless fail when a flexible heat consumes the only resource configuration that can satisfy a later, tightly constrained heat.

The response controller examined here separates fast allocation from fallback reasoning. It first executes the decision-tree allocator on only the affected, unlocked heats. If the decision tree fails and the available time exceeds the 90-s safety buffer, the controller exposes the affected heats, remaining resources and failure context to an LLM-compatible callable. Any returned mapping is accepted only if it contains every affected heat exactly once and passes the shared hard-constraint validator. A failure, timeout or invalid mapping returns the system to the Frozen path for human review.

We tested whether the fallback interface could recover a deliberately constructed greedy failure while preserving the same acceptance criteria. The objective was not to benchmark language models or to estimate plant-level benefit. Instead, the experiment asked a narrower question: can a mapping authored by the current Codex session enter the existing fallback path, recover an otherwise unassigned heat and survive the production validator without bypassing constraints?

## Methods

### Tiered response rule

For a disturbance at time \(t_e\), the controller computes the LLM budget as

\[
B = t_{\mathrm{pour,min}} - t_e - 90\ \mathrm{s}.
\]

The decision tree always runs first. An unsuccessful decision-tree result may reach the Codex fallback only when \(B>0\). The fallback output must provide one `heat_id`, `ladle_id` and `crane_id` mapping for every affected heat. The controller then applies the same `validate_output` function used for decision-tree assignments and rejects incomplete, duplicated, unknown or constraint-violating mappings.

### Synthetic disturbance scenario

The deterministic scenario contained two affected heats, two available ladles and two remaining cranes after baseline crane `C0` became unavailable at \(t_e=100\) s. Both heats had a pour time of 600 s, producing a fallback budget of 410 s after the safety buffer.

`H-FLEX` had priority 2, required grade 4 and allowed a 1,000-s transport window. `H-TIGHT` had priority 1, required grade 5 with enforced grade matching and allowed only a 10-s transport window. Ladle `L-FAR` was grade 4 at position 100 m, whereas `L-NEAR` was grade 5 at position 0 m. Crane `C1` started at 0 m and could operate from 0 to 100 m. Crane `C2` started at 100 m, carried an initial load of 150 t and could operate from 50 to 150 m. Both ladles weighed 80 t, and both cranes had a maximum load of 300 t.

### Decision-tree baseline

The allocator ordered heats by priority and processed `H-FLEX` first. Its scoring rule selected `L-FAR/C1` for this heat and updated the working position of `C1` to 100 m. For `H-TIGHT`, grade enforcement excluded `L-FAR`; the operating range of `C2` excluded `L-NEAR` at 0 m; and returning `C1` from 100 m to `L-NEAR` exceeded the 10-s window. The decision tree therefore returned one valid assignment and one unassigned heat.

### Codex fallback

The full scenario state and the decision-tree failure were presented to the current Codex session. Codex treated the two heats as a joint resource-allocation problem and returned the following mapping:

| Heat | Ladle | Crane | Rationale |
| --- | --- | --- | --- |
| `H-FLEX` | `L-FAR` | `C2` | Use the crane already positioned at the far ladle and preserve `C1` for the tight window. |
| `H-TIGHT` | `L-NEAR` | `C1` | Use the near crane to satisfy the 10-s transport window. |

The proposal was injected through the controller's LLM callable boundary. No external Codex or OpenAI API was called. The controller did, however, execute its normal fallback invocation, completeness check, hard-constraint validation, result merge and metric calculation.

### Validation and metrics

The validator checked grade compatibility, ladle availability, empty-ladle weight, crane load, crane operating range, arrival within the heat window and configured safety distance. For the Codex mapping, `C2` carried 230 t after receiving `L-FAR`, below its 300-t maximum, and `C1` carried 80 t. Both cranes began at the positions of their assigned ladles, yielding expected arrival times of 0 s in the scenario coordinate system. The primary outcome was the number of assigned heats. Secondary outcomes were on-time rate, priority-weighted on-time rate, average and maximum delay, and hard-constraint violations.

## Results

The Frozen baseline assigned neither affected heat. The decision tree assigned `H-FLEX` but left `H-TIGHT` unassigned, giving one assignment, an on-time rate of 0.50 and a priority-weighted on-time rate of 0.67. The controller then invoked the Codex fallback because the decision tree had failed and the time budget remained positive.

The Codex mapping assigned both affected heats. The completeness check confirmed that each heat appeared exactly once, and the shared validator returned `assign` for both rows. The fallback therefore entered the `llm_react_success` response path. Relative to the decision tree, Codex recovered one additional heat and increased both the overall and priority-weighted on-time rates to 1.00. No hard-constraint violation was recorded for either assignment.

| Response path | Assigned heats | On-time rate | Priority-weighted on-time rate | Average delay (s) | Maximum delay (s) | Hard-constraint violations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen | 0/2 | 0.00 | 0.00 | 505.0 | 1,000.0 | 0 |
| Decision tree | 1/2 | 0.50 | 0.67 | 5.0 | 10.0 | 0 |
| Codex fallback | 2/2 | 1.00 | 1.00 | 0.0 | 0.0 | 0 |

The zero violation count for Frozen and the failed decision-tree row should not be interpreted as successful allocation. In the current metric contract, an unassigned heat contributes delay but does not count as an applied assignment that violates a hard constraint. Assignment count and validation action must therefore be read together with the violation metric.

## Discussion

This counterexample shows why a fallback can add value even when it is not allowed to relax constraints. The decision tree optimized one heat at a time and committed the near crane to a heat with a wide window. Codex recognized the asymmetric resource dependency: `H-TIGHT` had only one feasible near-crane configuration, whereas `H-FLEX` could be served by the farther crane. Reversing the crane choices preserved the scarce configuration and recovered the second heat. The gain arose from joint reasoning over resource scarcity, not from accepting a lower safety standard.

The result also validates a specific software contract. The controller did not trust the declared success of the Codex proposal. It required a complete heat mapping and re-evaluated every assignment through the shared validator before returning `llm_react_success`. This behavior is important because it keeps an LLM proposal subordinate to deterministic production rules.

The evidence remains deliberately narrow. First, the scenario was synthetic and designed to expose a greedy failure; it does not estimate the frequency of such failures in plant data. Second, only one deterministic disturbance was evaluated, with no repeated runs, alternative language models, optimizer baseline or ablation. Third, the Codex proposal was authored in this interactive session and injected through an adapter. The measured controller time therefore excludes model inference, network transport, retries and service availability and must not be reported as Codex latency. Fourth, the current validator establishes compliance with its implemented per-assignment constraints but does not by itself prove safety against every temporal interaction in a production schedule. These boundaries prevent the experiment from supporting a general claim that Codex outperforms the decision tree or is ready for autonomous production use.

A production-facing evaluation should next derive decision-tree failure cases from real disturbance logs, invoke a versioned Codex endpoint through the same callable contract, record complete prompts and redacted responses, and compare the fallback with a deterministic global optimizer under identical constraints. Repeated trials should quantify fallback success, latency distribution, invalid-output rate, Frozen avoidance and human-review demand. Such evidence is required before the present interface result can be translated into an operational performance claim.

## Conclusion

We constructed a two-heat crane-offline scenario in which the greedy decision tree assigned only one heat despite the existence of a complete valid mapping. A Codex-authored global reassignment recovered the second heat, increased the on-time rate from 0.50 to 1.00 and passed the same hard-constraint validator with no recorded violations. The experiment demonstrates that the existing tiered controller can accept and validate a Codex fallback after a decision-tree failure. Its conclusion is limited to interface and constraint-loop feasibility in one synthetic case; production API reliability, latency, generalization and plant-level benefit remain untested.

---

## 中文结构说明

本报告采用“问题—方法—证据—边界”的算法论文结构。核心结论限定为：在一个可复现的合成反例中，Codex 给出的全局映射通过了现有统一校验器，并比贪心决策树多完成 1 个炉次。报告没有把会话内注入适配器的耗时当作模型推理耗时，也没有声称 Codex 已经接入生产 API 或在一般场景下优于决策树。

章节安排如下：

- 引言：说明局部贪心决策在资源稀缺场景下可能失败。
- 方法：定义 90 s 安全预算、合成扰动、决策树路径、Codex 映射和统一校验。
- 结果：仅报告本次审计直接支持的分配率、准时率、延迟和约束结果。
- 讨论：解释 Codex 方案为何有效，同时明确单场景、合成数据和未调用外部 API 的限制。
- 结论：只收束到“接口和约束闭环可行”，不延伸到生产效果。

## Terminology ledger

| Canonical term | First-use definition | Decision |
| --- | --- | --- |
| decision-tree allocator | The deterministic, priority-ordered primary allocation path | Use consistently; do not shorten to “tree model”. |
| Codex fallback | The mapping authored by the current Codex session after decision-tree failure | Do not call it a production Codex API response. |
| tiered response controller | The controller that executes decision tree, eligible LLM fallback and Frozen handling | Use as the system boundary under evaluation. |
| shared hard-constraint validator | `validate_output`, applied to both decision-tree and fallback mappings | Use to distinguish proposal generation from acceptance. |
| Frozen baseline | The no-reallocation response used when automated recovery is unavailable | Capitalize `Frozen` consistently. |
| on-time rate | On-time assignments divided by all heats | Report together with assigned-heat count. |

## Claim–evidence map

| Claim | Evidence | Status |
| --- | --- | --- |
| The constructed scenario caused decision-tree failure. | Audit path `decision_tree_failure`; one of two heats assigned. | Supported |
| Codex recovered one additional heat. | Codex path assigned two heats versus one for the decision tree. | Supported |
| The Codex mapping passed the existing hard constraints. | Complete proposal; two validated `assign` actions; zero recorded violations. | Supported |
| The controller can invoke and validate a Codex-authored proposal through its callable boundary. | `controller_called_adapter=true` and `llm_react_success` in the audit. | Supported |
| Codex is faster or more reliable than another model or optimizer. | No external inference, repeated trials or comparator. | Needs evidence |
| Codex improves production outcomes on real disturbances. | Only one synthetic scenario was evaluated. | Needs evidence |

## Assumptions or missing inputs

- No real disturbance log was available for this experiment.
- No external Codex API call, model version, token count or inference latency was measured.
- No deterministic global optimizer was included as a comparator.
- No repeated trials, confidence intervals or failure-rate estimates were available.
- The report relies on the hard constraints currently implemented in `validate_output`; unimplemented production constraints are outside its evidence boundary.

## Why this structure

- The abstract states the quantitative result and its boundary in the same paragraph.
- Methods separate controller mechanics from the Codex-authored decision.
- Results report observations without attributing a general mechanism.
- Discussion interprets the scarce-resource insight and then audits competing explanations and missing evidence.

