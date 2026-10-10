# DPR/RAG Analysis 真实失败离线诊断与验证

日期：2026-10-10。结论：已定位到 **DeepSeek 响应文本进入 Pydantic 的解析入口失败**，尚不能区分那次 JSON 语法失败与结构校验失败。历史具体错误为 **UNKNOWN**。确认并修复的是错误分类丢失这一可观测性缺陷，不是已经复原或修好了模型那次输出。

本轮真实模型请求、连接测试、重试均为 **0**；未修改用户项目、活动目标、Extraction、历史 Run、冻结科研材料或远端分支。AI 辅助科学审阅不构成人工确认。

**代码与保护基线**

实际工作树为现有独立 `comparison-workspace-identity-robustness`，分支 `codex/comparison-workspace-identity-robustness`。开始时 clean，HEAD `d7f236707f6cf16f82985a633dd8d651adba40f7`。诊断补丁提交 `6f7df53`，保留所有既有未推送提交。Team Preview 本地远端跟踪引用仍为 `3b3b984d217a0c734c47b9a45540646f2dfdebd8`；本轮未 fetch、push、merge 或修改 PR，未声称重新核对 GitHub 当前状态。

读取了 AGENTS、接手导航、当前状态、相关 provider/schema/Workspace/测试与前次 DPR/RAG 诊断。实际源码和 Run 高于历史文档。用户 SQLite 用标准库 `mode=ro&immutable=1` 打开，不创建 Repository、不读取环境 Key、`.env` 或运行中进程环境。审计使用已 checkpoint 的记录。

**最新失败 Analysis 的安全元数据**

| 字段 | 原生记录 |
| --- | --- |
| Run ID | `run_1d6cf22af0b44f0984d82f920bd56c6c` |
| Project / revision | `project_bbc47d100af64861901082c4af5dac87` / 7；检查时项目仍为 7 |
| stage / provider | analysis / deepseek |
| Run / provider status | FAILED / completed |
| requested / reported / legacy model | 均为 `deepseek-flash` |
| reasoning / 输出预算 | high / 32000 |
| input / output / total tokens | 54948 / 27395 / 82343 |
| cached / reasoning tokens | 0 / 23167 |
| 非推理输出（算术差） | 4228；不是保存的 JSON 长度 |
| elapsed | 105.581 秒 |
| incomplete_details / request_id | null / null |
| input modality / cost | EXTRACTED_TEXT / unknown |
| validation_diagnostic | `field_path="$"`, `rule="structured_output_schema"`, expected=[]，returned=null，handle_issue=null；无 parse_issue |
| output | null；没有保存的 provider 原始输出可复核 |
| 原生 state SHA-256 | `b13eae7ebe72550ef4b02e87f82da1c1ff6d7c949e6d4ab67e80369ebd422be2` |

开始于 `2026-10-10T04:48:56+00:00`，结束于 `04:50:42+00:00`。此前成功 Extraction 是 `run_95252a36a97e491c952656d389f3e11d`；其六个候选和 15 条 Evidence 保留。失败 Analysis 原子拒绝，没有新的 Observation / Finding 入库。

**解析层与 `$` 的含义**

调用链：`DeepSeekProvider._request` 的 Responses `create` → 检查 completed → `_parse_output` 的 `APIAnalysisOutput.model_validate_json(response.output_text)` → handle resolve → Workspace identity/source/active-result/locator 验证 → 入库。该错误规则仅由解析入口的异常处理产生；因此本次失败在 handle resolve 与 Workspace 校验之前，置信度高。

当前 wire schema 要求根对象包含 observations、findings 数组；Observation 包含 result_id、dimension、value、state、evidence；Finding 包含 category、affected_result_ids、scope、explanation、evidence。evidence 仅接受 evidence_handle；Record 禁止额外字段。状态和类别使用既有枚举。模型只选受控引用，后续由 host 解析来源。

旧 `_schema_diagnostic` 仅保留经允许名单过滤的路径及合并规则，丢弃 Pydantic 错误类型。合成 fixture 证明以下不同情形均可能显示 `$`：非法或空 JSON（json_invalid）、合法 JSON 的错误根类型（model_type）、未允许的额外根字段名称被安全隐藏、非文本输入（json_type）、其他入口异常。已知字段的错误可显示例如 `$.observations`。

因此 `$` 不等于“JSON 语法错误”，也不等于“超长截断”。这次是否带围栏、空输出、多个 JSON 文档、错误根类型、缺字段/枚举错误或其他形式，均 **UNKNOWN**。合成响应只检验本地合同，不冒充真实保存响应。

检查的本地 SDK 版本为 2.54.0；历史 Run 未记录实际 SDK 版本。其 `Response.output_text` 仅拼接 message 中 output_text 的文本，不拼接独立 reasoning 项。合成测试证明同一 JSON 的文本块可正常拼接，两个 JSON 文档拼接仍严格拒绝。不能据此推断那次服务返回了多个文档，或把 reasoning 文字混入输出当作已确认原因。

**与已成功 S1-A 的对照**

| 项目 | 成功 S1-A | 最新失败 |
| --- | --- | --- |
| Run | `run_601906dffb194d9eb56b96c8c5381072` | `run_1d6cf22af0b44f0984d82f920bd56c6c` |
| provider / Run 状态 | completed / COMPLETED | completed / FAILED |
| 模型、reasoning、输出预算 | deepseek-flash / high / 32000 | 相同 |
| input / output | 40285 / 31462 | 54948 / 27395 |
| reasoning / 非推理算术差 | 23601 / 7861 | 23167 / 4228 |
| reasoning 占 output | 75.0% | 84.6% |
| 报告 output 距预算的算术差 | 538 | 4605 |
| elapsed（Run 用时） | 127.37 秒 | 105.581 秒 |
| 页数 / 结果候选 / 输入 Evidence | 32 / 2 / 5 | 32 / 6 / 15 |
| 输入 Evidence quote 字符 | 1165 | 32664 |
| PDF 提取原文字符 | 124979 | 124936 |
| 重建声明 payload 字符 | 139761 | 184506 |
| schema / 引用形式 | AnalysisOutput；canonical paper/source/page/quote | APIAnalysisOutput；source-span/v0 handle |
| active 科学目标 | DPR Single 41.5 与 RAG-Seq. 44.5 | DPR Single 与 RAG 架构/训练配置 |

两篇原 PDF 的 SHA-256 在两次快照完全一致：DPR `3e67fc1a9977715acf722d85f0b7d124b03715e975f6310a4d6c12094190912f`，RAG `23e3249e9a1e75418d82efecab0ea8c4d033b89c93742f63208d47ce01f21233`。解析器记录分别为 pypdf/6.19.0 与 pypdf/6.20.0；页面文本确有 43 字符差异，未把两次 canonical text 当作完全相同输入，也未重绑历史证据。

当前 adapter 发送完整页面、所有候选与既有 canonical Evidence，再附 active_results；长 quote 与页面内容在不同字段中再次出现。输入 token 增加 14663（约 36.4%），说明成本/上下文负担增加，但不能隔离归因于某一字段。字符统计是按对应协议重建的声明 payload，不是保存的请求字节、精确 token 或费用；instructions/schema 等也影响服务计数。原始请求与原始响应均未重建为历史真值。

high reasoning 的成本与输出分配风险值得关注：此次 23167 token 用于推理，算术上剩余 4228 非推理输出。但 provider completed、incomplete_details=null、27395<32000；成功 S1-A 同样 high，推理绝对 token 反而更多。现有证据 **不支持 token 上限截断、高推理导致 JSON 错误或 SDK 超时的结论**。减少 reasoning 可以成为未来明确配置的单次观察，不能称为已证明的修复。实际费用未知，应看服务方账单，不由 token 差或旧报价推算已付费用。

**独立科学目标审阅（AI_ASSISTED_REVIEW；HUMAN_CONFIRMED=0）**

对失败 Run 快照与当前 active ID 交叉核对，并只读渲染原 PDF 表格。来源定位与科学支持分开记录：

| 目标 / 候选 | 来源及核对 | 结论与未决条件 |
| --- | --- | --- |
| DPR active `res_18974751357d49289217ead7332956b1` | 两条引用均 PDF 第 8 页 LOCATED；Table 4 的 Single / DPR / NQ = 41.5 | 与 NQ 端到端 QA EM 目标相符；Multi / DPR 也为 41.5，必须保留训练标签。同页 39.8 属另一个 joint ablation，不混为主结果。不能仅用相同数值确定实验身份。 |
| RAG active `res_6b1995e3838c4a76b8c7f077d6100f2d` | 引用第 3、3、18 页，均 LOCATED；候选自身 experiment_identity 是 §2.2–2.4、附录 C/G 的架构与训练配置 | **不是所需的 NQ EM 实验 Result**。需要用户重新选择/明确目标；未自动改写选择。这是独立科学风险，不能据此解释 JSON 解析失败。 |
| RAG inactive `res_9b14b3f4a1ef45209acb087722ba664b` | 引用第 6、4 页；第 6 页 Table 1：NQ RAG-Token=44.1，RAG-Seq.=44.5，DPR comparator=41.5 | 是可供用户审阅的 QA 候选；一条候选同时包含两个变体，需要明确要比较哪一个，不能自动默选。检索文档数、解码、训练/评测 split、质量条件仍须逐主张保留来源并确认。 |

当前正确研究问题并不保证所选 active Result 正确。两篇候选标题相同于论文标题，使用者需要看 description / experiment_identity 区分实验；本轮未扩展 UI 或改变候选。已有 LOCATED 不升级为 SCIENTIFICALLY_SUPPORTED 或 HUMAN_CONFIRMED。未创建 correction 或人工裁决，也未宣称所有 Extraction 描述均已科学验收。

**实施的最小改动**

- `domain/models.py`：ValidationDiagnostic 增加可选 parse_issue；历史缺省为 None。
- `providers/openai_provider.py`：复用两家 adapter 现有错误入口，仅将库错误类型归入 JSON_SYNTAX / SCHEMA_VALIDATION / PARSER_INPUT / PARSER_FAILURE；保留原路径过滤。不保存异常消息、原始输入、违规值或未经允许的字段名。
- 前端 `types.ts`、`App.tsx`：错误提示与历史记录显示安全分类；历史无分类明确 UNKNOWN，继续显示请求已发生、用量、失败未入库与审慎下一步。
- 三个 unittest 文件、mock_live_server、浏览器 live-ai.spec：覆盖语法/结构/输入/异常、SDK 文本拼接、旧记录兼容、跨论文严格拒绝、原子失败、导出、假 Key/私人值不泄漏。
- PRODUCT_GUIDE：说明分类及限制。

**未修改** DeepSeek parse 方法、Analysis schema、prompt、reasoning/预算默认值、handle 注册/查表、source/active-result/quote validator、失败原子性或重试策略。没有去围栏、补括号、删坏引用、部分入库或 fallback。因此只提高下一次失败的可观测性，不承诺提高历史输出通过率。

**离线验证**

在 clean 代码提交 `6f7df53d325e9d287c0504306fa8f5b85ad43025` 上，按 CONTRIBUTING 的唯一顺序运行完整 unittest 一次，随后 Gate 明确 `--skip-tests`，未重复完整套件：

| 检查 | 实际结果 |
| --- | --- |
| 定向 unittest | 123 tests，OK，0 skip，16.257 秒 |
| 完整离线 unittest | 1204 tests，OK，15 条件性 skips，256.248 秒；无失败 |
| Basic Gate --skip-tests | PASSED，609 files，0 error / 0 warning |
| Full Gate --skip-tests | PASSED，609 files，0 error / 3 既有 warning |
| Chromium 浏览器回归 | 24/24 PASS，42.9 秒；隔离数据、硬离线 / SDK mock |
| TypeScript + Vite build | PASS |
| 完整分支 diff --check | PASS |
| 历史保护 | 191 份既有科研材料文件 hash 一致 |
| 用户保护 | 数据库 + 6 份 PDF 共 7 文件 bytes/hash 一致；4 条相关原生 Run state hash 一致 |

Full 的三项 warning 为既有 W1 CSV 结构、19 个历史 annotation ID、旧 tracked experiment；未修改历史材料。完整套件中的负例会输出预期 FAIL CLOSED/FAILED 文本，最终 unittest 结果为 OK，不将负例日志误报为测试失败。Starlette/httpx 的既有 deprecation warning 未作任务外依赖升级。

验证命令为定向六个 comparison_workspace unittest 模块、`python -m unittest discover -s tests/automated -p "test_*.py" -q`、`python -m app.quality_gate --level basic --skip-tests`、`python -m app.quality_gate --level full --skip-tests`、`npm test`、`npm run build` 及 `git diff origin/main..HEAD --check`。实际使用具备 SDK 的既有测试虚拟环境；测试进程去除 API Key 环境项，未读取 `.env`。只读历史回放显式配置 COMPARISON_IDENTITY_REPLAY_ROOT、COMPARISON_SPAN_REPLAY_ROOT、COMPARISON_SPAN_AUDIT_ROOT、COMPARISON_SPAN_LIVE_REPLAY_ROOT，因此相关 S1 回放没有被未配置条件跳过。

S1-A 保存的成功 Extraction / Analysis canonical 输出兼容回放通过。原 S1-B 六证据仍为 **2 LOCATED / 4 INVALID**；E3 错页与 E6 历史 quote 不获自动救回；span live 原五条引用与未引用第 6 页 caveat 的历史事实不变。长页源控制保持独立 provenance，不是给旧 Run 补证据。

新增诊断单测以 socket guard 禁止网络，synthetic fixture 重现 completed + 本次相同用量的解析失败，但不冒充真实历史响应。浏览器新增场景验证 JSON_SYNTAX / SCHEMA_VALIDATION 分别显示、两次显式 mock 生成恰好两次 SDK 调用、失败项目不变、JSON 导出分类、旧诊断 UNKNOWN 及重开无隐式请求。开发时初次定向测试曾因新测试方法中误放旧断言失败，已将旧断言原样归回原方法，随后 123 项通过。

仓外本轮专用 `dpr_rag_analysis_failure_20261010` 保留 safe_metadata_comparison.json、synthetic_parser_probe_before.json、verification.json、保护 hash 清单与测试日志。只读 PDF 页渲染也仅留在该本地目录；未提交数据库、PDF、页图、完整模型响应、reasoning、Key 或本机私有绝对路径。报告之后的提交只记录文档，不代表重新执行真实实验。

**下一步最多两种**

1. **建议先免费收口**：用户核对并明确 RAG NQ EM 变体，复核 DPR Single 主结果及评测条件；用现有手工审查/导出记录 UNCONFIRMED，暂不付费。这同时纠正独立的科学目标风险，不能还原那次未知 JSON。
2. **有条件的一次新付费观察**：仅在目标和条件明确、采用本地诊断补丁、用户另行明确授权一次 Analysis 后考虑。冻结所选 Result / 输入 revision / 模型 / reasoning / 输出预算；若降低 reasoning，将其标为新参数观察而非已验修复。只发一次生成，SDK/HTTP 不重试，无连接探测或 fallback；completed 后仍须严格 schema/handle/ownership/source 校验和独立科学审查。任何 incomplete、解析/引用/来源错误或关键目标混淆即停。只保存安全分类与元数据；未经额外许可不留原始响应或 reasoning。不默认连续试错，不把单次成功解释为稳定性证明。

目前 **不建议立即按原配置重复付费**：RAG 活动目标不符，真实解析细节又缺失。新诊断能区分未来故障的大类，但仍不保证复原具体违规值。S1-A 的成功历史和 S1-B 既有事实状态保持原样；没有新增真实 Analysis、Human Gold 或 S1-B recovered 结论。
