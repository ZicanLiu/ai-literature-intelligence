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

## 历史 live 输出

`live_test_20260718/` 是已有的日期化 live 测试归档，为避免破坏报告引用继续保留。
新的普通运行不再写入该目录。

## `quality/`

保存质量门禁的普通运行结果，例如 JSON、Markdown 和失败项 CSV。该目录下除
`README.md` 外的普通结果默认由 `.gitignore` 忽略；需要长期保存时应先检查来源、
可复现性和敏感信息，再通过独立任务提升，不能影响现有 `baselines/`。
