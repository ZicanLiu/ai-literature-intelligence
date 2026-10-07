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

## 完整验收

完整 canonical unittest 一次、Basic / Full `--skip-tests` 和最终 secret sentinel scan 尚待运行。
完整业务、前端、测试和报告 diff 已逐项检查；本报告将在最终 clean HEAD 验收后更新。
