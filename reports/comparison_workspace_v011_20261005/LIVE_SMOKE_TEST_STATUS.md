# Live smoke test 状态

日期：2026-10-05。

| Provider | 状态 | 真实 API 请求 | 验证材料 |
| --- | --- | --- | --- |
| OpenAI | MOCK_ONLY | 0 | 本地自制合成 PDF + mocked 官方 SDK |
| DeepSeek | MOCK_ONLY | 0 | 本地自制合成 PDF + mocked 官方 SDK |

没有使用用户真实凭据、私人论文或真实收费请求。文档网络读取不是 provider API 调用。
两家 adapter 的认证模型检查、PDF 文本提取候选、活动结果分析、证据检查、独立修订与导出已 mock 验证。
尚未验证真实账户认证、余额、模型访问、JSON Schema 服务兼容、长论文质量、延迟或成本。

真实 smoke test 必须另获用户明确授权，首先仅用公共 / 合成材料，预先列明最少请求数量、
provider / model / reasoning 设置；不输出密钥。不得由当前 MOCK_ONLY 状态推导 LIVE_PASS。
