# W6 Candidate Canonicalization 与 Pool Bias Audit 报告

**日期:** 2026-08-25
**分支:** `feature/w6-canonicalization-pool-audit`
**目标:** 建立 source record → canonical paper entity 的确定性规范化，保留完整 record-level
provenance，并在不使用 relevance labels 的前提下审计 candidate pool 的 retriever 偏差。

---

## 1. 目标与边界

W4 Pilot 是 record-level Benchmark 并保留 same-paper alias；W6 正式区分

```text
source record ≠ canonical paper entity
```

本任务实现：

```text
source records + pre-canonical pool
        ↓ canonical entity mapping
post-canonical pool
        ↓ pool bias audit
retriever overlap / unique contribution / leave-one-retriever-out / alias sensitivity
```

Canonicalization **不是删除重复行**，而是为每个 source record 建立到 canonical entity 的显式映射；
原始 records、retrieval hits 与 provenance 全部保留。Bias Audit 不读取 relevance labels、metrics 或
error analysis，也不把 pooled coverage 称作真实 recall。

---

## 2. Canonical Identity 规则

按可靠度从高到低：

1. **normalized OpenAlex ID**：精确相同 → 同一 canonical entity（confirmed，high）。
2. **normalized DOI**：精确相同 → 同一 canonical entity（confirmed，high）。
3. **normalized title**：精确相同 → 同一 canonical entity（confirmed，high），但**仅当该 title
   group 不含互相冲突的非空 DOI**。

“title 很像”不直接当作同一论文：只有**精确 normalized title 一致**才是 high-confidence title
identity；模糊相似的 title 只进入 suspected relationship。

## 3. Confirmed / Suspected 边界

- 只有 `high + confirmed` 的多 record alias group 才映射为同一 canonical entity。
- 低/中置信候选（模糊 title 相似，或“同一 title 但不同 DOI”的 conflicting identity）进入
  `suspected_relationships`（`relationship_type = suspected_duplicate`，`review_state =
  pending_review`），保持两个独立 entities。
- 不为减少 pool size、提高指标或方便代码而自动合并 suspected duplicate。

fixture 验证：

- `rec_003` + `rec_008`：normalized DOI 均为 `10.5555/fixture.alias`，标题规范化后一致 →
  confirmed alias，映射为 `entity_rec_003`。
- `rec_005` + `rec_010`：标题高度相似但 DOI 不同（`fixture.005a` vs `fixture.005b`）→
  suspected duplicate，保持 `entity_rec_005` / `entity_rec_010` 两个独立 entities。

## 4. Provenance Preservation

- source record identity（`record_id`、provider、`source_record_id`）不变；
- alias、retrieval hit、retrieval system、query variant、source rank/score provenance 全部保留；
- post-canonical pool 仅对每个 member 填充 `canonical_entity_id`，其余字段（`retrieval_hit_ids`、
  `source_system_membership`、`selection_reasons`）与 pre-pool 逐字节一致；
- canonical entity 记录 `alias_record_ids`、`identity_evidence`、
  `source_retrieval_provenance_union`（alias 记录 retrieval hit 的并集）与
  `canonicalization_provenance`（tool/version/git/reviewer）。

## 5. Post-canonical Pool 确定性转换

`build_post_canonical_pool()` 从 pre-pool 到 post-pool：

- 保留全部 members、`policy`、`topic_counts`；
- 每个 member 依据 canonical mapping 填充 `canonical_entity_id`；
- `identity_stage → post_canonicalization`，`inputs` 增加 `canonical_entities` 引用；
- 重算确定性 `pool_identity`（`compute_pool_identity`）。

输出通过 `validate_candidate_pool()`。

## 6. Pool Bias Audit 指标

`src/w6_pool_audit.audit_pool_bias()` 在 record-level 与 canonical entity-level 两层分别报告：

- **Retriever overlap**：任意两个 acquisition system 的共同 candidate 数量（对称矩阵）。
- **Unique contribution**：每个 system 独有的 candidate 数量/比例。
- **Multi-system support**：candidate 被 1/2/3… 个 system 同时发现的直方图。
- **Leave-one-retriever-out**：移除某 system 后损失的 unique records/entities（= 该 system 独有
  candidate）。
- **Alias sensitivity**：pool items / distinct records / distinct entities 的差异，confirmed
  alias 数量，suspected relationship 数量，以及 record→entity 比例。

fixture 结论（仅证明逻辑，非真实 recall）：

| system | record 独有 | entity 独有 |
| --- | --- | --- |
| openalex_native | 3 | 2 |
| bm25_fixture | 1 | 1 |
| dense_fixture | 1 | 1 |
| deterministic_random_tail | 0 | 0 |

`rec_008`（仅 openalex 命中）是 `entity_rec_003` 的 alias，而 `entity_rec_003` 还经 `rec_003` 被
bm25 命中，因此 entity-level 的 openalex 独有损失（2）低于 record-level（3）——这正是 alias
sensitivity 的体现。

## 7. 文件清单

| 文件 | 作用 |
|------|------|
| `src/w6_canonicalization.py` | confirmed 聚类、preferred record、post-pool 转换、provenance union |
| `src/w6_pool_audit.py` | label-free pool bias audit（overlap/unique/multi-system/LOO/alias sensitivity） |
| `app/canonicalize_w6.py` | 薄 CLI：canonicalize → post-pool → audit → 自检 |
| `tests/automated/test_w6_canonicalization.py` | 19 个离线测试 |
| `tests/automated/test_w6_pool_audit.py` | 9 个离线测试 |

未修改：W4/W5 frozen artifacts、Bootstrap contracts、Candidate Pool、Benchmark。

## 8. 测试覆盖

- exact DOI identity / exact OpenAlex identity / title normalization；
- confirmed alias / suspected duplicate / conflicting identity；
- preferred record（确定性）；
- source record retention（pre→post 逐字段一致）；
- retrieval provenance union；
- pre→post mapping + post-pool 通过 contract validator；
- deterministic identity；
- leave-one-retriever-out（record / entity 两层）；
- record/entity-level counts 与 alias sensitivity；
- hash drift（canonical reference 漂移被拒绝）。

## 9. 复现命令

```powershell
python -m unittest tests.automated.test_w6_canonicalization -v
python -m unittest tests.automated.test_w6_pool_audit -v

python -m app.canonicalize_w6 --output-dir <dir>
```

## 10. 已知限制

- 真实 canonicalization rules 的 review 阈值（title 相似阈值 0.80）、更丰富的 identity
  evidence 与 sensitivity 报告仍属后续 Issue；本任务只提供可解释、确定性的 baseline。
- Pooled coverage 不代表真实 recall；本 audit 只描述 retriever 对当前 pooled candidate set 的
  贡献结构。
