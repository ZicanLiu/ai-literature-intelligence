# W5 BM25 与 B0/B1 基线 Artifact 报告

**日期:** 2026-08-17
**任务来源:** Issue #51（[W5-蒲正杰] 实现 BM25 稀疏排序并导出 B0/B1 统一基线 Artifact）
**实验性质:** 固定 60-pair Candidate Pool 上的 Query-Relevance ranking/reranking，
不是端到端 retrieval recall benchmark
**协议:** [`W5_METHOD_RANKING_CONTRACT.md`](../../project/W5_METHOD_RANKING_CONTRACT.md) v1.0

---

## 1. 交付物

三个符合 W5 Method Ranking Contract v1.0 的 method ranking package，全部通过
`python -m app.validate_w5_method` 严格校验（60/60 pair、每 RQ 20/20）：

| method_id | family | ranking.csv SHA-256 |
| --- | --- | --- |
| `bm25_v1` | sparse | `2e5818163598246de0c79069ac7c88247870b03c1a4bffc0c6d08709c373f74e` |
| `preliminary_score_v1` | baseline | `0fdd1679405322ccc623f4f528e153e3c251d2f44aed2aaa661f37b1f1e7b9d5` |
| `tfidf_two_stage_v1` | baseline | `29188a495e9e05cdb8853fb5bd3bf3b22972e5cba8b84b4a6724575e74c84df5` |

输出目录：`data/analysis/w5_methods/<method_id>/`（各含 `ranking.csv` 与
`manifest.json`）。三个 package 均在 clean Git 工作树（代码提交 `ff571e2`）上
生成，manifest 记录完整 provenance。

## 2. BM25 方法说明

- **实现**：`src/bm25_ranking.py`，纯 Python 标准库、CPU、无任何第三方依赖；
- **公式**：标准 Okapi BM25，`idf = ln(1 + (N - df + 0.5) / (df + 0.5))`，
  `score = Σ idf · tf·(k1+1) / (tf + k1·(1 - b + b·dl/avgdl))`；
- **预注册参数**：`k1 = 1.5`，`b = 0.75`（模块常量固定，未做任何 grid search
  或基于 benchmark 指标的调参）；
- **文本与查询**：复用 `src.text_relevance.tokenize_text`（与 TF-IDF baseline
  同一 tokenizer/规范化），查询为各 RQ 的显式 `ranking_keyword`，未新增
  query expansion；
- **文档**：冻结池每个 pair 的 `title + abstract`；缺 abstract 时只保留
  title，不删除 pair。

## 3. BM25 corpus 规则与 alias 限制（Issue 第六节要求写入报告）

- corpus statistics（df 与平均文档长度）使用冻结 Candidate Pool 的全部 **60 条
  record-level 文本**，即把每个 `research_query_id + openalex_id` pair 当作独立
  文档；
- 已知两对高置信 same-paper alias（RQ02：`w4_rq02_002`/`w4_rq02_011`；RQ03：
  `w4_rq03_004`/`w4_rq03_011`）**保留为独立记录**，未合并、未删除、未
  canonicalize；两对 alias 在各自 RQ 内获得相同分数并按 `pair_id` 升序打破
  并列，与 Contract 一致；
- **局限**：60 条记录是很小的语料，df/avgdl 估计方差大；alias 重复计入 df 会
  轻微压低相关词项的 IDF；这些统计只反映该冻结池，不代表更大的文献空间。因此
  BM25 结果只支持与 B0/B1 等方法在同一固定池内的相对比较，不支持对整个
  OpenAlex 空间的 retrieval 结论。

## 4. B0/B1 导出方式

- 排序计算**完全复用** `src.w4_benchmark_evaluation.rank_query_papers`（内部即
  `src.processor.add_preliminary_scores` 与 `src.ranking.apply_two_stage_ranking`），
  未重写、未修改任何公式、权重或阈值；`src/text_relevance.py`、`src/ranking.py`、
  `src/processor.py` 均零改动；
- `reference_year = 2026` 读取自冻结 `pool_manifest_v0.1.json`，与项目固定实验
  口径一致，未硬编码；
- artifact 的 `score` 列原样记录 `preliminary_score`（B0）与
  `stage2_ranking_score`（B1）；`rank` 列按 Contract 固定规则
  `score desc → pair_id asc` 生成（与旧 `old_rank`/`new_rank` 的引用量/年份
  tie-break 不同，这是 Contract 的确定性排序要求，分数本身不受影响）；
- 测试中用同一输入直接重算原算法，逐 pair 断言 artifact 分数与原算法输出完全
  一致（`tests/automated/test_w5_baseline_export.py`）。

## 5. Label-free 声明

三个 artifact 的 ranking generation 阶段均未读取 approved benchmark 的
`judgements.csv`/`final_label`、任何 annotation、agreement、Blind AI Audit 或
adjudication 结果，也未使用任何由正式 label 计算的指标。代码路径上不存在接受
label 的入口；manifest 中 `label_access.benchmark_labels_read = false`。

## 6. 复现命令

```powershell
# 前置：clean Git 工作树（artifact 已提交时请先移除 data/analysis/w5_methods/ 再重新生成）
python -m app.run_bm25_ranking
python -m app.export_w5_baselines

# 校验
python -m app.validate_w5_method --manifest data/analysis/w5_methods/bm25_v1/manifest.json
python -m app.validate_w5_method --manifest data/analysis/w5_methods/preliminary_score_v1/manifest.json
python -m app.validate_w5_method --manifest data/analysis/w5_methods/tfidf_two_stage_v1/manifest.json
```

生成器在写出任何输出前采集 Git 状态，dirty 或无法确认 clean 时拒绝生成。

## 7. 验证结果

- 定向测试：`test_bm25_ranking.py`（14 项）与 `test_w5_baseline_export.py`
  （10 项）全部通过，覆盖 term 不存在、TF 饱和、长度归一化、缺 abstract、
  同分 deterministic tie、60/60、20×3、manifest、validator、参数固定、输入
  hash 漂移拒绝、分数与原算法逐 pair 一致、alias 独立成行、label-free 字段；
- 全量离线测试：351 项通过，0 failure / 0 error；
- Basic Quality Gate：PASSED，0 error / 0 warning；
- `git diff --check`：无问题。

## 8. 边界表述

本次交付只产生三个冻结的 method ranking artifact 及其 provenance，**不包含**
任何基于 approved benchmark 的指标比较结论。后续评价应由统一评价阶段在 artifact
冻结后读取 strict approved benchmark 完成；结果只能表述为"在该固定 60-pair 池与
Pilot Benchmark 上的 Query-Relevance ranking 差异"。
