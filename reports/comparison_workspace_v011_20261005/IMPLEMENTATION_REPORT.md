# v0.1.1 BYO AI 实施报告

日期：2026-10-05（Asia/Shanghai）。范围：PR #87 v0.1 的独立后续。

## 基线与工作区

GitHub 实时核验 PR #87 为 OPEN，head 为 fc7de566420829e3b53ac511b0ae9e82a566bba3；
远程 main 为 5876190f9c2f959d37a2755274298a7138f9af51。
新建 Codex managed worktree，名称 comparison-workspace-v011-byo-ai，分支
codex/comparison-workspace-v011-byo-ai，精确从该 PR head 创建。
本轮未修改 PR #87 分支，原工作区的既有未跟踪 reentry 报告保持原状。
CURRENT_STATUS 仍是 2026-09-22 快照；本次 PR / Git 事实以实时查询为准。

## 交付行为

- AI 设置支持 OpenAI / DeepSeek 两套独立进程内 session Key，分别回退到对应环境变量。
- 状态仅返回凭据来源与可用性；无浏览器存储、数据库或导出凭据路径。
- 明确 provider / model；DeepSeek 两个当前 ID，以及服务默认 / none / low / high / max。
- Live 默认关闭，启用必须确认所选服务的数据发送；切换服务、清除当前 Key 关闭 Live。
- DISABLE_LIVE_API=true / 1 禁止两家生成与连接测试；缺省变量不是硬离线。
- 测试连接只显式 models.list，界面解释它不证明余额、结构化生成或质量。
- OpenAI 保留 Responses.parse / store=false；DeepSeek 用 Responses.create、JSON Schema 与本地校验。
- 每次任务捕获配置，Run 新增请求模型、服务报告模型、reasoning 和 EXTRACTED_TEXT。
  source / active result 身份继续保存在 revision 绑定的原输入快照中。
- 真实文本 PDF 可沿原上传、提取、目标选择、比较、证据、修订、导出流程走所选真实 adapter。
  本轮只用合成源与 mocked SDK 验证，没有实际付费 API 请求。

## 保留边界

没有修改 source / evidence 校验、用户修订 provenance、stale、防重复身份或 demo 合成警示。
没有 OCR、PDF 页图分析、其它服务商、provider 科研比较、云部署、多 Agent 或历史 evidence 改写。
Project schema 保持 v0.1；新 Run 字段为可选，旧记录仍可读。
--enable-api 仅保留参数兼容，不能绕过当前会话 Live 确认。

## 验证

实现提交：065b43bd284562db22eb7f8b602f33c46916463f。
定向 65 tests、前端构建和 9 条浏览器流程通过。完整 suite 在 clean 实现提交上运行一次：
1146 tests / 15 skipped，260.473s；Basic / Full Gate PASS，tests 明确 SKIPPED。
Full 有 3 条既有历史警告。完成后仅补记报告，未再修改源码。详见 TEST_REPORT。
安全自检见 SECURITY_REVIEW；实际服务兼容限制见 PROVIDER_COMPATIBILITY / LIVE_SMOKE_TEST_STATUS。
本报告是实施者自述，不冒充独立终审或真实服务验收。
