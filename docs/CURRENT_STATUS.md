# 当前项目状态

更新时间：2026-09-01

本次只读核对的公共 `origin/main` 为
`d5dc7bfc6b24146dfc64b8452ec8ef7731acf990`（PR #79）。Pilot v0.2
Selection/Context 与 RCP-v0.3 pre-execution infrastructure 已随 PR #79 进入 `main`；实时远端状态
仍须在每次接手任务时重新 fetch/GitHub 核对。

W5 Method Ranking Contract v1.1 已建立并向后兼容 v1.0。v1.1 只用于完整声明 B0/B1 的冻结
source sample 输入；BM25、SPECTER2、Cross-Encoder 与 RRF 的 v1.0 package 继续有效。
当前公共 `main` 的准确 HEAD 仍必须在接手任务时用 `git log`、`origin/main` 和 GitHub 核对。

v0.3.0 tag 仍指向较早的 W2 发布基线 `899f745`；不能用旧 tag、`d558a088` 前置基线或旧文档
快照替代当前 Git/源码/测试事实。

## AI / 新成员接手入口

开始新任务前依次阅读：

1. 根目录 [`AGENTS.md`](../AGENTS.md)；
2. [`AI_PROJECT_ONBOARDING.md`](project/AI_PROJECT_ONBOARDING.md)；
3. 本页和当前 Issue；
4. benchmark/W5 实验任务继续阅读
   [`W4_PILOT_BENCHMARK_PROTOCOL.md`](project/W4_PILOT_BENCHMARK_PROTOCOL.md) 和
   [`W5_METHOD_RANKING_CONTRACT.md`](project/W5_METHOD_RANKING_CONTRACT.md)；
5. W6 任务继续阅读
   [`W6_RESEARCH_CONTRACT_AND_PARALLEL_BOOTSTRAP.md`](project/W6_RESEARCH_CONTRACT_AND_PARALLEL_BOOTSTRAP.md)。

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

## W5 Method Ranking Contract v1.1 与正式 artifact

W5 的公共实验边界是固定 60-pair Candidate Pool 内的 Query-Relevance ranking/reranking，
不是端到端 retrieval recall benchmark。公共 contract v1.0 规定每个方法输出严格五列：
`pair_id,research_query_id,method_id,score,rank`；每个 RQ 恰好 20 条，score 统一
higher-is-better，并以 `score desc → pair_id asc` 确定性排序。

每个正式方法还必须配套 manifest，记录算法族、参数、模型/revision/adapter、冻结输入及
ranking hash、Git clean revision、Python/平台/依赖、运行时间和 label-access 声明。算法生成阶段
不得读取 approved benchmark label/judgement；参数和 artifact 必须先冻结再进入评价。

Post-merge 审计确认 B0/B1 还真实依赖冻结 W2 source sample 中的引用量等字段。Contract v1.1
增加严格受 trust anchor 校验的 `source_sample` 输入；B0/B1 ranking hash 未改变，只重冻
manifest。官方 B0/B1 method ID 已强制绑定 v1.1，不能通过自报 v1.0 省略该输入；其他方法保持
v1.0 backward compatibility。

当前正式目录有 6 个通过 validator 的 package：

- `preliminary_score_v1`；
- `tfidf_two_stage_v1`；
- `bm25_v1`；
- `specter2_adhoc_v1`；
- `cross_encoder_msmarco_v1`；
- `rrf_bm25_specter2_v1`（固定 BM25 + SPECTER2，`k=60`）。

`src.w5_method_contract` 和 `app.validate_w5_method` 提供公共 validator；
`evaluate_contract_ranking()` 是现有 W4 evaluator 的最小算法无关 adapter。两个无标签 fixture
位于 `tests/fixtures/w5_method_contract/`，使 RRF、Error Analysis 和 CI 不必等待真实排序器。
完整协议见 [`W5_METHOD_RANKING_CONTRACT.md`](project/W5_METHOD_RANKING_CONTRACT.md)。

## W5 正式统一实验

正式评价在所有 6 个 artifact 冻结后，于 clean revision `c11f0f4` 执行。Benchmark 为 approved
`w4_query_relevance_pilot_v0.1.0`，manifest SHA-256 为
`d503f5c2448409a9433bf3ffeada3890c7ddb31237bc7c95c529014b5fb8d094`。

Macro 结果：

| method | NDCG@5 | NDCG@10 | P@5 | P@10 |
| --- | ---: | ---: | ---: | ---: |
| B0 | 0.1293 | 0.2647 | 0.1333 | 0.2333 |
| TF-IDF two-stage | 0.3727 | 0.4559 | 0.2667 | 0.2667 |
| BM25 | 0.5400 | 0.6095 | 0.4000 | 0.3000 |
| SPECTER2 | 0.5776 | 0.6958 | 0.4000 | 0.4000 |
| Cross-Encoder | 0.4570 | 0.5298 | 0.4000 | 0.3333 |
| RRF | 0.6115 | 0.6859 | 0.4667 | 0.3667 |

RRF 的互补收益集中于 RQ02/Top5；macro NDCG@10 仍低于 SPECTER2，不能表述为全面最优。
正式 metrics、manifest、Error Analysis 与完整科研边界见
[`W5_FINAL_INTEGRATION_AND_EXPERIMENT.md`](reports/week5/W5_FINAL_INTEGRATION_AND_EXPERIMENT.md)。

## W6 Research Contract & Parallel Development Bootstrap

W6 Bootstrap 只建立六人独立开发所需的公共接口，不选择真实 Topic、不生成真实 Candidate Pool、
annotation、hidden labels、ranking、synthesis 或 Benchmark v0.2-alpha。当前新增：

- 任意 topic 数量的 Research Topic、retrieval run/hit provenance、source record、canonical
  entity/alias、pre/post canonicalization Candidate Pool 和 deterministic identity contracts；
- 与 pool/retriever/rank identity 解耦的 opaque annotation item/mapping、blind view，以及
  AI-assisted annotation/review provenance；
- 在 annotation start 前实际冻结并以 hash 绑定的 topic-level Dev/Hidden split，以及只接受
  sealed 状态的 external hidden-label hash anchor；Bootstrap 不提供 reveal API/仓内 label 文件；
- 保持 W5 五列/排序语义、不修改 W5 frozen artifact 的 dynamic-pool method extension；
- 共同 topic/pool 输入加受限 method-specific auxiliary inputs，以及多冻结 method input 的 raw
  score/rank/hash/normalization/weights extension point；正式 fusion 至少需要两个输入；
- frozen ranking selection + short evidence unit + input-hash-bound structured claim/render contract；
- 2 fake topics、10 fake source records、13 pool items 的 pre/post 两个视图、3 fake rankings 及
  valid/invalid offline fixtures；
- 六个 future task 全部只依赖 `Bootstrap + current main + 对应 fixtures`；测试会对每个任务仅复制
  声明 artifacts 做独立 load/validate/smoke，并验证缺文件 fail closed。真实跨模块运行留给独立
  Integration PR。

公共 validator：

```powershell
python -m app.validate_w6_bootstrap
```

详细字段、no-leakage、目录、fixture 和 Parallel Development Matrix 见 W6 Bootstrap 文档。Fixture
Benchmark status 为 `bootstrap_fixture`；仓库没有真实 W6 hidden labels，也没有批准的 W6
Benchmark v0.2-alpha。

### PR #71 历史 merge-candidate 快照（现已进入 main）

以下内容保留 2026-08-26 当时的审计边界，不能再用“尚未进入 main”解释当前仓库。PR #71
及随后列于当前 Git 历史的 W6 integration PR 已合并；具体当前能力必须以源码、committed
artifacts 和 validators 重新核对。

`feature/w6-benchmark-boundary-aware` 上的 PR #71 在公共 Bootstrap 之上形成了以下待合并成果：

- 已完成并冻结 9 个真实 Research Topics；候选 roster、viability evidence、淘汰理由与 freeze 决策
  记录于 W6 research artifact/report；
- 已冻结 topic-level Dev 5 / Hidden 4 split，9 个 Topic 无遗漏、无交叉，`reveal_state=sealed`；
- 已冻结 AI-assisted annotation、second annotation、review/adjudication protocol；仓库仍没有真实
  Hidden labels；
- 已完成 Boundary-Aware 候选方案比较并冻结 structured lexical prototype；当前 committed Benchmark
  package 仍是 `bootstrap_fixture`，不冒充真实 W6 Benchmark；
- 在 Topic/split freeze 后另行冻结 54 个 OpenAlex query，形成 54 query runs、4,265 query hits、
  3,439 topic-work assignments 和 2,977 unique Works 的 broad/raw acquisition corpus；它不是 final
  Benchmark Pool、canonical entity set、labelled dataset 或 Hidden evaluation set；
- OpenAlex package validator 已绑定 pre-acquisition config artifact identity 与 exact SHA-256，并从
  frozen config 重算 query/run/hit/work/count/chronology/完整 Topic Audit provenance closure。Git
  commit `59f4587` 提供 freeze 先于 acquisition 的外部 chronology anchor；package 内部 hashes 本身
  不被描述成可抵抗 config 与 package 整体重新包装的外部 trust anchor。

PR #71 没有修改 W4 approved Benchmark、W5 frozen method artifacts/metrics/error analysis，也没有重新
采集或改写 9 Topics、Dev/Hidden split、54 queries 或 2,977-Work corpus。

真实 W6 Integration 仍未完成：Multi-Retriever pooling、enrichment、exact-ID 之后的受控
canonicalization、final pool selection、blind annotation/second annotation/review/adjudication、正式
method/fusion generation、sealed Hidden evaluation 与 synthesis 均属于后续工作。

## Pilot v0.2 Selection / Context 与 RCP 当前状态

公共 `main` 已包含两个 Dev Topic 的 frozen canonical U80、Pilot Selection/Context 与
RCP-v0.3 pre-execution infrastructure（PR #79）：

- BM25 Lexical Selection、Dual-Curator tooling、generic Selection Artifact 和 method-agnostic
  Matched Context Builder；
- committed Dual-Curator `selection-preparation-v1`，状态仍为 `prepared_not_started`；
- RCP-v0.3 AI-assisted internal Reference infrastructure：versioned prompt/config、3 Core + 2
  Sentinel roster contract、one-candidate task export、strict judgement import、safe-zero/routing、
  blind H1/H2/R3、safe-zero audit、blind cutoff、final Reference、Reference-bound BM25 与 formal
  pair validation；
- committed RCP preparation package，状态为 `prepared_not_started`，真实 roster 尚未冻结。

Versioned RCP-v0.3.1 external-agent-runner package 仍为 `prepared_not_started`；它只放宽诚实声明
snapshot unavailable 的 Primary runner provenance，不启动真实执行。

当前没有真实模型 judgement、真实人类 review、正式 Reference Top-8、正式 BM25 Top-8、matched
experimental context 或 synthesis output。RCP 的正确 claim 仅为未来的 **auditable internal
reference selection**，不是 astronomy expert gold/ground truth。完整边界与真实执行 checkpoint 见
[`PILOT_V0_3_REFERENCE_CURATION_PROTOCOL.md`](project/PILOT_V0_3_REFERENCE_CURATION_PROTOCOL.md) 与
[`RCP-v0.3.1 addendum`](project/PILOT_V0_3_1_REFERENCE_CURATION_PROTOCOL.md)。

## 当前验证

以下是 PR #71 merge candidate（含 OpenAlex provenance-closure P1 修复）的 2026-08-26 历史验证
快照，不是当前公共 `main` 或本地 Pilot/RCP 分支的测试快照：

- approved benchmark strict validator：60/60、20 × 3，通过；
- 正式 W5 artifact checker：精确六方法 roster 6/6，通过；
- W6 public bundle validator：2 topics、10 source records、13 pool items、3 method packages，通过；
- W6 Topic validator：9 Topics、Dev 5 / Hidden 4、split identity 匹配；
- committed Issue #64 Benchmark validator：`bootstrap_fixture`、2 Topics、13 pool items、4 synthetic
  annotations，通过；
- committed OpenAlex package validator：54 runs、2,977 Works、4,265 hits，受信 config、deterministic
  IDs、rank/count、chronology、Work reverse provenance 与完整 Topic Audit closure 通过；
- OpenAlex package adversarial/audit tests：31/31；OpenAlex client + package tests：52/52；
- W6 contracts/Benchmark/Boundary/OpenAlex package/client：143 tests，141 PASS / 2 个 Windows
  symlink privilege 条件性 skip；Issue #64 Benchmark/Boundary 定向 tests：43 tests，41 PASS / 2 skip；
- W4/W5 regressions：164/164；
- 全量离线测试：568 tests，566 PASS / 2 skip，0 failure / 0 error；
- Basic Quality Gate：扫描 376 个文件，0 error / 0 warning，PASSED；
- Full Quality Gate：扫描 376 个文件，0 error / 3 个既有历史 warning，PASSED；
- experiment metrics 与六个 method manifest hash 复核一致；`git diff --check` 通过；
- 所有测试使用本地 fixture、临时 self-consistent mutations 或已提交 package，没有新增 OpenAlex live
  请求或神经模型推理。

Full Gate 的三个 warning 与此前公共基线一致：W1 一处历史 CSV 结构问题、
`data/manual/relevance_labels_w1.csv` 的 19 个旧 ID 未对齐当前统一样例、一个历史已跟踪
experiment `openalex_stellar_spectra_60`。本次没有修改这些历史 evidence，也没有新增 warning。

## W6 后续 Issue 保留的研究决策

PR #71 已完成 Topic freeze、topic-level Dev/Hidden split、annotation/review policy 与 Boundary-Aware
prototype preregistration。仍待真实 Integration/后续 Issue 完成：

1. multi-retriever roster、pool depth/target/minimum、pooling 与 enrichment 执行；
2. exact OpenAlex ID 之外的受控 canonicalization、alias review 与 final Benchmark Pool freeze；
3. blind annotation、20% second annotation、human review/adjudication 的实际执行与 provenance 验收；
4. independent hidden-label custodian、external anchor 与一次性 reveal/evaluation 流程；
5. frozen real method/fusion inputs、Boundary-Aware Integration 与 Dev-only method selection；
6. synthesis LLM/backend、证据抽取许可与人工事实核验。

不得根据当前正式指标回调参数后仍冒充同一次冻结实验；不得自行创建 W6 Issue。
