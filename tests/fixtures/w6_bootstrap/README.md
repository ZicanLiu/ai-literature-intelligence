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
- 10 个 fake source records、13 个 topic-record pool items 的 pre/post canonicalization 两个 pool；
- relevant、partial、irrelevant、wrong-object hard negative、task boundary、missing abstract；
- 同一 record 跨 topic、同一 record 被多个 retriever 命中、single-retriever-only candidate；
- 一对 high-confidence confirmed alias，另有一对仍为 pending review 的 suspected duplicate；
- retrieval run/config/seed/rank/raw-score/Git/hash provenance、冻结 included-run roster、精确 hit/system
  union 和 deterministic pool identity；
- 独立 opaque annotation item mapping 与严格 blind view；公开 task 不含内部 pool/record/canonical ID，
  也不含 method/rank/score/retrieval provenance；
- AI assistant / AI-assisted human primary annotations、独立 human review/adjudication artifact 和
  0/1/2 labels；
- 一个在 annotation start 前冻结并由 annotation artifact 绑定 hash 的 fake topic-level Dev/Hidden
  split，以及只声明外部 label identity/hash 的公开 sealed anchor；
- 三个 W5-column-compatible fake method packages，包括 raw scores、ranks、input hashes 和
  normalization extension point；
- 短 public snippet / structured field evidence units、supported/partial/unsupported structured
  claims，以及由 claim IDs 渲染的 fixture Markdown；
- `bootstrap_fixture` 状态的 Benchmark manifest skeleton，明确不是 approved benchmark。

Bootstrap 不保存 fake/真实 hidden-label 文件，也不提供 reveal API；公开 anchor 只保存 external
artifact identity/hash，`repository_path` 必须为 null。真实 W6 hidden labels 可始终放在普通仓库
之外，由未来独立 sealed evaluator/custodian contract 管理。

## Deliberate invalid fixtures

[`invalid/invalid_cases.json`](invalid/invalid_cases.json) 用小型、确定的 mutation recipe 表达
fail-closed regression，避免复制整份 valid artifact。覆盖：

- duplicate/unknown topic、topic Dev/Hidden overlap、missing provenance；
- blind annotation key/value identity leak；
- dangling canonical alias；
- candidate identity mismatch、冻结 retrieval provenance union 不完整；
- illegal relevance label、unknown candidate/review target、公开 hidden-topic annotation；
- hidden labels 出现在 method generation inputs；
- synthesis dangling/out-of-selection/rejected evidence、supported claim 缺少 evidence、input hash drift；
- bundle manifest hash/path 不可信。

测试还会在临时目录中模拟 hash tampering、method-input/weight identity drift，并对六个 future
task 各自只复制声明 artifact 做隔离 smoke；缺少任一声明输入必须失败。不得“修好”这些 invalid
fixture 后把 validator 改成接受它们。

## 安全边界

Fixtures 不访问 OpenAlex、模型仓库或任何 live API，不下载神经模型，不读取 `.env`，也不包含
真实成员 annotation 或科研结论。所有 URL 都使用 `example.test`；所有论文内容均为短 synthetic
text。
