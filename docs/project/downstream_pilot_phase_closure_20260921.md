# Downstream pilot 阶段收口 — 2026-09-21

## completed

- Engineering：RCP / selection / context infrastructure、PR #81 downstream measurement workbench
  已进入 main；本轮补充 lowercase 路径兼容和 formal-verification fail-closed。
- Formal AI pilot：仓库外 RCP、MCA、24 formal outputs、GPT / DeepSeek / GLM 盲评、agreement、
  pre-unblinding closure/authorization 和 frozen first-look 已完成。
- Evidence reconstruction：24 outputs / 144 claims / 72 primary evaluations /
  432 primary claim-judge units；Full Pro 24 outputs / 144 sensitivity units 完整。
- Measurement diagnosis：独立 first-look 28/28 MATCH，Full Pro sensitivity 与构念拆解已完成。

## not completed

- Original human Gate：`NOT_EVALUABLE`。
- Measurement external validation。
- Broad generalization。
- MCA mechanism attribution。
- Publication-level confirmation。

## current interpretation

本 pilot 仅有两个固定 Topic、三次 repetition，存在明显 evaluator sensitivity。
当前证据不能证明 MCA 更优，也不能证明 evaluator-invariant scientific-quality improvement。
Full Pro 是 post-hoc `SENSITIVITY_EVALUATOR`，不是第四个 primary Judge；
Rubric V2 是 `FUTURE / PROSPECTIVE DRAFT`，没有回溯应用或重评分。

## preservation

已执行最小独立备份：不同物理磁盘上的原字节副本、逐文件 SHA256 回读，以及备份位置的
registry/first-look 验证通过。该备份在同一台电脑内，不声称已完成异地冗余或云端同步。
29 个登记 package（10,086 files / 276,455,443 bytes）只迁移顶层目录至
`MVP/evidence_pilot_202609` 并 lowercase；内部文件名、字节和历史 manifest 不变。

Full Pro ZIP 与下载目录同名成员分别保存；仅 README 冲突经用户授权记录，后续验证使用 ZIP。
此冲突不是 frozen manifest 例外；supplement 仍无 prior immutable trust anchor。
既有空白模板换行符例外保留原分类。原始 evidence、私人备份和本地清理报告均不进入公共 Git。
执行细节见 [preservation plan](EXTERNAL_RESEARCH_EVIDENCE_PRESERVATION_PLAN.md)。

## next decision

Protect V1 blind human review → targeted human reason audit → prospective measurement falsification
→ only then stronger selector comparison。
