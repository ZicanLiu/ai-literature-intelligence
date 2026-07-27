# ranking 任务 live 样例

- 文件：`live_ranking_sample.csv`
- 任务：第二周"TF-IDF 与两阶段排序"（蒲正杰）
- 数据来源：OpenAlex live 模式（`src.openalex_client.fetch_openalex_papers`）
- 检索词（keyword）：`machine learning stellar parameter estimation spectra`
- 请求数量：60；清洗去重后记录数量：60
- 获取时间（UTC）：2026-07-27T12:27:51Z
- 本次运行未创建普通实验目录，无 run_id；分数由
  `python -m app.evaluate_ranking --mode live --keyword "machine learning stellar parameter estimation spectra" --max-results 60 --sample-csv data/samples/w2/ranking/live_ranking_sample.csv`
  一次运行生成。

## 字段说明

- `baseline_preliminary_score`：v0.2.0 `preliminary_score` 的基线副本；
- `combined_relevance_score`：TF-IDF 词法相关性组合分（0.7 * 标题 + 0.3 * 摘要），
  只是词法相关性基线，不代表语义理解；
- `stage1_relevance_level`：第一阶段分层（high / medium / low，阈值 0.20 / 0.05）；
- `stage2_ranking_score`：第二阶段固定权重综合分；
- `old_rank` / `new_rank`：baseline 与两阶段排序名次，从 1 开始；
- 分数字段在分析时重新计算，`recency_score` 依赖运行时的当前年份。

## 用途与边界

- 只用于开发、测试和人工分析，不是完整或权威的天文光谱文献集；
- 不包含 API Key；不包含人工标签；
- 离线复现：`python -m app.evaluate_ranking --mode offline --input data/samples/w2/ranking/live_ranking_sample.csv --keyword "machine learning stellar parameter estimation spectra"`。
