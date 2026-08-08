# 领域查询测试 fixture

- `sample_papers.csv` 提供两个可追溯的 OpenAlex Work ID；
- `labels_valid.csv` 提供合法的四级中文标签样例。

测试中的非法词典和非法标签由 `tempfile` 动态生成，避免把容易误用的坏数据留在正式
样例目录。fixture 仅用于离线单元测试，不触发网络请求。
