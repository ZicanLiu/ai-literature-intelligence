# Cross-paper evidence identity：诊断与最小修复

日期：2026-10-09，Asia/Shanghai。本轮零真实 API、零付费模型调用；不 push / merge / 修改 PR。

## 版本与证据

入口工作树 codex/srtp-reentry-audit-20261002 / 5876190，只有既有未跟踪
docs/reports/reentry_20261002/。fetch 后 HEAD、main、origin/main 相同，没有远端主线差异。
GitHub PR #87 为 OPEN / unmerged，head fc7de56、base 5876190。

v0.1.1 本地继承链：4f7bf7a BYO AI → d818eb1 live safety → 371fe9f diagnostics →
867a0db stabilization。最新分支比远端 PR #87 head 多 11 个本地提交，四个阶段均未推送；
这些工作树开始时干净。基于 867a0db 新建独立 codex/comparison-workspace-identity-robustness
工作树，保留全部已有分支及入口未跟踪文件。main 未合并 PR #87，CURRENT_STATUS 仍是
旧 downstream 阶段快照；本报告以实际 Git、源码、原生 Run 和当前 PR 状态为依据。

只读资料：PR #87 与本地完整 v0.1.1 源码/测试、产品 ARCHITECTURE / DATA_PROVENANCE、
S1 diagnostics / stabilization 报告，以及仓外 deepseek_live_s0_s1_20261007、
deepseek_s1_reasoning_diagnostic_20261007、s1_stabilization_two_family_pilot_20261008 的记录。
在 MVP 及旧交接目录未发现指定 CODEX_SOL_CROSS_PAPER_IDENTITY_ROBUSTNESS_AND_3_FAMILY_VALIDATION_20261008.md。
没有把历史调用预算当作授权；未读取 .env。

## 失败层与置信度

S1-B 原生保存 Run：run_c200c013f11c49ec9d0afb3b4f3731fa，extraction，provider_status=completed，
本地 FAILED，output=null。捕获文件保留精确 validation_diagnostic：

- 路径 $.results[2].evidence[0].paper_id；规则 evidence_paper_ownership。
- Result 允许 MWM DR19 的 paper_ecf690c996fc403180a3f1af2bbaebb9 /
  src_4ccb9120233547a08192963408913c6a。
- 证据返回 2022 跨巡天论文的 paper_7ec367ccb6ee48b5b758929cf4db28b1 /
  src_b4e7474049e94f4f8455b627f0e0375e。

源码链为 provider completed → Pydantic 解析 → Workspace.validate_output → Result.paper_id
形成 allowed_papers → bind 在 locate 之前拒绝 evidence.paper_id。两个返回 ID 都是真实项目
身份，仍不满足该 Result 的局部归属。这是高置信度的本地身份校验失败；不是 JSON/schema
解析失败，也未发现中间转换或字符串反推身份的代码。原 validator 正确。

旧 S1-A 补充 analysis（run_32afe55930b148228781eced9dcf0563）同样记录 completed 与
“提供方引用了其他论文的证据”，已进入 bind guard；但没有具体候选/path/原始 JSON。
同一 guard / 故障类别：高置信度；同一模型生成原因、误引对象或 quote：证据不足。
它与另一次 12000 output cap 的未完成 analysis 是不同失败，不能混为身份问题。

两次失败的 raw 结构化响应均未持久化。无法知道 S1-B 第三个候选的标题、引文或生成意图，
也不能声称保存响应完整回放。仓内 s1b_identity_diagnostic_20261008.json 只复制安全原生诊断，
对应回归明确使用 diagnostic scaffold，证明该已知身份关系仍被拒绝，不伪装缺失的真实响应。

已确认的接口风险：旧 prompt 要求模型重复生成 evidence.paper_id、source_snapshot_id、
page_index，而程序已持有这些关系；schema 允许彼此独立组合，不能表达对象间 ownership。
这解释了为何合法结构可以越过 parsing 后才被拒绝，不足以解释模型为何选择另一篇论文。

## A / B / C 取舍

| 路径 | 收益 | 风险与决定 |
| --- | --- | --- |
| A：Prompt / Schema 澄清 | 明确各对象 allowed scope，改动少 | 无法使重复生成的身份关系确定正确；单独采用证据不足 |
| B：host-owned 页面身份 + 查表 | 一次引用绑定真实 paper/source/page，无法伪造身份组合 | 仍可能选错合法 handle，继续硬拒绝；采用，并辅以必要 scope 提示 |
| C：per-paper extraction | 可缩小提取上下文 | 增加请求、调度/失败合并逻辑，且不解决 analysis 引用选择；本轮不采用 |

选择 B 的目标是消除可由 host 确定的身份组合生成责任。它不是把错 ID 替换成当前论文，
也不承诺模型将不再选错论文。模型仍须选择 Result.paper_id / active result references；
所有来源选择错误继续 fail closed。没有语义相似度、模糊引文、改权重、动态预算或重试。

## 实现和边界

- providers/evidence_handles.py：API 专用输出 schema。证据仅 evidence_handle / quote；
  当前快照逐页随机 handle → 明确 paper/source/page 查表。发送前拒绝重复 paper/source、
  不完整/错序页面和文本哈希不匹配，防止映射有歧义或绑定到错误页。
- 两家 provider：同一单次请求/授权/预算流程，解析新 wire 后仅按表转换原 canonical 输出。
  未知、伪造、跨请求 handle 和同一候选重复 handle/quote 直接失败，并保留安全 response metadata。
- Workspace：ownership、active-result、source identity、exact locator 的 guard 未放宽。
  唯一投影变化是保留原始 wire provider_output 及 evidence_handle_sources 供 Run/export 审计。
  ValidationDiagnostic 仅新增 evidence_handle_identity 规则；旧合同/历史记录不迁移。
- 页面 handle 不是最终 EvidenceSpan ID。同一页不同 quote 可复用 handle；分别生成不同 span。
  S1-A 历史成功响应确实需要这种复用。相同引用不能重复填充单个候选；不同候选可复用引用。
- 原文不匹配仍 INVALID，PRESENT / supported 等仍按原规则降为待复核；没有迁移到另一论文。
  精确出现仅证明文字出现，不证明模型语义或论文结果选择正确。
- 历史 Demo / Import / manual 保持原 canonical schema；API 的新 schema 不自动兼容旧 wire
  响应，也不尝试修复旧失败 Run。成功输出才保存 wire/map；失败 raw 仍不保存。

调用关系先搜再改；无前端行为、数据库结构、科研冻结数据或第三论文族任务变更。
新查表的真实消费者是身份转换与 raw proposal 审计；若不能查到来源则拒绝，避免无可审计归属。

## 离线验证范围

产品定向回归包括两家适配器 / 两阶段、正确跨论文 finding、另一论文合法 handle、
缺失/重复/未知/伪造/跨请求引用、模型身份覆盖、源哈希/重复身份、错引文、原 source guard、
S1-B 安全诊断 scaffold、原 provenance/授权撤回/严格失败测试。

可选只读回放通过 COMPARISON_IDENTITY_REPLAY_ROOT 指向仓外双族 pilot。读取两个 S1-A 成功
Run 的实际 input_snapshot 和保存 provider_output，机械转换成新 wire，通过两家真实 adapter
代码 + mock transport，再经原 Workspace validator。逐字段比较 canonical proposal、source/page/
hash/offset/quote/locator、Result/Observation/Finding 投影；仅忽略新生成 ID 和 provenance 时间。
不提交原始论文、文本、运行数据库或完整响应，不改写历史 artifact。

本轮测试结果、代码验证 SHA 和命令记录在 TEST_REPORT.md。回放通过只能说明新身份适配与
这些保存内容兼容，不证明新 prompt 下实际模型生成稳定性。

## 当前结论与下一轮建议

S1-A：历史真实成功事实保留，新代码离线兼容可验证；旧失败 analysis 的生成原因仍不明。
S1-B：历史真实 extraction 失败保持 FAILED，analysis NOT_RUN；已知越界关系继续被严格拒绝，
尚无新真实 API 完成证据，不能写 recovered。

建议另获授权后做最小 2 次 DeepSeek 生成：原 S1-B 两论文/同问题的新项目 extraction 1 次；
仅当通过身份校验且人工确认活动目标正确后，再 analysis 1 次。沿用 none/12000 与 high/32000，
不附加连接测试、不 retry、不第三族、不改模型。首个 incomplete、schema/handle/ownership
失败即停止；关键目标或证据无法确认也停止，不自动手工救回。若 extraction 失败，总量为 1。
若希望同时检验新生成 S1-A 流程，则额外需要 2 次，总上限 4；它不是本次建议的最小范围。
正式调用前应明确失败 proposal 的受限保存授权，避免再次只留下诊断而不能完整回放。

未验证：新 wire 的服务端实际兼容性、身份失败率是否下降、两族新模型输出效果、所有领域
泛化、科学解释正确率、付费费用或效率优势。工程 PASS 不构成研究优越性或 human gold。
