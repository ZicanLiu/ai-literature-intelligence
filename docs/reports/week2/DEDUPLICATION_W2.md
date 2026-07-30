# W2 去重实验报告

**日期:** 2026-07-30  
**数据来源:** OpenAlex live API（两组独立查询）  
**测试数据:** 21 条 fixture + 27 个自动化测试

---

## 1. 查询执行

| 查询 | 关键词 | 获取数量 | run_id |
|------|--------|:------:|--------|
| 查询 1 | `machine learning stellar spectra` | 60 | `run001_ml_stellar_spectra` |
| 查询 2 | `deep learning stellar spectroscopy` | 60 | `run002_dl_stellar_spectroscopy` |
| **合并** | | **120** | |

数据保存于 `data/samples/w2/dedup/combined_w2_raw.csv`。

---

## 2. 确定重复结果

| 规则 | 命中数量 | 说明 |
|------|:------:|------|
| `same_openalex_id` | 11 | 同一论文两次出现在不同查询中 |
| `same_doi` | 0 | 无同 DOI 但不同 ID 的情况 |
| `same_title_no_id` | 0 | 无缺失 ID 的重复 |
| **合计** | **11** | |

11 篇确定重复全为查询词重叠导致（同一 OpenAlex 作品同时匹配两组关键词）。这些重复可以被自动合并，无需人工干预。

---

## 3. 疑似重复结果

| 指标 | 值 |
|------|:--:|
| 疑似重复对数量 | 2 |
| 来自查询 1 的论文 | 2 |
| 来自查询 2 的论文 | 2 |

### 3.1 疑似重复详情

| pair_id | Left Title | Right Title | sim | auth | yr | DOI |
|---------|-----------|-------------|:---:|:----:|:--:|-----|
| SP-8d2fce71 | A MACHINE-LEARNING METHOD TO INFER FUNDAMENTAL STELLAR PARAMETERS FROM PHOTOMETRIC LIGHT CURVES | A Machine Learning Method to Infer Fundamental Stellar Parameters from Photometric Light Curves | 1.000 | 1.000 | 1 | one_missing |
| SP-fe25e871 | An active instance-based machine learning method for stellar population studies | An Active Instance-based Machine Learning method for Stellar Population Studies | 1.000 | 1.000 | 0 | one_missing |

### 3.2 判定分析

两对疑似重复均为**大小写不一的同一标题**在不同查询中出现，OpenAlex 给它们分配了不同的 `openalex_id`。双方 DOI 一侧有值一侧为空。

- **SP-8d2fce71**：查询 1（`run001`）返回的标题为大写，查询 2（`run002`）返回为标准大小写，年份差 1 年（2014 vs 2015），可能为版本差异。**建议人工确认。**
- **SP-fe25e871**：标题仅大小写不同，年份一致（2005），同一论文的不同元数据来源。**建议人工确认。**

---

## 4. 各规则命中统计

| 规则组件 | 命中次数 |
|---------|:------:|
| `title_very_high_similarity` | 2 |
| `author_high_overlap` | 2 |
| `year_close` | 2 |

---

## 5. 边界案例分析

### 案例 1：大小写差异导致不同 ID
两对疑似重复均由 OpenAlex 的大小写敏感匹配导致同一论文被分配了不同 ID。标准化标题完全相同（相似度 1.000），作者完全相同。属于 Level 1 精确去重无法覆盖的边界情况。

### 案例 2：相似度高但 DOI 排除
真实数据中，部分论文虽有高标题相似度，但因两侧 DOI 均存在且不同，被 blocking 排除。例如 arXiv 预印本和正式期刊版有不同 DOI，相似度很高但在当前 DOI 排除规则中被跳过了潜在重复对。

### 案例 3：年份窗口 blocking
当前仅比较 |year_diff| ≤ 2 的论文对。对于 arXiv 预印本和多年后正式出版的情况（如 2018 arXiv → 2022 期刊），会被 blocking 跳过。这是已知的 false negative 来源。

### 案例 4：标题高度重叠但学科不同
真实数据中有少量跨学科论文（如无线电通信、材料科学），标题中均含 "machine learning"，但与天文学无关。当前方法不检查语义，仅靠标题 token 匹配。

---

## 6. 可自动处理的项

| 类型 | 数量 | 处理方式 |
|------|:--:|---------|
| 同一 OpenAlex ID | 11 | 自动合并 |
| 同一 DOI 不同前缀 | 0 | 自动合并（如出现则自动） |
| 标题完全相同且无 ID | 0 | 自动合并（如出现则自动） |

---

## 7. 必须人工判断的项

| 类型 | 数量 | 原因 |
|------|:--:|------|
| 疑似重复（大小写差异） | 2 | 需确认是否为同一版本 |
| 预印本/正式版 | 0（真实数据） | 需人工判断内容版本差异 |
| 标题相似但作者不同 | 0（真实数据） | 需人工确认是否为改写/剽窃 |

---

## 8. 当前方法的潜在误判

| 误判类型 | 描述 | 发生条件 | 影响 |
|---------|------|---------|------|
| **False Positive** | 同课题组多篇系列论文被标为疑似重复 | 标题模式类似（如 Part I / Part II） | 低 — 仅进入审核队列 |
| **False Negative** | 标题改写后无法匹配 | 内容相同但用词不重叠 | 中 — 无法在当前框架解决 |
| **False Negative** | 年份差 > 2 被 blocking 排除 | arXiv 预印本 vs 多年后正式出版 | 中 — 可放宽年份窗口 |
| **False Positive** | 不同 DOI 排除后未经 blocking 检查就标记 | 一侧缺失 DOI 时相似度高 | 低 — blocking 已处理 |

---

## 9. 关键概念解释

### 精确匹配 vs 模糊匹配
- **精确匹配**：两个标识字符串逐字符比较，必须完全一致。例如同一 OpenAlex ID、同一标准化 DOI。确定重复使用此方法。
- **模糊匹配**：计算两个实体之间的相似程度，设定阈值。例如 Jaccard 系数、编辑距离。疑似重复使用此方法。

### 标题标准化
将标题转换为"可比形式"——小写、去除标点和 HTML 标签、空白压缩、去除版本号（arXiv ID 等）。标准化后，大小写差异、标点差异、空格差异都被消除。

### Jaccard 相似度
`|A ∩ B| / |A ∪ B|`，衡量两个词项集合的重合比例。对标题标准化后拆分词项计算。完全相同的标题 Jaccard = 1.0，毫无关联的标题 Jaccard = 0.0。

### SequenceMatcher / 编辑相似度
`difflib.SequenceMatcher.ratio()`，衡量两个字符串的最长公共子序列比例。对词序更敏感，补充纯词袋模型的不足。

### 作者重合
提取作者姓氏的 Jaccard 相似度。同名作者在两个版本中的差异通常体现在机构/缩写，姓氏重合度高可以确认同一组作者。

### Blocking
在 O(n²) 全量比较中，用启发式规则缩减候选对数量的技术。本系统使用年份窗口（±2）和 DOI 排除作为 blocking 条件。

### 为什么疑似重复不能直接删除
直接删除疑似重复论文造成信息损失：
1. 同一论文的不同版本（arXiv v1 vs v2、预印本 vs 期刊版）包含不同的修订内容
2. 高度相似的论文可能是不同的独立研究（如 benchmark 对比）
3. 软删除可能导致后续分析引用链路断裂

### 预印本与正式版的关系
同一论文常首先在 arXiv 发布，随后在期刊正式出版。两者可能 Title 略有不同（期刊版加上出版商后缀），DOI 完全不同（arXiv DOI vs 期刊 DOI），年份不同，但内容核心相同。这是去重中最容易误判的情况，尤其当前 blocking 条件可能漏判年份差 > 2 的情况。

### 数据来源追踪
每条记录保留 `keyword`（检索词）和 `run_id`（查询批次）。合并和去重记录中保留双向的来源信息，确保可以追溯到原始查询。

---

## 10. 测试覆盖

27 个自动测试，覆盖：

| 测试场景 | 通过 |
|---------|:---:|
| 相同 OpenAlex ID | ✓ |
| 相同 DOI（URL 前缀差异） | ✓ |
| 标题完全相同 | ✓ |
| 标点差异 | ✓ |
| 标题带副标题/arXiv ID | ✓ |
| 年份相差 1 年 | ✓ |
| 作者明显不同 | ✓ |
| 高相似但不自动删除 | ✓ |
| 低相似不进入队列 | ✓ |
| 空标题 | ✓ |
| HTML 特殊字符 | ✓ |
| pair_id 不重复 | ✓ |
| 来源追踪字段不丢失 | ✓ |
| 确定/疑似严格分开 | ✓ |
| DOI 标准化（多前缀） | ✓ |
| 作者姓氏提取 + 重合度 | ✓ |
| Jaccard 边界值（0, 0.5, 1.0） | ✓ |
| SequenceMatcher 边界值 | ✓ |

---

## 11. 交付物清单

| 文件 | 路径 |
|------|------|
| 去重核心模块 | `src/deduplication.py` |
| 审核 CLI | `app/review_duplicates.py` |
| 自动测试 | `tests/automated/test_deduplication.py` |
| 测试 fixture | `tests/fixtures/dedup/test_papers.json` |
| 查询数据（查询 1） | `data/samples/w2/dedup/query_run001_ml_stellar_spectra.csv` |
| 查询数据（查询 2） | `data/samples/w2/dedup/query_run002_dl_stellar_spectroscopy.csv` |
| 合并原始数据 | `data/samples/w2/dedup/combined_w2_raw.csv` |
| 疑似重复 CSV | `data/review/suspected_duplicates_w2.csv` |
| 精确重复 CSV | `data/analysis/w2_dedup/exact_duplicates_w2.csv` |
| 汇总统计 | `data/analysis/w2_dedup/dedup_summary_w2.csv` |
| 设计文档 | `docs/project/DEDUPLICATION_DESIGN.md` |
| 报告（本文件） | `docs/reports/week2/DEDUPLICATION_W2.md` |
