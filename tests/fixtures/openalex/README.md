# OpenAlex v2 离线 HTTP fixture

本目录只保存自动测试使用的小型 OpenAlex Works API 响应，不是 live 实验结果。

- `single_page.json`：两条记录的单页成功响应；
- `cursor_page_1.json`：带有下一页 cursor 的第一页；
- `cursor_page_2_with_duplicate.json`：包含一个跨页重复 OpenAlex ID 的末页。

fixture 使用 UTF-8 JSON，不含 API Key、Token、`.env` 内容或个人绝对路径。测试中
20、100、120 和 150 条记录的规模案例由确定性生成器构造，避免为简单计数提交大体积
重复数据。这些响应保留 OpenAlex 原始字段名；转换后的公共字段由客户端按
`docs/project/W2_DATA_CONTRACTS.md` 生成。
