# 第二周相关性标注说明

## 文件和字段

正式标注文件是 `data/manual/relevance_labels_w2_baseline.csv`，共 50 条。主要字段包括：

- `annotation_id`：本批唯一标注编号；
- `openalex_id`：真实且可追溯的 OpenAlex Work ID；
- `source_query_ids`：来源查询或统一样例批次；
- `label`、`reason`：标签和逐条理由；
- `object_type`、`task_type`：结构化研究对象和任务；
- `matched_positive_terms`、`matched_negative_terms`：词典匹配证据；
- `evidence_source`：能够找到该 OpenAlex ID 的仓库相对路径；
- `annotator`、`review_status`：判断来源及复核状态。

允许的标签只有：`高度相关`、`部分相关`、`不相关`、`待讨论`。

## 当前数量与来源

| 项目 | 数量 |
| --- | ---: |
| 总标注 | 50 |
| 高度相关 | 24 |
| 部分相关 | 1 |
| 不相关 | 23 |
| 待讨论 | 2 |
| 原 PR 人工判断按标题映射到真实 OpenAlex ID | 37 |
| AI-assisted-draft、待人工复核 | 13 |

原 PR 的 50 行包含具体标题和理由，但 OpenAlex ID 是 `W1`—`W50` 占位符。此次只保留了
能够与 `data/samples/openalex_stellar_spectra_100.csv` 精确匹配标题且 OpenAlex ID 不重复
的 37 条原判断；原始标签 `1` 映射为“高度相关”，`0` 和 `-1` 映射为“不相关”。结构化
对象、任务和命中词由程序辅助补齐，状态明确标为待组长抽查。

另外 13 条来自本次 live 样例，编号为 `w2_ann_038`—`w2_ann_050`。这些判断由
AI 根据标题、摘要和领域词典给出建议，`annotator=AI-assisted-draft`、
`review_status=待人工复核`，不得表述为陈星妤已经确认的人工标签。

## 标签口径

- **高度相关**：对象、数据类型和任务均直接服务于恒星光谱的机器学习处理；
- **部分相关**：至少一个核心环节相关，但对象、数据类型或任务不完全一致；
- **不相关**：只是命中宽泛词，实际研究不属于本项目方向；
- **待讨论**：仅凭当前元数据不能稳定判断，需要阅读全文或由两名标注者讨论。

人工标注存在主观性。遇到对象边界、测光与光谱混用、星震与光谱参数估计等情况时，
应保留“待讨论”，不能为了凑齐正负样本强行归类。

## Hard negative

`data/manual/hard_negative_cases_w2.csv` 保存 12 条真实、可追溯困难负例。它们包括星系
光谱、太阳物理、空间天气、星系暗晕、成像分类和非天文机器学习等误召回类型。每条均
来自统一 100 条样例，并保留原 PR 的逐条理由和标注者来源。困难负例用于发现查询规则
为什么误召回，不能只按“标题出现 spectrum/stellar”自动判定相关。

## 提交前人工复核

组长至少应逐条检查：

1. `w2_ann_038`—`w2_ann_050` 的建议标签和理由；
2. 37 条映射记录的 `object_type`、`task_type` 和词项匹配字段；
3. 12 条 hard negative 是否符合本项目“恒星光谱数据处理”边界。
