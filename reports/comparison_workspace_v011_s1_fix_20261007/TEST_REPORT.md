# S1 修复离线验收

日期：2026-10-07（Asia/Shanghai）。基线 `d818eb1`。
只使用 SDK mock / 合成 PDF / sentinel。真实 API 调用：**0**；未读取 `.env`。

## 定向回归

系统 Python 首次定向启动缺少可选 FastAPI，1 个 import error，未进入测试。
随后复用已审核 live-safety 工作树的 `.venv` 解释器，以本任务工作树为 cwd；没有复制配置或私有数据，
没有修改依赖版本。新测试保留 Windows 平台元数据并清除 provider 环境配置；SDK/socket 均受 mock guard 约束。

```powershell
& ../comparison-workspace-v011-live-safety-fix/.venv/Scripts/python.exe -m unittest tests.automated.test_comparison_workspace_s1_diagnostics tests.automated.test_comparison_workspace_live_ai tests.automated.test_comparison_workspace_live_safety tests.automated.test_comparison_workspace -q
```

第一轮业务定向：**87 tests，14.455s，PASS**。
保留既有 Starlette deprecation 和坏 PDF 负例 `EOF marker not found`，没有降低错误或删除断言。
Source diagnostic 小调整后中间定向 10 tests / 1.703s / PASS；随后补充不可信 provider status / usage
泄漏用例，最终 S1 定向 **11 tests / 1.995s / PASS**。

## 前端与浏览器

`npm ci --offline --no-audit --no-fund` 从本机缓存安装现有 lockfile 的 76 个包，没有改依赖 pins。
`npm run build`（TypeScript + Vite）：PASS。
浏览器使用该工作树构建、已审核 `.venv` 解释器及两份仅 loopback 的测试服务器；
mock 服务器明确清除环境凭据，所有 provider SDK transport 被替换，credential 流程禁用 trace/screenshot。

```powershell
npm test
npm test -- tests/live-ai.spec.ts --grep 'operation defaults'
```

首次统一运行：**18 passed / 1 failed，49.7s**。
唯一失败是新默认值用例的 `getByRole('status')` 同时匹配页面 toast 和 AI 设置提示，
并非产品运行失败。将该断言限定到 AI 设置 dialog，没有删除断言或放宽期望。
纠正后仅补跑该用例：**1 passed，9.5s**。全部 **19 个独立浏览器用例**已覆盖并通过，
分两次运行，不宣称一次完整的 19-test PASS。
新增两家 provider incomplete / completed identity 诊断、项目状态不变、默认 effort 与显式 override；
既有手工/合成演示、撤回授权、历史 model、导出和布局用例保留。

## 完整 canonical unittest（一次）

被验 clean HEAD：`e46f855252125babd7fe0a30d966a3260bcb543c`；真实 D 盘 linked worktree。
用已审核 `.venv` 解释器执行标准命令，移除子进程 provider 环境凭据、设置 `DISABLE_LIVE_API=true`，
不读取 `.env`，不改变 Python 输出编码。

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -q
python -m app.quality_gate --level basic --skip-tests
python -m app.quality_gate --level full --skip-tests
git diff --check
```

完整 unittest：**1169 tests，285.106s，OK（15 skipped），exit=0**。
本任务完整 suite 次数 **1**。前后均为同一 HEAD，Git-clean；没有 archive 副本或伪 Git metadata。
Python 3.13.9；stdout=gbk，preferred encoding=cp936，UTF-8 mode=0，PYTHONIOENCODING 未设置。
OpenAI SDK 2.54.0、FastAPI 0.142.2、Pydantic 2.12.4、httpx 0.28.1、pypdf 6.19.0、uvicorn 0.54.0。

随后首次 Basic Gate：**FAIL，1 error，0 warnings，tests 明确 SKIPPED**；错误为新负例测试源码的
合成用户目录路径前缀被个人绝对路径扫描拒绝。Full 当时未运行。
修复只将该测试的合成路径分段构造；实际测试值、编译后的测试 bytecode 和 constants 均核对相等。
业务源码、断言、Gate 规则和冻结 artifact 没有改变。原方法定向复验：**1 test / 0.151s / PASS**。
遵守任务完整 suite 仅一次的要求，不重复完整 unittest。两级 Gate 在修复后的 clean commit
`b1b228978aae256024ab7ecf6ad9cca4605c196d` 复验，均明确 `--skip-tests`；不会以 Gate 替代测试。

| 检查 | 最终实际结果 |
| --- | --- |
| Basic Gate | PASS；0 errors / 0 warnings；tests SKIPPED；exit=0 |
| Full Gate | PASS；0 errors / 3 historical warnings；tests SKIPPED；exit=0 |
| Git before / after Gate | 相同 b1b2289 HEAD，clean |
| 全部业务源码相对完整测试 HEAD | 无差异；仅负例路径的等价构造与报告更新 |
| 完整 unittest 次数 | 1；未在 Gate 内重复 |

Full 的三条原有 warning 保留：W1 的 1 个 CSV 结构问题；19 个旧标注 ID 不在当前统一样例；
已跟踪历史 experiments `openalex_stellar_spectra_60`。没有删断言、放宽错误、降低 warning 或改历史 evidence。
最初 Basic 的失败 raw log 和最终两级 Gate raw logs 分开保存，不覆盖前次失败记录。

## 安全与交付检查

完整业务、前端、新旧测试、mock 和四份报告 diff 已逐项检查，whitespace PASS。
提交前安全扫描 98 个任务文件/产品构建/合成浏览器数据库与结果，sentinel / 真实密钥格式命中 **0**，
未读取环境凭据值或 `.env`。广义 assignment 规则另有四个已人工核对的非敏感命中：
两个基线测试占位字符串、未变 PDF.js worker 的两个 JS 变量表达式。
没有豁免 sentinel 或真实密钥格式，也没有修改产品安全 validator；命中和复核结果如实记录。
最终扫描包含完整测试及两级 Gate 的本地日志，共 **109 个文件，0 findings**；四个已复核的
非敏感 assignment 命中单列保留。环境凭据值未被检查，`.env` 未读取。

本地验证证据在 ignored `temp/s1-canonical-validation-20261007/` 与
`temp/s1-gates-after-literal-fix-20261007/`，raw logs 不提交。
原产品工作树仍为 `d818eb1` / clean；原入口工作树的既有未跟踪报告没有改动。
最终报告提交后只检查报告 diff / whitespace、来源范围、Git-clean 和 sentinel，不重复已通过的测试。
