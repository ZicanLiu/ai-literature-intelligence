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
| 唯一 OpenAlex work 数 | 57 |
| 跨 RQ 共现论文 | 3 篇 |
| 同一 RQ 内重复 OpenAlex ID | 0 |
| DOI 指向不同 ID 的冲突 | 0 |
| 被 exact dedup 遗漏的同一实体（同 RQ 内） | **2 对** |
| 违反 suspected 边界（标题相似被误删） | 0 |

总体判断：**Candidate Pool 不存在明显实体错误，可以进入标注阶段**。但发现 2 对
“同一实体在同 RQ 内以不同 OpenAlex ID 出现、且未被 exact dedup 捕获”的记录，其根因
是 DOI 的 `/pdf` 后缀未在去重前归一化。这属于后续 dedup 改进项，不属于 W4 本任务
范围，本次只记录、不修改。

---

## 2. 60 个 pair 对应多少 unique paper

60 个 query-paper pair 对应 **57 篇唯一 OpenAlex work**，与 manifest
`unique_openalex_work_count = 57` 一致。差 3 是因为 3 篇论文跨 RQ 出现。

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

## 6. 被 exact dedup 遗漏的同一实体（关键发现）

发现 2 对在同一 RQ 内、标题完全相同、DOI 仅差 `/pdf` 后缀、但 OpenAlex ID 不同的记录：

### 6.1 RQ02 内重复

| pair_id | OpenAlex ID | DOI |
|---------|-------------|-----|
| w4_rq02_002 | W3106471209 | 10.1051/0004-6361/201833099/pdf |
| w4_rq02_011 | W2795071146 | 10.1051/0004-6361/201833099 |

标题：`Dissecting stellar chemical abundance space with t-SNE`

### 6.2 RQ03 内重复

| pair_id | OpenAlex ID | DOI |
|---------|-------------|-----|
| w4_rq03_004 | W3103819337 | 10.1051/0004-6361/201630240/pdf |
| w4_rq03_011 | W2607233176 | 10.1051/0004-6361/201630240 |

标题：`Unsupervised feature-learning for galaxy SEDs with denoising autoencoders`

### 根因

`src/deduplication.py` 的 `normalize_doi()` 只去除前缀（`https://doi.org/`、
`http://doi.org/`、`doi.org/`、`doi:`），**不去除 `/pdf` 后缀**。因此：

```text
10.1051/0004-6361/201833099     （干净 DOI）
10.1051/0004-6361/201833099/pdf （带 /pdf 后缀）
```

被当作两个不同 DOI，`same_doi` 规则无法命中；同时两篇论文 openalex_id 不同、
DOI 均非空，`same_title_no_id` 规则要求 `not oa_id and not doi`，也无法命中。
于是这 4 条记录逃过了 exact dedup。

### 建议后续处理方式

- 不在 W4 内修改 `src/deduplication.py`；
- 建议在后续公共任务中，为 `normalize_doi` 增加 `/pdf`、`.pdf`、`#abstract` 等
  常见后缀清理，并补充对应单元测试；
- 若未来重新生成候选池，可先用「DOI 去 `/pdf` 后缀 + 标题完全相同」作为 exact
  判定，或至少把这两对送入 suspected 复核队列。

---

## 7. 只凭 title 相似但不能安全自动删除的情况

RQ01 内存在若干标题相似度 0.60–0.73 的论文对，例如：

| pair A | pair B | 相似度 | 判定 |
|--------|--------|:------:|------|
| w4_rq01_001 Stellar Classification by Machine Learning | w4_rq01_019 Stellar classification from single-band imaging | 0.73 | 不同任务（多算法 vs 单波段成像），不应合并 |
| w4_rq01_001 Stellar Classification by Machine Learning | w4_rq01_009 miniJPAS star-galaxy classification | 0.67 | 星分类 vs 星-星系分类，不应合并 |

这些记录**没有被自动删除**，符合当前 suspected 边界要求（疑似重复只进入复核队列，
不自动合并）。审计确认边界未被扩大。

---

## 8. 是否违反现有 exact / suspected 边界

| 边界 | 是否违反 | 说明 |
|------|:--------:|------|
| exact dedup（同 ID / 同 DOI / 无 ID 无 DOI 同标题） | 否 | 现有三条规则均未误伤 |
| suspected 不自动删除 | 否 | 无标题相似记录被自动合并 |
| 跨 RQ 共现不被当作 duplicate 删除 | 否 | 3 篇跨 RQ 论文均保留 |
| same RQ 内 entity 重复被完整捕获 | **部分** | 2 对 `/pdf` DOI 重复遗漏（见第 6 节） |

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

1. **Candidate Pool 实体层面健康**：60 pair / 57 唯一 work，跨 RQ reuse 合理，
   无同 RQ 重复 ID，无 DOI 冲突，suspected 边界未被扩大。
2. **唯一待改进项**：2 对同 RQ 内因 DOI `/pdf` 后缀未归一化而漏判的 exact duplicate，
   已在第 6 节记录 pair_id 与建议，交由后续公共任务处理。
3. **不改动**：本次未修改 `src/deduplication.py`、`src/pipeline.py`、
   Candidate Pool、Assignments 或 Research Query config。
