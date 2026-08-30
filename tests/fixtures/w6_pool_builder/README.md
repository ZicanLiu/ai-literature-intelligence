# W6 Multi-Retriever Pool Builder fixture policy

本目录只包含 Pool Builder 自动测试使用的冻结 synthetic policy。Topic、retrieval runs/hits 和
source records 继续直接读取 `tests/fixtures/w6_bootstrap/valid/`，不复制、不修改公共 Bootstrap
fixture，也不依赖 canonicalization、annotation、benchmark 或 ranking evaluation artifact。

`pool_policy.json` 的 SHA-256 为：

```text
cdb6508ba7e62ec1daf122901c93abb94e0f5dfdd30d5f5ff5a98a2261b99713
```

该 policy 冻结以下 Builder v1 语义：

- included roster 包含公共 fixture 的 6 个 retrieval runs；
- depth 按 `acquisition_system` 配置，允许未来用 `retrieval_run_id` 做显式 override；
- depth 只决定 candidate admission；已入池 candidate 保留 included roster 中全部 hit provenance；
- 每 topic target 为 6、minimum 为 4；不足 target 时从其余 Broad Recall Universe 做确定性补齐；
- seed 固定为 `20260829`，随机生成器按 topic 派生，采样前先稳定排序；
- depth union 超过 target 时完整保留，不为凑固定大小裁剪 retriever contribution；
- 同一 topic-record 的重复命中只产生一个 pool member，但全部 hit references 继续保留。

这是接口测试配置，不是实际 W6 pool depth、target、minimum 或随机种子的研究决策。
