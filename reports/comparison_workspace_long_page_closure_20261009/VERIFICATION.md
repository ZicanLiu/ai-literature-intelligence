# S1-B 科学审阅收口与长页 span 边界

日期：2026-10-09。起始 HEAD 15b7cb8；原 Run run_4dddc42080ea4168a41eb9bad15166bd。
本轮零真实 OpenAI/DeepSeek 请求，未创建 Analysis，未改原生 Run/Project/冻结材料，未 push/merge。

## 独立科学审阅

来源定位、AI_ASSISTED_REVIEW、UNCONFIRMED、人类确认分开记录；HUMAN_CONFIRMED=0。
原 Run 五条证据继续 LOCATED；独立补充 anchor/视觉核对不伪装成原模型选择。

| 主张 | 本轮判断 / 后续处理 |
| --- | --- |
| C01/C03 | 核心 mean=0.023、scatter=0.105 dex 有 Table 2/§5.3 可审阅来源；APOGEE [M/H]−GALAH [Fe/H]，overall 不分 MS/RGB。不是同量 median 或均值标准误 |
| C05/C06 | 外部 MWM–GALAH DR4 median=0.01 有 §3.3 来源；MWM 全局 [M/H]、GALAH pseudo-iron [Fe/H] 定义不同，不借用 Figure 9 内部比较 |
| C08/C10 | Table 1 参考 N=63136、Figure 10 GALAH 面板 n=33901；样本映射、正文 median 分母 UNKNOWN，不推断 before/after cuts |
| C09 | 拒绝无条件“未报告散布量”的表述：已选片段不能证明全篇缺失，图示有 σ=0.09；σ/MAD 定义仍 UNKNOWN |
| C11 | 论文明确全局 metallicity 未校准；旧 Run 未引用，仍无旧产品来源支持；新 producer 仅提高未来引用可达性 |
| C13 | Figure 10 caption 是双方 SNR>50、MWM 无 BAD flags；不能扩成双方无 BAD flags。GALAH 其他 flags UNKNOWN |

形成四份有 AI provenance 的 correction proposals：样本口径限定、散布否定句限缩、校准 caveat、
flags 巡天归属。全部 UNCONFIRMED、未应用，不调用默认 operator=local-user 的 Correction 接口。
校准块也含 §3.1 IRFM 温度样本的 E(B−V) cuts；不能移植到 §3.3 的外部金属丰度比较。

## 最小生产修复

原代码在切块前用 len(page.text)>10000 排除整页，把单条 quote 上限误扩成页面上限。
仅调整 providers/evidence_handles.py：超长页没有整页 handle（context_handle=null），但原有 3000
字符唯一连续短块可引用。hash/offset/paper/source/ownership 与原 locator/validator 全部不变。
没有跨页拼接、归一化、句意推断或旧引用救回；重复/空白/错误来源继续 fail closed。

实际 p6 长 11444，四块分别 [0,2974)、[2974,5863)、[5863,8812)、[8812,11444)。最后块长 2632，
完整覆盖校准段 [9333,9910)，原文/哈希不变。新 host control 精确 LOCATED，provenance 明确区别
于旧模型选择，未写回 Run。旧 Run 的 p6 引用数仍为 0。

S1-B 候选 167→171，所有 53 页均有合法片段，整页 handle 仍只有 52。输入 322349→322626 字符，
增 277（0.0859%）；精确新 tokens/实际费用未测。没有检索/索引或额外模型调用。
长表全文上下文仍保留，但未必存在保全表头到脚注的单个合法 quote；多条来源不能自动变成科学批准。
两家 adapter 继续使用相同 wire，Demo/Import/Manual/历史 canonical 合同不改。

## 回归与历史保护

定向：116 tests，PASS，无 skip，含配置的 S1-A、原 S1-B、最新 span v0 Run 回放。
新增覆盖 10000/10001/30001 边界、长表上下文、重复长页拒绝、long-page hash/跨请求/ownership/
active-result 拒绝，以及真实 p6 完整 caveat 和原 Run 五条引用不变。
165 个旧文件在验证前后 hash 一致，包括旧 live ledger/Run/PDF/报告；原 Run state hash 保持不变。
完整 suite 和两个 skip-tests Gate 将在 clean 本地代码提交后按 CONTRIBUTING 顺序运行一次。

## Analysis 准入结论

核心两项 Result 有充分可审阅来源；未知项不必全变成 PASS 才能做受控的条件比较。
但当前 **NOT_READY_FOR_AUTOMATIC_ANALYSIS**：用户尚未确认核心主张/目标，四份 proposal 未被采纳，
active target 未选择。不能直接把旧 description 的否定句/样本暗示带入支持性结论。

未来先由用户明确确认 C01/C03/C05/C06 目标和 proposal 采纳范围；保留 C08/C10、MAD、GALAH 其他
flags 为显式 UNKNOWN，新校准来源另记 provenance，不把旧 Run 升级。原问题/scope 保留，若要添加
约束必须清楚冻结前后输入；只有用户批准后的更正才走现有 Correction 流，pending AI 文件不能冒充
local-user 已应用修订。0.013 只是 mean-minus-median 名义差，禁止无控制的准确度提高结论。

新授权建议最多一次 Analysis（deepseek-flash，high/32000，重新核对预算/公开合同），无重试、fallback
或连接探针；需新 harness 支持 null 整页 context，旧 Extraction runner 的 HEAD/长度/映射假设不复用。
incomplete、schema/handle/source/active-result 错误、未知条件被提升为已支持、错用样本/统计量/flags/
校准或必要上下文不可审阅立即停止。技术 LOCATED 不等于 HUMAN_CONFIRMED。

完整独立记录与 proposals 位于仓外 s1b_scientific_closure_long_page_20261009；不提交源 PDF/完整回应/数据库。
本轮结论仅为科学审阅 proposal 收口和长页边界离线验证，不是 Analysis 结果或 S1-B recovered。
