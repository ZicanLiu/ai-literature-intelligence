# 后续路线图

v0.2.0 只完成文献获取、清洗、严格去重、初步排序和结构化输出。W2 已进一步加入领域查询、OpenAlex v2 分页与重试、两级去重、TF-IDF 两阶段排序、离线评价和质量门禁；Unified Pipeline 与 Batch Runner 已随 v0.3.0 进入 `main`。W4 当前开始试运行评价基准和人工 Query Relevance 协议。

当前状态以 [`CURRENT_STATUS.md`](../CURRENT_STATUS.md) 为准，详细交接见
[`AI_PROJECT_ONBOARDING.md`](AI_PROJECT_ONBOARDING.md)。下列内容均为尚未实现或尚未完成验收的方向。

## 近期工程方向

### 1. 人工去重结论应用

当前 suspected duplicate 只进入人工复核队列，不自动删除。后续需要明确 confirmed/distinct 决策的数据契约、应用方式、审计记录和回滚边界。

### 2. Metadata fusion

当前 exact dedup 只合并 provenance，不融合标题、作者、摘要或来源等元数据。后续应先定义字段优先级和冲突报告，再决定是否实现。

### 3. 人工评价 benchmark

现有 W2 labels 仍有 AI-assisted draft 和待抽查映射，不是正式 gold ground truth。后续需要人工复核、扩大样本、版本化标注规范，并记录覆盖率。

### 4. v0.3 持久化和可视化

Unified Pipeline 当前以 JSON/CSV 为主，尚未实现 W2/v0.3 SQLite schema 和排序可视化。新增时应保留阶段字段、provenance 和 run 级复现信息。

### 5. 更大规模 live 验证

当前只完成小规模 live 验证。更大规模或 6/6 domain query 验证应作为独立实验，明确请求预算、配置、数据安全和验收指标。

## 排序研究方向

当前 `preliminary_score` 和 TF-IDF two-stage 都是可解释 baseline。后续可以在同一 benchmark 和同一评价口径下比较：

- BM25；
- semantic embedding；
- lexical + semantic hybrid ranking；
- learning-to-rank。

这些方法目前都未实现。不能把 TF-IDF 表述为语义理解，也不能在没有公平对照的情况下声称新方法更优。

## 数据与科研分析方向

- Crossref DOI 二次校验；
- 摘要中的研究对象、方法、数据集和指标抽取；
- 特定天体或研究任务的文献整理；
- 年份演化、引用网络和关系图谱；
- 带来源证据、可人工复核的 LLM 辅助分析报告；
- 多领域主题配置。

## 暂不纳入当前 Pipeline

- PDF 全文下载与解析；
- Web 前端；
- RAG；
- 多 Agent 或 LangGraph；
- 知识图谱生产系统。

这些方向需要新的需求、安全和数据授权评审，不应为了增加功能数量直接塞进当前 Unified Pipeline。
