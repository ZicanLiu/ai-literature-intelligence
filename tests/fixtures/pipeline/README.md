# Unified Pipeline fixtures

- `domain_terms.csv`：覆盖六个固定 query blueprint 所需词项的最小词表。
- `offline_queries.json`：两个 query 的离线 fetch 结果，包含跨 query OpenAlex ID 重复、DOI 重复和疑似重复。
- `labels.csv`：只用于离线 judged 评价的最小标签集。

这些文件只服务自动测试，不代表真实 OpenAlex 请求或正式科研样本。
