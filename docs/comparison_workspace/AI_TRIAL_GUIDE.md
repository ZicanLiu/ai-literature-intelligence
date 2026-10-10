# 可选 AI 体验：一次提取，审阅后再决定分析

目的：体验真实论文候选、证据与比较草稿，不是正式 benchmark 或提供方排名。可只交离线反馈。
Live 使用本人 Key、发送许可和可承担的费用；此文档不授权 AI Agent 自动调用。
先按 [团队指南 B](TEAM_PREVIEW.md#b-live-模式使用本人-api可选) 启动并明确启用 Live。

## 推荐公开材料

从原站下载固定版本到自己的资料目录，不提交论文到 Git：

- [DPR：Dense Passage Retrieval for Open-Domain Question Answering，v3](https://arxiv.org/abs/2004.04906v3)
  · [PDF](https://arxiv.org/pdf/2004.04906v3)，2004.04906v3.pdf，预期 13 页。
- [RAG：Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks，v4](https://arxiv.org/abs/2005.11401v4)
  · [PDF](https://arxiv.org/pdf/2005.11401v4)，2005.11401v4.pdf，预期 19 页。

上传后核对版本、页数、解析状态；有差异则记录，不伪装成相同输入。
也可用自己有权发送的其他论文，但不是 DPR/RAG 的重复验证。

## 可复制的研究问题

> 比较 DPR 与 RAG 在 Natural Questions 开放域问答测试集上报告的端到端 Exact Match（EM）结果。
> 分别记录具体模型变体、训练设置、检索方式、阅读器或生成器及评价条件，判断这些报告数字能否直接比较。
> 不得把不同设置下的数字差解释为受控性能提升；缺少来源支持的条件保留未知。

scope 可填“仅本次两篇固定版本；区分主实验、消融实验和架构说明；记录未决条件”。
不要把历史审计答案、失败输出或本指南检查清单当作论文内容粘入模型输入。

## 一次 Extraction 与本人审阅

1. 选一个提供方和模型，记录参数及本人预算。DeepSeek 按操作默认提取 none/12000、分析 high/32000；
   OpenAI 两阶段输出上限 12000，思考由服务默认。实际兼容、可用额度与费用由本人核对；预算不是美元上限。
2. 点一次提取并等待，记录安全 Run ID、requested/reported model、provider/Run 状态、reasoning effort、
   输出预算、input/output/reasoning tokens（未提供填 UNKNOWN）与耗时。
3. 预览候选摘要和实验身份，选择性能实验；不能仅按论文标题，不能把架构、训练配置或数据介绍当作 EM 结果。
4. 展开完整引文，回 PDF 核对列头、单位、脚注和评价对象；分别记录“来源定位 / 本人是否核查支持 / 仍未知什么”。

| 科学核查重点 | 避免的混淆 |
| --- | --- |
| DPR 端到端 QA EM，Table 4 的训练/模型/数据集行 | 检索 top-k accuracy 不是问答 EM；Single/Multi、主实验与 joint ablation 不混用 |
| RAG 的 Table 1、模型变体与 NQ 列 | RAG-Token / RAG-Sequence 不是同一个结果；不从混合候选中无说明地取数字 |
| 训练/推理检索文档数、reader/generator、解码与开发集选择 | 相似 k 或组件名不证明条件相同；训练和测试设置须分开 |
| EM 定义、评价 split、样本与结论范围 | 同名指标不自动等于同协议；报告数值差不证明受控提升 |
| 原文、页码、表头、脚注和 caveat | 合法 handle 与 LOCATED 仍可能对应不支持主张的片段 |

若一个候选混合多个变体，先用有来源、有理由的手工结果/Correction 明确目标，或保留 UNKNOWN 并暂停。
修订不自动成为 Human Gold；不补造证据、隐藏无效引用或强行确认条件。

## 可选的一次 Analysis 与停止条件

仅在目标清楚、必要来源可审阅且本人愿意继续付费时考虑。运行前检查问题、活动 Result、实验身份、来源、
参数和未决条件；返回不生成。确认后逐条检查 Observation / Finding 引用的结果/论文、原文支持与未知保留。
provider completed、本地 COMPLETED、全部 LOCATED 或 AI 自审，都不是科学确认。

incomplete、schema、UNKNOWN_HANDLE / DUPLICATE_HANDLE、ownership/source 错误、关键目标错误或必要证据
无法审阅时停止。超时、网络异常或结果不明也可能已发送；不要默认重试、更换模型救回。
记录安全分类即可，不要求完整响应、reasoning 或认证信息。即使成功，也不证明稳定性。

## 交回什么

按 [反馈模板](TEAM_FEEDBACK_TEMPLATE.md) 分开填写安装/离线、Live 技术结果、科学质量和交互建议。
记录实际尝试次数（包括发送后失败）、阶段/参数/tokens、候选与来源状态、是否误选目标、错误分类及本人发现。
可填“未进行 Live”，无需为了反馈再付费。导出留在本机，反馈只提供脱敏摘要或安全截图，
不附 Key、私人 PDF、数据库、完整提取文本或完整模型响应。
