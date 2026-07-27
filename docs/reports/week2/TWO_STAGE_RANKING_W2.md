# 第二周报告：TF-IDF 词法相关性与两阶段排序

- 负责人：蒲正杰
- 周期：2026-07-27—2026-07-31
- 设计文档：`docs/project/TWO_STAGE_RANKING_DESIGN.md`
- 数据契约：`docs/project/W2_DATA_CONTRACTS.md` 第 5 节

## 1. 交付清单

| 交付物 | 路径 | 状态 |
| --- | --- | --- |
| TF-IDF 词法相关性模块 | `src/text_relevance.py` | 已完成 |
| 排序评价模块 | `src/evaluation.py` | 已完成 |
| 两阶段排序入口 | `app/evaluate_ranking.py` | 已完成 |
| 相关性单元测试（22 项） | `tests/automated/test_text_relevance.py` | 已完成，全部通过 |
| 指标与两阶段单元测试（22 项） | `tests/automated/test_evaluation.py` | 已完成，全部通过 |
| ranking fixture（12 篇合成论文 + 标签 + 已知答案） | `tests/fixtures/ranking/` | 已完成 |
| live 样本（60 条） | `data/samples/w2/ranking/live_ranking_sample.csv` | 已完成 |
| 新旧排序逐论文对比 | `data/analysis/w2_ranking/baseline_vs_two_stage.csv` | 已完成 |
| 排名变化案例分析（5 例） | `data/analysis/w2_ranking/ranking_error_cases.csv` | 已完成 |
| 设计文档 | `docs/project/TWO_STAGE_RANKING_DESIGN.md` | 已完成 |
| 对比图 | `docs/reports/week2/figures/`（2 张） | 已完成 |

未修改 `src/processor.py`、`app/main.py`、`README.md`、`docs/CURRENT_STATUS.md`
和 `requirements.txt`（TF-IDF 为纯 Python 实现，无新增依赖）。

## 2. 实现概述

- 第一阶段：TF-IDF **词法相关性**（非语义理解）。标题、摘要分别在各自语料上
  统计平滑 IDF（`ln((N+1)/(df+1))+1`），与查询向量算余弦相似度，
  按 `0.7 × 标题 + 0.3 × 摘要` 合成 combined_relevance_score；
  按固定阈值 0.20 / 0.05 分为 high / medium / low 三层，只分层降权，不删除论文。
- 第二阶段：`stage2 = 分层降权系数 × (0.50 × 词法相关性 + 0.25 × 引用影响
  + 0.15 × 时效性 + 0.10 × 完整度)`，权重固定、总和为 1、写入模块常量。
- 旧版 `preliminary_score` 原样保留为 `baseline_preliminary_score`，
  `old_rank` 按旧规则重算，baseline 行为有测试守护。
- 人工标签只用于离线评价（Precision@K、NDCG@K、Top K 不相关数量、
  高相关平均排名），不进入任何评分公式；未标注论文不算不相关；
  非法标签抛出 ValueError。

## 3. OpenAlex live 验证

- 时间（UTC）：2026-07-27T12:27:51Z；模式：live
- 关键词：`machine learning stellar parameter estimation spectra`
- 请求 60 条，清洗去重后 60 条；样本与来源说明见
  `data/samples/w2/ranking/README.md`
- 第一阶段分层：high 4 / medium 32 / low 24
- 复现命令（离线，从样本 CSV 重算全部分析）：

  ```powershell
  python -m app.evaluate_ranking --mode offline `
      --input data/samples/w2/ranking/live_ranking_sample.csv `
      --keyword "machine learning stellar parameter estimation spectra"
  ```

## 4. fixture 离线评价结果

fixture（`tests/fixtures/ranking/`）为 12 篇合成论文，11 篇带人工等级
（高度相关 4、部分相关 4、不相关 3），1 篇故意未标注，1 篇故意缺摘要。
指标 K=10，baseline 与两阶段对比：

| 指标 | baseline | 两阶段 |
| --- | --- | --- |
| Precision@10 | 0.7 | 0.8 |
| NDCG@10 | 0.9306 | 0.9526 |
| Top 10 不相关数量 | 2 | 1 |
| 高度相关平均排名 | 3.75 | 4.0 |

两阶段后 4 篇高度相关全部进入前 9，3 篇不相关落到末 3 位；
高引用（800）但无关的股市论文从第 6 降到第 10，高引用（500）深海鱼论文
从第 10 降到第 11。高度相关平均排名略升 0.25：被救回的相关论文占据了前列，
把低引用（80）的相关论文 W9000000003 从第 9 挤到第 10，属预期内的正常交换。

fixture 只用于开发测试，以上数字不冒充真实领域评价结果。

## 5. live 数据排名变化案例分析

完整表见 `data/analysis/w2_ranking/ranking_error_cases.csv`（按变化绝对值取前 5），
逐例分析如下；另附 1 个词法方法失效的反例。

1. **Stellar atmospheric parameter estimation using Gaussian...**（引用 31，2014）
   48 → 4。标题直接命中查询主题，combined = 0.2985（high 层）。
   baseline 因引用和年份平庸把它压到 48，两阶段把它救回第 4，是本方案
   最有价值的纠偏类型。
2. **Full spectrum fitting with photometry in ppxf...**（引用 254，2023）
   8 → 35。combined = 0.0209（low 层），降权系数 0.5 生效。
   需要说明：全谱拟合其实与恒星参数估计相关，这篇很可能是**误伤**
   （标题摘要不使用查询用词），详见第 7 节限制。
3. **Photometric redshift estimation via deep learning**（引用 162，2017）
   44 → 16。combined = 0.1712（medium 层）。"estimation via deep learning"
   与查询词重合，但研究对象是星系红移而非恒星光谱——词法重合带来的
   **边界上升**案例，词法方法无法进一步甄别。
4. **Empirical Relations for the Accurate Estimation of Stellar...**（引用 33，2018）
   50 → 26。恒星参数估计相关论文，combined = 0.1274（medium 层），正常上升。
5. **Stellar parametrization from Gaia RVS spectra**（引用 88，2015）
   51 → 28。标题含 stellar parametrization 和 spectra，combined = 0.1277
   （medium 层），正常上升。
6. 反例（不在前 5，单独列出）：**SPCANet: Stellar Parameters and Chemical
   Abundances Network...**（引用 67）32 → 53。这是恒星参数估计的知名方法，
   但标题摘要用词（SPCANet、chemical abundances）与查询重合很少，
   combined = 0.0397 被分入 low 层。词法相关性识别不了这种领域变体，
   是本周**不硬删除论文**的直接理由。

新旧 Top 10 对比（`docs/reports/week2/figures/old_vs_new_rank_scatter.png`）：
新 Top 4 全部为恒星参数估计主题；893 引用的 "A survey of machine learning
for big data processing" 从 baseline 前列降到第 6，但 solar physics、
space weather、cosmology 等"机器学习 + 其他领域"论文仍留在第 5—8 位，
词法方法的边界清晰可见。

## 6. 自动测试

`python -m unittest discover -s tests/automated -p "test_*.py"`：**53 项全部通过**
（含既有 CLI 回归 9 项，确认未影响旧功能）。新增覆盖：

- `test_text_relevance.py`（22 项）：完全匹配、完全不匹配、缺摘要、缺标题、
  空查询、空语料、查询词不在语料、特殊字符、中文关键词（二字组）、单篇文献、
  分数范围 [0,1]、组合权重固定、输入不被原地修改、IDF 与余弦的手算已知答案
  （`tfidf_known_answer.json`）。
- `test_evaluation.py`（22 项）：Precision@K / NDCG@K 手算已知答案
  （`ranking_known_answer.json`）、非法标签报错、未标注论文不算不相关、
  待讨论按未标注、K 校验、第一阶段分层阈值、第二阶段排序稳定性与确定性、
  权重固定、baseline 分数与排名完整保留、缺摘要论文仍可排名、
  高度相关全部排在不相关之前、排名变化案例数量与解释。

## 7. 已知限制

- 词法相关性识别不了同义改写与领域变体（案例 2、6 的误伤），也拦不住
  共享通用词的主题偏离论文（案例 3）；TF-IDF 只是词法相关性基线。
- IDF 在候选集上统计，分数只在同一批次内可比。
- `recency_score` 依赖运行时年份，跨年复现会有微小差异。
- fixture 规模小（12 篇），仅用于验证机制正确性，不代表真实领域效果。

## 8. 验收标准自查

| 验收标准 | 结果 |
| --- | --- |
| 旧排序完整保留 | ✔ baseline_preliminary_score + old_rank + 测试守护 |
| 新增 TF-IDF 词法相关性 | ✔ `src/text_relevance.py` |
| 新增两阶段排序 | ✔ `app/evaluate_ranking.py` |
| 完成一次 OpenAlex live 验证 | ✔ 60 条，见第 3 节 |
| 指标可由代码重复计算 | ✔ 复现命令见第 3 节 |
| 测试有已知答案 | ✔ 两个 known-answer JSON + 手算推导 README |
| 人工标签不进入线上评分 | ✔ 仅评价路径使用；权重常量不含标签 |
| 至少分析 5 个排名变化案例 | ✔ 第 5 节 6 例 |
| 所有自动测试通过 | ✔ 53/53 |
| 能解释 TF-IDF、余弦相似度和 NDCG | ✔ 设计文档第 3、7 节 |

## 9. 下一步（P1 选做）

Precision@20 / NDCG@20、标题加权、分层阈值敏感性、摘要缺失影响分析；
领域词典或语义方法留待与领域查询任务对接后评估。
