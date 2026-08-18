# W5 BM25 与 B0/B1 基线 Artifact 报告

**日期:** 2026-08-18（PR #56 第一轮审查后修订）
**任务来源:** Issue #51（[W5-蒲正杰] 实现 BM25 稀疏排序并导出 B0/B1 统一基线 Artifact）
**实验性质:** 固定 60-pair Candidate Pool 上的 Query-Relevance ranking/reranking，
不是端到端 retrieval recall benchmark
**协议:** [`W5_METHOD_RANKING_CONTRACT.md`](../../project/W5_METHOD_RANKING_CONTRACT.md) v1.0

---

## 1. 交付物

三个符合 W5 Method Ranking Contract v1.0 的 method ranking package，全部通过
`python -m app.validate_w5_method` 严格校验（60/60 pair、每 RQ 20/20）：

| method_id | family | ranking.csv SHA-256 | manifest.json SHA-256 |
| --- | --- | --- | --- |
| `bm25_v1` | sparse | `4594272eb56ee6463efe31bb270041e01f2ba313a33d98d840162df33a28992c` | `3730a6486bf69995772d809d8ec9e9816fc6759d8c500fb0a11394830ec34195` |
| `preliminary_score_v1` | baseline | `0fdd1679405322ccc623f4f528e153e3c251d2f44aed2aaa661f37b1f1e7b9d5` | `5c12491c8859ecede1bd76edaadd9cf29577fe313f519cc48303fed6cfabc9f8` |
| `tfidf_two_stage_v1` | baseline | `29188a495e9e05cdb8853fb5bd3bf3b22972e5cba8b84b4a6724575e74c84df5` | `383ec9d70c13f0e0d7c854477e0dc212293fd107512cbb32fe1245fb5052e24d` |

输出目录：`data/analysis/w5_methods/<method_id>/`（各含 `ranking.csv` 与
`manifest.json`）。三个 package 均在 clean Git 工作树（代码提交 `ecfb23c`）上
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
  title，不删除 pair；
- **跨进程确定性**：查询词项按 `sorted(set(query_tokens))` 的固定顺序累加，
  不依赖无序 `set` 遍历（其顺序受 `PYTHONHASHSEED` 影响）；有专门的跨
  `PYTHONHASHSEED` 子进程回归测试保证同一代码与输入产出完全一致的 CSV hash，
  未使用任何低精度 round 来掩盖尾差。

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

## 5. 已知冲突：B0/B1 的 source sample 输入与 Contract v1.0

B0/B1 的现有算法除了 Candidate Pool 和 Research Query 之外，还会从

`data/samples/w2/domain_query/live_query_sample.csv`
（SHA-256 `d9179396b22b223e58a730fc41a97f6c7f6a5c976042a97a881e51bc956eda34`）

补回 `cited_by_count`、`authors`、`source_name` 等评分所需字段（Candidate Pool
本身不含这些字段）。审查已用 negative probe 证实：仅修改该文件中某条记录的
`cited_by_count`，在 Candidate Pool 与 Research Query 完全不变时，B0/B1 的
score/rank 会发生变化。因此 source sample 是 B0/B1 的**真实评分输入**，但当前
W5 Contract v1.0 的 manifest `inputs` schema 是精确字段集
`{candidate_pool, research_queries}`，没有声明它的槽位。

处理原则（遵循审查意见，不擅自修改公共 Contract 或冻结数据）：

- B0/B1 继续原样复用现有算法，不删除 `cited_by_count` 等输入、不改评分公式；
- 该 source sample 已锚定在 `src.w4_benchmark_validation.TRUSTED_W4_V01_INPUTS`
  的 `source_sample` 与冻结 `pool_manifest_v0.1.json` 中，hash 可验证；本项目
  生成路径（`export_w5_baselines`）读取时即使用该锚定路径；
- **建议的最小 Contract 扩展（v1.1）**：在 `inputs` 中增加可选的
  `source_sample` 槽位（同样含 path/sha256/version，并与
  `TRUSTED_W4_V01_INPUTS["source_sample"]` 对齐），供 B0/B1 这类依赖派生评分
  特征的 baseline 声明真实输入闭包；BM25 等只读 pool+query 的方法不受影响；
- 在公共 Contract 更新前，当前 B0/B1 artifact 的输入闭包以本节为准；待 owner
  统一更新 Contract 后，将基于最新 main 重新冻结 B0/B1 artifact。

## 6. Label-free 声明

三个 artifact 的 ranking generation 阶段均未读取 approved benchmark 的
`judgements.csv`/`final_label`、任何 annotation、agreement、Blind AI Audit 或
adjudication 结果，也未使用任何由正式 label 计算的指标。代码路径上不存在接受
label 的入口；manifest 中 `label_access.benchmark_labels_read = false`。

## 7. 复现命令

生成器在写出任何输出前采集 Git 状态，dirty 或无法确认 clean 时拒绝生成。因此
**复现验证时请把输出写到仓库外临时目录**，两个生成器即可连续执行（本流程已
实际完整运行验证）：

```powershell
# 前置：clean Git 工作树
$OUT = Join-Path $env:TEMP "w5_repro"   # 仓库外临时目录
python -m app.run_bm25_ranking --output-dir "$OUT/bm25_v1"
python -m app.export_w5_baselines --output-root "$OUT"

# 校验
python -m app.validate_w5_method --manifest "$OUT/bm25_v1/manifest.json"
python -m app.validate_w5_method --manifest "$OUT/preliminary_score_v1/manifest.json"
python -m app.validate_w5_method --manifest "$OUT/tfidf_two_stage_v1/manifest.json"
```

正式 artifact 的冻结流程：提交代码使工作树 clean → 按上述命令生成到仓库外 →
将三个 package 拷入 `data/analysis/w5_methods/` → 提交 artifact。重新生成时
`ranking.csv` 的内容与 hash 应与仓库中已提交版本完全一致（BM25 已保证跨
`PYTHONHASHSEED` 确定性）；`manifest.json` 中 `generated_at`/`duration_seconds`
随运行时间变化，属正常的 provenance 差异。

## 8. 验证结果

- 定向测试：`test_bm25_ranking.py`（16 项）与 `test_w5_baseline_export.py`
  （9 项）全部通过，覆盖 term 不存在、TF 饱和、长度归一化、缺 abstract、
  同分 deterministic tie、60/60、20×3、manifest、validator、参数固定、输入
  hash 漂移拒绝、分数与原算法逐 pair 一致、alias 独立成行、label-free 字段，
  以及跨 `PYTHONHASHSEED`（0 与 12345）子进程生成 hash 完全一致；
- 全量离线测试：352 项通过，0 failure / 0 error；
- `python -m app.validate_w4_benchmark`（strict approved）：通过；
- 三个 `app.validate_w5_method`：全部通过；
- Basic Quality Gate：PASSED，0 error / 0 warning；Full Quality Gate：PASSED，
  仅 3 个与公共基线一致的历史 warning；
- `git diff --check`：无问题。

## 9. 边界表述

本次交付只产生三个冻结的 method ranking artifact 及其 provenance，**不包含**
任何基于 approved benchmark 的指标比较结论。后续评价应由统一评价阶段在 artifact
冻结后读取 strict approved benchmark 完成；结果只能表述为"在该固定 60-pair 池与
Pilot Benchmark 上的 Query-Relevance ranking 差异"。
