# W6 OpenAlex 多查询语料扩展与 Topic Robustness Audit

## 1. 状态与研究边界

本报告记录 PR #71 在 Issue #64 Topic freeze **之后**开展的 Leader research expansion。
它不是 Issue #64 Topic discovery/freeze 的重做，也不属于正式 retrieval experiment、ranking
evaluation 或 label-aware method selection。

最终状态（query freeze `2026-08-26T15:50:21+08:00`；正式 acquisition
`2026-08-26T17:20:53+08:00` 至 `17:22:38+08:00`）：

- 原 9 个 frozen Topics 保持不变；
- 原 topic-level Dev 5 / Hidden 4 split 保持不变且 `reveal_state=sealed`；
- 已先冻结独立的 54-query audit config，再执行 live acquisition；
- `OPENALEX_API_KEY` 从 Windows User environment 成功解析；没有读取 `.env`、没有从聊天明文重建
  key，且 key 未进入 stdout、源码、config、fixture、report、manifest 或 corpus；
- 用户提供的 OpenAlex Usage 页面截图显示 Free Plan 当时 `$1.000` daily budget remaining
  (`100%`)。实现过程的运行记录报告两次 bounded 运行共 108 个 search requests、0 retries；按截图中的
  10 credits/search 约为 1,080 credits，低于 10,000 credits 的免费日预算。仓库只保留最终 run，
  因而两次运行合计仅作为过程记录，不作为可由 committed artifact 独立复核的正式证据；
- 最终 package 含 2,977 个全局 unique Works、4,265 个完整 query hits；9 个 Topic 的 union 合计
  3,439 个 topic-work assignments；
- `potential_topic_amendments` 为空，Topic Set 与 split 没有修改。

## 2. 冻结 Acquisition Design

独立配置：
[`openalex_topic_query_audit_v1.json`](../../../configs/w6/openalex_topic_query_audit_v1.json)

- artifact ID：`w6_openalex_topic_query_audit_v1`；
- config identity：
  `w6-openalex-query-audit-config:sha256:9f312e242f3b9bed2d65da651a85620d38ece58b2ffa9e8fe7425a66f11926a4`；
- config file SHA-256：
  `e678c048cb8a967845787e9eca7b5536bdec45fa96b83302c5064f65dc608fa1`；
- Topic Set hash：
  `6e2f6e6b8fea56cef6e245dcf37fa97a46ba5efc6703fb47e9863840e3a06ca4`；
- split identity：
  `w6-topic-split:sha256:8391d14987a15982b5afa2ae3760f029824909353f51056360d79fe9b85202bc`；
- split file hash：
  `bb57448288f122406d195cbec09dde80f76f78a7a0a1d0ef9bc85c052aea69ad`；
- freeze time：`2026-08-26T15:50:21+08:00`；
- 9 Topics × 6 query variants = 54 个固定 query；
- OpenAlex Works `search`，年份 `2000–2026`；
- 每 query 最多 80 条，因此单 Topic 理论上限为 480，目标约 200–400 unique works，
  soft cap 为 500；
- query 文本、variant ID、coverage facets 与 rationale 全部在 live acquisition 前冻结；
- 禁止看结果后改 query，禁止读取 relevance labels、judgements、ranking metrics 或 annotations。

这 54 个 variants 独立于原 Topic contract 中的 `acquisition_query_variants`。原
[`topics.json`](../../../data/research/w6/v0.2-alpha/topics.json) 没有被修改或重冻。

### 2.1 Query coverage roster

| Frozen Topic | Audit query IDs | 主要设计覆盖 |
|---|---|---|
| `w6_topic_galaxy_activity_spectra` | `galaxy_activity_aq01..06` | integrated spectra、activity classes、emission lines、AGN/LINER、ML classification |
| `w6_topic_supernova_spectral_typing` | `supernova_typing_aq01..06` | transient spectra、type、low signal、phase variation、ML classification |
| `w6_topic_exoplanet_atmospheric_retrieval` | `exoplanet_retrieval_aq01..06` | transmission/emission、retrieval、abundance、learned inverse model |
| `w6_topic_stellar_radial_velocity` | `stellar_rv_aq01..06` | spectra、RV、high resolution、time series、spectral variability |
| `w6_topic_spectral_anomaly_detection` | `spectral_anomaly_aq01..06` | spectra、survey、novelty、unsupervised、rare-object discovery |
| `w6_topic_stellar_spectral_denoising` | `stellar_denoising_aq01..06` | low S/N、learned denoising、artifact restoration、line preservation |
| `w6_topic_stellar_spectral_emulation` | `stellar_emulation_aq01..06` | synthetic spectra、parameters、forward surrogate、interpolation、synthesis |
| `w6_topic_solar_spectropolarimetric_inversion` | `solar_inversion_aq01..06` | solar spectra、Stokes、spectropolarimetry、magnetic field、inversion |
| `w6_topic_21cm_foreground_removal` | `21cm_foreground_aq01..06` | 21-cm、foreground removal、component separation、EoR、intensity mapping |

## 3. Acquisition 与 artifact contract

实现入口：

```powershell
python -m app.run_w6_openalex_audit validate-config
python -m app.run_w6_openalex_audit acquire --output-dir data/research/w6/v0.2-alpha/openalex-audit-v1
python -m app.run_w6_openalex_audit refresh-audit --package-dir data/research/w6/v0.2-alpha/openalex-audit-v1
python -m app.run_w6_openalex_audit validate-package --package-dir data/research/w6/v0.2-alpha/openalex-audit-v1
```

live command 只读取 process / Windows User / Windows Machine 环境中明确命名的
`OPENALEX_API_KEY`，不枚举其他变量、不读取 `.env`。manifest 只记录来源类型，不记录值。它复用
`src.openalex_client_v2.fetch_openalex_papers_v2` 的 cursor pagination、有限 retry/backoff、
年份 filter 与安全统计；key 不进入参数日志、源码、config、fixture、report 或输出 artifact。

完整 package 原子写入全新目录，拒绝覆盖现有 evidence，且通过 resolved path guard 防止输出目录
与 frozen Topic/config/split 输入发生父子或同路径重合。最终输出：

- `works.jsonl`：compact public work metadata，含 Work ID/URL、DOI、title、abstract、authors、
  publication year/date、source、work type、landing URL 与 acquisition identity；全局仅按 normalized
  OpenAlex Work ID exact dedup；
- `query_hits.jsonl`：每个 query-work hit、topic、variant、source rank、acquisition/query run ID，
  全部保留；
- `query_runs.json`：固定 query、API hit count、retrieved count、请求/分页/retry 统计；
- `topic_audit.json` / `topic_audit.md`：label-free descriptive audit；
- `manifest.json`：config/Topic/split 绑定、file hashes 与 acquisition identity。

不会做 DOI/title canonicalization、Multi-Retriever、enrichment、QA、fusion、synthesis 或新增 ranking
算法。相同标题但不同 OpenAlex Work ID 的记录必须分别保留。

### 3.1 Validator provenance closure 与 trust boundary

package validator 不再把 run/hit/work/audit 中的自报字段当作 semantic truth。它从受信 frozen config
构造 54 个 canonical `(topic_id, query_variant_id)`，验证 config 与 query runs 严格双射、query 文本和
year/filter/cap 完全一致，并按正式 derivation 重算 acquisition run ID、query run ID、hit ID 与
acquisition identity。随后从 hits 重算每个 run 的实际行数和连续 `1..N` rank coverage，区分 API
`meta.count`、client result count 与 committed hit count；按 exact canonical OpenAlex Work ID 验证
hit/work 双向 closure，并从 hits 重算每个 Work 的 hit/topic/query derived provenance。

validator 还按 timezone-aware 时间解析检查
`config freeze ≤ acquisition start ≤ query start ≤ query complete ≤ acquisition complete`，并从 frozen
config、runs、hits 和 works 完整重建 canonical Topic Audit（含 36 个 cross-topic pairs）及 Markdown
render 后逐语义比较。这里的 timestamp 约束只能证明已声明时间之间逻辑一致；timestamp 的外部真实性
仍依赖 Git/external evidence，不能被描述成密码学时间证明。

正式 package 的 `config_reference` 必须精确绑定：

- artifact ID：`w6_openalex_topic_query_audit_v1`；
- config identity：`w6-openalex-query-audit-config:sha256:9f312e242f3b9bed2d65da651a85620d38ece58b2ffa9e8fe7425a66f11926a4`；
- config file SHA-256：`e678c048cb8a967845787e9eca7b5536bdec45fa96b83302c5064f65dc608fa1`。

machine validator 证明 package 相对于该受信 config 的内部 provenance closure。pre-acquisition freeze
chronology 的外部 trust anchor 是独立提交 `59f4587`（完整 commit
`59f458733b44c4c3f97b16b8ca30b0273bda5f45`），它先于 live acquisition artifact。package 内部 hash
不能抵抗攻击者同时重写 config、package 和全部 hashes 的整体重新包装，也不作此声称；Git history / pinned
commit 才承担该外部边界。

## 4. 预注册 Audit 指标与解释边界

每个 query 记录 API hit count、retrieved count、对 Topic union 的 unique contribution，并计算 query
pair 的 intersection、union 与 Jaccard。每个 Topic 记录 union、multi-query support distribution、逐年
分布、title/abstract/DOI/authors/year/source/landing-page completeness、query-facet coverage 与代表性公开
论文 identity。跨 Topic 记录 exact Work-ID intersection 与 Jaccard。

代表论文只按 `query support → cited_by_count → year → OpenAlex ID` 的预注册描述顺序选择，用于人工
理解检索边界，不是 relevance judgement。hit count、overlap、metadata completeness 与 query-facet
coverage 都不等于 scientific relevance 或 ranking quality。

若后续 evidence 显示 fundamental scientific problem，只在本报告和 artifact 中新增
`potential_topic_amendment` 记录；不得直接修改 frozen Topic Set 或 Dev/Hidden split。

## 5. Offline verification（采集前）

新增纯离线 fixture 和 14 项定向测试，覆盖：

- 9 Topic / 54 query / config identity / Topic 与 split hashes；
- label-free、non-adaptive 和 exact-ID-only policy drift；
- 全 query-hit provenance、同标题不同 ID 不合并、Topic 内/跨 Topic overlap；
- API count、year、metadata completeness、representative identity 与 risk signal；
- API key、个人绝对路径不落盘，且 live path 不导入 dotenv 或 label-aware W6 模块；
- process → Windows User → Windows Machine 的限定 key-source 解析，不枚举其他环境 secret；
- missing key、frozen input/output path overlap、file hash tampering；
- 相同 fixture 的 acquisition identity 可复现；derived audit refresh 不改变 captured source hashes。

执行结果：

```text
python -m unittest tests.automated.test_w6_openalex_audit -v
Ran 14 tests ... OK
```

OpenAlex v2 的多页 cursor、429/5xx/timeout retry/backoff、无效响应和 safe-error 行为继续由既有
`tests/automated/test_openalex_client_v2.py` 离线测试覆盖。

最终 package 进入仓库后的 P1 closure 修复新增了 self-consistent repack adversarial regressions：
mutation 后测试会重新计算全部受影响 child file SHA 与 manifest acquisition identity，再验证荒谬 rank、
query text drift、unknown Topic、duplicate `(topic, query, work)`、run/client count drift、malformed Work
ID、inverted chronology、重签 frozen query semantics、同步改写 acquisition/query/hit ID、Work derived
provenance drift、Topic Audit/cross-topic statistic drift 与 Markdown drift 全部 fail closed。最终
OpenAlex audit suite 为 31 tests；与 21 个 OpenAlex client tests 合计 52/52 PASS。

采集前全量回归为 548 tests 全部通过（含 2 个既有 Windows symlink 条件性 skip）；Basic Gate
扫描 370 files，0 error / 0 warning；Full Gate 扫描 370 files，0 error / 3 个既有历史 warning，
均 PASSED。live artifact 进入仓库后必须再次执行完整验证，不能直接沿用本次采集前结果。

## 6. Live acquisition evidence

最终 package：
[`openalex-audit-v1`](../../../data/research/w6/v0.2-alpha/openalex-audit-v1/manifest.json)

- acquisition run ID：
  `w6-openalex-live-run:sha256:7e78d6ea8ad53616b6095b5e4315ef37315c21f7bb0dc8aa33c8e7feef386f13`；
- final acquisition identity：
  `w6-openalex-acquisition:sha256:1ae6a8045d7e22be9989203b17a060259288fc8d42f7ade345b3782a853ce73c`；
- final live window：`2026-08-26T09:20:53+00:00` 至 `09:22:38+00:00`；
- 54 queries / 54 pages / 54 requests / 0 retries / 0 failed queries；
- 所有 query 取到最多 80 条；4 个自然小于 80：`galaxy_activity_aq03=69`、
  `exoplanet_retrieval_aq06=62`、`21cm_foreground_aq02=63`、
  `21cm_foreground_aq04=71`；
- API `meta.count` 之和为 107,689；它是 54 个可能高度重叠的 search hit-count 之和，不能解释为
  unique/relevant 文献数；
- 最终文件总大小 9,990,491 bytes（约 9.53 MiB），最大单文件 `works.jsonl` 约 7.63 MB，未保存
  raw API response dump。

第一次同 query 运行完成后发现 compact schema 缺少用户要求的 publication date、work type、
OpenAlex URL 和显式 run identity，因此实现只扩展 OpenAlex `select` 与 provenance schema，未修改
frozen query 文本、顺序、year filter 或 cap。实现过程的运行记录报告两次 acquisition 得到相同的
2,977 Work IDs 和 4,265 个 topic/query/rank hits；仓库保留并可独立验证的是最终 run，以及两次运行
之间 frozen query semantics 未发生变化。第一轮旧-schema package 或独立 fingerprint 未保留，
因此该跨运行一致性不作为机器可独立验证的正式证据。最终 package 的 2,977/2,977 records 均含
date、type 与 OpenAlex URL。

### 6.1 Per-topic corpus size

| Topic | API hit-count sum | Retrieved query hits | Union works | Repeated query hits | Target status |
|---|---:|---:|---:|---:|---|
| galaxy activity spectra | 5,108 | 469 | 417 | 52 | within soft cap |
| supernova spectral typing | 61,881 | 480 | 386 | 94 | preferred |
| exoplanet atmospheric retrieval | 1,181 | 462 | 291 | 171 | preferred |
| stellar radial velocity | 18,546 | 480 | 406 | 74 | within soft cap |
| spectral anomaly detection | 4,888 | 480 | 386 | 94 | preferred |
| stellar spectral denoising | 5,835 | 480 | 408 | 72 | within soft cap |
| stellar spectral emulation | 3,747 | 480 | 414 | 66 | within soft cap |
| solar spectropolarimetric inversion | 3,760 | 480 | 379 | 101 | preferred |
| 21-cm foreground removal | 2,743 | 454 | 352 | 102 | preferred |

9 个 Topic 全部达到 200 的 planning minimum，且均未超过 500 soft cap。`supernova_typing_aq06`
单 query 的 `meta.count=45,904`，说明其 phase-varying transient 表达很宽；冻结规则要求保留并如实
报告，不能因 count 异常而事后改 query。

## 7. Broad corpus identity 与 metadata quality

4,265 query hits 经 Topic 内重复命中折叠后形成 3,439 topic-work assignments；再按 exact normalized
OpenAlex Work ID 全局折叠为 2,977 source records。共有 2,637 records 只属于一个 Topic 的 hit
universe，340 records 命中至少两个 Topics（252 命中 2 个、65 命中 3 个、15 命中 4 个、5 命中
5 个、3 命中 6 个）。这些只是 acquisition provenance；没有执行 DOI/title merge 或 canonicalization。

| Metadata | Present | Completeness |
|---|---:|---:|
| title | 2,972 | 99.83% |
| abstract | 2,842 | 95.47% |
| DOI | 2,875 | 96.57% |
| authors | 2,918 | 98.02% |
| publication year/date | 2,977 / 2,977 | 100% / 100% |
| source name | 2,860 | 96.07% |
| work type | 2,977 | 100% |
| landing URL | 2,977 | 100% |

主要 work types 为 article 2,401、preprint 351、conference paper 86、dissertation 58；其余为少量
book chapter、report、review、dataset 等公开类型。该 corpus 是 raw/broad acquisition universe，
不是 final Benchmark Pool、canonical entity set、relevance-labelled dataset 或 Hidden evaluation set。

## 8. Query robustness 与 temporal evidence

| Topic | Works with ≥2-query support | Pairwise Jaccard median / max | Max-overlap pair | Largest unique contribution | Year range / median | Recent 5y | Abstract / DOI |
|---|---:|---:|---|---|---|---:|---:|
| galaxy activity | 43 | 0.019 / 0.096 | aq01–aq04 | aq02: 73 | 2000–2026 / 2020 | 168 | 97.36% / 96.88% |
| supernova typing | 64 | 0.046 / 0.345 | aq01–aq05 | aq06: 69 | 2000–2026 / 2018 | 97 | 93.01% / 99.74% |
| exoplanet retrieval | 107 | 0.074 / 0.455 | aq01–aq04 | aq06: 44 | 2009–2026 / 2023 | 200 | 95.53% / 95.19% |
| stellar RV | 58 | 0.032 / 0.221 | aq02–aq05 | aq06: 73 | 2000–2026 / 2018 | 102 | 97.29% / 99.01% |
| spectral anomaly | 58 | 0.060 / 0.185 | aq01–aq03 | aq05: 77 | 2000–2026 / 2021 | 159 | 95.08% / 99.74% |
| stellar denoising | 48 | 0.026 / 0.203 | aq01–aq04 | aq06: 77 | 2001–2026 / 2023 | 258 | 94.85% / 94.85% |
| stellar emulation | 53 | 0.019 / 0.240 | aq01–aq04 | aq03: 72 | 2001–2026 / 2022 | 228 | 97.10% / 95.89% |
| solar inversion | 65 | 0.053 / 0.203 | aq01–aq04 | aq05: 70 | 2001–2026 / 2021 | 177 | 92.08% / 98.42% |
| 21-cm foreground | 80 | 0.039 / 0.276 | aq02–aq04 | aq06: 64 | 2000–2026 / 2022 | 203 | 98.01% / 91.48% |

所有 Topic 都同时表现出 multi-query support 和较大的 single-query unique contribution。最大 pairwise
Jaccard 也只有 0.455，说明 OpenAlex `search` 对合理措辞敏感，多 query acquisition 对 broad universe
确有补充价值。另一方面，unique contribution 高不等于 relevance 高；例如 supernova 的宽 query
带来巨大 API hit count，必须由后续 blind annotation 判断边界。

完整 54-query counts、15 个 query-pair/topic 的 intersection/Jaccard/双向 overlap ratio、逐年 counts、
bins、support distribution 和每 Topic 5 个公开 representative hits 位于
[`topic_audit.json`](../../../data/research/w6/v0.2-alpha/openalex-audit-v1/topic_audit.json) 与
[`topic_audit.md`](../../../data/research/w6/v0.2-alpha/openalex-audit-v1/topic_audit.md)。代表集合中包括
`W2921352493`（DASH supernova typing）、`W4390748916`（exoplanet variational retrieval）、
`W3033124288`（spectropolarimetric inversion）和 `W3099201768`（deep21）。这些 identity 只是
descriptive search evidence，不是 relevance gold。

## 9. Cross-topic empirical overlap

36 个 Topic pairs 中 35 个有至少一个 shared exact Work ID，但所有 Jaccard 都低于 0.07：

| Topic pair | Shared works | Jaccard | Directional overlap |
|---|---:|---:|---|
| galaxy activity / spectral anomaly | 52 | 0.0692 | 12.47% / 13.47% |
| stellar RV / stellar emulation | 42 | 0.0540 | 10.34% / 10.14% |
| stellar denoising / stellar emulation | 42 | 0.0538 | 10.29% / 10.14% |
| exoplanet retrieval / stellar emulation | 35 | 0.0522 | 12.03% / 8.45% |
| stellar RV / spectral anomaly | 39 | 0.0518 | 9.61% / 10.10% |
| solar inversion / 21-cm foreground | 0 | 0.0000 | 0% / 0% |

最高 overlap 与 frozen semantic matrix 一致：galaxy anomaly discovery 会共享 unusual-galaxy/survey
works；多个 stellar Topics 会共享通用 stellar spectroscopy/ML works。低 overlap 的 solar/21-cm
则在 object 与 wavelength regime 上都明显分离。结果不显示严重 corpus-level pseudo-diversity，但
低 overlap 也不能证明 Topic 一定优质或 pool 无偏。

## 10. 风险、Topic amendment 与 chronology 结论

高 multi-query support 的 descriptive hits 中仍可见宽检索噪声，例如 photometric-only galaxy、
photometric supernova、medical imaging、electron microscopy 或 wireless communication 标题。这是
OpenAlex broad search precision / lexical spill 风险，也说明本 corpus 必须经过后续 pooling、blind
annotation 和 canonicalization；不能直接作为 Benchmark。它不等于 9 个 Topic 的 scientific
definition 有根本错误，因为每个 Topic 同时存在直接匹配 object/modality/task 的公开 work identity，
且 9 个 corpus 均达到 planning scale。因此本次没有记录 `potential_topic_amendment`，也没有修改
`topics.json` 或 split。

真实 chronology 为：原 candidate smoke evidence → 9 Topic freeze → 5/4 split freeze → PR #71
Benchmark/Boundary work → 独立 54-query config freeze → post-freeze live acquisition/audit。后置 audit
没有参与 Topic selection、没有读取任何 relevance label/judgement/metric，也没有用于调
`boundary_aware_structured_lexical_v1`。

后续 Integration 仍需完成 Multi-Retriever pooling → enrichment → canonicalization → pool selection →
blind annotation/review/adjudication → frozen methods → sealed Hidden evaluation。本 PR 没有替代这些
sibling tasks。

## 11. Final verification 与 protected evidence

最终验收结果：

- query config validator：9 Topics / 54 queries，config identity 与 Topic/split hashes PASS；
- final OpenAlex package validator：54 queries / 2,977 works / 4,265 hits，acquisition identity 与 5 个
  child file hashes、frozen-config↔run↔hit↔work↔full-audit provenance closure PASS；
- `validate_w6_topics`：9 Topics / Dev 5 / Hidden 4、原 split identity PASS；
- `validate_w6_bootstrap`：2 synthetic Topics / 10 records / 13 pool items / 3 methods PASS；
- committed W6 Benchmark validator：`bootstrap_fixture`、2 Topics、13 pool items、4 annotations PASS；
- W6 contracts + Benchmark + Boundary + OpenAlex package/client tests：143 tests，141 PASS / 2 个
  Windows symlink privilege 条件性 skip；其中 Boundary committed fixture 由 W6 strict validator PASS；
- W4/W5 regressions：164 tests 全部 PASS；
- W4 strict approved validator：60/60，每 RQ 20/20，manifest hash 保持
  `d503f5c2448409a9433bf3ffeada3890c7ddb31237bc7c95c529014b5fb8d094`；
- 六个 W5 formal method manifests：6/6 PASS，ranking/manifest hashes 均保持；
- 全量 offline unittest：568 tests，566 PASS / 2 skip；
- Basic Quality Gate：扫描 376 files，0 error / 0 warning，PASSED；
- Full Quality Gate：扫描 376 files，0 error / 3 个既有历史 warning，PASSED；
- `git diff --check`、final package hash validation 与 protected path diff：PASS。

Full Gate 三个 warning 仍是历史 W1 CSV structure、W1 legacy label IDs、tracked historical experiment；
没有新增 warning，也没有删除断言、放宽 validator 或把 error 降级。

### 11.1 Previous P1 regression

| P1 | 回归证据 | 状态 |
|---|---|---|
| process-level no leakage | Boundary process-open/minimal-closure tests 仍证明 annotations/reviews/labels/metrics 打开数为 0 | CLOSED |
| second annotation / sealed trust | second judgement、conflict、adjudication、external real registry/fixture-promotion tests PASS | CLOSED |
| chronology / source-config binding | cross-artifact timestamps、config hash 与 method freeze chronology adversarial tests PASS | CLOSED |
| frozen path safety | Benchmark、Boundary 及新增 OpenAlex output resolved-path overlap tests PASS | CLOSED |

相对 PR review 修复 head `fbe8db766798e17e49c1ba4a774a905aba75b96b`，W4 approved Benchmark、
六个 W5 frozen method artifacts、W5 metrics、W5 Error Analysis、W6 Bootstrap fixtures 与
`src/w6_contracts.py` 的 protected path diff 为空。新增 live path 不读取 label-aware bundle，也不依赖
任何未合并 sibling W6 PR/code/artifact。

## 12. Files changed

- `configs/w6/openalex_topic_query_audit_v1.json`：pre-acquisition frozen 54-query design；
- `src/w6_openalex_audit.py`：config validation、exact-ID corpus、query-hit/run provenance、audit、
  package validator/refresh；
- `app/run_w6_openalex_audit.py`：environment-only validate/acquire/refresh/validate CLI；
- `src/openalex_client_v2.py`：最小扩展 public metadata `publication_date,type` select；
- `.gitattributes`：为 hash-pinned JSONL 固定 LF checkout，防止 Windows CRLF 导致 artifact hash drift；
- `data/research/w6/v0.2-alpha/openalex-audit-v1/`：最终 normalized live corpus 与 audit package；
- `tests/fixtures/w6_openalex_audit/base_works.json`、`tests/automated/test_w6_openalex_audit.py`、
  `tests/automated/test_openalex_client_v2.py`：纯离线 deterministic/adversarial coverage；
- 本报告与 `W6_BENCHMARK_AND_BOUNDARY_AWARE.md`：真实 post-freeze chronology 与 evidence。
