# W6 Research Contract Bootstrap fixtures

本目录只保存完全离线、确定、明确标记为 synthetic fixture 的公共接口样例。它不是 W6
Research Topic、Candidate Pool、annotation、hidden labels 或 Benchmark v0.2-alpha 的真实产物。

## 公共入口

```powershell
python -m app.validate_w6_bootstrap
```

默认入口是 [`valid/bundle_manifest.json`](valid/bundle_manifest.json)。Bundle 对全部公开 artifact
固定 `artifact_id + SHA-256`，并为六个后续任务声明 `depends_on=["w6_bootstrap"]`。任何成员都可只
复制自己需要的 fixture 文件；不需要等待另一成员生成真实 artifact。

## Valid fixture 覆盖

- 两个 fake frozen topics，每个有两个 query variants、scope-in/out 和 boundary cases；
- 10 个 fake source records、13 个 topic-record pool items；
- relevant、partial、irrelevant、wrong-object hard negative、task boundary、missing abstract；
- 同一 record 跨 topic、同一 record 被多个 retriever 命中、single-retriever-only candidate；
- 一对 high-confidence confirmed alias，另有一对仍为 pending review 的 suspected duplicate；
- retrieval run/config/seed/rank/raw-score/Git/hash provenance 和 deterministic pool identity；
- 严格的 full record → blind annotation view，完全不含 method/rank/score/retrieval provenance；
- AI assistant / AI-assisted human primary annotations、独立 human review/adjudication artifact 和
  0/1/2 labels；
- 一个 fake topic-level Dev/Hidden split、公开 seal anchor 和单独的 fake reveal artifact；
- 三个 W5-column-compatible fake method packages，包括 raw scores、ranks、input hashes 和
  normalization extension point；
- 短 public snippet / structured field evidence units、supported/partial/unsupported structured
  claims，以及由 claim IDs 渲染的 fixture Markdown；
- `bootstrap_fixture` 状态的 Benchmark manifest skeleton，明确不是 approved benchmark。

`valid/sealed/fake_hidden_labels.json` 只用于测试 reveal 边界。公开 bundle、method manifests 和
synthesis inputs 都不引用它的路径；公开 anchor 只保存 fixture identity/hash。真实 W6 hidden
labels 必须放在普通仓库之外。

## Deliberate invalid fixtures

[`invalid/invalid_cases.json`](invalid/invalid_cases.json) 用小型、确定的 mutation recipe 表达
fail-closed regression，避免复制整份 valid artifact。覆盖：

- duplicate/unknown topic、topic Dev/Hidden overlap、missing provenance；
- blind annotation score leak；
- dangling canonical alias；
- candidate identity mismatch；
- illegal relevance label、unknown candidate/review target、公开 hidden-topic annotation；
- hidden labels 出现在 method generation inputs；
- synthesis dangling evidence、supported claim 缺少 evidence；
- bundle manifest hash/path 不可信。

测试可在临时目录中进一步模拟 hash tampering 和 method-input identity drift。不得“修好”这些
invalid fixture 后把 validator 改成接受它们。

## 安全边界

Fixtures 不访问 OpenAlex、模型仓库或任何 live API，不下载神经模型，不读取 `.env`，也不包含
真实成员 annotation 或科研结论。所有 URL 都使用 `example.test`；所有论文内容均为短 synthetic
text。
