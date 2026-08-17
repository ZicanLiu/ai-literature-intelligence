# W4 Pilot Query Relevance judged set

当前版本为 [`v0.1.0-draft.1`](v0.1.0-draft.1/)，状态 `proposed`。

- `judgements.csv`：60/60 pair；57 条已有直接 judgement，3 条 `final_label` 仍为空；
- `adjudication_proposals.csv`：3 个 AI-assisted proposal，保留双方原判断和 reviewer 可填写列；
- `manifest.json`：冻结输入、六人 annotation、artifact hash、alias policy 和 promotion checklist。

Reviewer 应复制到新的 approved 版本目录后填写 review 结果，不覆盖此 draft。具体协议、字段
语义、versioning 和 strict evaluator 命令见
[`W4_PILOT_BENCHMARK_PROTOCOL.md`](../../../docs/project/W4_PILOT_BENCHMARK_PROTOCOL.md)。

当前 draft 可复现生成：

```powershell
python -m app.build_w4_benchmark_draft
python -m app.validate_w4_benchmark --allow-draft
```

生成器默认拒绝覆盖；只有明确重建同一 draft 时才可在人工核对目标后使用 `--force`。
