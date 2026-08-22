# W5 通用 RRF 混合排序融合报告

**日期:** 2026-08-17
**分支:** `feature/w5-rrf-hybrid-fusion`
**目标:** 实现算法无关的 Reciprocal Rank Fusion（RRF）混合排序模块，并用公共 fixture 完成开发与验证。

---

## 1. 目标与边界

W5 计划比较 sparse（BM25）与 dense（SPECTER2）的互补性，最终形成：

```text
BM25 + SPECTER2 → Reciprocal Rank Fusion → Hybrid Ranking
```

本任务**不依赖 BM25 / SPECTER2 PR**。W5 Bootstrap 已提供 `lexical_fixture.csv`、
`dense_fixture.csv`、W5 Ranking Contract 和 validator。本模块只实现通用 RRF，等所有相关
PR 合并后，组长只需把真实 BM25 / SPECTER2 manifest 传入即可生成正式 Hybrid artifact。

---

## 2. RRF 定义

```text
RRF_score(d) = Σ 1 / (k + rank_i(d))
```

- 固定 `k = 60`，第五周不调参；
- 不做 grid search、不引入人工权重、不用 benchmark label 调融合；
- 纯 rank-based，与各输入分数尺度无关。

---

## 3. 输入

输入是两个或更多已经通过 W5 validator 的 method manifest（package）。模块只依赖公共字段：

```text
pair_id
research_query_id
rank
```

以及 manifest identity（method_id、manifest/ranking SHA-256、frozen input path）。不依赖
BM25 / SPECTER2 / Cross-Encoder 的任何特定字段。

### 融合前校验

- 每个输入自身通过 W5 validator；
- Candidate Pool 路径一致；
- Research Query 路径一致；
- pair identity（`pair_id` + `research_query_id` 集合）完全一致；
- 每个 RQ 恰好 20 条；
- method_id 不重复；
- 不允许把同一个 manifest / ranking artifact 融合两次。

---

## 4. 输出

输出继续遵守 W5 Method Ranking Contract：

- `family = hybrid`；
- `ranking.csv` 严格为 `pair_id,research_query_id,method_id,score,rank`；
- 每个 RQ 内按 `score 降序 → pair_id 升序` 重排，rank 覆盖 `1..20`；
- manifest 的 `parameters` 记录 `rrf_k`、输入 method_id、输入 manifest/ranking hash、
  以及 `input_order_semantic`（RRF 求和可交换，为 `order_independent`）；
- `label_access.benchmark_labels_read = false`，只使用排名，不读取任何 label/judgement。

---

## 5. 文件清单

| 文件 | 作用 |
|------|------|
| `src/w5_rank_fusion.py` | 通用 RRF 融合核心（compute_rrf_score / validate_fusion_inputs / fuse_rankings） |
| `app/fuse_w5_rankings.py` | 融合 CLI，读入多个 manifest，输出 hybrid package 并自检 |
| `tests/automated/test_w5_rank_fusion.py` | 26 个离线自动测试 |
| `docs/reports/week5/W5_RRF_FUSION.md` | 本报告 |

未修改：BM25 / SPECTER2 / Cross-Encoder 代码、W5 Contract、Benchmark、Candidate Pool、
Research Query、existing ranking。

---

## 6. 关键设计决策

### 6.1 精确有理数求 RRF 分

`compute_rrf_score` 使用 `fractions.Fraction` 累加，避免浮点非结合性导致“同一数学结果
因输入顺序不同产生不同浮点值”。这保证：

- 确定性并列（deterministic tie）；
- RRF 对输入顺序不敏感（求和可交换）；
- 测试可用精确 `Fraction(141, 4880)` 断言数学结果。

排序键使用精确 `Fraction`（`-score → pair_id`），而不是 `-float(score)`，因此决定 rank 的
数学顺序不会被序列化成 float 后的碰撞改变。写入 artifact 前会检查“不同精确分数是否映射成
相同 float”：若发生这种精度碰撞，而当前 Contract 只能以 float 表达 `score`、无法无损区分，
则 **fail closed**，拒绝生成一个数学顺序已经失真的正式 artifact，而不是静默按 `pair_id`
错误排序。

### 6.2 固定 k=60（正式方法约束）

`RRF_K = 60` 是 W5 Method Ranking Contract 层级的固定常量（Issue #53）。正式 fusion 入口
`fuse_rankings` 和 manifest 构造 `build_manifest` 均不再接受外部 `k` / `rrf_k` 传值，始终使用
`RRF_K`。W5 validator 会拒绝 `parameters.rrf_k != 60` 的 hybrid artifact。可参数化的
`compute_rrf_score(..., k=...)` 仅作为数学 helper 保留给单元测试。

### 6.3 确定性并列

lexical 与 dense fixture 在 RQ01 内呈对称反向，`w4_rq01_001`（1/61 + 1/80）与
`w4_rq01_020`（1/80 + 1/61）数学上完全相同，产生并列。并列按 `pair_id` 升序打破：

```text
w4_rq01_001 → rank 1
w4_rq01_020 → rank 2
```

这验证了 contract 的 `score_desc → pair_id_asc` tie-breaking 在 RRF 输出中一致成立。

### 6.4 输入顺序语义

RRF 求和是可交换的，因此输入顺序不影响分数；manifest 以 `input_order_semantic =
order_independent` 显式记录这一点，同时仍保留输入 method_id 顺序供 provenance 追踪。

### 6.5 输出安全与端到端 duration

CLI 在写文件前预检 `method_id` 格式、Git clean/完整 revision 与输出目录安全（禁止与任一输入
package 重合、默认拒绝覆盖非空目标），并在临时目录完整生成 + 通过 validator 自检后才发布到
最终 `--output-dir`；任何失败都不会在最终目录留下半成品。`generation.duration_seconds`
记录从输入处理到 ranking 写出的端到端 generation 时长，而非仅 fusion 核心耗时。

---

## 7. 测试覆盖

| 场景 | 结果 |
|------|:---:|
| 两个合法 fixture 融合且确定性 | ✓ |
| 多输入（3 个）融合 | ✓ |
| RRF 数学结果（精确 Fraction） | ✓ |
| k=60 固定（`fuse_rankings` 拒绝外部 `k`） | ✓ |
| 确定性并列（pair_id tie-break） | ✓ |
| identical ranks 保持顺序 | ✓ |
| 输入 method_id 重复拒绝 | ✓ |
| 同一 artifact 融合两次拒绝 | ✓ |
| pair identity 不一致拒绝 | ✓ |
| RQ 不一致拒绝 | ✓ |
| Candidate Pool 不一致拒绝 | ✓ |
| invalid manifest 拒绝（CLI） | ✓ |
| 输出通过 W5 validator | ✓ |
| hybrid manifest 拒绝 `rrf_k != 60` | ✓ |
| Fraction→float 精度碰撞 fail closed（直接 + 75 方法端到端） | ✓ |
| CLI output 与输入 package 重合拒绝 | ✓ |
| CLI 覆盖已有非空 output 目录拒绝 | ✓ |
| CLI 非法 method_id / dirty worktree 不留半成品 | ✓ |
| CLI 融合并自检通过 | ✓ |
| 不访问 label（label_access=false） | ✓ |

全部 26 个测试离线，无网络请求。

---

## 8. 复现命令

```powershell
# 测试（项目标准 unittest 方式）
python -m unittest tests.automated.test_w5_rank_fusion -v

# 或使用当前仓库既有的标准 discovery
python -m unittest discover -s tests/automated -p "test_*.py" -v

# 用两个 fixture 生成一个 hybrid package（需先构造输入 manifest，见测试 helper）
python -m app.fuse_w5_rankings `
  --manifest <lexical manifest.json> `
  --manifest <dense manifest.json> `
  --method-id rrf_hybrid_v1 `
  --output-dir <dir>

# 验证输出
python -m app.validate_w5_method --manifest <dir>/manifest.json
```

正式 hybrid artifact 在所有 BM25 / SPECTER2 PR 合并后由组长统一生成，本 PR 不伪造正式
实验结果。

---

## 9. Label Leakage 说明

RRF generation 完全不需要 benchmark labels。代码只读取 ranking CSV 的 `pair_id`、
`research_query_id`、`rank` 与 manifest 身份，不读取 `judgements.csv`、annotation、
agreement、AI audit、metrics 或 error-analysis。manifest 显式声明
`benchmark_labels_read = false`。
