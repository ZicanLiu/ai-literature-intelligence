# 科研比较工作台 v0.1.1 使用指南

这是独立的本地产品入口。历史文献获取、排序、benchmark 和 Pipeline 保持原接口。

## 安装与一条命令启动

需要 Python 3.10+、Node.js 22.13+ 和 npm。本次验收使用 Python 3.13.9 / Node.js 22.21.0。
在本功能分支根目录运行（首次安装需要网络）：

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements-workspace.txt
python -m app.comparison_workspace_main
```

打开本地 http://127.0.0.1:8765 。首次启动自动执行 npm ci 和前端构建，之后已有构建直接启动。
准备好依赖与构建后，合成演示不依赖网络或 Key；组会前应先完成首次安装。
单进程后台同时提供 API 和静态前端，默认只监听 127.0.0.1。关闭该进程即可停止服务。

参数：--port、--data-dir、--rebuild、--enable-api。
也可用 COMPARISON_WORKSPACE_DATA_DIR 覆盖数据目录。默认数据保存在系统用户数据目录的
SRTP/ComparisonWorkspace（Windows）或 srtp/comparison-workspace（Linux），位于 Git 之外。
项目与 PDF 留在该目录；前端重建不删除项目。同一数据目录只启动一个后台服务。

开发时可另开 Vite（web/comparison-workspace 下 npm run dev），代理 /api 到 8765。
组会演示直接使用上面的一条启动命令。

## 无 Key 使用

首页“体验合成演示”创建三篇合成文献。每篇两种结果候选，默认激活主实验。
下拉切换结果，每篇始终只有一个活动结果；取消选择后不能运行比较。
三个问题展示：报告数字排序、相同协议下的划分阻断、资源证据缺口。
修改目标、问题或观察后，旧分析显示 STALE；重新运行不会抹去用户修订。

真实论文可新建项目，依次上传 2–10 篇 PDF。每篇限制 25 MiB / 100 页，超限明确拒绝，不截断。
上传后阅读源 PDF，手工创建结果，并在证据检查器中定位原文：
填写 PDF 页码与从提取文本复制的精确引文。页码从 1 开始显示。
再添加数据集、指标、划分、预算等问题相关观察，并关联对应论文的证据。

离线“手工模式”保存手工对照，不自动调用模型、不伪造提取或科学判断。
可通过“记录手工判断”分别记录已支持前提、阻断、未决、允许差异。
已支持前提、阻断和允许差异须引用有效定位；差异是否阻断由问题和解释决定。
点击观察 / 判断后可修订；论文身份与活动结果也有修订入口。修订必须说明理由，原记录保留。

## 原文检查与导出

点击矩阵单元格或审查卡，查看原文片段、PDF 页码、原字节 SHA256 和解析工具。
“提取页面文本”突出精确片段；“查看 PDF 第 N 页”使用本地打包的 PDF.js 渲染源页。
源 PDF 链接可单独阅读。固定两条证据后点击“并排查看”。
“原文已定位”只证明文字出现，不证明解释正确。

页面自动保存。回到项目概览 / 刷新 / 重启后台都可重开同一项目。
Markdown、JSON、CSV 导出保存问题、身份、活动目标、观察、四类判断、原记录、
修订、运行及 STALE 状态。CSV 使用记录类型区分各对象，并防护公式开头的单元格。
导出会遮盖可识别的凭据和本机路径，记录遮盖数；被遮盖片段应回本地原文复核。

## 导入

“导入结构化分析”先下载当前身份模板，填写 analysis.observations / analysis.findings，
再载入 JSON 或粘贴文本。schema_version、project_id、input_revision、question、scope、
每篇 source_snapshot_id / sha256 及 active_target_result_ids 必须精确匹配。
错误引用不会污染项目；无效引文标为待复核。导入始终显示“导入草稿”。
候选结构见 [domain/models.py](../../src/comparison_workspace/domain/models.py)。
模板里的 evidence 用 paper_id、source_snapshot_id、page_index（0 起算）、quote 定位。

## 使用自己的 AI API

v0.1.1 支持 OpenAI 和 DeepSeek。启动后打开右上角“AI 设置”，无需 --enable-api。
该旧启动参数保留兼容，但不自动启用 Live；进程启动时 Live 始终关闭。
不读取 .env、Codex 登录态或 ChatGPT 订阅凭据；API 费用与订阅分开。

1. 选择 AI 服务，粘贴自己的 API Key，明确选择模型；点击“保存 AI 配置”。
2. 可显式点击“测试连接”：只请求认证模型列表，不发送论文、不生成内容。
   通过只证明认证和模型列表可见，不证明余额、Responses structured output 或生成质量。
3. 阅读所选服务的数据发送说明，勾选确认，再显式启用本次会话 Live。
4. 新建项目，上传 2–3 篇有权发送的文本 PDF；填写具体比较问题。
5. 选择该服务 API 模式，点击“提取候选结果”，为每篇选定一个活动结果，再“运行分析”。
6. 查看原文定位、独立修订，并导出。返回内容始终是需复核的 AI 草稿。

Key 只保存在本地后台进程内存中：两家服务分别保存，session Key 优先于环境 Key。
密码输入在保存 / 测试 / 切换 / 关闭设置后清空；GET 只返回“未配置 / 环境变量已配置 /
本次会话已配置”，不返回密钥。Key 不进入数据库、项目、浏览器存储、导出或日志。
关闭后台进程后 session Key 消失；重新启动须重新启用 Live 和确认每个服务的数据发送。
“清除本次会话 Key”仅清除该服务；若其环境 Key 仍存在，将回退到环境变量。
清除当前服务会关闭 Live；切换服务也会关闭 Live，再启用需确认对应服务。
取消“确认数据发送”会立即向后端提交撤回并关闭 Live；保存后的勾选和开关以后台状态为准。
提交失败会显示错误并重新读取状态，不宣称撤回成功；若无法回读，需重新打开设置核对。
API 中省略 acknowledge 不改变已有确认，显式 false 即撤回，即使同传 live_enabled=true 也不会启用。
撤回确认、关闭 Live、清除 / 替换 Key 或切走服务会永久失效尚未发送的旧任务授权。
重新开启或重新输入同一 Key 只允许新建任务，不恢复旧队列。重启不恢复会话授权、不自动重试。
生成与连接测试在客户端准备后、SDK 请求入口做最后的授权与硬离线判定。
进入发送阶段后的请求可能仍在进行，撤回不能保证召回；关闭 Live 不是已经外发内容的删除操作。
连接测试不要求论文发送确认，但旧连接测试同样受凭据清除 / 替换、服务切换与硬离线约束。

可选进程环境回退：OpenAI 用 OPENAI_API_KEY / COMPARISON_OPENAI_MODEL；DeepSeek 用
DEEPSEEK_API_KEY / COMPARISON_DEEPSEEK_MODEL。请在进程环境配置，不写入或提交 .env。
DISABLE_LIVE_API=true（或 1）是部署硬离线开关，禁止两家服务的生成与连接测试；
session Key 无法绕过。缺省该变量只表示没有部署硬禁用，Live 仍默认关闭。

### OpenAI

明确填写自己账户可用、支持 Responses structured output 的模型 ID；没有“最佳模型”默认值。
服务端固定官方 https://api.openai.com/v1；使用官方 SDK Responses.parse 和本地 Pydantic 校验。
生成请求设置 store=false，关闭 Responses 应用存储；这不是服务零留存承诺。
查看 [OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)。

### DeepSeek

服务端固定 https://api.deepseek.com，浏览器不能提交任意 endpoint。当前支持：

| 模型 | 文本 | 图像理解 | 本工作台论文输入 |
| --- | --- | --- | --- |
| deepseek-flash（DeepSeek V4.1 Flash） | 支持 | 支持 | PDF 提取文本 |
| deepseek-v4-pro | 支持 | 不支持 | PDF 提取文本 |

能力依据 [DeepSeek 官方模型表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，
核对日期 2026-10-05。模型能力随服务商变化，本版本只列以上两个 ID。
两者使用 [Responses API](https://api-docs.deepseek.com/guides/responses_api/)，显式 JSON Schema，
本地 Pydantic 校验为应用结构的最终边界。DeepSeek 按操作默认：提取 none / 12000 output tokens，
分析 high / 32000 output tokens。可显式选择 none / low / high / max 覆盖两种操作的思考强度；
选项映射 reasoning.effort，保存在非敏感运行来源中。OpenAI 不套用此参数。

DeepSeek Responses 为无状态接口，不支持 store 设置；本工作台不发送该参数。
无状态接口不等于整个服务零留存，请查看服务商现行数据政策。
DeepSeek 不接受任意 PDF 文件输入；deepseek-flash 的图像理解能力不表示当前分析已经看到图表。
本轮两家服务都只收到提取文本和相关结构化记录，未实现 PDF 页图、多模态或 OCR。
本地 PDF.js 仍用于用户阅读源页，未将这些渲染图传给 API。

### 运行来源与失败

每次 live Run 保存 provider、请求模型、服务报告模型、实际 reasoning 选项、max_output_tokens、EXTRACTED_TEXT、
request ID（服务提供时）、耗时、token usage、project revision 与含 source / active result ID 的快照。
不保存 Key。API 输入上限 600,000 字符，超过明确拒绝、不截断；SDK 120 秒、max_retries=0。
失败不产生科学判断；每次显式重试创建新 Run，重启不自动重试。
费用保持 unknown，没有运行正式 provider 对比实验。本轮两家 API 均只用 mock 验证，未执行真实请求。
请求模型固定入队配置；服务报告模型只有实际响应明确报告时才保存。未收到有效响应的认证、
超时或网络失败显示“未取得服务端返回模型”，不以请求模型代替。响应已报告模型但本地解析 / 校验
失败仍保留可安全取得的报告模型、request ID 与 usage。三种导出保留两个独立字段。
旧记录的 model 原值仅兼容保留，来源不明时不推断为请求或服务返回。

更多见 [局限](LIMITATIONS.md)、[来源与修订](DATA_PROVENANCE.md)、[组会脚本](DEMO_SCRIPT.md)。
