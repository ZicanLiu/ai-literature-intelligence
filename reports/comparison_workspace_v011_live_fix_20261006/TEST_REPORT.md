# 测试与本地验证报告

初次报告：2026-10-06；最终 canonical 验收：2026-10-07（Asia/Shanghai）。base：`4f7bf7a46a89fe3db5141a300889f4b008ce71fc`。
最终实现：`cd43fccc1b6649b1ec93b76c989f469529426688`。
只使用 sentinel / mock / 合成 PDF；真实 OpenAI / DeepSeek 请求 **0**。

## 2026-10-07 最后一次 canonical validation（当前结果：PASS）

被验 HEAD：`dfa507822036846b1ea33cc6b05d498c3b059263`。
原 D 盘 linked worktree、分支 `codex/comparison-workspace-v011-live-safety-fix`；
执行前和 suite / Gate 完成后均为该精确 HEAD，Git status clean，`.git` 元数据有效。
本轮没有修改功能、测试、断言、依赖或冻结 artifact；没有使用 archive 副本或伪 Git metadata。

### 实际关键环境

本次 shell 明确执行 `$env:PYTHONIOENCODING = $null`，并检查该变量不存在。
仅设置非编码开关 `DISABLE_LIVE_API=true`，没有新增 Python 编码环境变量。
环境审计采用非敏感变量白名单，不读取或输出 API Key，也不读取 `.env`。

| 项 | 实际值 |
| --- | --- |
| Python / OS / 架构 | 3.13.9 / Windows 11 / AMD64 |
| locale / preferred encoding | cp936 / cp936 |
| stdout / stderr encoding | gbk / gbk |
| Python UTF-8 mode | 0 |
| PYTHONIOENCODING / PYTHONUTF8 | 均未设置 |
| PYTHONCOERCECLOCALE / PYTHONLEGACYWINDOWSSTDIO / PYTHONLEGACYWINDOWSFSENCODING | 均未设置 |
| PROCESSOR_ARCHITECTURE / PROCESSOR_ARCHITEW6432 | AMD64 / 未设置 |
| SYSTEMROOT / WINDIR | C:\Windows / C:\Windows（系统目录） |
| DISABLE_LIVE_API | true |

依赖版本与历史环境记录一致；没有安装或调整依赖。原始 stdout / stderr 直接写二进制日志，
展示和汇总按实际 cp936 解码，不改变测试进程或它的子进程编码。

### 严格顺序及结果

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/automated -p "test_*.py" -q
.\.venv\Scripts\python.exe -m app.quality_gate --level basic --skip-tests
.\.venv\Scripts\python.exe -m app.quality_gate --level full --skip-tests
git diff --check
git status
```

| 步骤 | 本次实际结果 |
| --- | --- |
| 完整 canonical unittest | **PASS，1158 tests，335.733s，0 failures / 0 errors，15 skipped，exit=0** |
| 本轮完整 suite 次数 | **1**；没有定向补跑或重复完整运行 |
| Basic Gate | PASS，0 errors / 0 warnings；tests 明确 SKIPPED，exit=0 |
| Full Gate | PASS，0 errors / 3 historical warnings；tests 明确 SKIPPED，exit=0 |
| git diff --check | PASS，exit=0 |
| git status | clean，exit=0 |

Full Gate 仍保留三条历史警告：W1 的 1 个 CSV 结构问题；W1 的 19 个 ID 不在当前统一样例；
已跟踪历史 experiments `openalex_stellar_spectra_60`。没有改变警告、验证器或断言。
此前 W5 平台缓存问题和上一轮五个编码 error 均未重现。
临时 Gate 汇总脚本曾有一条非阻断的 `SyntaxWarning: invalid escape sequence`，
来自 stdin 脚本的结果提取正则；Gate 原始日志及实际退出码均 PASS，没有改仓库或重复运行 Gate。

本次本地证据目录：`temp/live-safety-canonical-final-dfa5078/`。
包含白名单 `environment.json`、`unittest_result.json`、`full_unittest.raw.log`、
`basic_gate.raw.log` / `full_gate.raw.log`、两份 `*_gate_result.json` 和 `post_validation_git.json`。
环境、完整 suite、两级 Gate 和 clean 状态都绑定同一 `dfa5078` HEAD。
含临时本机路径的原始日志不提交；此前失败日志保持原样。

本轮仅允许随后修改 TEST_REPORT 和 ASTRA_REVIEW_HANDOFF 的报告-only 提交；
其余 Git 跟踪内容相对被验 HEAD 必须不变。报告更新的本地链接、安全及 diff 检查独立进行，
不再重复完整 suite。当前状态：**`READY_FOR_ASTRA_DIFF_REVIEW = YES`**。
此状态只表示离线工程验收完成并可交 Astra 复审；真实 API 未验证，S0 仍需单独明确授权。

## 2026-10-07 在 9214024 的复验（历史编码失败）

用户明确授权在 HEAD `92140244325fb9d62fe8e1479bcffdb6fb7d654f` 重新运行一次完整 canonical suite。
运行前核对 Git status / branch / log / HEAD / worktree list；D 盘原 linked worktree 的 `.git`
仍指向真实 Git worktree 元数据，分支为 `codex/comparison-workspace-v011-live-safety-fix`，工作树 clean。
原 v0.1.1 工作树 clean、HEAD 仍为 base。依赖版本与下方初次报告一致，没有安装或修改依赖。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/automated -p "test_*.py" -q
```

该轮完整运行 **1 次**；结果 **FAIL，1158 tests，379.525s，0 failures，5 errors，15 skipped，exit=1**。
此前两项 W5 平台缓存失败未重现。五个 error 均来自同一个方法的五个 subTest：

`test_pilot_selection_context.ExternalCoordinatorCliSequenceTests.test_real_cli_sequence_stays_external_and_git_clean`

labels：`import`、`compare`、`adjudication_task`、`adjudication_import`、`final`。

### 编码原因及诊断

该轮启动设置了 `DISABLE_LIVE_API=true`，另为日志显示设置 `PYTHONIOENCODING=utf-8`。
后者是该次验证启动引入的环境覆盖，不是仓库代码变化。
该设置使 Python CLI 子进程的 stderr 输出 UTF-8，但测试中的
`subprocess.run(capture_output=True, text=True)` 未指定 encoding，当前 Windows 默认解码为 cp936 / GBK。
五次捕获 stderr 的读取线程均发生 `UnicodeDecodeError: 'gbk' codec ...`。
CPython 读取线程未能填入 stderr buffer，`CompletedProcess.stderr` 因此为 None；
随后 `assertIn("repository root 之外", result.stderr)` 在 1094 行产生 TypeError。

精确检查位置：`tests/automated/test_pilot_selection_context.py:1076` 的子进程捕获、`:1094` 的消息断言，
以及 `app/pilot_curator_workflow.py:278` 的 stderr 输出。
这些文件相对 base 与被验 HEAD 均无本修复差异。
已核对本地 CPython 的 `_text_encoding`、`_readerthread` 和 `_communicate`：默认使用 locale 编码，
读取异常后空 buffer 转成 None；无需推测业务 CLI 未执行拒绝逻辑。

两个只读 / 临时输出诊断均未修改功能或断言：

1. 用原始字节捕获同一中文 stderr，保持父进程默认 cp936：强制子进程 UTF-8 时解码失败，
   不强制时解码正确。结果保存为 `encoding_diagnosis.json`。
2. 保持 `DISABLE_LIVE_API=true`，取消 `PYTHONIOENCODING` 覆盖，在同一 clean HEAD 单独运行原失败方法：
   **1 test，8.627s，PASS，exit=0**，包含原有五个 subTest 及所有 Git-clean / 禁止仓内输出断言。

诊断定位到验证环境的生产 / 解码编码不一致；不据单个方法 PASS 宣称完整 suite PASS。
该轮没有追加第二次完整运行。按当时用户“全部通过后才运行 Gate”的条件，
**该轮 Basic / Full Gate 均 NOT_RUN**；没有以 2026-10-06 Gate PASS 替代该轮失败。
本次最新授权后的完整复验已保持输出 / 解码一致并 PASS，见第一节；历史失败结果不改写。

该轮本地原始记录均在 `temp/live-safety-final-validation-20261007/`：
`git_context.json`、`unittest_result.json`、`full_unittest.log`、`encoding_diagnosis.json`、
`external_cli_encoding_diagnostic.log`。不覆盖初次失败日志，不提交含本机路径的原始日志。
该轮只更新 TEST_REPORT 和 ASTRA_REVIEW_HANDOFF，源码、测试、依赖和冻结 artifact 均未修改。
报告的 whitespace / Git diff 单独检查不构成测试验收；当时 `READY_FOR_ASTRA_DIFF_REVIEW = NO`。

## 2026-10-06 环境（历史记录）

Git CLI 在指定 D 盘创建真实 linked worktree，`.git` 为合法 worktree 元数据。
新建被忽略的 `.venv`，使用 `python -m venv .venv --system-site-packages`，
按现有 `requirements-workspace.txt` / `requirements.txt` 安装；没有改依赖 pins 或复制秘密。
前端使用现有 package-lock 的 `npm ci`。

Python 3.13.9；OpenAI SDK 2.54.0；FastAPI 0.142.2；Pydantic 2.12.4；httpx 0.28.1；
Starlette 1.7.0；pypdf 6.19.0；uvicorn 0.54.0；Node 22.21.0；npm 10.9.4。
`npm run build` PASS。SDK / frontend 运行依赖与构建未提交。

## 2026-10-06 定向与浏览器（历史记录，本轮未重跑）

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

## 2026-10-06 首次完整 canonical unittest（历史记录）

在实施提交 `771e423aa133624052422d840a99363afafab6d5`、Git-clean linked worktree 中执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/automated -p "test_*.py" -q
```

设置进程 `DISABLE_LIVE_API=true`。结果：**FAIL，1158 tests，249.644s，2 failures，15 skipped，0 errors**。
当日完整运行次数：**1**。本地原始日志：`temp/live-safety-validation/full_unittest.log`，不提交含本机临时路径的日志。
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

当日按提示词“完整 canonical offline validation ONCE”约束未再次运行完整 suite。
**该次历史结果不是完整 suite PASS，定向复测和后续 Gate PASS 不能替代。**
2026-10-07 两次分别授权的复验结果见前文，各次失败记录及最终 PASS 均保留。

开发定向迭代还修正了 raw wrapper 的 HTTP JSON 读取位置、mock 控制路由被 static mount 遮挡，
以及本机 Python 3.13 不提供平台缓存公开刷新 API；最终实现不调用该 API。
没有删断言、降低错误或改历史 warning 来通过。

## 2026-10-06 Gate / Git / 安全（历史记录）

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

当前最终验证状态：**`READY_FOR_ASTRA_DIFF_REVIEW = YES`**。
本轮真实 API 请求 **0**，未 push / PR / merge；后续为 Astra diff review，S0 需另行明确授权。
