# W4 Blind AI Audit

本目录保存 W4 60 个 query-paper pair 的独立 blind AI 质量审计与后续 human comparison。
它是 evidence/review artifact，不是 approved benchmark，也不自动修改任何 human label。

## Artifact 顺序与冻结规则

1. `blind_ai_audit_v0.1.csv` 在读取任何 human label、judgement、proposal、agreement 输出或
   per-pair 排名信号之前完成；其 SHA-256 固定在 `manifest_v0.1.json`。
2. `human_ai_comparison_v0.1.csv` 只在 Blind Phase 冻结后生成，逐条记录与当前 human
   judgement 的比较结果。
3. `review_queue_v0.1.csv` 只包含需要人工处理的 6 条；初始 reviewer 字段全部为空。
4. `comparison_summary_v0.1.json` 固定 comparison、review queue、blind audit 和 parent
   draft manifest 的 hash，并记录当前尚未具备 benchmark promotion 条件。

Blind Audit 的原始 `ai_label`、`confidence`、`reason` 和 evidence 字段不得因后续看到 human
答案而覆盖。若后续需要评论 AI 判断，只能在 review/adjudication 层追加记录。

## 当前人工工作

人工 reviewer 需要逐条处理 `review_queue_v0.1.csv`，填写：

- `reviewer_decision`
- `reviewer_final_label`
- `reviewer_note`
- `reviewer`
- `reviewed_at`

其中 `reviewed_at` 应为带时区的 ISO-8601 时间。AI 证据只能辅助 reviewer，不能自动成为
final label。六条全部完成且现有 provenance/approval checklist 复核完成后，才可新建不含
`draft` 后缀的 **W4 Pilot Adjudicated Judged Set** approved package。
