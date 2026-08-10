# 输出目录说明

## `baselines/`

保存经过来源、安全和可复现性检查的稳定结果。现有
`baselines/mock_v0.2.0/` 是历史 mock 基线，本次整理不修改其中内容。普通运行结果
不能手工改名后直接当作基线；需要长期保存时，应先核对运行配置、数据来源、记录数和
敏感信息，再通过独立任务提升。

## `experiments/`

从第二周基线开始，CLI 默认在这里为每次运行创建唯一的 `<run_id>/`。目录名包含时间、
模式、关键词片段、请求数量和短随机标识；完整原始关键词保存在 `run_config.json`。

一次完整实验包括：

```text
<run_id>/
├── run_config.json
├── raw/raw_response.json
├── tables/papers_ranked.csv
├── tables/duplicates_removed.csv
├── figures/top10_citations.png
├── figures/top10_preliminary_score.png
├── reports/run_summary.txt
└── data/literature.db
```

`run_config.json` 可用于查看参数、评分权重、数量、耗时、成功状态和各文件的相对路径。
普通实验默认被 `.gitignore` 忽略，不提交到仓库。现有
`experiments/openalex_stellar_spectra_60/` 是整理前已跟踪的历史实验，保留原路径。

统一 W2 Pipeline 也写入独立 `<run_id>/`，但按阶段组织，避免旧 writer 截断新字段：

```text
<run_id>/
├── run_config.json
├── domain/domain_query_set.json
├── retrieval/{query_stats,combined_papers}.*
├── retrieval/<query_id>/{raw_response,cleaned_papers}.json
├── dedup/{exact_duplicates,deduplicated_papers,suspected_duplicates,summary}.*
├── ranking/{ranked_papers,baseline_vs_two_stage,error_cases}.csv
├── evaluation/metrics.json                 # 仅提供 labels 时生成
└── reports/run_summary.txt
```

最终 CSV 的 `source_query_ids`、`source_run_ids` 和 `source_keywords` 使用可逆的 JSON
array 字符串；疑似重复只进入 review queue，不减少最终候选集。

## `batches/`

保存 Batch Runner 的配置快照和汇总。每个 item 仍产生一个独立 experiment run，batch
摘要通过 `batch_id`、`item_id`、`run_id` 关联，不复制论文处理逻辑。普通 batch 结果默认
忽略，只跟踪 [`batches/README.md`](batches/README.md)。

## 历史 live 输出

`live_test_20260718/` 是已有的日期化 live 测试归档，为避免破坏报告引用继续保留。
新的普通运行不再写入该目录。

## `quality/`

保存质量门禁的普通运行结果，例如 JSON、Markdown 和失败项 CSV。该目录下除
`README.md` 外的普通结果默认由 `.gitignore` 忽略；需要长期保存时应先检查来源、
可复现性和敏感信息，再通过独立任务提升，不能影响现有 `baselines/`。
