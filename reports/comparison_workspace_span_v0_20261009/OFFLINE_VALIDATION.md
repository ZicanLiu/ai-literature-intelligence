# Evidence Span Handles v0：离线实现与验收

日期：2026-10-09，Asia/Shanghai。基线：codex/comparison-workspace-identity-robustness / 5a1e06d。
代码提交：69a8f93f19b7cffdddc5b742a8c00fa3326d0c72。验收状态：**SPAN_PROTOCOL_OFFLINE_VALIDATED**。
没有重置 main 或覆盖既有未推送工作；历史 Run、Recovery Gate 和冻结科研材料不变；本轮零真实 provider 调用。

## 协议与取舍

采用 source-span/v0，复用现有 EvidenceHandles。模型只选择 evidence_handle；host 从当前
canonical page text 的连续范围填充 quote/paper/source/page，原 Workspace guard 再验证。
映射包含 page_text_sha256/start/end/context_handle，存入既有 Run.output.evidence_handle_sources；
新增 evidence_protocol 只标识 API wire，Project/Run/canonical schemas 不迁移。

通用规则：原页按最多 3000 Unicode code points 的非重叠块发送一次，优先换行边界；每个可引用
块必须在同页唯一。完整页不超过旧 quote 上限 10000 时，保留整页 context handle；表格可一起引用
caption、列头、单位和脚注。重复块只作上下文；过长/空白/提取错误页完整保留而不可引用。
一篇没有可引用页面则在发送前失败。没有复杂索引、检索、模型预筛选、跨页拼接或归一化救回。

比只调 Prompt 更可靠之处是：新 wire 根本不接收模型生成 quote、hash 或 offsets，文字从可信映射
确定。原 E2/E4 表示变化和 E6 quote 换词不再是允许的输出操作；未知/跨请求/越权引用仍拒绝。
模型依然可能选错语义 span，也可能提出错误科学解释。LOCATED 不升级为 SCIENTIFICALLY_SUPPORTED、
HUMAN_VERIFIED 或 gold；现有 Finding.category 始终保留 API 提议 provenance，独立科学审查不可省略。

## Phase 1 先行测量

先在新的仓外 evidence_span_v0_offline_20261009 目录做只读 prototype，再修改生产代码。
producer 没有论文、页码、数字或 quote 特判；已知六例只用于外部覆盖测量，不用于生成候选。

| 指标 | 本次材料结果 |
| --- | --- |
| S1-B 页面 / 可引用页 | 53 / 52 |
| 候选 span | 167，包含整页 context |
| 明确不可引用页 | 1 页，长度 11444；保留原文，超过 10000 旧上限 |
| 六处原文 counterpart 覆盖 | 6/6；仅 host 控制，不是新模型选择 |
| 关键表格 | 两个均可整页引用，表头/单位/脚注未被删除 |
| 原 page-handle extraction payload | 312809 字符 |
| 实际 span v0 payload | 322349 字符，+3.050%；UTF-8 +9540 bytes |
| 六引用 host 控制的 prospective analysis 场景 | +9.251% 字符（包含较宽引用作为已有 evidence 的额外内容） |

DeepSeek tokenizer 不在本地，没有实际新 token usage；字符/UTF-8 是开销指标，不冒充服务端 tokens
或严格分词上界。原 600000 输入字符限制继续生效。若未来模型选很多宽 span 或重复分析，输入和
导出可能更大；本次六引用场景不是通用最坏上限。两家调用数和 reasoning/output 预算完全不变。
没有“通过缩小未知样本/删掉难页”制造恢复：长页明确不可引用，所有原文本仍发送，失败不会自动补救。
生成成本为页哈希/切块与逐块页内精确唯一性搜索，后者 O(页字符数 × 块数)，可引用页受 10000
字符上限约束；引用查表平均 O(1)，另有原文序列化。内存随源文本/候选数增长，没有持久索引。

## 修改范围

- providers/evidence_handles.py：span 输入、只选 handle 的 wire、可信文本/offset 查表和 fail-closed 边界。
- providers/openai_provider.py：两家共用的声明输入、source-span/v0 指令和 provenance tag；DeepSeek 自身
  request 继续调用同一 schema/共同 _call，没有另建兼容路径或调用。
- providers/base.py、services/workspace.py：在现有输出审计链保存可选 protocol 标记；原严格 validator/locator 没改。
- tests/automated/test_comparison_workspace_spans.py：通用 span、表格/重复/Unicode/限长、严格来源、真实历史保护。
- test_comparison_workspace_identity.py、test_comparison_workspace_s1_diagnostics.py、mock_live_sdk.py：同步新 wire，
  SDK/HTTP 内存 transport、授权、metadata、schema 安全回归继续执行。
- span_semantic_review.json：三个明确 SYNTHETIC / AI_ASSISTED / NOT_HUMAN_GOLD 的独立审查负例。
- docs/comparison_workspace/EVIDENCE_SPAN_PROTOCOL_V0.md、ARCHITECTURE.md、DATA_PROVENANCE.md：协议和限制。

## 兼容与历史保护

Demo、Import、Manual 继续使用原 canonical 输出；既有基线回归保留。历史 S1-A 成功提议经过原
canonical/Workspace 路径回放，定位和投影原样一致。其 extraction 4 条、analysis 47 条旧 LOCATED
引用的原文范围均由通用 producer 覆盖，这只是来源覆盖检查，不是新生成效果。新 wire 不再接受旧模型 quote，因此没有把旧
page-handle/quote 响应伪装成新模型选择；相关旧 adapter roundtrip 改为 canonical 历史回放，
两家新 wire 的真实 SDK parsing 另由四组内存 transport 用例覆盖。

S1-B 原 quote 回放仍为 2 LOCATED / 4 INVALID。E3 原页引用未重绑；E6 的 `median di fferent`
原样保留，旧 wire 不能注入新 API 自动改写。新 span 的正向 controls 使用独立 offline-host-control
provenance，不保存为历史 Run，也不声称模型会选择它们。67 个旧 Recovery/audit/pilot 输入文件受 hash
保护，外部完整源/响应/数据库不进入 Git。

语义负例包括内部比较冒充外部、Table 1 计数冒充 Figure 10 样本、多对象范围冒充 GALAH 精确值。
它们可以真实 LOCATED，独立 fixture 的科学支持仍 UNCONFIRMED。没有实现科学真值分类器，也没有
把 AI 自审变成人工最终裁决；模型即使提出 SUPPORTED category，也只保留 api proposal 的身份。

首次新增真实历史回归曾因测试查找 `different` 而不是保存的 `di fferent` 失败；改为断言真实原样
字符串。没有改记录、放宽 validator 或删掉历史 INVALID 检查来通过。

## 验证结果

定向回归：112 tests，PASS。包含 spans、identity、S1 diagnostics、live adapter/safety、Workspace；
外部 S1-A/S1-B replay 均显式启用，网络禁用，验证前后 67 个受保护文件 hash 不变。

按 CONTRIBUTING 的顺序在 clean 代码提交 69a8f93 上执行：

```text
python -m unittest discover -s tests/automated -p "test_*.py" -q
python -m app.quality_gate --level basic --skip-tests
python -m app.quality_gate --level full --skip-tests
git diff 5a1e06d..HEAD --check
```

| 检查 | 实际结果 |
| --- | --- |
| 完整离线 unittest（只执行一次） | 1193 tests，OK，skipped=15，255.674 秒，无失败 |
| Basic Gate | PASSED，599 files，0 error / 0 warning，tests 明确跳过 |
| Full Gate | PASSED，599 files，0 error / 3 warning，tests 明确跳过 |
| task 完整 diff / whitespace | 通过 |
| 历史保护 | 定向/full/两个 Gate 前后 67 个文件 hash 全部相同 |
| 真实 OpenAI / DeepSeek 生成调用 | 0 |

15 个条件性跳过没有隐藏本轮真实材料回放：本轮 S1-A/S1-B optional replay 均启用，定向 112 tests
无 skip。Full Gate 的三个历史警告为 W1 CSV 结构、W1 19 个 ID 未在统一样例中找到、历史已跟踪
openalex_stellar_spectra_60 experiment；本轮未改写这些历史数据。

验证 helper 移除 provider API Key/model 环境值并设置 DISABLE_LIVE_API=true；adapter 测试使用
mock/内存 HTTP transport，网络 guard 生效。既有独立工作树/v0.1.1 提交链保留，原工作目录的
docs/reports/reentry_20261002/ 未跟踪内容保持不动。报告以外未再改代码，不重复完整 suite。

新的仓外 evidence_span_v0_offline_20261009/ 保存 phase1_feasibility.json、production_measurement.json、
s1a_source_coverage.json、protected_inputs_before.json 和 verification/ 的四组日志/结果；不提交源 PDF、
完整响应、数据库或临时配置。新测试日志的用户目录前缀已脱敏；历史日志未触碰。
本轮不 push / merge / 修改 PR，不把新协议控制用例写回历史 Run。

## 尚未验证及下一轮条件

新协议的真实服务端兼容性、模型选择的科学正确性、实际 input token/费用、宽引用比例和端到端
S1-B workflow 尚未验证。未运行前端浏览器回归，本轮无前端修改。

下一次真实 DeepSeek 验证必须获得新的明确授权；冻结本协议/参数/输入，先限定一次 extraction，
核对引用科学范围、表头/脚注、内部与外部比较、样本和 caveat，完成人工关键来源/目标确认后才可能
允许 analysis。任意来源、schema/handle/ownership、关键目标错误或 incomplete 即停止；不能以本轮
offline controls/LOCATED 替代科学核验。本轮不启动 Recovery，不使用历史未执行的第二次预算。

允许结论仅为 SPAN_PROTOCOL_OFFLINE_VALIDATED；不得标记 S1-B recovered。
