# 组长 W2 统一集成技术记录

记录日期：2026-08-10

集成基线：`52041a6`（`w2-stable-20260808`）

开发分支：`feat/w2-unified-pipeline`

## 做了什么

五个 W2 PR 在 `main` 中各自可运行，但入口仍彼此独立。本次没有重写算法，而是增加
`src/pipeline.py` 和 `app/run_pipeline.py`，把领域查询、OpenAlex v2、清洗、两级去重、
旧 baseline、TF-IDF 两阶段排序和可选评价组织为一个 parent run；随后增加 Batch Runner
复用同一 API。提交前审计进一步把纯排序逻辑提取到 `src/ranking.py`，CLI 继续兼容导出
原有函数名，消除了 `src` 对 `app` 的反向依赖。

集成时确认了三个真实接口问题：

1. `clean_single_paper()` 会重建固定字段，所以 provenance 必须在清洗后附加；
2. W2 exact 原本 first-seen wins，不会合并多 query 来源；现增加默认关闭的
   `merge_provenance` 选项，旧调用不变；
3. v0.2 CSV writer 使用固定旧表头，会丢 W2 字段，因此统一 Pipeline 使用专用 writer，
   没有改动旧 storage/SQLite baseline。

## 已完成验证

- 离线 parent run：2 queries、combined 8、exact 2、kept 6、suspected 1、ranked 6；
- live parent run：`q02_classification` 与 `q03_parameters` 各 20 条，combined 40、
  exact 1、kept/ranked 39、suspected 0；两次请求均成功且无重试；
- Batch Runner 的 3 个 offline item 和 2 个 live item 均成功，子 run 相互独立；
- 输出声明文件全部存在；最终 live CSV 为 39 行、30 列；
- live 输出未发现 API Key 赋值文本或个人绝对路径；
- 自动测试 204/204 通过（0 failed、0 error、0 skipped）；
- Basic Gate 为 0 error / 0 warning；Full Gate 只有 3 个已知历史 warning。

本次没有修改历史 W1/W2 fixture、人工标签、baseline、成员 evidence 或旧实验。

## 尚未做

没有应用 confirmed review decision、metadata fusion、SQLite v0.3 schema、排序可视化重做、
6/6 query 大规模 live、BM25/Embedding/LTR，也没有把 13 条 AI-assisted draft 当作正式
ground truth。这些应拆成后续 Issue。
