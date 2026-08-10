# Batch 输出

`python -m app.batch_runner` 在这里为每次批量实验创建唯一 `<batch_id>/`，保存配置快照、
JSON 摘要和 CSV 摘要。每个 batch item 的完整论文产物仍位于
`outputs/experiments/<run_id>/`，两者通过 `batch_id`、`item_id` 和 `run_id` 关联。

普通 batch 结果默认被 `.gitignore` 忽略。需要长期保存时，应先核对来源、配置、统计和
敏感信息，再通过独立任务提升；不要直接把临时 batch 目录当作稳定基线。
