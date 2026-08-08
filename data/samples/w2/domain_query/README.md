# 第二周领域查询 live 样例

- `live_query_sample.csv`：2026-08-08 三组 OpenAlex live 查询的整理样例；原始 90 行按
  OpenAlex ID 合并为 82 条，并记录所有来源 query_id 和 run_id。
- `query_results_summary.csv`：三次运行的数量、标注子集和待复核数量摘要。

查询词来自 `configs/w2/domain_query_set.json`。文件只包含公开论文元数据和项目追溯字段，
不包含 API Key、`.env` 内容或论文全文。相关性计数只覆盖已进入标注集的子集；其他结果
仍为待复核，不能把本样例视为完整或权威的天文光谱文献集。
