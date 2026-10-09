# Evidence Span Handles v0

API wire 标记：`source-span/v0`。只保护来源/原样文本绑定，不认证科学含义。

## Source 与 wire

每次请求从 immutable input snapshot 验证 paper/source 唯一性、页序、页面数量和文本 SHA256。
handle 只在该请求内有效，绑定 paper_id、source_snapshot_id、page_index、page_text_sha256、start、end。
source text、offset 均采用 Python Unicode code points；不做空白、连字、数学字形或断词归一化。

正常页分为最多 3000 字符的连续、非重叠块，优先在窗口内最后一个换行后切开。块按原顺序发送，
拼接后逐字符等于 canonical page text，没有重叠复制或删除。API 输入页用 evidence_spans 的 text
替代重复的 page.text；page metadata 和原始 Run.input_snapshot 保留。

每页同时有一个引用整页原文的 context handle，作为该页的 evidence_handle；每个可引用块也有
独立 handle，映射的 context_handle 指向完整页面。表格必须审阅整页 context（标题、列头、单位、
脚注），需要时直接引用整页 handle；切块不会删除这些内容，也不自动判断表格科学解释是否成立。

重复或空白块仍显示为上下文，但不分配可引用 handle。整页若超过既有 quote 最大 10000 字符、
页面文本空白或有提取错误，保留原 text 并声明不可引用，不默默截断或拆成丢失表头的表格证据。
一篇论文完全没有可引用页则在发送前失败。这个 v0 限制明确牺牲长页引用覆盖，未引入检索/复杂索引。

输出 EvidenceReference 仅含 evidence_handle；quote、source、hash、offset 等额外字段一律拒绝。
host 按映射取 canonical text[start:end] 并形成原 EvidenceCandidate，再执行现有 Workspace guard。
模型不能生成/改写 quote，也不能把一页的 quote 与另一页 handle 组合。跨页不能拼成一条引文。
Result.paper_id、Observation.result_id、Finding.affected_result_ids 仍由模型选择且严格核验。

候选内重复 handle、未知、伪造、跨请求 handle 拒绝；跨论文/非活动 Result 拒绝。不同 span 可以
来自同一页，不同候选可以复用同一 span。source map 返回副本，不能修改进程内可信绑定。
API extraction Result 必须有来源 evidence；无法确认时返回无候选，不编造来源。analysis 的
NOT_LOCATED/AMBIGUOUS/UNRESOLVED 仍可没有 evidence，沿用原信息状态语义。

## Provenance 与兼容

两家 adapter 使用同一 wire schema / resolver，无新调用或自动重试，预算及发送前授权保持。
只改 API wire；Demo、Import、Manual、历史 Project/Run/canonical EvidenceCandidate 保持原合同。
新接受输出保存 provider_output、evidence_handle_sources 和 evidence_protocol；查表不重复保存正文。
旧 page-handle/quote wire 不能作为新 API 响应自动回退；历史 Run 仍原样读，不重新解释或改写。

原 locator、ownership、active-result guard 无改变。新 span 引用可以 LOCATED，也可以科学上不相关。
Finding 的 category 仍是 api provenance 的模型提议；本协议不产生 SCIENTIFICALLY_SUPPORTED、
HUMAN_VERIFIED 或 human gold。独立审查必须区分内部/跨巡天、样本池/图示样本、范围/专属精确值。
合法错误 span 的语义风险仍在，不能把来源保证当成 S1-B recovered。

## 预算与已知范围

S1-B 离线可行性：53 页中 52 页可引用，167 个候选；唯一不可引用页长 11444 字符。
六处经审计来源均有覆盖，两个关键表格可整页引用。producer 不含论文、页码、数字或 quote 特判。
原文只发送一次，extraction 输入字符约增加 3.05%；一个六引用 host 控制的 analysis 场景约增加
9.25%（较宽 canonical 引文被作为已有 evidence 再发送）。这不是新模型实际选择，也不是通用最坏上限。
没有本地 DeepSeek tokenizer，不能声称实际 token 增量；原 600000 输入字符上限继续 fail closed。
长页、许多宽引用、重复运行的 history 可增加输入/导出体积，不截断、不自动涨预算。

生成只扫描已有页面并做页内精确唯一性检查：哈希/切块随文本长度增长，唯一性检查为每页
O(页字符数 × 块数)，可引用页字符数受 10000 上限约束。查表每条引用平均 O(1)，另有 quote
序列化成本；映射/原文存储随文本与候选数增长，没有持久索引、检索阶段或额外模型调用。

离线通过只允许标记 SPAN_PROTOCOL_OFFLINE_VALIDATED。服务端实际兼容性、模型选择正确率、科学支持
和输入 token/费用仍需在新授权及预先声明的人工 Gate 下验证。
