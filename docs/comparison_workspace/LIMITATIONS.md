# v0.1 局限与解释边界

- 不提供普遍的科学可比性 YES 认证、不显示未校准置信度百分比。
  已支持前提只是一条具体问题下的提议 / 用户记录；也须复核。
- SYNTHETIC DEMO / NOT RESEARCH EVIDENCE：三篇演示论文、数值与叙述均自制，
  不是 gold 或研究 benchmark。产品没有建立研究新颖性或真实用户有效性。
- 三个固定演示问题只适用于该 fixture。改变问题 / 活动结果 / 提取信息之后不能套用
  原数值结论；系统保留 STALE 或要求复核，不为任意 PDF 提供假的离线 AI 分析。
- 自动 pipeline 要求可完整提取文本。扫描件不提供 OCR；复杂表格、公式、编码异常、
  图像页与页面顺序可能无法可靠表达。提取失败不是“论文没报告”。
- 加密 / 损坏、超过 25 MiB / 100 页的源明确拒绝。没有静默截断。
- 提供 PDF 页跳转和提取文本 exact quote；不承诺任意 PDF 图像上的准确 bbox 高亮。
- AI / 导入解释需要源审阅；structured output 和有效 quote 不能校准科学解释。
  已有受限 DeepSeek Extraction 技术观察，尚无 S1-B Analysis / Human Gold；不是模型稳定性或优越性证明。
  账户模型可用性、未来长文科学质量与费用均不能由该次观察推定。
- API 最多发送 600,000 个字符，超限明确拒绝、不截断；SDK 单次 120 秒、max_retries=0。
  模型由用户配置。上下文窗口 / 实际服务约束可能更小，失败单独记录。
- OpenAI 使用 store=false 关闭 Responses 应用存储；DeepSeek Responses 为无状态接口，不发送 store。
  两者都不代表整个外部服务零留存；使用者应查看所选服务的数据政策并只发送已获授权文本。
- 本地单用户单后台，无认证、多用户权限或并发协作。操作者 local-user 是本机记录，
  不是研究身份认证。相同数据目录不要同时运行多个服务。
- v0.1 使用聚合 SQLite 结构，无已有旧版本的数据迁移承诺。项目无自动删除 /
  源文件清理流程；管理私人数据应由用户在停止服务后自行处理。
- 导出遮盖常见凭据 / 绝对路径模式并防护 CSV 公式，但不能识别所有个人敏感内容。
  分享前应审阅自身上传材料。报告的隐藏字符串不修改本地原件与源哈希。
- 没有做云端部署、OCR、KG / GraphRAG、向量库、多 Agent、研究 benchmark 或旧 pilot
  重分析。历史 BM25 / MCA 证据保持原研究语境。

- v0.1.1 只支持 OpenAI / DeepSeek，禁止浏览器任意兼容 endpoint。DeepSeek 列表仅有
  deepseek-flash / deepseek-v4-pro；模型列表检查不验证实际生成、余额或分析质量。
- deepseek-flash 支持图像理解，deepseek-v4-pro 不支持；当前两家论文分析仍仅用 PDF 提取文本。
  没有 PDF 页图 / 图表视觉输入或 OCR；本地 PDF.js 渲染仅供用户原文检查。
- 关闭 Live / 清除 Key 无法撤回已发出的请求；清除 session Key 后环境 Key 可能仍可用，
  但需要再次确认并启用 Live。session 指本地后台进程，不是浏览器 tab 或用户账号隔离。
