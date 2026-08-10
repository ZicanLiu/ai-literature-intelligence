# 第二周配置说明

本目录用于保存第二周任务的机器可读配置。配置文件应使用 UTF-8 编码，优先采用
JSON，并通过稳定且唯一的 `query_id` 关联查询、样例和实验结果。

建议命名：

- `domain_query_set.json`：领域查询配置，由领域查询任务负责人维护；
- `integration_batch.example.json`：批量集成配置示例，由组长整合确认。

配置文件不得包含 API Key、Token、个人绝对路径或 `.env` 内容。示例配置只能用于说明
字段和调用方式，不能表述为已经完成的真实配置。成员原则上只修改自己负责的配置；
需要调整他人配置或公共字段时，先在 Pull Request 中说明。最终正式配置由组长整合确认。

`domain_query_set.json` 已由领域词表生成；`integration_batch.example.json` 是可直接离线
执行的三条集成示例，使用 `tests/fixtures/pipeline/`，不会请求 OpenAlex。真实 live batch
应复制为本地配置后缩小请求规模，并继续保证 acquisition queries 与 ranking keyword
分别显式填写。
