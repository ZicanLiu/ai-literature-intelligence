# 文档索引

这里按用途整理项目文档。第一次进入仓库时，建议先阅读根目录
[`AGENTS.md`](../AGENTS.md)、[`README.md`](../README.md)、
[`AI 项目交接文档`](project/AI_PROJECT_ONBOARDING.md) 和
[`CURRENT_STATUS.md`](CURRENT_STATUS.md)。

## 项目说明

- [AI 项目交接与开发入口](project/AI_PROJECT_ONBOARDING.md)：组员和 AI Agent 接手最新代码时的详细项目上下文与开发入口
- [架构与数据流](project/architecture.md)
- [代码阅读与学习指南](project/learning_guide.md)
- [后续功能路线](project/future_roadmap.md)
- [2026 年暑期推进计划](project/SUMMER_PLAN_2026.md)
- [原始项目要求（历史基线）](../project_requirements.md)

## 协作规范

- [贡献指南](../CONTRIBUTING.md)
- [团队 Git 协作指南](collaboration/TEAM_GIT_GUIDE.md)

## 第一周报告

- [第一周工作总结](reports/week1/WEEKLY_REPORT_20260725.md)
- [第一周组会提纲](reports/week1/MEETING_BRIEF_20260725.md)
- [OpenAlex 字段审计](reports/week1/OPENALEX_FIELD_AUDIT_W1.md)
- [领域检索词与标注说明](reports/week1/DOMAIN_QUERY_GUIDE_W1.md)
- [初步排序结果分析](reports/week1/RANKING_ANALYSIS_W1.md)
- [第一周补充测试报告](reports/week1/TEST_REPORT_W1_COMPLETED.md)

## 第二周协作

- [第二周成果索引](reports/week2/README.md)
- [第二周文件归属与协作边界](collaboration/W2_FILE_OWNERSHIP.md)
- [第二周数据接口约定](project/W2_DATA_CONTRACTS.md)
- [统一 Pipeline 使用与复现](project/UNIFIED_PIPELINE_GUIDE.md)
- [批量实验指南](project/BATCH_EXPERIMENT_GUIDE.md)
- [组长集成技术记录](reports/week2/LEADER_TECHNICAL_NOTES_W2.md)
- [v0.3.0 候选发布说明](reports/week2/V0.3.0_RELEASE_NOTES.md)

五项成员功能、统一 Pipeline 与 Batch Runner 已进入 `main`，并标记为 v0.3.0。旧
`app.main` 仍保留为 v0.2.0 兼容 baseline。

## 第四周研究评价

- [W4 研究计划：评价基准与实验体系试运行](project/W4_RESEARCH_PLAN.md)
- [W4 Query Relevance 标注指南](project/W4_ANNOTATION_GUIDELINE.md)
- [W4 Pilot Benchmark 收口协议](project/W4_PILOT_BENCHMARK_PROTOCOL.md)
- [W4 Pilot Annotation 公共数据与任务命令](../data/annotation_tasks/w4/README.md)
- [W4 versioned judged-set artifact](../data/benchmarks/w4_query_relevance/README.md)

W4 六人 annotation、Agreement Analyzer、entity/provenance/query-boundary audit 和 evaluator
已进入 `main`。60-pair Blind AI Audit 与独立人工 review 已完成，
`w4_query_relevance_pilot_v0.1.0` 状态为 `approved` 并通过 strict validator；该集合仍不得称为
gold ground truth。

## live 验证

- [2026-07-18 OpenAlex live 测试报告](reports/live/LIVE_TEST_REPORT_20260718.md)

## 当前状态

- [当前仓库与集成状态](CURRENT_STATUS.md)

文档中的未来文件名如果出现在计划章节中，只表示预期交付物，不代表当前已经实现；
当前有效文件以本索引和仓库实际内容为准。
