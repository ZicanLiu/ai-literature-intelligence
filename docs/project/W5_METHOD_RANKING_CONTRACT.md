# W5 Method Ranking Contract v1.1 与公共实验协议

状态：`v1.1` 已用于 W5 正式基线输入闭包；validator 继续兼容已冻结的 `v1.0`
方法包。适用于 W5 固定 Candidate Pool 上的正式方法比较。

## 1. 实验问题与边界

W5 当前评价是：

> 固定 60-pair Candidate Pool 上的 Query-Relevance ranking / reranking 实验。

它不是端到端 retrieval recall benchmark。所有方法看到的是同一批已经冻结的候选记录，评价的
是它们在每个 Research Query 内如何排序。因此 W5 结果只能支持“在该固定池和当前 Pilot
Benchmark 上，某方法的 ranking 指标更高/更低”等表述，不能声称某方法在整个 OpenAlex 文献
空间中的 retrieval recall 更高。

真正的 retrieval benchmark 需要另行建立 multi-retriever pooling、盲标与未检出相关文献评估，
不属于本协议。

## 2. 冻结 generation 输入

所有正式方法都读取以下两个公共 generation 输入：

| 输入 | 版本 | SHA-256 |
| --- | --- | --- |
| `data/annotation_tasks/w4/candidate_pool_v0.1.csv` | `w4_pilot_v0.1` | `25f608eb4c94218dfa220ba108b15ec846b2bd418174501420a468c376ed17cc` |
| `configs/w4/research_queries.json` | `w4_pilot_v0.1` | `c77ec74ef4567614d3dfb6dab937b85398f95128cdb29e823587715002d99ab1` |

Candidate Pool 固定 60 个 record-level query-paper pair，三个 Research Query 各 20 个。已知
same-paper alias 继续作为不同冻结 record 保留，不得静默合并或删除。

Method ranking generation 不得读取：

- approved benchmark 的 `judgements.csv`、`final_label` 或其他人工答案；
- annotation、agreement、AI proposal、adjudication 或 error-analysis 结果；
- 已经用正式 label 计算出的 W5 指标来回调参数。

Approved benchmark 只在 ranking artifact 已经生成、hash 冻结之后，由 evaluation 阶段读取。

### 2.1 B0/B1 的冻结辅助输入与 v1.1

B0 `preliminary_score` 与 B1 TF-IDF two-stage 复用既有项目算法。Candidate Pool 只保留展示
字段，这两个算法还必须从以下冻结 source sample 补回 `cited_by_count`、`authors`、
`source_name` 等真实评分输入：

| 输入 | 版本 | SHA-256 |
| --- | --- | --- |
| `data/samples/w2/domain_query/live_query_sample.csv` | `w2_live_query_sample_v1` | `d9179396b22b223e58a730fc41a97f6c7f6a5c976042a97a881e51bc956eda34` |

因此 Contract v1.1 要求 B0/B1 manifest 的 `inputs` 精确包含
`candidate_pool`、`research_queries`、`source_sample`。该扩展只修复 provenance 与复现输入
闭包，不改变 baseline 公式、权重、阈值或 ranking。

Backward compatibility：

- v1.0 package 的 `schema_version/contract_version` 仍为 `1.0/1.0`，`inputs` 精确包含两个
  公共输入；BM25、SPECTER2、Cross-Encoder、RRF 等只使用公共输入的已冻结包无需迁移；
- v1.1 package 的版本对为 `1.1/1.1`，`inputs` 精确增加上述冻结 `source_sample`；当前仅
  B0/B1 使用；
- 稳定官方 ID `preliminary_score_v1`、`tfidf_two_stage_v1` 已与 v1.1 绑定；把旧 manifest
  自报为 v1.0、删除 `source_sample` 的 package 会被公共 validator 拒绝，不能进入正式实验；
- multi-method runner 比较所有方法共同的 Candidate Pool / Research Query identity，同时保留
  各方法经 validator 核验的辅助输入，不要求无关方法伪造同一辅助输入。

## 3. Ranking CSV v1.0

每个方法输出一个 UTF-8 CSV，表头和顺序必须严格为：

```csv
pair_id,research_query_id,method_id,score,rank
```

字段语义：

| 字段 | 约束 |
| --- | --- |
| `pair_id` | 必须完整、唯一覆盖冻结 Candidate Pool 的 60 个 `pair_id` |
| `research_query_id` | 必须与该 `pair_id` 在冻结池中的 RQ 完全一致 |
| `method_id` | 稳定、小写、机器可读；整个 artifact 只能有一个值 |
| `score` | 有限数值；统一为越高越相关（`higher_is_better`） |
| `rank` | 每个 RQ 内唯一、完整覆盖 `1..20` |

排序规则固定为：

```text
score descending → pair_id ascending
```

即分数越高排名越前；分数相同时按 `pair_id` 字典序升序打破并列。方法实现必须先按这个规则
生成 rank，validator 会重新排序核对。不要依赖输入行顺序、平台特定的非稳定排序或随机并列。

该表同时容纳 `preliminary_score`、TF-IDF/two-stage、BM25、cosine similarity、
Cross-Encoder logit/score 和 RRF score。算法内部可以使用任意原始分数范围，但写入 artifact 时
必须满足 higher-is-better；若原算法越低越好，输出前必须做有文档记录的确定性转换。

CSV 不允许额外列，尤其不得包含 `label`、`final_label`、`human_label`、`judgement`、
`review_decision`、annotator 或 adjudication 字段。算法解释、参数和环境信息属于 manifest，
不应复制到每一行。

## 4. Method Manifest v1.0 / v1.1

每个正式 ranking CSV 必须在同一 output package 中配套一个 JSON manifest。`ranking.path` 相对
manifest 所在目录解析，且不得离开 package。以下是只读取两个公共输入的 v1.0 schema；v1.1
只把版本对改为 `1.1/1.1` 并按 2.1 节增加 `inputs.source_sample`：

```json
{
  "schema_version": "1.0",
  "contract_name": "w5_method_ranking",
  "contract_version": "1.0",
  "artifact_type": "method_ranking",
  "method": {
    "method_id": "example_method_v1",
    "display_name": "Example Method v1",
    "family": "sparse",
    "parameters": {},
    "model": null
  },
  "inputs": {
    "candidate_pool": {
      "path": "data/annotation_tasks/w4/candidate_pool_v0.1.csv",
      "sha256": "25f608eb4c94218dfa220ba108b15ec846b2bd418174501420a468c376ed17cc",
      "version": "w4_pilot_v0.1"
    },
    "research_queries": {
      "path": "configs/w4/research_queries.json",
      "sha256": "c77ec74ef4567614d3dfb6dab937b85398f95128cdb29e823587715002d99ab1",
      "version": "w4_pilot_v0.1"
    }
  },
  "ranking": {
    "path": "ranking.csv",
    "sha256": "<64 lowercase hex characters>",
    "row_count": 60,
    "score_direction": "higher_is_better",
    "tie_breaking": ["score_desc", "pair_id_asc"]
  },
  "generation": {
    "generated_at": "2026-08-17T20:00:00+08:00",
    "duration_seconds": 1.25,
    "git_revision": "<full 40-character lowercase commit SHA>",
    "git_worktree_clean": true,
    "python": {
      "version": "3.12.0",
      "implementation": "CPython"
    },
    "platform": {
      "system": "Windows",
      "release": "11",
      "machine": "AMD64"
    },
    "dependencies": {
      "example-package": "1.2.3"
    }
  },
  "label_access": {
    "benchmark_labels_read": false,
    "declaration": "Ranking generation did not read benchmark labels or judgements."
  }
}
```

`method.family` 只能是 `baseline`、`sparse`、`dense`、`neural` 或 `hybrid`。所有实际参数必须
写入 `parameters`，不能只写“默认参数”。如果使用预训练模型，`model` 必须记录稳定的
`name`、明确的 `revision` 和 `adapter`；未使用 adapter 时写 `null`。`dense` 和 `neural`
方法不能把 `model` 留空。RRF 等 hybrid 方法应在 parameters 中记录输入 method artifact 的
稳定标识/hash 和融合参数。

正式输出必须在 clean Git 工作树生成并记录完整 commit SHA。`dependencies` 记录该方法复现
所需的直接依赖版本；模型权重版本放在 `model`，不要把下载缓存路径、Token 或个人绝对路径写入
manifest。

建议 package 结构：

```text
<method-output>/
├─ manifest.json
└─ ranking.csv
```

## 5. Validator

业务逻辑位于 `src.w5_method_contract.validate_method_output()`；薄 CLI 位于
`app.validate_w5_method`，保持 `app → src`：

```powershell
python -m app.validate_w5_method --manifest <method-output>/manifest.json
```

Validator 不读取 benchmark judgement。它会拒绝：

- 总数不是 60、缺失/未知/重复 pair；
- 任一 RQ 不是 20 条，或 pair 的 RQ 与冻结 Candidate Pool 不一致；
- method_id 混乱或不符合稳定 ID 规则；
- 非有限 score；rank 缺失、越界、重复或不完整；
- score/rank 不符合 higher-is-better 和固定 tie-breaking；
- Candidate Pool / Research Query 路径、版本或 hash 漂移；
- v1.1 `source_sample` 缺失，或其路径、版本、hash 与冻结 trust anchor 不一致；
- ranking 文件 hash 与 manifest 不一致；
- ranking CSV 包含 benchmark label/judgement 等禁止字段或任何额外列；
- schema/contract/artifact version 不匹配；
- 官方 B0/B1 method ID 自报 v1.0，以版本降级方式省略 `source_sample`；
- 参数/model、Git/Python/platform/dependency、时间或 label-access provenance 不完整；
- 正式输出声明在 dirty/未知工作树生成，或声明曾读取 benchmark labels。

Validator 只能验证 artifact 与声明，不能从技术上证明算法进程从未在别处查看 label。代码审查、
独立分支、参数预注册和先冻结 artifact 再评价仍是正式实验的必要过程控制。

## 6. Evaluation adapter

`src.w4_benchmark_evaluation.evaluate_contract_ranking()` 接受
`validate_method_output()` 的返回结果，在评价阶段才把 approved labels 按 `pair_id` 连接进来，
并复用现有 judged Precision/NDCG 等指标函数。adapter 不判断算法类型，因此后续新增方法不需要
在 evaluator 中复制一套特殊分支。

现有 W4 B0/B1 CLI 行为保持不变。正式 W5 多方法编排位于 `src.w5_experiment`，CLI 为
`app.evaluate_w5_methods`；它先验证所有 method package，再打开 strict approved benchmark 并
连接 label。`scripts/check_w5_method_artifacts.py` 另行执行 W5 final closure 的六方法 roster
policy，拒绝缺失、未知、重复、目录/manifest identity 不一致或版本错误的正式封存集合。

## 7. 公共 fixture 与完全并行开发

`tests/fixtures/w5_method_contract/` 提供两个无标签、非正式算法结果的合法排名：

- `lexical_fixture.csv`：含并列分数，用于 validator 与 deterministic tie 测试；
- `dense_fixture.csv`：反向顺序，用于两个不同 ranking 的组合和比较测试。

它们使后续任务可以只基于 Bootstrap 后的 `main` 开工：

| 任务 | 可独立使用的公共接口 |
| --- | --- |
| BM25 / SPECTER2 / Cross-Encoder | 冻结输入 + Ranking CSV + manifest + validator |
| RRF | 两个公共 fixture，无需等待真实 sparse/dense artifact |
| Hard-negative / Error Taxonomy | 两个 fixture + evaluator adapter，无需等待任一正式排序器 |
| CI / reproducibility | manifest schema、CLI、正负测试和固定 fixture |

Fixture 不带 manifest，是为了避免伪造正式 Git/模型/运行环境 provenance；测试会在临时目录中按
contract 构造明确标为 fixture 的 manifest。它们不得改名后冒充 BM25、SPECTER2 或正式 W5
结果。

## 8. 公平比较与冻结流程

所有 W5 方法必须：

1. 使用完全相同的 Candidate Pool 和 Research Query，并完整声明方法实际读取的冻结辅助输入；
2. 在不知道 approved Query-Relevance label 的情况下生成 ranking；
3. 在看正式评价结果前固定参数、模型 revision、adapter 和随机种子（如适用）；
4. 不为提高 W5 指标回调参数或挑选有利 run；
5. 先在 clean commit 上生成 ranking 和 manifest，再通过 validator 冻结 artifact hash；
6. 冻结后才由 evaluation 阶段读取同一个 strict approved benchmark；
7. 对 B0、B1、BM25、SPECTER2、Cross-Encoder、RRF 使用同一 Contract 和评价口径；
8. 报告这是 fixed-pool Query-Relevance ranking/reranking，而非 retrieval recall。

若参数、模型、代码或 ranking 任一项改变，必须生成新的 method_id 或明确的新版本 artifact 和
hash；不得原地覆盖已经进入正式评价的 artifact。
