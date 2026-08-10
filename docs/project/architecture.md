# 架构说明

本文专门记录仍被保留的 v0.2.0 baseline 架构。当前 W2/v0.3.0 Unified Pipeline 候选没有替换该入口；两者关系和最新架构见
[`AI_PROJECT_ONBOARDING.md`](AI_PROJECT_ONBOARDING.md)。

本项目第一版只实现一条清晰、稳定、可演示的数据流：

```text
关键词输入
→ OpenAlex 或 mock 数据
→ 字段标准化
→ DOI/标题去重
→ 缺失字段统计
→ 初步排序
→ CSV/SQLite 保存
→ 图表和运行摘要
```

真实数据来源是 OpenAlex，不是 OpenAI。v0.2.0 的稳定边界是文献获取、字段清洗、严格规则去重、缺失统计、初步排序、CSV、SQLite、图表和运行摘要；不包含 PDF 解析、RAG、多 Agent、知识图谱或前端。

## 1. 关键词输入

用户通过命令行传入关键词：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
```

`app/main.py` 读取 `--mode`、`--keyword` 和 `--max-results`，也接受可选的
`--output-root`、`--run-name`，并把这些参数传给后续模块。

## 2. OpenAlex 或 mock 数据

`mock` 模式调用 `src/mock_client.py`，读取本地 `data/mock_papers.json`。这个模式不需要网络、不需要 API Key，适合课堂演示和调试。

`live` 模式调用 `src/openalex_client.py`，请求 OpenAlex Works API。API Key 只能从 `.env` 或环境变量读取。

live 模式已经完成小规模真实数据测试，测试记录见
`docs/reports/live/LIVE_TEST_REPORT_20260718.md`。

v0.2 的单次 `per_page` 上限为 100；传入更大值时会自动限制为 100。当前不实现分页。

## 3. 字段标准化

`src/processor.py` 把不同来源的数据统一成以下字段：

- `title`
- `authors`
- `publication_year`
- `doi`
- `abstract`
- `cited_by_count`
- `source_name`
- `openalex_id`
- `landing_page_url`
- `keyword`
- `retrieved_at`

文本字段会去除首尾空格；DOI 会统一小写并去掉 `https://doi.org/` 等前缀；数字字段会尽量转换为整数，无法转换时保留为 `None`。

## 4. DOI/标题去重

去重规则非常克制：

1. 如果 DOI 存在，按标准化 DOI 完全相同去重。
2. 如果 DOI 缺失，按标准化标题完全相同去重。
3. 不做模糊匹配、语义相似度或标题猜测。

被去重的记录会保存到本次实验目录的
`tables/duplicates_removed.csv`，其中包含 `duplicate_reason`。

## 5. 缺失字段统计

去重后，程序会统计每个字段缺失了多少条，并写入：

```text
outputs/experiments/<run_id>/reports/run_summary.txt
```

这样可以直观看到当前数据质量。

## 6. 初步排序

`src/processor.py` 计算：

```text
preliminary_score =
0.40 × relevance_score
+ 0.30 × impact_score
+ 0.20 × recency_score
+ 0.10 × completeness_score
```

这个分数只用于初步文献排序，不代表论文价值评价。

其中相关性分数会先把关键词、标题和摘要拆成小写英文数字词项，再做完整词项匹配，避免 `ai` 错误匹配到 `training` 等单词内部。

## 7. CSV/SQLite 保存

`src/run_context.py` 先创建唯一的 `outputs/experiments/<run_id>/`，集中管理路径和
`run_config.json`。`src/storage.py` 再保存三个核心结果：

- `raw/raw_response.json`
- `tables/papers_ranked.csv`
- `data/literature.db`

排序 CSV 和去重 CSV 使用固定字段顺序；即使结果为空，也会保留完整表头。

这些路径都相对于本次 `<run_id>/`。SQLite 只使用 Python 自带的 `sqlite3`，
第一版只建一张 `papers` 表，方便初学者理解。每次实验使用自己的数据库，不会清空
其他实验。

## 8. 图表和运行摘要

`src/visualizer.py` 生成两张图：

- 引用量最高的 Top 10 文献柱状图
- `preliminary_score` 最高的 Top 10 文献柱状图

图表标题会按运行模式标记 `[MOCK DATA]` 或 `[OPENALEX LIVE]`；mock 图仅用于教学演示，不代表真实学术结论。

`app/main.py` 同时生成运行摘要，记录本次运行模式、关键词、数量统计、缺失字段统计和
相对输出路径；`run_config.json` 还记录运行状态、耗时、评分权重和完整原始关键词，
不保存 API Key 或个人绝对路径。

此前展示过的 PDF 解析属于临时演示，相关内容已删除，不在当前数据流中。
