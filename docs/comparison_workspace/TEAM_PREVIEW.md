# Windows 团队预览 v2：离线与 Live 双模式

这是单机、单用户预览，供五名组员分别安装体验，不是共享在线服务。默认完整体验无需 Key，
不产生模型费用。Synthetic Demo 的论文、数字和判断全部自制，不是科研实验或 Human Gold。
真实 S1-B 仅完成有限 Extraction 技术观察；科学人工确认与 S1-B Analysis 均未完成，不能称 recovered。
五位组员都可完成离线体验；有权发送论文且愿意承担本人费用的成员也可自行选择 DeepSeek / OpenAI Live。
不要求每人付费，不共享组长 Key，也不建立共享在线工作台。

本页对应 v2 候选；安装前请确认组长已宣布下方 v2 分支与候选 SHA 发布，本地验收不代表远端发布。已发布的
`preview/comparison-workspace-team-20261010`（3b3b984）是旧预览，不包含本页的新候选展示与运行前检查。
组长确认发布 v2 后，再使用下面的新分支命令；不要覆盖旧安装目录或自己的项目。

## A. 离线模式：获取、安装与启动

需要 Git、Python 3.10+（推荐 3.13）、Node.js 22.13+（含 npm）。安装后重新打开 PowerShell，
用 `git --version`、`python --version`、`node --version`、`npm.cmd --version` 检查。

以下获取命令仅在组长确认发布后使用；本地验收不代表远端分支已经存在：

```powershell
git clone --branch preview/comparison-workspace-team-v2-20261010 --single-branch https://github.com/ZicanLiu/ai-literature-intelligence.git comparison-workspace-team-v2
cd comparison-workspace-team-v2
.\start-team-preview.cmd --data-dir "$env:LOCALAPPDATA\SRTP\TeamPreviewV2"
```

后续启动仍运行最后一行命令。也可双击 `start-team-preview.cmd`（使用下文的默认数据目录）。第一次创建独立 `.venv-workspace`，安装 Python 依赖，
执行锁文件对应的 `npm ci` 和前端构建，需要网络；安装后再次运行直接启动。
浏览器打开 http://127.0.0.1:8765 。终端保持开启，按 Ctrl+C 停止。脚本始终强制硬离线，
不加载 `.env`，也不允许“测试连接”。无需激活虚拟环境或调整 PowerShell 执行策略。

可选：`.\start-team-preview.cmd --port 8766 --data-dir "$env:LOCALAPPDATA\SRTP\TeamPreviewV2"`。
只有一个后台可以使用同一数据目录。端口占用时先停止旧服务或使用不同端口。

更新时确认没有自己的源码改动，再执行：

```powershell
git pull --ff-only
.\start-team-preview.cmd --install --rebuild --data-dir "$env:LOCALAPPDATA\SRTP\TeamPreviewV2"
```

普通再次启动无需 `--install`；离线时不要运行它。Python 依赖使用仓库版本范围，npm 使用
package-lock.json；以后重新安装的 Python 补丁版本可能不同。不要复制其他成员的虚拟环境。
若依赖安装失败，保留报错，确认网络与版本后用同一数据目录加 `--install --rebuild` 重试；不会删除项目。
每次启动应沿用同一个 `--data-dir`。如果换成双击启动却看不到项目，先核对是否打开了下文的默认目录。

### 五分钟无 Key 演示

1. 首页点“体验合成演示”：三篇自制 PDF，各有两个候选、一个活动目标。
2. 展开“结果候选”列表，点只读预览，核对摘要、实验身份、来源与关联原文；关闭预览不会改目标。
   “设为活动目标”才保存选择。观察 STALE，再选回主实验并运行合成分析。
3. 点 B 的评估划分，核对引文、提取页文本与 PDF 第 2 页；“原文已定位”只证明文字存在。
4. 分别固定 A、B 的划分证据，点“并排查看”；窄屏会纵向排列。
5. 切换“相同协议”看阻断，切换“资源效率”看未决；缺失不是论文未报告的证明。
6. 修订一个观察并填写理由，查看原记录与 STALE；回概览重开，再导出 Markdown / JSON / CSV。

长于 600 字符的引用默认只展示 360 字符预览。点“展开完整原文”再核查完整语境，点“收起”
恢复预览；短引用直接显示。折叠只改变显示，不改变 canonical quote、位置、hash 或导出。
演示里的短句通常无需折叠；可在手工流程中用自制 PDF 第 1 页完整提取文本体验长引用。

### 上传与手工复核

首页新建具体问题，上传 2–10 篇有权使用的文本 PDF（每篇最多 25 MiB / 100 页）。
首次练习可选仓库 `src/comparison_workspace/demo/fixtures/paper_A.pdf` 与 `paper_B.pdf`，
仍会标为合成材料。真实私人 PDF 只留在各自设备，不能作为反馈附件公开。

逐篇“手工添加”结果并选择活动目标；“阅读论文”查看 PDF 和逐页提取文本；“定位证据”填写
从当前页提取文本原样复制的引用和 PDF 页码。随后添加比较维度、关联该论文证据，记录判断，
保存手工对照并导出。无 Key 模式不会替任意论文生成假 AI 结果。

来源定位、科学支持与真实人工确认分别核查。表头、单位、脚注、数据集、方向、均值/中位数、
质量筛选和 caveat 都可能影响解释。精确定位或 AI 草稿不是人工金标准。无法确认的事项留作未决。
用户修订记录的 local-user 表示本机操作，并非已认证科研身份。

候选即使标题相同，也会按已有实验身份展示不同菜单文本与摘要，原始标题不被改写。
“AI 提取草稿”“手工记录”“用户修订”分别标识；用户修订与原文已定位都不代表独立人工确认。
提取后“结果候选”会立即显示已有记录；比较观察和四类判断仍需另行整理，不会凭空生成。
先确认每篇选的是所需实验，不能把性能实验、架构配置和数据条件直接当成同一类结论。

## B. Live 模式：使用本人 API（可选）

团队预览脚本始终禁止外发论文。确有本人授权的 Live 任务时，先 Ctrl+C 停止离线后台，
在仓库根目录使用普通入口（只允许配置 Live，启动本身不发送模型请求）：

```powershell
$env:DISABLE_LIVE_API = 'false'
.\.venv-workspace\Scripts\python.exe -m app.comparison_workspace_main --data-dir "$env:LOCALAPPDATA\SRTP\TeamPreviewV2" --port 8765
```

普通入口只解除硬禁用，Live 仍默认关闭，启动不会生成内容或发送论文；无需 --enable-api，
该兼容参数也不能绕过页面授权。先完成 A 的依赖安装，无需新增 Live 脚本。

1. 打开“AI 设置”，选择 DeepSeek 或 OpenAI，填**自己的 API Key**，不共享组长凭据。
2. DeepSeek 选择应用支持的模型，例如 deepseek-flash，先保留“按操作默认”：提取 none/12000、分析 high/32000。
   显式 none/low/high/max 会用于两种操作；high 可能产生较多 reasoning tokens，输出预算不是费用上限。
3. OpenAI 填本人账户可用且支持 Responses Structured Outputs 的 API 模型 ID，没有内置默认模型。
   当前两阶段输出上限均为 12000；不套用 DeepSeek 思考选项。兼容性查看
   [OpenAI 官方 Structured Outputs 文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)，
   普通 JSON 模式不等于本应用使用的 Schema 合同。
4. 点“保存 AI 配置”。输入框清空是正常行为，“本次会话已配置”表示 Key 仍在后台内存。
5. 本人确认有权发送后，勾选“确认数据发送”，再打开“启用本次会话 Live”。保存 Key 不等于授权。
   切换服务会关闭 Live，需核对对应 Key、模型、确认和开关。“测试连接”是可选的显式模型列表请求，
   不是必做项，也不证明余额或生成兼容；不要重复点击排查生成质量。
6. 新建真实项目，填写问题和 scope，上传有权使用的 PDF。推荐任务见 [AI 体验指南](AI_TRIAL_GUIDE.md)。
   项目中选择 DeepSeek/OpenAI API 模式，检查工具栏服务，**点击一次**“提取候选结果”，等待结束。
7. 在运行记录查看 Run ID、provider/本地状态、请求/返回模型、参数及 tokens。到“结果候选”阅读摘要、
   实验身份、完整 Evidence 和 PDF；逐篇选择具体实验，不仅看标题。定位不保证科学支持。
8. 若目标或必要来源有错，记录反馈并停止。可审阅后，由本人决定是否承担一次 Analysis 费用。
   “运行分析”先展示比较问题、活动目标、实验身份、来源与未决条件；返回/查看详情不生成。
   只有“确认对象并运行一次分析”才提交 Analysis。提取不会自动进入分析，确认也不是科学正确性认证。
9. 逐条审查 Observation / Finding，必要时以有理由的 Correction 保留修订来源；导出先留本机，
   只交脱敏反馈，不原样公开项目 JSON、全文报告或含私人引文的截图。

建议首次每人只选一个提供方，先一次 Extraction，再决定至多一次可选 Analysis，不要求五人都付费。
incomplete、schema/handle/来源错误、零候选、关键科学目标错误或必要证据不可审阅时停止，不连续重试。
超时或结果不明也可能已计费；SDK 不自动重试不表示失败免费。两家模型只看到提取文本，没有看到 PDF 页图。
普通入口里选“合成演示”仍使用内置合成 provider，不调用付费模型。
手工与合成演示不需要付费检查；结束 Live 后停止后台，用 A 的命令返回硬离线。

详见 [产品指南](PRODUCT_GUIDE.md)。组长 Key 不随版本分发，不能共享订阅凭据。
基础团队体验不需要 Live。不要把 Key 放进 `.env`、截图、Git、反馈或命令历史。
目前真实 DeepSeek Analysis 曾 completed 后本地解析失败，历史具体原因 UNKNOWN；本地诊断有所改进，
未通过新的真实调用证明成功率。失败时查看“运行与修订记录”的 Run ID、用量和安全原因，
不要连续付费重试。费用以服务方账单为准，输入长短或 LOCATED 数量都不证明科学正确性。

## C. 会话、共同数据目录与反馈

| 操作 | 项目与 Run | Key 与 Live |
| --- | --- | --- |
| 浏览器刷新、关闭网页重开，后台未停 | 保留 | 同一后台的配置仍在；项目页面回到手工/演示模式，需自行选择 API 模式 |
| Ctrl+C 后重启普通入口 | 保留 | 会话 Key、模型/思考设置、发送确认和 Live 不从数据库恢复，需重新配置并授权 |
| 普通入口停止后，用离线脚本及同一 --data-dir 启动 | 保留，可继续审阅/手工/导出 | 硬禁用两家生成与连接测试 |
| 服务停止时仍有 QUEUED/RUNNING | 原输入与历史保留 | 重启记 INTERRUPTED，不恢复旧授权、不自动重试 |

高级例外：普通入口有既有的环境 Key/模型回退；若终端预先配置了环境变量，重启后可能显示
“环境变量已配置”，但发送确认与 Live 仍关闭。清除会话 Key 也可能回退环境 Key，界面会显示来源。
如果不清楚环境 Key 的来源，先停止并确认属于本人，不能误用他人的配置。
推荐组员只用 UI 会话 Key，不要求环境配置；硬离线脚本去除这些环境配置再启动。
网页关闭、输入框空白不等于 Key/Live 已撤销。关闭 Live 阻止未发送的旧授权请求，已发出请求可能仍在进行，
不能保证召回；结束试用先等请求结案并记录安全 Run 信息。

默认 Windows 数据目录为 `%LOCALAPPDATA%\SRTP\ComparisonWorkspace`，包含 `workspace.sqlite3`
和原始 PDF；显式 `--data-dir` 优先，也支持 `COMPARISON_WORKSPACE_DATA_DIR`。刷新/重启可恢复，
重建前端不清除数据；备份前先停止服务并备份整个目录。导出不是完整数据库备份。
只监听本机 127.0.0.1；没有多人权限、云同步、OCR、自动清理或任意旧版数据迁移承诺。

反馈发送给组长，或经本人检查后提交仓库 Issue；不要上传数据库、原 PDF、Key、真实模型回应。
复制 [组员反馈模板](TEAM_FEEDBACK_TEMPLATE.md) 填写即可，不需要懂代码。

常见启动问题：提示找不到 Python/Node 时安装环境并重开终端；提示端口占用时停止旧后台或加
`--port 8766`，随后打开对应 URL；页面仍是旧样式时停止后台，用 `--rebuild` 启动后 Ctrl+F5。
默认手工模式中没有自动提取候选属于预期行为。需要真实 AI 时不能继续用硬离线脚本启用 Live。

依赖及许可证见 [第三方说明](THIRD_PARTY_NOTICES.md)，详细边界见 [局限](LIMITATIONS.md)。
