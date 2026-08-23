# W5 CI 与可复现性门禁

## 1. 范围

本任务为 core repository 增加一个最小 GitHub Actions workflow，不修改排序算法、W4 Benchmark、
Candidate Pool、Research Query 或公共 W5 Contract。Workflow 在 `pull_request → main` 与
`push → main` 时运行 Python 3.13 core 验收。

## 2. Workflow 门禁

CI 使用 `requirements.txt` 安装 core 依赖，并把以下命令拆成可单独定位失败的 step：

1. PR diff 的 `git diff --check`；
2. `python -m app.validate_w4_benchmark`；
3. 全量 `tests/automated` 离线 unittest；
4. Basic Quality Gate；
5. 正式 W5 method artifact checker。

任一步失败都会使 job 失败；workflow 不使用 `continue-on-error`，不引用 secrets，也不安装
SPECTER2、Cross-Encoder、Torch、Transformers 或 GPU 依赖。

## 3. 正式 W5 artifact discovery 与验证

Checker 只扫描明确的正式提升目录：

```text
data/analysis/w5_methods/<method-id>/manifest.json
```

它不会递归扫描整个仓库，因此不会把 `tests/fixtures`、W4 benchmark manifest、无关 JSON 或更深
层的临时文件误认为正式 method artifact。当前分支尚无正式 W5 method package，0 artifact 会输出
清晰的 no-artifact 信息并以 0 退出。

发现一个或多个 package 时，checker 会逐个调用公共
`src.w5_method_contract.validate_method_output()`，不复制 validator 逻辑。全部合法才返回 0；任一
非法 package 都返回 1，并保留其他 package 的逐项 PASS/FAIL 结果。

## 4. Live API 边界

Workflow 声明 `DISABLE_LIVE_API=true` 作为离线 CI 的意图标识，但当前项目代码不消费该变量，
因此它本身不是网络沙箱，也不应被表述为“技术上强制禁止一切 Live API”。当前离线保证来自 CI
只选择 strict validator、fixture/mock 驱动的自动测试、Quality Gate 和本地 artifact checker；
workflow 不调用任何 live CLI、不提供 API secrets，也不安装会下载模型的可选依赖。

## 5. 测试口径

Workflow contract 保留轻量字符串 smoke check；`requirements.txt` 不含 YAML parser，因此本任务
不额外引入解析或 Actions 模拟依赖。Artifact checker 另有真实行为测试，覆盖：

- 0 artifact；
- 单个合法 artifact；
- 多个合法 artifact；
- 任一非法 artifact 导致失败；
- 正常 `<method-id>/manifest.json` discovery；
- fixture、无关 JSON 与非约定深度 manifest 不被扫描。

这些测试完全离线，并实际复用公共 W5 validator。

## 6. 验证边界

本地实际验证结果：

- CI workflow/checker 定向测试：10 项通过；
- 全量离线 unittest：337 项通过；
- W4 approved benchmark strict validator：60/60，通过；
- Basic Quality Gate：0 error / 0 warning，通过；
- Full Quality Gate：0 error / 3 个公共历史 warning，通过；
- 正式 artifact checker：当前 0 artifact，清晰跳过并以 0 退出；
- `git diff --check`：通过。

本地可验证 workflow contract、checker 行为以及 workflow 中的所有项目命令。由于本次不 push，
不会产生新的 GitHub Actions run；真实 GitHub CI 状态必须在后续 push 更新原 PR 后重新确认。
