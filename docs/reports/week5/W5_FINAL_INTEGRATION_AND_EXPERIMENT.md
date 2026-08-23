# W5 Post-Merge 最终集成、正式实验与 Error Analysis 报告

日期：2026-08-24

实验性质：固定 60-pair Candidate Pool 上的 Query-Relevance ranking/reranking

收口基线：`origin/main=d71132f040b6a81ea1c5ed4611c031eb99ac23f3`

正式评价 revision：`c11f0f4fbd2c7ed8057d124eefe1193764227948`（clean）

## 1. 结论摘要

六个 W5 PR #56–#61 已全部进入 `main`，合并后的实现、测试、validator、CI、multi-method
runner 与 Error Analysis 可以形成一条统一链，但初始状态尚未形成完整正式闭环：

1. B0/B1 的真实评分依赖冻结 W2 source sample，Contract v1.0 manifest 未声明该输入；
2. RRF 只有通用实现和 fixture 测试，没有合并后真实 BM25 + SPECTER2 正式 package；
3. `CURRENT_STATUS` 与 onboarding 仍停留在 W5 Bootstrap 前，不能代表当前源码事实。

本次以向后兼容的 Contract v1.1 修复 B0/B1 输入闭包，未修改任何 baseline 公式或 ranking；
随后在 clean revision 上重冻 B0/B1、生成预注册 `BM25 + SPECTER2, k=60` RRF，并在所有六个
artifact 冻结后才读取 Approved Benchmark 运行统一评价和 Error Analysis。

在当前固定池上，RRF 的 macro NDCG@5 与 Precision@5 最高，但 macro NDCG@10 略低于
SPECTER2。其收益主要来自 RQ02；在 RQ01/RQ03 上，query boundary、wrong task/modality 和
semantic false positive 仍未解决。因此当前证据支持“存在局部互补价值”，不支持“RRF 或任一
模型普遍最优”。

## 2. Repository / GitHub Post-Merge 状态

- 起始本地 `main`、刚 fetch 的 `origin/main` 与 GitHub `main` 均为 `d71132f`；初始工作树 clean；
- #56 BM25、#57 RRF、#58 SPECTER2/runner、#59 CI、#60 Cross-Encoder、#61 Error Analysis
  均为 `MERGED`；
- 核验时 GitHub 没有 open PR 或 open Issue；
- `main@d71132f` 的最近 W5 CI run
  [32650578884](https://github.com/ZicanLiu/ai-literature-intelligence/actions/runs/32650578884)
  状态为 success；
- 所有原正式 artifact 的 generation revision 均存在且是当前 HEAD 的 ancestor；
- 本次从同步且干净的 `main` 创建 `codex/w5-post-merge-closure`，未在用户 `main` 上开发，
  未 push、merge、tag 或 release。

## 3. Post-Merge Audit Findings

### P0

无。未发现 benchmark judgement 漂移、60/60 identity 破坏、label 泄漏、same-paper alias
静默删除或正式 artifact ranking hash 损坏。

### P1

#### P1-1：B0/B1 generation input closure 不完整

`preliminary_score_v1` 与 `tfidf_two_stage_v1` 实际调用
`src.w4_benchmark_evaluation.rank_query_papers()`，需要从
`data/samples/w2/domain_query/live_query_sample.csv` 补回 `cited_by_count`、`authors`、
`source_name` 等字段。只改变该 source sample 的引用量即可改变 B0/B1 score/rank，因此它是
真实 generation input，而不是仅供展示的 provenance。

原 v1.0 manifest 只声明 Candidate Pool + Research Query，虽然旧 validator 会 PASS，但输入闭包
不足以独立解释和复现 ranking。该问题不影响 BM25、SPECTER2、Cross-Encoder 或 RRF，它们只读
两个公共输入。

#### P1-2：缺失正式 RRF package

PR #57 有完整通用 RRF 实现、固定 `k=60` 和 fixture 测试，但按设计把真实 BM25 + SPECTER2
融合留给 post-merge owner。初始正式目录只有 5 个 package，无法完成提示要求的六方法正式比较。

### P2

#### P2-1：状态文档落后于代码

`docs/CURRENT_STATUS.md` 和 onboarding 仍把 W5 候选方法写成尚未实现或待六人开发，与
`main@d71132f` 冲突。本文及同步状态更新以当前代码、artifact 和实测为准。

#### P2-2：Error taxonomy evidence 覆盖有限

当前 taxonomy 有人工/冻结 evidence 的 pair 为 20/60；40/60 必须保持 `unclassified`。这不是
工具错误，但限制了 method-family failure interpretation 的覆盖率。

## 4. 必要修复

### 4.1 Contract v1.1（向后兼容）

- v1.0 继续严格接受 `candidate_pool + research_queries`，现有 BM25、SPECTER2、
  Cross-Encoder、RRF 无需迁移；
- v1.1 精确要求第三个 `source_sample`，并对 path、SHA-256 和版本
  `w2_live_query_sample_v1` 使用现有 W4 trust anchor 校验；
- multi-method runner 只比较所有方法共同的 Candidate Pool / Research Query identity，不再要求
  无关方法伪造相同辅助输入；
- RRF 输出只继承两个公共输入，辅助输入不会被错误传播到 hybrid package。

这是最小方案：没有改变 W4 package、Candidate Pool、Research Query、source sample、B0/B1
算法、任何模型参数或评价指标。

### 4.2 Artifact migration / freeze 范围

- 重冻：B0、B1 manifest；ranking hash 与迁移前完全相同；
- 新增：`rrf_bm25_specter2_v1`；
- 不重冻：BM25、SPECTER2、Cross-Encoder；其代码、参数、模型 revision、ranking 与 manifest
  保持原冻结状态。

## 5. 最终 Method Artifact Inventory

所有 package 均覆盖 60/60 pair、每 RQ 20/20，按 `score desc → pair_id asc` 确定性排序，保留
两对 same-paper alias，且声明 generation 未读取 benchmark labels。

| method_id | Contract / family | frozen configuration | generation revision | ranking SHA-256 | manifest SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `preliminary_score_v1` | v1.1 / baseline | weights 0.4/0.3/0.2/0.1；reference year 2026 | `11dd37379301cdb6f599954cc8b31cebf77a9da1` | `0fdd1679405322ccc623f4f528e153e3c251d2f44aed2aaa661f37b1f1e7b9d5` | `b22c8a197add530957336d51388b993cc98dfad63113ae544b5b19b79596779b` |
| `tfidf_two_stage_v1` | v1.1 / baseline | title/abstract 0.7/0.3；Stage1 0.2/0.05；Stage2 0.5/0.25/0.15/0.1 | `11dd37379301cdb6f599954cc8b31cebf77a9da1` | `29188a495e9e05cdb8853fb5bd3bf3b22972e5cba8b84b4a6724575e74c84df5` | `7190b20fad0692995fbbe665d9aa6f9de66e2f8ab8f6c3f4d1b652e1a8bc4f4c` |
| `bm25_v1` | v1.0 / sparse | `k1=1.5`、`b=0.75`、title+abstract、60-record corpus | `ecfb23c6e8fb916c7c2ffcd6c33c4b06287d5c62` | `4594272eb56ee6463efe31bb270041e01f2ba313a33d98d840162df33a28992c` | `3730a6486bf69995772d809d8ec9e9816fc6759d8c500fb0a11394830ec34195` |
| `specter2_adhoc_v1` | v1.0 / dense | SPECTER2 base + adhoc query/proximity paper adapters；negative Euclidean | `2e879e5c5c27c342f22e642a5cad00e4cd6dcccc` | `7bd205cfaa8ecb559e4a90fee0583dceb18a3ef8ef1f1bcbb0a632ea837b575b` | `a917bfb3ed545428441bdd9d821f179ae96ddb9abeeb4ca11458c300d641fbee` |
| `cross_encoder_msmarco_v1` | v1.0 / neural | `cross-encoder/ms-marco-MiniLM-L6-v2@233902d...`；raw logit | `c8be0550be8b180f51356987d44d70ff9f40c8ce` | `2562de52955ecfba552fe6a465c5cd0996c0018c75ae5b75f4a1092f2976b241` | `4a7b34a2b5689df1e4d5b3d8ae5c13a6925a589432ae7fc070e3a34d9e5694fb` |
| `rrf_bm25_specter2_v1` | v1.0 / hybrid | BM25 + SPECTER2；RRF `k=60`；order-independent | `11dd37379301cdb6f599954cc8b31cebf77a9da1` | `70cbbf1436f9b92aa39f9b325c77eddfb4ba94a9f33196dce692d7b40b32b5a5` | `1ce0ef37c06083ab5499bb722f61083b7175db683345e35eb54259aa0299d9c8` |

SPECTER2 与 Cross-Encoder 均固定到 exact model revision。冻结池有 3 条缺摘要
（`w4_rq01_017`、`w4_rq02_001`、`w4_rq02_015`）；BM25、SPECTER2、Cross-Encoder 均使用
已声明的 title-only fallback，不删除 pair。

## 6. 正式统一实验配置与 Provenance

- Benchmark：`w4_query_relevance_pilot_v0.1.0`，status `approved`；
- Benchmark manifest SHA-256：
  `d503f5c2448409a9433bf3ffeada3890c7ddb31237bc7c95c529014b5fb8d094`；
- input set identity：
  `sha256:dff3f396c6ae5ac1614bfdedcdaacec845e65e8522f5967ca668d2dd9e2ecc88`；
- scope：固定 60-pair、20 × 3 RQ、record-level；
- label：0/1/2 graded relevance；60/60 approved labels；
- metrics：judged-condensed NDCG@5/10、Precision@5/10、Coverage@5/10、irrelevant Top-K；
- 正式运行 Git revision：`c11f0f4fbd2c7ed8057d124eefe1193764227948`；
- Git dirty：`false`；
- 环境：CPython 3.13.9，Windows 11 AMD64；requirements SHA-256
  `2b728b84c305568201523b267ac67f9aaac1bdd66cdda4d6b929decc20b2e1fa`；
- metrics SHA-256：`0d63c530a4291350338b129e515bf14653e6f266297553a90ddd96fec21bd713`；
- experiment manifest SHA-256：
  `7705d920a6b3cae1a656fb7df8c00ff0d7f6ed30062c9d73782d5db9e5a8df62`。

严格顺序为：验证全部 method artifact → strict 验证 approved benchmark → 连接 label → 评价。
正式指标产生后没有重新生成或调整任何 method artifact。

## 7. Per-RQ Metrics

Coverage@5 与 Coverage@10 对所有方法/RQ 均为 `1.0`，因为 approved benchmark 完整覆盖固定池。
下表 `I@5/I@10` 是原 Top-K 中 final label=0 的数量。

| Method | RQ | NDCG@5 | NDCG@10 | P@5 | P@10 | I@5 | I@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | RQ01 classification | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 5 | 10 |
| B0 | RQ02 parameters | 0.3878 | 0.4634 | 0.4000 | 0.5000 | 3 | 5 |
| B0 | RQ03 preprocessing | 0.0000 | 0.3306 | 0.0000 | 0.2000 | 5 | 8 |
| TF-IDF two-stage | RQ01 classification | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 5 | 10 |
| TF-IDF two-stage | RQ02 parameters | 0.5969 | 0.7483 | 0.6000 | 0.6000 | 2 | 4 |
| TF-IDF two-stage | RQ03 preprocessing | 0.5213 | 0.6194 | 0.2000 | 0.2000 | 4 | 8 |
| BM25 | RQ01 classification | 0.1510 | 0.3870 | 0.2000 | 0.3000 | 4 | 7 |
| BM25 | RQ02 parameters | 0.6427 | 0.6153 | 0.8000 | 0.5000 | 1 | 5 |
| BM25 | RQ03 preprocessing | 0.8262 | 0.8262 | 0.2000 | 0.1000 | 4 | 9 |
| SPECTER2 | RQ01 classification | 0.1952 | 0.4382 | 0.2000 | 0.3000 | 4 | 7 |
| SPECTER2 | RQ02 parameters | 0.7113 | 0.8230 | 0.8000 | 0.8000 | 1 | 2 |
| SPECTER2 | RQ03 preprocessing | 0.8262 | 0.8262 | 0.2000 | 0.1000 | 4 | 9 |
| Cross-Encoder | RQ01 classification | 0.1510 | 0.2811 | 0.2000 | 0.2000 | 4 | 8 |
| Cross-Encoder | RQ02 parameters | 0.6985 | 0.7869 | 0.8000 | 0.7000 | 1 | 3 |
| Cross-Encoder | RQ03 preprocessing | 0.5213 | 0.5213 | 0.2000 | 0.1000 | 4 | 9 |
| RRF | RQ01 classification | 0.1510 | 0.4043 | 0.2000 | 0.3000 | 4 | 7 |
| RRF | RQ02 parameters | 0.8573 | 0.8271 | 1.0000 | 0.7000 | 0 | 3 |
| RRF | RQ03 preprocessing | 0.8262 | 0.8262 | 0.2000 | 0.1000 | 4 | 9 |

RQ01 的 20 条中只有 4 条 label=2、16 条 label=0；RQ03 只有 1 条 label=2、1 条 label=1、
18 条 label=0。当前 P@K 与 NDCG 必须结合这种小且不均衡的每-RQ label 分布解释。

## 8. Macro Metrics

| Method | NDCG@5 | NDCG@10 | P@5 | P@10 | mean I@5 | mean I@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 preliminary_score | 0.1293 | 0.2647 | 0.1333 | 0.2333 | 4.3333 | 7.6667 |
| TF-IDF two-stage | 0.3727 | 0.4559 | 0.2667 | 0.2667 | 3.6667 | 7.3333 |
| BM25 | 0.5400 | 0.6095 | 0.4000 | 0.3000 | 3.0000 | 7.0000 |
| SPECTER2 | 0.5776 | 0.6958 | 0.4000 | 0.4000 | 3.0000 | 6.0000 |
| Cross-Encoder | 0.4570 | 0.5298 | 0.4000 | 0.3333 | 3.0000 | 6.6667 |
| RRF BM25+SPECTER2 | 0.6115 | 0.6859 | 0.4667 | 0.3667 | 2.6667 | 6.3333 |

这些是同一固定池上的描述性比较，不做显著性检验，也不用于调参或选择新的正式 run。

## 9. Error Analysis

### 9.1 Coverage 与总体错误计数

Taxonomy evidence 为 20/60：6 个 `scope_in`、12 个 `hard_negative`、2 个 `boundary`；其余
40 个保持 `unclassified`。Error Analysis 共输出 360 个 method×pair 行、185 个 case 行、31 个
`rank_shift >= 10` pair。

| Method | irrelevant Top5 | irrelevant Top10 | relevant buried（label=2, rank≥11） | hard negative Top5 | hard negative Top10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 | 13 | 23 | 8 | 4 | 6 |
| TF-IDF two-stage | 11 | 22 | 5 | 2 | 5 |
| BM25 | 9 | 21 | 3 | 4 | 8 |
| SPECTER2 | 9 | 18 | 2 | 1 | 5 |
| Cross-Encoder | 9 | 20 | 3 | 3 | 7 |
| RRF | 8 | 19 | 2 | 1 | 8 |

RRF 把 hard negative Top5 降到 1，但 Top10 仍有 8，说明融合更多是把部分错误向后推，并未消除
边界错误。SPECTER2 的 irrelevant Top10 最少（18），RRF 为 19；这与 RRF 的 NDCG@5 优势、
SPECTER2 的 NDCG@10 优势一致。

### 9.2 Representative disagreement / failure cases

以下 rank 均为各自 RQ 内 1..20，pair 仍按 record-level 计算：

- `w4_rq01_017`，label 2，*Classification of Spectra of Emission Line Stars Using
  Machine Learning Techniques*：SPECTER2 3、Cross-Encoder 5、RRF 5，而 B0 20、TF-IDF 19、
  BM25 10。这是缺摘要 title-only pair；semantic/neural 在当前证据上纠正了 baseline 的 relevant
  buried，但单例不能证明通用同义理解能力。
- `w4_rq02_006`，label 2，*A PCA approach to stellar effective temperatures*：RRF 1、
  BM25 4、SPECTER2/Cross-Encoder 3、TF-IDF 7、B0 18。这里 sparse 与 dense 同向支持，融合把
  相关文献推到首位。
- `w4_rq02_018`，label 2，*The RAVE-on Catalog of Stellar Atmospheric Parameters and
  Chemical Abundances...*：BM25 2、RRF 4、SPECTER2 8、Cross-Encoder 7、TF-IDF 18。
  这是 sparse 明显高于 dense/旧 TF-IDF 的成功案例。
- `w4_rq03_003`，label 0，*Machine Learning Based Automatic Modulation Recognition for
  Wireless Communications...*：B0 1、TF-IDF/BM25 3、Cross-Encoder 10、RRF 11、SPECTER2
  20。SPECTER2 成功压低跨领域 lexical overlap；同一 work 在 RQ01 的 alias pair
  `w4_rq01_014` 也从 B0 2 降至 SPECTER2 20。
- `w4_rq03_018`，label 0，mine water/XGBoost：BM25 2、B0 9、RRF 9，而 SPECTER2 15、
  TF-IDF 16。BM25 被算法词和“spectral/mixed”表面重合吸引；dense 纠正较多，但 RRF 仍把该错误
  留在 Top10。
- `w4_rq02_014`，label 0，*Carbon Stars Identified from LAMOST DR4 Using Machine
  Learning*，taxonomy=`classification_vs_regression`：Cross-Encoder 2、SPECTER2/TF-IDF 4，
  BM25 14，RRF 8。semantic/neural 反而把“恒星+机器学习”但任务边界错误的论文推高。
- `w4_rq03_012`，label 0，*deep-REMAP: Parameterization of Stellar Spectra...*，
  taxonomy=`downstream_task`：Cross-Encoder 3、SPECTER2 6、BM25/RRF 8、B0 17。通用 neural
  语义相似度没有自动解决 preprocessing 与 parameterization 的任务边界。
- `w4_rq01_016`，label 0，taxonomy=`object_classification_vs_stellar_type`：所有方法均在
  Top4，Cross-Encoder/RRF 为 1。该 pair 是当前所有 family 的共同失败。
- `w4_rq03_009`，label 0，*Generating Stellar Spectra Using Neural Networks*，
  taxonomy=`generation_vs_preprocessing`：SPECTER2/RRF 5、BM25/Cross-Encoder 7、TF-IDF 10、
  B0 11。融合继承了 dense 的 query-boundary 错误。

### 9.3 RRF 的互补价值

直接证据显示 RRF 在 RQ02 Top5 有互补价值：P@5=1.0、I@5=0，优于 BM25 与 SPECTER2 各自的
P@5=0.8、I@5=1；NDCG@5=0.8573 也高于两个输入。它还把 overall irrelevant Top5 从两个输入的
9 降到 8。

但互补不是全局的：

- RQ01 的 RRF NDCG@5 与 BM25 相同，NDCG@10 低于 SPECTER2；
- RQ03 的 RRF 指标与 BM25/SPECTER2 相同，未带来可见增益；
- macro NDCG@10 低于 SPECTER2；
- RRF 仍保留 8 个 hard negative Top10，并继承两个明确 boundary 错误。

因此本轮只支持“rank-only fusion 在当前 RQ02/Top5 呈现互补”，不支持“RRF 已解决 sparse/dense
错误”或“hybrid 普遍优于 dense”。

## 10. Reproducibility / CI / Validator 状态

- W4 strict validator：approved，60/60，20 × 3；
- W5 formal artifact checker：6/6 PASS；
- Contract v1.1 / baseline / runner / RRF 定向测试：68/68 PASS；
- CI workflow/checker 定向测试：10/10 PASS；
- 全量离线 unittest：440/440 PASS，0 failure / 0 error；
- Basic Quality Gate：扫描 296 个文件，0 error / 0 warning，PASSED；
- Full Quality Gate：扫描 296 个文件，0 error / 3 个既有历史 warning，PASSED；
- `git diff --check`：PASS；
- experiment metrics hash 与 manifest 声明一致，六个 method manifest hash 均复核一致；
- generation revisions：完整 40 位 SHA、clean 声明，且都在当前 Git 历史中；
- 正式 experiment manifest：记录 Git、Python、platform、requirements/dependencies、benchmark、
  六个 method manifest/ranking hash 与 metrics hash；
- Error Analysis summary：绑定 benchmark、taxonomy source/mapping、六个 method hash 和固定阈值；
- GitHub `main@d71132f` CI：success；本地对收口分支执行同等或更严格的 validator/test/gate；
- 全程未运行 OpenAlex live 请求或重新下载/推理神经模型；未读取 `.env`。

Full Gate 的 3 个 warning 与任务开始前完全相同：W1 历史 CSV 结构、19 个 W1 label ID 未与
当前统一样例对齐、历史已跟踪 experiment `openalex_stellar_spectra_60`。本任务没有修改这些
历史 evidence，也没有引入新 warning。

正式输出：

- `data/analysis/w5_formal_experiment_v1/metrics.csv`；
- `data/analysis/w5_formal_experiment_v1/experiment_manifest.json`；
- `data/analysis/w5_formal_experiment_v1/error_analysis/` 六个结构化分析文件。

## 11. Research Interpretation

### 11.1 Directly supported

- 在这个固定 60-pair pool 和当前 approved labels 上，所有新 W5 方法的 macro NDCG@5/10 均高于
  B0，BM25/SPECTER2/RRF 的幅度尤其明显；
- RQ 与 cutoff 会改变相对结果：RRF 的 Top5 指标最好，SPECTER2 的 macro NDCG@10 最好；
- sparse 与 dense 存在可观察的 rank disagreement，且双方都有独有成功和失败案例；
- RRF 在 RQ02 Top5 显示互补，但未消除 query-boundary/hard-negative 错误；
- B0/B1 的真实复现输入包括冻结 source sample，v1.1 manifest 现在完整声明该事实；
- 当前 taxonomy 只能对 20/60 pair 提供 evidence-backed 类型，40/60 不能自动分类。

### 11.2 Plausible hypotheses（待新证据验证）

- 科学文献专用 dense representation 可能比旧 TF-IDF 更能利用低 lexical-overlap 的标题/摘要；
- 通用 MS MARCO Cross-Encoder 对任务边界的适配不足，可能需要 scientific-domain calibration；
- rank-only RRF 的收益可能集中在 sparse/dense 各自 top ranks 互补的 RQ；normalized-score fusion
  是否更好尚未测试；
- RQ01/RQ03 的极少 relevant labels 与 candidate selection 可能放大单个 pair 对 NDCG/P@K 的影响。

这些都是解释或研究问题，不是本轮数据已经证明的机制。

### 11.3 Not supported

当前结果不能支持：

- 任一方法在完整 OpenAlex 上有更高 retrieval recall；
- 任一方法对其他天文主题、其他学科或大规模独立 test set 普遍更优；
- 该 benchmark 是 astronomy expert gold standard、纯人工 ground truth 或论文价值真值；
- RRF、SPECTER2 或 Cross-Encoder 已解决 hard negative、wrong task、wrong modality；
- 根据本轮结果回调参数、模型、adapter、RRF k 后仍称同一次预注册正式实验；
- 把 record-level alias 静默合并后的指标当作当前 v0.1 正式指标。

## 12. 剩余限制

- 仅 3 个 Research Query、60 pair，per-RQ relevant 分布小且不均衡；
- Candidate Pool 来自单一既有 retrieval sample，存在 selection bias；fixed-pool ranking 无法评价
  未进入池的相关论文；
- 60 pair 对应 57 个 OpenAlex record，并保留两对 known same-paper alias；
- annotation 包含 AI assistance、Blind AI Audit 和 human review/adjudication，主要标注者不是天文
  专家；
- taxonomy 只覆盖 20 pair；
- 该 benchmark 已被成员反复用于 W5 方法评价，继续基于它开发方法会增加 benchmark overfitting
  风险；
- 本轮没有重复神经模型推理，只验证已冻结 ranking、精确 revision、hash 与 provenance。

## 13. 下一阶段只需决策的问题

1. 是否先扩大 Research Query 与独立 benchmark，而不是继续在当前 60 pair 上调参？
2. 是否采用 multi-retriever pooling 建立真正能评价 retrieval recall 的候选池？
3. 是否需要天文专家 calibration，优先复核 query-boundary 与当前 unclassified 高位错误？
4. 是否应建立一次性盲 test split，降低继续使用当前 Pilot 造成的 overfitting？
5. RRF 的局部收益是否值得在新 benchmark 上预注册比较 normalized-score fusion，而不是在当前
   labels 上试权重？
6. Error Analysis 是否足以支持一个聚焦 task/modality boundary 的自研改进问题？
7. 若进入 evidence-grounded literature synthesis，是否先单独定义证据抽取、来源许可与人工核验
   协议，而不把当前 ranking label 当作事实正确性标签？

本文不替团队选择 W6 Roadmap，也未创建任何 W6 Issue。
