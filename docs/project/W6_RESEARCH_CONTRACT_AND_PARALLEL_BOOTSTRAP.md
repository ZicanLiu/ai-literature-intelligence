# W6 Research Contract & Parallel Development Bootstrap

状态：公共 Bootstrap contract；不包含真实 W6 Topic、Candidate Pool、annotation、hidden labels、
ranking、synthesis 或 Benchmark v0.2-alpha。

## 1. 目标与最重要的协作约束

W6 六个成员任务的共同开发模型是：

```text
同一个 Bootstrap main
→ 六人从 main 建六个独立分支
→ 每个分支只使用 Bootstrap contracts + fixtures
→ 六个 PR 全部先进入 main
→ 组长另建 Integration PR 执行真实跨模块端到端流程
```

任一成员 PR 不得导入、读取或等待另一成员尚未合并的 code/artifact。开发期需要的 topic、pool、
canonical entity、ranking、annotation、hidden seal 和 synthesis evidence 都由
[`tests/fixtures/w6_bootstrap/`](../../tests/fixtures/w6_bootstrap/README.md) 提供 deterministic fake
版本。真实研究数据只能在对应 Issue 和最终 Integration PR 中产生。

Bootstrap 的职责是固定 identity、provenance、hash、blind view、no-leakage 和 extension point；
它不提前选择研究问题或实现任何后续算法。

## 2. 现有架构复用

### 2.1 直接复用

- W4 的 `0/1/2` graded Query Relevance 语义继续使用，并显式命名为
  `query_relevance_0_1_2_v1`；W6 annotation 仍需区分原始 annotation、AI assistance、review 和
  adjudication provenance。
- W4 的 record-level alias 安全原则继续有效：source record 不因 canonical mapping 被删除，
  suspected duplicate 不自动合并。
- `src.annotation_tasks.sha256_file()` 继续作为文件 hash 基础，不引入第二套 hash 工具。
- W5 Ranking CSV 的严格五列、`higher_is_better`、`score desc → pair_id asc`、method family 和
  frozen-input/no-label 规则继续复用。
- W5 RRF 已证明 `input manifest hash + ranking hash + pair identity` 是通用的多方法组合边界；
  W6 score-fusion extension 沿用该边界并补充 raw-score/rank usage 与 normalization config。
- 依赖方向仍是 `app → src`。`app.validate_w6_bootstrap` 只是薄 CLI。

### 2.2 必须扩展、不能硬套 W4/W5 的部分

`src.w5_method_contract` 有意绑定 W4 的 60 rows、3 RQ、20 rows/RQ 和 W4 trust anchors。修改这些
常量会破坏已冻结 W5 package，因此 W6 使用
[`src/w6_method_contract.py`](../../src/w6_method_contract.py) 的 extension manifest：CSV 列和排序
语义保持 W5-compatible，行数和 topic 数由冻结 W6 Candidate Pool 动态决定。

W4 v0.1 仍是 record-level Pilot；W6 新增 source record 与 canonical entity 的显式双层 identity、
topic-level Dev/Hidden split、sealed label anchor，以及 structured evidence/claim。它们不存在于 W5
Contract，故由 [`src/w6_contracts.py`](../../src/w6_contracts.py) 和
[`src/w6_synthesis_contract.py`](../../src/w6_synthesis_contract.py) 提供最小扩展。

现有 W4 approved package、W5 六方法 package、正式 metrics 和 Error Analysis 不迁移、不重冻、
不重新解释。

## 3. Artifact graph 与目录约定

概念数据流：

```text
Topic Set
├─ Retrieval Runs/Hits → Source Records ─┬→ Canonical Entity Mapping
│                                        └→ record-level provenance retained
├─ Topic Split → Dev / Hidden Test → public seal anchor
└─ Candidate Pool ← retrieval union + canonical mapping
   ├─ Blind Annotation Tasks → AI-assisted Results → separate Review/Adjudication artifact
   ├─ Frozen W5-compatible Rankings → future evaluation/fusion
   └─ Frozen Ranked List + Evidence Units → Structured Claims → rendered review
```

真实 W6 versioned artifact 建议放在 `data/` 下的独立 W6 目录，并由未来 Issue 决定准确路径。开发
fixture 固定在 `tests/fixtures/w6_bootstrap/`。本 Bootstrap 不创建大量空 `configs/w6/` 或真实
`data/benchmarks/.../v0.2-alpha` 目录，避免把 skeleton 误认成研究结果。

所有跨 artifact reference 使用：

```json
{"artifact_id": "stable_machine_id", "sha256": "64 lowercase hex"}
```

公开 bundle 才记录 fixture 相对路径。业务 artifact 之间用 identity/hash 绑定，避免个人绝对路径
进入 manifest。

## 4. Contract 逐项说明

### 4.1 Research Topic

`w6_topic_set` 支持任意非零数量的 topics，不限制为 6、10 或 12。每个 topic 包含：

- stable `topic_id`、research question、version、candidate/frozen/retired lifecycle；
- scientific object、data modality、target task、method role、scientific role；
- scope-in、scope-out、common boundary cases；
- 一个或多个带稳定 ID/version/status 的 acquisition query variants；
- 创建来源、时间和 Git provenance。

Bootstrap topic 全部是 synthetic fixture。真实 topic discovery、viability、freeze 和数量由 Leader
Issue 决定。

### 4.2 Retrieval run 与 hit provenance

`w6_retrieval_provenance` 将 algorithm-independent run 与 hit 分开：

- run：topic/query variant、acquisition system、method/model identity、完整 frozen config 及其
  canonical JSON SHA-256、可选 deterministic seed、开始/结束时间、Git revision、run-output hash；
- hit：stable hit ID、run ID、record ID、source rank、raw source score/方向和 retrieval time。

因此 OpenAlex native relevance、BM25、dense、Cross-Encoder reranking、deterministic random tail
或未来 retriever 都可以新增 run，而不修改 Benchmark schema。

### 4.3 Source record / Candidate record

`w6_source_records` 保存供应方 record identity，不把它和论文实体混为一谈：

- `record_id`、命中的 `topic_ids`、OpenAlex ID、原始 DOI、title/abstract/year/authors/venue；
- landing page 和 provider/source-record identity；
- metadata completeness status、missing fields、score；
- 完整 acquisition hit references。

Missing abstract 是合法但必须显式记录的状态，不得删除 candidate 或补造摘要。

### 4.4 Canonical entity / alias

`w6_canonical_entities` 为每个 source record 建立显式 mapping：

- stable canonical entity ID、preferred record、normalized OpenAlex IDs/DOIs/title；
- 全部 alias record IDs、identity evidence、confidence/review state；
- canonicalization tool/version/time/Git/reviewer provenance；
- alias records 的 retrieval provenance union。

Validator 只允许 `high + confirmed` 的多-record alias group。低/中置信度相似项进入
`suspected_relationships`，保持两个独立 canonical entities；不得为方便自动删除或合并。

### 4.5 Candidate Pool

`w6_candidate_pool` 表达 `multiple retrieval runs → pooled topic-record set`：

- 每个 member 有 stable pool item ID、topic/record/canonical identity、全部 hit IDs、source-system
  membership union 和 selection reasons；
- pool policy 的 target/minimum/depth 等值属于 `parameters`，schema 不硬编码；
- `topic_counts` 由 members 校验；
- `identity_stage` 明确 pre/post canonicalization；
- input artifact IDs/hashes、policy、counts、排序后的 members 共同形成 deterministic pool identity。

为保持 Bootstrap 小而可用，单个 Candidate Pool JSON 同时承担 pool manifest 和 member table 的
职责；公开 bundle 另行固定其完整文件 hash，不再创建一个内容重复的空壳 manifest。

Confirmed aliases可以作为不同 source-record pool items 保留并指向同一 canonical entity；
suspected duplicates 必须保持不同 entity/items。

### 4.6 Blind annotation view

`build_blind_annotation_tasks()` 是明确的 full record → blind view 转换边界。输出只含：

- topic question/object/modality/task/method role/scope/boundary；
- pool/record/canonical public identity；
- title、abstract、year、authors、venue、OpenAlex/DOI/landing page。

输出精确白名单不含 acquisition system、retrieval run/hit、source rank/score、method ID、ranking、
RRF、selection reason 或任何 label。Validator 既扫描禁止 key，又逐项重算投影，额外字段和内容
漂移都会 fail closed。

### 4.7 AI-assisted annotation result

`w6_ai_assisted_annotations` 继续使用 versioned `0/1/2` Query Relevance，保存不可改写的
primary annotation 层：

- task/topic/pool item/record identity；
- label、confidence、evidence source/reference/check time；
- 人类可审查的简短 justification summary 和 uncertainty；
- review status；
- actor type、actor ID、model/tool、prompt/protocol version、时间、是否额外 lookup；
- 原始 annotation 的 review status，但不把后续裁决写回原记录。

允许 actor type 为 `ai_assistant`、`human` 或 `ai_assisted_human`，但 AI proposal 没有 human review
时不能伪装为 adjudicated human judgement。Contract 明确拒绝 chain-of-thought/private reasoning
字段；仓库只保存结论、证据引用和简短依据。

`w6_annotation_reviews` 是独立 review/adjudication 层，按 `annotation_id` 绑定原记录，保存 reviewer
type/identity、approve-or-modify、final label、time、note 和 provenance。这样 primary annotation
历史不会被 review 静默覆盖，future adjudication 也可继续增加独立 artifact/version。

### 4.8 Topic-level Dev / Hidden Test split

`w6_topic_split` 要求：

- split unit 精确为 `topic`；
- Dev/Hidden topic IDs 无交集且恰好覆盖冻结 topic set；
- 在 labels 产生和 label-aware method selection 前冻结；
- 记录 split ID/identity、时间、负责人、Git provenance 和 reveal state。

禁止随机拆同一个 topic 的 papers 到 Dev/Test 两侧。

### 4.9 Hidden label seal / reveal

公开 `w6_hidden_label_anchor` 只保存 hidden artifact identity/hash，不保存仓库路径；真实 storage
必须为 external。它固定 hidden topic set，并要求：

- method freeze 后才可 reveal；
- one-time sealed evaluation；
- generation 不能读取；
- reveal 前实际文件 SHA-256 必须与 anchor 一致。

`validate_hidden_label_reveal()` 是显式 reveal 边界。仓库内只允许
`is_fixture=true` 的 fake hidden-label artifact，用于验证 hash/topic/pool/label 完整性；真实 hidden
labels 不得提交。

### 4.10 Benchmark v0.2-alpha future manifest

`w6_benchmark_manifest` skeleton 绑定 topic set、split、pool、canonical mapping、公开 annotation、
独立 review artifact、hidden anchor、counts、reference year、generation/review provenance 和 deterministic benchmark
identity。它使用 `topic_id + pool_item_id` 作为 judgement unit，同时保留 canonical mapping。

Bootstrap fixture 的 status 是 `bootstrap_fixture`，version 是
`w6_query_relevance_v0.2-alpha.bootstrap-fixture`。它不是 proposed/approved Benchmark v0.2-alpha；
真实 status promotion、review roster 和 hidden evaluation 由后续 Issue 定义并执行。

## 5. Ranking 与 score-fusion extension

W6 ranking CSV 仍严格为：

```csv
pair_id,research_query_id,method_id,score,rank
```

W6 extension manifest 显式映射：

```text
pair_id            → pool_item_id
research_query_id  → topic_id
ranking unit       → source_record
```

不同之处只有：topic 数与每 topic 行数来自冻结 Candidate Pool，而不是 W4 的固定 3 × 20。Manifest
继续要求 method family/model/parameters、topic/pool/canonical input hashes、clean Git generation、
seed/dependencies、frozen configuration hash 和 label-access declaration。

W5 的 B0/TF-IDF/BM25/SPECTER2/Cross-Encoder/RRF 实现未来可以在新的冻结 W6 pool 上生成
W6-extension package 并按同一 evaluator 接口比较；现有六个 W5 frozen packages 自身仍绑定 W4
60-pair identity，不能直接与不同 pool 混用或被重冻。

Fusion extension 不实现标准化算法，但提供足够边界：

- 两个或以上 input method packages 必须先独立通过 validator；
- 每个 input 固定 method ID、manifest hash、ranking hash；
- 显式记录使用 raw score、rank 或两者；
- 如果读取 raw scores，必须记录 normalization strategy/parameters/fit scope；
- normalization 必须声明不读 labels；
- output 仍是算法无关合法 ranking artifact；
- configuration hash 在评价前冻结；
- generation 声明 dev/hidden relevance labels 都未读取。

Future standardized score fusion 可以复用已有 RRF 的 input-identity 经验和 W6 extension，不需要
另建 fusion-only CSV 或 evaluator。

## 6. Evidence-grounded synthesis

### 6.1 Synthesis input

`w6_synthesis_input` 绑定一个 Topic/Question、一个已验证 frozen ranking manifest/ranking hash、按
rank 顺序选择的 pool items、paper metadata、retrieval/source provenance、evidence artifact hash
和生成 provenance。开发期直接使用 fake ranking，不等待真实 Pool Builder。

### 6.2 Evidence unit

`w6_evidence_units` 支持：

- paper 的 canonical + source-record identity；
- abstract snippet、public summary snippet 或 structured metadata；
- source type/reference/locator；
- extraction method、model/tool、time、source-license note；
- extraction status 与 confidence。

Snippet 上限为 800 characters；Contract 不支持仓库默认复制整篇正文。

### 6.3 Structured claim 与 render

每个 claim 包含 claim ID/text、supporting canonical paper IDs、evidence references、confidence、
support status 和 citation status。规则是：

- `supported` 必须有匹配 paper/evidence，citation 为 `verified`；
- `partially_supported` 必须有匹配 paper/evidence，citation 为 `incomplete`；
- `unsupported` 必须明确无 supporting refs 且 citation 为 `missing`；
- dangling paper/evidence 或 evidence-paper mismatch 直接失败。

Human-readable Markdown 只是结构化 claims 的 render，必须列出全部且仅这些 claim IDs。Relevance
ranking/label 只决定阅读候选，不证明 factual claim correctness。

## 7. Validator 与使用方式

公共命令：

```powershell
python -m app.validate_w6_bootstrap
python -m unittest tests.automated.test_w6_contracts -v
```

主要 Python 接口：

- `validate_w6_bootstrap_bundle()`：验证公开 hash-pinned bundle 及全部 cross-artifact identity；
- `validate_topic_set()` / `validate_retrieval_provenance()` / `validate_source_records()`；
- `validate_canonical_entities()` / `validate_candidate_pool()`；
- `build_blind_annotation_tasks()` / `validate_blind_annotation_tasks()`；
- `validate_annotation_results()` / `validate_annotation_reviews()` / `validate_topic_split()`；
- `validate_hidden_label_anchor()` / `validate_hidden_label_reveal()`；
- `validate_w6_method_package()`；
- `validate_evidence_units()` / `validate_synthesis_input()` /
  `validate_structured_synthesis()`。

Validators fail closed，覆盖 duplicate/unknown/mismatch/dangling/hash/leakage 等结构错误；它们不尝试
判断论文科学事实、annotation 是否“正确”或某算法是否“更好”。

## 8. 六人 Parallel Development Matrix

| 后续任务 | 只读 Bootstrap inputs | 本 PR 不实现的 future output | 独立开发证明 |
| --- | --- | --- | --- |
| Leader：Topic/Benchmark/annotation/Dev-Hidden/Boundary-Aware | fake topics、pool、blind tasks、AI-assisted results、split、seal、benchmark skeleton、fake ranking | 真实 topic、真实 labels/split、Boundary-Aware ranking | 可完整测试 topic freeze、blind projection、annotation/review、split/seal 和 method output，无需真实 retriever |
| 蒲正杰：Synthesis + Standardized Fusion | fake topic/pool、两个 base rankings、fusion package、synthesis input、evidence、claims | normalization choice/weights、LLM/backend、真实 synthesis | raw score/rank/hash/normalization 和 evidence/claim 全部已有 fake inputs，无需 Pool Builder |
| 武子恒：Multi-Retriever Pool Builder | fake topics、runs/hits、source records、canonical map、pool | 真实 retriever execution/pool | 可用既有 runs 验证 union、multi-hit、single-hit、policy、pool identity，无需 Leader topics |
| 贾馥诚：Canonicalization/Provenance/Bias Audit | fake retrieval、records、confirmed alias、suspected relation、pool | canonicalization algorithm、真实 bias audit | confirmed/suspected 两条路径、provenance union 和 record retention 可离线测试，无需 Pool Builder PR |
| 陈星妤：Metadata Enrichment/Query Diagnostics | fake topics、runs、records、pool | enrichment backend、真实 diagnostics | complete/missing abstract、multi-topic/query/run provenance 已覆盖，无需 canonicalization PR |
| 黄斌：Data Quality/Leakage/Artifact Gate | 全部 valid + deliberate invalid fixtures | 最终全仓 W6 gate policy | 可验证所有错误类别、hash/no-leakage/hidden/synthesis/method drift，无需真实 benchmark |

Bundle manifest 中每个任务都精确声明 `depends_on=["w6_bootstrap"]`。自动测试会验证依赖矩阵和
fixture availability；不能增加另一 future member output 作为开发期依赖。

## 9. Integration PR 才允许做的工作

六个成员 PR 全部进入 `main` 后，组长的独立 Integration PR 才能：

1. 读取 Leader 冻结的真实 Topic Set 和 topic-level split；
2. 执行真实 Multi-Retriever Pool Builder；
3. 连接 metadata enrichment 与 canonicalization/bias audit；
4. 生成 blind tasks，执行真实 AI-assisted annotation/review；
5. 将冻结 method artifacts 交给 Dev/Hidden evaluator；
6. 在 method freeze 后进行一次 sealed hidden evaluation；
7. 将通过验证的 frozen ranking 和 evidence units 交给 synthesis prototype；
8. 运行 W6 QA Gate 并形成真实 Benchmark/experiment provenance。

Integration PR 不等于允许绕过 hash、blindness 或 hidden seal。若真实模块接口与 Bootstrap contract
冲突，应报告并版本化 contract，而不是从字符串推断或静默丢字段。

## 10. No-leakage 与科研解释边界

1. Retrieval/ranking/fusion generation 不读任何 relevance labels、metrics 或 Error Analysis；
2. Hidden-test labels 不参与 method design，公开 generation input 不含其路径；
3. Dev/Test 只能按 topic 分隔，真实 split 在 labels 和 label-aware selection 前冻结；
4. Blind annotation 不暴露 retriever/method/rank/score/RRF/selection signal；
5. AI-assisted annotation 保留 actor/model/tool/prompt/evidence/review provenance，不称 pure-human gold；
6. W4/W5 60-pair 是 historical development/diagnostic evidence，不是 W6 independent confirmation；
7. 正式 method/config/ranking 先冻结，再进行 hidden evaluation；
8. Ranking relevance label 不等于 synthesis factual correctness；
9. 每个 supported/partial synthesis claim 必须绑定具体 canonical paper 和 evidence；
10. Bootstrap fixture 的 PASS 只证明结构兼容，不证明未来研究结果有效。

## 11. 留给后续 Issue 的研究决策

- 最终 topic 数量、内容、viability 标准和 freeze roster；
- 真实 retriever roster、pool depth/target/minimum 和 pooling policy；
- 真实 canonicalization rules、review thresholds 和 sensitivity reporting；
- Dev/Hidden topic split 与真实 hidden-label custodian/reveal process；
- AI annotation prompt/model/evidence lookup/human review/adjudication policy；
- Boundary-Aware method formulation；
- score normalization、weights、fit scope 与 preregistration；
- synthesis LLM/backend、evidence extraction policy 和 human factual verification。

这些决定不得在 Bootstrap fixture 中被提前当作正式研究结论。
