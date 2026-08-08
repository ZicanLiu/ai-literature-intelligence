# ranking 任务 live 样例

- 文件：`live_ranking_sample.csv`
- 任务：第二周"TF-IDF 与两阶段排序"（蒲正杰）
- 数据来源：OpenAlex live 模式（`src.openalex_client.fetch_openalex_papers`）
- 检索词（keyword）：`machine learning stellar parameter estimation spectra`
- 请求数量：60；清洗去重后记录数量：60
- 获取时间（retrieved_at，UTC）：2026-07-27T12:27:51Z
- run_id：`20260731_185604465127_offline_machine-learning-stellar-parameter-estimation-sp_n60_c8e68d`（重新生成本文件的那次运行；本文件由
  `python -m app.evaluate_ranking --mode offline --input <完整字段原始数据> --keyword "machine learning stellar parameter estimation spectra" --sample-csv data/samples/w2/ranking/live_ranking_sample.csv`
  生成）

## 字段补齐说明（2026-07-28）

初版样本缺少 doi、authors、source_name、landing_page_url 等字段，导致从样本
离线重算时 completeness_score 变化、无法复现已提交的分析结果。现版本：

- 动态字段（title、abstract、cited_by_count、publication_year）保留
  2026-07-27 获取时的原快照值；
- 稳定身份字段（doi、authors、source_name、landing_page_url）于 2026-07-28
  按 openalex_id 从 OpenAlex 重新获取后补齐；
- 补齐后从本样本离线重算的分数与名次，与
  `data/analysis/w2_ranking/baseline_vs_two_stage.csv` 完全一致，
  由回归测试（`tests/automated/test_evaluation.py` 中 LiveSampleFieldTests
  与 LiveSampleReproductionTests）保证。
- 2026-07-31 第二次修正：3 篇缺失摘要的论文曾被误存为字符串 `nan`
  （NaN 在 CSV 读取后被 `str()` 化的结果），导致完整度被误判为字段存在；
  现统一把真正缺失的值保存为空，`load_papers_csv` 逐单元格用 `pd.isna`
  转成 None，不同 pandas 版本重算结果一致。

## 字段说明

- `keyword` / `retrieved_at` / `run_id`：来源追踪；`retrieved_at` 是数据从
  OpenAlex 获取的时间，`run_id` 是生成本文件的那次运行编号；
- `baseline_preliminary_score`：v0.2.0 `preliminary_score` 的基线副本；
- `title_relevance_score` / `abstract_relevance_score` /
  `combined_relevance_score`：TF-IDF 词法相关性分数
  （combined = 0.7 * 标题 + 0.3 * 摘要），只是词法相关性基线，不代表语义理解；
- `stage1_relevance_level`：第一阶段分层（high / medium / low，阈值 0.20 / 0.05）；
- `stage2_ranking_score`：第二阶段固定权重综合分；
- `old_rank` / `new_rank`：baseline 与两阶段排序名次，从 1 开始；
- 分数字段在分析时重新计算，`recency_score` 依赖运行时的当前年份；
  跨年份重算时分数会有微小差异，应按上文流程重新生成样本。

## 用途与边界

- 只用于开发、测试和人工分析，不是完整或权威的天文光谱文献集；
- 不包含 API Key；不包含人工标签；
- 离线复现：`python -m app.evaluate_ranking --mode offline --input data/samples/w2/ranking/live_ranking_sample.csv --keyword "machine learning stellar parameter estimation spectra"`。
