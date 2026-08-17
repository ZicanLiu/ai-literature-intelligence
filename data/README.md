# 数据目录说明

## 目录用途

- `mock_papers.json`：离线教学与自动测试使用的 mock 数据。
- `samples/`：来源、检索词、记录数和用途已经说明的固定样例。
- `manual/`：人工标注或人工复核输入；每条记录应能追溯到明确样例批次。
- `analysis/`：由样例检查、人工复核或实验分析形成的结构化表。
- `domain/`：第二周领域词典、同义词、任务词和排除词。
- `processed/`：可由脚本重新生成的候选库、查询记录表等整理后数据。
- `review/`：疑似重复和其他需要人工确认的结构化复核队列。
- `annotation_tasks/`：待人工判断的任务池、分配和个人任务；不是确认后的 ground truth。
- `benchmarks/`：带 version/status/hash provenance 的 judged-set artifact；只有 approved 且
  通过 strict validator 的版本可用于正式实验。
- `samples/w2/`：第二周各任务经过整理、来源清楚且体积适中的 live 样例或摘要。

当前统一真实样例是 `samples/openalex_stellar_spectra_100.csv`。它来自一次
OpenAlex live 检索，只用于团队开发、测试和人工分析，不是完整或权威的天文光谱
文献集。

## 提交边界

可以提交：来源清楚、体积适中、许可允许且已完成敏感信息检查的 mock 数据、固定样例、
人工标注和分析表。

不得提交：`.env`、API Key、访问 Token、个人手机号或学号、申请书原件、未经授权的
论文全文、无法说明来源的数据、大体积临时下载和本地运行数据库。

CSV 统一使用 UTF-8 或 UTF-8 with BOM，第一行必须是非空且不重复的表头。字段中包含
逗号、换行或双引号时必须按 CSV 规则转义。人工标注至少应记录样例文件名或批次、
稳定论文标识（优先 OpenAlex ID）和标注口径；无法与目标样例关联的标签不能直接用于
排序评价。
