# 文献实现机理调研：LLM 驱动的调度规则自动设计

> 版本：v1.0　日期：2026-10-13
> 用途：为「钢包重排规则的 LLM 启发式进化方法研究」提供实现级依据与差异化定位。
> 方法：逐篇核对 arXiv LaTeX 源码、官方仓库源码与论文正文；**凡未核实的内容一律显式标注**。
> 配套：`openspec/changes/llm-evolved-ladle-reschedule-rules/`、`docs/设计稿-钢包重排规则LLM进化.md`

---

## 0. 先说三处引用纠错（会直接影响参考文献列表）

| # | 原记录 | 实际情况 |
|---|---|---|
| 1 | `docs/毕设文献清单.md` 记 InstSpecHH = **arXiv:2508.13984** | **错**。2508.13984 是 "The AI-Fraud Diamond"（cs.CY）。正确编号 = **arXiv:2506.00490**《LLM-Driven Instance-Specific Heuristic Generation and Selection》，v3 2026-03-16 |
| 2 | LLM4DRD = arXiv:2601.15738 | 编号对，但那是 **v1 的标题**；v2（2026-03-31）已改名 **EvoDR** |
| 3 | "LSH（LLM Search Heuristics）" | **arXiv 全库检索该短语 0 命中**。DSevolve 与 LLM4RCPSP 均引作 "LSH = Yu et al. 2026"。最可能对应 IEEE *"Automated Scheduling Heuristic Generation and Evaluation via Large Language Model"*（IEEE 11358979）。**建议不要使用 "LSH" 这个名称**，需先核实原始出处 |

另需注意：**DSevolve 有两个版本，且在线机制完全不同**（详见 §1）。引用时必须指明版本。

---

## 1. DSevolve（最直接对标）

### 1.1 两个版本

| | **v1**（2026-03-29；ar5iv 与 Semantic Scholar 都是 v1） | **v2**（2026-07-28，arXiv 现行版） |
|---|---|---|
| 标题 | …Dynamic **Shop Floor**… | …Dynamic **Flexible** Job Shop… |
| 在线机制 | 6 维探针指纹 + 案例库检索 + 前瞻仿真 | **整段替换**为 22 维状态指纹 + 神经选择器（ListNet） |
| 大模型 | Qwen-Plus / DeepSeek-V3 / GPT-4o-mini | 仅 Qwen-Plus |
| Limitations | 有（3 条） | **整节删除** |

### 1.2 已核实的关键事实

- **v1 的三维行为特征空间**（Appendix A）：`f_skew = max_m L_m / L̄`；`f_wait = Σ W_j / Σ P_j`；`f_div = min_{c'∈A} sim(c,c')`（sim 为代码文本编辑距离**或**语义嵌入相似度，**未说明用哪个**）。注意 f_div 用**代码**相似度而非行为相似度，与正文"behavioral novelty"表述不一致。
- **MAP-Elites 存档**：v1 Appendix E.2 明确 **uniform 10×10×10 binning（1000 cells）**，**每 cell 保留 1 个个体**，存档 N=400。实测占据：DSevolve 68.5 cells、EoH 47.3、ReEvo 38.2、HSEvo 31.7——库其实相当稀疏。
- **v1 六维探针指纹**：`f = [f_skew^p, f_cpd, f_flex, f_wait^p, f_den, f_aflex]`；Z-score 标准化 ε=1e-10；权重 **`w_j = Var(f_j)/Σ Var(f_l)`**（方差越大权重越大）。知识库 100 实例 × top-R=4 条；在线 top-k=5、候选 20 条。
- **在线开销（v2 实测）**：每实例 7.66 次决策，平均 **1165.99 ms/次**，其中**神经前向仅 0.88 ms**，1164.77 ms 花在状态特征构造与探针评估。
- **实验规模**：v1 evolution 5 / case library 100 / test 500；每框架 400 条规则；**总 LLM 查询数与费用两版均未报告**。
- **v1 Limitations 原文三条**：①三维特征空间人工选取、未必覆盖其他调度域；②离线知识库构造随 archive 与实例数线性增长（建议 LSH 索引）；③**"our evaluation focuses on makespan as the sole objective"**，多目标（tardiness / energy / utilization）与产线验证为 future work。

### 1.3 证据可得性缺陷（重要）

- v1 声称 persona prompt 在 "Appendix .5/.6/.7-8"，但 **LaTeX 源码中该标签从未定义，附录只有 A–E**——7 条 persona prompt **全文不存在**，只有 7 个名称（Extreme Greedy / Load Balancer / Global Planner / Deadline Chaser / Contrarian / Formula Synthesizer / Hybrid Hierarchical）。
- v1 声称"完整伪代码在附录"，**同样不存在**（源码虽 `\usepackage{algpseudocode}` 但无 `algorithm` 环境）。
- **无代码仓库**：仅写 "code can be provided upon request"；所引 github 只是 DEAP 框架。
- v1 **未给出 HDR 函数签名**（仅说 LLM 收到含 "FJSP definition and code interface" 的 task description）。v2 给出形式 `q_k(o,m|s) = r_k(z(o,m,s))`，`(o*,m*) = argmin q_k`。

→ **含义**：无法逐字复现 DSevolve 的提示词。若做对比实验，必须声明"依据论文描述自行复现，非官方实现"。

---

## 2. EoH（进化引擎）

### 2.1 个体表示

个体 = {自然语言 thought（一句话，**必须在 `{}` 内**）+ code（预定义格式的 Python 函数体）+ fitness}。论文 3.3 原文："Each heuristic consists of three parts: 1) its description in natural language, 2) a code block in a pre-defined format, and 3) a fitness value."

模板填法（LLM4AD 实际做法）：`deepcopy(template_function)` 后置 `body = ''`，把只剩签名+docstring 的模板塞进 prompt。返回后：`thought = re.findall(r'\{.*?\}', response)[0]`（抓不到→None）；`trim_preface_of_function` 丢掉第一个 `def` 之前内容；`trim_function_body` 用 `ast.parse` 从尾部反复删行直到可解析。

### 2.2 算子命名（现有开题材料写错了）

**论文只有 E1、E2、M1、M2、M3 五个算子**（Exploration: E1/E2；Modification: M1/M2/M3），**不存在 E3/E4/E5**。

| 论文算子 | 语义 | 现有开题材料的错误对应 |
|---|---|---|
| E1 | p 个父代 → "totally different form" | 新生成 ✓ |
| E2 | p 个父代 → 先识别共同主干再生成（杂交式） | 被写成"杂交"，但编号被写作 E4 |
| M1 | 1 个父代 → modified version | 被写成"改造"，编号写作 E2 |
| M2 | 1 个父代 → 只改参数设置 | 被写成"参数微调"，编号写作 E5 |
| M3 | 1 个父代 → 删除冗余组件（化简） | **完全缺失** |

论文 3.2 原文："At each generation, each strategy is called $N$ times… **At most $5N$ new heuristics** will be added to the current population at each generation."（**不是**概率采样）。父代选择 $p_i \propto 1/(r_i+N)$，$r_i$ 为按 fitness 的排名。

> ⚠️ **LLM4AD 只实现了 `i1, e1, e2, m1, m2`，没有 M3**；且"一代"由 `_next_gen_pop` 达到 `pop_size` 触发 `survival()` 定义，与论文"每代 5N 次"不同。

### 2.3 种群与选择

- 论文种群规模：OBP **N=20**，TSP/FSSP **N=10**；LLM4AD 默认 `pop_size=5`，并按 `max_sample_nums` 自动调整（≥10000→40、≥1000→20、≥200→10、否则 5）。
- **环境选择 = 截断式 (μ+λ) + 精英保留**（非锦标赛）：`pop = population + next_gen_pop; sorted(score desc); population = pop[:pop_size]`。
- **去重：论文未说明**。LLM4AD 的 `has_duplicate_function` 以 `str(f)==str(func)` **或** `func.score == f.score` 判重并置 `-inf`（个体仍被 append）→ **对连续型适应度是同分即判重的陷阱**。

### 2.4 适应度与评测协议

| 问题 | 训练实例数 | 适应度 |
|---|---|---|
| OBP | **5** 个 Weibull 实例 | `average lb/n`（越大越好） |
| TSP | **64** 个 TSP100 | 相对 Concorde 最优的平均 gap |
| FSSP | **64** 个随机实例 | 平均 makespan |

论文预算：`max_generations=20`，OBP "20 generations, which involves **2,000 LLM queries**"，TSP/FSSP 1000 次。LLM = GPT-3.5-turbo，**temperature 论文未说明**。

> ⚠️ **口径差**：LLM4AD 的 `OBPEvaluation` 返回 `-np.mean(num_bins)`（负的平均用箱数），**不是**论文的 `lb/n`。

### 2.5 不可行/报错个体的处理

- **论文**：只有 Step 1.4 "added to the current population if the heuristic and code are feasible"；对代码报错、超时、非法结果时的适应度取值、是否重试、是否惩罚，**论文未说明**。
- **LLM4AD 实际**：`SecureEvaluator` 在异常或超时时返回 `None`。`score=None` 时，**初始化阶段直接丢弃**；进化阶段置 `-inf` 但仍 append，靠 `survival()` 截断淘汰；`selection()` 只从非 `isinf` 个体抽样。→ "淘汰 + 赋 -inf"，**无重试、无惩罚分**（重试只在 HTTP 层：`HttpsApi` 捕获异常后 `sleep(2)` 无限重试）。

### 2.6 结果口径

论文主表（Table 1/2/3）**只有点估计，无重复次数、无标准差**。独立重复只出现在讨论节：thought/code 交互、不同 LLM、EoH expert 均"carried out… **three times**"，逐次列 Run1/2/3 + Average，**未给 std**。

### 2.7 约束优化扩展

- **原 EoH：全文无 "constraint" 字样**，搜索空间无约束。
- **MEoH**（arXiv:2409.16867）：多目标 AHD，目标 = Optimal Gap + Efficiency（+ 三目标版加 Halstead 可读性）。核心 **dominance-dissimilarity**：用 **AST 相似度**取负作 dissimilarity 矩阵，与 Pareto 支配 mask 逐元素相乘后按列求和得评分向量；父代按 softmax 采样。**未涉及硬约束**。
- **EoH-S**（arXiv:2508.03082，AAAI 2026）：目标是**规则集合**，$\mathcal{F}(H)=\sum_i \min_{h\in H} f_i(h)$，证明其 monotone + supermodular，故贪心有理论保证。个体额外维护 instance-wise 性能向量；互补感知搜索用 **Manhattan distance** 选 2 个互补父代。**CVRP 自带容量约束，但论文未提出专门约束处理机制**。

### 2.8 LLM4AD 的三个工程坑（必须在实现时处理）

1. **同分判重**：`has_duplicate_function` 中 `func.score == f.score` 会把合法但同分的个体置 `-inf`。
2. **`profiler=None` 时 `max_sample_nums` 失效**：`self._tot_sample_nums += 1` 位于 `if self._profiler is not None:` 块内 → 查询预算失控。
3. **Windows 上的进程/线程组合**：`SecureEvaluator` 默认每次评测 `multiprocessing.Process`（Windows 为 `spawn`），而 `EoH` 默认用 `ThreadPoolExecutor` 提交评测 → 在线程中 spawn 进程在 Windows 上脆弱且昂贵。建议 `num_evaluators=1` + `multi_thread_or_process_eval='thread'`，并发交给 `num_samplers`。

---

## 3. 调度规则自动设计这条线（GP vs LLM）

### 3.1 GP 的标准做法

规则 = **表达式树**；**终端 = 活动/工序属性 + 数值常数**；**内部节点 = 数学算子**；候选规则嵌入 **SSGS / 仿真**在训练集上构造调度，调度质量即 fitness；用 selection/crossover/mutation 进化。终端集合典型为 `pt, wkr, rm, so, twk, ema, dd, et`。

代价（LLM4RCPSP 原文）："each exact fitness evaluation involves constructing schedules across the training set"；"GPHH can still require substantial computational effort … because many candidate rules must be assessed"。

> **未核实**：Branke et al. 2016（IEEE TEVC 20(1):110-124，DOI 10.1109/TEVC.2015.2429314）全文在付费墙/403，其 taxonomy 的具体维度名与对 bloat 控制的原文表述**未核实，不要引用**。该综述的官方摘要确认它是 "summarising the state of the art, suggesting a taxonomy, and providing guidelines for the design of hyper-heuristics in production scheduling"。Pickardt 2013 / Hildebrandt 2010 的规则形态**未核实**。

### 3.2 GP 的公认局限（均有原文可引）

- 终端词汇受限 + 可解释性弱（EvoDR："dependent on fixed terminal sets and have weak interpretability"）。
- 搜索随机性高、探索效率低（SeEvo："stochastic search operators"、"high randomness in the search process"）。
- 泛化差 + 特征空间指数膨胀（SeEvo："may not generalize well to unseen DFJSSP instances"、"exponentially increase the search space"）。
- **最该引的一句**（LLM4RCPSP §2.4）："GP-based methods generally search over expressions assembled from predefined terminals and functions, whereas LLM-based methods can generate complete executable heuristics from natural-language task specifications."

### 3.3 LLM vs GP 的实证对照（**回应"GP 早就有"的标准答案**）

**LLM4RCPSP**（arXiv:2609.03754，Luo / Vanhoucke / Coelho, 2026-09）是目前**唯一做同等搜索预算对照**的论文。摘要原文：

> "the LLM-designed rules … **outperform GP-designed rules obtained under comparable search effort**, while remaining **competitive with rules obtained from a substantially larger GP search**."

即：**同预算下 LLM 优于 GP；GP 需要大得多预算才追平**。→ 这直接支撑"LLM 方法具备样本效率优势"，并提供了一个可借用的对照协议。设计：规则在整个调度构造过程中**保持不变**，但 $q_{it}$ 随 $z_t$ 中的构造输入更新而变化——注意这属于**隐式自适应**，不是规则内显式状态分支。

> **未核实**：LLM4RCPSP §5 表格的**精确数值**未读到（HTML 截断），需自行取全文。
> DSevolve v1 摘要明确点名 GP（"outperforms … classical dispatching rules, **genetic programming**, and deep reinforcement learning"），**v2 摘要已删去 GP**。

### 3.4 各篇速查（目标 / 硬约束是否一等公民 / 在线是否调 LLM）

| 工作 | 问题 | 在线调 LLM？ | 目标 | 硬约束一等公民？ |
|---|---|---|---|---|
| **SeEvo**（arXiv:2410.22657 / IEEE T-FS） | 动态模糊 JSSP | 否 | makespan 与 tardiness **分别单目标** | 否 |
| **EvoDR**（原 LLM4DRD，arXiv:2601.15738） | 动态柔性装配流水车间 + kitting | 否 | 单目标平均 tardiness | **部分**（异构图可行有向边排序，把可行性做进动作空间） |
| **LLM4RCPSP**（arXiv:2609.03754） | RCPSP（紧前 + 可再生资源） | 否 | 单目标 makespan | 否（**SSGS/PSGS 构造性保证**） |
| **DSevolve** v1/v2 | 动态柔性作业车间 | 否（但需神经选择器） | 单目标平均 makespan | 否 |
| **InstSpecHH**（arXiv:2506.00490） | **非调度**（OBPP/CVRP） | — | optimality gap | 否（构造保证） |
| **RACE-Sched**（arXiv:2605.29262 / IJCAI 2026） | 动态 FJSP，**毫秒级控制周期** | **是**（在线合成/验证/进化规则 + sandbox） | — | — |

**关键总结**：以上**全部是单目标**（LLM-AMA 例外但非同类）；**没有任何一篇把硬约束可行性作为可权衡目标**——全走 masking / 可行边 / SGS 构造性保证，**可行性被外包给解码器而非被优化**。

---

## 4. 对本课题立论的直接影响（**修正之前的判断**）

### 4.1 必须放弃的说法

| 原说法 | 为什么不能用 |
|---|---|
| "首次把自适应写进单条规则内部" | **已有先例**：SeEvo 用 `ema` 历史偏差趋势作为特征，本质就是规则内自适应；LLM4RCPSP 有 "add gate" 条件门 + 靠 $z_t$ 更新的隐式自适应 |
| "在线零额外选择开销"作为独立卖点 | DSevolve v2 已实测神经前向仅 **0.88 ms**；硬要主张会被视为打稻草人 |

### 4.2 仍然成立的立论

1. **主贡献：可行性作为一等公民**。这是真空缺——所有现有工作都把可行性外包给解码器，从未作为可权衡目标。而 **arXiv:2509.02297**（3D packing 复评）证明 LLM 启发式搜索"几乎只在微调打分函数"、结果与人工贪心相当、且**约束收紧时效果衰减**——这正是本课题最直接的动机。
2. **辅贡献：自适应的层级**。可主张"规则内部针对**硬约束状态**（候选稀缺度、时间窗压力、可达余量）的显式条件分支"，与 DSevolve 的"规则库 + 事件级切换"形成层级对立。注意表述为"层级差异"而非"首次"。
3. **辅贡献：持续再进化 + 上线回归门控**。既有工作均为一次性离线进化。

### 4.3 必须回应的两个邻居

- **DSevolve**：事件级自适应 + 外部神经选择器已被占。以"层级对立"回应，不碰"在线零开销"。
- **RACE-Sched**（arXiv:2605.29262, IJCAI 2026）：动态 FJSP + 毫秒级控制周期 + 在线 LLM 合成/验证/进化规则。这是对"在线 LLM + 实时性"处理最认真的工作，**必须正面回应**；其在线仍依赖 LLM，本课题在线为零 LLM。

### 4.4 投稿前必须排查的潜在反例（均未核实）

| 工作 | 出处 | 为什么危险 |
|---|---|---|
| **DGEvo** | Swarm and Evolutionary Computation, S2210650226001975 (2026) | JSSP + **固定预防性维护（硬约束）**，双特征引导 LLM 进化。ScienceDirect 403，正文未读到 |
| **LHC-CMOEA** | IEEE 11648173 | 事件触发 LLM 引导**约束多目标**协同进化（非调度，但方法论可迁移） |
| **ESWA S095741742600669X** | Expert Systems with Applications | LLM 辅助约束优化 EA 设计 |

### 4.5 对抗 GP 质疑的最优路径

直接借用 **LLM4RCPSP 的 "comparable search effort" 协议**：同一特征池与算子集合、相同总评测次数预算，并**显式报告"GP 的适应度评估次数 vs LLM 的候选数"**。

---

## 5. 未核实清单（**禁止直接引用**）

- Branke et al. 2016 的 taxonomy 维度名与 bloat 控制机制原文。
- Pickardt 2013、Hildebrandt 2010 的规则具体形态。
- SeEvo / EvoDR / DSevolve / LLM4RCPSP 的表格精确数值。
- LLM-AMA、DGEvo、LHC-CMOEA、ESWA S095741742600669X 的正文细节。
- "LSH" 这个名称本身（arXiv 检索 0 命中）。
- DSevolve 的 persona prompt 全文与伪代码（论文中实际不存在）。
- LLM4AD 是否接受**负分**适应度（源码可见 `Population` 的比较不排除负值，但未做端到端验证；实现前需 30 分钟小实验确认）。

---

## 6. 实际访问成功的来源

**论文**：`arxiv.org/abs/2603.27628`、`arxiv.org/html/2603.27628v1`、`arxiv.org/html/2603.27628v2`、`arxiv.org/e-print/2603.27628v1|v2`（LaTeX 源码，公式与附录结构的唯一可靠来源）、`arxiv.org/e-print/2401.02051`、`arxiv.org/e-print/2409.16867`、`arxiv.org/e-print/2508.03082`、`arxiv.org/abs/2601.15738`、`arxiv.org/abs/2410.22657`、`arxiv.org/html/2410.22657v2`、`arxiv.org/abs/2506.00490`、`arxiv.org/abs/2509.02297`、`arxiv.org/abs/2609.03754`、`arxiv.org/html/2609.03754v1`、`arxiv.org/abs/2605.29262`、`arxiv.org/abs/2508.13984`（用于确认该号是另一篇论文）

**代码**：`raw.githubusercontent.com/Optima-CityU/LLM4AD/main/llm4ad/{method/eoh/{eoh,prompt,population,sampler,profiler}.py, base/{evaluate,code,sample}.py, tools/llm/llm_api_https.py, task/optimization/online_bin_packing/{evaluation,template}.py}`、`example/methods/eoh/run_eoh_tsp.py`

**其它**：`gpbib.pmacs.upenn.edu`（Branke 2016 摘要）、`ojs.aaai.org`（EoH-S / HSEvo）、`ieeexplore.ieee.org`（11358979 / 10945804 / 11648173）、`sciencedirect.com`（S2210650226001975，**403**）、`emergentmind.com`、`semanticscholar.org`

**未能获取**：`arxiv.org/pdf/*`（工具不支持 application/pdf）、`openreview.net/pdf?id=BwAkaxqiLB`（浏览器校验拦截）、ScienceDirect 全文（403）
