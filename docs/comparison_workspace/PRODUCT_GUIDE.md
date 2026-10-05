# 科研比较工作台 v0.1 使用指南

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

## 可选 OpenAI API

本次交付没有执行 live 请求。只在用户允许发送本项目文本到外部 API 时配置。
进程环境必须设置 OPENAI_API_KEY、COMPARISON_OPENAI_MODEL，并明确 DISABLE_LIVE_API=false；
启动再加 --enable-api。缺少任一条件不能发出请求。默认硬离线；不读取 .env 或 Codex 登录态，
不会将 ChatGPT/Codex 订阅当作 API 凭据。模型由用户明确选择，需支持 Responses structured output。

UI 选择 OpenAI API 后可提取结果候选或运行比较。发送内容包括本项目问题、页面提取文本、
活动结果、观察与修订。返回解释始终是草稿。
官方 SDK Responses.parse 使用 Pydantic 结构、store=false、max_retries=0、120 秒超时；
记录返回的实际 model、request ID 和 token usage。费用未知。失败不产生科学判断；
每次手工重试创建新的 Run，重启不自动重试。
实现依据 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
和 [Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses)。

更多见 [局限](LIMITATIONS.md)、[来源与修订](DATA_PROVENANCE.md)、[组会脚本](DEMO_SCRIPT.md)。
