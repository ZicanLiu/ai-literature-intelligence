# 两阶段排序设计文档

- 任务：第二周"TF-IDF 词法相关性与两阶段排序"（蒲正杰）
- 代码：`src/text_relevance.py`、`src/evaluation.py`、`app/evaluate_ranking.py`
- 数据契约：`docs/project/W2_DATA_CONTRACTS.md` 第 5 节

## 1. 背景与问题

v0.2.0 的 `preliminary_score` 把相关性、引用影响、时效性和完整度直接线性加权
（0.40 / 0.30 / 0.20 / 0.10），其中相关性只是"关键词词项是否出现"的计数。
第一周发现：**高引用但主题偏离的论文可能排名较高**——引用影响 0.30 的权重足以
把一篇主题几乎无关的高引用论文推进前列。

本周新增两阶段排序：第一阶段用 TF-IDF 词法相关性筛选（分层 + 低相关降权），
第二阶段在较相关候选中进行多指标排序。旧版排序完整保留为 baseline。

## 2. 总体流程

```text
原始论文
  → clean_papers / remove_duplicates / add_preliminary_scores   （v0.2.0，不修改）
  → baseline_preliminary_score 副本 + old_rank                  （baseline 完整保留）
  → 第一阶段：TF-IDF 词法相关性
        title_relevance_score / abstract_relevance_score / combined_relevance_score
        stage1_relevance_score = combined_relevance_score
        stage1_relevance_level ∈ {high, medium, low}（固定阈值分层）
  → 第二阶段：stage2_ranking_score
        = 分层降权系数 × (0.50 × 词法相关性 + 0.25 × 引用影响
                          + 0.15 × 时效性 + 0.10 × 完整度)
  → new_rank（stage2_ranking_score 降序）
```

第一阶段只做分层和降权，**不删除任何论文**：本周阈值未经更大规模验证，
硬删除可能误杀用词不同但真实的相关论文（见第 8 节 SPCANet 案例）。

## 3. TF-IDF 词法相关性（`src/text_relevance.py`）

TF-IDF 是**词法相关性基线**：它只衡量查询与论文在词项上的重合程度，
不代表真正的语义理解。

- 文本标准化：小写化；英文数字按完整单词 `[a-z0-9]+` 分词；特殊字符自然丢弃。
- 中文处理：连续汉字切成二字组（"恒星光谱" → 恒星、星光、光谱），单字保留。
  二字组是词法层面的最小可解释单位：单字误匹配太多，整段匹配太严格。
- 词袋模型：文档表示为词项多重集合，不考虑词序。
- TF：词项在文档中的原始出现次数。
- IDF：`ln((N + 1) / (df + 1)) + 1`，N 为语料文档数，df 为包含该词项的文档数。
  平滑公式避免除以 0，保证查询词不在语料时仍为有限正数。
- 稀疏向量：TF-IDF 向量用字典表示，只存非零项。
- 余弦相似度：查询向量与文档向量的夹角余弦。TF-IDF 权重非负，
  所以取值恒在 [0, 1]；余弦相似度不受文档绝对长短影响，
  长摘要不会因为词多而天然得高分。
- 标题与摘要分别在**标题语料**和**摘要语料**上统计 IDF，
  两类分数各自在论文之间可比。
- `combined_relevance_score = 0.7 × title + 0.3 × abstract`：
  标题比摘要更直接表达主题；权重固定写死在模块常量，可解释、可复查。

边界处理：缺标题或缺摘要时对应子分为 0，组合分由存在的部分算出；空查询、
空文本、空语料、查询词不在语料、特殊字符输入都得到 0 分，不抛异常。

## 4. 第一阶段分层阈值

- `combined >= 0.20` → high；`>= 0.05` → medium；其余 → low。
- 降权系数：high = 1.0，medium = 0.8，low = 0.5。
- 阈值依据：在 100 条统一样例（`openalex_stellar_spectra_100.csv`）上，
  两个候选关键词下三层数量为 14/59/24 与 4/46/47；在 60 条 live 数据上为
  4/32/24（见 `docs/reports/week2/figures/stage1_relevance_distribution.png`），
  三层都非空且 low 层足以容纳明显无关论文。
- 阈值是**先定后测**的固定常量，不随单次数据自动调整，也不参考人工标签。

## 5. 第二阶段综合排序

| 指标 | 权重 | 来源 |
| --- | --- | --- |
| 词法相关性 combined_relevance_score | 0.50 | 本周新增 |
| 引用影响 impact_score | 0.25 | v0.2.0 已有子分 |
| 时效性 recency_score | 0.15 | v0.2.0 已有子分 |
| 完整度 completeness_score | 0.10 | v0.2.0 已有子分 |

权重固定、总和为 1、全部写入模块常量。词法相关性提升到主导地位（0.50），
直接针对第一周的问题；引用影响从 0.30 下调到 0.25 并受分层降权约束。
排序按 stage2_ranking_score 降序，平局依次按 combined_relevance_score、
cited_by_count、publication_year 降序，保证结果确定可复现。

## 6. 数据泄漏防控

- **人工标签不进入线上评分**：所有评分输入都是论文自带、获取时即可得的字段；
  人工标签只出现在 `tests/fixtures/ranking/` 和 `src/evaluation.py` 的评价路径。
- **未标注论文不自动算作不相关**：未标注论文没有等级，既不计入相关也不计入
  不相关；`待讨论` 按未标注处理；非法标签直接抛出 ValueError。
- **IDF 语料与评价 fixture 隔离**：IDF 只在当前候选论文集上统计，
  绝不在带人工标签的 fixture 上统计后再来评价 fixture——
  fixture 的语料分布是人工按标签挑选的，用它统计 IDF 等于让评分系统
  间接看到答案（轻度泄漏）。
- **权重不看着 fixture 指标调**：权重和阈值基于设计理由固定，
  fixture 只用于最终验证，不用于迭代调参。

## 7. 离线评价指标（`src/evaluation.py`）

人工等级：高度相关 = 2，部分相关 = 1，不相关 = 0。

- Precision@K = Top K 中等级 ≥ 1 的数量 / K；
- DCG@K = Σ (2^等级 − 1) / log2(名次 + 1)，NDCG@K = DCG@K / IDCG@K，
  IDCG 由全部已标注论文等级降序排列计算；未标注论文增益为 0 但仍占名次；
- Top K 不相关数量：只数明确标注为不相关的论文；
- 高相关样例平均排名：等级 2 论文名次的平均值（从 1 开始）。

## 8. 已知限制

- 词法相关性无法识别同义改写和领域变体。live 数据中
  "SPCANet: Stellar Parameters and Chemical Abundances..." 用词与查询重合少，
  combined = 0.0397 被分到 low 层，排名 32 → 53；它很可能实际相关。
  这正是"词法相关性 ≠ 语义理解"的实例，也是本周不硬删除论文的原因。
- 共享通用词的主题偏离论文（如标题含 machine learning 的股市论文）仍可能
  得到中等词法分数，词法方法无法根除这类问题。
- IDF 在候选集上统计，候选集本身偏向查询主题时，低频词权重会偏高；
  分数只在同一批次内可比，不跨批次比较。
- recency_score 依赖运行时年份，跨年复现分数会有微小差异。

## 9. P1 选做方向

Precision@20 / NDCG@20、标题加权实验、不同分层阈值对比、摘要缺失影响分析，
以及引入领域词典或语义方法弥补词法局限，均留待 P0 验收后评估。
