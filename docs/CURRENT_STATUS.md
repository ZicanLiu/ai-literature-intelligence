# 当前项目状态

入口核验日期：2026-09-22。Fetch 后 `origin/main` = `37b2f7d`，PR #83 已合并；
当时唯一 open PR 为 #82（协作练习），无 open Issue。以上是核验快照；每次任务重新核对 Git/GitHub。

## 当前阶段与必守解释

2026-09 downstream pilot 已收口。仓外已执行 RCP/integration、MCA 人工审核聚合、matched
context、24 formal outputs、GPT/DeepSeek/GLM 三 Judge 盲评、授权解盲、frozen first-look、
Full Pro sensitivity 与 measurement reconstruction。PR #81 的工作台及 PR #83 的路径兼容和
formal-verification 加固已进入 main。

- 原 original human Gate = **NOT_EVALUABLE**。
- Full Pro = **SENSITIVITY_EVALUATOR**，不是第四个 primary Judge。
- Rubric V2 = **FUTURE / PROSPECTIVE DRAFT**，没有回溯应用或重评分。
- 当前证据不证明 MCA 更优、跨 Topic 泛化、机制归因或外部有效性。
- 仓内 preparation 的 `prepared_not_started` 仅描述该 committed 准备快照；不能推断外部研究未执行。

当前阶段入口/下一步决策：
[phase closure](project/downstream_pilot_phase_closure_20260921.md)、
[measurement evidence contract](project/DOWNSTREAM_MEASUREMENT_EVIDENCE_CONTRACT.md)。
后续顺序为 Protect V1 blind human review → targeted human reason audit → prospective
measurement falsification → 再讨论更强的 selector comparison。

## Evidence 与复现入口

- 正式代码仓库：`MVP/astro-spectrum-literature-mvp`。
- 外部只读 evidence root：`MVP/evidence_pilot_202609`，不是整个 MVP。
- 29 个登记 package 的顶层为 lowercase，保留明确的 legacy aliases；内部原字节与 manifest 不变。
- Full Pro 使用该 root 内独立 supplement ZIP；没有此前冻结 trust anchor，保持 unanchored 分类。
- Derived 输出在 evidence root 外，每次使用新目录；正式复现必须加 `--formal-verification`，
  严格要求 28/28 MATCH 和 source binding，不能以 diagnostic 完成替代。
- 已有同机不同物理盘独立备份；未声称异地/云端验证。详见
  [preservation plan](project/EXTERNAL_RESEARCH_EVIDENCE_PRESERVATION_PLAN.md)。

最近已提交的 closeout 验证记录在[历史状态](project/PROJECT_STATUS_HISTORY.md)，
它不是本次任务测试结果。当前验证必须重新执行。

## 工程与科研任务导航

最小阅读与任务协议见[接手导航](project/AI_PROJECT_ONBOARDING.md)。
`app.main` 保留 v0.2 baseline；`app.run_pipeline` 和 `app.batch_runner` 使用统一主链。
W4 approved record-level benchmark、W5 Method Contract 与冻结方法/指标保留原身份；
W6 contract/fixture 通过不等于完成真实 hidden evaluation。

交付使用[标准本地验证顺序](../CONTRIBUTING.md#5-修改与验证)。
W4/W5 具体结果、W6 演进、旧验证数字和未完成研究决策保留于
[历史参考](project/PROJECT_STATUS_HISTORY.md)，按任务查阅，不列为普通小任务默认必读。
