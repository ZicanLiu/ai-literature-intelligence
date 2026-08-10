# 个人标注结果

主分支只保留本说明，不预先提交六个半完成的空白结果。每位成员从最新 `main` 创建自己的
W4 分支后，通过 `python -m app.create_annotation_task --annotator <slug>` 只生成自己的
15 条任务，并在同一文件中完成 Query Relevance 标注。

不要查看、修改或复制其他成员的 label。个人文件通过 validator 后随各自 Issue 的 PR
提交；所有 PR 合并后，再由后续公共任务处理 agreement、分歧裁决和 benchmark 提升。
