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

完整 suite 在提交后的 clean worktree 运行一次，然后 Basic / Full 使用 --skip-tests。
当前阶段待执行；完成后将在本报告补记真实数量、耗时、跳过项与 Gate 警告。
不会把工程 PASS 提升为科研优越性或真实 API 质量结论。
