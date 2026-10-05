# Scientific Comparison Workspace v0.1 — Independent Final Review

日期：2026-10-05（Asia/Shanghai）。审查对象是实际实现及运行行为，不是初次实施报告。

## Executive verdict

**READY_WITH_LIMITATIONS**。初始交接版本存在需要在组会前修复的问题，不能仅凭原有 36 项测试通过就直接验收。
本轮修复了 8 项 MAJOR 问题，补充回归并实际操作应用；最终未留下本轮已识别的 BLOCKER / MAJOR。

修复后的产品可以作为一个本地、单用户、可追溯的文献对照工作台演示。它已经有明确的结果身份、
原文定位、追加修订、过期状态、持久化和可复用导出，价值超出一次性问答。
此结论只覆盖产品演示与所测工程边界，不证明自动分析质量、研究新颖性或科学有效性。

审查基准为 `e0d9480d2cf5266ef48519939a2f4417a62e434b`；修复及完整测试基准为
`5279bb4ee51597fc48bb3046a613ad9807b3c7c6`，分支 `codex/comparison-workspace-v01`。
报告文件在测试后写入；没有以旧测试结果替代修复后的结果。

## Verified claims

| 初次交付主张 | 独立核验结果 |
| --- | --- |
| 指定 D 盘工作树、分支、HEAD、3 个提交、57 文件 / +5608 -1、clean | 初始 Git 状态、log、merge-base、diff stat 均一致 |
| 基线 origin/main | 本地 ref 与 merge-base 均为 `5876190f9c2f959d37a2755274298a7138f9af51` |
| 后端 / 前端 / SQLite / 本地 PDF.js | 已阅读实际调用链、配置和测试，并启动服务验证 |
| 三篇合成 PDF、每篇两个候选、一个活动结果 | 已读原始 fixture、检查逐页警示、操作选择与矩阵 |
| 默认无 Key、离线演示 | 独立复跑；浏览器回归阻断远端请求并断言没有外发；API 禁用的 mock 断言通过 |
| 真实上传 / 手工工作流 | 使用自制 PDF 经过普通文件上传路径，手工结果、证据、观察、修订、保存均通过；未使用私人论文 |
| 四类判断、证据检查、PDF 页、并排阅读、修订、重开、三格式导出 | 交互检查及浏览器回归通过；修订和过期判断的问题见下文 |
| 后端 36 tests、浏览器 4 flows、npm audit 0 | 修复前独立复验成立；修复后变为 45 tests、6 flows，audit 仍为 0 |
| 仓库 1117 tests / 15 skipped、Basic / Full PASS | 属于旧交付快照；本轮修复后实测 1126 tests / 15 skipped，两个 Gate PASS |
| 没有改动冻结历史研究 evidence | 完整分支文件范围复核通过；本轮只改产品源码、测试及报告，未改研究数据或合同 |
| OpenAI 适配器 | 仅 mock 验证，不声称真实服务、账户、模型或费用通过 |
| GitHub Linux CI | 工作流静态审查及对应本机步骤通过；没有运行 GitHub CI |

## BLOCKER findings

本轮未复现必须判为 BLOCKER 的数据丢失、跨论文原文下载、任意路径访问、密钥泄露或核心演示中断。
这不是对所有 PDF、客户端或攻击面的完整安全证明。

## MAJOR findings

以下问题均在本轮修复。复现使用本产品合成材料及临时数据库；未动历史研究 evidence。

| ID | 原问题与影响 | 修复及验证 |
| --- | --- | --- |
| M01 | 修订一个模型判断后重跑，`current_analysis_run_id` 切换；原 correction 仍存储，但其目标不再进入有效视图。用户修订从当前判断消失，也不能继续修订同一目标。 | 在项目中保留被修订提议的原记录，以稳定 ID 应用修订；原 Run 不改写。新增重跑、再次修订、原输出不可变回归，浏览器实际验证。 |
| M02 | 手工判断没有过期绑定。换问题 / 范围 / 活动结果后再运行，新 Run 为当前状态，旧手工 blocker 仍混入当前四类审查。 | 相关输入变化使手工及保留的修订判断 stale；旧记录单独展示并导出，当前审查计数排除它们。旧手工记录缺少语境状态时保守视为过期。问题、范围、目标、观察四条路径及 Markdown / CSV 回归通过。 |
| M03 | 修订观察后换活动结果，Demo 仍发送非活动观察，运行 FAILED；此外修订数据集或范围后仍可能套用 Dataset X / B 未定位等固定结论。检查器也可能继续展示上一目标的选择。 | 只向本次 Demo 输出活动目标的修订观察；输入修订后暂停全部固定叙述，给出未决复核提示；输入变动或运行结束清除旧选择。目标切换、往返切换、修订后的叙述及浏览器回归通过。 |
| M04 | 自动观察即使 quote 不存在仍可保留 PRESENT；一个观察混有有效和无效证据时，矩阵只检查任一证据有效，就显示整体“原文已定位”。 | 无证据或混有无效定位的自动 PRESENT 观察转为 AMBIGUOUS；原始 provider_output 保留。矩阵要求全部绑定证据有效。零证据、无效、混合三种输入回归通过。手工记录仍允许用户独立整理。 |
| M05 | 内置合成 PDF 改名后走普通上传路径，`synthetic=False`，矩阵会显示 USER PDF，项目 / 导出顶层缺失警示。 | 上传时复用源 SHA256 识别三个已知 fixture；项目列表、矩阵、检查器和导出保留合成标识。不会因此启用固定 Demo provider，也不声称识别所有合成文档。回归及普通上传浏览器流程通过。 |
| M06 | 服务只核对 Origin 与来访 Host 是否相同，未限制 Host。测试中恶意域名 Host 的 GET 返回 200，同名 Origin 的 POST 返回 201，缺少抵御 DNS rebinding 的必要边界。 | 使用标准 TrustedHostMiddleware 只接受 127.0.0.1 / localhost，继续同源写入检查。恶意 Host 的项目读取、源 PDF 读取和写入现在全部 400；合法回环地址流程通过。 |
| M07 | 把某观察维度修订为已有维度时可产生重复键；矩阵 `.find` 只显示第一条，另一条被隐藏。按原始维度判断添加 / 重跑冲突也会漏掉修订后的名字。 | 创建、修订和重跑保留逻辑使用有效维度键；冲突返回 409，事务不追加半条修订。重命名、重复添加和重跑唯一性回归通过。 |
| M08 | 多论文判断的证据勾选框只有页码与 quote。不同论文在同页出现相同文本时，用户无法辨别正在关联哪篇论文。 | 每项显示与矩阵一致的论文编号及标题；浏览器回归验证 Aster / Birch 来源可辨识。后端原有跨论文范围校验仍保留。 |

主要修复入口：
[workspace.py](../../src/comparison_workspace/services/workspace.py)、
[models.py](../../src/comparison_workspace/domain/models.py)、
[demo.py](../../src/comparison_workspace/providers/demo.py)、
[HTTP adapter](../../app/comparison_workspace_api.py)、
[App.tsx](../../web/comparison-workspace/src/App.tsx)、
[exports](../../src/comparison_workspace/export/reports.py)。

## MINOR findings

- **m01，已修复：** CSV 项目行重复包含整个项目、页面与运行历史，两个简单分析就可能触发普通 CSV reader 的字段长度限制。
  项目行现只放元信息，子对象仍逐类独立导出；没有删除原记录、修订或 Run。
- **m02，保留：** 证据在多次运行中重复出现，选择框会变长；来源现在可辨识，但阅读成本仍高。
- **m03，保留：** 390×844 可用，矩阵需要内部横向滚动，抽屉可关闭；小字、紧凑按钮及嵌套滚动不适合投影展示。组会使用桌面尺寸。
- **m04，静态检查：** 浏览器 `popstate` 复用会 pushState 的 navigate，可能产生重复历史项。当前“全部项目”和列表重开路径已验证；本轮未改导航机制。
- **m05，保留：** App.tsx / CSS 较密集，完整 provider 输出主要通过 API 与导出审阅；运行弹窗主要显示元信息。
  这是维护 / 深度检查的便利性限制，不应把“保留原提议”描述为已经有完善的原提议对照 UI。

## OPTIONAL future ideas

仅记录，不实现：用少量经授权真实论文做任务观察，评估研究生是否能正确区分原文定位、解释与修订；
根据观察结果再决定是否改善长证据列表、导入指导和键盘导航。没有开始 v0.2、OCR、KG、GraphRAG、
向量库、多 Agent、多结果矩阵、团队账户、新 benchmark 或旧 pilot 重分析。

## Fixes made

本地提交 `5279bb4`：14 个文件，+310 / -41，包括 9 项新增后端回归、2 条新增浏览器流程及实施 / 测试报告补记。
没有增加新依赖。新增 `Finding.stale` 直接保护已复现的“旧手工判断被当成当前结论”风险，
消费者只有工作台视图和导出；没有增加自定义 manifest、hash gate 或泛化基础设施。
合成识别复用既有 PDF 字节哈希，不给普通源码建立额外 integrity 层。

## Tests rerun

| 命令 / 检查 | 本轮结果 |
| --- | --- |
| `.venv/Scripts/python.exe -m unittest discover -s tests/automated -p test_comparison_workspace.py -q` | 修复前 36 通过；最终 45 通过，6.466s |
| `npm run build` | TypeScript / Vite 通过 |
| `npm test` | 最终 6 passed，15.1s |
| `npm audit` | 0 vulnerabilities |
| `.venv/Scripts/python.exe -m pip check` | No broken requirements found |
| `.venv/Scripts/python.exe -m unittest discover -s tests/automated -p "test_*.py" -q` | 在 clean `5279bb4` 上完整运行一次：1126 tests，255.416s，OK，15 skipped |
| `.venv/Scripts/python.exe -m app.quality_gate --level basic --skip-tests` | 562 files，0 errors / 0 warnings，PASSED；测试明确 SKIPPED |
| `.venv/Scripts/python.exe -m app.quality_gate --level full --skip-tests` | 562 files，0 errors / 3 warnings，PASSED；测试明确 SKIPPED |
| `git diff --check`、`git diff --check origin/main...HEAD` | 通过 |
| 实际服务与浏览器 | 回环端口 8765，独立临时测试目录；三种尺寸、PDF 第 2 页、修订、旧状态、重开及下载已检查 |

15 项跳过涉及未配置的外部真实 evidence 和当前 Windows 的大小写 / symlink / junction 能力边界，
不等于这些路径已验证。Full 三条警告仍为历史 W1 CSV 结构、19 个历史 ID 匹配及已跟踪旧 experiment，未修改它们换取通过。
已见 Starlette TestClient 的 httpx 弃用警告、损坏 PDF 的 EOF 诊断及测试中预期的 fail-closed 输出；suite 最终 exit 0。

## Scientific-boundary assessment

| 指定红队场景 | 结果 |
| --- | --- |
| 1. 分析后换问题 | 原 Run stale；手工 / 修订判断也分开失效，重跑不能静默恢复旧判断 |
| 2. 换活动目标 | 原分析 stale；非活动修订不会混入新 Demo 输出；切回后修订仍在 |
| 3. quote 不匹配 | locator INVALID；自动支持 / blocker 降为未决，自动 PRESENT 观察为 AMBIGUOUS；原提议保留 |
| 4. 明确冲突与无关未知并存 | 相同协议问题下 A/B split blocker 与 B 预处理 unknown 同时存在；四类可共存 |
| 5. 合法差异 | 只比较报告数字时 split / 额外训练数据作为允许差异，没有自动 blocker |
| 6. 扫描 / 空 PDF | NO_TEXT / EXTRACTION_FAILED 是技术状态；自动流程明确拒绝，手工阅读路径保留 |
| 7. 错 PDF hash 的导入 | 身份校验拒绝，不污染项目 |
| 8. API disabled | 无 Key / hard offline mock 断言没有调用；离线浏览器流程无外发 |
| 9. 导出路径 / 秘密 | 已有测试占位凭据、私人路径模式及 CSV 公式防护通过；实际合成导出无本机仓库绝对路径；不承诺识别任意私人文本 |
| 10. 合成来源 | 默认演示和已知 fixture 的新普通上传保留警示；源页始终明示非研究证据；既有数据库未做批量迁移 |

数据流可区分：原始 PDF 字节 → 源快照 / 页面文本与哈希 → provider 原提议 → 服务器定位投影 →
问题相关解释 → 独立人工 correction。quote 出现不等于解释被证实；PRESENT / LOCATED 也不是人类 gold。
UI 没有普遍可比性 YES、科学优越性分数或把缺失自动当成冲突的机制。
旧下游研究的 original human Gate、Full Pro sensitivity 和 prospective rubric 身份均未改动。

## Engineering / CI assessment

`app → src` 方向、薄 HTTP adapter、可选产品依赖、声明输入隔离复制测试成立。
SQLite 参数化 SQL、BEGIN IMMEDIATE 与 expected_revision 防止写入覆盖；Run 完成时在同一事务校验 revision，
晚到输出保留为 STALE。后台单 worker、重启标记 INTERRUPTED、无自动外部重试符合本地 v0.1 范围。

源文件使用服务器生成 ID 和独占创建；下载先校验 project / paper 绑定。25 MiB / 100 页、损坏 / 加密 PDF
的拒绝路径通过；没有浏览器任意文件路径接口。没有 .env 加载、Key 回显或 Codex 凭据推断。
OpenAI 输入有字符上限，异常返回安全原因，SDK 零自动重试与 store=false 已 mock 验证；没有 live 请求。

启动在 Windows 实测，默认数据目录位于仓外；已有构建可以离线启动。第一次安装 / 构建仍需 Node / npm 和依赖准备。
CI 新增依赖安装位于 unittest 前，Node 22 / 锁文件 / Chromium 安装 / 浏览器启动路径匹配；
原完整 unittest 仍是单独阻断步骤，后续 Basic 明确 skip tests。未发现静态可确定的 CI 阻断缺陷。
本地 pip check / build / tests / audit 通过不等于 Ubuntu runner 已通过，PR 后还须观察真实 GitHub CI。

限定为单用户、单后台；不承诺数据库多进程协作、恶意 PDF 的资源隔离、复杂公式表格解析或所有历史数据库迁移。
Markdown / CSV 是可读与程序消费记录，完整结构交换优先 JSON；自动脱敏不是任意私人内容的识别器。

## UX assessment

首页明确展示“具体问题 → 条件 → 证据”，无需先读实现文档即可进入合成演示。
每篇一个活动结果、单元格到原文、来源标识、修订理由与历史、导出构成连贯工作流；无 Key 手工模式确实可用，
但需要用户自己阅读与建字段，不能宣传为无 Key 自动理解任意论文。

实际检查 1440×900、1280×800、390×844：首页 / 工作区、四类审查、原文高亮、本地 PDF canvas、并排阅读、
修订及 stale 历史区。浏览器无捕获到的 error / warn；响应式回归无页面级横向溢出。
矩阵内部横向滚动属于既定设计，窄屏抽屉可关闭；建议组会用桌面，先演示三个固定问题，再演示修订。

实际停止并重启独立测试服务后可重开原项目；后续修订也经过返回概览 / 重开验证。
实际下载的 Markdown 含合成警示、stale 分区、原记录和 correction；JSON / CSV 下载由浏览器回归及内容断言验证。
演示脚本与不应声称的内容见 [FINAL_DEMO_READINESS](FINAL_DEMO_READINESS.md)。

未 push、未创建 PR、未 merge / tag / release；原工作区及其未跟踪 reentry 目录保持原状，旧 C 盘副本未触碰。
