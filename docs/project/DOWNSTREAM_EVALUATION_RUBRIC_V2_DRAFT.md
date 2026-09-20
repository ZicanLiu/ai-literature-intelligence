# Downstream Evaluation Rubric V2（前瞻性草案）

> 状态：**FUTURE / PROSPECTIVE DRAFT**。本草案仅为未来实验设计输入，
> **不是**当前 pilot 的重新评分规则，不改变任何已冻结 judgement、
> first-look 结果或 Gate 前提。禁止用当前 treatment 结果回调本草案权重，
> 禁止挑选有利于任一 arm 的规则，禁止据此重打分。

## 1. 为什么需要 V2

2026-09-19 measurement reconstruction 确认了 V1 的三个测量问题：

1. **复合端点混淆机制**。`U = atomic ∧ supported ∧ in-scope ∧ nonredundant`
   把四个构造压成一个数：GPT 与 Full Pro 对同一 144 claims 的 U 分歧
   （raw agreement 0.806）几乎全部来自 atomicity 与 scope 两个成分，
   support 与 redundancy 在所有 evaluator 间完全一致（raw agreement 1.000）。
2. **evaluator 实现敏感**。同一证据、同一规则文本下，原三 Judge 的
   ΔU 为 +7/12、+1/12、0，Full Pro 为 −7/12；固定 λ 网格上 Full Pro 的
   ΔU 从 −0.583（λ=0）单调变号到 +0.667（λ=1）。
3. **单维分数无法定位分歧来源**。V1 无法回答"分歧来自证据支持还是任务边界
   解释"；分解后 GPT 的 U 损失同时来自 atomic(4) 与 scope(5) 失败
   （BM25 臂），Full Pro 的负 ΔU 集中于 MCA 臂 atomic-only 失败（16）。

## 2. V2 分构造报告原则

每个 output 按**独立维度**分别报告，不再聚合成单一 UIS：

| 维度 | 构造 | V1 对应 | 备注 |
| --- | --- | --- | --- |
| D1 Evidence Support | claim 是否被引文证据支持 | support | 各 evaluator 已一致；保留原判定 |
| D2 Task/Scope Alignment | claim 是否在任务边界内 | scope | 需要显式边界判据（对象/模态/任务/方法角色） |
| D3 Structural Atomicity | 一个单元是否表达单一主要事实 | atomic | 需书面化"必要限定属于该事实"的操作定义 |
| D4 Redundancy / Increment | 相对先前单元的信息增量 | redundancy | 各 evaluator 已一致 |
| D5 Substantive Error Events | 独立实质错误事件 | E | 保留 distinct-event 计数与全部子类型标签 |
| D6 Usefulness/Coverage（可选） | 对下游科研任务的实际可用性 | 无 | 仅未来人评维度，AI judge 不得代替 |

禁止项：不得把 D1–D5 重新加权组合成"新 UIS 总分"后再用于 arm 对比；
跨 arm 对比必须逐维度报告方向与幅度。

## 3. 边界子类型显式化（吸收 error audit 发现）

V1 的 `task_boundary_misuse` 是泛化标签；事件词表实际含
`wrong_method_role`(12)、`wrong_target_task`(8)、`wrong_scientific_object`(2)、
`wrong_data_modality`(1)。V2 要求 scope 判定与错误事件按四个子类型**分开记录**
（一个事件可多标签），使 D2 分歧可归因。

## 4. Evaluator 与测量校准计划

1. **冻结 schema**：Full Pro 类敏感性评审若无冻结 schema 不得用于任何
   （包括诊断外的）汇总。
2. **合成 metamorphic 校准集**：构造已知真值的合成 case
   （atomic 边界、scope 边界、evidence 部分支持），要求 evaluator 在
   受控变换下保持判定不变；已在 synthetic reviewer qualification
   （V1/V1.1）方向上有先例，V2 将把它用于 **evaluator** 而非仅 reviewer。
3. **evaluator calibration set**：每 evaluator 在同一冻结校准集上报告
   各维度命中率与偏差方向；未校准的 evaluator 不得单独作为 primary。
4. **inter-evaluator agreement 报告规范**：必须同时报告 raw agreement、
   列联表、prevalence；κ 仅在两侧边缘分布非退化时给出（GLM 在本 pilot
   中 144/144 PASS 即为退化例）。
5. **human reason audit**：对每 evaluator 的 D2/D3 失败抽样做人类理由审计，
   区分"规则解释差异"与"事实判断差异"。
6. **前瞻冻结**：V2 采用前必须整体冻结（维度定义、子类型、校准集、
   报告模板），实验后不得回调。

## 5. 与当前 pilot 的关系

- 当前 first-look（GPT +7/12、DeepSeek +1/12、GLM 0/0；Full Pro 敏感性
  −7/12/−8/12）**按 V1 口径保持原样**，不重算、不重解释为 V2 结论。
- V2 结论必须在**新的、预注册的**实验上产生；本草案本身不预置任何
  arm 方向预期。
- 本草案未经项目协调者批准不得升级为 approved rubric。
