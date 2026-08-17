# W4 研究计划：评价基准与实验体系试运行

状态：W4 计划已执行并进入 W5 前置收口。本文保留研究问题、Pilot Candidate Pool 和独立
双标的设计基线；当前 judged-set 的真实状态与批准条件见
[`W4_PILOT_BENCHMARK_PROTOCOL.md`](W4_PILOT_BENCHMARK_PROTOCOL.md)。

## 1. 本周定位

项目当前研究定位逐步收敛为：

> 面向特定科研问题的专业文献智能检索、多维价值画像与阅读优先级排序。

W2 解决了多查询获取、来源追踪、去重、两阶段排序和工程验收的串联问题。W4 首先回答
“以后说一种方法更好时，评价依据是什么”，而不是继续堆叠新算法。

本周不实现 BM25、Dense Embedding、SPECTER、BERT、RankNet、LambdaMART、LLM
Reranker、Knowledge Graph 或 AHP/TOPSIS 大型评价系统。它们只能在基准和评价协议稳定后
作为候选实验。

## 2. Research Questions

### RQ1：检索方法比较

在低标注的专业科研领域中，词法检索、语义检索以及二者融合，哪一种能够更准确地找到
与具体科研问题相关的文献？

这是未来实验要回答的问题；当前项目只有词法相关性 baseline，尚未进行语义或融合方法
对照。

### RQ2：阅读优先级

在保证主题相关性的前提下，引入引用影响、时效性等文献计量信号，能否改善科研人员的
阅读优先级排序，同时避免高引用但主题偏离的论文重新进入 Top-K？

引用量、年份和完整度只是信号，不是论文绝对质量，也不能替代主题相关性判断。

### RQ3：领域术语与 hard negatives

领域术语和 hard negatives 能否帮助检索系统处理专业术语、同义表达，以及“表面词汇相关
但核心任务不同”等专业领域检索错误？

当前 Pilot 只建立能够观察这些错误的人工 relevance 协议，不提前声称领域词或 hard
negative 已经改善结果。

## 3. 三层文献评价

### 第一层：Query Relevance

回答“这篇论文是不是当前科研问题真正想找的”。W4 人工标注只处理这一层，判断核心研究
任务与 research question 的对应关系。

### 第二层：Value Profile

分开描述 relevance、impact signal、recency、metadata completeness，以及未来可能加入的
领域或方法特征。它们是多维画像，不应被压缩成“客观绝对质量”。

### 第三层：Reading Priority

回答“对于当前科研任务，已经比较相关的论文应该先读哪一些”。排序实验应先保证相关性，
再研究文献计量信号是否改善阅读顺序。

本项目不宣称可以给论文一个客观绝对质量分。

## 4. Pilot 的三个具体科研问题

机器可读配置见 [`configs/w4/research_queries.json`](../../configs/w4/research_queries.json)。

| ID | 中文问题 | English question | Acquisition query |
| --- | --- | --- | --- |
| `rq01_stellar_classification` | 机器学习如何用于恒星光谱分类或恒星类型识别？ | How is machine learning used to classify stellar spectra or identify stellar types? | `q02_classification` |
| `rq02_stellar_parameters` | 机器学习如何从恒星光谱估计有效温度、表面重力、金属丰度等恒星物理或大气参数？ | How is machine learning used to estimate stellar physical or atmospheric parameters, including effective temperature, surface gravity, and metallicity, from stellar spectra? | `q03_parameters` |
| `rq03_spectral_preprocessing` | 机器学习如何用于恒星光谱的预处理、降噪、归一化、校准或质量改进？ | How is machine learning used for preprocessing, denoising, normalization, calibration, or quality improvement of stellar spectra? | `q04_preprocessing` |

`acquisition_query_ids` 决定候选从哪组既有 retrieval provenance 进入；
`ranking_keyword` 对每个 research query 单独显式配置，用于候选分层，不能从 acquisition
query 的顺序隐式推断。

## 5. Pilot Candidate Pool v0.1

当前 Pilot 包含三个 research query，每个 20 个 query-paper pair，共 60 pair。它用于试运行：

- annotation protocol；
- 无标签泄漏的 candidate selection；
- 独立双标分配；
- 后续 agreement 和 adjudication 工作流。

同一篇论文可以对应多个 research query，因为 relevance 是 query-dependent；同一个
`research_query_id + openalex_id` 不会重复。当前 60 pair 对应 57 篇唯一 OpenAlex work。

这不是大规模 benchmark、gold standard、专家标注集或论文级正式 ground truth，也不能
证明当前排序优于其他算法。

## 6. 来源与无标签泄漏选样

唯一论文来源是已提交的真实 OpenAlex W2 样例：

`data/samples/w2/domain_query/live_query_sample.csv`

该文件由 q02、q03、q04 各 30 条 live 命中按 OpenAlex ID 合并成 82 条，并保留所有 query
和 run 来源。W4 没有新增 live 请求。

每个 research query 的确定性选样规则为：

1. 只保留 provenance 命中对应 acquisition query 的 30 条记录；
2. 先按 `openalex_id, title` 固定输入顺序；
3. 用该 research query 的显式 ranking keyword 重新计算当前
   `preliminary_score + TF-IDF two-stage` 排序，参考年份固定为 2026；
4. 选择 new rank 前 5、中间 5、后 5；
5. 从剩余记录中按 `abs(rank_change)` 降序再选 5 条；
6. tie 依次使用 `new_rank`、`openalex_id`、`title`；
7. pair 编号前先按 `SHA-256(pool_version|research_query_id|openalex_id)` 排序，避免编号直接
   暴露排名 bucket。

选样没有读取或使用：

- `relevance_labels_w1.csv`；
- `relevance_labels_w2_baseline.csv`；
- AI-assisted labels；
- hard negative 人工判断；
- 其他人工 label 或 review 结果。

因此 Candidate Pool 的选择不存在人工 label leakage。分层使用的是已有算法输出，用来覆盖
高、中、低排名和排名变化样本，不被解释为人工答案。

## 7. Candidate Pool 数据契约

公共池位于 `data/annotation_tasks/w4/candidate_pool_v0.1.csv`，字段包括：

- `pair_id`、`research_query_id`；
- 中英文 research question；
- `acquisition_query_id`；
- `openalex_id`、标题、摘要、落地页、年份和 DOI；
- JSON array string 形式的 `source_query_ids`、`source_run_ids`；
- `pool_version` 和仅供审计的 `selection_bucket`。

个人标注任务不会包含 `selection_bucket`，也不会包含 preliminary/stage2 分数、old/new rank、
引用信号、人工旧标签或 assignment role。

## 8. Pair ID 与冻结

pair ID 使用 `w4_rq01_001` 至 `w4_rq03_020` 的稳定格式。它是 query-paper pair 的长期
标识，不依赖 CSV 行号。

[`pool_manifest_v0.1.json`](../../data/annotation_tasks/w4/pool_manifest_v0.1.json) 记录生成时间、
Git revision、来源及 SHA-256、选择规则、各 query 计数和输出哈希。v0.1 进入成员标注阶段
后冻结；若必须调整，建立新版本，不静默覆盖。

## 9. Balanced Double Annotation

60 个 pair 都有一个 primary，其中 30 个再由第二人独立标注，共 90 次 assignment。六名
成员各 15 条，三个 research query 各有 10 个 secondary overlap。

primary 按稳定 pair 顺序轮转分配；secondary pair 按固定 SHA-256 顺序选择，再在每个 RQ
的固定配额下避免 `primary == secondary` 并分散搭档。当前分配覆盖全部 15 种两人组合，
不会让固定两个人始终互相双标。

双标必须独立，任何人不得查看另一标注者的 label。

## 10. 本次实现边界

本节记录 W4 bootstrap 当时的实现边界：公共准备只交付 candidate pool、manifest、assignment、
个人任务生成器、格式 validator、标注指南和导航。

本次不实现：

- 合并六人 annotation；
- Cohen's Kappa 或 Weighted Kappa；
- disagreement adjudication；
- 使用新 benchmark 比较 baseline 与 two-stage；
- BM25、Embedding、LTR 或其他新排序模型。

其中六人 annotation、agreement、entity/provenance/query-boundary audit 和 evaluator 后来已由
W4 PR #42–#47 合并；分歧的人类 adjudication 和 approved judged set 仍待完成。

## 11. 形成正式 benchmark 前的条件

全部个人 PR 已合并，agreement 已完成；当前剩余条件是 3 个分歧的独立人工裁决、provenance
复核和 strict validator。版本化结果位于 `data/benchmarks/w4_query_relevance/`，原始个人文件
继续保留在 `annotation_tasks`。统一使用 Pilot Adjudicated Judged Set，不使用 `gold` 或
`ground_truth`。
