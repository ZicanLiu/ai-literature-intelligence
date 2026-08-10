# W4 Pilot Annotation 公共数据

本目录保存 W4 Pilot v0.1 的待人工判断任务池和均衡双标分配，不是人工 ground truth。

## 公共文件

- `candidate_pool_v0.1.csv`：三个 research query 各 20 个 query-paper pair；
- `assignments_v0.1.csv`：60 primary + 30 secondary，共 90 次分配；
- `pool_manifest_v0.1.json`：来源、选择规则、Git revision、计数和 SHA-256；
- `annotation_template.csv`：个人标注 CSV 的固定空表头；
- `annotations/README.md`：个人结果的分支协作规则。

研究问题和标注口径见：

- [`W4_RESEARCH_PLAN.md`](../../../docs/project/W4_RESEARCH_PLAN.md)
- [`W4_ANNOTATION_GUIDELINE.md`](../../../docs/project/W4_ANNOTATION_GUIDELINE.md)
- [`research_queries.json`](../../../configs/w4/research_queries.json)

## 数据来源与冻结

Candidate Pool 只来自既有真实 OpenAlex 样例
`data/samples/w2/domain_query/live_query_sample.csv`。选样依据 retrieval provenance 和当前
baseline/two-stage ranking，没有读取 W1/W2 relevance labels、AI-assisted labels 或 hard
negative 人工判断，也没有新增 live 请求。

v0.1 已冻结。需要修改候选或 research query 时必须建立新版本，不能静默覆盖。

## 六人任务命令

| 成员 | slug | 生成命令 |
| --- | --- | --- |
| 刘子璨 | `liuzican` | `python -m app.create_annotation_task --annotator liuzican` |
| 武子恒 | `wuziheng` | `python -m app.create_annotation_task --annotator wuziheng` |
| 贾馥诚 | `jiafucheng` | `python -m app.create_annotation_task --annotator jiafucheng` |
| 陈星妤 | `chenxingyu` | `python -m app.create_annotation_task --annotator chenxingyu` |
| 黄斌 | `huangbin` | `python -m app.create_annotation_task --annotator huangbin` |
| 蒲正杰 | `puzhengjie` | `python -m app.create_annotation_task --annotator puzhengjie` |

每条命令只生成该成员被分配的 15 条，不生成其他人的空白结果，也不会显示 assignment
role、selection bucket、分数、排名、引用信号或旧标签。

## 完成后验证

```powershell
python -m app.validate_annotation_task `
  --file "data/annotation_tasks/w4/annotations/<slug>.csv"
```

成员只提交自己的 `annotations/<slug>.csv` 和 Issue 明确允许的主任务文件。不得修改：

- `candidate_pool_v0.1.csv`；
- `assignments_v0.1.csv`；
- `pool_manifest_v0.1.json`；
- `configs/w4/research_queries.json`；
- 其他成员的 annotation CSV。

六人分别在独立分支新增自己的文件，因此不会共同编辑 candidate pool，也不会产生同一个
个人 CSV 的正常协作冲突。
