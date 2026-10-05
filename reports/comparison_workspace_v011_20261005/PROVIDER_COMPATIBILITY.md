# Provider 兼容性

官方文档核对日期：2026-10-05。非真实账户调用验证。

| Provider | Model | Text | Image | Structured Output | Reasoning Setting | Current Workspace Input Mode |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI | 用户明确选择的模型 ID | 需要支持 | 依模型，未自动断言 | 需支持 Responses structured output；parse + 本地 Pydantic | 本轮不发送 DeepSeek 设置 | EXTRACTED_TEXT |
| DeepSeek | deepseek-flash（V4.1 Flash） | 是 | 是 | Responses JSON Schema + 本地 Pydantic | 服务默认 / none / low / high / max | EXTRACTED_TEXT |
| DeepSeek | deepseek-v4-pro | 是 | 否 | Responses JSON Schema + 本地 Pydantic | 服务默认 / none / low / high / max | EXTRACTED_TEXT |

## 请求合同

OpenAI 固定 https://api.openai.com/v1，官方 SDK responses.parse，store=false。
DeepSeek 固定 https://api.deepseek.com，官方 OpenAI SDK responses.create；显式 text.format
带 type=json_schema、name 和 Pydantic JSON Schema，之后 model_validate_json。
仅 DeepSeek 在选择 effort 时发送 reasoning={effort: ...}，默认不发送该字段。
两家均 max_retries=0、timeout=120s、max_output_tokens=12000；没有自动计费重试。
DeepSeek 无状态 Responses 不支持 store；本实现不发送 store 或 previous_response_id。

Flash 的图像能力只是能力元数据。当前只发送提取文本及声明结构化输入，没有 input_image /
input_file、PDF rasterization、OCR 或图表视觉解释。原本 PDF.js 仅供用户检查本地源页。
models.list 通过不证明所选模型实际 Responses 调用、schema 支持或余额可用。

## 官方依据

- [DeepSeek 模型表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
- [DeepSeek Responses guide](https://api-docs.deepseek.com/guides/responses_api/)
- [DeepSeek Responses schema / reasoning](https://api-docs.deepseek.com/api/create-response/)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [OpenAI Responses storage](https://developers.openai.com/api/docs/guides/migrate-to-responses)

模型 ID / 图像能力依据官方模型表；不采用历史 Flash alias 作为默认模型。
API schema 页面搜索获取到完整正文；直接打开部分 DeepSeek 页面超时，guide 与模型表直接打开成功。
没有把文档支持等同于实际账户可用性，未实现其它 provider 或任意兼容 URL。
