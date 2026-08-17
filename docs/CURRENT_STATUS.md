# 当前项目状态

更新时间：2026-08-17

W5 Contract 的已核对前置基线：`d558a088`（PR #48 已合并）。

W5 Method Ranking Contract v1.0 已建立，作为六名成员并行开发的公共接口。当前公共 `main`
的准确 HEAD 不在文档中预写；接手任务时必须以当前 `git log`、`origin/main` 和 GitHub 为准。

v0.3.0 tag 仍指向较早的 W2 发布基线 `899f745`；不能用旧 tag、`d558a088` 前置基线或旧文档
快照替代当前 Git/源码/测试事实。

## AI / 新成员接手入口

开始新任务前依次阅读：

1. 根目录 [`AGENTS.md`](../AGENTS.md)；
2. [`AI_PROJECT_ONBOARDING.md`](project/AI_PROJECT_ONBOARDING.md)；
3. 本页和当前 Issue；
4. benchmark/W5 实验任务继续阅读
   [`W4_PILOT_BENCHMARK_PROTOCOL.md`](project/W4_PILOT_BENCHMARK_PROTOCOL.md) 和
   [`W5_METHOD_RANKING_CONTRACT.md`](project/W5_METHOD_RANKING_CONTRACT.md)。

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

`data/benchmarks/w4_query_relevance/v0.1.0/`

准确状态是 **approved**，正式版本为 `w4_query_relevance_pilot_v0.1.0`：

- 评价目标仅为 Query Relevance；标签为 `0/1/2` graded relevance；
- 共 60/60 record-level query-paper pair，每个 Research Query 20/20；
- 30 条来自 primary single annotation，27 条来自双标一致，3 条来自原始 disagreement；
- 独立 Blind AI Audit 在读取人工答案前完成并冻结；与 57 条当时可用 human final label 比较后，
  54 条一致、3 条不一致；当时其余 3 条尚无原始 human final label；
- 六条 review queue 均由非该 pair 原 annotator 的人类 reviewer 完成：3 条原 disagreement
  proposal 获 approve，3 条既有 judgement 经明确 `modify` 决定更新；
- 所有 60 条 final label 均为 `0/1/2`，无 `?`、空值或 `pending_human_review`；
- manifest 固定 candidate pool、assignment、query config、来源样例、pool manifest、六人
  annotation、judgements、proposals 和 Blind AI Audit provenance 的 SHA-256，并记录完整冻结
  `input_set_identity`；
- approved manifest 绑定被审核 parent draft；manifest SHA-256 为
  `d503f5c2448409a9433bf3ffeada3890c7ddb31237bc7c95c529014b5fb8d094`。

陈星妤的 15 条已由本人实际审核确认；本次只修正 review provenance，不改变其标签。贾馥诚
的标签是带逐行 AI assistance 记录的人工判断；团队已核对该 provenance，仓库仍不声称存在
GitHub 本人再确认记录。

默认 `python -m app.validate_w4_benchmark` 是 strict，只接受 approved、无 draft 后缀、
60/60 final label、完整人工 adjudication/approval checklist 和冻结 hash 完全匹配的 package。
当前 approved package 已通过 strict validator；保留的 parent draft 仍只能用 `--allow-draft`
做结构复核，正式 evaluator 会拒绝 draft。

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
  --benchmark-manifest data/benchmarks/w4_query_relevance/v0.1.0/manifest.json `
  --output-dir <experiment-output-dir>
```

Strict 会拒绝非 60/60、每 RQ 非 20/20、缺失/未知/重复 pair、`?`/空/非法 final label、
未 approved package、分歧缺少完整 human reviewer/decision/time/note、proposal 与原 annotation
provenance 不一致，以及 candidate/query/source 等冻结 hash 漂移。冻结输入同时修改并刷新
package 自报 hash 仍会被 package 外 trust anchor 和 pool manifest 交叉验证拒绝。

正式 evaluator 在任何输出前采集 Git 状态，拒绝 dirty 或无法确认 clean 的工作树；strict
reference year 强制继承 approved benchmark。成功运行必须生成 `experiment_manifest.json`，记录
Git revision/clean state、Python/依赖/平台、benchmark version/hash/input identity/parent draft、
输入 hash、reference year、实际方法配置、时间和输出文件 hash。

## W5 Method Ranking Contract v1.0

W5 的公共实验边界是固定 60-pair Candidate Pool 内的 Query-Relevance ranking/reranking，
不是端到端 retrieval recall benchmark。公共 contract v1.0 规定每个方法输出严格五列：
`pair_id,research_query_id,method_id,score,rank`；每个 RQ 恰好 20 条，score 统一
higher-is-better，并以 `score desc → pair_id asc` 确定性排序。

每个正式方法还必须配套 manifest，记录算法族、参数、模型/revision/adapter、冻结输入及
ranking hash、Git clean revision、Python/平台/依赖、运行时间和 label-access 声明。算法生成阶段
不得读取 approved benchmark label/judgement；参数和 artifact 必须先冻结再进入评价。

`src.w5_method_contract` 和 `app.validate_w5_method` 提供公共 validator；
`evaluate_contract_ranking()` 是现有 W4 evaluator 的最小算法无关 adapter。两个无标签 fixture
位于 `tests/fixtures/w5_method_contract/`，使 RRF、Error Analysis 和 CI 不必等待真实排序器。
完整协议见 [`W5_METHOD_RANKING_CONTRACT.md`](project/W5_METHOD_RANKING_CONTRACT.md)。

## 当前验证

- 六个 annotation validator：全部通过；
- Agreement Analyzer：`complete`，30/30 comparable，3 个 disagreement；
- approved benchmark strict validator：60/60，通过；
- W4 validator 默认 approved / 显式 draft strict / draft review 入口：4 项回归测试通过；
- W5 method contract / validator / evaluator adapter 定向测试：21 项通过；
- agreement/evaluator/strict validator/W5 contract 相关定向测试：111 项通过；
- 全量离线自动测试：327 项通过，0 failure / 0 error / 0 skipped；
- Basic Quality Gate：扫描 242 个文件，0 error / 0 warning，PASSED；
- Full Quality Gate：扫描 242 个文件，0 error / 3 个既有历史 warning，PASSED；
- 所有测试使用本地 fixture 或已提交样例，没有新增 live 请求。

Full Gate 的三个 warning 与此前公共基线一致：W1 一处历史 CSV 结构问题、
`data/manual/relevance_labels_w1.csv` 的 19 个旧 ID 未对齐当前统一样例、一个历史已跟踪
experiment `openalex_stellar_spectra_60`。本次没有修改这些历史 evidence，也没有新增 warning。

## 下一步

1. 六个 W5 Issue 从包含 Contract v1.0 的最新 `main` 独立开分支；
2. 正式方法先生成并冻结通过 validator 的 artifact，再使用 approved benchmark 评价；
3. W5 比较固定同一 candidate/query/benchmark，不查看当前 label 调参数或挑选 run；
4. 继续把该集合准确表述为 **human annotation + independent blind AI evidence audit + human
   review/adjudication**，不称为 gold standard、expert ground truth 或 pure human ground truth。
