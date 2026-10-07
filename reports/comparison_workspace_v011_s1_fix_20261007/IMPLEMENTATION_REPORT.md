# S1 最小产品修复

日期：2026-10-07（Asia/Shanghai）。基线 `d818eb1`；独立任务分支和 D 盘 linked worktree。
任务允许本地中文 commit；没有 push、PR、merge、tag 或 release。真实 API 调用：**0**。

## 最终行为

- DeepSeek 未指定 `reasoning_effort` 时：extraction **none**，analysis **high**。
  明确选择 none / low / high / max 优先用于两种操作；清空选择恢复按操作默认。
  AI 设置展示默认语义，Run 保存实际发送 effort。OpenAI 的 effort 行为不变。
- `Run.provider_status` 和 `Run.incomplete_details.reason` 进入原有 SQLite JSON、API 与三种导出。
  请求/返回模型、request_id、数值 usage 和 elapsed 沿用原字段。
  SDK 请求未取得响应时 provider status 保持 null / 未知；不把本地 FAILED 伪装成 provider failed。
- OpenAI 的原始响应边界在 SDK schema parse 前提取安全元数据；DeepSeek 在本地 JSON parse 前提取。
  Provider incomplete 显示未完成原因；completed 后 schema 失败仍保留 completed。
- Evidence 身份失败记录 `validation_diagnostic.field_path`、`rule`、expected paper/source 配对及
  returned 身份。路径包含 observation / finding / result 和 evidence 的数组下标。
  Source mismatch 同样保留正确的 source 配对规则；原 guard 和 exact locator 不放宽。
- UI 失败提示区分 provider 未完成和本地校验失败。运行历史展示 provider 状态、未完成原因、
  字段路径、规则、预期与返回身份。Markdown 摘要展示元数据和诊断，JSON / CSV 保留完整 Run。

## 安全与状态边界

Provider status 使用有限枚举；incomplete reason 使用既有有界安全 identifier 过滤。
Usage 只保留原有数值白名单；不保存任意 error body、headers、raw exception、raw reasoning 或 output_text。
Schema 诊断只复制已知字段名及受限数组下标，不复制 Pydantic input / context / message / 任意 extra key。
返回的 paper/source 必须与冻结 Run snapshot 中某个身份精确相等才保留，否则为 null / 未知。

本次没有新增失败原始 proposal 存储。校验失败仍为 FAILED / output=null；有效科学投影只在全部验证
通过后的现有事务中附加。回归比较整个 Project，包含 revision、活动目标、旧分析、所有原记录和 corrections。
旧 Run 向后兼容新增 null 字段，不回填历史 provider status。

## 修改范围

业务代码仅涉及 comparison workspace 的 domain、provider、session settings、service、export 和现有前端。
永久回归覆盖默认/override、响应与响应前失败、安全 schema/identity 诊断、跨论文及源身份拒绝、
科学状态不变、凭据泄漏、真实 SDK 的内存 transport 与 UI 展示。
新增 mock 场景只在测试服务器中，生产 API 没有测试控制端点。

**未改变**：analysis / extraction cap（均 12000）、prompt、provider output schema、算法、权重、
历史 evidence、human judgement、benchmark、PDF、自动重试策略（仍无自动重试）。
没有增加 manifest、hash gate、兼容框架或新的科研结论。

原 Call 3 的精确对象和生成原因仍未知，见 [FORENSIC_REPORT](FORENSIC_REPORT.md)。
验收结果见 [TEST_REPORT](TEST_REPORT.md)；下一次 Live 的判断见 [NEXT_LIVE_HANDOFF](NEXT_LIVE_HANDOFF.md)。
