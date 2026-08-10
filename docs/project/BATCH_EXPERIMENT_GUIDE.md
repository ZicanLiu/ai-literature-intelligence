# W2 批量实验指南

Batch Runner 只负责读取配置、逐项调用 `src.pipeline.run_unified_pipeline()` 并汇总结果，
不复制获取、去重或排序代码。

## 离线示例

```powershell
python -m app.batch_runner --config configs/w2/integration_batch.example.json
```

示例包含三项：单独运行 `q01_broad_ml`、单独运行 `q02_classification`、合并运行两组查询。
它们使用测试 fixture，不联网。每项产生独立 parent run；batch 自身在
`outputs/batches/<batch_id>/` 保存：

- `batch_config.json`：带 `batch_id` 的配置快照；
- `batch_summary.json`：机器可读状态、计数和 run 关联；
- `batch_summary.csv`：便于人工查看的同内容摘要。

## 配置字段

顶层字段：

- `batch_name`：批次名称；
- `continue_on_error`：某项失败后是否继续；
- `terms_path`：默认领域词表；
- `items`：实验列表。

每个启用的 item 至少写：

- `item_id`；
- `acquisition_query_ids`；
- `ranking_keyword`；
- `mode`；
- `max_results_per_query`；
- offline 时的 `offline_fixture_path`。

可选字段包括 `from_year`、`to_year`、`labels_path`、`evaluation_k`、
`include_unverified_labels` 和 `run_name`。配置不接受含义模糊的单个 `query_id`；领域
query ID、child request/run ID、parent run ID、batch item ID 和 batch ID 必须分开。
`continue_on_error`、`enabled`、`include_unverified_labels` 必须使用真正的 JSON
`true/false`，字符串或数字不会被静默转换。

`continue_on_error=true` 时，失败 item 记为 `failed`，后续 item 继续；batch 最终仍返回
非零退出码并标记 `completed_with_errors`。为 false 时，后续项记为
`not_run_after_failure`。这两种情况都不会伪装成功。

普通 batch 与 experiment 输出默认忽略。若要把结果提升为长期 evidence，应另开任务检查
来源、统计、配置、敏感信息和复现命令，不要直接提交整个临时目录。
