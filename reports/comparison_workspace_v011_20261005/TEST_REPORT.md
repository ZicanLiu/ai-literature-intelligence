# v0.1.1 测试报告

日期：2026-10-05。全部自动化使用合成 PDF、mock SDK 和临时数据；无真实 provider 请求。
测试 Python 复用已有项目虚拟环境；没有复制 .env 或 session credential。

## 已执行定向验证

| 验证 | 结果 |
| --- | --- |
| unittest discover -s tests/automated -p test_comparison_workspace*.py -q | 65 tests，6.524s，OK：原 45 + 新 20 |
| npm ci | 完成，audit 0 vulnerabilities |
| npm run build | TypeScript / Vite PASS |
| npm test | 9 passed，22.4s：原 6 + 两家完整 BYO 流程 + 隔离 / v4-pro 能力流程 |
| python -m pip check | No broken requirements found |
| git diff --check | PASS |

首次新 browser 流程复现 Live 复选框异步回跳，已修复为立即更新并等待服务器确认；最终全部通过。
新 mock helper 初次 kwargs 不匹配已修正；没有删断言或降低通过条件。
之后 backend 增补安全 request ID 与已捕获凭据撤销回归，定向最终 65 项通过。

## 回归覆盖

双凭据隔离 / 清除 / 环境回退 / session 优先 / 进程重启、默认关闭 / provider consent / 硬离线、
任意 endpoint 拒绝、真实 adapter 的 schema / reasoning / metadata、malformed / refusal / incomplete、
auth / model unavailable / rate / timeout / network，无自动重试；两个 browser 完整流程到证据、修订和三种导出。
SQLite / Run / GET / error / export / log sentinel 不持久化，browser storage 无 Key。
新 browser 流程关闭 traces，mock server 替换 SDK transport，环境真实凭据在测试子进程丢弃。

## 最终 canonical 验证

验证基准为 clean 065b43bd284562db22eb7f8b602f33c46916463f。
完整离线 suite 只运行一次，随后按 canonical 顺序执行两级 Gate，明确不重复 unittest。

| 实际命令（同一 Python 虚拟环境） | 结果 |
| --- | --- |
| python -m unittest discover -s tests/automated -p "test_*.py" -q | 1146 tests，260.473s，OK（15 skipped），exit 0 |
| python -m app.quality_gate --level basic --skip-tests | 577 files，0 errors / 0 warnings，PASSED；tests SKIPPED |
| python -m app.quality_gate --level full --skip-tests | 577 files，0 errors / 3 warnings，PASSED；tests SKIPPED |
| git diff --check | PASS |
| git diff --check fc7de566420829e3b53ac511b0ae9e82a566bba3 HEAD | PASS |

Full 三条警告为历史 W1 CSV 结构、19 个旧 ID 不在当前统一结果、已跟踪旧 experiment。
15 项跳过不计为验证通过；本次未新增 skip、删断言或改历史材料换取 PASS。
见到 Starlette TestClient 的 httpx 弃用提示、损坏 PDF EOF 诊断及既有负向 fail-closed 输出；最终 suite exit 0。
测试 runtime：Python 3.13.9，OpenAI SDK 2.54.0，Pydantic 2.12.4，FastAPI 0.142.2，Node 22.21.0。

完整 diff 仅包含 26 个本任务产品源码、测试、指南和新报告文件，未修改冻结研究数据。
提交 diff 及 54 个声明测试产物 / build / 新报告文件的完整 sentinel 扫描通过。
最终只补记报告，不改变源码；不再重复完整 suite。GitHub Linux CI 未运行，推送前仍需独立审阅。
不会把工程 PASS 提升为科研优越性或真实 API 质量结论。
