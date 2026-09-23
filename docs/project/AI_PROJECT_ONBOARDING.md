# AI 项目接手导航

## 最小必读

普通任务先完成 Git 状态/分支/HEAD 核对，然后阅读：

1. [AGENTS.md](../../AGENTS.md)：长期架构、科研、安全和交付规则。
2. 本页：按下表选择任务协议。
3. [CURRENT_STATUS](../CURRENT_STATUS.md)：当前阶段和解释限制。
4. 当前 Issue 或用户任务、涉及的源码与测试。

不用默认通读历史交接和历周报告。修改前搜索调用关系；文档和源码冲突时以源码、Git 与
实际测试为准。完整离线测试一次 + Gate 的统一顺序见
[贡献指南](../../CONTRIBUTING.md#5-修改与验证)。

## 按任务必读

| 任务 | 协议/入口 |
| --- | --- |
| CLI、Pipeline、获取/清洗/去重/排序 | [Pipeline guide](UNIFIED_PIPELINE_GUIDE.md)、[W2 contracts](W2_DATA_CONTRACTS.md) |
| 批量实验 | [Batch guide](BATCH_EXPERIMENT_GUIDE.md) |
| W4 benchmark / annotation / strict evaluation | [Pilot protocol](W4_PILOT_BENCHMARK_PROTOCOL.md)、[Annotation guideline](W4_ANNOTATION_GUIDELINE.md) |
| W5 ranking / method output / formal evaluation | [Method Ranking Contract](W5_METHOD_RANKING_CONTRACT.md) |
| W6 topic/pool/hidden/blind/method/synthesis/Gate | [W6 research contract](W6_RESEARCH_CONTRACT_AND_PARALLEL_BOOTSTRAP.md)；并行矩阵及 fixture closure 在该协议内 |
| Pilot selection / RCP | [RCP v0.3](PILOT_V0_3_REFERENCE_CURATION_PROTOCOL.md)、[v0.3.1 addendum](PILOT_V0_3_1_REFERENCE_CURATION_PROTOCOL.md) |
| Downstream evidence、measurement、first-look | [Phase closure](downstream_pilot_phase_closure_20260921.md)、[Evidence contract](DOWNSTREAM_MEASUREMENT_EVIDENCE_CONTRACT.md) |
| Evidence 保存/迁移 | [Preservation plan](EXTERNAL_RESEARCH_EVIDENCE_PRESERVATION_PLAN.md) |

涉及里程碑时，继续阅读当前状态指向的阶段计划。只读与任务相关的协议；W4 的 60/60 身份
和 W6 六人开发矩阵是版本协议要求，不是所有普通维护任务的默认阅读范围。

## 快速定位

- `app/`：薄 CLI；`src/`：业务与 validator，依赖只允许 `app → src`。
- `tests/automated/`：unittest；`tests/fixtures/`：离线固定输入。
- `configs/`：运行/研究配置；`data/benchmarks/`、`data/analysis/` 中可能有冻结科研 artifact，
  修改前必须检查其协议和身份边界。
- `outputs/experiments/`、`outputs/batches/`：普通运行输出，不提交。
- `docs/project/`：协议；`docs/reports/`：历史阶段记录。

## 历史参考（按需）

- [完整技术与历史交接](AI_PROJECT_REFERENCE.md)：W1–W6 架构、字段、阶段说明和旧命令。
- [历次状态与验证快照](PROJECT_STATUS_HISTORY.md)：W4/W5 结果、W6 演进、历次测试数字。
- 历史记录保留来源语境；不得用旧 preparation 状态否定后来已执行的外部 pilot，也不得把
  旧测试结果当作当前验证。
