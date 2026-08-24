# W6 Benchmark v0.2-alpha 与 Boundary-Aware Ranking 研究报告

状态：Issue #64 个人分支研究与工程实现。本文记录已经冻结的研究决策、fixture 验证边界和后续
Integration 工作；它不声称已经生成真实 W6 Benchmark，也不包含 Hidden Test label 或结果。

## 1. 研究边界与时间顺序

本任务只依赖 `main@90811052194801263708627c1eda39a2765e9037`、公共 W6 Bootstrap contracts
和已提交 synthetic fixtures。未读取或导入任何 sibling W6 PR 的代码或 artifact。

关键时间顺序如下：

1. 先定义 Topic viability/diversity criteria，研究 16 个候选；
2. 在没有任何新 W6 relevance annotation 的前提下，于 `2026-08-24T14:18:00+08:00`
   冻结候选取舍；
3. 于 `2026-08-24T14:18:30+08:00` 冻结 9 个真实 Research Topics；
4. 只使用冻结 Topic metadata，于 `2026-08-24T14:19:00+08:00` 冻结 topic-level
   Dev/Hidden split；
5. 在 labels 和 label distribution 可见前，于 `2026-08-24T14:19:30+08:00` 冻结 annotation、
   second annotation、review 和 adjudication policy；
6. Boundary-Aware 只把 W5 Error Analysis 当作历史诊断和假设来源，不读取 W6 labels，并在任何
   W6 evaluation 前固定 formulation 和默认参数。

以上 freeze 不得因未来 label distribution 或任何方法指标而改动。真实 Multi-Retriever Pool、
canonicalization、annotation 和 sealed hidden evaluation 均留给 Integration PR。

## 2. Topic discovery 与 viability criteria

候选筛选不是关键词拼接。每个候选都按以下十个维度记录：

- scientific object；
- data modality；
- target task；
- method role；
- scope-in / scope-out；
- hard-negative potential；
- literature viability；
- query variant feasibility；
- 与 W4/W5 Research Query 的重叠；
- 与新候选之间的重叠和伪多样性风险。

完整、机器可验证的候选记录和公开 query URL 位于
[`topic_research.json`](../../../data/research/w6/v0.2-alpha/topic_research.json)。OpenAlex evidence
统一使用 `title_and_abstract.search`、`from_publication_date=2000-01-01` 和 `has_abstract=true`；
hit count 是检索可行性线索，不是 relevance judgement，也没有用于比较 ranking 方法。

### 2.1 十六个候选的真实 OpenAlex smoke evidence

| Candidate | 代表 query 的 hit count | 决定 | 核心理由 |
| --- | ---: | --- | --- |
| Stellar atmospheric parameters | 59 | 淘汰 | 文献充分，但直接重复 W4/W5 参数估计 |
| Stellar spectral classification | 100 | 淘汰 | 文献充分，但直接重复 W4/W5 分类边界 |
| Generic spectral preprocessing | 8 | 淘汰 | 结果异质且与 W4/W5 preprocessing 重叠 |
| Spectroscopic galaxy redshift | 21 | 淘汰 | photometric-redshift 污染强，新增多样性有限 |
| Galaxy activity classification | 4 | 保留 | 小而直接的光谱 activity 分类语料，边界清楚 |
| Quasar classification/redshift | 48 | 淘汰 | photometry、spectroscopy、分类和回归混合，target 不稳定 |
| Supernova spectral typing | 14 | 保留 | DASH 等直接证据，光谱与 light-curve 边界清楚 |
| Exoplanet atmospheric retrieval | 20 | 保留 | 多个直接 inverse retrieval 方法，forward/inverse 边界清楚 |
| Stellar radial velocity | 8 | 保留 | WOBBLE 等直接 evidence，目标区别于参数和分类 |
| Spectral anomaly discovery | 48 | 保留 | stellar/galaxy survey 的直接 anomaly evidence，增加无监督任务 |
| Stellar spectral denoising | 12 | 保留 | Spectra-GANs 等直接 restoration evidence，边界可执行 |
| Emission-line detection/deblending | 11 | 淘汰 | relaxed query 混入 strong-lens 等下游任务，deblending 语料不闭合 |
| Telluric correction | 4 | 淘汰 | broad hits 少，直接 learned correction evidence 不足 |
| Stellar spectral emulation | 13 | 保留 | 直接 interpolation evidence，明确是 forward role |
| Solar spectropolarimetric inversion | 10 | 保留 | 多个直接 Stokes inversion 方法，modality 独特 |
| 21-cm foreground removal | 6 | 保留 | deep21 等直接 evidence，增加 radio/cosmology 模态 |

这些 count 只说明某个严格 query 在当时 OpenAlex 索引中的结果规模。小 count 不自动淘汰，较大
count 也不自动保留；代表性论文是否直接匹配 object/modality/task/role 才用于 boundary 判断。

### 2.2 补充 OpenAlex research 的执行边界

用户随后授权为 16 个候选各查询两个合理 variants，并收集年份分布和代表论文。执行环境没有暴露
`OPENALEX_API_KEY` 进程、User 或 Machine 环境变量，因此没有从聊天明文重建、打印或保存密钥。
匿名公开接口的单 query smoke 成功，但较大补充批次随后收到 HTTP 429。补充 research 会在限流
窗口恢复且 `OPENALEX_API_KEY` 作为环境变量实际暴露后再另行继续；本次不把失败批次写成成功
evidence。失败响应不会补造 count、年份或论文 identity，也不会改变已经冻结的 Topic roster。

## 3. 最终 Topic freeze

冻结 Topic Set 位于 [`topics.json`](../../../data/research/w6/v0.2-alpha/topics.json)：

- artifact ID：`w6_research_topics_v0.2_alpha`；
- SHA-256：`6e2f6e6b8fea56cef6e245dcf37fa97a46ba5efc6703fb47e9863840e3a06ca4`；
- final count：9；
- 每个 Topic 均有 stable ID、Research Question、object、modality、task、method/scientific role、
  scope-in/out、boundary cases、两个 frozen acquisition query variants 和 provenance。

### 3.1 Coverage matrix

| Frozen Topic | Scientific object | Modality | Target task | Method/scientific role | 主要边界 |
| --- | --- | --- | --- | --- | --- |
| `w6_topic_galaxy_activity_spectra` | galaxy / nucleus | integrated optical spectra | activity classification | primary classifier / ionization regime | photometric AGN、redshift、line measurement |
| `w6_topic_supernova_spectral_typing` | transient | phase-varying optical spectra | spectral typing | primary classifier / rapid ID | light curve、host classification、redshift only |
| `w6_topic_exoplanet_atmospheric_retrieval` | exoplanet atmosphere | transmission/emission spectra | physical retrieval | inverse model / composition inference | transit detection、forward synthesis、molecule-only detection |
| `w6_topic_stellar_radial_velocity` | star / host star | high-resolution time series | Doppler velocity | estimator/disentangler / motion measurement | atmospheric parameters、type、activity-only prediction |
| `w6_topic_spectral_anomaly_detection` | rare survey objects | optical/IR survey spectra | anomaly discovery | novelty score / follow-up prioritization | fixed known-class classifier、generic embedding |
| `w6_topic_stellar_spectral_denoising` | low-S/N star | 1-D optical/IR spectra | denoising/restoration | learned restoration / line preservation | normalization、incidental preprocessing、generation |
| `w6_topic_stellar_spectral_emulation` | stellar model grid | parameter-conditioned synthetic spectra | interpolation/generation | forward surrogate / faster synthesis | inverse parameterization、denoising、augmentation-only |
| `w6_topic_solar_spectropolarimetric_inversion` | solar atmosphere | Stokes profiles | magnetic/atmospheric inversion | inverse surrogate / field reconstruction | image classification、forward transfer、non-solar parameters |
| `w6_topic_21cm_foreground_removal` | cosmological 21-cm sky | radio-frequency spectra/maps | component separation | learned separator / signal recovery | RFI classification、parameter inference、continuum imaging |

### 3.2 残余 overlap 与限制

9 个 Topic 仍有有意保留的高价值邻接：stellar denoising 与 stellar emulation 共享部分词汇，但一项
处理 observed input、一项生成 synthetic output；exoplanet/solar inversion 都是 inverse problem，
但 object 与 modality 不同；galaxy activity 和 supernova typing 都是 classification，但 label physics
不同。这些邻接用于形成 hard negatives，而不是伪装成完全正交。OpenAlex 查询本身仍可能受索引、
同义词和 metadata completeness 影响，Integration 的 Candidate Pool 不能把 smoke hit count 当作
目标 pool size 或 recall 估计。

## 4. Topic-level Dev / Hidden split

比较过三种策略：

| Strategy | 优点 | 风险 |
| --- | --- | --- |
| seeded random topics | 简单且可复现 | 可能把 object/task 家族集中到单侧 |
| manual object-only stratification | object coverage 直观 | modality 和 method role 仍可能失衡 |
| constrained balanced topic split | 同时平衡 object、modality、task、role | 规则更复杂，需固定 seed 消除等价方案自由度 |

最终选择 `constrained_balanced_topic_split_v1`，seed 为 `issue64-topic-split-v1`。分割单位严格是
Topic，且仅读取冻结 Topic metadata：

- Dev（5）：supernova typing、stellar radial velocity、spectral anomaly、stellar emulation、
  21-cm foreground removal；
- Hidden（4）：galaxy activity、exoplanet retrieval、stellar denoising、solar inversion。

冻结 artifact 是 [`split_manifest.json`](../../../data/research/w6/v0.2-alpha/split_manifest.json)，
split identity 为
`w6-topic-split:sha256:8391d14987a15982b5afa2ae3760f029824909353f51056360d79fe9b85202bc`。
Dev/Hidden 无交集并完整覆盖 9 个 Topic。真实 Hidden labels 必须由独立 custodian 保存在普通仓库
之外；公开仓库未来最多保存 external sealed hash anchor，不能包含 reveal path。

## 5. AI-assisted annotation 与 review protocol

冻结协议位于
[`annotation_protocol_v1.json`](../../../configs/w6/annotation_protocol_v1.json)，SHA-256 为
`5f654dc8493a5bcf584a69442c3b1dfd770b0f1c89fc918800143d01820cfaef`。

### 5.1 Primary annotation

- 使用 W4-compatible `0/1/2` Query Relevance；
- 如实记录 actor 为 `ai_assistant`、`human` 或 `ai_assisted_human`，不称 pure-human gold；
- blind view 只显示 Topic boundary、title/abstract 和公开 paper metadata；
- 禁止 retriever、run/hit、source rank/score、method、fusion、selection reason、内部 pool identity、
  其他 label 和 metrics；
- 每条保存 confidence、uncertainty、evidence source/reference、lookup status、简短可审查依据、
  actor/model/tool、prompt/protocol version、timestamp 和 review status；
- `not_needed/completed/insufficient/failed` 明确区分 lookup 结果；
- 禁止保存 private chain-of-thought，只有 conclusion、short justification 和 evidence reference。

### 5.2 Second annotation、review 与 adjudication

在 labels 可见前冻结如下规则：

- 每个 Dev Topic 用 `issue64-second-annotation-v1` 确定性抽取 20% 做独立第二标注；
- second judgement 保存在 Issue #64 自己的 versioned extension artifact，显式绑定同一 blind task、
  `independent_second` round、actor、timestamp、evidence 与 protocol；不放宽公共 Bootstrap 的
  “一个 task 一份 primary”语义；
- `second actor != primary actor` 由 validator 检查；primary/second label 不同会自动形成 conflict，
  caller 不能手工漏传 conflict ID；
- low confidence、非空 uncertainty、evidence insufficient、boundary case、annotation conflict、
  missing abstract 必须 review；
- 每个 Topic 的 high-confidence candidates 用 `issue64-high-confidence-qa-v1` 确定性抽取 10%；
- reviewer 必须独立于 primary actor；
- conflict 必须由 `human` 或 `ai_assisted_human` adjudicate；
- decision 只能是 `approve/modify`，必须记录 final label、review time/note/provenance；
- primary history 永不被 adjudication 静默覆盖；
- review selection 不得使用“某方法高排但 label=0”等 ranking signal。此类分析只能在正式 labels
  freeze 后作为 Error Analysis。

## 6. Benchmark v0.2-alpha workflow

[`src/w6_benchmark.py`](../../../src/w6_benchmark.py) 和三个薄 CLI 实现：

- 真实 frozen Topic/research/split 校验，包括近重复 Research Question、scope-in/out 矛盾、
  split overlap、hash drift 和 chronology；
- annotation protocol fail-closed 校验；
- deterministic second-annotation selection、独立 second judgement extension 和 blind review plan；
- Bootstrap bundle 到 versioned Benchmark package 的适配、构建、自校验和原子发布；
- topic/retrieval/source/canonical/pool/task map/blind tasks/split/annotation/review/hidden anchor 的
  hash-pinned graph closure；
- `bootstrap_fixture`、`draft`、`proposed`、`sealed_candidate` 的核心 API 状态门禁；当前 standalone
  CLI 只构建 `bootstrap_fixture`，不暴露没有真实 Integration adapter 的 production choices；
- Topic viability → Topic research freeze → Topic Set freeze → split freeze，以及
  split → protocol → annotation start/primary → second → review/adjudication 的实时时间比较；
- package/Benchmark/全部 package artifacts 的 fixture identity 一致性；real `draft`、`proposed`、
  `sealed_candidate` 还必须由 caller 提供 package 外的 hash-pinned trusted input registry。

状态门禁拒绝 `approved` 自报。`proposed` 要求 Dev annotation coverage 完整；
`sealed_candidate` 还要求冻结 policy 选中的 second judgements 全部存在、annotator/reviewer 独立、
自动识别的 conflict 全部 adjudicate、全部 mandatory review 完成且 chronology 合法。package 自己
提供的一组自洽 SHA 不是 trust root；没有外部 trusted registry 时，任何 fixture→real promotion 都
fail closed。当前个人分支只有 synthetic Bootstrap fixture 可跑，所以 fixture PASS 只证明 contract、
hash、blindness 和 workflow 兼容，不证明真实 Benchmark coverage 或 label validity。真实
Multi-Retriever candidates 和 annotation 没有被伪造。

提交的 [`w6_issue64`](../../../tests/fixtures/w6_issue64/README.md) fixture 从 clean revision
`74d5956b48ed67082a1b475900e8694bf6f4deff` 生成。Benchmark package 状态为
`bootstrap_fixture`，含 2 fake Topics、13 pool items、4 synthetic annotations；package identity 为
`w6-benchmark-package:sha256:aceb77d85cb54a6d8f8d55dc2d7961a8a86a0c4cc8d32e247f91a1d9762272dc`。

## 7. Boundary-Aware research

### 7.1 历史诊断与问题定义

W5 Error Analysis 暴露的失败机制包括 classification vs regression、preprocessing vs
parameterization、generation vs preprocessing、object classification vs stellar type，以及 object、
modality、target task 和 method role mismatch。W5 labels 和 representative cases 只用于形成这个
hypothesis；它们不是 W6 独立验证，也没有用于选 W6 Topic、调 W6 label 或生成 ranking。

### 7.2 方案比较

| 方案 | Inputs / determinism | Leakage 与过拟合风险 | 结论 |
| --- | --- | --- | --- |
| 单一 deterministic compatibility rule | Topic fields + text；完全确定 | 易解释，但丢失基础 relevance 强度 | 未选 |
| structured decomposition + relevance/penalty | Topic fields + source text；完全确定 | 无 labels，可逐维诊断，复杂度低 | 选择 |
| lightweight classifier | 需要训练数据/model revision | 容易记住 W5 小样本边界，需额外模型治理 | 暂缓 |
| LLM boundary judge | 外部 model/prompt/tool | 非确定性、成本和 provenance 更复杂 | 暂缓 |

### 7.3 冻结 prototype

最终方法 ID 为 `boundary_aware_structured_lexical_v1`。方案比较、输入白名单、限制和参数已冻结在
[`boundary_aware_structured_lexical_v1.json`](../../../configs/w6/boundary_aware_structured_lexical_v1.json)，
并由 CLI 实际加载。对每个 Topic 的完整 frozen pool：

```text
score = 0.60 × per-topic min-max BM25 relevance
      + 0.40 × structured compatibility
      - 0.50 × max(scope-out overlap, boundary-case overlap)
```

structured compatibility 是 scientific object、data modality、target task、method role 四维等权
平均。query 来自冻结 Topic structured fields 和 scope-in；candidate text 来自显式声明并 hash 绑定
的 `source_records` auxiliary input。缺失 abstract 的 candidate 保留并使用 title-only，不因 missingness
额外扣分。默认 backend 是无网络、无模型的 deterministic lexical decomposition；测试使用显式
fixed-assessment fake backend。

输出严格复用 W5 五列 `pair_id,research_query_id,method_id,score,rank`，其中 pair 对应动态
`pool_item_id`、query 对应 `topic_id`；score higher-is-better，tie-break 为
`score desc -> pair_id asc`。method manifest 固定 Topic/Pool/source-record hashes、parameters、backend、
Git clean revision、configuration hash 和 no-label declaration。source config 的 `artifact_id + SHA-256`
与只影响 numeric ranking 的 semantic configuration 分开记录，但两者都进入 method configuration
hash。最终 artifact 同时通过公共 W6 method validator 和 Issue #64 strict layer；后者机器检查
`config freeze <= generation <= method freeze < evaluation（若存在）`。

Boundary generation 不再调用完整 Bootstrap bundle validator。task-scoped safe loader 只打开
`boundary_generation_inputs.json`、Topic Set、retrieval provenance、source records、canonical mapping、
Candidate Pool 和 frozen source config。retrieval/canonical 只用于验证 post-canonical pool identity，仍是
明确且 label-free 的必要闭包。进程级 file-open regression 断言 annotation/task results、reviews、
Benchmark/Hidden anchor、method rankings、metrics、synthesis 与 W5 diagnostics 的打开数均为 0；只复制
上述闭包、不复制任何 annotation artifacts 时，CLI 仍可生成 ranking，删除任一必要 input 则 fail closed。

提交的 Boundary fixture 对 13 个 Bootstrap pool items 生成完整 ranking；ranking SHA-256 为
`8b4c33c7eb30af9d4586ed24641d1ed87f47b5d038b99ff08133611cd1c03b58`，configuration SHA-256
为 `b4e3f18570cfd2588e8ba1c43a5eccf4b04128dd8f68d7f3e8965f7d6fb95c31`。Manifest 显式绑定
`source_records`、`retrieval_provenance`、`canonical_entities` auxiliary inputs 和独立 source-config
artifact identity，并声明 Dev/Hidden relevance labels 均未读取。

已知限制是 lexical/synonym brittleness、短文本对 overlap 的敏感性和 per-topic min-max 在很小 pool
上的不稳定性。因此它是最小研究原型，不是经过 Hidden Test 证明的新最优方法。任何参数变更都应
产生新 version/configuration hash，不能根据 W6 Hidden metrics 回调当前 v1。

## 8. 测试与 adversarial coverage

新增离线测试覆盖：Topic schema/near-duplicate/scope contradiction、viability/split chronology、blind
policy drift、second judgement coverage/independence/chronology、自动 conflict 与 adjudication、reviewer
independence、fixture 全量自洽重哈希 promotion、Boundary process-level file-open audit/minimal closure、
source-config binding/chronology、method freeze chronology、两个 builder 的 resolved path overlap，以及
原有 ranking determinism/dynamic pool、mismatch penalty、missing abstract 和公共 W6 validators。测试不
联网、不读取 `.env`、不调用 LLM 或下载模型。

最终验收结果：

- `python -m app.validate_w6_topics`：9 Topics、Dev 5 / Hidden 4、split identity 匹配；
- `python -m app.validate_w6_bootstrap`：2 fake Topics、10 records、13 pool items、3 methods，PASS；
- W6 contract + Issue #64 tests：73/73 PASS；其中新增定向 tests 为 25/25；
- committed Benchmark package validator：`bootstrap_fixture`、2 Topics、13 pool items、4 annotations，
  PASS；committed Boundary package 也通过公共 W6 method validator；
- W4 strict approved validator：60/60、每 RQ 20/20，manifest hash 保持
  `d503f5c2448409a9433bf3ffeada3890c7ddb31237bc7c95c529014b5fb8d094`；
- W5 formal artifact checker：既有六方法 6/6 PASS；
- 全量 offline unittest：519/519 PASS；
- Basic Quality Gate：扫描 360 个文件，0 error / 0 warning，PASSED；
- Full Quality Gate：扫描 360 个文件，0 error / 3 个既有历史 warning，PASSED；
- `git diff --check` 与 protected frozen-evidence path audit：PASS。

Full Gate 的三个 warning 与 base 一致：历史 W1 CSV 结构、W1 旧 label IDs、已跟踪历史 experiment。
没有通过删除断言、放宽 validator 或降级 error 取得 PASS。

## 9. 留给 Integration PR 的真实工作

1. 使用冻结的 9 Topic 和 5/4 split 执行真实 Multi-Retriever acquisition；
2. enrichment、canonicalization、bias audit 和真实 post-canonical Candidate Pool；
3. 生成 blind tasks，执行全量 AI-assisted annotation、独立 second annotation、review/adjudication；
4. 由 Integration/custodian 注册真实 frozen inputs 的外部 trusted registry，再使用核心 API 构建
   `draft/proposed/sealed_candidate`；
5. 由独立 custodian 生成/保存真实 Hidden labels，仅提交 external sealed hash anchor；
6. 从 clean、冻结 inputs 生成真实 W6 methods，包括本 Boundary-Aware prototype；
7. method/config freeze 后执行一次 sealed Hidden Test evaluation；
8. 最终 Benchmark promotion、实验比较、Error Analysis、QA gate 和 synthesis。

本个人分支没有完成或假装完成上述 Integration 工作，也没有产生任何 Hidden Test result。
