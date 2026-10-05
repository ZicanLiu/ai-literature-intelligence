# 推送前独立审阅

日期：2026-10-05。本轮无 push / PR / merge / tag / release；PR #87 保持原 head。

建议独立审查：

1. 服务端 secret-only 请求合同、验证错误与 SDK failure 脱敏，固定 endpoint 与本地 Host / Origin 边界。
2. 会话 Key / 环境 Key 隔离、清除及重启、数据发送确认、关闭 Live / 切换 / 排队任务配置快照。
3. DeepSeek JSON Schema 和 reasoning.effort 与核对日官方合同一致；Flash / Pro 图像能力按模型表达。
4. Run 来源、source / active result snapshot、原 provider 输出、用户 correction 与 stale 语义保持原边界。
5. 两家 mocked browser 流程、完整离线 suite、Gate 记录，真实服务尚未验收的限制。

审阅后由用户决定是否授权 push / 新 follow-up PR。建议基于 PR #87 分支审阅增量；
若 #87 先合并，再按届时 main 状态检查基线。不要修改或自动合并 #87。
实际 API smoke test 和 PDF 页图能力均属另行授权任务；本轮不自动开始。
