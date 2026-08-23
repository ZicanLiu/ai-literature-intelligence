# W5 Hard Negative 与 Error Taxonomy 分析设计

## 1. 范围与正式数据链

本工具服务 Issue #54，只分析固定 60-pair Candidate Pool 内的 Query Relevance ranking。
它不修改 ranking 算法、Research Query、Candidate Pool、annotation 或 approved benchmark，也不
自动产生方法优劣或科研结论。

正式数据链只有一条：

```text
一个或多个 W5 method manifest
→ src.w5_method_contract.validate_method_output()
→ strict approved W4 benchmark
→ frozen W4 Query Boundary taxonomy mapping
→ pair_id + research_query_id join
→ deterministic analysis outputs
```

所有 method manifest 必须先全部通过公共 validator，之后程序才验证并读取 approved benchmark
的 `final_label`。任一 method 无效时整体 fail closed，不读取 label、不写输出。

## 2. Taxonomy 与 judgement provenance

Taxonomy 的唯一事实源是：

- `data/analysis/w4_query_boundary_examples.csv`；
- `docs/reports/week4/W4_QUERY_BOUNDARY_AND_HARD_NEGATIVES.md`。

提交的 `data/analysis/w5_error_taxonomy/w5_taxonomy_mapping.csv` 是对 W4 CSV 的确定性转换，逐行
保留：

```text
example_id
pair_id
research_query_id
example_role
boundary_type
boundary_reason
source
```

程序会先核对 frozen W4 source hash，再把 mapping 与 source 重新生成的期望结果逐行比较，
拒绝 source 或 mapping 的手工漂移。`scope_in`、
`hard_negative`、`boundary` 原样保留；非 `scope_in` 的 error type 使用现有
`boundary_type`。没有 W4 evidence 的 benchmark pair 统一为 `unclassified`，不补造类别。

Judgement 的唯一来源是通过 strict validator 的 approved W4 benchmark `final_label`。旧的
12-pair `data/w5_error_cases.csv` 已删除；它不再是输入或第二套 label 事实源。

## 3. Identity、rank 与固定判定

- 主 identity：`pair_id`；同时验证 `research_query_id` 一致；
- same-paper alias 保留为不同 pair，不按 `openalex_id` 合并；
- rank 直接使用 W5 Contract 已验证的每 RQ `1..20`，不依赖 CSV 行序；
- Irrelevant Top-K：`final_label == 0` 且 `rank <= 5/10`；
- Relevant Buried：`final_label == 2` 且 `rank >= 11`；
- Hard Negative Top-K：W4 `example_role == hard_negative` 且 `rank <= 5/10`；
- Cross-method Rank Shift：同一 pair 的 `max(rank) - min(rank) >= 10`。

阈值在代码和 `analysis_summary.json` 中固定记录，不根据正式结果回调。

## 4. Coverage

Coverage 的 benchmark denominator 固定为 approved benchmark 的 60 pair。当前 frozen W4
taxonomy evidence 为 20 pair：

| example_role | evidence pair | benchmark denominator |
| --- | ---: | ---: |
| `scope_in` | 6 | 60 |
| `hard_negative` | 12 | 60 |
| `boundary` | 2 | 60 |
| `unclassified` | 40 | 60 |

运行时 `coverage.csv` 同时给出 `benchmark_coverage`（denominator 60）和
`taxonomy_evidence_distribution`（denominator 20），避免把 evidence subset 表述成整个
benchmark。

## 5. 输出

所有内容先在内存完成计算和序列化，再由 CLI 写入目标目录：

- `analysis_summary.json`：benchmark/method/taxonomy hash、固定阈值和输出行数；
- `pair_analysis.csv`：每个 method × pair 的 label、per-RQ rank 与 taxonomy join；
- `method_error_type_matrix.csv`：long-form Method × W4 Error-Type 统计；
- `error_cases.csv`：irrelevant Top-K、relevant buried、hard-negative Top-K；
- `rank_shifts.csv`：达到固定阈值的跨方法 pair-level rank shift；
- `coverage.csv`：benchmark coverage 与 evidence distribution。

`irrelevant_top5/10` 只由 approved `final_label == 0` 产生，不把所有 taxonomy case 自动视为
irrelevant。

## 6. CLI

```powershell
python -m app.analyze_w5_errors `
  --manifest <method-a>/manifest.json `
  --manifest <method-b>/manifest.json `
  --output-dir <analysis-output-dir>
```

`--manifest` 至少出现一次；重复传入即可比较多个方法。默认 benchmark 和 taxonomy 路径指向
当前 approved W4 v0.1 与提交的 W4-derived mapping，也可显式传入以便验证和测试。

## 7. 解释边界

输出只描述固定 Candidate Pool、approved Query-Relevance judgement 和 validated ranking 上的
事实统计。例如可以报告某方法在 `wrong_modality` 中有多少 Top10 false positives，但不能据此
自动断言该方法不适合科研检索，也不能使用本分析结果反向修改 benchmark、taxonomy 或方法参数。
