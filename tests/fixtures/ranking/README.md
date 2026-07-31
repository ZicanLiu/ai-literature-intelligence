# ranking fixture：TF-IDF、排序和指标已知答案案例

本目录是第二周"TF-IDF 与两阶段排序"任务（蒲正杰）的离线测试 fixture。
所有数据都是**人工构造的合成数据**，只用于开发测试，不代表真实论文，
也不能冒充真实领域评价结果。

## 文件清单

- `papers.csv`：12 篇合成论文，查询词为
  `machine learning stellar parameter estimation spectra`。
  `openalex_id` 使用 `W9000000xxx` 号段，表示虚构标识。
  W9000000008 故意缺摘要，用于验证缺摘要论文仍可处理；
  W9000000009、W9000000010 是高引用但主题无关的论文，对应第一周发现的
  "高引用但主题偏离排名靠前"问题。
- `labels.csv`：11 篇论文的人工相关等级（口径见下）。
  **W9000000012 故意不出现**，用于验证"未标注论文不能自动算作不相关"。
- `labels_invalid_deliberate.csv`：**故意写错的标签文件**，
  `非常相关` 不在第二周允许的 label 取值内，用于验证非法标签必须报错。
- `tfidf_known_answer.json`：TF-IDF 手算已知答案。
- `ranking_known_answer.json`：Precision@K / NDCG@K 等指标手算已知答案。

## 标签口径

- `高度相关` = 2，`部分相关` = 1，`不相关` = 0；
- 未标注论文没有等级，不计入相关，也不计入不相关；
- 标签只用于离线评价，不进入线上评分公式。

## 已知答案推导

### TF-IDF（tfidf_known_answer.json）

文档：D1 = `machine learning spectra`，D2 = `machine vision`，
D3 = `deep sea fish`；查询 = `machine learning`。N = 3。

- df：machine = 2（D1、D2），其余词项各为 1；
- idf(t) = ln((N + 1) / (df + 1)) + 1：
  machine = ln(4/3) + 1 ≈ 1.287682，其余 = ln(4/2) + 1 ≈ 1.693147；
- 查询向量 = {machine: 1.287682, learning: 1.693147}（tf 均为 1）；
- 余弦相似度：D1 ≈ 0.782408，D2 ≈ 0.366447，D3 = 0.0（无重合词项）。

### 排序指标（ranking_known_answer.json）

固定排名 [A, B, C, D, E]；标签 A = 2，B = 0，C = 1，E = 2，D 未标注。
指标采用 judged（condensed）口径：未标注的 D 从 Top K 中移除后再计算，
不占位置、不进分母。

- judged Precision@3 = Top 3（A、B、C，全部已标注）中等级 ≥ 1 的数量 2 / 3 ≈ 0.666667；
- judged Precision@5 = 已标注的 A、B、C、E 中相关 3 / 4 = 0.75；
  judged_count_at_5 = 4，coverage_at_5 = 4 / 5 = 0.8；
- condensed DCG@3 = 3/log2(2) + 0/log2(3) + 1/log2(4) = 3.5，
  IDCG@3 按已标注等级降序 [2, 2, 1, 0] 截断计算 = 3 + 3/log2(3) + 1/log2(4) ≈ 5.392789，
  judged NDCG@3 = 3.5 / 5.392789 ≈ 0.649015；
- condensed DCG@5 = 3 + 0 + 0.5 + 3/log2(5) ≈ 4.792030（D 已移除，E 为第 4 个位置），
  IDCG@5 = 5.392789（等级 0 增益为 0），judged NDCG@5 ≈ 0.888599；
- Top 3 不相关数量 = 1（只有 B；D 未标注，不算不相关）；
- 高度相关（A 排第 1，E 排第 5）平均排名 = (1 + 5) / 2 = 3.0。
