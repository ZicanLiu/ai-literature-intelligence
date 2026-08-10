# 当前项目状态

更新时间：2026-08-10

稳定基线：`52041a6`（tag `w2-stable-20260808`）

Issue #21 开发分支：`feat/w2-unified-pipeline`

本页所述统一集成修改仍未 commit、未合并 `main`，v0.3.0 尚未正式发布。

## AI / 新成员接手入口

开始新任务前，先阅读根目录 [`AGENTS.md`](../AGENTS.md) 和
[`AI_PROJECT_ONBOARDING.md`](project/AI_PROJECT_ONBOARDING.md)，再以当前 Git 状态、源码、测试和 Issue 核对本页快照。

## 当前已验证范围

`main` 已包含 OpenAlex v2 分页/重试、领域查询、W2 两级去重、TF-IDF 两阶段排序与评价、
质量门禁。旧 `python -m app.main` 继续作为 v0.2.0 baseline，支持 mock/live 获取、清洗、
严格去重、`preliminary_score`、CSV、SQLite、图表和摘要。

本分支新增统一 Pipeline：一个 parent run 可选择多组 acquisition query，清洗后附加来源，
跨 query 精确去重并合并 provenance，再用显式 `ranking_keyword` 完成旧 baseline 与两阶段
排序。疑似重复只进入 review queue，不自动删除。Batch Runner 复用同一 API 运行多个
独立 parent run。

`preliminary_score` 和 TF-IDF 都是透明、可解释的项目 baseline，不代表论文真实学术价值
或语义理解，也不能替代人工阅读。

## 数据与评价状态

- `data/samples/openalex_stellar_spectra_100.csv` 是 100 条 OpenAlex live 统一样例；
- W1/W2 成员样例、分析、报告和历史 experiments 均保持原样；
- W2 label CSV 共 50 行，其中 37 行来自原 PR 人工判断映射，13 行是
  `AI-assisted-draft` 且待人工复核；统一 Pipeline 默认排除后 13 行；
- 默认可用的 37 行仍标记“结构字段待组长抽查”，正式科研结论前需要继续核验；
- 未标注论文不会被自动当作不相关，labels 只进入 judged 离线评价，不进入评分公式。

## Issue #21 验证

- 离线 E2E：2 queries，combined 8、exact 2、kept 6、suspected 1、ranked 6；
- 小规模 live：`q02_classification`、`q03_parameters` 各 20 条，combined 40、exact 1、
  kept/ranked 39、suspected 0；
- live 两次请求各 1 页、无重试；输出完整，未发现 Key 赋值文本或个人绝对路径；
- Batch 示例包含 3 个 offline item，每项产生独立 run；失败继续与停止策略均有自动测试；
- live batch 另以 2 个 item、每项 10 条完成验收，两项均成功；临时配置未保留；
- 自动测试共 204 项，204 通过、0 失败、0 error、0 skipped；Basic Gate 为
  0 error / 0 warning，Full Gate 为 0 error / 3 个已知历史 warning。

## 输出状态

旧 v0.2 run 使用 `raw/tables/figures/reports/data` 结构；统一 Pipeline 使用
`domain/retrieval/dedup/ranking/evaluation/reports` 结构，所有路径和实际参数写入
`run_config.json`。三个 provenance list 在 CSV 中使用 JSON array string，能够无损恢复。

普通 `outputs/experiments/` 和 `outputs/batches/` 默认忽略。本次 live/offline 验证只创建新
目录，没有覆盖或提升为 baseline。

## 当前明确不包含

本分支没有实现 confirmed review 应用、metadata fusion、SQLite v0.3 schema、排序图表重做、
6/6 query 大规模 live、BM25、Embedding、LTR、PDF 解析、RAG、多 Agent、知识图谱或前端。
v0.3.0 当前只是候选状态，必须经过人工 diff 评审、提交并合并后才能发布。

## 下一步

1. 人工查看 Pipeline/Batch Runner 的配置、provenance 和失败状态实现；
2. 对 37 条映射标签完成组长抽查，另开 Issue 处理 13 条 AI-assisted draft；
3. 决定是否把本次小规模 live run 提升为受控 evidence（默认不提交）；
4. 把 metadata fusion、review decision 应用和 SQLite 升级拆成独立 P1 Issue。
