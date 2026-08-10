# AI 项目交接与开发入口

## 0. 如何使用本文

本文帮助只熟悉 v0.2.0、只参与过某个 W2 模块，或第一次进入仓库的成员和 AI Agent 建立完整上下文。它不是永远正确的状态数据库。

- 快照更新时间：2026-08-10
- 对应公共基线：`899f745`（tag `v0.3.0`）
- 当前准备分支：`chore/w4-benchmark-bootstrap`
- 当前状态：Unified Pipeline 已进入 `main`；W4 benchmark bootstrap 正在准备，尚未合并

每次开始新任务，都必须重新用 Git、源码和测试核对本文。事实优先级及长期规则见
[`AGENTS.md`](../../AGENTS.md)，当前快照见 [`docs/CURRENT_STATUS.md`](../CURRENT_STATUS.md)。

## 1. 项目背景

项目目标是研究 AI 驱动的科研文献获取、处理和辅助评估流程。当前 MVP 聚焦“AI 在天文光谱数据处理中的应用”，使用 OpenAlex 公开论文元数据完成候选获取、清洗、去重、排序、离线评价和结构化输出。

当前目标不只是“搜到论文”，而是形成一条可追溯、可复现、可比较的处理链。长期可以迁移到其他科研主题，但当前代码和样例仍以天文光谱为主。项目不声称已经实现论文真实价值判断、语义理解或自动科研结论生成。

## 2. 从 v0.2.0 到 W2/v0.3.0 发生了什么

v0.2.0 入口仍然保留：

```text
app.main
→ mock / 旧 OpenAlex client
→ clean
→ 旧 DOI/标题严格去重
→ preliminary_score
→ CSV / SQLite / 图表 / 摘要
```

W2 的五项成员能力已经进入当前 `main` 基线：

- 领域词表与可解释 query set；
- OpenAlex v2 cursor 分页、重试、统计和获取层 ID 防重复；
- W2 exact/suspected 两级去重；
- TF-IDF 词法相关性、Stage 1 分层、Stage 2 排序和 judged 评价；
- Basic/Full Quality Gate。

Issue #21 进一步新增并已经进入当前 `main`：

- `src.pipeline.run_unified_pipeline()`：把上述能力串成一个多 acquisition query 的 parent run；
- `app.run_pipeline`：统一 Pipeline CLI；
- `src.batch_runner.run_batch()` 与 `app.batch_runner`：复用同一 Pipeline API 的批量入口；
- `src/ranking.py`：从旧 CLI 中抽出的可复用两阶段排序核心；
- 清洗后 provenance、跨 query 精确去重的来源合并、显式 ranking keyword；
- 独立输出目录、结构化失败状态和离线 E2E/batch 测试。

旧 `app.main` 没有被删除，也没有被悄悄替换。它仍是兼容和教学 baseline；统一 Pipeline
和 Batch Runner 已随 v0.3.0 发布并成为 W4 的工程基础。

### 当前从工程 Pipeline 转向研究评价

W4 不继续堆新排序算法，而是先建立 research query、无标签泄漏 candidate pool、独立双标
协议和可验证的个人任务。涉及 W4 benchmark 的 Issue 还必须继续阅读：

- [`W4_RESEARCH_PLAN.md`](W4_RESEARCH_PLAN.md)
- [`W4_ANNOTATION_GUIDELINE.md`](W4_ANNOTATION_GUIDELINE.md)
- [`data/annotation_tasks/w4/README.md`](../../data/annotation_tasks/w4/README.md)

当前只是 Pilot Annotation 准备，不能表述为大规模 benchmark、gold ground truth 或算法
优劣结论。

## 3. 当前关键目录

| 路径 | 职责 |
| --- | --- |
| `app/` | CLI、参数校验、用户输出；不承载可复用算法 |
| `src/` | 获取、清洗、去重、排序、评价、输出编排和验证逻辑 |
| `configs/w2/` | W2 可复用配置与安全离线 batch 示例 |
| `configs/w4/` | W4 research query 机器可读配置 |
| `data/domain/` | 领域词表和生成的查询集合 |
| `data/samples/` | 固定、可追溯的公开元数据样例 |
| `data/manual/` | 人工或待复核标注、审核数据 |
| `data/analysis/` | 可提交的分析结果，不等同于运行时输出 |
| `data/annotation_tasks/` | 待人工判断的候选池、分配和个人任务，不是 ground truth |
| `tests/automated/` | 标准库 `unittest` 自动测试 |
| `tests/fixtures/` | 离线、确定、可重复的测试输入 |
| `docs/project/` | 长期架构、接口和使用说明 |
| `docs/reports/` | 某一阶段的事实快照与成员分析 |
| `outputs/experiments/` | 单次 parent run，默认忽略 |
| `outputs/batches/` | batch 级配置快照与摘要，默认忽略 |
| `outputs/baselines/` | 经单独核验、可长期保留的稳定结果 |

依赖方向必须保持 `app → src`。若业务逻辑只能从 `app/` 导入，先考虑把它抽到 `src/`，不要新增 `src → app`。

## 4. 当前架构

### A. v0.2.0 baseline

```text
app.main
├─ src.mock_client / src.openalex_client
├─ src.processor
├─ src.run_context
├─ src.storage
└─ src.visualizer
```

### B. Unified Pipeline

```text
app.run_pipeline
└─ src.pipeline
   ├─ src.domain_query
   ├─ src.openalex_client_v2 / offline fixture fetcher
   ├─ src.processor
   ├─ src.deduplication
   ├─ src.ranking → src.text_relevance
   └─ src.evaluation（可选）
```

### C. Batch Runner

```text
app.batch_runner
└─ src.batch_runner
   └─ 对每个 item 调用 src.pipeline.run_unified_pipeline
```

Batch Runner 不重新实现 retrieval、dedup 或 ranking。每个 item 都产生独立 parent run，batch 只保存批次配置和状态汇总。

### D. Quality Gate

```text
app.quality_gate
└─ src.validation
   ├─ 目录、JSON、CSV、引用和数值检查
   ├─ Python 导入与 Markdown 链接检查
   ├─ 敏感信息风险扫描
   └─ unittest discovery
```

Quality Gate 是运行前后都可使用的工程验收工具，不参与论文打分，也不应被塞进单篇论文处理函数。

## 5. Unified Pipeline 十三个阶段

### Step 1：Domain Query

- 输入：`data/domain/stellar_spectra_terms_w2.csv` 和选中的 `query_id`；
- 输出：完整 query set 及本次 selected acquisition queries；
- 文件：`src/domain_query.py`，输出到 `domain/domain_query_set.json`；
- 关键函数：`load_domain_terms()`、`build_query_set()`、`write_query_set()`；
- 位置原因：先把领域词表转成稳定、可解释的查询，再进行获取，避免在网络请求中临时拼词。

### Step 2：OpenAlex v2 或离线获取

- 输入：每个 acquisition query、每组最大结果数、可选年份范围；
- 输出：`papers`、`raw_response`、请求统计；
- 文件：`src/openalex_client_v2.py`，离线替代在 `src/pipeline.py` 的 `build_offline_fixture_fetcher()`；
- 关键函数：`fetch_openalex_papers_v2()`；
- 位置原因：每组查询必须先独立获取并保留请求证据，之后才能合并来源。

### Step 3：Clean

- 输入：单组 query 的原始论文对象和该 acquisition keyword；
- 输出：统一基础字段的论文列表；
- 文件：`src/processor.py`；
- 关键函数：`clean_papers()`、`clean_single_paper()`；
- 位置原因：来源追踪和跨 query 去重都依赖稳定字段，不能直接对未经清洗的供应方结构操作。

### Step 4：Attach Provenance

- 输入：清洗论文、`query_id`、acquisition keyword、child run ID；
- 输出：追加 `source_query_ids`、`source_run_ids`、`source_keywords` 的论文；
- 文件：`src/pipeline.py`；
- 关键函数：`_attach_provenance()`；
- 位置原因：清洗完成后附加来源，避免清洗器丢弃扩展字段，同时保证每条记录进入合并前已有可追溯来源。

### Step 5：Combine

- 输入：各 acquisition query 的清洗结果；
- 输出：尚未做 entity dedup 的合并候选集；
- 文件：`src/pipeline.py`；
- 产物：`retrieval/combined_papers.json`、`retrieval/combined_papers.csv` 和 query stats；
- 位置原因：先保留完整命中事实，再在单一候选池中判断跨查询重复。

### Step 6：Exact Dedup

- 输入：合并候选集；
- 输出：`kept_papers`、确定重复记录和规则统计；
- 文件：`src/deduplication.py`；
- 关键函数：`find_exact_duplicates(..., merge_provenance=True)`；
- 位置原因：可靠标识符重复可自动合并；Pipeline 模式同时合并 provenance，但不做 metadata fusion。

### Step 7：Suspected Review Queue

- 输入：exact dedup 后的保留记录；
- 输出：疑似重复 pair 和原因统计；
- 文件：`src/deduplication.py`；
- 关键函数：`find_suspected_duplicates()`；
- 位置原因：相似标题、作者和年份只能形成审核线索。此阶段产生队列，不删除任何候选。

### Step 8：Preliminary Baseline

- 输入：保留论文和显式 `ranking_keyword`；
- 输出：四个子分、`preliminary_score`、baseline 顺序；
- 文件：`src/processor.py`；
- 关键函数：`add_preliminary_scores()`；
- 位置原因：保留 v0.2.0 的可解释参照，才能与 W2 排序公平比较。Pipeline 固定本次 run 的参考年份以提高复现性。

### Step 9：TF-IDF

- 输入：同一候选集的标题、摘要和 `ranking_keyword`；
- 输出：标题、摘要和组合词法相关性；
- 文件：`src/text_relevance.py`；
- 关键函数：`add_text_relevance_scores()`、`TextRelevanceScorer`；
- 位置原因：获取词和排序词可能不同，必须在合并、去重后的统一候选集上计算同一套词法相关性。

### Step 10：Stage 1

- 输入：`combined_relevance_score`；
- 输出：`stage1_relevance_score` 和 `high/medium/low`；
- 文件：`src/ranking.py`；
- 关键函数：`assign_stage1_level()`；
- 位置原因：先做可解释分层和降权，不硬删除词法低相关论文，降低同义改写被误杀的风险。

### Step 11：Stage 2

- 输入：词法相关性、引用影响、时效性、完整度和 Stage 1 gate；
- 输出：`stage2_ranking_score`、`new_rank`、`rank_change`；
- 文件：`src/ranking.py`；
- 关键函数：`apply_two_stage_ranking()`；
- 位置原因：在保留 baseline 的同时，让主题词法相关性成为新版排序的主导因素。

### Step 12：Optional Evaluation

- 输入：排序结果、可选 label CSV、`K` 和标签纳入策略；
- 输出：baseline 与 two-stage 的 judged 指标；
- 文件：`src/pipeline.py`、`src/evaluation.py`；
- 关键函数：`load_pipeline_labels()`、`evaluate_ranking()`；
- 位置原因：标签只评价最终排序，不参与评分，从而避免把答案泄漏到排序公式。

### Step 13：Outputs

- 输入：各阶段结果、配置、计数和状态；
- 输出：parent run 完整目录及 `run_config.json`；
- 文件：`src/pipeline.py`；
- 关键函数：`_output_file_map()`、`_write_json()`、`_write_csv()`、`_write_summary()`；
- 位置原因：配置先以 `running` 写入，成功后改为 `completed`；异常时保留同一 run 的 `failed` 状态和安全错误摘要，避免留下“看似成功”的半成品。

## 6. Paper 数据契约

完整协作约定见 [`W2_DATA_CONTRACTS.md`](W2_DATA_CONTRACTS.md)。Pipeline 当前实际字段分为：

- 基础字段：`title`、`authors`、`publication_year`、`doi`、`abstract`、`cited_by_count`、`source_name`、`openalex_id`、`landing_page_url`、`keyword`、`retrieved_at`；
- 兼容与运行字段：`run_id`；
- provenance：`source_query_ids`、`source_run_ids`、`source_keywords`；
- baseline：`relevance_score`、`impact_score`、`recency_score`、`completeness_score`、`preliminary_score`、`baseline_preliminary_score`、`old_rank`；
- TF-IDF/排序：`title_relevance_score`、`abstract_relevance_score`、`combined_relevance_score`、`stage1_relevance_score`、`stage1_relevance_level`、`stage2_ranking_score`、`new_rank`、`rank_change`。

三个 provenance 字段在内存和 JSON 中是 `list[str]`，写入 CSV 时是 JSON array string，例如 `["q02_classification","q03_parameters"]`。重新读取 Pipeline CSV 应使用 `src.pipeline.load_pipeline_csv()`，不能按逗号手工拆分。

兼容字段 `keyword` 和 `run_id` 保留单条记录首次来源，帮助旧代码继续工作；完整来源必须读取三个 `source_*` 字段。它们不能替代 parent run 的 `run_config.json`。

## 7. Query、Run 与 Provenance

### 标识和用途

- domain `query_id`：查询蓝图的稳定编号，如 `q02_classification`；
- acquisition keyword：该 query 实际发给获取器的完整关键词；
- `ranking_keyword`：对合并候选集统一打分的显式关键词；
- parent `run_id`：一次 Unified Pipeline 的总实验目录 ID；
- child `run_id`：一次 query 请求的 ID，当前形式为 `<parent_run_id>__<query_id>`；
- `batch_id`：一次批量实验的总 ID；
- `item_id`：batch 配置中的稳定条目标识，每项对应一个 parent run。

这些 ID 不能混用。尤其不能从 child run 字符串反向猜 `query_id`，也不能把 `batch_id` 当作论文来源。

### 缩小示例

以下是概念示例，不是某次固定 run 的真实输出。假设 `q02_classification` 和 `q03_parameters` 都命中 `https://openalex.org/Wxxxx`：

```text
q02 命中 Wxxxx → source_query_ids=[q02]，source_run_ids=[child-q02]
q03 命中 Wxxxx → source_query_ids=[q03]，source_run_ids=[child-q03]

exact dedup 后只保留一个 Wxxxx 实体：
source_query_ids=[q02, q03]
source_run_ids=[child-q02, child-q03]
source_keywords=[q02 的完整关键词, q03 的完整关键词]
```

该实体的 `keyword`/`run_id` 仍可能是首次命中的兼容值；分析查询覆盖时必须使用合并后的 provenance list。

## 8. OpenAlex 获取

旧 `src/openalex_client.py` 服务 `app.main` 的 v0.2.0 单请求 baseline，单次最多 100 条，不做 cursor 分页。

`src/openalex_client_v2.py` 服务 Unified Pipeline，当前支持：

- cursor pagination；
- `max_results` 总量控制及每页最多 100；
- `from_year`/`to_year`；
- 对超时、连接错误、HTTP 408/429 和 5xx 的有限重试与退避；
- 请求数、页数、重试数、停止原因和耗时统计；
- 获取层页内/跨页 OpenAlex ID 防重复；
- 不在异常、统计和输出中写 API Key 或完整请求 URL。

v2 的 ID 防重复只处理同一次获取中 OpenAlex 返回的重复 work，不能替代跨 query 的 W2 entity exact dedup。

## 9. Dedup

### Exact

`find_exact_duplicates()` 按以下可靠规则识别确定重复：

1. `same_openalex_id`；
2. `same_doi`；
3. 两侧均无 OpenAlex ID/DOI 时的严格标准化标题相同。

Pipeline 显式开启 `merge_provenance=True`。可靠 identifier 合并后会传播 OpenAlex ID/DOI alias，后续记录可继续命中同一实体；若同一记录的 ID 与 DOI 指向两个不同保留实体，则停止自动合并并报冲突，不静默选择。

当前只合并 provenance，不做标题、摘要、作者等 metadata fusion。merge 模式使用新的阶段快照，避免反向修改 retrieval 阶段的 `combined_papers`。

### Suspected

疑似队列使用年份窗口、标题 Jaccard/SequenceMatcher、作者姓氏重合和 DOI 排除等可解释信号。它只输出 `pair_id`、相似度、原因和 `review_status=pending`，不删除记录。

当前 Pipeline 尚未自动应用人工 confirmed/distinct review decision；审核结果如何回写候选集应另开 Issue 设计。

## 10. Ranking

v0.2.0 baseline：

```text
preliminary_score =
0.40 × relevance_score
+ 0.30 × impact_score
+ 0.20 × recency_score
+ 0.10 × completeness_score
```

`src/ranking.py` 在该 baseline 之上追加：

- TF-IDF 标题/摘要词法相关性，组合权重 0.70/0.30；
- Stage 1：`>=0.20` 为 high，`>=0.05` 为 medium，其余 low；
- Stage 1 gate：1.0/0.8/0.5，只降权、不删除；
- Stage 2：词法相关性、引用影响、时效性、完整度权重 0.50/0.25/0.15/0.10。

这些参数是当前可解释 baseline，不是已经通过大规模标注证明的最优参数。TF-IDF 衡量词项重合，不是语义排序；不同 run 的候选语料不同，分数也不应直接跨批次比较。

## 11. Evaluation

人工标签只用于离线评价，不进入任何评分公式。未标注论文不是“不相关”；`待讨论` 也按未标注处理。

当前指标使用 judged/condensed 口径：先移除未标注论文，再在已标注排名上计算 judged Precision@K 和 judged NDCG@K；`coverage_at_k` 仍说明原始 Top K 的标签覆盖。另有原始 Top K 中明确不相关数和高度相关论文平均排名。

当前 W2 label CSV 共 50 行：37 行来自原 PR 人工判断映射，13 行为 `AI-assisted-draft` 且待人工复核。Unified Pipeline 默认排除后 13 行；37 行仍需组长抽查，不能称为正式 gold ground truth。重复 `openalex_id` 会直接报错，不采用静默覆盖。

## 12. Batch Runner

Batch Runner 读取 JSON 配置，对每个 enabled item 构造 `PipelineConfig`，然后顺序调用同一个 `run_unified_pipeline()`。每项独立保存 parent run；batch 目录只保存配置快照和机器/人工可读摘要。

- `continue_on_error=true`：失败项保留 `failed` 和可追溯 run 信息，后续项继续，batch 最终仍为非成功；
- `continue_on_error=false`：失败后其余项记为 `not_run_after_failure`；
- `enabled`、`continue_on_error`、`include_unverified_labels` 必须是真正的 JSON `true/false`，字符串和数字不被隐式转换；
- Pipeline 已创建目录后失败会抛出带 `run_id`/`run_dir` 的 `PipelineRunError`，batch 摘要因此能定位失败 parent run。

配置与复现方法见 [`BATCH_EXPERIMENT_GUIDE.md`](BATCH_EXPERIMENT_GUIDE.md)。

## 13. Outputs

Unified Pipeline 的一个 parent run 结构如下；评价目录只在提供 labels 时出现：

```text
outputs/experiments/<parent_run_id>/
├─ run_config.json
├─ domain/domain_query_set.json
├─ retrieval/
│  ├─ <query_id>/raw_response.json
│  ├─ <query_id>/cleaned_papers.json
│  ├─ query_stats.json
│  ├─ query_stats.csv
│  ├─ combined_papers.json
│  └─ combined_papers.csv
├─ dedup/
│  ├─ exact_duplicates.csv
│  ├─ deduplicated_papers.json
│  ├─ deduplicated_papers.csv
│  ├─ suspected_duplicates.csv
│  └─ summary.json
├─ ranking/
│  ├─ ranked_papers.csv
│  ├─ baseline_vs_two_stage.csv
│  └─ error_cases.csv
├─ evaluation/metrics.json
└─ reports/run_summary.txt
```

Batch 输出位于 `outputs/batches/<batch_id>/`，包含 `batch_config.json`、`batch_summary.json` 和 `batch_summary.csv`。

普通 experiment 和 batch 结果默认被 Git 忽略；目录中的 README 可跟踪。只有经来源、安全、统计和复现审核的结果，才通过独立任务提升到 `outputs/baselines/`，不能手工把临时 run 当作 baseline。

## 14. 自动测试

当前测试体系包括模块单测、安全离线 fixture、Unified Pipeline E2E、失败边界、Batch Runner 和 Quality Gate 测试。它不依赖真实 API Key，也不应把测试输出写入正式实验目录。

本文更新时的 W4 bootstrap 工作区快照为 **214 项自动测试全部通过**。该数字不是永久事实；开始任何新任务都必须重新运行：

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -q
```

定向测试用于快速反馈，不能替代交付前的完整 discovery。

## 15. Quality Gate

```powershell
python -m app.quality_gate --level basic
python -m app.quality_gate --level full
```

- Basic：目录、正式 JSON、关键导入、Markdown 本地链接、敏感信息风险和自动测试；
- Full：包含 Basic，并增加 CSV 结构、唯一 ID、标签引用、数值范围、run config 和已跟踪实验检查；
- error 会使 CLI 返回非零；warning 需要人工阅读，但不会单独导致失败。

本文更新时 Basic 为 0 error / 0 warning；Full 为 0 error / 3 warning。三个 warning 均是现有历史 W1/旧输出快照：

1. 一条 W1 标注 CSV 的逗号未按 CSV 规则转义；
2. `data/manual/relevance_labels_w1.csv` 有 19 个 OpenAlex ID 未与当前统一样例对齐；
3. 历史已跟踪 experiment `outputs/experiments/openalex_stellar_spectra_60`。

这些结论也只是本文更新时间点的快照。新任务不得因为 warning 已知就忽略新出现的错误或 warning。

## 16. 常用 PowerShell 命令

同步并创建任务分支：

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/<issue-name>
```

查看 v0.2.0 baseline 和新入口帮助：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
python -m app.run_pipeline --help
python -m app.batch_runner --help
```

运行安全离线示例：

```powershell
python -m app.run_pipeline --query-ids q01_broad_ml q02_classification `
  --ranking-keyword "machine learning stellar parameter estimation spectra" `
  --mode offline --max-results-per-query 10 `
  --terms tests/fixtures/pipeline/domain_terms.csv `
  --offline-fixture tests/fixtures/pipeline/offline_queries.json `
  --labels tests/fixtures/pipeline/labels.csv

python -m app.batch_runner --config configs/w2/integration_batch.example.json
```

交付前：

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -q
python -m app.quality_gate --level basic
python -m app.quality_gate --level full
git diff --check
git status --short
git diff --stat
```

这里不提供需要真实 Key 的 live 命令。是否运行 live 必须由当前 Issue 和用户授权决定，Key 不能写进命令、配置或报告。

## 17. 新 Issue 的标准开发流程

1. 切回并拉取最新 `main`；
2. 阅读根目录 `AGENTS.md`；
3. 阅读本交接文档；
4. 阅读 `docs/CURRENT_STATUS.md`；
5. 阅读当前 Issue 和相关模块文档；
6. 若使用 AI，先让 AI 只读审计实际代码、测试和 Git 状态；
7. 从最新 `main` 创建独立 feature/fix/docs/test 分支；
8. 按最小范围实现，不改无关模块；
9. 运行与修改直接相关的定向测试；
10. 运行完整离线自动测试；
11. 运行适用的 Quality Gate；
12. 检查 `git diff --check`、`git status` 和完整 diff；
13. 由成员或组长人工审查边界、数据和结论；
14. 再 commit、push、创建 PR，等待审核合并。

可复制到 Issue 的入口说明：

> ## 开始前必读
>
> 开始本 Issue 前，请先同步最新 `main`，并阅读 `AGENTS.md`、`docs/project/AI_PROJECT_ONBOARDING.md`、`docs/CURRENT_STATUS.md` 及与本 Issue 相关的模块文档。如果使用 AI 辅助开发，请先让 AI 核对当前源码、测试和 Git 状态，不要基于旧分支、旧压缩包或历史聊天直接修改。

## 18. 给 AI Agent 的标准启动提示

```text
你现在位于本项目仓库中。开始本 Issue 前，请先完整阅读根目录 AGENTS.md、
docs/project/AI_PROJECT_ONBOARDING.md、docs/CURRENT_STATUS.md 和当前 Issue，
然后只读核对 git status、当前分支、HEAD、相关源码、测试与调用关系。

以当前工作区代码、实际测试和本 Issue 为事实来源；如果文档与代码冲突，
先报告差异。不要根据旧聊天、旧分支、旧压缩包或常见项目结构猜测实现。
保持 app → src 的依赖方向，优先复用现有模块，保留 provenance、v0.2 baseline
及 suspected-review 边界。只修改 Issue 范围内文件，并补充定向测试。

不得读取或输出 .env、API Key、Token；未经明确授权不要运行 live、push、merge、
tag 或 release。完成后运行定向测试、完整离线测试、适用的 Quality Gate 和
git diff --check，并报告实际 Git 状态、验证结果、限制和未完成事项。
```

## 19. Known Limitations / P1 / P2

以下能力当前尚未实现，不能在 Issue 或报告中写成已有功能：

### P1 候选

- 完成 W4 六人独立标注、agreement 计算和 disagreement adjudication；
- 把人工 confirmed/distinct duplicate review decision 安全应用回数据集；
- exact dedup 后的 metadata fusion 及字段冲突审计；
- W2/v0.3 的 SQLite schema 和阶段化持久化；
- 统一 Pipeline 的排序图表与可复现可视化；
- 13 条 AI-assisted label 的人工复核，以及 37 条映射标签的抽查；
- 6/6 domain query 的更大规模 live 验证；
- 为 exact duplicate 记录增加稳定 pair/entity 标识的接口设计。

### P2 / 研究候选

- 扩大、分层并版本化人工 benchmark；
- 比较不同 Stage 1 阈值、权重和缺失摘要条件；
- 缓解 TF-IDF 无法识别同义改写、领域缩写和语义相关的问题；
- BM25、Embedding、hybrid ranking、learning-to-rank 等候选方法。

这些项目都应单独建 Issue、定义数据和验收标准，不能直接修改当前算法后宣布“更优”。

## 20. 后续科研方向

以下是未来研究方向，**尚未实现**，不属于当前 Unified Pipeline 功能：

- 面向具体天文科研场景组织问题和证据；
- 特定天体的文献与数据整理；
- 主题、方法或观测对象的年份演化分析；
- 引用网络与论文关系图谱；
- 从摘要或未来经授权的全文中抽取对象、方法、数据集和指标；
- LLM 辅助生成带来源引用、可人工核验的科研分析报告。

是否加入 PDF、RAG、知识图谱、多 Agent 或前端，必须经过新的需求和安全评审，不能当作当前架构的自然默认步骤。

## 21. 与未来排序研究的关系

当前可比较基线是：

```text
v0.2 preliminary_score
+ W2 TF-IDF two-stage ranking
```

未来可将 BM25、semantic embedding、hybrid ranking、learning-to-rank 作为候选实验，但它们目前都 **NOT IMPLEMENTED**，项目也没有采用 RankNet。

公平比较应保持：

```text
固定 baseline → 候选方法 → 同一 benchmark → 同一评价口径 → 误差案例分析
```

不能在不同查询、不同样例、不同标签覆盖率下只比较一个分数，也不能一边查看评价结果一边无记录地调权重。

## 22. 最容易犯的错误

- 用旧 `main`、旧分支或旧压缩包理解当前项目；
- 再写一套 OpenAlex client、dedup 或 ranking，而不是复用现有模块；
- 把 `query_id`、parent/child `run_id`、`batch_id`、`item_id` 混在一起；
- 合并论文时丢失 provenance；
- 用 acquisition keyword 隐式代替 ranking keyword；
- 把 Stage 1 层级当成人工标签；
- 把 OpenAlex v2 获取层 ID 防重复当成 W2 entity dedup；
- 自动删除 suspected duplicate；
- 把 AI-assisted label 冒充人工 ground truth；
- 直接改 baseline 公式或成员结论，却没有独立 Issue 和证据；
- 只跑自己新增的测试，不跑全量测试和门禁；
- 提交普通 experiment、batch 输出、本地数据库或敏感配置；
- 新增 `src → app` 反向依赖；
- 把可复用业务逻辑复制到 CLI；
- 为通过测试删除断言、放宽错误或修改历史 evidence。
