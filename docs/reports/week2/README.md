# 第二周成果索引

- 计划周期：2026-07-27—2026-08-02
- 组内汇总节点：2026-08-01
- Milestone：第二周检索、数据质量与排序协作

五项成员 PR 已进入 `main`，并在稳定标签 `w2-stable-20260808` 上通过集成验收。组长负责
的 Issue #21 统一 Pipeline 与 Batch Runner 已在独立分支实现并验证，当前等待人工 diff
评审，尚未发布 v0.3.0。

`docs/project/SUMMER_PLAN_2026.md` 是暑期方向初稿；第二周的实际人员分工和路径以已经
发布的 Issue、本页及文件归属表为准。

| 方向 | 负责人 | 代码入口 | 数据目录 | 测试 | 报告 | 当前状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 批量实验与集成 | 刘子璨 | `src/pipeline.py`、`app/run_pipeline.py`、`src/batch_runner.py`、`app/batch_runner.py` | 普通结果在忽略的 `outputs/` | `test_pipeline.py`、`test_batch_runner.py` | `LEADER_TECHNICAL_NOTES_W2.md` | 分支已验证，待评审 |
| OpenAlex v2 | 武子恒 | `src/openalex_client_v2.py`、`app/openalex_fetch_v2.py` | `data/samples/w2/openalex_client/` | `test_openalex_client_v2.py` | `OPENALEX_RETRIEVAL_W2.md` | 已合并 |
| 去重与复核 | 贾馥诚 | `src/deduplication.py`、`app/review_duplicates.py` | `data/review/`、`data/analysis/w2_dedup/` | `test_deduplication.py` | `DEDUPLICATION_W2.md` | 已合并 |
| 领域查询与标注 | 陈星妤 | `src/domain_query.py`、`app/build_domain_queries.py` | `data/domain/`、`data/manual/` | `test_domain_query.py` | `DOMAIN_QUERY_SET_W2.md` | 已合并 |
| 质量门禁 | 黄斌 | `src/validation.py`、`app/quality_gate.py` | `data/samples/w2/quality_gate/` | `test_quality_gate.py` | `TEST_REPORT_W2.md` | 已合并 |
| 两阶段排序 | 蒲正杰 | `src/text_relevance.py`、`src/evaluation.py`、`app/evaluate_ranking.py` | `data/analysis/w2_ranking/` | `test_text_relevance.py`、`test_evaluation.py` | `TWO_STAGE_RANKING_W2.md` | 已合并 |

## 集成与复现入口

- [第二周文件归属与协作边界](../../collaboration/W2_FILE_OWNERSHIP.md)
- [第二周数据接口约定](../../project/W2_DATA_CONTRACTS.md)
- [统一 Pipeline 使用与复现](../../project/UNIFIED_PIPELINE_GUIDE.md)
- [批量实验指南](../../project/BATCH_EXPERIMENT_GUIDE.md)
- [组长集成技术记录](LEADER_TECHNICAL_NOTES_W2.md)
- [v0.3.0 候选发布说明](V0.3.0_RELEASE_NOTES.md)
- [贡献指南](../../../CONTRIBUTING.md)

表中“分支已验证”不等于已经进入 `main`。合并前仍需检查完整 diff、全量自动测试、
Basic/Full Quality Gate 和 `git diff --check`。
