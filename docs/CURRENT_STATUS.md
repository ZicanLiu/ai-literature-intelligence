# 当前项目状态

更新时间：2026-08-17

最新公共 `main` 基线：`7125455`（已合并 W4 PR #42–#47）

当前 W5 前置收口分支：`codex/w5-baseline-closure`（未 push、未 merge）

v0.3.0 tag 仍指向较早的 W2 发布基线 `899f745`；`7125455` 是当前 Git/源码/测试事实，不能
用旧 tag 或旧文档快照替代。

## AI / 新成员接手入口

开始新任务前依次阅读：

1. 根目录 [`AGENTS.md`](../AGENTS.md)；
2. [`AI_PROJECT_ONBOARDING.md`](project/AI_PROJECT_ONBOARDING.md)；
3. 本页和当前 Issue；
4. benchmark/W5 实验任务继续阅读
   [`W4_PILOT_BENCHMARK_PROTOCOL.md`](project/W4_PILOT_BENCHMARK_PROTOCOL.md)。

所有状态都要重新用当前 Git、源码和实际测试核对。

## 当前稳定工程基础

`main` 已包含 OpenAlex v2 分页/重试、领域查询、W2 两级去重、TF-IDF 两阶段排序与评价、
Unified Pipeline、Batch Runner 和 Quality Gate。旧 `python -m app.main` 继续作为 v0.2.0
兼容 baseline；`python -m app.run_pipeline` 和 `python -m app.batch_runner` 是 v0.3.0 主链入口。

Unified Pipeline 支持多 acquisition query、清洗后 provenance、跨 query exact dedup、
不自动删除的 suspected review queue、显式 ranking keyword、旧 baseline 与 two-stage 排序、
可选 judged 评价及阶段化输出。

`preliminary_score` 和 TF-IDF 都是透明、可解释的项目 baseline，不代表论文真实学术价值，
也不能替代人工 Query Relevance 判断。W5 前置收口没有修改 baseline/two-stage 的任何权重、
阈值或排序公式。

## W4 已完成并合并的公共工作

W4 PR #42–#47 已进入 `main`，当前实际具备：

- 三个项目 Research Question 和三个 Pilot research query；
- 冻结的 `candidate_pool_v0.1.csv`、`assignments_v0.1.csv` 和 pool manifest；
- 六人各 15 条、共 90 次 assignment 的原始 annotation；
- Agreement Analyzer、W4 Benchmark Evaluator；
- Candidate entity、provenance、query boundary/hard-negative 和组长研究框架报告。

六个 annotation validator 均通过。Agreement Analyzer 当前结果为：30/30 双标可比较，27
一致、3 分歧；overall exact agreement `0.90`，Cohen's Kappa `0.8133`，quadratic weighted
Kappa `0.9343`。RQ01/RQ02 各 10/10 一致；RQ03 为 7/10 一致。

## Pilot Adjudicated Judged Set 当前状态

当前 versioned artifact 位于：

`data/benchmarks/w4_query_relevance/v0.1.0-draft.1/`

准确状态是 **proposed/draft**，不是 approved benchmark：

- 评价目标仅为 Query Relevance；标签为 `0/1/2` graded relevance；
- 共 60/60 record-level query-paper pair，每个 Research Query 20/20；
- 30 条来自 primary single annotation，保留 `single_annotation` provenance；
- 27 条双标一致，直接形成共同 judgement；
- 3 条 RQ03 分歧仍没有 human final label；
- 3 条均有明确标记为 `pending_human_review` 的 AI adjudication proposal；
- manifest 固定 candidate pool、assignment、query config、来源样例、pool manifest、六人
  annotation、judgements 和 proposals 的 SHA-256。

陈星妤的 15 条已由本人实际审核确认；本次只修正 review provenance，不改变其标签。贾馥诚
的标签是带逐行 AI assistance 记录的人工判断；仓库不声称存在 GitHub 本人再确认记录，正式
promotion checklist 仍要求核对该 provenance。

默认 `python -m app.validate_w4_benchmark` 是 strict，只接受 approved、无 draft 后缀、
60/60 final label 和冻结 hash 完全匹配的 package。当前 draft 只能用
`--allow-draft` 做结构复核，正式 evaluator 会拒绝它。

## Entity alias 与评价单位

W4 v0.1 明确定义为 record-level Pilot Benchmark。冻结池的两对高置信 same-paper alias 保留：

- RQ02：`w4_rq02_002` / `w4_rq02_011`；
- RQ03：`w4_rq03_004` / `w4_rq03_011`。

因此 60 pair 对应 57 个 OpenAlex records，canonicalize 后约 55 个论文实体。本次不修改冻结
pool、不静默删除 alias、不扩大 dedup；未来可另建 canonicalized/sensitivity v0.2。

## Strict evaluator 与实验复现

旧 `--labels` 入口继续支持 smoke/partial evaluation，不能当作正式 W5 实验。正式模式要求：

```powershell
python -m app.evaluate_w4_benchmark --strict `
  --benchmark-manifest <approved-manifest.json> `
  --output-dir <experiment-output-dir>
```

Strict 会拒绝非 60/60、每 RQ 非 20/20、缺失/未知/重复 pair、`?`/空/非法 final label、
未 approved package，以及 candidate/query/source 等冻结 hash 漂移。成功的正式实验必须生成
`experiment_manifest.json`，记录 Git revision/dirty state、benchmark version/hash、输入 hash、
reference year、实际方法配置、时间和输出文件 hash。

## 当前验证

- 六个 annotation validator：全部通过；
- Agreement Analyzer：`complete`，30/30 comparable，3 个 disagreement；
- agreement/evaluator/strict validator 定向测试：74 项通过；
- 全量离线自动测试：290 项通过，0 failure / 0 error / 0 skipped；
- Basic Quality Gate：扫描 226 个文件，0 error / 0 warning，PASSED；
- Full Quality Gate：扫描 226 个文件，0 error / 3 个既有历史 warning，PASSED；
- 所有测试使用本地 fixture 或已提交样例，没有新增 live 请求。

Full Gate 的三个 warning 与此前公共基线一致：W1 一处历史 CSV 结构问题、
`data/manual/relevance_labels_w1.csv` 的 19 个旧 ID 未对齐当前统一样例、一个历史已跟踪
experiment `openalex_stellar_spectra_60`。本次没有修改这些历史 evidence，也没有新增 warning。

## 下一步（进入 W5 前的最小人工工作）

1. 独立 reviewer 对 3 个 proposal 逐条 approve 或 modify，并记录 final label、姓名、时间和说明；
2. 核对贾馥诚的“人工判断 + AI assistance” provenance，不补造 GitHub 确认；
3. 复制为新的无 draft 版本，更新 version/status/artifact hashes；
4. 运行默认 strict benchmark validator；
5. 人工检查本分支完整 diff，合并后再从最新 `main` 开始 W5 算法实验；
6. W5 比较固定同一 candidate/query/benchmark/reference year，不查看当前 label 调权重。

在上述 1–4 完成前，可以审查协议和运行 smoke/partial 测试，但不得把当前 draft 作为 approved
benchmark 或据此宣布算法优劣。
