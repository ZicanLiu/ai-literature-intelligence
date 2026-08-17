# W4 Pilot Query Relevance judged set

当前版本为 [`v0.1.0`](v0.1.0/)，状态 `approved`；被审核的
[`v0.1.0-draft.1`](v0.1.0-draft.1/) 原样保留。

- `judgements.csv`：60/60 pair，所有 `final_label` 均为 `0/1/2`，无 pending review；
- `adjudication_proposals.csv`：3 个原 disagreement proposal 的人工 review 决定，保留双方原判断；
- `manifest.json`：冻结输入、六人 annotation、approved artifact、Blind AI Audit provenance、
  完整 input-set identity、parent draft 和 alias policy；
- approved manifest SHA-256：
  `d503f5c2448409a9433bf3ffeada3890c7ddb31237bc7c95c529014b5fb8d094`。

该版本由 **human annotation + independent blind AI evidence audit + human
review/adjudication** 形成；AI 只提供证据辅助，没有自动覆盖 human label。具体协议、字段
语义、versioning 和 strict evaluator 命令见
[`W4_PILOT_BENCHMARK_PROTOCOL.md`](../../../docs/project/W4_PILOT_BENCHMARK_PROTOCOL.md)。
Approved manifest 已绑定 parent draft 的路径/hash/version/input-set identity。

当前 draft 可复现生成：

```powershell
python -m app.build_w4_benchmark_draft
python -m app.validate_w4_benchmark --allow-draft
```

生成器默认拒绝覆盖；只有明确重建同一 draft 时才可在人工核对目标后使用 `--force`。

验证 approved package：

```powershell
python -m app.validate_w4_benchmark `
  --manifest data/benchmarks/w4_query_relevance/v0.1.0/manifest.json
```
