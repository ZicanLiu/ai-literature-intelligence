# W6 Multi-Retriever Candidate Pool Builder

## 1. 交付范围

本任务实现了算法无关的 Multi-Retriever Candidate Pool Builder。它从冻结的 W6 Topic Set、一个
或多个 retrieval provenance artifacts、source records 和 hash-pinned pooling policy 构建：

```text
merged retrieval provenance
+ pre-canonical Candidate Pool
+ label-free pool statistics
+ hash-bound build manifest
```

该 Builder 解决 W4/W5 fixed-pool ranking 无法观察不同 retrieval family 候选覆盖差异的问题，但
本成员 PR 仍只使用 synthetic Bootstrap fixtures。它没有选择真实 W6 Topic、执行 live retrieval、
生成真实 Candidate Pool、读取 relevance labels、进行 canonicalization 或计算 ranking metrics。

## 2. 架构与 retriever abstraction

业务逻辑位于 `src/w6_candidate_pool_builder.py`，CLI 位于
`app/build_w6_candidate_pool.py`，依赖方向保持 `app → src`。

Builder 只读取统一的 `w6_retrieval_provenance` run/hit contract，不导入或复制 OpenAlex、BM25、
SPECTER2、Cross-Encoder 的具体评分实现。未来 retriever 只需把自己的冻结输出适配成：

- run：topic/query variant、acquisition system、method/model、配置及 hash、seed、时间、Git 和输出 hash；
- hit：run、record、source rank、raw score/direction 和 retrieval time。

`RetrievalArtifactBackend` Protocol 隔离 artifact 来源。正式 CLI 使用显式本地 JSON backend，测试
使用 deterministic fake backend；两者都不会联网或加载模型。

多个 retrieval artifacts 会先逐个通过公共 W6 validator，再按稳定 ID 合并。重复 artifact ID、
run ID 或 hit ID fail closed；合并结果的 runs 按 ID 排序，hits 按 run/rank/hit ID 排序。Candidate
Pool 只需绑定一个聚合 retrieval artifact，因此不需要修改 Benchmark schema。

## 3. Broad Recall Universe 与 pooling policy

Broad Recall Universe 的 identity unit 为：

```text
(topic_id, record_id)
```

它不是 canonical paper identity。同一真实论文的多个 source records 可以在 pre-canonical 阶段同时
存在；同一个 record 跨 topic 出现时也是两个不同的 pool items。

冻结 policy 明确记录：

- included retrieval run roster；
- per-system depth 与可选 per-run override；
- target/minimum size（支持公共整数或逐 topic mapping）；
- deterministic random seed 与是否补齐；
- target overflow policy；
- duplicate-hit handling。

正式 Builder v1 的 target 是 fill-to target：depth union 小于 target 时，可从同一 included-run
Broad Universe 的剩余 topic-records 中确定性补齐；超过 target 时全部保留。minimum 是硬下限，
不足时在写出任何 artifact 前失败。随机实现使用局部 `random.Random`，seed 通过 SHA-256 按 topic
派生，候选采样前先排序，不使用进程相关的 Python `hash()`。

测试 policy 的 SHA-256 为：

```text
cdb6508ba7e62ec1daf122901c93abb94e0f5dfdd30d5f5ff5a98a2261b99713
```

该配置只用于接口测试，不提前决定真实 W6 的 run roster、depth、target、minimum 或 seed。

## 4. Exact provenance union

depth 与 provenance 是两个不同阶段：

1. `source_rank <= resolved_depth` 决定某个 run 是否让 topic-record 入池；
2. 一旦入池，member 的 `retrieval_hit_ids` 必须回收 included roster 中该 topic-record 的全部 hits；
3. `source_system_membership` 是这些完整 hits 对应 acquisition systems 的精确去重并集。

因此，若论文在 BM25 中 rank 1、在 OpenAlex 中 rank 30，而 OpenAlex depth 为 10，它仍可因 BM25
入池，并必须保留 OpenAlex rank 30 的 hit provenance。selection reason 只说明 admission，不能替代
完整 provenance。

同一 topic-record 在同一或不同 run 中重复命中时，只生成一个 pool member，但不删除任何合法
hit reference。公共 `validate_candidate_pool()` 会重新从冻结 roster 计算 expected union；即使删除
hit 后重新计算 `pool_identity`，验证仍然失败。

## 5. Pre-canonical 与 no-label 边界

输出固定为 `identity_stage=pre_canonicalization`：

- inputs 只绑定 topic set、merged retrieval provenance 和 source records；
- 所有 `canonical_entity_id` 都是 `null`；
- 不读取 canonical mapping；
- 不读取 annotation、judgement、approved benchmark 或 ranking evaluation；
- CLI 没有 label、benchmark、judgement 或 canonical 参数。

selection reasons 只记录算法事实，例如 `depth_qualified:<run_id>`、
`deterministic_random_fill`、`multi_system_provenance`。Bootstrap pool 中用于说明 fixture 设计的
`hard negative`、`partial relevance` 等文字不会作为 Builder 输入或真实选择依据。

## 6. Score direction 与 duplicate handling

当前公共 W6 retrieval contract 要求：

- 有限数值 score 使用 `higher_is_better`；
- `source_score=null` 使用 `not_applicable`。

Builder 以冻结 `source_rank` 应用 depth，不跨系统比较 raw scores。原始算法若越低越好，应在
retriever adapter 中做确定性转换（例如 negative Euclidean distance），不能向当前 contract 写入
`lower_is_better`。NaN、Infinity、非法 direction 和重复 source rank 均由公共 validator 拒绝。

duplicate policy 的含义是：candidate identity 按 topic-record 去重，完整 hit provenance 不去重。
完全重复的 hit ID 或 run ID 视为 artifact collision，直接失败。

## 7. Pool diagnostics

统计输出与 Candidate Pool 分文件保存，避免给严格 `w6_candidate_pool` schema 增加额外字段。当前
diagnostics 包括：

- input artifact/run count 与 included run count；
- raw hit count、depth-eligible hit count；
- global unique record count 与 unique topic-record count；
- per-system raw hit、pool-member 和 single-system-only contribution；
- multi-system、single-system-only、pool size 和 topic counts；
- target overflow 与 minimum satisfaction。

`multi_system_hit_count` / `single_system_only_count` 的计数单位都是已选 topic-record pool member。
这些统计只描述 pooling composition，不使用 relevance label，因此不能被解释为 recall、precision、
系统优劣或 Pool Bias Audit 结论。

## 8. Artifact 与复现

CLI 输出固定为：

```text
<output-dir>/
├── retrieval_provenance.json
├── precanonical_candidate_pool.json
├── pool_statistics.json
└── build_manifest.json
```

Candidate Pool 通过 input artifact ID/hash、完整 policy、topic counts 和稳定排序 members 计算公共
`pool_identity`。外部 policy 文件必须同时提供预注册 SHA-256；build manifest 固定全部输入 identity、
输出文件 hash、Git SHA/clean state、Python/平台、开始时间和耗时，并声明没有读取 benchmark labels。

聚合 retrieval artifact 的时间锚定为冻结输入中最晚的 `created_at`，而不是本次重跑时间。因此在
相同代码 revision、输入和 policy 下，不同时间重跑仍得到相同 merged retrieval hash 和 pool
identity。实际运行时间保存在 pool/statistics/build manifest 的 generation provenance 中。

`frozen` 状态只能在生成开始前 clean Git worktree 上运行；`candidate` 状态允许开发期临时输出。
输出目录必须不存在或为空，避免静默覆盖已经冻结的 artifact。

## 9. 完全离线测试

`tests/automated/test_w6_candidate_pool_builder.py` 覆盖：

- multi-query、multi-retriever 和 N-artifact merge；
- single-retriever-only candidate；
- duplicate hits 与 exact provenance union；
- below-depth hit 的完整保留；
- missing/extra hit、run roster drift、policy/output hash drift；
- score direction 与 NaN/Infinity；
- input order、seed、build time 和 pool identity 的确定性；
- target overflow、minimum failure 和 random fill；
- pre-canonical 不依赖 canonical mapping；
- public W6 Candidate Pool validator；
- fake backend 不触发 HTTP；
- CLI 无 label/benchmark/canonical 参数；
- frozen build 的 clean-worktree 要求。

运行方式：

```bash
python -m app.validate_w6_bootstrap
python -m unittest tests.automated.test_w6_candidate_pool_builder -v
python -m unittest discover -s tests/automated -p "test_*.py" -q
python -m app.quality_gate --level basic
```

## 10. 已知限制与 Integration 边界

- 本 PR 不执行真实 OpenAlex 或模型 retrieval；
- 不决定真实 topic、query variants、retriever roster 或 pool sizes；
- 不做 canonicalization、metadata enrichment、bias audit、annotation 或 ranking evaluation；
- 当前 statistics 不能证明未检出文献是否相关；
- 不实现跨 retriever score normalization/fusion；
- 当前公共 retrieval contract 统一为 higher-is-better，lower-is-better 算法需由 adapter 转换；
- 真实全 Topic pool 必须在成员 PR 合并后的独立 Integration PR 中生成、验证和冻结。
