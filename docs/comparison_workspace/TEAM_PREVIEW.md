# Windows 团队预览

这是单机、单用户预览，供五名组员分别安装体验，不是共享在线服务。默认完整体验无需 Key，
不产生模型费用。Synthetic Demo 的论文、数字和判断全部自制，不是科研实验或 Human Gold。
真实 S1-B 仅完成有限 Extraction 技术观察；科学人工确认与 S1-B Analysis 均未完成，不能称 recovered。

## 获取与启动

需要 Git、Python 3.10+（推荐 3.13）、Node.js 22.13+（含 npm）。安装后重新打开 PowerShell，
用 `git --version`、`python --version`、`node --version`、`npm.cmd --version` 检查。

以下获取命令仅在组长确认发布后使用；本地验收不代表远端分支已经存在：

```powershell
git clone --branch preview/comparison-workspace-team-20261010 --single-branch https://github.com/ZicanLiu/ai-literature-intelligence.git comparison-workspace-team
cd comparison-workspace-team
.\start-team-preview.cmd
```

也可双击 `start-team-preview.cmd`。第一次创建独立 `.venv-workspace`，安装 Python 依赖，
执行锁文件对应的 `npm ci` 和前端构建，需要网络；安装后再次运行直接启动。
浏览器打开 http://127.0.0.1:8765 。终端保持开启，按 Ctrl+C 停止。脚本始终强制硬离线，
不加载 `.env`，也不允许“测试连接”。无需激活虚拟环境或调整 PowerShell 执行策略。

可选：`.\start-team-preview.cmd --port 8766 --data-dir "$env:LOCALAPPDATA\SRTP\TeamPreview"`。
只有一个后台可以使用同一数据目录。端口占用时先停止旧服务或使用不同端口。

更新时确认没有自己的源码改动，再执行：

```powershell
git pull --ff-only
.\start-team-preview.cmd --install --rebuild
```

普通再次启动无需 `--install`；离线时不要运行它。Python 依赖使用仓库版本范围，npm 使用
package-lock.json；以后重新安装的 Python 补丁版本可能不同。不要复制其他成员的虚拟环境。
若依赖安装失败，保留报错，确认网络与版本后用 `--install --rebuild` 重试；不会删除项目。

## 五分钟无 Key 演示

1. 首页点“体验合成演示”：三篇自制 PDF，各有两个候选、一个活动目标。
2. 阅读矩阵，切换一个候选观察 STALE，再选回主实验并运行合成分析。
3. 点 B 的评估划分，核对引文、提取页文本与 PDF 第 2 页；“原文已定位”只证明文字存在。
4. 分别固定 A、B 的划分证据，点“并排查看”；窄屏会纵向排列。
5. 切换“相同协议”看阻断，切换“资源效率”看未决；缺失不是论文未报告的证明。
6. 修订一个观察并填写理由，查看原记录与 STALE；回概览重开，再导出 Markdown / JSON / CSV。

长于 600 字符的引用默认只展示 360 字符预览。点“展开完整原文”再核查完整语境，点“收起”
恢复预览；短引用直接显示。折叠只改变显示，不改变 canonical quote、位置、hash 或导出。
演示里的短句通常无需折叠；可在手工流程中用自制 PDF 第 1 页完整提取文本体验长引用。

## 上传与手工复核

首页新建具体问题，上传 2–10 篇有权使用的文本 PDF（每篇最多 25 MiB / 100 页）。
首次练习可选仓库 `src/comparison_workspace/demo/fixtures/paper_A.pdf` 与 `paper_B.pdf`，
仍会标为合成材料。真实私人 PDF 只留在各自设备，不能作为反馈附件公开。

逐篇“手工添加”结果并选择活动目标；“阅读论文”查看 PDF 和逐页提取文本；“定位证据”填写
从当前页提取文本原样复制的引用和 PDF 页码。随后添加比较维度、关联该论文证据，记录判断，
保存手工对照并导出。无 Key 模式不会替任意论文生成假 AI 结果。

来源定位、科学支持与真实人工确认分别核查。表头、单位、脚注、数据集、方向、均值/中位数、
质量筛选和 caveat 都可能影响解释。精确定位或 AI 草稿不是人工金标准。无法确认的事项留作未决。
用户修订记录的 local-user 表示本机操作，并非已认证科研身份。

## Key、数据与反馈

团队预览脚本禁止外发论文。确有独立授权的 Live 任务才使用
`.venv-workspace\Scripts\python.exe -m app.comparison_workspace_main` 普通入口，
并确保部署环境未设置 `DISABLE_LIVE_API=true`；在“AI 设置”输入自己的 Key、确认数据发送、
显式启用 Live。详见 [产品指南](PRODUCT_GUIDE.md)。组长 Key 不随版本分发，不能共享订阅凭据。
本轮团队体验不需要这一步。不要把 Key 放进 `.env`、截图、Git、反馈或命令历史。

默认 Windows 数据目录为 `%LOCALAPPDATA%\SRTP\ComparisonWorkspace`，包含 `workspace.sqlite3`
和原始 PDF；显式 `--data-dir` 优先，也支持 `COMPARISON_WORKSPACE_DATA_DIR`。刷新/重启可恢复，
重建前端不清除数据；备份前先停止服务并备份整个目录。导出不是完整数据库备份。
只监听本机 127.0.0.1；没有多人权限、云同步、OCR、自动清理或任意旧版数据迁移承诺。

反馈发送给组长，或经本人检查后提交仓库 Issue；不要上传数据库、原 PDF、Key、真实模型回应。
可用以下模板：

```text
版本：git rev-parse --short HEAD
系统 / Python / Node：
流程：合成演示 / 自制 PDF 手工 / 其他（不附私人原件）
复现步骤：
预期 / 实际：
是否刷新或重启仍出现：
影响：阻断 / 困惑 / 显示问题
可分享的脱敏截图与错误摘要：
科学含义问题：引用、比较对象、统计量或未决条件（不得冒充人工 gold）
```

依赖及许可证见 [第三方说明](THIRD_PARTY_NOTICES.md)，详细边界见 [局限](LIMITATIONS.md)。
