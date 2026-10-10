# DPR/RAG 真实用户 handle 失败：离线诊断与有限修复

日期：2026-10-10。状态：**HANDLE_DIAGNOSTICS_OFFLINE_VALIDATED**。
起始发布 SHA：`3b3b984d217a0c734c47b9a45540646f2dfdebd8`，起始工作区 clean。
继续 `codex/comparison-workspace-identity-robustness`；代码提交 `d8a57007b16bef965e6a2a2728e664302de42875`。
后续仅报告提交。本轮真实模型请求 0，未 push/merge/修改远端 Team Preview 或 PR #87。

## 实际 Run 与失败位置

只用标准库 SQLite 只读查询用户记录，未用会写 schema 的 Repository 打开用户数据库。
未读 .env、API Key、认证头、进程会话凭据或完整原始 HTTP/SDK 响应。源 PDF 和原 Run 未复制进仓库。

| 项目 | Revision 2 | Revision 3 |
| --- | --- | --- |
| 输入 | DPR 2004.04906v3，13 页；RAG 2005.11401v4，19 页 | 同两篇、共 32 页 |
| 问题 / scope | 天文光谱金属丰度问题，scope 空 | DPR/RAG Natural Questions EM、配置/检索/训练/评价条件，scope 空 |
| 请求 / 返回模型 | deepseek-flash / deepseek-flash | 相同 |
| extraction 参数 | none / max_output_tokens 12000 | 相同 |
| provider / native Run | completed / FAILED | completed / FAILED |
| input / output / total tokens | 40008 / 5 / 40013 | 40077 / 891 / 40968 |
| 本地错误 | 未返回结果候选 | $.results[0].evidence[1].evidence_handle；evidence_handle_identity |
| 保存的 output | null | null |

Revision 2：问题与论文不匹配是已核实事实；API schema 允许空 results，随后 Workspace 拒绝零候选。
它与“找不到题目所需证据便返回空候选”的提示一致，但未保存模型完整回答/推理，不能断言其内部动机。
本地仍保留 completed 和实际 usage，不能把失败理解为未发送或免费。

Revision 3：已过 provider completed 和 API schema 解析，在 EvidenceHandles.resolve 查表/候选内去重
阶段失败，尚未完成 canonical EvidenceCandidate 转换、Workspace ownership/source/locator 校验或入库。
字段路径说明至少存在一个 Result，且其第二条引用失败；模型输出的总候选数 UNKNOWN。
原 resolver 用同一分支/同一消息处理“未声明”和“重复”。失败只保存安全元数据，provider_output 与随机
注册表没有进入 Run.output，因此**未知 handle 还是重复 handle：UNKNOWN**。没有用重新生成代替历史响应。

为什么没有可审阅候选：adapter 必须先完成整份 handle 解析才返回 ProviderResult；任一引用不合法即抛错。
Workspace.execute 将 Run 标为 FAILED，未得到可附加的结果集合，原项目保留。这里的全量拒绝是安全边界，
本轮没有接受部分候选、删异常引用或保存未经许可的完整响应来制造成功。

## 有证据的问题与未知项

| 判断 | 证据 / 置信度 |
| --- | --- |
| 历史诊断不能区分两类 handle 错误 | 源码合并分支、保存的合并 rule/message、output=null；高置信度 |
| 短页存在同一 handle 双重展示 | 源码页级 handle 与唯一块复用同值；对保存输入离线重建，86 个注册项出现 91 次声明；高置信度 |
| 双重展示导致本次第二引用失败 | 具体历史模型选择/注册表未保存；UNKNOWN，不当作已确认根因 |
| Prompt/Schema/注册表实际来源错配 | 源码使用同一请求内 handles 实例构建 payload 和 resolve；离线声明集合与注册表一致，未发现身份不一致 |
| 历史真实发送字节/随机表能否独立逐字复核 | 没有保存的真实请求表；UNKNOWN。新离线表只验证 producer，不是旧表 |
| 新模型一定不会再未知/重复引用 | 尚未真实调用；UNKNOWN，严格拒绝仍必要 |

五个短页别名发生在 DPR 第 13 页，以及 RAG 第 1、16、17、19 页；不是针对这些页硬编码补丁。
两次输入的已有 evidence/observations 均为 0，没有发现上一轮模型引用被带进该项目的证据。
Schema 的非空字符串约束不等于注册表成员约束；后者仍在 host 查表执行。这是两层检查，不是取消身份校验。

## 最小改动与安全性

生产文件共五个，沿用现有模块：

| 文件 | 改动 |
| --- | --- |
| src/comparison_workspace/domain/models.py | ValidationDiagnostic 新增可选枚举 handle_issue；旧记录缺字段为 null，不猜测旧原因 |
| src/comparison_workspace/providers/evidence_handles.py | 保留 evidence_handle_identity rule，区分 UNKNOWN_HANDLE / DUPLICATE_HANDLE；只记录安全枚举与字段路径；单块页只在页级声明 handle，块文本保留且块 handle=null |
| src/comparison_workspace/providers/openai_provider.py | 共享提示词明确单块页规则、只复制本请求 handle、整页/块避免冗余；EvidenceReference schema description 同步解释唯一引用要求 |
| web/comparison-workspace/src/App.tsx | 失败提示/历史显示已发送、服务报告 input/output tokens、未入库与下一步；旧合并诊断显示 UNKNOWN；费用以账单为准 |
| web/comparison-workspace/src/types.ts | 可选 handle_issue 类型，与后端合同一致 |

其余为五个测试文件和两份协议/使用文档，共 12 个实现/验收文件；另有本报告。
测试文件：test_comparison_workspace_identity.py、test_comparison_workspace_spans.py、
test_comparison_workspace_s1_diagnostics.py、mock_live_server.py、web/.../tests/live-ai.spec.ts。
文档：EVIDENCE_SPAN_PROTOCOL_V0.md、PRODUCT_GUIDE.md。

DeepSeek 继续复用共享 resolver/schema/提示；其 adapter、SDK retries、预算、Live 授权未改。
source ownership、active-result guard、page hash、offset、精确 quote locator、单条引用上限均未改。
未知/伪造/跨请求引用继续 UNKNOWN_HANDLE 拒绝；同候选重复继续 DUPLICATE_HANDLE 拒绝；跨论文仍在
原 ownership guard 拒绝。不同合法 span 可来自同页，不同候选可复用同一来源。

只消除**输入中的别名重复声明**，没有去重模型输出。选择整页仍能保留表头、单位、脚注；多块页及
长页短块仍可引用。LOCATED 不升级为科学支持或 HUMAN_CONFIRMED。

仅优化 Prompt 不能提供确定性保证；只增加诊断不能消除已证实的重复展示，因此采用二者加极小声明改动。
未引入动态 enum 全表 schema、重试、检索或新架构；没有依据不完整日志猜测具体错误 handle。

## 真实输入离线控制与回归

从 Revision 3 保存的输入构造独立 host 控制，比较冻结 producer 与本次 producer；随机 handle 值不跨请求比较，
比较其 paper/source/page/page hash/offset/quote hash 绑定集合。没有写回原项目或伪装成未来模型选择。

| 离线控制 | 结果 |
| --- | --- |
| 页面 / 注册项 | 32 页；86 → 86 个合法来源绑定 |
| 非空 handle 声明次数 | 91 → 86；每个注册项恰好声明一次 |
| 页面全文、来源/offset/quote hash 集合 | 完全相同 |
| 全部来源 host 控制 | 86 条均 LOCATED；仅来源控制，不是科学结果或真实模型输出 |
| papers 子 payload JSON 字符 | 138849 → 138674（-175） |

其他提示词/schema description 有少量新增文字；不能用上述子 payload 字符变化冒充总请求 token、费用
或模型质量改进。没有进行新的 tokenizer/真实用量测量。

| 验证 | 结果 |
| --- | --- |
| 定向离线回归 | 120 tests，PASS，0 skip，15.904 秒；网络 socket guards、SDK mock |
| 完整离线 unittest（clean 代码提交上一次） | 1201 tests，OK，15 条件性 skips，253.525 秒 |
| Basic Gate --skip-tests | PASSED；608 files；0 error / 0 warning |
| Full Gate --skip-tests | PASSED；608 files；0 error / 3 历史 warning |
| TypeScript + Vite build | PASS |
| 真实 Chromium 浏览器回归 | 23/23 PASS，40.5 秒；包含两家 mock extraction 未知/重复/零候选、用量提示、旧诊断 UNKNOWN、三种导出、恰好三次显式 mock 请求且无隐式重试 |
| diff --check | PASS |
| 历史与用户保护 | 191 份旧科研材料哈希不变；用户数据库与六个源 PDF 共 7 个文件哈希不变，两次 Run state hash 不变 |

首轮定向有一个历史诊断比较因新增可选 null 字段失败；按 ValidationDiagnostic 解析旧快照后逐字段
比较并额外断言 handle_issue=None。原 fixture 未改，身份拒绝断言未删，后续 120 项全部通过。
Full 的三项 warning 为原 W1 CSV、19 个历史 annotation ID、旧 tracked experiment；未改历史材料。

S1-A 保存的成功 extraction/analysis canonical 提议、quote、来源、语义字段离线回放通过。
旧 S1-B 六证据仍 2 LOCATED / 4 INVALID，E3 错页与 E6 历史 different 不获救回；span live 原五证据仍
LOCATED，第 6 页未被原 Run 引用事实不变；长页 caveat 仍只作为独立 host control。均不是新增真实实验。

## 下一次真实 Extraction 建议

**可在新明确授权后安排最多一次受控观察，但不建议把本轮当成已找到/修复历史具体生成根因。**
依据是来源覆盖不变、重复展示已消除、安全诊断补全、离线及浏览器回归通过；不能保证模型不再违规。
本轮没有该调用授权，也没有执行任何连接探针、生成、fallback、Analysis 或第三论文族。

下一次前提与停止条件：

1. 明确授权一次生成；安装并冻结本地修复版本，重建前端、重启自己的后台；不能仅看已发布 3b3b984 分支。
2. 核对同两篇 PDF/source hash/32 页、DPR/RAG NQ EM 问题与 scope，不带入天文问题或预设正确答案。
3. 沿用 deepseek-flash、extraction none/12000；执行前另核对当时模型合同、输入预算和公开价格，使用自己的 Key。
4. 一次请求，SDK/HTTP 不重试，无连接探针/fallback；超时或结果不明也算已消耗尝试。只保留安全诊断、usage、Run ID，
   不保存 Key、认证头、完整原始响应或 reasoning；不因诊断改进增加原始响应留存。
5. incomplete、schema/handle/ownership/source 错误、零候选或关键目标错误立即停止；不删引用、不猜 ID、不再生成。
6. 技术通过后逐项审阅 NQ 数据/EM 定义、模型配置、检索、训练与评价条件和原文；不能把定位成功当成受控性能提升。
   本轮不进入 Analysis，后续也须另有明确授权。

仓外 dpr_rag_handle_failure_20261010 保存源码控制脚本、受限元数据/哈希核验和测试日志；不提交用户数据库、PDF、
原始响应或本机路径。本次交付仅本地诊断/声明与体验修复，已发布 Team Preview 未由本轮更新。
