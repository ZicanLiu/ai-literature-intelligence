# Team Preview v2 双模式补充验收

日期：2026-10-10。状态：**TEAM_PREVIEW_V2_DUAL_MODE_READY**（本地流程与 mock 授权验收）。
本轮真实模型生成与真实连接测试均为 **0**，不是两家真实服务成功率验证或 GitHub 发布状态。

**基线与修改范围**

分支 `codex/comparison-workspace-team-preview-v2`；开始时 clean，HEAD `88da6a2bd33e6a6d91d47b8cf7ab567bdd8273f0`。
双模式文档/测试提交 `e636db7d4d8dc65e29f1c2ca0460b78cb95eb511`。最终冻结 SHA 是包含本补充报告的后续文档提交，
由最终交付给出；原 88da6a2 不再是本轮建议发布的候选终点，祖先链完整保留。

现有普通入口足够简单，因此**没有生产代码、Live 辅助脚本或 Provider 变更**。
保留原离线脚本、模型参数、Schema、span/handle、strict source/active-result/quote validator、重试、Correction/STALE 与导出合同。
本轮只修改 TEAM_PREVIEW、PRODUCT_GUIDE、TEAM_FEEDBACK_TEMPLATE，新增 AI_TRIAL_GUIDE 与两个永久启动/会话单测，
补充两家提供方的刷新/合成模式浏览器用例。本报告是追加记录，未改写上轮验收或科研报告。

**现有能力核查**

| 项目 | 代码事实与验证结论 |
| --- | --- |
| 离线脚本 | start-team-preview.cmd → start_comparison_workspace.py，强制 DISABLE_LIVE_API=true，去除提供方环境 Key/模型配置；生成与连接测试均禁止 |
| 普通入口 | app.comparison_workspace_main 允许配置 Live，但 Live、发送确认默认关闭；--enable-api 兼容参数不能授权 |
| Key 与提供方 | 组员本人 UI 会话 Key，不共享组长 Key；两家配置分开，切换服务关闭 Live |
| 浏览器刷新 | 后台未停时会话 Key/确认/Live 保留；输入框为空不等于 Key 清除。项目页重新选择手工/演示默认模式，需要本人切回 API 模式 |
| 后台重启 | 新进程不从项目数据库恢复会话 Key、模型、思考选项、发送确认或 Live；未完成任务记 INTERRUPTED，不自动重试 |
| 环境变量例外 | 普通入口保留已有环境 Key/模型回退；重启可显示环境配置，但仍需本人确认和 Live。来源不明应停止，清会话 Key 可能回退环境 Key |
| 同一数据目录 | 停止前一后台后可两种模式顺序复用相同 --data-dir；项目、活动目标、Evidence、修订和 Run 保留，不能同时开两个服务用同一目录 |
| 模式区分 | 合成演示使用内置 DemoProvider，即使会话已启用 Live 也不变成付费模型；API 模式提取与分析为独立显式操作 |

**交付给组员的双模式操作**

先按 [团队指南](../../docs/comparison_workspace/TEAM_PREVIEW.md) 安装正确版本。仓库根目录离线启动：

```powershell
.\start-team-preview.cmd --data-dir "$env:LOCALAPPDATA\SRTP\TeamPreviewV2"
```

首次安装下载依赖，之后可无 Key 演示、自制/私人 PDF 手工阅读、Evidence、Correction 与三种导出。
如本人选择 Live，先在离线后台 Ctrl+C 停止，再在同一仓库执行：

```powershell
$env:DISABLE_LIVE_API = 'false'
.\.venv-workspace\Scripts\python.exe -m app.comparison_workspace_main --data-dir "$env:LOCALAPPDATA\SRTP\TeamPreviewV2" --port 8765
```

打开 http://127.0.0.1:8765 ，在 AI 设置选择提供方、本人 Key 和兼容模型，保存后本人确认数据发送并开启 Live。
没有命令行 Key，也不会自动生成。先一次 Extraction，审阅并选择具体实验目标，再自行决定一次可选 Analysis；
确认窗口可返回或看原文，只有显式继续才提交。不要把 completed / LOCATED 当成科学正确。
结束时关闭后台，再用离线命令和相同数据目录继续审查。源目录不是共享在线数据库。

**真实体验任务与反馈**

[AI_TRIAL_GUIDE](../../docs/comparison_workspace/AI_TRIAL_GUIDE.md) 给出 DPR v3 / RAG v4 的官方固定版本入口、NQ 端到端 EM 问题、
scope、参数记录、一次提取与可选分析。模型输入不含预设正确数字或历史审计答案。
科学审查区分 QA EM 与检索 accuracy、DPR Single/Multi/消融、RAG Token/Sequence、训练/推理文档数、解码、split 与表格上下文。
候选混合变体或必要来源不足时先修订/保留 UNKNOWN，不强行进入分析。

[反馈模板](../../docs/comparison_workspace/TEAM_FEEDBACK_TEMPLATE.md) 分离安装/离线、Live 技术元数据、科学比较质量与交互建议。
Live 可填“未进行”，不要求五人付费；逐次记录模型、参数、状态、tokens、候选/Evidence 质量、误选目标、安全错误分类和本人审查问题。
不要求上传 Key、私人 PDF、全文提取、完整模型响应/reasoning 或数据库；导出留本机，反馈只用脱敏摘要。

**隔离验证与安全边界**

进程级专项连续使用一个新的仓外数据目录，四阶段均通过：

1. 实际离线 cmd 脚本启动，父环境只放合成 sentinel 配置且硬禁用原本为 false；启动后 hard_offline=true、无环境凭据，
   UI Live/连接测试禁用，试图通过本地 API 绕过也返回 422，原合成项目不变。
2. 普通 CLI 在仅替换 SDK transport 的审计进程中启动；默认无授权、不构造 SDK 客户端。通过真实浏览器分别配置两家，
   上传自制 PDF、一次 Extraction、活动选择、检查取消、一次 Analysis 与导出。
3. 停止重启普通 CLI、复用同一目录：三个测试项目内容 hash 一致，Key/模型/确认/Live 不恢复，SDK ledger 从 0 开始且无自动请求。
4. 再次运行实际离线脚本，同一目录：项目与原生提议可继续阅读，所有内容 hash 一致，Live 硬禁用。

该专项 mock 生成总数 **4**（OpenAI 两次、DeepSeek 两次），connection **0**，四次 SDK 客户端均 max_retries=0；
不是整套回归中的全部 mock 计数，更不是四次真实 API。普通入口审计进程同时禁止非 loopback socket，浏览器也拒绝外部资源。
离线脚本来自上轮干净安装的隔离检出；启动/Provider/前端相关源码与当前版本一致（Windows 换行规范化后比较），
使用全新的测试数据目录，不冒充本轮重新安装依赖，也没有引入产品测试端点。审计 hooks 只在仓外 mock 包装器中。

永久单测另验证脚本去除环境配置的交接、兼容参数不能启用 Live、两种入口同目录复用、Key 不落盘、原生 Run hash 不变、
重启不恢复授权、生成请求次数和 retries=0。现有撤回/中断/超时与失败原子性回归继续保留。
浏览器新增用例证明两家会话在页面刷新后仍配置，合成模式再运行也不会增加 SDK 计数。

**测试结果**

按 CONTRIBUTING 在 clean `e636db7` 上运行完整 unittest 一次，再执行 Basic / Full，明确 --skip-tests：

| 验证 | 实际结果 |
| --- | --- |
| 新永久双模式单测 | 2/2 PASS；合成 Key/SDK、外部 socket 禁止 |
| 定向 workspace 回归 | 125 tests，OK，0 skip，18.776 秒 |
| 完整离线 unittest | 1206 tests，OK，15 条件性 skip，319.116 秒，无失败 |
| Basic Gate --skip-tests | PASSED，621 files，0 error / 0 warning |
| Full Gate --skip-tests | PASSED，621 files，0 error / 3 既有 warning |
| Chromium 浏览器完整回归 | 31/31 PASS，1.1 分钟；隔离数据、SDK mock |
| 进程级四阶段切换 | PASS；实际离线 cmd、普通 CLI SDK mock、普通重启、切回离线 |
| 用户数据保护 | 原数据库 + 6 PDF 共 7 文件 hash 一致，未写入用户项目 |
| 历史科研保护 | 191 文件 hash 一致 |
| diff / 新增文件与未发布 blob 安全检查 | PASS；未发现新增私有数据或凭据模式 |

Full 的 warning 沿用历史 W1 CSV 结构、19 个 annotation ID 与旧 tracked OpenAlex experiment；没有删历史材料。
S1-A 保存的成功 canonical Extraction/Analysis 回放通过；旧 S1-B 仍 **2 LOCATED / 4 INVALID**，E3/E6 不获救回，
span live 原五条来源及未引用第 6 页的事实不变。相关外部回放根已显式配置，未因未配置而跳过。
生产前端和依赖没有变化，因此不重复安装/构建，复用上轮已验构建并以浏览器实际加载检验。

开发时新单测首次把 Windows TestClient 内部 loopback socketpair 一并禁用，随后仅允许 loopback、仍禁止外部 socket；
新增浏览器断言最初混淆 mode=demo 与 provider=DemoProvider，修正为同时核对两字段。未改变生产代码、来源规则或正式数据。
上述初轮失败日志与后续通过日志均留在仓外本轮目录。

**保护与发布边界**

用户数据库与 6 份原 PDF 只做文件 hash 保护，没有读取用户 Key、修改项目或旧 Run。191 份既有科研材料继续检查。
没有新私有 runtime/PDF/原始响应进入 Git；既有 main 的历史 OpenAlex 元数据数据库沿用上轮披露，未改。
本轮不创建公网服务、不新增账号系统、不 push/merge，不修改 main、PR #87 或旧预览分支。
只读远端核对仍为 main=`5876190f9c2f959d37a2755274298a7138f9af51`、旧预览=`3b3b984d217a0c734c47b9a45540646f2dfdebd8`，
PR #87 OPEN，head=`fc7de566420829e3b53ac511b0ae9e82a566bba3`；建议新 v2 分支本轮检查时不存在。
发布需用户重新批准**新的最终 SHA**，建议仍建立新 `preview/comparison-workspace-team-v2-20261010`；
发送前重新核对分支未占用、远端基线与候选安全，普通非强制推送，推送后独立核对。

本地双模式流程可以准备就绪，但未验证组员的真实 Key/余额/网络、每个 OpenAI 模型的服务兼容、
DeepSeek/OpenAI 真实 schema 成功率或科学可比性。旧 Analysis 原因仍 UNKNOWN，S1-B 未完成 Analysis / recovered，
无新 Human Gold 或稳定性统计证明。本轮不因文档任务启动任何真实付费实验。

用户本轮明确撤销额度重置安排；没有查询剩余额度或使用重置卡。
