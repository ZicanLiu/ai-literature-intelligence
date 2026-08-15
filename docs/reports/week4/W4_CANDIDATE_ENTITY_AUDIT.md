# W4 Candidate Pool 实体核查报告

**日期:** 2026-08-14
**核查对象:** `data/annotation_tasks/w4/candidate_pool_v0.1.csv`（只读）
**核查性质:** 实体级只读审计，不修改去重算法、不修改 Candidate Pool
**数据契约:** 见 `pool_manifest_v0.1.json`

---

## 1. 结论概览

| 核查项 | 结果 |
|--------|------|
| pair 总数 | 60 |
| 唯一 OpenAlex work records（OpenAlex ID） | 57 |
| 高置信 same-paper entity alias | 2 对 |
| 合并 alias 后约对应论文实体 | ~55 |
| 跨 RQ 共现论文 | 3 篇 |
| 同一 RQ 内重复 OpenAlex ID | 0 |
| DOI 指向不同 ID 的冲突 | 0 |
| 违反 suspected 边界（标题相似被误删） | 0 |

总体判断：**Candidate Pool 不存在明显实体错误，可以进入标注阶段**。

需要区分两个层次：

- **OpenAlex work record**：以 `openalex_id` 为单位的原始记录，共 **57** 个；
- **canonical entity**：经过实体合并后的真实论文实体。发现 **2 对高置信 same-paper
  alias**（同一论文被 OpenAlex 收录为两个不同 ID），若未来完成 canonical entity
  consolidation，约对应 **55** 个论文实体。

这 2 对 alias 是**当前 exact / suspected contract 尚未覆盖**的情况，不是“当前 exact
规则已经应该识别却执行失败”。属于后续 DOI canonicalization / dedup 改进项，本次只
记录、不修改。

---

## 2. 60 个 pair 对应多少 unique paper

60 个 query-paper pair 对应 **57 个 unique OpenAlex work records**（OpenAlex ID），与
manifest `unique_openalex_work_count = 57` 一致。差 3 是因为 3 篇论文跨 RQ 出现。

在 entity 层面，57 个 record 中存在 2 对高置信 same-paper alias（见第 6 节），合并后
约对应 **55 个高置信论文实体**。

各 RQ 分布均匀：R01/R02/R03 各 20 条。

---

## 3. 跨 RQ 共现的论文

| OpenAlex ID | 标题 | 出现的 RQ | 是否合理 reuse |
|-------------|------|-----------|:-------------:|
| W2777402735 | Carbon Stars Identified from LAMOST DR4 Using Machine Learning | RQ01、RQ02 | 合理 |
| W4384201335 | Machine learning in solar physics | RQ01、RQ03 | 合理 |
| W3155899199 | Machine Learning Based Automatic Modulation Recognition for Wireless Communications | RQ01、RQ03 | 内容存疑 |

前两篇是典型的 query-dependent reuse：一篇碳星论文同时涉及“光谱分类”（RQ01）与
“恒星参数/大气参数”（RQ02）；一篇太阳物理 ML 综述既可能涉及分类，也可能涉及
预处理/降噪（RQ03）。

第三篇（W3155899199）是无线通信自动调制识别综述，与恒星光谱无关，属于词汇级
误命中（"machine learning" + "spectrum/spectra"）。它跨 RQ 出现本身不违反去重边界，
但内容上应被判为 `0`（不相关）。这一内容问题在标注阶段由人工如实判断，无需在
审计阶段改动。

**结论**：跨 RQ 共现是 benchmark 的正常设计（单位是 research question + paper），
不是 entity 错误，**不应也不能直接删除**。

---

## 4. 同一 RQ 内重复 OpenAlex ID

未发现。每个 `research_query_id + openalex_id` 组合唯一，符合 `W4_RESEARCH_PLAN.md`
第 5 节的契约。

---

## 5. DOI 冲突

以原始 DOI（去除 `https://doi.org/` 等前缀、但**保留** `/pdf` 后缀）为准，未发现
同一 DOI 指向不同 OpenAlex ID 的冲突。

---

## 6. 高置信 same-paper entity alias（当前 contract 尚未覆盖）

发现 2 对在同一 RQ 内、标题完全相同、DOI 主体相同（仅差 `/pdf` 后缀）、但 OpenAlex
ID 不同的记录，判定为高置信 same-paper entity alias：

### 6.1 RQ02 内 alias

| pair_id | OpenAlex ID | DOI |
|---------|-------------|-----|
| w4_rq02_002 | W3106471209 | 10.1051/0004-6361/201833099/pdf |
| w4_rq02_011 | W2795071146 | 10.1051/0004-6361/201833099 |

标题：`Dissecting stellar chemical abundance space with t-SNE`

### 6.2 RQ03 内 alias

| pair_id | OpenAlex ID | DOI |
|---------|-------------|-----|
| w4_rq03_004 | W3103819337 | 10.1051/0004-6361/201630240/pdf |
| w4_rq03_011 | W2607233176 | 10.1051/0004-6361/201630240 |

标题：`Unsupervised feature-learning for galaxy SEDs with denoising autoencoders`

### 与当前 dedup 实现的关系

这两对 alias **当前不命中任何 exact / suspected 规则**，原因是：

1. `normalize_doi()` 只去除前缀（`https://doi.org/`、`http://doi.org/`、`doi.org/`、
   `doi:`），**不去除 `/pdf` 后缀**。因此 `10.1051/.../201833099` 与
   `.../201833099/pdf` 被判为两个不同 DOI，**不命中 `same_doi`**；
2. 两条记录 openalex_id 不同，且 DOI 均非空，因此不满足 `same_title_no_id` 要求的
   `not oa_id and not doi`，**也不命中该规则**；
3. 当前 suspected 逻辑对“两侧 DOI 非空但不同”的论文对**直接跳过**，因此这两对
   **也不会进入 suspected queue**。

所以准确的结论是：这是**当前 exact / suspected contract 尚未覆盖的高置信 entity
alias**，不是“当前 exact 规则已经应该识别却执行失败”。

### 建议后续处理方式

- 不在 W4 内修改 `src/deduplication.py`；
- 建议在后续公共任务中做 DOI canonicalization：为 `normalize_doi` 增加 `/pdf`、
  `.pdf`、`#abstract` 等常见后缀清理，并补充对应单元测试；
- 若未来重新生成候选池并做 canonical entity consolidation，可把这两对合并为一个
  论文实体（约 57 → 55），同时保留各自的 OpenAlex ID 与 provenance。

---

## 7. 标题相似但不能安全合并的示例

RQ01 内存在若干标题相似度 0.60–0.73 的论文对，作为**人工审计中的 title-similarity
示例**，说明仅凭标题相似不能安全合并：

| pair A | pair B | 相似度 | 说明 |
|--------|--------|:------:|------|
| w4_rq01_001 Stellar Classification by Machine Learning | w4_rq01_019 Stellar classification from single-band imaging | 0.73 | 不同任务（多算法 vs 单波段成像），不应合并 |
| w4_rq01_001 Stellar Classification by Machine Learning | w4_rq01_009 miniJPAS star-galaxy classification | 0.67 | 星分类 vs 星-星系分类，不应合并 |

这些示例用于说明“标题相似 ≠ 同一实体”，并非暗示它们已经进入当前 suspected queue。

---

## 8. 是否违反现有 exact / suspected 边界

| 边界 | 是否违反 | 说明 |
|------|:--------:|------|
| exact dedup（同 ID / 同 DOI / 无 ID 无 DOI 同标题） | 否 | 现有三条规则均未误伤 |
| suspected 不自动删除 | 否 | 无标题相似记录被自动合并 |
| 跨 RQ 共现不被当作 duplicate 删除 | 否 | 3 篇跨 RQ 论文均保留 |
| 同 RQ 内高置信 alias 被完整捕获 | 否（不在 contract 内） | 2 对 `/pdf` DOI alias 属后续 canonicalization 改进项 |

---

## 9. 摘要缺失记录

3 条记录摘要为空，会影响人工标注的证据充分性，标注时需结合标题 + 外部页面判断：

| pair_id | OpenAlex ID | 标题 |
|---------|-------------|------|
| w4_rq01_017 | W2078829410 | Classification of Spectra of Emission Line Stars Using Machine Learning Techniques |
| w4_rq02_001 | W1653774948 | Nucleosynthesis in Stellar Explosions |
| w4_rq02_015 | W3161474384 | Internal mixing of rotating stars inferred from dipole gravity modes |

---

## 10. 审计结论与建议

1. **Candidate Pool 实体层面健康**：60 pair / 57 个 unique OpenAlex work records，
   跨 RQ reuse 合理，无同 RQ 重复 ID，无 DOI 冲突，suspected 边界未被扩大。
2. **记录/实体两个层次**：57 是 OpenAlex record 数；若做 canonical entity
   consolidation，约 55 个论文实体（含 2 对 `/pdf` DOI alias 的合并）。
3. **当前 contract 未覆盖的 alias**：2 对高置信 same-paper entity alias 因
   `normalize_doi` 不去 `/pdf` 且 suspected 跳过双侧非空不同 DOI，目前既不进 exact
   也不进 suspected；作为后续 DOI canonicalization / dedup 改进项记录，不视为当前
   dedup 的失败。
4. **不改动**：本次未修改 `src/deduplication.py`、`src/pipeline.py`、
   Candidate Pool、Assignments 或 Research Query config。
