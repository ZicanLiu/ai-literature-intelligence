# 当前项目状态

更新时间：2026-08-10

最新公共基线：`899f745`（tag `v0.3.0`）

当前公共准备分支：`chore/w4-benchmark-bootstrap`

W2 Unified Pipeline 与 Batch Runner 已进入 `main`。本页新增的 W4 bootstrap 尚未合并
`main`，当前状态是评价基准与 Pilot Annotation 的公共前置准备，不是已完成 benchmark。

## AI / 新成员接手入口

开始新任务前，先阅读根目录 [`AGENTS.md`](../AGENTS.md) 和
[`AI_PROJECT_ONBOARDING.md`](project/AI_PROJECT_ONBOARDING.md)，再以当前 Git 状态、源码、
测试和 Issue 核对本页快照。

W4 任务继续阅读：

- [`W4_RESEARCH_PLAN.md`](project/W4_RESEARCH_PLAN.md)
- [`W4_ANNOTATION_GUIDELINE.md`](project/W4_ANNOTATION_GUIDELINE.md)
- [`data/annotation_tasks/w4/README.md`](../data/annotation_tasks/w4/README.md)

## 当前稳定工程基础

`main` 已包含 OpenAlex v2 分页/重试、领域查询、W2 两级去重、TF-IDF 两阶段排序与评价、
Unified Pipeline、Batch Runner 和 Quality Gate。旧 `python -m app.main` 继续作为 v0.2.0
兼容 baseline。

Unified Pipeline 支持多 acquisition query、清洗后 provenance、跨 query exact dedup、
不自动删除的 suspected review queue、显式 ranking keyword、旧 baseline 与 two-stage 排序、
可选 judged 评价及阶段化输出。

`preliminary_score` 和 TF-IDF 都是透明、可解释的项目 baseline，不代表论文真实学术价值
或语义理解，也不能替代人工阅读。

## W4 当前目标

W4 从工程集成转向：

- 把研究方向写成可执行的 research questions；
- 区分 Query Relevance、Value Profile 和 Reading Priority；
- 建立不依赖人工答案的 Pilot Candidate Pool；
- 试运行独立双标、证据分级和 AI 使用记录；
- 为后续 agreement、分歧裁决和公平排序实验准备数据接口。

本周不实现 BM25、Embedding、SPECTER、BERT、RankNet、LambdaMART、LLM Reranker、
Knowledge Graph 或大型多指标评价系统。

## W4 Pilot v0.1 数据状态

- 来源：`data/samples/w2/domain_query/live_query_sample.csv`；
- 三个 research query 分别映射 q02 classification、q03 parameters、q04 preprocessing；
- 每个 research query 有 20 个 query-paper pair，共 60 pair；
- 60 pair 对应 57 篇唯一 OpenAlex work；同一论文可因 query-dependent relevance 进入不同 RQ；
- pool 由 top/middle/bottom/rank-shift 四个 bucket 各 5 条组成；
- 选择只使用 retrieval provenance 和当前 baseline/two-stage ranking，没有读取人工 label；
- 本次没有新增 OpenAlex live 请求；
- manifest 已记录来源、Git revision、选择规则、计数和 SHA-256。

当前目录是 `data/annotation_tasks/w4/`，表示待人工判断任务，不是
`data/manual/w4_benchmark/`，也不使用 gold/ground truth 命名。

## Assignment 与个人任务

- 60 pair 全部有 primary；
- 30 pair 有一个独立 secondary；
- 共 90 次 assignment，六人各 15 条；
- 三个 research query 各有 10 个 secondary overlap；
- 没有第三标注者，primary 与 secondary 不相同；
- 个人任务不显示分数、排名、引用信号、selection bucket、assignment role 或旧标签；
- generator 默认拒绝覆盖，validator 只检查格式和数据契约，不判断标签正确性。

个人结果尚未生成或合并。agreement、Kappa、分歧裁决及新 benchmark 排序评价也尚未实现。

## 当前验证

- W4 定向自动测试：10 项通过；
- 全量自动测试：214 项，214 通过、0 失败、0 error、0 skipped；
- Basic Quality Gate：0 error / 0 warning；
- Full Quality Gate：0 error / 3 个既有历史 warning；
- W4 Candidate Pool、assignment 和个人任务不变量均由自动测试覆盖；
- 所有测试使用本地 fixture 或已提交样例，没有网络请求。

Full Gate 的三个历史 warning：

1. W1 标注保留一处 CSV 结构问题；
2. `data/manual/relevance_labels_w1.csv` 有 19 个 ID 未与当前统一样例对齐；
3. 历史已跟踪 experiment `openalex_stellar_spectra_60`。

本次没有修改这些历史交付物，也没有新增 W4 error。

## 当前明确不包含

- 正式大规模 benchmark、gold standard 或专家标注集；
- 完成后的六人个人标签；
- agreement 指标和 disagreement adjudication；
- 使用新 Pilot label 比较 baseline 与 two-stage；
- confirmed duplicate review 应用、metadata fusion、SQLite v0.3 schema；
- BM25、Embedding、LTR、PDF 解析、RAG、多 Agent、知识图谱或前端。

## 下一步

1. 评审并合并 W4 bootstrap；
2. 为六名成员建立独立 W4 Issue 和分支边界；
3. 每人生成自己的 15 条任务，完成主任务和 Query Relevance 标注；
4. 各 PR 通过个人 validator、自动测试和人工审查；
5. 所有个人结果合并后，另开公共任务处理 agreement、裁决和 benchmark 提升。
