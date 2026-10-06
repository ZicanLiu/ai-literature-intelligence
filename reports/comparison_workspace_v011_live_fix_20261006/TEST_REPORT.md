# 测试与本地验证报告

日期：2026-10-06（Asia/Shanghai）。base：`4f7bf7a46a89fe3db5141a300889f4b008ce71fc`。
最终实现：`cd43fccc1b6649b1ec93b76c989f469529426688`。
只使用 sentinel / mock / 合成 PDF；真实 OpenAI / DeepSeek 请求 **0**。

## 环境

Git CLI 在指定 D 盘创建真实 linked worktree，`.git` 为合法 worktree 元数据。
新建被忽略的 `.venv`，使用 `python -m venv .venv --system-site-packages`，
按现有 `requirements-workspace.txt` / `requirements.txt` 安装；没有改依赖 pins 或复制秘密。
前端使用现有 package-lock 的 `npm ci`。

Python 3.13.9；OpenAI SDK 2.54.0；FastAPI 0.142.2；Pydantic 2.12.4；httpx 0.28.1；
Starlette 1.7.0；pypdf 6.19.0；uvicorn 0.54.0；Node 22.21.0；npm 10.9.4。
`npm run build` PASS。SDK / frontend 运行依赖与构建未提交。

## 定向与浏览器

| 阶段 | 实际运行 | 结果 |
| --- | --- | --- |
| A | 新安全模块 + HTTP false / omitted 用例 | 12 tests，PASS；subTest 覆盖两家 provider |
| B | `npm test -- tests/live-ai.spec.ts`，当时尚未添加 legacy 单例 | 9 passed，17.5s |
| B 补充 | `npm test -- tests/live-ai.spec.ts --grep 'legacy model'` | 1 passed，4.5s |
| C | 三个 comparison-workspace Python 模块 | 77 tests，PASS，11.090s |
| C 浏览器 | `npm test -- tests/workspace.spec.ts --grep-invert nonexistent`（过滤不排除任何实际用例） | 6 passed，13.7s |
| 修复污染后 | 上述三个 Python 模块 + 两个受影响 W5 CLI 方法，同一进程按该顺序运行 | 79 tests，PASS，10.180s |

浏览器共 16 个独立用例通过，分三次运行，不宣称一次统一的 16-test execution。
新增两家立即撤回 / 保存 / UI disabled、失败回读、不复活旧真实队列、successful / failed provenance；
旧 BYO 全流程与工作台流程仍通过。仅测试 mock 服务增加控制端点，生产 API 无测试端点。
mock 控制请求断言 HTTP 成功，worker barrier 阻塞实际 executor，统计实际 SDK mock 调用。

Python 新模块阻止 socket connect / connect_ex；实际 SDK 用 httpx.MockTransport 全内存响应。
Windows ASGI TestClient 内部需要本地 socketpair，HTTP false 验收放在既有 HTTP 测试类，
barrier / SDK 用例仍保持 socket guard。

## 唯一一次完整 canonical unittest

在实施提交 `771e423aa133624052422d840a99363afafab6d5`、Git-clean linked worktree 中执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/automated -p "test_*.py" -q
```

设置进程 `DISABLE_LIVE_API=true`。结果：**FAIL，1158 tests，249.644s，2 failures，15 skipped，0 errors**。
完整运行次数：**1**。本地原始日志：`temp/live-safety-validation/full_unittest.log`，不提交含本机临时路径的日志。
日志记录真实 revision / branch / `clean=True`；没有 archive 副本、伪 Git metadata 或历史测试数替代。

失败方法：

1. `test_w5_rank_fusion.FusionCliTests.test_cli_fuses_two_packages_and_self_validates`。
2. `test_w5_rank_fusion.FusionCliTests.test_cli_publish_copy_failure_leaves_no_partial_package`。

两者都被 `generation.platform` 的 system / release / machine 完整性校验提前阻断。
根因由本次新增实际 SDK 测试引入：清空全部进程环境后，在 Windows 首次调用平台信息，
`platform.machine()` 缓存空字符串。恢复环境后缓存仍为空，污染后续 W5 CLI。
独立进程诊断复现：正常 AMD64 → 清空环境空串 → 恢复仍空；保留真实 OS 变量后始终 AMD64。

修复只修改新增测试：保留 PROCESSOR_ARCHITECTURE / PROCESSOR_ARCHITEW6432 / SYSTEMROOT / WINDIR，
继续移除所有 provider 凭据及配置；不填写假的平台 metadata。
假换 Key 字符串同时改为明确 test 占位命名，安全扫描规则不变。
实际产品代码、W5 validator、冻结 artifact、科研 identity / assertion 均未改。
同进程安全模块后跟两个原失败方法已通过，见最终 79 项结果。

按提示词“完整 canonical offline validation ONCE”约束未再次运行完整 suite。
**这不是完整 suite PASS，定向复测和后续 Gate PASS 不能替代。需要成功完整复验才能闭合验收。**

开发定向迭代还修正了 raw wrapper 的 HTTP JSON 读取位置、mock 控制路由被 static mount 遮挡，
以及本机 Python 3.13 不提供平台缓存公开刷新 API；最终实现不调用该 API。
没有删断言、降低错误或改历史 warning 来通过。

## Gate / Git / 安全

完整结果记录后，修复污染并完成定向复测，再运行：

```powershell
.\.venv\Scripts\python.exe -m app.quality_gate --level basic --skip-tests
.\.venv\Scripts\python.exe -m app.quality_gate --level full --skip-tests
git diff --check
git status
```

- Basic：PASS，0 errors / 0 warnings，tests 明确 SKIPPED。
- Full：PASS，0 errors / 3 warnings，tests 明确 SKIPPED。
- 三条历史警告完整保留：W1 标注 1 个 CSV 结构问题；W1 的 19 个 ID 不在当前统一样例；
  已跟踪历史 experiments `openalex_stellar_spectra_60`。
- 运行环境仍提示 Starlette 的 httpx TestClient deprecation；负例测试的 `EOF marker not found` /
  FAIL CLOSED 日志保留，不等于新增测试失败。
- 完整 base diff / staged diff whitespace：PASS。
- sentinel 检查：0 findings，详见 [SECURITY_REGRESSION_REPORT](SECURITY_REGRESSION_REPORT.md)。
- 最终报告提交后 `git status --short` 为空；源 v0.1.1 HEAD 与工作树不变。

最终状态：`F1_F4_PASS_CANONICAL_RECHECK_REQUIRED`；`READY_FOR_ASTRA_DIFF_REVIEW = NO`。
