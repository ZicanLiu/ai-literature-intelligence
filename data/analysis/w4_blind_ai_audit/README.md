# W4 Blind AI Audit

本目录保存 W4 60 个 query-paper pair 的独立 blind AI 质量审计与后续 human comparison。
它是 evidence/review artifact，不自动修改任何 human label。六条 review queue 已由独立人工
reviewer 确认，结果进入 `w4_query_relevance_pilot_v0.1.0` approved package。

## Artifact 顺序与冻结规则

1. `blind_ai_audit_v0.1.csv` 在读取任何 human label、judgement、proposal、agreement 输出或
   per-pair 排名信号之前完成；其 SHA-256 固定在 `manifest_v0.1.json`。
2. `human_ai_comparison_v0.1.csv` 只在 Blind Phase 冻结后生成，逐条记录与当前 human
   judgement 的比较结果。
3. `review_queue_v0.1.csv` 只包含需要人工处理的 6 条；初始 reviewer 字段为空，现已记录完整
   decision、final label、reviewer、带时区时间和说明。
4. `comparison_summary_v0.1.json` 固定 comparison、review queue、blind audit 和 parent
   draft manifest 的 hash，并记录 human review 与 benchmark promotion 结果。

Blind Audit 的原始 `ai_label`、`confidence`、`reason` 和 evidence 字段不得因后续看到 human
答案而覆盖。若后续需要评论 AI 判断，只能在 review/adjudication 层追加记录。

## Human review 结果

六条均已完成：

- `w4_rq02_013`：`0`（modify）
- `w4_rq03_005`：`0`（modify）
- `w4_rq03_006`：`0`（approve）
- `w4_rq03_007`：`1`（modify）
- `w4_rq03_009`：`0`（approve；由非原 annotator `huangbin` 独立复核）
- `w4_rq03_011`：`0`（approve）

AI 证据只作为辅助，最终 label 来自记录在 review queue 和 approved judged set 中的人工
决定。Approved package 位于 `data/benchmarks/w4_query_relevance/v0.1.0/`，正式名称仍为
**W4 Pilot Adjudicated Judged Set**。
