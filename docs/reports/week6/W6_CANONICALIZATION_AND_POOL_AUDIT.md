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

1. **normalized DOI**（authoritative）：精确相同 → 同一 canonical entity（confirmed，high）。
   同一 DOI 可调和不同 provider 的 OpenAlex ID（`rec_003` / `rec_008`）。
2. **normalized OpenAlex ID**：精确相同 → 同一 entity，但仅当合并后的 component 不产生
   DOI 冲突（`≤1` 个非空 DOI）。
3. **normalized title**：精确相同 → 同一 entity，但仅当（a）title 非 generic（`≥3` 个
   token）、（b）无 DOI 冲突、（c）无 OpenAlex 冲突。

一个 confirmed component 必须满足 **identity 一致性不变量**：

- 至多一个非空 normalized DOI；
- exact DOI group 可以调和不同 provider OpenAlex ID；
- exact OpenAlex group 不得产生 DOI 冲突；
- exact title group 必须作为整体保持无歧义：存在多个带 OpenAlex identity 的 component 时，它们
  必须具有真实 shared OpenAlex identity。某个 component 内已有 DOI 不能替另一个仅凭 title、且
  OpenAlex 不相关的 record 提供“调和”。

同一个 identity key 的全部待合并 components 会整体进行 compatibility 判断，不使用会因 anchor / union
顺序而改变结果的 greedy partial merge。

“title 很像”不直接当作同一论文：只有精确 normalized title 一致才是 high-confidence title
identity；模糊相似 title 只进入 suspected relationship；generic/empty title 不作为自动
confirmed identity。

## 3. Confirmed / Suspected 边界

- 只有 `high + confirmed` 的多 record alias group 才映射为同一 canonical entity。
- 低/中置信候选（模糊 title 相似、同 title 不同 DOI、同 OpenAlex 不同 DOI 等 conflicting
  identity）进入 `suspected_relationships`（`relationship_type = suspected_duplicate`，
  `review_state = pending_review`），保持两个独立 entities。
- 不为减少 pool size、提高指标或方便代码而自动合并 suspected duplicate，也不做跨 identity
  类型的 transitive chaining 合并。

fixture 验证：

- `rec_003` + `rec_008`：normalized DOI 均为 `10.5555/fixture.alias`（不同 provider 的
  OpenAlex ID）→ confirmed alias，映射为 `entity_rec_003`。
- `rec_005` + `rec_010`：标题高度相似但 DOI 不同（`fixture.005a` vs `fixture.005b`）→
  suspected duplicate，保持 `entity_rec_005` / `entity_rec_010` 两个独立 entities。

adversarial 回归覆盖：不同 OpenAlex + 相同 title、相同 OpenAlex + 不同 DOI、
相同 title + 不同 DOI、DOI/title bridge、输入顺序 permutation、transitive conflict、generic title，
均不错误 confirmed merge。

## 4. Provenance Preservation

- source record identity（`record_id`、provider、`source_record_id`）不变；
- alias、retrieval hit、retrieval system、query variant、source rank/score provenance 全部保留；
- post-canonical pool 仅对每个 member 填充 `canonical_entity_id`，其余字段（`retrieval_hit_ids`、
  `source_system_membership`、`selection_reasons`）与 pre-pool 逐字节一致；
- canonical entity 记录 `alias_record_ids`、`identity_evidence`、
  `source_retrieval_provenance_union`（alias 记录 retrieval hit 的并集）与
  `canonicalization_provenance`（tool/version/git/reviewer）；
- `identity_evidence` 只记录真实发生的 identity：每个 evidence 的 `record_ids` 精确等于匹配该
  value 的 records，`normalized_title` evidence 只在多个 record 真正共享该 title 时产生，不按
  preferred record 事后伪造覆盖整个 alias group 的 title evidence。

## 5. Post-canonical Pool 确定性转换

`build_post_canonical_pool()` 从 pre-pool 到 post-pool：

- 保留全部 members、`policy`、`topic_counts`；
- 每个 member 依据 canonical mapping 填充 `canonical_entity_id`；
- `identity_stage → post_canonicalization`，`inputs` 增加 `canonical_entities` 引用；
- 重算确定性 `pool_identity`（`compute_pool_identity`）。

输出通过 `validate_candidate_pool()`。

## 6. Pool Bias Audit 指标

`src/w6_pool_audit.audit_pool_bias()` 从已验证 post-canonical pool 的 frozen policy
（`included_retrieval_run_ids`）派生 retriever roster，并校验 pool member hits → retrieval
runs → acquisition systems → frozen roster 的完整闭包；不接受 caller 额外传入的可漂移 roster。
指标使用 hit/run 派生的 acquisition system 作为 source of truth；member 自报的
`source_system_membership` 必须与派生集合精确一致，否则 fail closed。
同一 acquisition_system 在多个 included runs 中声明不同 family 时 fail closed。审计在
record-level 与 canonical entity-level 两层分别报告：

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
| `src/w6_canonicalization.py` | confirmed 聚类（identity 一致性）、truthful evidence、preferred record、post-pool 转换 |
| `src/w6_pool_audit.py` | label-free pool bias audit（roster 闭包校验 + overlap/unique/multi-system/LOO/alias sensitivity） |
| `src/w6_contracts.load_canonicalization_inputs` | task-scoped、label-free 最小输入闭包 loader |
| `app/canonicalize_w6.py` | 薄 CLI：load → canonicalize → post-pool → audit → 文件 SHA → 自检 → 原子发布 |
| `tests/automated/test_w6_canonicalization.py` | 39 个离线测试 |
| `tests/automated/test_w6_pool_audit.py` | 15 个离线测试 |

未修改：W4/W5 frozen artifacts、W6 Bootstrap fixtures、既有 Bootstrap validator 语义、
Candidate Pool、Benchmark。Shared `w6_contracts.py` 只为 task-scoped loader 增加 fixture identity
一致性检查与可信传播值。

## 8. 测试覆盖

- exact DOI identity / exact OpenAlex identity / title normalization；
- confirmed alias / suspected duplicate / conflicting identity；
- 不同 OpenAlex + 相同 title / 相同 OpenAlex + 不同 DOI / transitive conflict / generic title；
- evidence truthfulness（同 DOI/OpenAlex 不同 title 不伪造 title evidence）；
- preferred record（确定性，canonical ID 绑定最小 alias 而非 preferred）；
- source record retention（pre→post 逐字段一致）；
- retrieval provenance union；
- pre→post mapping + post-pool 通过 contract validator；
- deterministic identity；
- leave-one-retriever-out（record / entity 两层）；
- record/entity-level counts 与 alias sensitivity；
- hash drift（canonical reference 漂移被拒绝）；
- 最小依赖闭包 loader + process-level 只打开 4 个输入、不读 downstream artifact；
- CLI 内嵌 SHA == 实际落盘文件 SHA；CLI 拒绝覆盖冻结输入树 / 非空目标；
- audit roster 闭包（unknown run / 删 roster 后 member hit 失配 / 同一 system 冲突 family）。
- audit system membership 闭包（missing / extra / wrong system 均 fail closed，指标只使用 hit 派生值）；
- 四个 task-scoped inputs 与 bundle manifest 的 `is_fixture` 一致性；all-true / all-false 传播，mixed
  fail closed；
- sibling staging directory 完整生成和验证后一次 rename 发布；故障注入不会在 final path 留下
  partial package。

## 9. 复现命令

```powershell
python -m unittest tests.automated.test_w6_canonicalization -v
python -m unittest tests.automated.test_w6_pool_audit -v

python -m app.canonicalize_w6 --output-dir <dir>
```

## 10. 已知限制

- 真实 canonicalization rules 的 review 阈值（title 相似阈值 0.80、title identity 最少 3 token）、
  更丰富的 identity evidence 与 sensitivity 报告仍属后续 Issue；本任务只提供可解释、确定性的
  baseline。
- Pooled coverage 不代表真实 recall；本 audit 只描述 retriever 对当前 pooled candidate set 的
  贡献结构。
- `included_retrieval_run_ids` 的顺序仍是 frozen policy 的一部分（`compute_pool_identity`
  按原样纳入 policy），本 PR 不擅自修改共享 contract；若需 canonical sort 属于独立 contract
  变更。
